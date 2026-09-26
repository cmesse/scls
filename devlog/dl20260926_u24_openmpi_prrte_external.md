# Devlog 2026-09-26 — U24 column: openmpi 5.0.11 halts on PRRTE going external

**Date:** 2026-09-26
**Topic:** `/update-build` of the 2026-09-22 campaign, U24 column (Ubuntu 24.04); root cause of the 2026-08 "intermittent" PRRTE drop
**AIs involved:** Claude (U24 build host, session scls-7b); peer session scls-b2 (U26 host) over the bridge
**Flavor / Host:** debug on the U24 build VM (Ubuntu 24.04, DEB)
**Verification:** 7 packages built and installed on U24/debug with installed version == recipe; openmpi failure diagnosed from `config.log` and the installed tree. The proposed fix is **not** applied or tested.

## Summary

The U24 debug run installed environment, cmake, ucx, blaspp, blaze, pmix and lapackpp, then halted
at openmpi 5.0.11. The recipe's `install.post` guard (added after the 2026-08-24 incident) fired:
PRRTE (`bin/prte`, `prterun`, `libprrte.so`) was missing from the staged tree. The guard did its job;
without it this would have shipped a `mpirun` that cannot launch ranks.

## Key Findings

- **Cause.** OpenMPI 5's `--with-prrte` defaults to auto: if an external PRRTE >= 3.0 compiles, it is
  used and the bundled copy is skipped. The installed openmpi 5.0.10-3 had put `prte.h`,
  `prte_version.h` and `libprrte.so.3.0.13` into `/opt/scls/debug`. The DEB/unix build environment
  exports `CPATH=<prefix>/include` (`python/build_common.py:1005`), so the `prte.h` probe compiles with
  no `-I` flag. `config.log`: `checking for prte.h... yes`, `checking if external PRRTE version is
  3.0.0 or greater... yes`, summary `PRRTE: external`.
- **This explains the 2026-08 "intermittent" failure** in
  `devlog/dl20260824_openmpi_prrte_and_sundials_ldpath.md`, which had no leading hypothesis left. That
  devlog's sequence (broken 15:41, correct 21:01, broken 01:11, correct 12:32) alternates in exactly
  the way this mechanism predicts. A build on top of a good install sees PRRTE, goes external, and
  ships without it. The next build, on top of that broken install, finds none and bundles PRRTE again.
  Load, `make -j` races and flex were never involved.
- **Why RPM hosts are unaffected.** R9, R10 and AMZN built 5.0.11 on top of an installed 5.0.10 and
  passed the same guard. rpmbuild does not run through the `CPATH` environment. Inferred from the
  code path, not re-tested on an RPM host.
- **Host gaps found in preflight (U24 only).** The flavor meta-packages `scls-<F>` were built in
  August but never installed, so `vtk` (a leaf only the meta-package pulls in) was absent on all
  three flavors. Debian package names map `_` to `-` (`superlu_dist` → `superlu-dist`), so a drift
  sweep querying `scls-$F-$p` misreports superlu_dist as missing.

## Decisions (Christian, this session)

- Sudo grant `--scope pkg`. `sudo -n apt-get --version` is the working gate; `sudo -n true` fails by design.
- `scls-{debug,gcc,mkl}-suitesparse` removed (no dependents, no `DT_NEEDED` consumers).
- oneAPI MKL 2026.0 → 2026.1.0-236 (major stays `.so.3`). `common-licensing-2026.0` and
  `common-oneapi-vars-2026.0` stay because 2026.1 depends on them. No `scls-mkl-*` package was removed.
- Desktop, snaps and LibreOffice removed for disk space. VTK's GL/X11 runtime libraries
  (loaded at run time via `dlopen`) verified retained.
- Repository-local git identity set to the repository's author.

## Open — needs Christian

1. **openmpi fix (build-config change).** Proposal: `--with-prrte=internal` in
   `configure.flavor_args` for `gcc`, `mkl` and `debug`. It makes explicit what RPM hosts already
   build. Alternatives: remove the old openmpi before the build (destructive), or drop `CPATH` from
   the DEB environment (`python/`, wider effect). Full text is under Blockers in
   `todo/rebuild_campaign_20260922.md`.
2. The 2026-08-24 devlog's "root cause still unknown" and the recipe comment should be updated once
   the fix lands.
