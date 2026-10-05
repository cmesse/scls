# EL10 (R10) build of the 2026-10-04 math campaign

**Date:** 2026-10-04 evening to 2026-10-05 (PDT; drop names are UTC 2026-10-05)
**Host:** EL10 build host (Rocky 10.2, GCC 14), tracker column `R10`, flavors debug, gcc, mkl
**Tracker:** `todo/rebuild_campaign_20261004.md`; host instructions `todo/campaign_20261004_hosts.md`.
**Recipe state:** `7623f57` on `ipopt`. No recipe, manifest, patch or builder change was made here.
**Commits (on `ipopt`, not pushed):** `5e1b971`, `4b57cbd`, `cc08a72` (tracker ticks), and the
commit that adds this file.

## 1. Start, release, sync

- The task arrived as a relay from the EL9 session. Christian in this session, asked whether he
  releases `7623f57` for EL10 although the DEB pilot (U24) had not built (policy §5): "It will
  fit, carry on", then "you have a go for the campaign".
- Local `ipopt` was one commit behind (`ef07cda`); fast-forwarded to `7623f57`.
- `flavor.conf`: `python: /home/mockbuild/Applications/python/bin/python3` for the session (the
  system `python3` has no `jinja2`); the venv's `bin/` was removed from `PATH` for every build,
  gate and staging command. Restored with `git checkout flavor.conf` at the end.
- sudo: `sudo -n true` fails by design on this host (grant scoped to dnf/apt-get/dpkg/rpm);
  `sudo -n rpm -q rpm` works. All installs ran without a prompt.
- Disk: 13 GB free on `/home` at the start, below the 20 GB of `doc/BUILD_EXECUTION.md` §1.4.
  Christian: "It will fit". It stayed at 13 GB through all three flavors.

## 2. State before the campaign

- Drift sweep over the full `build_order.py` list, debug, gcc and mkl: hwloc, scotch, mumps,
  armadillo, petsc, slepc, sundials, nothing else. `scls-<F>` 2026-2 installed.
- `check_mkl_linkage.sh` passes on debug, gcc and mkl.
- spral at `d908cfc`: the generated spec differs from the one at `21f141e` in nine added
  `%changelog` lines only, on all three flavors. Cells: `kept: changelog-only (d908cfc)`.

## 3. Builds

| Package | debug | gcc | mkl |
|---|---|---|---|
| hwloc 2.15.0-1 | installed | installed | installed |
| scotch 7.0.15-3 | installed | installed | installed |
| armadillo 15.6.1-1 | installed | installed | installed |
| petsc 3.26.0-1 | installed | installed | installed |
| slepc 3.26.0-1 | installed | installed | installed |
| sundials 7.9.0-2 | installed | installed | installed |
| mumps 5.9.1-3 | installed | installed | installed |
| ipopt 3.14.20-1, rebuilt | kept | kept | installed |

Gate that ran: `./scls build`, `./scls install` exit 0, installed version-release equal to the
recipe, package by package. Every package built at the first attempt; no class M, P or D fix.
The petsc and slepc manifest fixes from EL9 (`2594296`, `58cc158`) are sufficient on EL10.

- `petsc-baijmkl-decls.patch` applies with GNU patch at `--fuzz=0` without offset message, and
  petsc 3.26.0 builds on mkl with GCC 14 and the installed oneAPI, the case the patch is for.
- Build times, petsc: debug 808 s, gcc 512 s, mkl 3017 s. slepc, sundials, mumps and ipopt on
  mkl were also several times slower than on gcc (slepc 611 s against 112 s). The cause was not
  investigated; the VM shares a physical host with EL9 and AMZN.

## 4. Gates G1–G3

Run as written in the tracker (the code blocks extracted from the file; only the Ipopt source
path filled in). hs071 was built from `examples/hs071_cpp` unpacked from
`rpmbuild/SOURCES/ipopt-3.14.20.tar.gz`; the source tree was not on the host.

| Gate | debug | gcc | mkl |
|---|---|---|---|
| G1 | pass | pass | pass |
| G2 | pass | pass | pass, as written |
| G3 | pass | pass | failed after scotch on the known defect; passes after mumps and ipopt |

- G2, all three flavors: `ParMETIS_V3_PartKway`, `_Mesh2Dual`, `_AdaptiveRepart`, `_RefineKway`
  and `ParMETIS_V32_NodeND` of `libpetsc.so.3.26` bind to `libparmetis.so`;
  `SCOTCH_ParMETIS_V3_NodeND` binds to `libptscotchparmetisv3.so.7.0`.
- **G2 on mkl runs on EL10.** `LD_BIND_NOW=1 ./g2` exits 0; the loader segfault EL9 reported
  does not occur here. No substitute evidence was needed. Noted in the backlog entry.
