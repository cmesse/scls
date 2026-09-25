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
| 1 | 2 | cmake 4.4.2 → 4.4.3 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 2 | 2 | openblas 0.3.33 → 0.3.34 | up | n/a | [x] | n/a | n/a | [x] | n/a | [ ] | n/a | n/a | [ ] | n/a |
| 3 | 2 | ucx 1.20.1 → 1.22.0 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 4 | 3 | blaze 3.8.2-1 → -2 | casc (openblas) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 5 | 4 | blaspp 2025.05.28-1 → -2 | casc (openblas) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 6 | 4 | pmix 5.0.10 → 5.0.11 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 7 | 5 | lapackpp 2025.05.28-1 → -2 | casc (openblas, blaspp) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 8 | 5 | openmpi 5.0.10 → 5.0.11 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 9 | 5 | superlu 7.0.1-2 → -3 | casc (openblas) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 10 | 6 | hdf5 1.14.6-2 → -3 | casc (openmpi) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 11 | 6 | parmetis 4.0.3-2 → -3 | casc (openmpi) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 12 | 6 | scalapack 2.2.3-2 → -3 | casc (openmpi) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 13 | 6 | scotch 7.0.13 → 7.0.15 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 14 | 7 | arpack-ng 3.9.1-2 → -3 | casc (openmpi, scalapack) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 15 | 7 | mumps 5.9.1-1 → -2 | casc (openmpi, scotch, scalapack, parmetis) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 16 | 7 | netcdf 4.10.1-1 → -2 | casc (hdf5, openmpi) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 17 | 7 | slate 2025.05.28-2 → -3 | casc (openmpi, blaspp, lapackpp) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 18 | 7 | superlu_dist 9.2.1-2 → -3 | casc (openmpi, parmetis) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 19 | 8 | armadillo 15.4.2 → 15.6.0 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 20 | 8 | butterflypack 4.1.0-2 → -3 | casc (openmpi, arpack-ng, scalapack) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 21 | 8 | exodus 2026.08.11-1 → -2 | casc (hdf5, netcdf, openmpi) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 22 | 9 | strumpack 8.0.0-3 → -4 | casc (openmpi, scotch, butterflypack, scalapack) | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 23 | 10 | petsc 3.25.4 → 3.25.5 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 24 | 11 | slepc 3.25.1 → 3.25.2 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 25 | 11 | sundials 7.8.0 → 7.9.0 | up | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 26 | 0 | environment 2026-1 → 2026-2 | stale | [x] | [x] | [x] | n/a | n/a | n/a | [ ] | [ ] | [ ] | [ ] | [ ] |
| 27 | 2 | libunwind 1.8.3-1 → -2 | stale | [x] | [x] | [x] | n/a | n/a | [x] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 28 | 2 | nlopt 2.10.1 → 2.11.0 | stale | [x] | [x] | [x] |
| 29 | 2 | hwloc 2.13.0 → 2.14.0 | stale (mkl only) | n/a | n/a | [x] | n/a | n/a | n/a | [ ] | [ ] | [ ] | [ ] | [ ] |

**Rows 26–28 were added on 2026-09-22, mid-run, and are not part of the original ten-bump
scope.** `why: stale` means the installed package on the R9 build host was behind its own recipe
and the gap predates this campaign — none of the three is a cascade of anything in rows 1–25.
They are appended rather than inserted in build order so rows 1–25 keep their numbers; their
real positions are `environment` Group 0 (always first) and `libunwind`/`nlopt` Group 2.

Found when belfem's publishing session questioned an `scls-gcc-nlopt-2.10.1-1` in a planned drop
against the `nlopt-2.11.0-1` already live in the repo. A full installed-vs-recipe sweep then
showed all three stale on `debug` and `gcc`. Staging any drop before fixing this would have
regressed `nlopt` in the published repository.

