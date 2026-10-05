# U24: the 2026-10-04 math campaign; ipopt rebuilt on all three flavors

**Date:** 2026-10-05 (UTC)
**Host:** Ubuntu 24.04 build host (tracker column `U24`, noble), flavors debug, gcc and mkl.
**Tracker:** `todo/rebuild_campaign_20261004.md`; host instructions `todo/campaign_20261004_hosts.md`.
**Commits (on `ipopt`, not pushed):** the scope widening for ipopt, one tracker tick per flavor,
and this record. No recipe, manifest, patch, `python/` or `scripts/` change.

## 1. Sync and state before the campaign

- Branch `ipopt`. Built from `e7dde30` (debug) and `860347d` (gcc, mkl); the commits in between
  touch only `todo/`, `devlog/` and `scripts/stage_to_belfem.sh` (`b333cf8`, RPM path of
  `--replace`). Checked with `git diff --stat` over `recipes flavors files patches python packaging`
  before each rebase: empty. Rebases were done between flavors only, never during a build.
- Release and order: Christian, in session: the VM shares a physical host with AMZN, so U24 waited
  for AMZN's last build. AMZN reported it done; U24 then built. U26 was held the same way and got
  "host free" after the last mkl build and its gates.
- Drift sweep, all three flavors: hwloc, scotch, mumps, armadillo, petsc, slepc, sundials, nothing
  else. `scls-<F>` 2026-2 installed. `check_mkl_linkage.sh` passes on all three.
- Published mkl libraries before the rebuild (tracker, scope note for row 8): `libsipopt.so`,
  `libipopt.so`, `libdmumps.so` and `libmumps_common.so` already had RUNPATH
  `/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib`,
  and `ldd` reported nothing missing. The RUNPATH defect of the RPM hosts was not present in the
  published noble packages.
- Disk: 8.9 GB free at the start, below the 20 GB of `doc/BUILD_EXECUTION.md` §1.4.
  `prune_old_packages.sh` found 4 files, 0.0 MiB. With Christian's confirmation ("yes, delete the
  old drops and superseded tarballs"): the five staged drops of 2026-09-28 to 2026-10-02 and 36
  superseded tarballs in `work/sources/` removed; 11 GB free. Kept: every tarball a current
  recipe names, all patches, the test matrices. `work/build/*` was removed after each install and
  free space stayed at 11 GB through the run.

## 2. Scope: ipopt on debug and gcc

Christian, 2026-10-05: "I would prefer to rebuild ipopt anyways"; asked which flavors, he chose
all three on U24. Written into the tracker before the builds (+2 builds, 24 on this host). The
published debug and gcc .debs are replaced at the same version, as already ruled for mkl.

## 3. Builds

Gate that ran: `./scls build`, `./scls install` exit 0, installed version equal to the recipe's
version-release. No class M/P/D fix; the branch builds as it is.

| Package | debug | gcc | mkl |
|---|---|---|---|
| hwloc 2.15.0-1 | installed, 3m28s | installed, 2m47s | installed, 3m55s |
| scotch 7.0.15-3 | installed, 2m58s | installed, 2m28s | installed, 2m44s |
| armadillo 15.6.1-1 | installed, 0m51s | installed, 0m21s | installed, 0m28s |
| petsc 3.26.0-1 | installed, 14m58s | installed, 11m41s | installed, 24m02s |
| slepc 3.26.0-1 | installed, 2m40s | installed, 2m21s | installed, 6m34s |
| sundials 7.9.0-2 | installed, 5m12s | installed, 5m05s | installed, 13m18s |
| mumps 5.9.1-3 | installed, 4m07s | installed, 2m01s | installed, 7m10s |
| ipopt 3.14.20-1, rebuilt | installed, 4m12s | installed, 2m12s | installed, 8m54s |

The mkl times are about twice those of gcc. Not investigated; the physical host is shared.

## 4. Gates G1–G3

Run as written in the tracker; G2 with the text of `11e38af`, extracted from the tracker
mechanically (indent stripped), not retyped.

