# Building a private libhsl for Ipopt

HSL's linear solvers are proprietary (STFC HSL license). SCLS ships no HSL source or
binary and no package that depends on HSL; see the HSL section of
[`LICENSE_POLICY.md`](LICENSE_POLICY.md). What SCLS provides is build tooling: you supply
the tarballs you are licensed to use, SCLS builds one shared library from them against the
stack's own METIS and BLAS/LAPACK, and the stack's unchanged Ipopt loads it at runtime
(`linear_solver ma27|ma57|ma77|ma86|ma97`).

## Tarballs to provide

Obtain them from the STFC licensing portal (<https://licences.stfc.ac.uk>; the Ipopt
bundle is listed on <https://www.hsl.rl.ac.uk/ipopt/>). Keep the files **exactly as
downloaded** — original names, unmodified — in one directory, by default `tmp/HSL/` under
the SCLS checkout (git-ignored), or anywhere else passed with `--sources DIR`.

| Tarball | Status | What it is used for |
|---|---|---|
| `coinhsl-2024.05.15.tar.gz` | **required** | Coin-HSL, the full STFC bundle for Ipopt: MA27, MA28, MA57, MC19, HSL_MA77, HSL_MA86, HSL_MA97, HSL_MC68 and the METIS 5 adapter. This is the base of the build. |
| `hsl_ma77-<version>.tar.gz` | optional | Used **only if newer** than the HSL_MA77 inside Coin-HSL (6.4.0). Today 6.5.0 is newer and is used; it is also what the refactorization test requires. |
| `hsl_ma86-<version>.tar.gz` | optional | Same rule, against Coin-HSL's 1.7.4. Equal today, so it is ignored. |
| `hsl_ma97-<version>.tar.gz` | optional | Same rule, against Coin-HSL's 2.8.1. Equal today, so it is ignored. |

Notes:
- It must be the **full** Coin-HSL, not "Coin-HSL Archive" (MA27/MA28/MC19 only). The
  Archive tarball fails the build with a message about an unpinned release.
- Exactly one `coinhsl-*.tar.gz` and at most one tarball per optional package may be present.
- A standalone override combines two HSL distributions you hold into one build: the solver's
  own source files are taken from the newer release, everything else from Coin-HSL. It is
  applied only after the assembler has verified that the two releases agree on every C
  interface, header, and shared dependency unit; anything else stops the build. The original
  tarballs are never modified. Whether combining releases is within your license is your call;
  `--no-overrides` builds Coin-HSL exactly as shipped.
- The build is pinned to Coin-HSL **2024.05.15**. A newer Coin-HSL release stops the build
  until its component versions have been reviewed and added to the pin table in
  `scripts/hsl/assemble_sources.sh`.

## Commands

Prerequisites: the flavor's `metis` installed in the stack prefix, CMake (the stack's own
is used when present), the flavor's compilers.

```bash
./scls build hsl [--sources DIR]    # build and check; stage the result, install nothing
./scls install hsl                  # install the staged build after three questions
```

As with every other package, `build` only builds. It assembles the sources outside the SCLS
work tree, builds `libcoinhsl.so` (`.dylib` on macOS) with a `libhsl.so` / `libhsl.dylib`
symlink — the name Ipopt looks for — and runs these checks before staging: every symbol
Ipopt's loader resolves is present; no METIS is compiled in (the stack's `libmetis` is
linked); every dependency resolves to the stack (METIS, OpenBLAS / reference LAPACK / the
flavor's MKL layer); a dlopen smoke test; an MA77 factor-and-solve test (its refactorization
part runs only with HSL_MA77 >= 6.5.0); on MKL flavors `scripts/check_mkl_linkage.sh`. The
checked result is staged, owner-only, under `$TMPDIR` (or `/tmp`) as
`scls-hsl-<uid>/<flavor>/`. The scratch tree holding HSL source is removed at exit, including
on errors and interrupts, unless `--keep-work`.

`install` takes the staged build and asks three questions (flags for scripted use):

1. **Install type** — `local`: `~/.local/scls-hsl/<flavor>`, owner-only (0700/0600); Ipopt
   needs `hsllib <full path>`. `global`: the stack prefix `/opt/scls/<flavor>`, readable by
   every user of the machine, owned by no RPM/DEB package, published with `sudo install` (only the
   file copies run as root); Ipopt finds it with no option. `--local` / `--global`.