- G3 on mkl, first run (mumps 5.9.1-2 installed): `ldd -r libdmumps.so` reports
  `libmkl_gf_lp64.so.3`, `libmkl_gnu_thread.so.3` and `libmkl_core.so.3` not found; `mpirun` and
  hs071 with mumps and spral ran. This is the defect fixed in `0a256a1`. After mumps 5.9.1-3 and
  ipopt were rebuilt: G3 passes. RUNPATH of `libdmumps.so`, `libsmumps.so`, `libmumps_common.so`,
  `libsipopt.so` and `libipopt.so` is
  `/opt/scls/mkl/lib:/opt/intel/oneapi/mkl/latest/lib/intel64:/opt/intel/oneapi/mkl/latest/lib`.
  No object in `/opt/scls/mkl/{lib,bin}` NEEDs `libmkl_*` without an MKL directory in RUNPATH.

## 5. Standing gates and drops

After the last build of each flavor: drift sweep empty, `scls-<F>` 2026-2 installed,
`check_mkl_linkage.sh` pass (debug: libgomp, libblas; gcc: libgomp, libopenblas; mkl: one layer,
`libmkl_gnu_thread`).

`work/publish/published-el10.txt` dated from 2026-09-25 and differed from belfem's public el10
repodata in 310 lines. It was regenerated from the `primary.xml` of `el10/x86_64` and
`el10/source` before the first select run and again after the debug promotion (254 NEVRAs). The
old file is kept as `published-el10.txt.20260925`.

belfem (session "Server"): contract v1.7, RPM drops unchanged from v1.6; no NEVRA collision.

| Drop | Files | Bytes | sha256(SHA256SUMS) | git_head | State |
|---|---|---|---|---|---|
| R10-debug-20261005T0641Z | 36 | 214186574 | `27aa94ef…6b7b` | `5e1b971` | uploaded; verified and promoted (belfem) |
| R10-gcc-20261005T0702Z | 31 | 203019227 | `03999e4f…5398` | `4b57cbd` | uploaded; verified and promoted (belfem) |
| R10-mkl-20261005T0850Z | 31 | 203057687 | `15eb48e6…3958` | `2faf7e1` | uploaded; verified and promoted (belfem) |

Each payload is the table of hosts file §4 and nothing else; `excluded: 0` on all three
(suitesparse is not installed on EL10); `scls-<F>-examples` is not in any payload.

Christian's approvals, in this session: "you can upload debug first and might want to build gcc
first", "you can go on and upload gcc", "you are also approved to upload mkl when done". This
releases EL10 ahead of the other hosts (policy §7). Each upload followed belfem's size OK.

The mkl drop was first staged as `R10-mkl-20261005T0846Z` at `cc08a72`. The belfem session was
unreachable then, so it was restaged as `…0850Z` at `2faf7e1` (same payload, same digest) after
the devlog commit, and uploaded after belfem's gcc promotion and size OK. Christian had the four
local commits pushed before that ("We can push now"); `origin/ipopt` was at `2faf7e1` for the mkl
drop.

## 6. ipopt on debug and gcc at the unchanged release; gate G2, new text

Instruction: `todo/el9_el10_ipopt_rebuild_20261005.md` (Christian's override: the rebuilt package
replaces a published RPM at the same NEVRA so the `%changelog` matches mkl). Built from the merge
`36264aa` (local R10 docs commits + `origin/ipopt` at `5901986`); no recipe, manifest, patch or
`python/` edit. AMZN and R9 were not building.

| | debug | gcc |
|---|---|---|
| built | 2026-10-05 03:59 PDT | 2026-10-05 04:04 PDT |
| `SHA256HEADER` before | `06e92da6…b438` | `70aa6c7d…efd8` |
| `SHA256HEADER` after | `20444709…a9ab` | `68a16715…5f51` |
| `PAYLOADDIGEST` before = after | `a6125ab6…b42e` | `58e7599a…1b0a` |
| G3 (`ldd -r` loop, `mpirun`, hs071 with mumps and spral) | PASS | PASS |

The payload digest is unchanged on both flavors and the header digest differs: the build is the
same and the `%changelog` is new, as the instruction expects. `rpm -q --changelog` starts with
the 2026-10-04 entry on both.

G2, text of `11e38af`, run verbatim from the tracker: `G2 PASS` on debug, gcc and mkl, each with
part (a) (six lookups: five `ParMETIS_*` in `libparmetis.so`, `SCOTCH_ParMETIS_V3_NodeND` in
`libptscotchparmetisv3.so.7.0`) and part (b) (loader log present, no "no loader log" note).

Standing gates on all three flavors: drift sweep empty, `scls-<F>` 2026-2, `check_mkl_linkage.sh`
pass. `work/publish/published-el10.txt` (258 NEVRAs) is identical to belfem's public el10
repodata fetched for this step, so it was not regenerated.

## Open

- Blocker: none on EL10.
- All three R10 drops are promoted; belfem reports el10 complete for this campaign (258 RPMs).
  A select run on each flavor against the regenerated published list gives an empty payload.
- Backlog: one note added to the existing entry on gate G2 (`todo/backlog.md`): it runs as
  written on EL10 mkl.
- AMZN shares the physical host and was told that EL10 has finished compiling.
