# R9 pilot of the 2026-10-04 math campaign; MUMPS/Ipopt MKL RUNPATH fix

**Date:** 2026-10-04 (evening, PDT; drop names are UTC 2026-10-05)
**Host:** R9 build host (Rocky 9.8), flavors debug, gcc, mkl
**Tracker:** `todo/rebuild_campaign_20261004.md`; host instructions `todo/campaign_20261004_hosts.md`.
**Commits (on `ipopt`, not pushed):** `2594296`, `58cc158` (class M), `0a256a1` (MUMPS/Ipopt
RUNPATH), tracker commits `b5a58ca`, `fb0462e`, `49c5710`.
The three later drops were staged and uploaded at `49c5710`.

## 1. Sync and state before the campaign

- Local `ipopt` was 20 commits behind; fast-forwarded to `a110ea7`.
- Drift sweep, all three flavors: hwloc, scotch, armadillo, petsc, slepc, sundials, nothing else.
  `scls-<F>` 2026-2 installed. `check_mkl_linkage.sh` passes on debug, gcc, mkl.
- spral at `d908cfc`: spec diff against `21f141e` is `%changelog` only on debug, gcc and mkl.
  Cells are `kept: changelog-only (d908cfc)`.
- §2c, gcc, petsc 3.25.5: 20 symbols exported by both `libparmetis.so` and
  `libptscotchparmetisv3.so`. `LD_BIND_NOW=1 LD_DEBUG=bindings`: `ParMETIS_V3_PartKway` and
  `ParMETIS_V3_Mesh2Dual` of `libpetsc.so` bound to `libptscotchparmetisv3.so.7.0`;
  `ParMETIS_V32_NodeND`, `ParMETIS_V3_AdaptiveRepart`, `ParMETIS_V3_RefineKway` to `libparmetis.so`.
  Same as on macOS.

## 2. Builds

| Package | debug | gcc | mkl |
|---|---|---|---|
| hwloc 2.15.0-1 | installed | installed | installed |
| scotch 7.0.15-3 | installed | installed | installed |
| armadillo 15.6.1-1 | installed | installed | installed |
| petsc 3.26.0-1 | installed (second build) | installed | installed |
| slepc 3.26.0-1 | installed (second build) | installed | installed |
| sundials 7.9.0-2 | installed | installed | installed |
| mumps 5.9.1-3 | installed | installed | installed |
| ipopt 3.14.20-1, rebuilt | kept | kept | installed |

Gate that ran: `./scls build`, `./scls install` exit 0, installed version-release equal to the
recipe. scotch's own `ctest` with the prefix ran inside the build on all three flavors.

Class M fixes, both found on debug:

- `2594296` petsc 3.26.0: `include/petsc/private/matmetisimpl.h`, `matparmetisimpl.h`,
  `lib/petsc/bin/search.py`, `lib/petsc/conf/rules_gm.mk` added to `files/petsc.txt`.
- `58cc158` slepc 3.26.0: `include/slepc/private/cupmblas.h`, `include/slepcconfiginfo.h` added to
  `files/slepc.txt`.

**The other hosts need both commits before they build petsc and slepc.**

## 3. Gates G1–G3

| Gate | debug | gcc | mkl |
|---|---|---|---|
| G1 | pass | pass | pass |
| G2 | pass | pass | does not run as written; see below |
| G3 | pass | pass | failed, fixed (§4), passes |

G2 on debug and gcc: every `ParMETIS_*` symbol of `libpetsc.so` binds to `libparmetis.so`,
`SCOTCH_ParMETIS_V3_NodeND` to `libptscotchparmetisv3.so.7.0`.

G2 on mkl: `LD_BIND_NOW=1 ./g2` exits 139. The loader prints "Relink
`libmkl_gnu_thread.so.3' with `/lib64/libm.so.6' for IFUNC symbol `sincos'" and the binding log
has no libpetsc line. Without `LD_BIND_NOW` the program exits 0. A two-line MKL program does not
crash under `LD_BIND_NOW`, `dlopen` of `libpetsc.so` under `LD_BIND_NOW` works, and hs071 (ipopt,
mumps) runs under it; only the PETSc-linked executable crashes. Whether petsc 3.25.5 on mkl
behaved the same was not measured. The gate was not edited. Substitute evidence, not the gate:
after `PetscInitialize`, `dlsym(RTLD_DEFAULT, s)` + `dladdr` gives `libparmetis.so` for
`ParMETIS_V3_PartKway`, `_Mesh2Dual`, `_AdaptiveRepart`, `_RefineKway` and `ParMETIS_V32_NodeND`,
and `libptscotchparmetisv3.so.7.0` for `SCOTCH_ParMETIS_V3_NodeND`; in the program's load closure
only `libparmetis.so` defines the unprefixed names. belfem's arrival checks on debug and gcc found
the same from the packages.

