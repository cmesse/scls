# 2026-10-04 math campaign — build tracker

**Date:** 2026-10-04
**Branch:** `ipopt` (Christian merges it into `main` and deletes `devel` and `ipopt` himself; build
hosts pull the branch he names)
**Policy:** `doc/CAMPAIGN_POLICY.md`. This tracker is the scope (§1). Pilot hosts are R9 and U24
(§5). Nothing is uploaded until every host has passed (§7).
**Purpose:** PETSc 3.26.0 with slepc 3.26.0, armadillo 15.6.1, hwloc 2.15.0 and the Scotch
METIS-prefix option (both to match what PETSc 3.26.0 pins, policy §9), and the one rebuild they force. Round 2 (2026-10-03/04) is built on all five hosts and was never staged, so
each host stages **one** drop per flavor that carries round 2 and this campaign together.
**Scope:** 6 packages, one row each, one cell per (host, flavor). Public binary flavors only
(`gcc`, `mkl`, `debug`).
**Column grouping:**

```
           ||      RHEL 9     ||     RHEL 10     || AMZN 2023 ||  Ubuntu 24 LTS  ||  Ubuntu 26 LTS
Package    || DBG | GCC | MKL || DBG | GCC | MKL || GCC | MKL || DBG | GCC | MKL || DBG | GCC | MKL
```

**Cell legend:** `[ ]` to do · `[x]` built **and installed** · `n/a` not built for that
flavor · `--` blocked (add a note under Blockers) · `kept: <reason>` not rebuilt (policy §6)

A cell is only ticked once the package is both rebuilt and installed on that host.

---

## A. The campaign — 6 packages, in build order

Rows are in `build_order.py` order for the `gcc` flavor (`G` = group); `mkl` and `debug` resolve
the same relative order for these packages.

`why`: **up** = upstream version bump · **opt** = build option change · **casc (x)** = unchanged
recipe, rebuilt because that dependency changed its SONAME.

| # | G | Package | why | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL | U26 DBG | U26 GCC | U26 MKL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 | hwloc 2.14.0-2 → 2.15.0-1 | up (PETSc pin) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 2 | 6 | scotch 7.0.15-2 (release kept) | opt (`-DSCOTCH_METIS_PREFIX=ON`) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 3 | 8 | armadillo 15.6.0 → 15.6.1 | up | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 4 | 10 | petsc 3.25.5 → 3.26.0 | up | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 5 | 11 | slepc 3.25.2 → 3.26.0 | up | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 6 | 11 | sundials 7.9.0-1 → -2 | casc (petsc) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

6 packages × 14 cells = **84 builds**. petsc is the longest.

**Why the cascade is one package.** Policy §6: consumers rebuild only when a dependency's SONAME,
exported ABI, headers or installed file names change.

- petsc 3.26.0 changes the SONAME to `libpetsc.so.3.26`. Its consumers are slepc (bumped anyway)
  and sundials (release +1; 7.9.0-1 is published).
- scotch: `libscotch`, `libptscotch` and `libesmumps` keep SONAME `7.0`. The prefix renames only
  the symbols of the METIS/ParMETIS emulation libraries, which on the macOS install only `libpetsc`
  and `libslepc` link. **mumps, strumpack and ipopt are not rebuilt.** Gate G3 below checks that
  claim on the pilot hosts instead of assuming it.
- armadillo is a leaf.
- hwloc keeps SONAME `libhwloc.so.15` (libtool `25:3:10` → `25:4:10` in upstream `VERSION`). Its
  consumers pmix, openmpi and spral are **not rebuilt**; petsc is rebuilt anyway. hwloc 2.14.0-2
  was never published, so 2.15.0-1 replaces it. Gate G3 covers this claim too.

scotch 7.0.15-2 was built in round 2 and never published, so the release stays at 2
(`doc/BUILD_EXECUTION.md` §0.6) and every host rebuilds it: the option changes what the build does
on every flavor (policy §6).

### Gates (fixed with this scope, policy §4)

The standing set of policy §4 (install and version match, drift sweep, meta-package installed,
`check_mkl_linkage.sh` on every flavor, `stage_to_belfem.sh --build`), plus three for this
campaign. They are defined here, before any build, so they block:

