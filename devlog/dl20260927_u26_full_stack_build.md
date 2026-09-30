# Devlog 2026-09-27 — U26 (Ubuntu 26.04) first full-stack build: debug, gcc, mkl

**Date:** 2026-09-26 → 2026-09-27
**Topic:** bring up the new U26 build host and build the whole stack for `debug`, `gcc`, `mkl` (`/build-stack` rules, per-package driver)
**AIs involved:** Claude Opus (U26 host session); U24 build session (peer, over Remote Control); Fable subagent, Codex gpt-6-astra and Grok 4.7 for the lapack fix (`dl20260926_u26_lapack_gfortran15_zlaqr5.md`)
**Flavor / Host:** U26 = Ubuntu 26.04.1 VirtualBox VM, GCC/gfortran 15.2.0, 8 cores / 15 GB after resize, DEB
**Verification:** built and installed on U26: every package in `build_order.py --names-only` installed with `dpkg-query` version == recipe version-release (debug 37/37, gcc 37/37, mkl 36/36); meta-packages `scls-{debug,gcc,mkl}` 2026-1 installed; `scripts/check_mkl_linkage.sh --flavor mkl` PASS (491 ELF files, `libmkl_gnu_thread` only); lapackpp full test suite passes on all three flavors. Nothing staged or published.

## Summary

First build of U26. Three repo fixes landed during the run (all on `origin/devel`): openmpi
5.0.11-2 `--with-prrte=internal` (found and fixed on U24, applied here), lapack 3.12.1-2
`-ffp-contract=off` (found here: gfortran 15.2 wrong code in `zlaqr5`), and the U26 host column plus
the new `/build-fix-jury` skill. Host-only changes needed no repo edit.

## Timeline (wall clock, host CPUs shared with the U24 VM until 2026-09-26 ~23:40)

- debug: 02:07 → 17:56, including ~6.5 h idle after the vtk OOM stop (below) and the lapack diagnosis.
- gcc: 17:57 → 01:53 (vtk ~3.3 h at `-j4`).
- mkl: 01:54 → 06:14.

## Host findings (U26 only, no repo change)

- **sudo-rs.** 26.04's default `sudo` is sudo-rs, which ignores `verifypw=never`: after
  `grant_pkg_sudo.sh --scope all`, `sudo -n true` and `sudo -n apt-get` pass but `sudo -n -v` fails,
  so `scls build all`'s keepalive cannot work. Classic `/usr/bin/sudo.ws` passes. Worked around with a
  per-package build+install driver (git-ignored `tmp/u26_build_loop.sh`). Recorded in
  `.claude/commands/grant-pkg-sudo.md`.
- **curl** is not in a 26.04 minimal install; `unix_builder.check_host_tools` requires it.
- **vtk OOM at `make -j8`** (debug, 15 GB): the harness reaped the build. `get_parallel_jobs()` is
  `multiprocessing.cpu_count()`, which Python ≥ 3.13 overrides with `PYTHON_CPU_COUNT`; the driver runs
  vtk, petsc, slate, strumpack and butterflypack at 4 jobs. No builder change.
- **Codex/Grok sandbox works at `kernel.apparmor_restrict_unprivileged_userns=1`** because 26.04 ships
  the `bwrap-userns-restrict` AppArmor profile (apparmor 5.0.2, bubblewrap 0.11.1); U24 (apparmor
  4.0.1, no such profile) needed the sysctl relaxed.
- System build deps from `packaging/system_packages.yaml` all resolved on 26.04, including the
  `t64` renames (`libssl3`, `librdmacm1` are versioned Provides of `*t64`). No mapping edits.
- Prefix sizes after the run: `/opt/scls/debug` 5.7 G (debug info), `gcc` 963 M, `mkl` 920 M.

## Open — needs Christian

1. `scls-<F>-lapack` does not Depend on `scls-<F>-blas` (Codex P1, pre-existing; see the lapack devlog).
2. lapack binary packages ship no LAPACK license notice (pre-existing).
3. Optional GCC bug report for the `zlaqr5` SLP wrong code (standalone kernel in U26 scratch).
4. DEB staging for U26 is not implemented (`scripts/stage_to_belfem.sh` knows only U24), and
   `deb_builder`'s `scls-release` hard-codes `Suites: noble`; .deb versions carry no distro tag, so
   U24 and U26 builds of the same recipe would collide in one pool.
