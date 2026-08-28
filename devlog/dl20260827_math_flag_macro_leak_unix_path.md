# 2026-08-27 — `%{mklroot}` / `%{prefix}` leaking into math flags on the unix/deb path

## Purpose

Reported symptom was a cosmetic gfortran warning during a STRUMPACK build. The
warning turned out to be the visible half of a two-part macro-expansion defect
in `unix_builder`, whose other half baked literal `%{prefix}/lib` strings into
the RUNPATH of shipped libraries. This note records both halves, which packages
actually carry damage (fewer than the ones that are *exposed*), why the RPM path
is not affected, and one adjacent defect that this fix does **not** address.

Diagnosed on the Ubuntu 24.04 build host against the installed `debug`, `gcc`
and `mkl` flavor trees.

## Symptom as reported

```
tol.f.o
f951: Warning: Nonexistent include directory '%{mklroot}/include'
    [-Wmissing-include-dirs]
```

## The defect

`math_common` emits both of its flag strings with placeholders in them:

| line | string | placeholder |
|---|---|---|
| `math_common.py:372` | `-I%{mklroot}/include` | compile flags |
| `math_common.py:379` | `-I%{prefix}/gcc/lib/gcc/...` (macOS/llvm only) | compile flags |
| `math_common.py:275-276` | `-Wl,-rpath,%{mklroot}/lib...` | link line |
| `math_common.py:242,282,310,326` | `-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib` | link line |

`unix_builder.configure()` expanded exactly one of the four combinations —
`%{mklroot}` in `math_ldflags`:

```python
self.math_flags   = get_math_compile_flags(self.flavor, self.recipe)
self.math_ldflags = get_math_link_line(self.flavor, self.recipe)
mklroot = os.environ.get('MKLROOT', '/opt/intel/oneapi/mkl/latest')
self.math_ldflags = self.math_ldflags.replace('%{mklroot}', mklroot)
```

Both strings are then appended verbatim to the exported flags
(`unix_builder.py:229-232`), so two things leaked:

**Leak 1 — `-I%{mklroot}/include` into CFLAGS/CXXFLAGS/FCFLAGS.** This is the
reported warning. It is *cosmetic only*: `build_common.setup_environment()`
already prepends `${MKLROOT}/include` to `CPATH` for any flavor whose name
contains `mkl` (`build_common.py:960-964`), so the compiler found the MKL
headers anyway. Nothing was miscompiled.

**Leak 2 — `-Wl,-rpath,%{prefix}/lib` into LDFLAGS.** This one reached shipped
artifacts. `ld` stores the rpath string verbatim, so the literal seven-character
macro ends up in the ELF RUNPATH:

```
$ readelf -d /opt/scls/mkl/lib/libmumps_common.so | grep RUNPATH
  [/opt/scls/mkl/lib:/opt/intel/.../lib/intel64:/opt/intel/.../lib:%{prefix}/lib]
```

The matching `-L%{prefix}/lib -lscalapack` did not break any link, because
`setup_environment()` also puts `{prefix}/lib` on `LIBRARY_PATH`
(`build_common.py:951`) — so `-lscalapack` resolved regardless. That is why this
went unnoticed: every symptom was masked by an environment variable set for
other reasons.

## Scope: deb + macOS only, not RPM

`DebBuilder` subclasses `UnixBuilder` (`deb_builder.py:210`), and the macOS
builder *is* `unix_builder`. So the defect covers the Ubuntu/deb path and the
macOS path.

The RPM path is clean, for two separate reasons:

1. `rpm_builder.py:1349-1350` expands `%{mklroot}` in **both** strings, so
   Leak 1 cannot occur. Confirmed in a generated spec:
   `export FCFLAGS="... -I/opt/intel/oneapi/mkl/latest/include -fopenmp -m64"`.
2. `%{prefix}` is deliberately left unexpanded in the spec, because it is a
   genuine RPM macro — `default.spec.j2:5` emits `%define prefix {{ prefix }}`,
   which renders as e.g. `%define prefix /opt/scls/mkl`. rpmbuild expands it at
   parse time, exactly as it does for the `export PATH=%{prefix}/bin:$PATH` and
   `PKG_CONFIG_PATH="%{prefix}/lib/pkgconfig..."` lines sitting three lines away
   in the same `%build` block.

Not independently verified: this host has no `rpmspec`/`rpmbuild`, so the
expansion in (2) is argued from the `%define` plus the known-good behaviour of
the neighbouring PATH lines, not demonstrated. Anyone on a RedHat host can
settle it in one command:

```
rpmspec -P rpmbuild/SPECS/scls-mkl-mumps.spec | grep 'export LDFLAGS'
```

Expected: `-Wl,-rpath,/opt/scls/mkl/lib -L/opt/scls/mkl/lib ...` with no macro.

## Exposure is much wider than damage

Nineteen recipes declare a truthy `features.math`; eighteen of them would leak a
macro under the old code on the `gcc` and/or `mkl` flavors (`suitesparse` is the
exception). Only **three** carry a literal in a shipped RUNPATH: `mumps`,
`petsc`, `slepc`.

The difference is build-system, not recipe: cmake manages RPATH itself and
rewrote or dropped the bogus entry at install time, whereas mumps (hand-written
makefiles) and petsc/slepc (custom configure) pass `LDFLAGS` straight to the
link. Do not use "declares math" as the rebuild criterion — scan the artifacts.

The `debug` flavor is clean for Leak 2 by construction: the reference-BLAS
branch (`math_common.py:340-353`) appends a bare `-lscalapack` and never emits
`%{prefix}` at all. Only the MKL branch (line 282) and the OpenBLAS branch
(lines 310, 326) do.