| Gate | debug | gcc | mkl |
|---|---|---|---|
| G1, after scotch | pass | pass | pass |
| G3, after scotch | pass | pass | pass |
| G2, after petsc | pass | pass | pass, without the "no loader log" note |
| G3, after ipopt | pass | pass | pass |

G3 on mkl passes already after scotch, unlike on the RPM hosts: the published Ubuntu mumps
5.9.1-2 carried the MKL RUNPATH (§1). RUNPATH of the four libraries after the rebuilds is the
same string as before.

The first gcc launch was stopped seconds into hwloc and restarted: its gate lines were piped
into `grep`, so a failed gate would not have stopped the builds. The partial hwloc tree was
removed first. Gate logs: `work/logs/<F>/gate-*.log` (gcc, mkl).

## 5. Standing gates and drops

Drift sweep empty on all three flavors after the last build, `scls-<F>` 2026-2 installed,
`check_mkl_linkage.sh` passes on the installed prefixes and on each staged drop.

Christian: "You have the go for all three drops", given while gcc was building and U26 had not
built; taken as the per-drop approval and as releasing U24 ahead of U26 (policy §7). belfem
(Server session): contract v1.7, DEB manifest body as the script writes it, `replace_published:`
accepted for .debs. Each drop was staged with `--build`, sized by belfem, then uploaded with
`--build --upload --drop <DROP>` and `--replace` naming `scls-<F>-ipopt`.

| Drop | Files | Bytes | sha256(SHA256SUMS) | git_head | State |
|---|---|---|---|---|---|
| `U24-debug-20261005T1120Z` | 35 | 140285302 | `2c2e626fcb4637032d4e399e0bf103bae0449bfefec013cfe3b50402128b430b` | `5ef32ba` | uploaded; verified and promoted (belfem) |
| `U24-gcc-20261005T1138Z` | 35 | 119515962 | `8e8b173dba6446bbb8c0ca2fd39b00b90455a7643eece1c3d652a06695331e06` | `0f771d8` | uploaded; verified and promoted (belfem) |
| `U24-mkl-20261005T1247Z` | 35 | 119515562 | `d144b1dcca7b584750dd92ce5a32abb94667ccb99ffa865c452dfc70cecccada` | `f50cb97` | uploaded; verified and promoted (belfem) |

- Each drop: 11 .deb (the seven packages, ipopt, and the petsc, slepc and sundials `-examples`)
  and 24 source files; `excluded: 0`, `no_source: 0`, `replace_published: 2` (ipopt binary and
  source); `already_published` 66 / 63 / 61. Payload upload rc 0, then READY, script exit 0.
- The `git_head` values are local commits of this host (origin plus tracker-only commits); the
  first two were rewritten by later rebases and exist only in the drops' manifests.
- belfem's results, relayed by its session; this host cannot check them: verify PASS on all
  three; el9 parity 97/97 objects matched, HARD 0, ALLOWED libquadmath (3) and libmvec (2); the
  Scotch emulation library does not export `ParMETIS_V3_PartKway`, `libpetsc` 3.26 NEEDs
  `libparmetis`, `libhwloc` SONAME `.so.15`; on mkl all 84 MKL objects NEED one threading layer.
- **ipopt replacement, belfem's comparison:** on debug, gcc and mkl the rebuilt .deb has an
  identical control file, file list and installed files; only the .deb container differs. The
  replacement changes nothing a user sees on noble.

- **Client check on U24 after the three promotions:** `apt-get update` clean; for the 33
  campaign packages (11 per flavor) the belfem candidate equals the installed version;
  `apt-get download` of petsc, mumps and ipopt for all three flavors gives files byte-identical
  (`cmp`) to `work/pkgs`, the replaced ipopt included. No upgrade was run.
- belfem after the mkl promotion: noble complete for this campaign, 132 binary packages,
  signature good, every .deb matches the signed index.

## 6. Backlog

- Removed: "Verify the 2026-10-04 staging change on a real DEB package database". Three
  `--build` runs here: the script runs to the end, `excluded: 0`, the `-examples` packages are
  selected, lapack's `blas`/`cblas`/`lapacke` are listed as already published.

## Open

- U26: rows 1–8, started after this host's last build.
