# Devlog 2026-10-04 — campaign policy, the PETSc 3.26 math campaign, and Scotch's ParMETIS emulation

**Date:** 2026-10-04
**Topic:** todo consolidation before merging `ipopt`; review of the devlogs since 2026-09-04 for procedure gaps; new `doc/CAMPAIGN_POLICY.md`; the 2026-10-04 math campaign; `-DSCOTCH_METIS_PREFIX=ON`
**AIs involved:** Claude Opus 5.5 (macOS dev host); Codex gpt-5.6-terra/high and Grok grok-4.7/high, blind, plan round and implementation round on the Scotch option (`tmp/ai_exchange/plan_scotch_metis_prefix.md`, `impl_scotch_metis_prefix.md`)
**Claude Confidence:** high on what was measured on the macOS install; medium on the Linux consequences, which no host has built yet
**Auditor Confidence:** both rounds: no finding against the recipe diff; Codex P0 and Grok P1 against the first version of the campaign gates
**Flavor / Host:** macOS dev host (x86_64), `/opt/scls` with scotch 7.0.11 and petsc 3.25.0 installed
**Upstream References:** PETSc 3.25.0 and 3.26.0 `config/BuildSystem/config/packages/PTSCOTCH.py`; PETSc 3.25.0 `src/mat/graphops/partition/impls/scotch/scotch.c:296-306`; Scotch 7.0.11 and 7.0.16 `src/libscotchmetis/CMakeLists.txt:96-97,177-178`, `library_parmetis.h:77-110`; hwloc 2.14.0 and 2.15.0 `VERSION`
**Verification:** `otool -L`, `nm -m`, `nm -gU` on the macOS install; `patch -p1 --dry-run -N -F0` (Apple patch) against the new tarballs; `validate_project.py`, `build_order.py`, `--spec-only`. **Not run:** any Linux build.

## Summary

The 2026-09-22 campaign and its round 2 took two weeks. Christian asked for the cause. The devlogs
show that most of the rework fixed defects that were already in the published packages, found by
gates that were invented mid-campaign or that ran at belfem after upload, with no rule separating
"blocks this release" from "next campaign". `doc/CAMPAIGN_POLICY.md` now fixes scope, blocker
classes, one backlog, gates, a pilot on R9 and U24, payload-based rebuilds, upload order, audit
availability, and PETSc as the reference for the versions of its dependencies. The first campaign
under it is `todo/rebuild_campaign_20261004.md`.

## Key Findings

- **Rework triggers, 2026-09-22 to 2026-10-04** (policy §10 has the table): four stale packages on
  R9, mixed MKL threading layers, openmpi's external PRRTE, the gfortran 15.2 `zlaqr5` miscompile,
  Ubuntu's `--as-needed`, gperftools without libunwind, inert scotch flags, triplet-prefixed tools,
  the pprof tests, spral on debug. Only the last is a defect of something the campaign added.
- **Two engineering causes** sit behind most of them: rpm_builder and unix/deb_builder set up
  different build environments (`CPATH`/`LIBRARY_PATH`, argument expansion, `--as-needed`,
  `flavor_pre/post`, MKL environment), and builds depend on undeclared host state. Both are in the
  backlog, not solved.
- **Scotch's ParMETIS emulation shadowed the real ParMETIS in PETSc.** Measured on the macOS
  install:
  - Only `libpetsc` and `libslepc` link `libptscotchparmetisv3`; nothing links
    `libscotchmetisv3`/`v5`. MUMPS links `ptesmumps`/`ptscotch`/`scotch`
    (`templates/mumps/Makefile.inc.j2:65`).
  - `libparmetis` and `libptscotchparmetisv3` export 20 common names (four functions in five
    spellings); `libmetis` and `libscotchmetisv3` export 30.
  - `libpetsc` imports `ParMETIS_V3_PartKway` and `ParMETIS_V3_Mesh2Dual` from
    `libptscotchparmetisv3`, and `ParMETIS_V3_AdaptiveRepart`, `ParMETIS_V3_RefineKway`,
    `ParMETIS_V32_NodeND` from `libparmetis`. PETSc's link line has `-lptscotchparmetisv3` before
    `-lparmetis`. So PETSc's `parmetis` partitioner ran PT-Scotch for k-way partitioning.
  - The emulation library cannot be switched off without a PETSc patch: `PTSCOTCH.py` lists a
    `libptscotchparmetis*` in both link alternatives (identical in 3.25.0, 3.25.5 and 3.26.0), and
    PETSc's PT-Scotch partitioner calls `SCOTCH_ParMETIS_V3_NodeND` for nested dissection.
  - PETSc builds its own Scotch with `-DSCOTCH_METIS_PREFIX:BOOL=ON`. SCLS did not set it.
  - Options weighed: leave (0 builds); prefix on (scotch only); emulation off (scotch, petsc, slepc,
    a `PTSCOTCH.py` patch, loss of PT-Scotch nested dissection). Christian: stay close to PETSc
    upstream, prefix on.
- **PETSc 3.26.0's pins against the recipes.** mumps, superlu, superlu_dist, scotch, strumpack,
  scalapack, parmetis, netcdf, zfp, openblas, slate, gmp, openmpi and cmake match. hwloc was behind
  (2.14.0 against 2.15.0), hdf5 is a major behind (1.14.6 against 2.2.0), butterflypack is ahead
  (4.1.0 against 3.2.0).
- **hwloc 2.14.0 → 2.15.0 keeps `libhwloc.so.15`** (libtool `25:3:10` → `25:4:10`); the installed
  public headers differ in comments and one inline-helper line. Exported symbols not compared.
