# SCLS MKL ABI Policy

## Why this document exists

SCLS's MKL-class flavors — every flavor whose `flavors/*.yaml` declares
`math.linalg: mkl` (currently `mkl`, `intel`, `gcc-mkl-cuda`) — link every
consumer binary against Intel oneAPI MKL using its installed shared
libraries. Linux records that linkage by copying the MKL library's
`DT_SONAME` (e.g. `libmkl_core.so.3`) into the consumer's `DT_NEEDED`
entries. When Intel bumps an MKL major SONAME — which is the standard
Linux signal for "ABI compatibility broken, rebuild required" — every
previously-built consumer binary stops resolving against the new MKL, even
though the install path, the unversioned symlinks, and SCLS's own rpath
are all unchanged.

This document is the playbook for detecting, fixing, and *not* mis-fixing
that situation.

## What the pitfall looks like

Worked example (oneAPI 2025.x on EL9 build hosts):

```
$ ldd /opt/scls/mkl/lib/libspqr.so
        ...
        libmkl_gf_lp64.so.2 => not found
        libmkl_gnu_thread.so.2 => not found
        libmkl_core.so.2 => not found
```

The host's installed MKL ships `libmkl_*.so.3`, not `.so.2`. Both the SCLS
binary's rpath and the host's MKL install are correct — the dynamic linker
is simply refusing to bind a `NEEDED libmkl_*.so.2` entry to a file whose
SONAME is `.so.3`, which is exactly what SONAME versioning is designed to
do.

The RPM had installed cleanly because the only MKL-related runtime deps
SCLS emits are unversioned: `Requires: intel-oneapi-mkl,
intel-oneapi-mkl-devel` (see `python/rpm_builder.py:1615`), and
`AutoReqProv: no` is set on every package and subpackage in the SPEC
template (`templates/default.spec.j2:54,71`). RPM's automatic SONAME
capture is therefore intentionally suppressed across the board, so the
runtime `ldd` error is the first signal a host can give. The next section
explains why suppression is deliberate and what mitigation SCLS uses
instead.

## Why the obvious "fixes" do not work

### Linking against `libmkl_core.so` (the unversioned symlink) instead of `libmkl_core.so.3`

Intuitively it looks like this should produce a version-less `DT_NEEDED`
and therefore future-proof against a future `.so.4` bump. It does not. The
linker reads the SONAME out of the resolved library's ELF header and
writes *that string* into the consumer's `DT_NEEDED`, regardless of which
filename you fed `-l` or `-L`. `-lmkl_core` (which is what SCLS already
emits, via `python/math_common.py:get_mkl_serial_link_line`) produces
`NEEDED libmkl_core.so.3` today; rebuilt against a future `.so.4` MKL it
would produce `NEEDED libmkl_core.so.4`. The version is unavoidable as
long as the linked library has a versioned SONAME, which Intel's does.

### `patchelf --replace-needed libmkl_core.so.3 libmkl_core.so`

Strips the version and pairs with a compat symlink at the rpath
directory. This silently binds the consumer to whatever MKL major is
installed at runtime, which is exactly what SONAME versioning exists to
prevent. When Intel changes ABI in a non-obvious way (struct size,
threading semantics, return convention), this produces subtle data
corruption rather than a clean load error. **Do not do this.**

### Host-side compatibility symlinks (`libmkl_core.so.2 -> libmkl_core.so.3`)

Same failure mode as patchelf — works exactly until it doesn't, and the
failure is harder to diagnose than a missing-file error. Do not do this.

### Repackaging existing RPMs to inject a corrected `Requires:`

(Contrast with `REPACKAGE_ENVIRONMENT_DEP.md`, where in-place metadata
rewriting *is* the right answer — because the payload was already
correct.) Here, the payload binaries themselves embed the wrong SONAME in
their `DT_NEEDED`. No metadata rewrite changes that. The only fix is a
true rebuild against the current MKL.

## What SCLS actually relies on

### The deliberate design: `AutoReqProv: no` + explicit deps only

The SPEC template (`templates/default.spec.j2:54,71`) sets `AutoReqProv:
no` on every package and subpackage. This is intentional and load-bearing:
RPM's automatic dependency generator scans installed binaries' `DT_NEEDED`
entries and emits `Requires:` lines for every shared library it finds.
Without suppression, an SCLS RPM whose binaries happened to link against
the host's `/usr/lib64/liblapack.so.3` (because some recipe's configure
auto-detected it) would advertise a runtime dep on the distro's LAPACK —
silently coupling SCLS to whatever the build host's `/usr/lib64` happened
to contain. The whole point of installing into `/opt/scls/<flavor>/` is to
deliver a self-contained stack whose deps are exactly what the recipes
declare; auto-Requires breaks that invariant by adding sneak-in deps that
no recipe ever asked for. The Debian builder reaches the same goal a
different way: `python/deb_builder.py` writes explicit `Depends:` into
`DEBIAN/control` and invokes `dpkg-deb --build` directly, bypassing
`dpkg-shlibdeps` entirely (`python/deb_builder.py:930`).