**No package in rows 1–25 needs rebuilding because of this.** Verified rather than assumed:
`environment` 2026-2 changes only RPM metadata (`rpm_requires:` for the host toolchain,
`rpm_recommends: doxygen`, honouring `release:`/`AutoReqProv`) and alters no prefix, flag or
path; `libunwind` 1.8.3-2 fixes `%dir` ownership and its changelog records that it was
"re-wrapped from the existing payload rather than recompiled, so every file digest is
unchanged", and its only reverse dependencies are `gperftools` and `gcc`, neither in this
campaign; `nlopt` is a leaf with no reverse dependencies at all.

**Rows 26–28 are installed, not rebuilt.** All nine correct-version RPMs already exist in the
local tree (`scls-{debug,gcc,mkl}-environment-2026-2.el9.noarch.rpm`,
`…-libunwind-1.8.3-2.el9.x86_64.rpm`, `…-nlopt-2.11.0-1.el9.x86_64.rpm`) — built here, uploaded,
and then never installed on this host. This matches the uninstall-on-rebuild defect from
2026-05-12 rather than an interrupted run, and went unnoticed for months because nothing
compares installed state against recipes; the tracker only knows the packages it lists.

Installing the existing artifacts rather than regenerating them keeps this host *byte*-identical
to the published repo, not merely version-identical. Rebuilding would have produced the same
NEVRA with different bytes — which belfem's contract v1.2 refuses to promote, since `mv -f`
would replace a signed file with an unsigned one and break clients whose metadata is cached
(`scls.repo` sets no `metadata_expire`, so up to 48 h).

Drift is on all three flavors; `mkl` needs only two of the three:

| flavor | environment | libunwind | nlopt |
|---|---|---|---|
| debug | 2026-1 → 2026-2 | 1.8.3-1 → -2 | 2.10.1-1 → 2.11.0-1 |
| gcc   | 2026-1 → 2026-2 | 1.8.3-1 → -2 | 2.10.1-1 → 2.11.0-1 |
| mkl   | 2026-1 → 2026-2 | 1.8.3-1 → -2 | already current |

Eight installs in total. Rows 26–28 are **not staged** to belfem: their NEVRAs are already
published, so they go in `MANIFEST.txt` under `already_published:` rather than as payload.

**Row 29 (`hwloc`, mkl only) was found after rows 26–28 were installed**, by re-running the
drift check across all three flavors. `debug` and `gcc` already had 2.14.0; only `mkl` was
behind at 2.13.0, and `scls-mkl-hwloc-2.14.0-1.el9.x86_64.rpm` was sitting in
`rpmbuild/RPMS/x86_64/` unused — the same built-but-never-installed defect, fourth instance.

It was installed **before** the mkl column was built, which matters: `hwloc` is a dependency of
`pmix` and `openmpi`, so building mkl first would have linked its whole MPI stack against 2.13.0
while `debug` and `gcc` got 2.14.0 — a cross-flavor inconsistency that no manifest check would
have caught and that nothing in the campaign would have flagged. `n/a` in the debug and gcc
columns means those flavors were already current, not that the package is unbuilt there.

After rows 26–29 the drift check reports `(all current)` for `debug` and `gcc`; `mkl` shows only
the 24 campaign packages still to build.

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
- 2026-09-22 — **R9: gcc 25/25 — column complete.** All 25 NEVRAs re-verified against recipes in
  one sweep. openblas 0.3.34-1 confirmed the hand-edited version-stamped
  `libopenblas-r0.3.34.so` manifest entry. Both Class M fixes from the debug column
  (`67c3d4f` armadillo, `3810fe9` petsc) applied unchanged on gcc — two flavors each is the
  evidence they are upstream drift rather than debug-specific, and they still must reach R10,
  AMZN and U24. Rows 26–29 installed on every affected flavor (see above).
