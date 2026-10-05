# AMZN: the 2026-10-04 math campaign; G2 rewritten; ipopt on gcc replaced at the same release

**Date:** 2026-10-05 (UTC)
**Host:** Amazon Linux 2023 build host (tracker column `AMZN`), flavors gcc and mkl. No debug flavor.
**Tracker:** `todo/rebuild_campaign_20261004.md`; host instructions `todo/campaign_20261004_hosts.md`.
**Commits (on `ipopt`, pushed on Christian's instruction):** `fa81730`, `8fa3495` (tracker ticks),
`b333cf8` (`stage_to_belfem.sh --replace` on the RPM path), `e7dde30` (status), `11e38af` (gate G2),
`9f96ed6` (todo for EL9 and EL10).

## 1. Sync and state before the campaign

- Branch `ipopt` at `7623f57`, level with origin; fast-forwarded to `2faf7e1` during the gcc run
  after checking that the four new commits touch only `devlog/` and `todo/`.
- Release: Christian, in session: "You can start building when EL10 is done." EL10 reported done
  on all three flavors before the first build here. U24 had not built yet (policy §5); Christian
  later released AMZN for upload ahead of the Ubuntu hosts ("Once the builds are done, you are
  approved to upload debug, gcc and mkl"; AMZN has no debug).
- Drift sweep, gcc and mkl: hwloc, scotch, mumps, armadillo, petsc, slepc, sundials, nothing else.
  `scls-<F>` 2026-2 installed. `check_mkl_linkage.sh` passes on both.
- spral at `d908cfc`: spec diff against `21f141e` is `%changelog` only on gcc and mkl. Cells are
  `kept: changelog-only (d908cfc)`.
- Disk: 7.3 GB free at the start, below the 20 GB of `doc/BUILD_EXECUTION.md` §1.4. With
  Christian's confirmation: `prune_old_packages.sh --apply` (14 files), the two staged drops of
  2026-09-25 and `rpmbuild/BUILD/*` removed; 8.5 GB free. The whole run then used 0.8 GB.

## 2. Builds

| Package | gcc | mkl |
|---|---|---|
| hwloc 2.15.0-1 | installed | installed |
| scotch 7.0.15-3 | installed | installed |
| armadillo 15.6.1-1 | installed | installed |
| petsc 3.26.0-1 | installed | installed |
| slepc 3.26.0-1 | installed | installed |
| sundials 7.9.0-2 | installed | installed |
| mumps 5.9.1-3 | installed | installed |
| ipopt 3.14.20-1, rebuilt | installed (§5) | installed |

Gate that ran: `./scls build`, `./scls install` exit 0, installed version-release equal to the
recipe. No class M/P/D fix; the branch builds as it is.

## 3. Gates G1–G3

| Gate | gcc | mkl |
|---|---|---|
| G1 | pass | pass |
| G2 as first written | pass | does not run: `LD_BIND_NOW=1 /tmp/g2` exits 139 |
| G2 as rewritten (§4) | pass, lookup and loader log | pass, lookup; loader log unavailable |
| G3 | pass; again after the ipopt rebuild | failed after scotch on `libdmumps` ("libmkl_* not found"), passes after mumps 5.9.1-3 and ipopt |

RUNPATH of `libdmumps.so`, `libsmumps.so`, `libmumps_common.so`, `libsipopt.so` and `libipopt.so`
on mkl after the rebuilds:
`/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib`.

## 4. Gate G2 on MKL flavors

Same symptom as on R9 mkl: under `LD_BIND_NOW=1` the test program exits 139 and the loader prints
"Relink `libmkl_gnu_thread.so.3' with `/lib64/libm.so.6' for IFUNC symbol `ceil'"; without
`LD_BIND_NOW` it exits 0. EL10 does not show it.

Measured here (glibc 2.34-231.amzn2023, intel-oneapi-mkl 2026.1.0): `libmkl_gnu_thread.so.3`
imports `ceil`, `sincos`, `log` and `sqrt` and NEEDs only `libdl.so.2` and `libpthread.so.0`;
`libmkl_core.so.3` and `libmkl_gf_lp64.so.3` do not NEED `libm` either. Inferred from the loader
message, not confirmed with a debugger (no gdb on the host): with eager binding the loader runs
libm's IFUNC resolver for an MKL relocation before libm itself is relocated. Why EL10 survives was
not examined.

Christian: "This should have been fixed hours ago". G2 in the tracker is rewritten (`11e38af`):

- (a) on every flavor: after `PetscInitialize` the test program looks up every ParMETIS symbol
  that `libpetsc.so` imports (`dlsym(RTLD_DEFAULT)` + `dladdr`); `ParMETIS_*` must come from
  `libparmetis.so`, `SCOTCH_ParMETIS_*` from `libptscotchparmetisv3.so`.
- (b) the loader's binding log as before, checked wherever the program survives `LD_BIND_NOW`;
  skipped with a printed note only when it exits non-zero with no libpetsc line in the log.

Results with the new text: gcc PASS with (a) and (b); mkl PASS with (a). On both flavors the six
imported symbols are `ParMETIS_V32_NodeND`, `ParMETIS_V3_AdaptiveRepart`, `ParMETIS_V3_Mesh2Dual`,
`ParMETIS_V3_PartKway`, `ParMETIS_V3_RefineKway` (all `libparmetis.so`) and
`SCOTCH_ParMETIS_V3_NodeND` (`libptscotchparmetisv3.so.7.0`). Against a wrong binding (policy §4):
with a preloaded library that defines `ParMETIS_V3_PartKway` the gate fails on gcc and on mkl.

Limit: (a) reports the global-scope lookup, which is how libpetsc's imports resolve, but it is not
the loader's record for libpetsc. belfem's arrival check on the mkl drop found independently that
`libpetsc` 3.26 NEEDs `libparmetis` and that the Scotch emulation library does not export
`ParMETIS_V3_PartKway`.

The backlog entry "Campaign gates G2 and G3 do not run as written on MKL flavors" is removed.

## 5. ipopt on gcc, rebuilt at the unchanged release

Scope addition by Christian (policy §1), 1 build on this host. The tracker had the cell as
`kept: build unchanged`; the installed gcc package was the round-2 build of 2026-10-04 and went out
in the first gcc drop. Christian: "I would rebuild ipopt anyways so that the changelogs are
identical"; after being told that 3.14.20-1 had been promoted an hour earlier: "I override this
rule for this time. We don't need to bump"; "you can ask belfem to write a patch that allows a
same-version replacement". Confirmed by him in the belfem session ("yes, I confirm the override. I
will also rebuild ipopt for el9 and el10").

- Rebuilt and installed (112 s). Binary digests: published build `SHA256HEADER 05b2640e…1276`,
  `PAYLOADDIGEST dd0a60d5…7af4`; rebuild `b00e329a…8029`, `fa8b4912…4b87`. G3 passes with it.
- `scripts/stage_to_belfem.sh` (`b333cf8`, approved by Christian in session; not audited):
  `--replace FILE --replace-reason TEXT` now selects a published NEVRA into the payload on the RPM
  path, with its SRPM, and writes both under `replace_published:`. A name that selects nothing
  exits 2. Select-only checks: without `--replace` 0 files and 85 already published; with
  `scls-gcc-ipopt` 2 files; an unknown name is refused.
- belfem patched its verifier and promotion for the same interface (relay, Server session).
- Known consequences (belfem, stated to Christian): clients with cached metadata can see a
  checksum mismatch on this package for up to 48 h; machines that installed the first build keep it.

`todo/el9_el10_ipopt_rebuild_20261005.md` asks EL9 and EL10 for the same on debug and gcc, and for
a re-run of G2 with the new text on all three flavors. Neither session was reachable when it was
written; the file is the handoff.

## 6. Standing gates and drops

Drift sweep empty, `scls-<F>` 2026-2 installed, `check_mkl_linkage.sh` pass on gcc and mkl after
the last build.

`work/publish/published-amzn2023.txt` dated from 2026-09-25 (104 of 166 lines stale). Regenerated
from belfem's public amzn2023 repodata (x86_64 and source `primary.xml`) before the first select
run and again after the gcc promotion; the old file is kept as `published-amzn2023.txt.20260925`.

| Drop | Files | Bytes | sha256(SHA256SUMS) | git_head | State |
|---|---|---|---|---|---|
| AMZN-gcc-20261005T0954Z | 31 | 202975269 | `41de47fa…e33c` | `2faf7e1` | uploaded, verified and promoted (belfem) |
| AMZN-mkl-20261005T1024Z | 31 | 202899916 | `d19795f9…3742` | `8fa3495` | uploaded, verified and promoted (belfem) |
| AMZN-gcc-20261005T1033Z (ipopt, `replace_published: 2`) | 2 | 2927173 | `c05c24ce…8363` | `9f96ed6` | uploaded and verified by belfem (manifest accepted as written; file list and Requires equal to the published RPM, `%changelog` carries the 2026-10-04 entry) and promoted: the published RPM and SRPM are the rebuild, the old builds are in belfem's attic |

Both 31-file payloads are the table in the hosts file §4 and nothing else. `excluded: 0` on every
run. belfem's note on the first gcc drop: `scls-gcc-examples` 2026-1 under `already_published:`
differs in digest from the published copy; that is the existing backlog entry on the examples
meta-package, and the package was not in the payload.

## Open

- Blockers: none on AMZN.
- Backlog entries added: none. Removed: the G2/G3 entry (§4).
- For other hosts: `todo/el9_el10_ipopt_rebuild_20261005.md` (EL9, EL10). Whether U24 and U26 also
  rebuild ipopt on debug and gcc is Christian's decision and is not asked for anywhere yet.