The consequence for MKL specifically: nothing in the current SCLS metadata
records the MKL major SONAME a consumer binary was linked against. RPM and
DEB resolution see only the unversioned `intel-oneapi-mkl` floor and
happily proceed. A SONAME mismatch surfaces at the first `ldd` or load
attempt, not at install time.

### The mitigation: rebuild on SONAME bump

Given the above, the policy is:

1. **The builders inject `intel-oneapi-mkl` + `intel-oneapi-mkl-devel`
   as runtime Requires for any recipe with `features.math` set**
   (`python/rpm_builder.py:1611`, `python/deb_builder.py:357`). Flavor
   YAMLs additionally list `intel-oneapi-mkl` under `rpm_requires` (the
   `-devel` companion appears in `rpm_build_requires`, not at runtime).
   All of these are unversioned — they force *some* MKL family member
   onto the host but do not pin a major version.
2. **SONAME bumps trigger a rebuild on the affected build host.**
   Historically rare — `.so.1` → `.so.2` around 2018, `.so.2` → `.so.3`
   around oneAPI 2025 — so the rebuild cadence is small. Old RPMs remain
   installable on hosts still pinned to the old MKL; the new RPMs ship
   alongside them in the repo.
3. **Build hosts are the source of truth** for which MKL major their RPMs
   embed in `DT_NEEDED`. Coordination across the build matrix happens at
   the rebuild step, not via metadata pinning.

### Optional enhancement: explicit MKL-only SONAME Requires

A future change could narrow the gap without re-enabling `AutoReqProv` for
everything (which would reintroduce the system-lib sneak-in problem). The
shape would be: at SPEC/control-file generation time, scan each consumer
binary's `DT_NEEDED` entries, filter to `libmkl_*\.so\.N`, and emit those
as explicit `Requires: libmkl_core.so.N()(64bit)` for RPM, and the
equivalent versioned `Depends:` line for DEB. The exact DEB dependency
shape (package name, virtual provides) needs verification against
Intel's apt repo metadata before any implementation lands — the RPM
side is well-defined because Intel's RPMs auto-Provide the SONAMEs.
Only MKL would be special-cased; the AutoReqProv invariant
for everything else would be preserved. This is not currently implemented;
the rebuild-on-bump mitigation above is what's in force.

## Detection playbook

### Identify SCLS binaries that reference a stale MKL major

```bash
flavor=mkl
find /opt/scls/${flavor} -type f 2>/dev/null | while read -r f; do
  readelf -d "$f" 2>/dev/null \
    | grep -Eo 'libmkl_[a-z0-9_]+\.so\.[0-9]+' \
    | sed "s|^|${f}: |"
done | sort -u
```

(`find` over the whole install tree, not just `lib/*` and `bin/*`, since
some packages install nested ELF files under `lib/openmpi/`, `lib/pmix/`,
`libexec/`, etc. `readelf` produces no output for non-ELF files, so no
explicit type check is needed.)

### Identify the SONAME the host's MKL provides

```bash
readelf -d ${MKLROOT}/lib/libmkl_core.so | grep SONAME
```

A mismatch between the two is the SONAME-bump scenario. `ldd <binary> |
grep 'not found'` is the runtime confirmation.

## Rebuild playbook

When the detection scan above finds binaries that reference a stale MKL
SONAME (or, going forward, if MKL-only metadata is added and a future RPM/
DEB install is blocked with a clean SONAME-mismatch error):

1. Identify which build host(s) saw the MKL upgrade. Typically only one
   OS target at a time — Intel's oneAPI repos roll out independently per
   distro family. The worked example above affected only the EL9 build
   host.
2. On that host, rebuild every MKL-flavor SCLS package whose recipe links
   MKL. `./scls build next` walks the dependency order; the registry at
   `${prefix}/share/scls/registry/` tracks completion.
3. Publish the new RPMs/DEBs to the SCLS repo. Old artifacts can stay —
   they remain installable on hosts still on the old MKL.
4. **Do not rebuild on the unaffected build hosts.** Their MKL hasn't
   changed; their artifacts still resolve correctly. Rebuilding the entire
   build matrix on every Intel-side bump is unnecessary churn.

## A second, unrelated hazard: `-lgomp` in `CMAKE_<LANG>_STANDARD_LIBRARIES`