- 2026-09-22 — R9: mkl 8/24 built and installed (rows 1–9, groups 2–5 complete; row 2 openblas
  `n/a` — mkl uses MKL for BLAS). Stopped deliberately before hdf5 at Christian's request,
  **not** on a failure; hdf5 (row 10) had just been reached and was killed at the start of its
  build. Three mkl-specific risks cleared so far: blaze's blazetest passed against MKL's
  `mkl_cblas.h` under oneAPI 2026; openmpi 5.0.11 built clean without the dropped
  `part-persist` patch on the third and final flavor, retiring that risk for the campaign; and
  pmix compiled against hwloc 2.14.0 — verified via `HWLOC_VERSION` in
  `/opt/scls/mkl/include/hwloc/autogen/config.h`, not assumed, because the SONAME is
  `libhwloc.so.15` for both 2.13 and 2.14 and `DT_NEEDED` would not have revealed a mismatch.
  Still untested on this column: the MKL major SONAME in consumers' `DT_NEEDED`
  (`doc/MKL_ABI_POLICY.md`), petsc's `baijmkl` patch — inert on debug and gcc but load-bearing
  here, since oneAPI 2026 has no `mkl_dcsrmv` — and scalapack, which must come from the stack
  and never from `libmkl_scalapack`/`libmkl_blacs`.
  Resume with `/update-build --from hdf5`. Host HEAD at run start: fc3edbe.
- 2026-09-23 — **R9 COMPLETE: debug 24/24, gcc 25/25, mkl 24/24, plus rows 26–29.**
  Final gate was a sweep over the *full* `build_order.py` list for each flavor, not just the
  campaign rows: every installed package on all three flavors matches its recipe. Two Class M
  auto-fixes (`67c3d4f` armadillo, `3810fe9` petsc), no blockers, no halts.
  Three mkl-only checks, each verified by inspection rather than inferred from a successful build:
  - **scalapack provenance.** `readelf -d /opt/scls/mkl/lib/libscalapack.so` shows
    `libmkl_gf_lp64.so.3`, `libmkl_sequential.so.3`, `libmkl_core.so.3` and **no**
    `libmkl_scalapack*` or `libmkl_blacs*`. The stack's own ScaLAPACK over MKL's BLAS/LAPACK,
    exactly as policy requires.
    **CORRECTION 2026-09-25 — this entry certified a defect.** The provenance claim is true and
    still holds: ScaLAPACK is ours and no `libmkl_scalapack`/`libmkl_blacs` is linked. But
    "exactly as policy requires" was wrong about the rest of the line. `libmkl_sequential.so.3`
    was printed here and passed over, and it made this the only library in the flavor not linking
    `libmkl_gnu_thread` — so `ldd libpetsc.so` loaded two MKL threading layers into one process.
    The check asked about provenance and answered it correctly; it never asked whether the flavor
    was self-consistent, which no per-package check can. Fixed on 2026-09-25 outside this
    campaign's scope (scalapack 2.2.3-4, armadillo 15.6.0-2, plus
    `scripts/check_mkl_linkage.sh` as a per-flavor gate). See
    `devlog/dl20260925_mkl_threading_uniformity.md` and the new threading-uniformity section of
    `doc/MKL_ABI_POLICY.md`. Anyone reading this row as a precedent for a future campaign should
    read the correction first.
  - **MKL major SONAME.** Those `DT_NEEDED` entries are `.so.3`, so this column re-aligns the
    mkl flavor after the host's `.so.2` → `.so.3` bump. Per `doc/MKL_ABI_POLICY.md` that SONAME
    is invisible to RPM metadata under `AutoReqProv: no`, so a rebuild on the affected host is
    the only fix and direct inspection the only confirmation.
  - **hwloc.** `HWLOC_VERSION "2.14.0"` in `/opt/scls/mkl/include/hwloc/autogen/config.h`, so
    pmix and openmpi compiled against the same hwloc as debug and gcc. The SONAME is
    `libhwloc.so.15` for both 2.13 and 2.14, so `DT_NEEDED` would not have exposed a mismatch.
  **Correction to the 2026-09-22 entry above:** `petsc-baijmkl-decls.patch` is recorded there as
  "load-bearing on `mkl`/`intel`". That is wrong for this host. The installed
  `/opt/scls/mkl/include/petscconf.h` defines `PETSC_HAVE_MKL_INCLUDES`, `..._LIBS` and
  `..._SET_NUM_THREADS` but **neither** `PETSC_HAVE_MKL_SPARSE` nor `..._SPARSE_OPTIMIZE`, so
  both of the patch's guards are false and it is inert on all three R9 flavors. The error was
  inferring the macro from `mkl_sparse_optimize` being present in `mkl_spblas.h`; PETSc does not
  enable MKL sparse merely because the symbol exists, and the recipe passes only
  `--with-blaslapack-{include,lib}`. The upstream gating mismatch is nonetheless real and unfixed
  in 3.25.5 (verified against the pristine tarball), and the recipe comment names **RHEL 10** as
  the trigger — so **keep the patch**, and expect the `R10` column to be what actually tests it.
  Host HEAD at run start: fc94ae6.