## Damage inventory

Full ELF scan of `/opt/scls/{debug,gcc,mkl}` (all files, executables included,
deduped by realpath because `lib -> lib64`):

| flavor | file | bad RUNPATH entry | cause |
|---|---|---|---|
| gcc, mkl | `libmumps_common.so`, `libdmumps.so`, `libsmumps.so` | `%{prefix}/lib` | this bug |
| gcc, mkl | `libpetsc.so.3.25.4` | `%{prefix}/lib` **and** `/home/christian/scls/work/build/petsc-3.25.4/%{prefix}/lib` | this bug |
| gcc, mkl | `libslepc.so.3.25.1` | same two entries | this bug |
| debug, gcc, mkl | `libstrumpack.so.8.0.0` | `lib` (relative) | **not** this bug — see below |
| debug, gcc, mkl | `x86_64-linux-gnu-test-static-link` (libunwind) | `/home/christian/.../libunwind-1.8.3/src/.libs` | pre-existing, unrelated |

**Severity of the `%{prefix}/lib` entries: inert.** They are nonexistent
absolute paths, which the loader skips, and the correct
`/opt/scls/<flavor>/lib` is already the first entry. The petsc build-tree entry
is likewise a path that does not exist post-install. This is a correctness and
audit-hygiene problem, not a runtime failure — nothing is currently mis-resolving
because of it.

## Fix

`unix_builder.py` now expands both macros in both strings:

```python
mklroot = os.environ.get('MKLROOT', '/opt/intel/oneapi/mkl/latest')
for macro, value in (('%{mklroot}', mklroot), ('%{prefix}', str(self.prefix))):
    self.math_flags   = self.math_flags.replace(macro, value)
    self.math_ldflags = self.math_ldflags.replace(macro, value)
```

`self.prefix` is set in `__init__` (`unix_builder.py:93`), well before
`configure()` runs, so the value is available.

## Verification

Instantiated `UnixBuilder(pkg, 'mkl')` in-process for strumpack, mumps, petsc
and scalapack and expanded the real recipe/flavor inputs through the new logic:
zero residual `%{...}` tokens, `-I/opt/intel/oneapi/mkl/latest/include` on the
compile side, `-Wl,-rpath,/opt/scls/mkl/lib` on the link side.

**This is not a build.** It exercises the substitution against real inputs; it
does not prove the flags reach the compiler correctly or that the resulting
RUNPATH is clean. That requires a rebuild — see below.

## Rebuild list

Six builds, all on the deb path:

| package | flavors | why |
|---|---|---|
| `mumps` | gcc, mkl | literal `%{prefix}/lib` in RUNPATH |
| `petsc` | gcc, mkl | literal `%{prefix}/lib` ×2 in RUNPATH |
| `slepc` | gcc, mkl | literal `%{prefix}/lib` ×2 in RUNPATH |

`debug` needs nothing (reference-BLAS branch never emitted the macro). No RPM
rebuild is required. petsc must precede slepc; mumps is independent.

Post-rebuild acceptance check:

```
readelf -d /opt/scls/<flavor>/lib/libmumps_common.so | grep RUNPATH   # no '%{'
```

## What this fix does NOT address

`libstrumpack.so.8.0.0` carries a **relative** RUNPATH entry `lib` on all three
flavors — including `debug`, whose math link line contains no `%{prefix}`
whatsoever. That rules out the macro leak as its cause. A relative RUNPATH entry
is resolved against the process's current working directory, so unlike the inert
`%{prefix}/lib` entries this one has real (if minor) runtime and trust
implications.

Leading hypothesis, **unconfirmed**: the recipe passes
`-DCMAKE_INSTALL_LIBDIR=lib` (`recipes/strumpack.yaml:37`) and upstream sets
`INSTALL_RPATH` from the relative `CMAKE_INSTALL_LIBDIR` rather than
`CMAKE_INSTALL_FULL_LIBDIR`. Not verified: the source tarball is not in
`work/sources/` (only `strumpack_bpack_inttype.patch` is) and the build tree has
been cleaned, so neither upstream's CMakeLists nor the generated `link.txt` was
available to read. Rebuilding strumpack will **not** clear this entry.

## Open questions

1. **Confirm the strumpack `lib` entry's origin** — fetch the 8.0.0 tarball and
   `grep -n 'INSTALL_RPATH\|INSTALL_LIBDIR' CMakeLists.txt`. If the hypothesis
   holds, the fix is `-DCMAKE_INSTALL_RPATH=%{prefix}/lib` in the recipe, or
   dropping `-DCMAKE_INSTALL_LIBDIR=lib` in favour of an absolute libdir.
2. **Should the placeholders be expanded at the source instead?**
   `math_common` is the only producer of these macros and every consumer
   (`rpm_builder`, `unix_builder`) has to remember to expand them, with the RPM
   consumer deliberately expanding only one of the two. Having
   `get_math_*_flags()` take the prefix and mklroot as arguments would make the
   whole class of bug unrepresentable, at the cost of the RPM path losing its
   ability to defer `%{prefix}` to rpmbuild. Worth weighing, not obviously right.
3. **macOS exposure is untested.** The macOS path runs the same `unix_builder`
   code and `math_common.py:379` puts `%{prefix}` into the *compile* flags for
   llvm/macOS, which the old code never expanded either. No macOS host was
   available; nobody has checked whether an installed macOS stack carries
   literal `%{prefix}` in its install names or rpaths.
