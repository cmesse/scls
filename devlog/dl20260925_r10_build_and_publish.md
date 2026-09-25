# Devlog 2026-09-25 — R10 column of the 2026-09-22 campaign: built, fixed, published

**Date:** 2026-09-23 – 2026-09-25
**Topic:** `/update-build` and `/stage-drop` for the R10 column (Rocky 10.2), including the MKL threading fix
**AIs involved:** Claude (R10 build host, session scls-ae); belfem coordinator sessions claude-06 / claude-f7 over the bridge
**Flavor / Host:** debug, gcc, mkl on the R10 build VM (Rocky Linux 10.2, `.el10`)
**Verification:** built and installed on R10/{debug,gcc,mkl}; full `build_order.py` NEVRA sweep clean on all three; `scripts/check_mkl_linkage.sh --prefix /opt/scls/<f>` PASS on all three; four drops uploaded, then verified and promoted **by belfem** (this host can only claim "uploaded")

## Summary

The R10 column is complete and published: debug 24/24, gcc 25/25, mkl 24/24, plus the
scalapack 2.2.3-4 / armadillo 15.6.0-2 release bumps from `6a4d268` on every flavor. No Class M/P/D
auto-fixes were needed on el10. The R9 manifest fixes (`67c3d4f` armadillo, `3810fe9` petsc) held.
One blocker, shared with R9 (mixed MKL threading layers), was fixed upstream on R9 and rebuilt
here with Christian's approval. One tooling bug in the staging path was fixed (`40e296a`).

## Key Findings

- **Built-but-never-installed, fifth instance.** The preflight drift sweep (`doc/BUILD_EXECUTION.md`
  §1.6) found `libunwind`, `blaze`, `gperftools`, `nlopt`, `vtk` built for mkl but never
  installed. Christian approved installing the existing `.el10` artifacts for the four
  non-campaign ones before any mkl build. blaze is a campaign row and was rebuilt normally.
- **Mixed MKL threading layers (R9 and R10).** Found by belfem on R9-mkl, then confirmed here:
  346/348 MKL-linked files were `gf_lp64 + gnu_thread + core`, but `libscalapack.so.2.2.3` linked
  `libmkl_sequential` (`python/math_common.py` gated threading on the recipe's `openmp: false`)
  and `libarmadillo.so.15.6.0` added `libmkl_rt` (its own FindMKL under `-DALLOW_MKL_LINUX=ON`).
  Consumers loading both layers: butterflypack, mumps, petsc, slepc, strumpack. My R10 mkl Status
  line listed `libmkl_sequential.so.3` under "scalapack provenance" without flagging it. That is
  the same miss the R9 entry made, and it is corrected in the tracker. Fix: `6a4d268` (authored on R9).
  See `devlog/dl20260925_mkl_threading_uniformity.md` and `doc/MKL_ABI_POLICY.md`.
- **Pre-fix vs post-fix spec diff.** Generated every mkl spec from `15bdbd2` (worktree, with the
  real `rpmbuild/SOURCES` linked so tarball-derived `%setup -n` names match) and from `6a4d268`.
  Exactly three specs changed: scalapack, armadillo, and blaze (header-only, test-link flags only,
  not rebuilt). A first attempt with an empty SOURCES dir showed 14 spurious diffs, all
  `%setup -n` case differences.
- **The release bumps are recipe-wide.** `6a4d268` bumps scalapack/armadillo for every flavor, but
  the fix plan only rebuilt mkl. The stage script's "installed NEVRA ≠ recipe" filter then
  silently dropped scalapack/armadillo from the R10-gcc selection (`excluded: 2`). Christian
  approved rebuilding debug and gcc as well (release-only on those flavors). R9 did not, and
  belfem is scheduling an el9 follow-up.
- **Relative `--stage` broke the linkage gate.** `check_mkl_linkage.sh` extracts RPMs after `cd`
  into a scratch dir, so a relative path found "0 ELF objects". It failed closed (no READY
  written). Fixed in `40e296a`: `stage_to_belfem.sh` realpaths `--stage`, and the gate realpaths
  `--dir`/`--prefix`.
- **Upload-time `excluded:` is recomputed.** In `--upload --drop` mode the report block reprints
  the selection counts from *current* host state, not from the staged MANIFEST. The R10-debug
  report said `excluded: 2` after the release bump, while the uploaded drop has no exclusions.
  Cosmetic, but misleading in a report that is relayed verbatim. Not fixed.
- **`petsc-baijmkl-decls.patch` is inert on R10 too.** The installed `petscconf.h` defines
  neither `PETSC_HAVE_MKL_SPARSE` nor `..._SPARSE_OPTIMIZE`. Nothing in the campaign exercised it.
- **Runbook nit.** `doc/BUILD_EXECUTION.md` §1.3 tests `sudo -n true`, which always fails under
  its own recommended Option A (NOPASSWD only for dnf/apt-get/dpkg/rpm). `sudo -n rpm -q rpm` is
  the meaningful probe. Not changed.

## Changes Made

- `40e296a` fix(publish): resolve `--stage`/`--dir`/`--prefix` to absolute paths.
- Tracker `todo/rebuild_campaign_20260922.md`: R10 cells, Status entries, the MKL blocker and its
  resolution, and the provenance correction.
- Host: `scls-{debug,gcc,mkl}-suitesparse` removed with Christian's approval (GPL-2,
  `include_flavors: []`; no `DT_NEEDED` consumer). Their RPM/SRPM files remain in `rpmbuild/`.
  They cannot ship, because selection starts from *installed* packages.

## Drops (all promoted by belfem)

| Drop | Files | Bytes | sha256(SHA256SUMS) |
|---|---|---|---|
| R10-debug-20260925T0959Z | 51 | 765014526 | df28530f…5676 |
| R10-gcc-20260925T1111Z | 53 | 794720168 | c920792d…341a |
| R10-debug-20260925T1112Z (scalapack/armadillo fixup) | 4 | 14266718 | 550e1258…fd6a |
| R10-mkl-20260925T1111Z | 51 | 765256774 | 1514831d…9901 |

Christian approved the R10 uploads directly in the R10 session. belfem gave the size OK and
the slot go-ahead for each. The two belfem sessions briefly contradicted each other on who
coordinated. The fixup upload followed the final consistent instruction (claude-06), and the
crossing messages are recorded in the relay.

## Open

- el9 follow-up: debug/gcc scalapack 2.2.3-4 / armadillo 15.6.0-2 (belfem schedules).
- AMZN and U24 columns: not started.
- The stage script's upload-mode `excluded:` count (above).
