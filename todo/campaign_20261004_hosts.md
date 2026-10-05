# 2026-10-04 math campaign — what each build host does

**Written:** 2026-10-04 on the macOS dev host.
**Tracker:** `todo/rebuild_campaign_20261004.md` (the package table, the gates G1–G3, the cells to
tick). **Policy:** `doc/CAMPAIGN_POLICY.md` — read it first; it decides what a session does with a
finding and when a host rebuilds.
**State:** round 2 (2026-10-03/04) is **published for U24 and U26** (uploaded and promoted
2026-10-05 UTC) and is built and installed but **not staged on R9, R10 and AMZN**. This campaign
builds six more packages per flavor on every host. The Ubuntu hosts then stage the six campaign
packages; the RPM hosts stage **one** drop per flavor that carries round 2 and this campaign
together.

**Names.** The hosts are EL9, EL10, AMZN (Amazon Linux 2023), U24 and U26. `R9` and `R10` below are
the column names of EL9 and EL10 in the tracker and in `stage_to_belfem.sh --column`; they are kept
because the staging script and belfem's drop names use them.

Cell legend: `[ ]` to do · `[x]` done · `n/a` not applicable · `kept: <reason>` not rebuilt (policy §6).

---

## 0. Order and rules

**Order (policy §5).** R9 and U24 are the pilot hosts and start now. R10, AMZN and U26 do §1 and
§2 now and start §3 only when both pilot hosts are through §4 and Christian has released the
recipe commit by hash.

| Phase | R9 | U24 | R10 | AMZN | U26 |
|---|---|---|---|---|---|
| §1 sync | [x] | [ ] | [x] | [ ] | [ ] |
| §2 state before the campaign | [x] | [ ] | [x] | [ ] | [ ] |
| §3 build the campaign, gates G1–G3 | [x] | [ ] | [x] | [ ] | [ ] |
| §4 standing gates, stage with `--build` | [x] | [ ] | [ ] | [ ] | [ ] |
| released for fan-out (Christian, commit hash) | pilot | pilot | [x] | [ ] | [ ] |
| §5 upload, per drop | [x] | [ ] | [ ] | [ ] | [ ] |

**Rules.**

- Only the class M/P/D fixes of `doc/BUILD_EXECUTION.md` §3 are made without asking (manifest
  drift is expected for petsc, slepc and hwloc). No other recipe, flavor, patch, `python/` or
  `scripts/` change.
- A finding is classified by policy §2 and reported in its format. Only B1–B4 stops the run.
  Everything else is appended to `todo/backlog.md` and the run continues.
- Commit on the branch, do not push (`doc/BUILD_EXECUTION.md` §0.2). Never commit `flavor.conf`.
- **Branch.** Pull the branch Christian names. He has announced merging `ipopt` into `main` and
  deleting `devel` and `ipopt`; for this campaign that overrides "be on `devel`" in
  `doc/BUILD_EXECUTION.md` §1.2.

## 1. Sync (every host)

```bash
git checkout flavor.conf          # the committed default is macos
git fetch --prune
git switch <branch> && git pull --ff-only
git log --oneline -1              # record the hash; staging writes it as git_head
```

## 2. State before the campaign

### 2a. The one fix the Ubuntu hosts have and the RPM hosts do not: spral at `d908cfc`

`d908cfc` (2026-10-04, made on U24) clears `CPATH` for spral on debug through
`configure.flavor_env`. It is the only build-relevant commit since the recipe state R9, R10 and
AMZN built from (`21f141e`).

- **U24, U26:** all three flavors already hold spral 2025.09.18-1 built from `d908cfc`
  (`devlog/dl20261004_u24_round2.md`, `dl20261004_u26_round2.md`). Nothing to do.
