# 2026-10-04 math campaign — build tracker

**Date:** 2026-10-04
**Branch:** `ipopt` (Christian merges it into `main` and deletes `devel` and `ipopt` himself; build
hosts pull the branch he names)
**Policy:** `doc/CAMPAIGN_POLICY.md`. This tracker is the scope (§1). Pilot hosts are R9 and U24
(§5). Nothing is uploaded until every host has passed (§7).
**Purpose:** PETSc 3.26.0 with slepc 3.26.0, armadillo 15.6.1, hwloc 2.15.0 and the Scotch
METIS-prefix option (both to match what PETSc 3.26.0 pins, policy §9), and the one rebuild they force. **Round 2 (2026-10-03/04):** published for U24 (noble) and U26 (resolute) on 2026-10-05 UTC; built
and installed but never staged on R9, R10 and AMZN. So the Ubuntu drops of this campaign carry the
six packages below, and the RPM drops carry round 2 and this campaign together.
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
| 1 | 2 | hwloc 2.14.0-2 → 2.15.0-1 | up (PETSc pin) | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 2 | 6 | scotch 7.0.15-2 → -3 | opt (`-DSCOTCH_METIS_PREFIX=ON`) | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 3 | 8 | armadillo 15.6.0 → 15.6.1 | up | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 4 | 10 | petsc 3.25.5 → 3.26.0 | up | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 5 | 11 | slepc 3.25.2 → 3.26.0 | up | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 6 | 11 | sundials 7.9.0-1 → -2 | casc (petsc) | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 7 | — | mumps 5.9.1-2 → -3 | fix (MKL RUNPATH; added 2026-10-04) | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [x] | [ ] | [ ] | [ ] |
| 8 | — | ipopt 3.14.20-1, same release | fix (MKL RUNPATH of `libsipopt`; added 2026-10-04) | [x] (rebuilt 2026-10-05, same release) | [x] (rebuilt 2026-10-05, same release) | [x] | [x] (rebuilt 2026-10-05, same release) | [x] (rebuilt 2026-10-05, same release) | [x] | [x] (rebuilt 2026-10-05, same release) | [x] | [x] | [x] | [x] | kept: build unchanged | kept: build unchanged | [ ] |

6 packages × 14 cells = **84 builds**. petsc is the longest.

**Scope widened by Christian on 2026-10-04 (policy §1), during the R9 pilot: +19 builds.**
Gate G3 failed on R9 mkl because `libdmumps.so`, `libsmumps.so`, `libmumps_common.so` and
`libsipopt.so` NEED `libmkl_*` with only the prefix in RUNPATH (`0a256a1`).

- Row 7, mumps 5.9.1-3: 14 cells. The build changes on MKL flavors only; the other flavors
  rebuild for version parity (Christian: "Version parity would be nice"). No consumer rebuild.
