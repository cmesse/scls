# 2026-09-22 rebuild campaign — build tracker

**Date:** 2026-09-22
**Branch:** `devel` (nothing on `main`)
**Purpose:** upstream bumps for ten packages plus the rebuild they force, after an unexplained
`-DBUILD_LIBSCOTCHMETIS` flip was found in `recipes/scotch.yaml` (95da949, 2026-04-01). That
option is **unchanged** in this campaign; the open question lives in `todo/scotch_metis_prefix.md`.
**Scope:** 25 packages, one row each, one cell per (distro, flavor) build. Public binary flavors
only (`gcc`, `mkl`, `debug`); nothing that ships only as a source build (`lbl`, `macos`, `intel`)
is listed. Derived from `python/build_order.py` for the three flavors plus a reverse-dependency
closure over every recipe whose version or release changed — see section C for what is *not*
in the closure and why.
**Column grouping** (Markdown has no merged header cells, so the prefixes carry it):

```
           ||      RHEL 9     ||     RHEL 10     || AMZN 2023 || Ubuntu 24 LTS
Package    || DBG | GCC | MKL || DBG | GCC | MKL || GCC | MKL || DBG | GCC | MKL
```

**Cell legend:** `[ ]` to do · `[x]` built **and installed** · `n/a` not built for that
flavor · `--` blocked (add a note under Blockers)

A cell is only ticked once the package is both rebuilt and installed on that host.
Built-but-not-installed stays `[ ]`; note it under Status instead.

---

## A. The campaign — all 25 packages, in build order

Rows are in `build_order.py` order for the `gcc` flavor (`G` = group); `mkl` and `debug`
resolve the same relative order for these packages. Packages in the same group can be built in
parallel; each group needs every earlier group installed.

`why`: **up** = upstream version bump · **casc (x, y)** = unchanged recipe, rebuilt because
those dependencies changed.