This one is not a SONAME problem, but it lives in the same link line and is
easy to mistake for one, so it is recorded here.

`build_common.get_cmake_args` builds `CMAKE_C_STANDARD_LIBRARIES` and
`CMAKE_CXX_STANDARD_LIBRARIES` from `math_common.get_mkl_serial_link_line`,
which ends in the OpenMP runtime (`-lgomp` on GNU flavors, `-liomp5` on
Intel). On non-MKL flavors the same variable is just `-lm`.

**Effect:** when that variable contains `-lgomp`, any CMake `try_compile`
that links an OpenMP imported target (`OpenMP::OpenMP_CXX`) links with *no
OpenMP runtime at all* and fails on undefined `GOMP_*` symbols. The value is
not forwarded into the try-compile project, but its presence drops the
imported target's runtime from the probe link, and nothing replaces it.
Measured with cmake 4.3.2 against upstream STRUMPACK's own probe source:

| `CMAKE_CXX_STANDARD_LIBRARIES` | probe | probe link line |
|---|---|---|
| unset / `-lm` / `-lm -ldl` / a bogus `-l<name>` | passes | ends with libgomp |
| `-lmkl_gf_lp64 -lmkl_core -lpthread -lm -ldl` (no `-lgomp`) | passes | ends with libgomp |
| `-lgomp` / `-lm -lgomp` / the full MKL line | **fails** | no OpenMP runtime |

**Why it is nasty:** the *outer* library link is unaffected, so the package
still builds and still gets `NEEDED libgomp.so.1`. Only the configure-time
feature probes lie. Upstream then compiles out whatever the probe gated,
silently, and the loss shows up as missing parallelism rather than as a
build or install failure.

**Worked example:** `scls-mkl-strumpack-8.0.0-1` shipped on el9, el10 and
amzn2023 with `STRUMPACK_USE_OPENMP_TASKLOOP` and
`STRUMPACK_USE_OPENMP_TASK_DEPEND` compiled out, while the gcc and debug
builds of the same recipe had both. See
`devlog/dl20260817_strumpack_openmp_tasking.md`.

**Exposure:** any cmake package on an mkl or intel flavor whose configure
runs a `try_compile` against an OpenMP imported target. Checked clean so
far: `sundials`, `superlu_dist` (installed config headers byte-identical
between the published gcc and mkl RPMs). Unchecked: `butterflypack`,
`gklib`, `metis`, `parmetis`, `slate`, `vtk`, `zfp`.

**Detection:** diff the installed config header of a cmake package between
its gcc and mkl RPMs. Any feature `#undef` on mkl but `#define` on gcc is a
candidate — the compiler is identical, so the flavor cannot legitimately
change a compiler-capability probe.

**Mitigations, in preference order:**

1. Remove the OpenMP runtime from `CMAKE_<LANG>_STANDARD_LIBRARIES` and let
   `-fopenmp` / `-qopenmp` in `CFLAGS`/`CXXFLAGS` supply it. Fixes every
   affected package at once, but changes the link line of the whole mkl and
   intel stack, so it needs a full rebuild plus a `readelf -d` check that
   packages with `features.math` and `features.openmp: false` have not lost
   their OpenMP `NEEDED` entry. **Not applied — open decision.**
2. Pin the probe result per recipe, as `recipes/strumpack.yaml` does with
   `-DSTRUMPACK_USE_OPENMP_TASKLOOP=TRUE`. Deterministic and cheap, but
   per-package and only viable where the capability is genuinely present.

## Source-of-truth references

- `python/math_common.py:get_mkl_interface_lib` — picks `mkl_gf_*` vs
  `mkl_intel_*` per the active flavor's compiler. Mixing the two within
  one flavor causes a *different* MKL ABI failure (segfaults in complex-
  returning BLAS routines under gfortran); see the docstring there.
- `python/math_common.py:get_mkl_serial_link_line` /
  `get_mkl_mpi_link_line` — canonical MKL link lines. Already emit
  unversioned `-l` names; this is correct but, per above, does *not* make
  the consumer's `DT_NEEDED` version-less.
- `python/rpm_builder.py:get_intel_oneapi_setup` — MKL build-time env
  (`MKLROOT`, `LD_LIBRARY_PATH`, `LIBRARY_PATH`, `CPATH`).
- `python/build_common.py:get_cmake_args` — emits
  `CMAKE_<LANG>_STANDARD_LIBRARIES`; see the `-lgomp` hazard above.
- `python/math_common.py:compiler_family` — single source of truth for the
  compiler family, and therefore for the OpenMP runtime, MKL threading
  layer and MKL interface library. Everything else derives from it.