## 4. G3 on mkl: MUMPS and sIpopt without an MKL RUNPATH

```
finding:    libdmumps.so, libsmumps.so, libmumps_common.so (mumps 5.9.1-2) and libsipopt.so (ipopt 3.14.20-1) NEED libmkl_* with RUNPATH = prefix only
class:      backlog by policy §2 (in the published mumps since 2026-09); promoted into the campaign by Christian
since:      mumps: published 5.9.1-2 and earlier; ipopt: first build, 2026-10-03
evidence:   ldd -r libdmumps.so: three "libmkl_*.so.3 => not found"; readelf -d: RUNPATH /opt/scls/mkl/lib
radius:     mumps x 14 cells, ipopt x 5 mkl cells = 19 builds; mumps release bump yes, ipopt no
proposal:   block and fix (Christian: "We need to make that work now. We need to rebuild mumps")
```

Cause. MUMPS: the template's `RPATH_OPT` named the prefix only, and the MKL branch takes its link
line from `get_mkl_mpi_link_line()`, which has no MKL rpath (`get_math_link_line()` is the one
that adds it). Ipopt: `libsipopt.so` is linked by libtool through `libipopt.la`, whose
`dependency_libs` drop the `-Wl,-rpath` that `--with-lapack-lflags` gives `libipopt.so`.

Fix, `0a256a1`:

- `templates/mumps/Makefile.inc.j2`: on MKL flavors `RPATH_OPT` also names `<mklroot>/lib/intel64`
  and `<mklroot>/lib`. Both builders pass `context['mklroot']`. mumps release 2 → 3.
- `recipes/ipopt.yaml`: `configure.flavor_pre`, key `mkl`, appends the two rpaths to `LDFLAGS`.
  RPM only. Release kept.

Decisions (Christian, in session):

- "I approve the template change."
- mumps on all flavors: "we can afford rebuilding MUMPS on all flavors. I have changed my mind
  here. Version parity would be nice."
- Audit: "Let's do the audit, but with terra and medium."
- ipopt: "we do not bump ipopt, this is a manual override." Reason given: "nobody knows that the
  U26 repo exists. The vast majority of the community uses EL. The risk that one user downloaded
  U24 in the meantime is extremely low." At that time ipopt 3.14.20-1 was published on noble and
  resolute (all three flavors) and on el9 debug; el9 gcc was uploaded; el9 mkl was not published.
- Ubuntu: "We can rebuild ipopt on deb, better safe than sorry. No version bump." The published
  mkl .deb is replaced at the same version. That is the U24/U26 sessions' work.

Review gate. Plan round and implementation round, each blind, Codex `gpt-5.6-terra`/medium and
Grok `grok-4.7`/medium (`tmp/ai_exchange/mumps_ipopt_mkl_rpath*.md`).

| Round | Finding | Taken |
|---|---|---|
| Plan, Grok P1 | An `LDFLAGS=` configure argument for ipopt replaces the LDFLAGS the unix/deb builder exports, which already has the MKL rpath and `--no-as-needed` | yes: `flavor_pre` instead (my first plan was the `LDFLAGS=` argument) |
| Plan, Grok P1 / Codex P1 | key `mkl` matches `gcc-mkl-cuda` but not `intel`; the template change covers all three | accepted; `intel` in backlog |
| Plan, Grok (suggestion) | guarded `configure.pre` export to cover `intel` and deb | not taken: the unix builder runs each `pre` command in its own `sh -c`, so the export would not persist there (`python/unix_builder.py`, "Run any pre-configure commands") |
| Implementation, Codex P2, Grok P2 | changelog named gcc-only MKL libraries; Ubuntu sentence did not match the diff | yes, wording corrected |

Verified by build on R9 mkl: RUNPATH of `libdmumps.so`, `libsmumps.so`, `libmumps_common.so` and
`libsipopt.so` is `/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib`.
A sweep of `/opt/scls/mkl/{lib,bin}` finds no object that NEEDs `libmkl_*` without an MKL
directory in RUNPATH. G3 passes. Generated specs for debug and gcc: mumps differs in `Release`, a
comment in `Makefile.inc` and `%changelog`; ipopt in `%changelog` only.