| # | G | Package | why | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | cmake 4.4.2 → 4.4.3 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 2 | 2 | openblas 0.3.33 → 0.3.34 | up | n/a | [ ] | n/a | n/a | [ ] | n/a | [ ] | n/a | n/a | [ ] | n/a |
| 3 | 2 | ucx 1.20.1 → 1.22.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 4 | 3 | blaze 3.8.2-1 → -2 | casc (openblas) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 5 | 4 | blaspp 2025.05.28-1 → -2 | casc (openblas) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 6 | 4 | pmix 5.0.10 → 5.0.11 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 7 | 5 | lapackpp 2025.05.28-1 → -2 | casc (openblas, blaspp) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 8 | 5 | openmpi 5.0.10 → 5.0.11 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 9 | 5 | superlu 7.0.1-2 → -3 | casc (openblas) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 10 | 6 | hdf5 1.14.6-2 → -3 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 11 | 6 | parmetis 4.0.3-2 → -3 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 12 | 6 | scalapack 2.2.3-2 → -3 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 13 | 6 | scotch 7.0.13 → 7.0.15 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 14 | 7 | arpack-ng 3.9.1-2 → -3 | casc (openmpi, scalapack) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 15 | 7 | mumps 5.9.1-1 → -2 | casc (openmpi, scotch, scalapack, parmetis) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 16 | 7 | netcdf 4.10.1-1 → -2 | casc (hdf5, openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 17 | 7 | slate 2025.05.28-2 → -3 | casc (openmpi, blaspp, lapackpp) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 18 | 7 | superlu_dist 9.2.1-2 → -3 | casc (openmpi, parmetis) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 19 | 8 | armadillo 15.4.2 → 15.6.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 20 | 8 | butterflypack 4.1.0-2 → -3 | casc (openmpi, arpack-ng, scalapack) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 21 | 8 | exodus 2026.08.11-1 → -2 | casc (hdf5, netcdf, openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 22 | 9 | strumpack 8.0.0-3 → -4 | casc (openmpi, scotch, butterflypack, scalapack) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 23 | 10 | petsc 3.25.4 → 3.25.5 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 24 | 11 | slepc 3.25.1 → 3.25.2 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 25 | 11 | sundials 7.8.0 → 7.9.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

`openblas` builds only for `gcc` among the binary flavors (`mkl` uses MKL, `debug` uses the
Netlib reference), so its four dependents (`blaze`, `blaspp`, `lapackpp`, `superlu`) cascade on
`gcc` only. They are still rebuilt on `debug` and `mkl` because the release bump is in the
recipe and therefore changes the NEVRA on every flavor; a repository that carries `-2` for `gcc`
and `-1` for `mkl` of the same recipe is the state this table exists to avoid.

## B. What was verified on the dev host before this file was written

macOS, no `rpmbuild` — evidence level is static inspection plus `--spec-only`.

- All ten new tarballs download from the recipe URLs (`curl -sSfL`).
- Every remaining patch applies at fuzz 0 against the new tarball (`patch -p1 --dry-run -F0`):
  armadillo (1), openblas (2), petsc (1), scotch (3), sundials (1).
- `openmpi-5.0.10-part-persist-drop-forced-inline.patch` reverse-applies against 5.0.11: its
  single hunk (`mca_part_persist_start` losing `__opal_attribute_always_inline__`) is upstream.
  Dropped from the recipe and the tree; `lbl` keeps its 4.1.6 patch.
- Version-stamped *files* in manifests edited by hand: `files/openblas.txt`
  (`libopenblas-r0.3.34.so`), `files/petsc.txt` (`conf/modules/petsc/3.25.5`),
  `files/slepc.txt` (`conf/modules/slepc/3.25.2`). Version-stamped *directories* need no edit
  (`rpm_builder.get_file_list()` globs them).
- All 55 recipes parse; `build_order.py` resolves for `gcc`, `mkl`, `debug`; specs regenerate.

**Not verified, expect it at the first Linux build:** manifest drift for `ucx` (1.20 → 1.22) and
`sundials` (7.8 → 7.9), both new minor series. `rpmbuild` fails on unpackaged files, so drift
surfaces as a build error, not a silent omission. Regenerate the manifest on the build host and
commit it to `devel`.

## C. Deliberately not in the campaign

| Package | Reported | Reason |
|---|---|---|
| butterflypack | 4.1.0 → 5.0.0 | Major bump, judged too risky this cycle; strumpack links it. Rebuilt at 4.1.0-3 for the cascade only. No `max_major` pin was added — say so if one is wanted. |
| gklib, parmetis | commit pin → newer commit | Commit pins, not releases. Moving gklib forces metis and parmetis (`doc/GKLIB_STATIC_POLICY.md`). Separate decision. |
| hdf5 | 1.14.6 → 2.1.0 | Held by `max_major: 1`, correctly. Rebuilt at 1.14.6-3 for the cascade. |
| openssl | 3.6.2 → 3.6.4 | `include_flavors: [macos]`; not a binary package. |
| automake | 1.18.1 → 1.19 | `include_flavors: [macos]`; GPL-3 build tool, not a binary package. |
| suitesparse, zlib | — | `include_flavors: []`; never built by default. The zlib "100 → 100.120.1" line is the Apple tag series, not a version. |
| metis, zfp, vtk, googletest, hwloc, libevent, … | current | Depend only on `cmake`, `gklib` or nothing that changed. `cmake` is treated as a build tool, not a cascade trigger — the same call the ASC 2026 tracker made when it bumped cmake 4.3.3 → 4.4.2 without rebuilding `blaspp`, `blaze`, `lapackpp`, `nlopt`, `testsweeper`. |

## D. Running it

```bash
git checkout devel
echo "flavor: debug" > flavor.conf        # canary flavor first, as in ASC 2026
./scls order                              # confirm the 25 above appear in this order
./scls build next && ./scls install next  # repeat; or loop over the rows of section A
```

Tick a cell only after `./scls install` succeeds on that host. Prune superseded artifacts
happens automatically on install (`SCLS_KEEP_OLD_ARTIFACTS=1` to keep them).

## Status

- 2026-09-22 — recipes, manifests and changelogs committed to `devel`. No build yet.
- 2026-09-22 — R9: debug 8/24 built and installed (rows 1–9, groups 2–5 complete).
  Run stopped deliberately at Christian's request for a host shutdown, **not** on a failure —
  hdf5 (row 10) was ~33 min into its `make check` (`tools/h5repack`, with `fortran` and `hl`
  still ahead) and was killed mid-build; its partial tree was discarded and it re-extracts from
  `rpmbuild/SOURCES` on resume. No auto-fixes were needed: ucx 1.20→1.22 built with no manifest
  drift, and openmpi 5.0.11 built clean with the dropped `part-persist-drop-forced-inline` patch,
  confirming the dev-host finding that upstream absorbed it. sundials (row 25) is still the one
  untested drift candidate from section B.
  Resume with `/update-build --from hdf5`. Host HEAD at run start: 6f46a04.
  Logs: `work/logs/debug/` (git-ignored, local to this host).
- 2026-09-22 — R9: debug 16/24 built and installed (rows 1–17, groups 2–7 complete).
  Resumed run added hdf5 1.14.6-3, parmetis 4.0.3-3, scalapack 2.2.3-3, scotch 7.0.15-1,
  arpack-ng 3.9.1-3, mumps 5.9.1-2, netcdf 4.10.1-2, slate 2025.05.28-3. Stopped deliberately
  after slate for a second host shutdown, **not** on a failure; superlu_dist (row 18) was killed
  at the start of its build and stays unticked. Still no auto-fixes: scotch 7.0.13 → 7.0.15
  applied its three patches at fuzz 0 on Linux and produced no manifest drift. mumps is the
  first package linking all four rebuilt group-6 deps, and netcdf the first consumer of the
  rebuilt hdf5, so the cascade is consistent through group 7.
  Remaining on this column: rows 18–25 (superlu_dist, armadillo, butterflypack, exodus,
  strumpack, petsc, slepc, sundials). sundials is still the untested drift candidate from
  section B. Resume with `/update-build --from superlu_dist`.
  Host HEAD at run start: 88a324c (rebased onto fe904d0).
- 2026-09-22 — **R9: debug 24/24 built and installed — column complete.** All 24 installed
  NEVRAs re-verified against their recipes in one sweep after the last package. Final run added
  superlu_dist 9.2.1-3, armadillo 15.6.0-1, butterflypack 4.1.0-3, exodus 2026.08.11-2,
  strumpack 8.0.0-4, petsc 3.25.5-1, slepc 3.25.2-1, sundials 7.9.0-1.
  Two Class M auto-fixes were required, both committed and **both needed on the other three
  columns**:
  - `67c3d4f` armadillo — 15.6.0 consolidated `fn_{,inplace_}{s,}trans.hpp` into
    `fn_{,inplace_}xtrans.hpp` and added the `cubemul` and `permute` feature groups.
    4 removed, 8 added. rpmbuild reported only the 4 missing; the 4 new headers were found by
    diffing the whole buildroot and would otherwise have failed the next build as unpackaged.
  - `3810fe9` petsc — dropped the stale `include/petscmat.h.orig` entry. `patch` runs with
    `--no-backup-if-mismatch`, so an earlier version's fuzzy apply created the backup and a
    manifest regenerated from that buildroot captured it; every petsc package shipped since
    then carried an unpatched copy of a public header. 3.25.5 applies at fuzz 0, so the entry
    is now stale. Verified the patch still applies (not a silently-unpatched build).
  `petsc-baijmkl-decls.patch` was checked against pristine 3.25.5 and is **still required**:
  `baijmkl/makefile` still requires `PETSC_HAVE_MKL_SPARSE_OPTIMIZE` while `petscmat.h:427`
  still gates the declarations on `PETSC_HAVE_MKL_SPARSE`, and this host's oneAPI MKL 2026.0
  has no `mkl_dcsrmv`. Inert on `debug`/`gcc`; load-bearing on `mkl`/`intel`.
  sundials 7.8 → 7.9 produced **no** manifest drift, closing the last section B prediction.
  Host HEAD at run start: 55f3f0b.

## Blockers

- none
