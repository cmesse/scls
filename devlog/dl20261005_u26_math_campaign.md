# U26: the 2026-10-04 math campaign; ipopt rebuilt on all three flavors

**Date:** 2026-10-05
**Host:** Ubuntu 26.04 build host (tracker column `U26`, resolute; GCC/gfortran 15.2.0, 8 vCPUs,
15 GB), flavors debug, gcc and mkl.
**Tracker:** `todo/rebuild_campaign_20261004.md`; host instructions `todo/campaign_20261004_hosts.md`.
U26 mirrored U24 (`devlog/dl20261005_u24_math_campaign.md`) on Christian's instruction.
**Commits:** tracker and hosts-file ticks and this record. No recipe, manifest, patch, `python/` or
`scripts/` change.

## 1. Sync and state before the campaign

- Branch `ipopt`. debug and the first three gcc packages were built from `0d0f073`, the rest from
  `8591573`. Both differ from `860347d` (the state U24 built) only in `devlog/`, `todo/`, `doc/`,
  `web/` and `python/generate_website.py`; `git diff --stat` over `recipes flavors files patches
  python scripts packaging templates changelogs` showed nothing but the website generator. Pulled
  by fast-forward; `flavor.conf` was not touched while a build ran.
- Order: U26 shares a physical host with U24 and waited for U24's "host free" after its last mkl
  build and gates.
- Drift sweep, all three flavors: hwloc, scotch, mumps, armadillo, petsc, slepc, sundials, nothing
  else. `scls-<F>` 2026-2 installed. `check_mkl_linkage.sh` passes on all three.
- Published mkl libraries before the rebuild: `libsipopt.so`, `libipopt.so`, `libdmumps.so` and
  `libmumps_common.so` had RUNPATH
  `/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib`
  and `ldd` reported nothing missing, as on U24. They have the same RUNPATH after the rebuild.
- sudo non-interactive, the gcc specs override in effect (an unused `-lgomp` stays in NEEDED),
  25 GB free; 24 GB free at the end.

## 2. Scope: ipopt on debug and gcc

Christian to this session: "U24 is building the final round of its campaign. Reach out to it to
get instructions and mirror what it does", and then: "we don't keep, we rebuild ipopt for all
three, no bumping (overruled by me)". Written into the tracker before the builds (+2 builds, 24
on this host). The published resolute ipopt .debs are replaced at the same version.

## 3. Builds and gates

Gate that ran: `./scls build`, `./scls install` exit 0 and the installed version equals the
recipe's, per package; `work/build/*` removed after each install. petsc with `SCLS_JOBS=4`.

| Package | Version | debug | gcc | mkl |
|---|---|---|---|---|
| hwloc | 2.15.0-1 | installed | installed | installed |
| scotch | 7.0.15-3 | installed | installed | installed |
| armadillo | 15.6.1-1 | installed | installed | installed |
| petsc | 3.26.0-1 | installed | installed | installed |
| slepc | 3.26.0-1 | installed | installed | installed |
| sundials | 7.9.0-2 | installed | installed | installed |
| mumps | 5.9.1-3 | installed | installed | installed |
| ipopt | 3.14.20-1 (same release) | installed | installed | installed |

- No class M/P/D fix. No finding of class B1–B4.
- Campaign gates, extracted mechanically from the tracker text (two-space indent stripped, `P` set
  per flavor) and run with their exit status stopping the run: **G1 PASS** after scotch, **G3
  PASS** after scotch and again after ipopt, **G2 PASS** after petsc, on all three flavors. G2 is
  the text of `11e38af`; on mkl it printed a plain "G2 PASS", the loader survives `LD_BIND_NOW`
  here. Logs: `work/logs/<F>/c4_G{1,2,3}_*.log`.
- Standing gates after the last build of each flavor: drift sweep empty, `scls-<F>` 2026-2,
  `check_mkl_linkage.sh` PASS (mkl: one layer, `libmkl_gnu_thread`).
- GCC/gfortran 15.2: no numerical test failure in petsc, slepc, sundials, mumps or ipopt that the
  other hosts do not show.

## 4. Drops

Christian: "Once you have build, you are authorized to dropo", and for the first drop: "The server
is back. You are authorized to upload." Each drop was uploaded after belfem's size OK; contract
v1.7. Staged with `--replace` (one line, `scls-<F>-ipopt`) and the reason "ipopt 3.14.20-1 rebuilt
at the unchanged release (Christian, 2026-10-05, same-version override)".

| Drop | Files | total_bytes | sha256(SHA256SUMS) | already_published | git_head |
|---|---|---|---|---|---|
| `U26-debug-20261005T1527Z` | 35 | 141054466 | `d7aa865b1193bd0def6397a60568ac7e2aebb2955ce1f60b90e7c61fd4acb931` | 66 | `0d0f073` |
| `U26-gcc-20261005T1633Z` | 35 | 119544150 | `4dc89401ea18c7ec7be1e8a3439b392d0c936bd11795863ad0e0687dea03eb2c` | 63 | `8591573` |
| `U26-mkl-20261005T1634Z` | 35 | 119542324 | `0fb6f603bdc2d4c657dcc5bf30a3d69ba00cb7af6fabc7229b0af21f8d021ed5` | 61 | `8591573` |

Each: 11 binaries + 24 source files (the seven packages amd64 + source, petsc-, slepc- and
sundials-examples, and ipopt amd64 + source), `excluded: 0`, `no_source: 0`,
`replace_published: 2`, local `sha256sum -c` OK, linkage gate PASS. Payload rsync rc 0, then
`READY` separately, for all three.

- debug: verified by belfem (97/97 objects matched against el9, HARD 0; the scotch emulation
  library does not export `ParMETIS_V3_PartKway`, `libpetsc` 3.26 NEEDs `libparmetis`, `libhwloc`
  SONAME `.so.15`; the rebuilt ipopt differs from the published .deb in the container only) and
  promoted into resolute.
- gcc and mkl: uploaded; arrival result and promotion are belfem's and were pending when this was
  written.

## 5. Build times and the shared host

debug took 05:48–07:46 and the first half of gcc was as slow; U24 needed about 35 minutes per
flavor. While U24 was still running, a single-core Python loop of 10 million additions took 10.6 s,
3.3 s and 2.6 s in three consecutive runs on U26, with the VM 94 % idle otherwise. After Christian
switched the U24 VM off, mkl ran 08:49–09:33 (petsc 10 min, sundials 11 min, ipopt 6 min). The
cause was not determined from inside the VM (VirtualBox reports no steal time); host contention or
throttling is the reading that fits, and it would also fit the spral `ssidst` timings of round 2.
Backlog entry: `todo/backlog.md` §7.

## Open

No blocker. Pending at belfem: arrival result and promotion of the gcc and mkl drops, then the apt
client check on U26.