- 2026-09-23 — R10: debug 9/24 built and installed (rows 1, 3–10; groups 2–6 through hdf5).
  Stopped deliberately after hdf5 at Christian's request (checkpoint), **not** on a failure;
  parmetis (row 11) was killed within a second of starting and stays unticked. No auto-fixes:
  ucx 1.22 and openmpi 5.0.11 built clean on el10, as on R9. hdf5 `make check` took 67 min.
  Preflight drift sweep on this host: `debug` and `gcc` stale only on campaign rows —
  `environment`, `libunwind`, `nlopt`, `hwloc` were already current, hence `n/a` in rows 26, 27,
  29 (row 28 has no R10 cells; nlopt is current on all three R10 flavors). `mkl` additionally had
  `libunwind`, `blaze`, `gperftools`, `nlopt`, `vtk` built but **never installed** — fifth
  instance of the built-not-installed defect. With Christian's approval the existing
  `.el10` RPMs of libunwind 1.8.3-2, gperftools 2.18.1-1, nlopt 2.11.0-1 and vtk 9.7.0-1 were
  installed before any mkl build (not rebuilt); blaze is campaign row 4 and builds in the mkl
  column. Sudo on this VM is Option A (dnf/apt-get/dpkg/rpm only), so `sudo -n true` fails by
  design; the builders only call those binaries.
  Resume with `/update-build --from parmetis`. Host HEAD at run start: a580f09.
  Logs: `work/logs/debug/` (git-ignored, local to this host).

- 2026-09-24 — **R10: debug 24/24 built and installed — column complete.** Resumed from parmetis
  (rows 11–25, 13:20–14:51); a full `build_order.py` sweep afterwards shows every debug package
  matching its recipe. **No auto-fixes on el10:** the R9 manifest fixes (`67c3d4f` armadillo,
  `3810fe9` petsc) were already on `devel` and held; scotch 7.0.15 and sundials 7.9.0 built with
  no drift. Rebased the checkpoint onto two upstream tooling commits (8e10061, 15bdbd2) — no
  recipe, manifest or patch changes among them. Host HEAD at resume: 4da6920.

- 2026-09-24 — R10: gcc 19/25 built and installed (rows 1–19, through armadillo).
  Stopped deliberately at Christian's request, **not** on a failure; butterflypack (row 20) was
  7 min into its build and was killed — its partial `BUILD`/`BUILDROOT` trees were removed, so it
  re-extracts on resume. Still no auto-fixes: openblas 0.3.34 confirmed the hand-edited
  `libopenblas-r0.3.34.so` entry on el10, and the R9 armadillo fix (`67c3d4f`) held.
  Remaining on this column: rows 20–25 (butterflypack, exodus, strumpack, petsc, slepc, sundials),
  then the whole mkl column. Resume with `/update-build --from butterflypack` (gcc).
  Host HEAD at run start: bf6e99d.

- 2026-09-24 — **R10: gcc 25/25 built and installed — column complete.** Resumed at butterflypack
  (rows 20–25, 21:59–22:28); full `build_order.py` sweep clean for gcc. Still no auto-fixes on
  el10 — the R9 petsc manifest fix (`3810fe9`) held on both R10 columns. Host HEAD at resume: 4f5d457.

## Blockers

- none