- **G1 — no unprefixed emulation symbols.** After scotch installs:
  `nm -D --defined-only <prefix>/lib/libptscotchparmetisv3.so libscotchmetisv3.so libscotchmetisv5.so | grep -E ' (METIS_|ParMETIS_|metis_|parmetis_)'`
  prints nothing.
- **G2 — PETSc's ParMETIS calls reach ParMETIS.** After petsc installs, build the five-line
  program below and run it with `LD_BIND_NOW=1 LD_DEBUG=bindings`: every `ParMETIS_V3*` symbol of
  `libpetsc.so` binds to `libparmetis.so`, and `SCOTCH_ParMETIS_V3_NodeND` to
  `libptscotchparmetisv3.so`.

  ```bash
  cat > /tmp/b.c <<'EOF'
  #include <petscsys.h>
  int main(int c, char **v){ PetscInitialize(&c,&v,NULL,NULL); return PetscFinalize(); }
  EOF
  source <prefix>/share/scls/activate
  mpicc /tmp/b.c -o /tmp/b $(pkg-config --cflags --libs PETSc) -Wl,-rpath,<prefix>/lib
  LD_BIND_NOW=1 LD_DEBUG=bindings /tmp/b 2>&1 | grep -E "ParMETIS_V3|SCOTCH_ParMETIS" | grep libpetsc
  ```
- **G3 — the packages that were not rebuilt still load.** After hwloc and scotch install and
  before anything else is built: `ldd -r` on `libpmix.so`, `libmpi.so`, `libdmumps.so`,
  `libstrumpack.so`, `libipopt.so` and `libspral.so` reports no undefined symbol;
  `mpirun -np 2 hostname` runs; Ipopt's hs071 solves with `linear_solver mumps` and with
  `linear_solver spral`.
  If this fails, the "no cascade" claim is wrong: stop, it is a B1 finding.

## B. What was verified on the dev host before this file was written

macOS, no `rpmbuild` — evidence level is static inspection plus `--spec-only`.

- The four new tarballs download from the recipe URLs (`curl -sSfL`): hwloc 2.15.0 (from the
  `v2.15` series directory), armadillo 15.6.1, petsc 3.26.0, slepc 3.26.0.
- Patches against the new tarballs, `patch -p1 --dry-run -N -F0` (Apple patch 2.0, not GNU patch):
  - armadillo (1): clean.
  - petsc `petsc-baijmkl-decls.patch`: **context refreshed.** Upstream rewrote the guard as
    `#if PetscDefined(HAVE_MKL_SPARSE)` and moved the block to `include/petscmat.h:467`. The two
    added lines are unchanged; it applies at fuzz 0 now. The upstream mismatch it fixes is still
    present in 3.26.0.
  - scotch (3): unchanged, the version does not move. `scotch-shared.patch` refreshed for 7.0.16
    is archived in `patches/scotch/archive/` for the day PETSc pins 7.0.16.
  - sundials (1): not re-checked, source unchanged.
- Version-stamped manifest lines edited: `files/petsc.txt` (`conf/modules/petsc/3.26.0`),
  `files/slepc.txt` (`conf/modules/slepc/3.26.0`).
- Scotch prefix, traced in the 7.0.16 source (the 7.0.11 tarball on this host has the same lines;
  7.0.15 itself was not read): `SCOTCH_METIS_PREFIX` is a `PUBLIC` compile
  definition of `scotchmetisv*` and `ptscotchparmetisv*` (`src/libscotchmetis/CMakeLists.txt:96-97,
  177-178`); with it the C names become `SCOTCH_*` and the Fortran names `scotchf*`/`SCOTCHF*`
  (`library_parmetis.h:77-110`). The tests link those targets and inherit the definition. No file
  name changes, so `files/scotch.txt` is unedited.
- PETSc 3.26.0's own package pins (`config/BuildSystem/config/packages/*.py`): scotch 7.0.15 with
  `-DSCOTCH_METIS_PREFIX:BOOL=ON`, superlu_dist 9.2.1 (minimum 6.3.0), mumps 5.9.1, strumpack 8.0.0,
  scalapack 2.2.3, hwloc 2.15.0, cmake 4.4.3, hdf5 2.2.0. After this campaign only hdf5 (1.14.6)
  and butterflypack (4.1.0 against 3.2.0) differ, both by Christian's ruling (policy §9).
