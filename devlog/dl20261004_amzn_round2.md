# AMZN round 2: linking fixes, spral + ipopt, HSL script test

**Date:** 2026-10-04
**Host:** AMZN build host (Amazon Linux 2023, kernel 6.1, GCC 11.5.0, 8 cores), flavors gcc, mkl
(AMZN has no debug column)
**Commit:** built from `bde7be5` (recipe state `21f141e`). Instructions:
`todo/round2_el10_amzn2023.md`. Reference hosts: `devlog/dl20261003_r9_round2.md`,
`devlog/dl20261004_r10_round2.md`.

## Result

Every round-2 package is built and installed on gcc and mkl, and every check in
`todo/round2_el10_amzn2023.md` §3 passes. AMZN holds the same nine NEVRAs per flavor as R9 and R10
(no lapack: debug only). No recipe, flavor, manifest, patch or `python/` change was made or needed.
Nothing is staged or uploaded.

| Package | NEVRA (`.amzn2023`) | Evidence on AMZN (gcc and mkl) |
|---|---|---|
| environment | 2026-3 | activate sets `OMP_CANCELLATION=TRUE`, leaves `OMP_PROC_BIND` unset |
| libunwind | 1.8.3-3 | no `libexec/libunwind`; no triplet-prefixed file |
| gperftools | 2.18.1-2 | `libprofiler.so`, `libtcmalloc.so` NEED `libunwind.so.8`; suite 48/48 (see below); `rpm -ql` 73 |
| hwloc | 2.14.0-2 | `bin/lstopo` under its plain name; no `bin/*-lstopo` |
| openmpi | 5.0.11-2 | `PRRTE: internal`; `bin/prte`; `libmpi.so.40`, `libprrte.so.3` |
| scotch | 7.0.15-2 | ZLIB, BZip2, LibLZMA found; NEEDs `libz.so.1`, `libbz2.so.1`, `liblzma.so.5`; Requires `zlib`, `bzip2-libs`, `xz-libs` |
| spral | 2025.09.18-1 | `Library hwloc found: YES`; meson test Ok 9, Fail 0; NEEDs `libmetis.so.0`, `libhwloc.so.15`; no CUDA |
| ipopt | 3.14.20-1 | `%check` passes incl. hs071 "running with linear solver spral", "Optimal Solution Found" |
| `scls-<F>` | 2026-2 | installed; Requires spral and ipopt |

- The triplet guard did not fire for any package (`_scls_triplet=` empty in all seven autotools
  build logs). `find /opt/scls/{gcc,mkl} -name 'x86_64-redhat-linux-*' -o -name
  'x86_64-amazon-linux-*'` returns nothing.
- **gperftools pprof skip, real test here:** the host has Perl `/usr/bin/pprof`
  (`pprof-2.9.1-1.amzn2023.0.3`), and configure still printed `checking for pprof... (cached) no`
  and "pprof tool not found. Will skip". Suite: TOTAL 48, PASS 48, FAIL 0, ERROR 0. None of
  `sampling_test`, `sampling_debug_test`, `profiler_unittest.sh`, `heap-profiler_unittest.sh`,
  `heap-profiler_debug_unittest.sh` occurs in either build log. Same result as R9 and R10.
- SPRAL multi-core run per flavor: `examples/hs071_cpp` from the Ipopt 3.14.20 source, built against
  the installed prefix after `source <prefix>/share/scls/activate`, `pkg-config --cflags --libs
  ipopt` plus `-Wl,-rpath,<prefix>/lib`, `linear_solver spral`, `OMP_NUM_THREADS=8`: "Optimal
  Solution Found" on gcc and mkl, no warnings.
- mkl: ipopt's configure finds MKL Pardiso (`checking for function pardiso_ in … -lmkl_gf_lp64
  -lmkl_gnu_thread -lmkl_core -lgomp … yes`). `libipopt.so` and `libspral.so` NEED
  `libmkl_gf_lp64.so.3`, `libmkl_gnu_thread.so.3`, `libmkl_core.so.3`, `libgomp.so.1`.
  `scripts/check_mkl_linkage.sh --flavor mkl --prefix /opt/scls/mkl`: PASS, 451 ELF files, one
  threading layer (`libmkl_gnu_thread`). MKL on this host: 2026.1.0-236.
- `scls-gcc` and `scls-mkl` were not installed on this host before; `./scls install _meta` installed
  2026-2 on both without problems.

## HSL script test (gcc flavor)

Christian's terms: academic licence, single user, local install, then uninstall.

- `./scls build hsl --sources /tmp` with the licensee's `coinhsl-2024.05.15` and `hsl_ma77-6.5.0`:
  exit 0 (all gates pass), "MA77 functional gate: PASS", 0 "Fortran 2018 deleted feature" lines; the
  work tree `/tmp/scls-hsl-<random>` with HSL source is gone afterwards.
- `./scls install hsl --local --licence academic --accept-licence`: `~/.local/scls-hsl/gcc`, mode
  0700, files 0600; licences, provenance and the acceptance record (`licence_type: academic`,
  `how: --accept-licence`) under `share/`.
- hs071 with `hsllib $HOME/.local/scls-hsl/gcc/lib/libhsl.so` and `linear_solver <s>`: "Optimal
  Solution Found" for ma27, ma57, ma77, ma86 and ma97.
- Uninstall: `rm -rf ~/.local/scls-hsl/gcc`. `find / -xdev \( -name 'libcoinhsl*' -o -name
  'libhsl.*' \)` finds nothing.
- Same small finding as R10: after the install, the stage parent `/tmp/scls-hsl-1001` remained as an
  empty directory. Removed by hand, not fixed.
- Nothing HSL was copied into the repo or any artifact. The two tarballs are still in `/tmp`, where
  Christian put them.

## Host notes (AMZN)

- Builder Python: the system `python3` has `jinja2` and `yaml`; no `python:` override was needed.
- meson and ninja: a venv's whole `bin/` (`~/python/bin`) was first on the login `PATH`. Only
  `meson` (1.12.1) and `ninja` are linked into `~/.local/bin`, and the builds ran with an explicit
  `PATH` without that venv (checked in the running builder's `/proc/<pid>/environ`).
- No `activate` variables (`SLEPC_DIR`, `CMAKE_PREFIX_PATH`, `MPI_HOME`, …) in the build shells, the
  AMZN lesson from 2026-09-25; `activate` was sourced only in the separate hs071 test shells.
- sudo: a persistent `NOPASSWD: ALL` rule (`sudo -n -l`); no keepalive needed.
- `zlib-devel`, `bzip2-devel`, `xz-devel` were already installed (AL2023 names resolve as on EL9).
- `flavor.conf` was set per section and restored with `git checkout flavor.conf`; not committed.

## Open

- **Not staged, not uploaded.** Christian handles staging.
- `/tmp/scls-hsl-<uid>` is left behind as an empty directory by `./scls install hsl` (also R10).