2. **License type** — `academic` (HSL Academic Licence: personal, non-commercial use by you
   alone; the software and its use may not be shared with anyone, including colleagues at
   your institution) or `commercial` (an agreement with STFC whose terms you hold).
   `--license academic|commercial`. A global install under an academic license is permitted
   only if you are the sole user of the machine; `install` asks you to confirm this
   (`--sole-user`) and is refused otherwise.
3. **Acceptance** — the license files from your tarballs are printed (Coin-HSL's own is a
   pointer to the agreement you accepted on the STFC portal), followed by what you confirm for
   the chosen license and install type; type `yes` (`--accept-license`). SCLS grants no rights
   and distributes nothing.

Install type, license type, who accepted, when, from which host, and the checksums of the
license texts shown are recorded in `<prefix>/share/hsl/build-info.yaml`. The staged build is
deleted once the install has succeeded.

With GNU Fortran the fixed-form (`.f`) sources are compiled with `-std=legacy`. Those Fortran 77
routines use arithmetic `IF` and labelled `DO` terminations, which gfortran otherwise reports as
"Fortran 2018 deleted feature" on every use; no `-Wno-` switch covers that message, and the
sources are your unmodified tarballs. `-std=legacy` is gfortran's default dialect without those
messages; for sources that already compile, it generates the same code. The `.f90` solvers keep the default diagnostics. The flag
is recorded as `fixed_form_fflags` in `build-info.yaml`.

## Using it from Ipopt

Local install — give the full path, in `ipopt.opt` or via the API:

```
hsllib /home/<you>/.local/scls-hsl/<flavor>/lib/libhsl.so
linear_solver ma97
```

Global install — nothing to configure: Ipopt's default `hsllib` (`libhsl.so` /
`libhsl.dylib`) is found through `libipopt`'s RUNPATH.

```
linear_solver ma97
```

`LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH` are not used in SCLS and not needed here.

An installed HSL library never changes how Ipopt is built: the Ipopt recipe passes
`--without-hsl`, which disables Ipopt's build-time HSL probe, and the HSL install ships no
`coinhsl.pc` or headers for that probe to find. Ipopt reaches HSL only through its runtime
loader, so the packaged Ipopt is identical on every host. There is deliberately no option to
link HSL into `libipopt`: that would make Ipopt itself HSL-derived and unpackageable, for no
gain beyond changing Ipopt's default `linear_solver` (set it in `ipopt.opt` instead).

## What gets installed

```
<prefix>/lib/libcoinhsl.so            (libcoinhsl.dylib on macOS)
<prefix>/lib/libhsl.so -> libcoinhsl.so
<prefix>/share/doc/hsl/LICENCES/LICENCE.<package>-<version>   one per tarball used
<prefix>/share/doc/hsl/PROVENANCE.txt   inputs, SHA-256, files replaced by overrides
<prefix>/share/hsl/build-info.yaml      flavor, compilers, flags, DT_NEEDED, script hashes
<prefix>/share/scls/registry/hsl.yaml   global install only: registry entry (see below)
```

## Listing and removing a global install

A global install writes a registry entry, `share/scls/registry/hsl.yaml`, so `./scls list`
shows `hsl` next to the stack's packages. The entry is a record of this private install, not a
package: there is still no recipe, spec, RPM, DEB or PKG, and nothing in the build order. Its
compile and link flags are empty, so nothing links HSL through the registry. A local install
(`~/.local/scls-hsl/<flavor>`) lies outside the stack prefix and gets no entry; remove it by
deleting that directory.

To remove a global install, from the SCLS checkout (the file list is `files/hsl.txt`):

```bash
python python/unix_builder.py --uninstall -p hsl -f <flavor>
```

This removes the library, the `libhsl` symlink, the license copies, the provenance file, the
acceptance record and the registry entry, using `sudo` when the prefix is not writable. Do not
add `--with-deps`: that would also try to remove the stack packages it depends on (METIS,
OpenBLAS or LAPACK, GCC) wherever no other package needs them.

The entry lists the stack packages the library resolves against (`metis`, and where they are
stack packages, `openblas` or `lapack`, and `gcc`), taken from the `needed:` record. That
protects them only from `unix_builder.py --uninstall`, which refuses to remove a package
another entry depends on. On RPM and DEB hosts the package manager does not read the registry:
`dnf remove` or `apt-get remove` of `scls-<flavor>-metis` will go ahead and leave the private
library unable to load. Remove HSL first, or rebuild it afterwards.

An install made before the registry entry existed has no entry; `./scls build hsl` followed by
a global `./scls install hsl` adds it.

Never share the library, the assembled sources or the tarballs beyond what your own HSL
license permits. Only the SCLS scripts are public.