- sundials 7.7.0 source (the copy on this host) uses only `Vec*`, `SNESSetFunction`, `SNESSolve`,
  `SNESGet*` and viewer calls from PETSc; 7.9.0 against PETSc 3.26.0 is not built anywhere yet.
- All 58 recipes parse; `validate_project.py` 0 errors; `build_order.py` resolves for `gcc`, `mkl`,
  `debug`; `--spec-only` (gcc) regenerates all six at the expected version-release with the expected
  patch count.

**Not verified, expect it at the first Linux build:**
- Manifest drift for petsc, slepc and hwloc (new minor series). `rpmbuild` fails on unpackaged files, so
  drift is a build error (class M), not a silent omission.
- scotch's own `ctest` with the prefix.

## C. Deliberately not in the campaign

| Package | Reported | Reason |
|---|---|---|
| scotch | 7.0.15 → 7.0.16 | Held by PETSc 3.26.0, which pins 7.0.15 (policy §9; Christian, 2026-10-04). The refreshed patch is archived. |
| superlu_dist | 9.2.1 → 9.3.0 | Held by PETSc 3.26.0, which pins 9.2.1 (policy §9). Not rebuilt: nothing it links changes. |
| cmake | 4.4.3 → 4.4.4 | Held by PETSc 3.26.0, which pins 4.4.3 (Christian, 2026-10-04: "we pin hwloc and cmake to petsc"). |
| vtk | 9.7.0 → 9.7.1 | Christian, 2026-10-04: next week. The longest build in the stack. |
| hdf5 | 1.14.6 → 2.2.0 (PETSc's pin) | Christian, 2026-10-04: "I don't want to update hdf5 on this round." Held by `max_major: 1`. |
| openssl | 3.6.2 → 3.6.5 | `include_flavors: [macos]`; not a binary package. Backlog. |
| butterflypack | 4.1.0 → 5.0.0 | Christian, 2026-10-04: "I don't want to do a major butterflypack jump at this time." It stays at 4.1.0, ahead of PETSc's 3.2.0 ("we can live with butterflypack being ahead for now"). No `max_major` pin was added. |
| automake | 1.18.1 → 1.19 | `include_flavors: [macos]`; build tool, not a binary package. |
| mumps, strumpack, ipopt | current | Link `libscotch`/`libptscotch`/`libesmumps`, whose SONAMEs do not change; not rebuilt (policy §6, gate G3). |
| gklib, parmetis, hdf5, suitesparse, zlib | — | Standing exclusions, unchanged from `todo/rebuild_campaign_20260922.md` §C. |

Everything else that came up while planning is in `todo/backlog.md`.

## D. Running it

**Pilot (policy §5): R9 and U24 first, all their flavors.** R10, AMZN and U26 start only after
both pilot hosts have every cell ticked, gates G1–G3 and the standing gates pass, each flavor is
staged with `--build`, and Christian has released the recipe commit by hash.

```bash
git checkout flavor.conf && git fetch --prune && git switch <branch> && git pull --ff-only
sed -i 's/^flavor: .*/flavor: debug/' flavor.conf    # canary flavor first; never commit flavor.conf
./scls build hwloc && ./scls install hwloc
./scls build scotch && ./scls install scotch         # then G1 and G3
./scls build armadillo && ./scls install armadillo
./scls build petsc && ./scls install petsc           # then G2
./scls build slepc && ./scls install slepc
./scls build sundials && ./scls install sundials
```

Then the standing gates, then `scripts/stage_to_belfem.sh --flavor <F> --column <C> --build`.
Use `/update-build`; class M/P/D fixes are committed on the branch and not pushed.

A finding is classified by policy §2 and reported in its format. Only B1–B4 stops the run;
anything else is appended to `todo/backlog.md` and the run continues. A recipe change after the
pilot needs a blocker.

Per-host instructions (sync, state before the campaign, order, the combined drop, host notes):
`todo/campaign_20261004_hosts.md`.

## Status

- 2026-10-04 — recipes, patches, manifests and changelogs committed on `ipopt`. No build yet.

## Blockers

(none)
