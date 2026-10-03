# Building a private libhsl for Ipopt

HSL's linear solvers are proprietary (STFC HSL licence). SCLS ships no HSL source or
binary and no package that depends on HSL; see the HSL section of
[`LICENSE_POLICY.md`](LICENSE_POLICY.md). What SCLS provides is build tooling: you supply
the tarballs you are licensed for, SCLS builds one shared library from them against the
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
| `hsl_ma77-<version>.tar.gz` | optional | Used **only if newer** than the HSL_MA77 inside Coin-HSL (6.4.0). Today 6.5.0 is newer and is taken; it is also what the refactorization test requires. |
| `hsl_ma86-<version>.tar.gz` | optional | Same rule, against Coin-HSL's 1.7.4. Equal today → ignored. |
| `hsl_ma97-<version>.tar.gz` | optional | Same rule, against Coin-HSL's 2.8.1. Equal today → ignored. |
| `ma57-*`, `hsl_ma57-*` | ignored | Standalone MA57 calls the METIS 4 interface; Coin-HSL's copy uses the METIS 5 adapter. `hsl_ma57` is a different package line. |
| `hsl_mc68-*` | ignored | HSL_MC68 is already inside Coin-HSL (`common/deps90.f90`). |
| `hsl-galahad*` | ignored | The GALAHAD HSL subset; superseded by Coin-HSL for this purpose. |

Notes:
- It must be the **full** Coin-HSL, not "Coin-HSL Archive" (MA27/MA28/MC19 only). The
  Archive tarball fails the build with a message about an unpinned release.
- Exactly one `coinhsl-*.tar.gz` and at most one tarball per optional package may be present.
- A standalone override combines two HSL distributions you hold into one build: the solver's
  own source files are taken from the newer release, everything else from Coin-HSL. It is
  applied only after the assembler has verified that the two releases agree on every C
  interface, header and shared dependency unit; anything else stops the build. The original
  tarballs are never modified. Whether combining releases is within your licence is your call;
  `--no-overrides` builds Coin-HSL exactly as shipped.
- The build is pinned to Coin-HSL **2024.05.15**. A newer Coin-HSL release stops the build
  until its component versions have been reviewed and added to the pin table in
  `scripts/hsl/assemble_sources.sh`.

## Commands

Prerequisites: the flavor's `metis` installed in the stack prefix, CMake (the stack's own
is used when present), the flavor's compilers.

```bash
./scls build hsl [--sources DIR]      # per-user install: ~/.local/scls-hsl/<flavor>
./scls install hsl [--sources DIR]    # stack prefix /opt/scls/<flavor>, after licence acceptance
```

Both assemble the sources outside the SCLS work tree, build `libcoinhsl.so` (`.dylib` on
macOS) with a `libhsl.so` / `libhsl.dylib` symlink — the name Ipopt looks for — and run
these checks on the staged library **before** anything is installed: every symbol Ipopt's
loader resolves is present; no METIS is compiled in (the stack's `libmetis` is linked);
every dependency resolves to the stack (METIS, OpenBLAS / reference LAPACK / the flavor's
MKL layer); a dlopen smoke test; an MA77 factor-and-solve test (its refactorization part
runs only with HSL_MA77 >= 6.5.0); on MKL flavors `scripts/check_mkl_linkage.sh`. The scratch
directory, which holds HSL source, is removed at exit, including on errors and interrupts,
unless `--keep-work`.

`./scls build hsl` installs owner-only (directories 0700, files 0600): under the HSL
Academic Licence the library is for your personal use and may not be shared, including with
colleagues at your own institution.

`./scls install hsl` (or any `--prefix` outside your home directory) is a shared install. It
prints the licence files from your tarballs, states the Academic Licence's personal-use and
no-sharing terms in SCLS's own words, and requires you to type `yes` (or pass
`--accept-licence` for scripted use), confirming that you have read your licence agreement
and that it covers use of the library at that location by everyone who can use it. An
academic licence does not; a single-user machine, or a licence whose terms allow shared use,
can. SCLS grants no rights and distributes nothing. The files are published with `sudo
install`; the build itself never runs as root. Who accepted, when, from which host, and the
checksums of the licence texts shown are recorded in `share/hsl/build-info.yaml`.

## Using it from Ipopt

Per-user install — give the full path, in `ipopt.opt` or via the API:

```
hsllib /home/<you>/.local/scls-hsl/<flavor>/lib/libhsl.so
linear_solver ma97
```

Stack-prefix install — nothing to configure: Ipopt's default `hsllib` (`libhsl.so` /
`libhsl.dylib`) is found through `libipopt`'s RUNPATH.

```
linear_solver ma97
```

`LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH` are not used in SCLS and not needed here.

## What gets installed

```
<prefix>/lib/libcoinhsl.so            (libcoinhsl.dylib on macOS)
<prefix>/lib/libhsl.so -> libcoinhsl.so
<prefix>/share/doc/hsl/LICENCES/LICENCE.<package>-<version>   one per tarball used
<prefix>/share/doc/hsl/PROVENANCE.txt   inputs, SHA-256, files replaced by overrides
<prefix>/share/hsl/build-info.yaml      flavor, compilers, flags, DT_NEEDED, script hashes
```

Never share the library, the assembled sources or the tarballs beyond what your own HSL
licence permits. Only the SCLS scripts are public.