- **R9, R10, AMZN:** their spral 2025.09.18-1 predates the commit. `rpm_builder` never reads
  `configure.flavor_env`, so the generated spec is expected to differ in `%changelog` only.
  Confirm it per flavor; policy §6 then decides:

  ```bash
  F=<flavor>
  python python/rpm_builder.py --package spral --flavor $F --spec-only
  cp rpmbuild/SPECS/scls-$F-spral.spec /tmp/spral-$F-new.spec
  git worktree add /tmp/scls-old 21f141e
  ( cd /tmp/scls-old && ln -s "$OLDPWD/rpmbuild/SOURCES" rpmbuild/SOURCES 2>/dev/null; \
    python python/rpm_builder.py --package spral --flavor $F --spec-only && \
    cp rpmbuild/SPECS/scls-$F-spral.spec /tmp/spral-$F-old.spec )
  diff /tmp/spral-$F-old.spec /tmp/spral-$F-new.spec
  git worktree remove --force /tmp/scls-old
  ```

  - Diff inside `%changelog` only → the cell is `kept: changelog-only (d908cfc)`. No rebuild.
  - Any other difference → report it before doing anything. spral 2025.09.18-1 is published on
    noble and resolute, so whether an RPM-side rebuild keeps the release is Christian's call.

| spral at `d908cfc` | R9 dbg | R9 gcc | R9 mkl | R10 dbg | R10 gcc | R10 mkl | AMZN gcc | AMZN mkl |
|---|---|---|---|---|---|---|---|---|
| spec diff checked; kept or rebuilt | kept: changelog-only (d908cfc) | kept: changelog-only (d908cfc) | kept: changelog-only (d908cfc) | kept: changelog-only (d908cfc) | kept: changelog-only (d908cfc) | kept: changelog-only (d908cfc) | [ ] | [ ] |

### 2b. Drift sweep and linkage (every host, every flavor; read-only)

- Drift sweep over the full `build_order.py` list (`doc/BUILD_EXECUTION.md` §1.6). Expected:
  hwloc, scotch, armadillo, petsc, slepc and sundials, and nothing else. `scls-<F>` is installed at `2026-2`.
- `scripts/check_mkl_linkage.sh --flavor <F> --prefix /opt/scls/<F>` passes on every flavor.

### 2c. R9 only, once, before §3: today's ParMETIS binding (the "before" for gate G2)

```bash
P=/opt/scls/gcc/lib
nm -D --defined-only $P/libparmetis.so           | awk '{print $3}' | sort > /tmp/pm.txt
nm -D --defined-only $P/libptscotchparmetisv3.so | awk '{print $3}' | sort > /tmp/sc.txt
comm -12 /tmp/pm.txt /tmp/sc.txt                 # exported by both, before the prefix
readelf -d $P/libpetsc.so | grep NEEDED | grep -n -i 'metis\|scotch'
```

Then the five-line program of gate G2 in the tracker, against the installed petsc 3.25.5. Record
which library each `ParMETIS_V3_*` symbol of `libpetsc.so` binds to. On the macOS install,
`PartKway` and `Mesh2Dual` bind to Scotch's library
(`devlog/dl20261004_campaign_policy_and_math_campaign.md`).

## 3. Build the campaign (pilot hosts now; the others after release)

`/update-build` with `todo/rebuild_campaign_20261004.md`. Six packages per flavor, debug first
(AMZN: gcc, then mkl), in this order, with the tracker's gates where marked:

| # | Package | Version-release | After it |
|---|---|---|---|
| 1 | hwloc | 2.15.0-1 | — |
| 2 | scotch | 7.0.15-3, now with `-DSCOTCH_METIS_PREFIX=ON` | **G1**, then **G3** before anything else is built |
| 3 | armadillo | 15.6.1-1 | — |
| 4 | petsc | 3.26.0-1 | **G2** |
| 5 | slepc | 3.26.0-1 | — |
| 6 | sundials | 7.9.0-2 | — |

- pmix, openmpi, spral and strumpack are **not** rebuilt. G3 is the check.
- **Added 2026-10-04 (tracker rows 7 and 8, `0a256a1`):** after sundials, build and install
  mumps 5.9.1-3 on every flavor, and ipopt 3.14.20-1 (same release) on mkl; then re-run G3 on
  mkl. Ubuntu mkl: the published ipopt is replaced at the same version (tracker, scope note).
- **G2 on mkl** segfaults under `LD_BIND_NOW=1` (seen on R9; tracker Status). Report it; do not
  edit the gate. The `dlsym` + `dladdr` lookup in `devlog/dl20261004_r9_math_campaign.md` is the
  substitute evidence.
- Tick the cells in the tracker.

## 4. Standing gates and local staging (every host, per flavor)

1. Drift sweep empty; `scls-<F>` 2026-2 installed.
2. `scripts/check_mkl_linkage.sh --flavor <F> --prefix /opt/scls/<F>` passes.
3. `scripts/stage_to_belfem.sh --flavor <F> --column <R9|R10|AMZN|U24|U26>` (select and report),
   then the same with `--build` (stage and verify, no upload).