- Row 8, ipopt 3.14.20-1 at the same release: the 5 mkl cells. Christian: "we do not bump ipopt,
  this is a manual override". On RPM hosts the mkl package was never published. On U24/U26 the
  unix/deb build commands do not change, but the mkl package is rebuilt and the published one
  replaced at the same version (`stage_to_belfem.sh --replace`; Christian: "We can rebuild ipopt
  on deb, better safe than sorry. No version bump"). Check `readelf -d libsipopt.so` first and
  record what the published .deb had. The debug and gcc builds are unchanged everywhere.
- After mumps and ipopt install on an MKL flavor, re-run G3.

**Scope widened by Christian on 2026-10-05 (policy §1), before the U24 builds: +2 builds.**
Row 8, ipopt 3.14.20-1 at the same release, is also rebuilt on U24 debug and U24 gcc (Christian:
"I would prefer to rebuild ipopt anyways"; asked which flavors, he chose all three on U24). U24
therefore builds 24 packages: rows 1–7 on three flavors and ipopt on three. The build commands on
debug and gcc do not change; the published debug and gcc .debs are replaced at the same version
(`stage_to_belfem.sh --replace`), as already ruled for mkl. Before the mkl rebuild the published
U24 mkl `libsipopt.so`, `libipopt.so`, `libdmumps.so` and `libmumps_common.so` already carried
`/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib` in
RUNPATH and `ldd` reported nothing missing (read 2026-10-05 on U24). Other hosts are unchanged.

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
  consumers pmix, openmpi and spral are **not rebuilt**; petsc is rebuilt anyway. Gate G3 covers
  this claim too.

scotch goes to release 3: 7.0.15-2 is published on noble and resolute, and the option changes
what ships (`doc/BUILD_EXECUTION.md` §0.6). The RPM hosts never published -2 and go from the
published -1 to -3.

### Gates (fixed with this scope, policy §4)

The standing set of policy §4 (install and version match, drift sweep, meta-package installed,
`check_mkl_linkage.sh` on every flavor, `stage_to_belfem.sh --build`), plus three for this
campaign. They are defined here, before any build, so they block:

Each gate is a script that exits non-zero on a wrong result (implementation audit, Grok P1:
the first versions only printed, so a wrong binding or an unreadable library would have passed).
Set `P=/opt/scls/<F>` first.

- **G1 — no unprefixed emulation symbols.** After scotch installs:

  ```bash
  rc=0
  for l in libptscotchparmetisv3.so libscotchmetisv3.so libscotchmetisv5.so; do
    syms=$(nm -D --defined-only "$P/lib/$l") || { echo "G1 FAIL: cannot read $l"; rc=1; continue; }
    [ -n "$syms" ] || { echo "G1 FAIL: $l exports nothing"; rc=1; continue; }
    bad=$(printf '%s\n' "$syms" | awk '{print $NF}' | grep -E '^(METIS_|ParMETIS_|metis_|parmetis_|PARMETIS_)' || true)
    [ -z "$bad" ] || { echo "G1 FAIL: $l exports unprefixed:"; echo "$bad"; rc=1; }
    printf '%s\n' "$syms" | awk '{print $NF}' | grep -q '^SCOTCH_' || { echo "G1 FAIL: $l has no SCOTCH_ symbol"; rc=1; }
  done
  [ $rc -eq 0 ] && echo "G1 PASS"; ( exit $rc )
  ```

- **G2 — PETSc's ParMETIS calls reach ParMETIS.** After petsc installs. Rewritten 2026-10-05
  (Christian; found on R9 mkl, again on AMZN mkl): as first written the gate rested on
  `LD_BIND_NOW=1 LD_DEBUG=bindings` alone, and on MKL flavors of EL9 and Amazon Linux 2023 the
  loader dies there before `libpetsc.so` is bound (`libmkl_gnu_thread.so.3` imports `ceil`,
  `sincos`, `log` and `sqrt` without NEEDing `libm`; glibc 2.34 prints "Relink ... for IFUNC
  symbol" and the program exits 139). The gate now has two parts. (a) runs on every flavor: the
  test program looks up every ParMETIS symbol `libpetsc.so` imports in the global scope after
  `PetscInitialize` (`dlsym(RTLD_DEFAULT)` + `dladdr`) and the gate checks the library. (b) is
  the loader's binding log as before; it is checked wherever it exists and skipped with a
  printed note only when `LD_BIND_NOW` kills the program before libpetsc is bound. Checked on
  AMZN: passes on gcc with (a) and (b), on mkl with (a); fails on both when a preloaded library
  defines `ParMETIS_V3_PartKway`. Remove the two-space indent when pasting.

  ```bash
  cat > /tmp/g2.c <<'EOC'
  #define _GNU_SOURCE
  #include <dlfcn.h>
  #include <stdio.h>
  #include <petscsys.h>
  int main(int c, char **v){
    PetscInitialize(&c,&v,NULL,NULL);
    for (int i = 1; i < c; i++) { Dl_info d; void *p = dlsym(RTLD_DEFAULT, v[i]);
      printf("lookup %s %s\n", v[i], (p && dladdr(p,&d)) ? d.dli_fname : "UNRESOLVED"); }
    return PetscFinalize(); }
  EOC
  ( source $P/share/scls/activate
    mpicc /tmp/g2.c -o /tmp/g2 $(pkg-config --cflags --libs PETSc) -Wl,-rpath,$P/lib -ldl ) || { echo "G2 FAIL: build"; false; }
  rc=0
  syms=$(nm -D --undefined-only $P/lib/libpetsc.so | awk '{print $NF}' | grep -E '^(SCOTCH_)?(ParMETIS_|PARMETIS_|parmetis_)') || { echo "G2 FAIL: libpetsc.so imports no ParMETIS symbol"; rc=1; }
  for s in ParMETIS_V3_PartKway ParMETIS_V3_Mesh2Dual SCOTCH_ParMETIS_V3_NodeND; do
    printf '%s\n' "$syms" | grep -qx "$s" || { echo "G2 FAIL: libpetsc.so does not import $s"; rc=1; }
  done
  # (a) what every flavor can run: the global lookup libpetsc's imports go through
  /tmp/g2 $syms | grep '^lookup ' > /tmp/g2.lookup; [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "G2 FAIL: /tmp/g2 did not run"; rc=1; }
  [ "$(wc -l < /tmp/g2.lookup)" -eq "$(printf '%s\n' "$syms" | wc -l)" ] || { echo "G2 FAIL: lookup lines missing"; rc=1; }
  grep -E '^lookup (ParMETIS_|PARMETIS_|parmetis_)' /tmp/g2.lookup | grep -v '/libparmetis\.so' && { echo "G2 FAIL: a ParMETIS_* symbol resolves outside libparmetis (lines above)"; rc=1; }
  grep -E '^lookup SCOTCH_' /tmp/g2.lookup | grep -v '/libptscotchparmetisv3\.so' && { echo "G2 FAIL: a SCOTCH_ParMETIS_* symbol resolves outside libptscotchparmetisv3 (lines above)"; rc=1; }
  # (b) the loader's own binding log, where the loader survives LD_BIND_NOW
  LD_BIND_NOW=1 LD_DEBUG=bindings /tmp/g2 2>&1 | grep 'binding file .*libpetsc\.so' > /tmp/g2.log; bn=${PIPESTATUS[0]}
  if [ "$bn" -ne 0 ] && [ ! -s /tmp/g2.log ]; then
    echo "G2 note: no loader log, LD_BIND_NOW=1 /tmp/g2 exits $bn before libpetsc is bound (MKL: libmkl_gnu_thread imports libm IFUNC symbols without NEEDing libm); result rests on (a)"
  else
    for s in ParMETIS_V3_PartKway ParMETIS_V3_Mesh2Dual; do
      grep -q "to .*libparmetis\.so.*\`$s'" /tmp/g2.log || { echo "G2 FAIL: $s not bound to libparmetis"; rc=1; }
    done
    grep -E "\`ParMETIS_" /tmp/g2.log | grep -v 'to .*libparmetis\.so' && { echo "G2 FAIL: a ParMETIS_* symbol binds elsewhere (lines above)"; rc=1; }
    grep -q "to .*libptscotchparmetisv3\.so.*\`SCOTCH_ParMETIS_V3_NodeND'" /tmp/g2.log || { echo "G2 FAIL: SCOTCH_ParMETIS_V3_NodeND not bound to libptscotchparmetisv3"; rc=1; }
  fi
  [ $rc -eq 0 ] && echo "G2 PASS"; ( exit $rc )
  ```

  If `libpetsc.so` no longer imports one of the three named symbols, the gate fails: report it as
  a finding with `/tmp/g2.lookup` and `/tmp/g2.log`; do not edit the gate on the host.

- **G3 — the packages that were not rebuilt still load and run.** After hwloc and scotch install
  and before anything else is built. glibc's `ldd -r` exits 0 even with undefined symbols, so the
  output is searched:

  ```bash
  rc=0
  for l in libpmix.so libmpi.so libdmumps.so libstrumpack.so libipopt.so libspral.so; do
    out=$(ldd -r "$P/lib/$l" 2>&1) || { echo "G3 FAIL: ldd $l"; rc=1; continue; }
    printf '%s\n' "$out" | grep -E 'undefined symbol|not found' && { echo "G3 FAIL: $l (lines above)"; rc=1; }
  done
  ( source $P/share/scls/activate; mpirun -np 2 hostname ) || { echo "G3 FAIL: mpirun"; rc=1; }
  ```

  Then the solver run, as in round 2 (`devlog/dl20261004_r10_round2.md`): Ipopt installs no
  example, so build `examples/hs071_cpp` from the Ipopt 3.14.20 source tree in `work/` against
  the installed prefix and run it once per solver:

  ```bash
  cd <ipopt-3.14.20 source>/examples/hs071_cpp
  ( source $P/share/scls/activate
    g++ hs071_main.cpp hs071_nlp.cpp -o /tmp/hs071 $(pkg-config --cflags --libs ipopt) -Wl,-rpath,$P/lib
    cd /tmp
    for s in mumps spral; do
      echo "linear_solver $s" > ipopt.opt
      ./hs071 | tee /tmp/hs071_$s.log | grep -q 'Optimal Solution Found' || { echo "G3 FAIL: hs071 with $s"; exit 1; }
    done ) || rc=1
  [ $rc -eq 0 ] && echo "G3 PASS"; ( exit $rc )
  ```

  If G3 fails, the "no cascade" claim is wrong: stop, it is a B1 finding. G3 does not prove ABI
  compatibility of data structures; for hwloc that rests on upstream's libtool version
  (`25:3:10` → `25:4:10`, read from both `VERSION` files on 2026-10-04).

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
- hwloc 2.14.0 against 2.15.0, both tarballs: `libhwloc_so_version` is `25:3:10` and `25:4:10`
  (same `current - age` = 15, revision only). The installed public headers (`hwloc.h`,
  `hwloc/*.h`) differ in comments and in one line of an inline helper (`hwloc/helper.h`: a local
  variable gains `__hwloc_attribute_unused`). No declaration is removed or changed. Exported
  symbols were not compared; that needs a build.
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
- 2026-10-04 — review gate for the Scotch option closed. Plan round and implementation round, each
  blind, Codex `gpt-5.6-terra`/high and Grok `grok-4.7`/high. No finding against the recipe diff:
  the option reaches every flavor's configure line, and slepc and sundials are the only in-stack
  consumers of `libpetsc`. Taken from the implementation round: gates G1–G3 rewritten so that a
  wrong result exits non-zero (Codex P0: G1 as first written passed when forbidden symbols were
  present and searched two libraries in the current directory; Grok P1: G2 never checked the
  binding target, glibc `ldd -r` exits 0 on undefined symbols, hs071 is not installed);
  `libptesmumps` added to the changelog; the PETSc changelog and recipe comment corrected. Not
  taken: Codex's P2 to write `%{version}` in `files/petsc.txt` and `files/slepc.txt` (backlog).
  Still open by execution only: scotch's `ctest` with the prefix, and the pilot builds.
- 2026-10-04 — correction after pulling the Ubuntu sessions' commits: the U24 and U26 round-2 drops
  were uploaded and promoted this evening (`devlog/dl20261004_u24_round2.md`,
  `dl20261004_u26_round2.md`), so scotch 7.0.15-2 and hwloc 2.14.0-2 are published there. scotch
  is therefore 7.0.15-3, not a same-release rebuild as first committed.

- 2026-10-04 — R9: debug 7/7, gcc 7/7, mkl 8/8 built and installed (rows 1–7, and ipopt on mkl).
  2 manifest fixes, class M: petsc `2594296` (4 files), slepc `58cc158` (2 headers); the other
  hosts need both before they build. spral kept as changelog-only (`d908cfc`) on all three flavors.
  Gates: G1 pass on all three. G3 pass on debug and gcc; on mkl it failed on the MUMPS RUNPATH,
  fixed in `0a256a1` (review gate: two blind rounds, Codex gpt-5.6-terra/medium and Grok
  grok-4.7/medium), and passes after mumps 5.9.1-3 and ipopt were rebuilt. G2 pass on debug and
  gcc. **G2 does not run as written on mkl**: `LD_BIND_NOW=1` segfaults in the loader inside
  `libmkl_gnu_thread` before libpetsc is bound. Substitute evidence on mkl, not the gate:
  `dlsym(RTLD_DEFAULT)` + `dladdr` after `PetscInitialize` resolves the five `ParMETIS_*` symbols
  libpetsc imports to `libparmetis.so` and `SCOTCH_ParMETIS_V3_NodeND` to
  `libptscotchparmetisv3.so.7.0`. Gate not edited (backlog). Drops: R9-debug-20261005T0453Z
  promoted; R9-gcc-20261005T0504Z uploaded and verified by belfem. Both predate mumps 5.9.1-3.

- 2026-10-04 — R9 uploads (Christian released R9 ahead of the other hosts, policy §7). Standing
  gates pass on debug, gcc, mkl. `R9-debug-20261005T0453Z` and `R9-gcc-20261005T0504Z` promoted.
  Uploaded, script exit 0, size approved by belfem, arrival result pending:
  `R9-mkl-20261005T0551Z` (31 files), `R9-debug-20261005T0552Z` and `R9-gcc-20261005T0552Z`
  (mumps 5.9.1-3, 2 files each). Details: `devlog/dl20261004_r9_math_campaign.md`. Not done:
  R10, AMZN, U24, U26 (rows 1–8), and the Ubuntu ipopt replacement.
- 2026-10-05 — R10 (EL10), from `7623f57` released by Christian: debug 7/7, gcc 7/7, mkl 8/8 built
  and installed (rows 1–7, and ipopt on mkl). No class M/P/D fix. spral kept as changelog-only
  (`d908cfc`) on all three flavors. Gates: G1, G2 and G3 pass on all three; G2 runs as written on
  mkl here; G3 on mkl failed after scotch on the known `libdmumps` lines and passes after mumps
  5.9.1-3 and ipopt were rebuilt. Standing gates pass. Drops: `R10-debug-20261005T0641Z` uploaded,
  verified and promoted; `R10-gcc-20261005T0702Z` uploaded and verified by belfem, promotion
  pending; mkl staged with `--build` (31 files, 203057687 bytes), not uploaded: the belfem session
  was offline. Details: `devlog/dl20261005_el10_math_campaign.md`. Not done: the R10 mkl upload;
  AMZN, U24, U26 (rows 1–8), and the Ubuntu ipopt replacement.
- 2026-10-05 — R10 uploads (Christian released EL10 ahead of the other hosts, policy §7; one go per
  drop). `R10-debug-20261005T0641Z` and `R10-gcc-20261005T0702Z` promoted. `R10-mkl-20261005T0850Z`
  (31 files, 203057687 bytes, restaged at `2faf7e1` with the digest of the earlier `…0846Z`)
  uploaded, verified and promoted; belfem reports el10 complete. Not done: AMZN, U24,
  U26 (rows 1–8), and the Ubuntu ipopt replacement.
- 2026-10-05 — AMZN (Amazon Linux 2023), built from `7623f57`/`2faf7e1` (docs-only difference):
  gcc 7/7, mkl 8/8 built and installed (rows 1–7, and ipopt on mkl). No class M/P/D fix. spral
  kept as changelog-only (`d908cfc`) on both flavors. Gates: G1 and G3 pass on both (G3 on mkl
  failed after scotch on the known `libdmumps` lines and passes after mumps 5.9.1-3 and ipopt);
  G2 passes on gcc and does not run as written on mkl (`LD_BIND_NOW=1` exits 139, as on R9;
  the `dlsym` + `dladdr` substitute resolves the five `ParMETIS_*` symbols to `libparmetis.so`
  and `SCOTCH_ParMETIS_V3_NodeND` to `libptscotchparmetisv3.so.7.0`). Standing gates pass.
  Drops: `AMZN-gcc-20261005T0954Z` (31 files, 202975269 bytes) uploaded, verified and promoted;
  `AMZN-mkl-20261005T1024Z` (31 files, 202899916 bytes) uploaded, script exit 0, arrival result
  pending. Scope addition by Christian, 2026-10-05: ipopt
  3.14.20-1 on gcc is rebuilt at the unchanged release so its `%changelog` matches mkl ("I
  override this rule for this time. We don't need to bump"), and replaces the published
  package through `stage_to_belfem.sh --replace` on the RPM path (`b333cf8`); he announced the
  same for el9 and el10 in the belfem session. Rebuilt and installed on AMZN gcc; G3 passes
  with it. Not done: the AMZN gcc ipopt replacement drop; U24, U26 (rows 1–8), and the Ubuntu ipopt replacement.
- 2026-10-05 — gate G2 rewritten (Christian: "This should have been fixed hours ago"), see the
  gate text. Re-run on AMZN with the new text: gcc PASS with the lookup and the loader log; mkl
  PASS with the lookup, loader log unavailable (exit 139 under `LD_BIND_NOW`). The G2 results
  recorded above for R9 mkl ("does not run as written", substitute evidence) and for AMZN mkl
  are the same lookup the gate now performs. U24 and U26 run the new text.
- 2026-10-05 — AMZN drops: `AMZN-mkl-20261005T1024Z` verified and promoted. Replacement drop
  `AMZN-gcc-20261005T1033Z` (ipopt 3.14.20-1 x86_64 and src, `replace_published: 2`, 2927173
  bytes) uploaded, verified and promoted; it is the first RPM drop staged with `--replace`, and
  belfem reports amzn2023 complete for this campaign (88 x86_64 + 82 source RPMs). AMZN is complete: gcc 8/8 (row 8 rebuilt by Christian's override), mkl 8/8.
  Details: `devlog/dl20261005_amzn_math_campaign.md`. Not done: EL9 and EL10 ipopt on debug and
  gcc and their G2 re-run (`todo/el9_el10_ipopt_rebuild_20261005.md`); U24, U26 (rows 1–8), and
  the Ubuntu ipopt replacement.

- 2026-10-05 — R9: ipopt 3.14.20-1 rebuilt and installed on debug and gcc at the unchanged release
  (`todo/el9_el10_ipopt_rebuild_20261005.md`, Christian's override). G3 passes on both. G2 with the
  text of `11e38af`: PASS on debug and gcc with both parts; on mkl the "no loader log" note and
  PASS on part (a). Drift sweep empty, linkage pass on all three flavors. Replacement drops
  `R9-debug-20261005T1053Z` and `R9-gcc-20261005T1053Z` (2 files each, `replace_published: 2`):
  size approved by belfem, uploaded, script exit 0; arrival result and promotion pending.
- 2026-10-05 — R10: ipopt 3.14.20-1 rebuilt and installed on debug and gcc at the unchanged release
  (`todo/el9_el10_ipopt_rebuild_20261005.md`, Christian's override), from the merge `36264aa`.
  `SHA256HEADER` differs from the published build on both, `PAYLOADDIGEST` is the same. G3 passes
  on both. G2 with the text of `11e38af`: PASS on debug, gcc and mkl with both parts (the loader
  survives `LD_BIND_NOW` on EL10). Drift sweep empty, `scls-<F>` 2026-2, linkage pass on all three
  flavors. Details: `devlog/dl20261005_el10_math_campaign.md` §6.
- 2026-10-05 — R10 replacement drops, staged at `b9f201b` with `--replace`:
  `R10-debug-20261005T1112Z` (2 files, 2933201 bytes) and `R10-gcc-20261005T1112Z` (2 files,
  2932700 bytes), `replace_published: 2` and `excluded: 0` on each. Uploaded on Christian's
  approval in the R10 session ("drops authorized"; both at once, with his confirmation of the
  size OK, since no belfem session was reachable from this host); script exit 0 on both.
  Not done: the report to belfem, arrival result and promotion of both drops; U24, U26
  (rows 1–8), and the Ubuntu ipopt replacement.

- 2026-10-05 — U24, from origin `860347d` (no build-relevant change since `2faf7e1`): debug 8/8,
  gcc 8/8, mkl 8/8 built and installed (rows 1–7, and ipopt on all three after Christian widened
  the scope by 2 builds). No class M/P/D fix. Gates: G1, G2 (text of `11e38af`, plain pass on mkl
  too) and G3 pass on all three; G3 on mkl passed already after scotch, because the published
  Ubuntu mumps 5.9.1-2 carried the MKL RUNPATH. Standing gates pass. Drops, each with
  `replace_published: 2` (ipopt) and `excluded: 0`: `U24-debug-20261005T1120Z` (35 files,
  140285302 bytes) and `U24-gcc-20261005T1138Z` (35 files, 119515962 bytes) uploaded, verified
  and promoted by belfem; `U24-mkl-20261005T1247Z` (35 files, 119515562 bytes) uploaded and
  verified by belfem, promotion pending. belfem: on all three flavors the rebuilt ipopt differs
  from the published .deb in the container only. Details:
  `devlog/dl20261005_u24_math_campaign.md`. Not done: the mkl promotion; U26 (rows 1–8), started
  after U24's last build.

## Blockers

(none)