Not verified: any DEB build; the `intel` and `gcc-mkl-cuda` flavors; whether the Ubuntu mumps and
ipopt packages have the defect.

## 5. Standing gates and drops

Drift sweep empty, `scls-<F>` 2026-2 installed, `check_mkl_linkage.sh` pass on all three flavors
after the last build.

The local `work/publish/published-el9.txt` dated from 2026-09-23, before the September R9 debug
promotion; the first `--build` for debug selected 70 files including 18 already-published
packages. The list is now regenerated from belfem's public el9 repodata (x86_64 and source
`primary.xml`); belfem confirmed repodata as authoritative. The old list is kept as
`published-el9.txt.20260923`. The list has to be regenerated after every promotion.

| Drop | Files | Bytes | sha256(SHA256SUMS) | State |
|---|---|---|---|---|
| R9-debug-20261005T0453Z | 34 | 207238473 | `d1f809f5…2451` | uploaded, verified and promoted (belfem) |
| R9-gcc-20261005T0504Z | 29 | 196273753 | `6b271ad2…677d` | uploaded, verified (belfem); promoted per repodata |
| R9-mkl-20261005T0551Z | 31 | 202916391 | `96ed3a57…6f07` | uploaded, exit 0; belfem's arrival result pending |
| R9-debug-20261005T0552Z (mumps) | 2 | 6736195 | `1ac42577…2e91` | uploaded, exit 0; belfem's arrival result pending |
| R9-gcc-20261005T0552Z (mumps) | 2 | 6735308 | `ec9f6576…c727` | uploaded, exit 0; belfem's arrival result pending |

Christian released R9 for upload ahead of the other hosts (policy §7): "You are authorized to
upload when you are ready"; "You can upload R9-gcc*". The debug drop was restaged from `…0452Z` to
`…0453Z` after a tracker-only commit moved the head; payload and digest were identical and belfem
accepted it.

## 6. Sync with the dev host; the changed staging script on a real rpmdb

Christian promoted all five drops; belfem's repodata lists mumps 5.9.1-3 and ipopt 3.14.20-1 on
debug, gcc and mkl. `origin/ipopt` had moved to `c7c3871` (`57c7621`, `2cf1911`: `require_buildable()`
in the builders, `never_ship_reason()` and `%{SOURCERPM}` in `stage_to_belfem.sh`; `8196929`,
`c7c3871`: hosts file). Merged, not rebased, so that the commit hashes written into the five drop
manifests (`git_head`) and into this file stay valid. No conflict. **All five drops were staged
with the script as of `a110ea7`, before this change.**

After the merge, on EL9:

- `bash -n scripts/stage_to_belfem.sh`, `py_compile` of `python/*.py` and
  `scripts/deb_drop_select.py`, `validate_project.py` (0 errors).
- `--spec-only` for mumps, ipopt and petsc on debug, gcc, mkl: identical to before the merge.
- Select-only run, all three flavors, with the published list regenerated after the promotions
  (258 NEVRAs): exit 0 under `set -u -o pipefail`; payload 0 files; `excluded: 1`.
- `--build` into a scratch stage with an empty published list, debug: 86 files selected,
  `sha256sum -c` OK, linkage pass. `excluded:` is `scls-debug-suitesparse-7.12.2-1` only, the same
  single exclusion as with the old script. `blas`, `cblas`, `lapacke`, `lapack` and the
  `petsc`/`slepc`/`sundials` `-examples` packages are selected. Scratch stage removed.
- `rpm -qa --qf '%{NAME} %{SOURCERPM}\n' 'scls-*' | awk '$2=="(none)" || $2==""'` prints nothing.
- The hosts-file note expected `excluded:` to be empty because suitesparse was removed from this
  host on 2026-09-25. It is installed: `scls-{debug,gcc,mkl}-suitesparse-7.12.2-1.el9`. Not
  investigated when or why it came back.
- `scls-debug-examples` and `scls-gcc-examples` are not installed on this host, so the script
  never sees them; `scls-mkl-examples` 2026-1 is listed as already published.

## Open

- Blockers: none on R9.
- Backlog entries added (`todo/backlog.md` §3): ipopt on `intel` without the fix; gates G2 and G3
  on MKL flavors.
- For the other hosts: tracker rows 7 and 8, and the Ubuntu ipopt replacement.