Expected payload per flavor, and nothing else:

| Package | Version-release | RPM hosts (R9, R10, AMZN) | Ubuntu (U24, U26) |
|---|---|---|---|
| hwloc | 2.15.0-1 | in the drop | in the drop |
| scotch | 7.0.15-3 | in the drop | in the drop |
| armadillo | 15.6.1-1 | in the drop | in the drop |
| petsc | 3.26.0-1 | in the drop | in the drop |
| slepc | 3.26.0-1 | in the drop | in the drop |
| sundials | 7.9.0-2 | in the drop | in the drop |
| mumps | 5.9.1-3 | in the drop | in the drop |
| ipopt (mkl only) | 3.14.20-1, rebuilt | in the drop (round 2 row below) | replaces the published one |
| environment | 2026-3 | in the drop (round 2) | already published |
| libunwind | 1.8.3-3 | in the drop (round 2) | already published |
| gperftools | 2.18.1-2 | in the drop (round 2) | already published |
| openmpi | 5.0.11-2 | in the drop (round 2) | already published |
| lapack, blas, cblas, lapacke | 3.12.1-2 | in the drop, debug only (R9, R10) | already published |
| spral | 2025.09.18-1 | in the drop (round 2) | already published |
| ipopt | 3.14.20-1 | in the drop (round 2) | already published |
| `scls-<F>` | 2026-2 | in the drop (round 2) | already published |

hwloc 2.14.0-2 and scotch 7.0.15-2 are published on noble and resolute and are superseded there by
this campaign; the RPM hosts never ship them.

- Everything else belongs under `already_published:`. A package in the payload that is not in
  this table is a finding: report it before anything is uploaded. Known candidate on R9 debug
  and gcc: scalapack 2.2.3-4, if belfem's el9 follow-up of 2026-09-25
  never happened. The stage script decides from belfem's published list; do not decide by hand.
- Report per drop, verbatim from the script: drop name, `file_count`, `total_bytes`,
  `sha256(SHA256SUMS)`, `excluded`, `already_published`, `git_head`, and the linkage result.

## 5. Upload (only on Christian's go-ahead per drop)

Policy §7: uploads of this campaign start once all five hosts are through §4. Then `/stage-drop`: one drop in
flight, debug → gcc → mkl per host, each after belfem's size OK and promotion of the previous
one. Use `--upload --drop <DROP>` so the bytes that were sized are the bytes that go. If the branch
head moved after §4, restage first.

## 6. Host notes

### EL9 (tracker column `R9`) — RPM pilot

**From the dev-host session, 2026-10-04 evening — read this before §1.** The EL9 session (`session_014CkV9f59rDdb9oVz4oXcDE`) could not
be reached with a direct message from the dev host, so the note is here. The host is **EL9**; `R9`
is only its column name in the tracker and in `stage_to_belfem.sh --column R9`. What changed on
the branch since EL9 last pulled
(`21f141e` recipe state), newest last:

1. **`doc/CAMPAIGN_POLICY.md` is new and in force.** A finding blocks only as B1–B4; everything
   else goes to `todo/backlog.md` in the policy's report format and the run continues. `todo/`
   was consolidated: the round-2 trackers are gone, this file and
   `todo/rebuild_campaign_20261004.md` replace them.
2. **The math campaign** (`3ae0c19` and follow-ups): hwloc 2.15.0-1, scotch **7.0.15-3** with
   `-DSCOTCH_METIS_PREFIX=ON`, armadillo 15.6.1-1, petsc 3.26.0-1, slepc 3.26.0-1,
   sundials 7.9.0-2. `petsc-baijmkl-decls.patch` has refreshed context for 3.26.0; it was checked
   with Apple `patch` only, so the first `rpmbuild --fuzz=0` here is its real test. Scotch is -3,
   not a same-release rebuild: 7.0.15-2 was published on noble and resolute this evening.
3. **Gates G1–G3 in the tracker are scripts that exit non-zero.** Run them as written; if one
   fails because of the gate itself, report it, do not edit it on the host.