- **The first version of the campaign gates could pass on a wrong result** (both auditors): G1
  succeeded when forbidden symbols were present, G2 never checked the binding target, G3 relied on
  the exit code of glibc's `ldd -r`. Rewritten as scripts that exit non-zero.
- **A fact missed during planning:** the U24 and U26 round-2 drops were uploaded and promoted the
  same evening by their own sessions. The campaign was first committed with scotch as a
  same-release rebuild of an "unpublished" 7.0.15-2; after pulling, it became 7.0.15-3.

## Decisions (Christian, 2026-10-04)

- Adopt the campaign policy. The payload rule (§6) amends the same-day rule that every host
  rebuilds at the same release so the changelog matches.
- "We always take the latest PETSc version and bump its dependencies to that." scotch stays at
  7.0.15 and superlu_dist at 9.2.1; hwloc and cmake are pinned to PETSc (hwloc → 2.15.0, cmake
  4.4.4 held); butterflypack may stay ahead; hdf5 not this round.
- `-DSCOTCH_METIS_PREFIX=ON`.
- Not now: vtk 9.7.1 (next week), butterflypack 5.0.0 (major).
- `lbl` release numbers are not a question: source-only flavors ship none.

## Changes Made

- `doc/CAMPAIGN_POLICY.md` (new); pointers in `CLAUDE.md`, `doc/BUILD_EXECUTION.md` §0,
  `/update-plan`, `/update-build`, `/stage-drop`.
- `todo/`: 15 files consolidated to the backlog, the two campaign files and the old tracker;
  `todo/backlog.md` is the single sink, with 22 items carried from devlog "Open" sections.
- Campaign: petsc 3.26.0, slepc 3.26.0, armadillo 15.6.1, hwloc 2.15.0, scotch 7.0.15-3 with the
  prefix, sundials 7.9.0-2. `petsc-baijmkl-decls.patch` context refreshed for 3.26.0.
  `patches/scotch/archive/scotch-shared-7.0.16.patch` kept for the day PETSc pins 7.0.16.

## Follow-up, same day: `extra_packages:` on unix/deb, and NEVER_SHIP for subpackages

Christian: "Go ahead and fix them now." Both were found on 2026-09-30 and had been deferred.
Exchange: `tmp/ai_exchange/plan_extra_packages_never_ship.md`, `impl_extra_packages_never_ship.md`.

- **B1.** `build_common.require_buildable()` is the one gate for rpm_builder, unix_builder and,
  through it, deb_builder. A recipe excluded by its own flavor lists builds when `flavor.conf`
  lists it under `extra_packages:`; until now only rpm_builder honoured that.
  `UnixBuilder.check_dependencies` now requires a dependency that is itself only opted in.
- **B2.** `scripts/stage_to_belfem.sh` reads `%{SOURCERPM}` from the rpmdb and excludes a binary
  when its own name or its source package's is a NEVER_SHIP recipe. `scripts/deb_drop_select.py`
  does the same from the `.dsc` `Binary:` map and from the recipe's `subpackages:` list.
- **Plan round** (Codex gpt-5.6-terra/high, Grok grok-4.7/high, blind): both refuted the first DEB
  design (`${source:Package}` from dpkg-query): SCLS .debs carry no `Source:` field
  (`templates/default.control.j2`), so it would have returned the binary's own name. Both also
  pointed out that `build next`/`all`/`order` still ignore `extra_packages:` (backlog).
- **Gates on the dev host:** `UnixBuilder('zlib'|'suitesparse', 'macos')` raises without the
  opt-in and constructs with it; `metis` unchanged. `--spec-only` for all 58 recipes × gcc, mkl,
  debug: specs and output identical before and after. `never_ship_reason` (bash, extracted from
  the script): 12 cases. `deb_drop_select.never_ship_table`/`never_ship_reason`: 10 cases.
- **Not run:** `rpm -qa` on a real rpmdb, `dpkg-query`, the full staging script, a DebBuilder
  build. The implementation audit round had not reported when `57c7621` was committed and
  pushed, on Christian's instruction.
- **Implementation round** (same auditors, blind): no P0, no P1. Four P2, three fixed in the
  follow-up commit: `never_ship_table` read only mapping-form `subpackages:` and missed the list
  form that petsc, slepc and sundials use (the fixture in the first test was a mapping, so it
  passed); an unused import in rpm_builder; a subpackage whose rpmdb `SOURCERPM` is empty or
  `(none)` was not excluded, so the loop now checks again with the artifact's own `SOURCERPM`.
  The fourth is in the backlog: with `extra_packages: [gcc]` on unix/deb, `build next` cannot
  schedule the gcc that `check_dependencies` now requires.

## Open

Blockers: none. Everything deferred is in `todo/backlog.md`. Open by execution only, on the pilot
hosts: scotch's `ctest` with the prefix; gate G2 (every `ParMETIS_V3_*` import of `libpetsc.so`
binds to `libparmetis.so` on Linux); manifest drift for petsc, slepc and hwloc; sundials 7.9.0
against PETSc 3.26.0.

## Files Updated

`doc/CAMPAIGN_POLICY.md`, `doc/BUILD_EXECUTION.md`, `CLAUDE.md`, `.claude/commands/{update-plan,update-build,stage-drop}.md`,
`recipes/{petsc,slepc,armadillo,hwloc,scotch,sundials}.yaml`, the matching `changelogs/`,
`files/{petsc,slepc}.txt`, `patches/petsc/petsc-baijmkl-decls.patch`, `patches/scotch/archive/`,
`todo/backlog.md`, `todo/rebuild_campaign_20261004.md`, `todo/campaign_20261004_hosts.md`,
this devlog, `devlog/README.md`.