4. **`57c7621` and `2cf1911` change `scripts/stage_to_belfem.sh`,** and EL9 is the first host to
   run it on a real rpmdb. The `rpm -qa` query now has a fifth field, `%{SOURCERPM}`, and a new
   `never_ship_reason()` excludes a binary when its own name **or its source package's** is a
   NEVER_SHIP recipe (so a subpackage of suitesparse cannot ship). It is checked twice: from the
   rpmdb, and again from the RPM file's own `SOURCERPM`. On the dev host it was tested only with
   the function extracted and canned input. **On the first `--flavor debug --column R9` select
   run (no `--build`), check and report:**
   - the script runs to the end under `set -u -o pipefail`;
   - `excluded:` contains nothing that was not excluded before (expected: empty on EL9, since
     suitesparse was removed from this host on 2026-09-25);
   - lapack's `blas`, `cblas`, `lapacke` and the `*-examples` packages are selected or listed as
     already published, not excluded;
   - `rpm -qa --qf '%{NAME} %{SOURCERPM}\n' 'scls-debug*' | awk '$2=="(none)" || $2==""'` prints
     nothing.
   A wrong exclusion here is a B1 finding: stop before `--build`.
5. **`python/rpm_builder.py` now calls `build_common.require_buildable()`** for the
   flavor/`extra_packages:` check. Messages are unchanged and `--spec-only` output for all 58
   recipes on gcc, mkl and debug was identical before and after on the dev host. Nothing to do;
   a "not built for" error on a package that built before would be a B1 finding.
6. Both changes went through plan and implementation audits (Codex and Grok, blind): no P0, no P1.
   Record: `devlog/dl20261004_campaign_policy_and_math_campaign.md`.

- **sudo grant is not durable** (no `/etc/sudoers.d/scls-build`). Round 2 ran on a cached login
  and one install failed when it lapsed. Christian, before §3:
  `scripts/grant_pkg_sudo.sh --user mockbuild --scope all --apply`.
- §2c is done here.
- Disk was 27 GB free on 2026-10-03. Three petsc builds plus three staged drops fit; prune with
  `scripts/prune_old_packages.sh` below about 10 GB.

### EL10 (R10)

- The system `python3` has no `jinja2`: set `python:` in `flavor.conf` for the session as on
  2026-10-04; restore with `git checkout flavor.conf`.
- Keep the venv's `bin/` off `PATH`.
- This is the host where `petsc-baijmkl-decls.patch` matters (GCC 14, oneAPI without
  `mkl_dcsrmv`). Its context was refreshed for 3.26.0 on the dev host with Apple `patch`; the
  first `rpmbuild` here applies it with GNU patch at `--fuzz=0`.

### Amazon Linux 2023 (AMZN)

- No debug column. sudo is a persistent `NOPASSWD: ALL` rule. Nothing else is open.

### Ubuntu 24.04 (U24) — DEB pilot

- **Disk: 9.5 GB free on 2026-10-04**, below the 20 GB `doc/BUILD_EXECUTION.md` §1.4 asks for.
  Three petsc builds will not fit. Before §3: `scripts/prune_old_packages.sh` (dry run, then
  `--apply` on Christian's confirmation), `sudo apt-get clean`, remove finished build trees
  under `work/build/`.
- **Auditors cannot run here** (bwrap blocked by `kernel.apparmor_restrict_unprivileged_userns=1`).
  A build-configuration change found necessary on U24 is audited from U26 or the dev host, or
  waits (policy §8).
- The gcc specs override that removes `--as-needed` is in place; `deb_builder` refuses to build
  without it.
- Debian package names map `_` to `-`.

### Ubuntu 26.04 (U26)

- sudo-rs: `scls build all`'s keepalive does not work; build and install package by package.
- 15 GB RAM: run petsc with `SCLS_JOBS=4`.
- GCC/gfortran 15.2: the host that found the `zlaqr5` miscompile. A numerical test failure in
  petsc or slepc that the other hosts do not show is a B2 finding; report the compiler flags.

## 7. Record (every host)

- [ ] Tick the cells here and in the tracker; add a dated Status line to the tracker.
- [ ] One devlog entry per host: the hash, §2 results, gate outputs, class M/P/D fixes, the drop
      reports. Its "Open" section holds only blockers or pointers to `todo/backlog.md` (policy §3).
- [ ] `git checkout flavor.conf`.
- [ ] After the last promotion: delete this file and remove the staging item from
      `todo/backlog.md` §1.
