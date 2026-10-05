# SCLS Campaign Policy — scope, blockers, gates, rebuilds, publishing

**Adopted:** 2026-10-04 (Christian), after the 2026-09-22 campaign and its round 2 took two weeks
instead of two days. The review of the devlogs from 2026-09-04 to 2026-10-04 is summarised in §10.

A *campaign* is one run of `/update-plan` → `/update-build` → `/stage-drop` over a fixed package
list on a fixed set of hosts. This file says what may change while a campaign is running and what
may not. `doc/BUILD_EXECUTION.md` describes how a single package is built and installed; where the
two overlap, this file decides *whether* something is done in the current campaign and that file
decides *how*.

The build-configuration approval rule in `CLAUDE.md` is unchanged and still comes first.

---

## 1. Scope is fixed when the tracker is approved

The tracker written by `/update-plan` is the scope: packages, hosts, flavors, and the gates of §4.
After Christian approves it:

- No package, builder feature, host or distribution is added. A new package or a new builder type
  (as ipopt, spral and `configure.type: meson` were in round 2) is its own campaign. A new host is
  brought up with `/build-stack` outside a running campaign; what it finds goes to the backlog.
- Christian can widen the scope. The session then writes the addition into the tracker with the
  number of builds it adds, before anything is built for it.

## 2. What blocks a campaign

A finding blocks the current campaign only if it is one of these:

| Class | Meaning |
|---|---|
| **B1 regression** | The campaign's own change makes a package worse than the published one. |
| **B2 broken** | Wrong numerical result, crash, or a package that cannot be installed or loaded. |
| **B3 licence** | Something ships that `doc/LICENSE_POLICY.md` forbids, or a required notice or source is missing from a package this campaign publishes for the first time. |
| **B4 cannot build** | The build or install fails and `doc/BUILD_EXECUTION.md` §3 (classes M, P, D) or `/build-fix-jury` cannot resolve it without a build-configuration change. |

Everything else goes to the backlog (§3), however cheap the fix looks. In particular these do
**not** block:

- a defect that is already in the published packages and that the campaign did not make worse
  (missing optional linkage, undeclared but satisfied dependencies, naming, inert options);
- a difference between hosts or builders that a parity report lists and that is not B2;
- missing tests, documentation, or tidiness.

Christian can promote a backlog item into the campaign. Nobody else can.

**How a finding is reported.** One block, in this order, so the decision does not need a
follow-up question:

```
finding:    <one sentence>
class:      B1 | B2 | B3 | B4 | backlog
since:      <published since when, or "introduced by <commit>">
evidence:   <command and output, or file:line>
radius:     <packages> x <host/flavor cells> = <builds>; release bump yes/no
proposal:   block and fix | backlog
```

A session does not present backlog items as open decisions at the end of a campaign. It lists the
backlog entries it added and stops there.

## 3. One backlog

`todo/backlog.md` is the only place where deferred work lives.

- Every finding that is not a blocker is appended there in the session that made it: build
  sessions, audit rounds ("pre-existing, out of scope"), parity reports, and reviews.
- A devlog's "Open" section may contain only campaign blockers and pointers to backlog entries.
  Before a session ends, each open item in its devlog is either a blocker in the tracker or a line
  in the backlog.
- `/update-plan` reads the backlog first. Christian picks what joins the next campaign; the rest
  stays.
- Entries are removed when done. The record of the work is the devlog and the changelog.

## 4. Gates are fixed with the scope

The tracker lists the gates a drop must pass. The standing set:

1. `./scls install` exits 0 and the installed version-release equals the recipe (`BUILD_EXECUTION.md` §0.4).
2. The drift sweep over the full `build_order.py` list is clean (`BUILD_EXECUTION.md` §1.6).
3. The flavor meta-package `scls-<F>` is installed.
4. `scripts/check_mkl_linkage.sh` passes on the installed prefix (every flavor: on non-MKL flavors
   it checks for one OpenMP runtime, one BLAS provider and no MKL).
5. `scripts/stage_to_belfem.sh --build` passes its own checks.

Rules:

- **All gates run on the build host, before upload.** A check that belfem runs on arrival and that
  has found a defect once is ported into the repository as a gate (backlog entry, next campaign).
- **A gate added during a campaign reports only.** It runs, its findings are classified by §2, and
  it becomes blocking with the next campaign. A new check does not fail work that passed the
  gates the campaign started with.
- A gate that cannot reproduce a known defect is not a gate. Its first run is against a tree that
  has the defect.

## 5. Pilot before fan-out

The campaign has two phases.

**Pilot.** One RPM host (R9) and one DEB host (U24) build the whole tracker on all their flavors,
pass every gate, and stage each flavor with `--build` (no upload). Recipe and builder fixes found
here are cheap: two hosts rebuild.

**Fan-out.** The remaining hosts start only after both pilot hosts are complete and Christian has
released the recipe state by commit hash. From then on the recipes are frozen: a change needs a
§2 blocker.

Before the campaign, not during it:

- A new recipe or a `python/` change has a real build on **one RPM host and one DEB host** before
  it enters a tracker. `--spec-only` and a macOS build do not count for Linux packages; the two
  builders set up different build environments (backlog: unify them).
- Both auditors answer a probe on the host that will make build-configuration changes (§8).

## 6. Rebuilds follow the payload

This amends `doc/BUILD_EXECUTION.md` §0.6.

When a recipe changes after a host has built the package, that host and flavor rebuild only if
the change alters what the build does there:

1. Generate the spec (RPM) or the build commands (DEB/unix) before and after the change, for that
   flavor.
2. If the only difference is `%changelog` text or comments, the host does **not** rebuild. The
   tracker cell gets the note `kept: changelog-only (<commit>)`.
3. Otherwise it rebuilds, at the same release while the version-release is unpublished and with
   `release:` +1 once it is published (§0.6 as before).

A change that only affects one builder (a `configure.flavor_env` that `rpm_builder` never reads,
a `.deb` mapping) therefore costs builds on that builder's hosts only. The source package of a
kept build carries the older changelog text; that is accepted.

Cascade rebuilds of consumers are owed only when the dependency's SONAME, exported ABI, headers
or installed file names change. A change of its `Requires`, its tests or its changelog is not a
reason to rebuild consumers.

## 7. Nothing is uploaded until every host has passed

Uploads start when all hosts of the campaign have passed the gates of §4 for all their flavors.
Then the drops go out as `/stage-drop` describes: one in flight, each after belfem's promotion
and Christian's go-ahead. Christian can release a single host earlier.

Reason: a defect found on the fourth host after the first two were published means replacing
published packages, which costs a release bump on every host or a contract override.

## 8. The audit gate is available or the change waits

A build-configuration change needs the review gate of `doc/AI_COLLABORATION_PROTOCOL.md`. If an
auditor cannot run on the host (login expired, sandbox blocked, tool missing), the audit runs on
a host where both work, or the change waits. An audit that cites no `file:line` did not run.
Christian can waive the gate for one change; the devlog records the waiver in his words.

Risks an auditor names in the plan round are either tested before the builds start or accepted
by Christian. They are not left to the first full rebuild to settle.

## 9. PETSc sets the versions of its dependencies

Adopted 2026-10-04 (Christian): "we always take the latest PETSc version and bump its
dependencies to that, regardless what the latest version is."

- **PETSc is taken at its latest release.** slepc follows it.
- **A package that PETSc can download itself is held at the version PETSc pins**, read from
  `config/BuildSystem/config/packages/<Package>.py` (`self.version`, `self.gitcommit`) in the
  PETSc tarball the campaign builds. A newer upstream release of such a package is not a
  candidate; it is listed in the tracker's §C as "held by PETSc <version>" and becomes one when
  PETSc moves its pin. First applied on 2026-10-04: scotch stays at 7.0.15 and superlu_dist at
  9.2.1 although 7.0.16 and 9.3.0 exist.
- **PETSc's build options for that package are the reference too**, unless a recipe comment
  records why SCLS differs (`-DSCOTCH_METIS_PREFIX=ON` came in this way).
- `/update-plan` compares every recipe that `recipes/petsc.yaml` passes to PETSc's configure
  against PETSc's pins and prints the table before the candidates.
- A patch that was refreshed for a version PETSc does not pin yet is kept under
  `patches/<pkg>/archive/` with a README line, so the work is not repeated.

Deviations from PETSc 3.26.0's pins, ruled on by Christian on 2026-10-04:

| Package | SCLS | PETSc 3.26.0 | Ruling |
|---|---|---|---|
| hwloc | 2.15.0 | 2.15.0 | "we pin hwloc and cmake to petsc"; bumped from 2.14.0 in the 2026-10-04 campaign |
| cmake | 4.4.3 | 4.4.3 | pinned to PETSc; 4.4.4 is held |
| butterflypack | 4.1.0 | 3.2.0 | "we can live with butterflypack being ahead for now"; strumpack 8.0.0 links it |
| hdf5 | 1.14.6 (`max_major: 1`) | 2.2.0 | "I don't want to update hdf5 on this round"; to be revisited, netcdf and exodus depend on it |

mumps, superlu, superlu_dist, scotch, strumpack, scalapack, parmetis, netcdf, zfp, openblas, slate,
gmp and openmpi match PETSc 3.26.0's pins.

## 10. Why these rules exist

From the devlogs of 2026-09-04 to 2026-10-04:

| Gap | What happened | Rule |
|---|---|---|
| No scope rule | ipopt, spral, meson, HSL and xz joined the fix round; U26 (GCC 15) joined mid-campaign | §1 |
| No blocker rule | gperftools without libunwind, inert scotch flags and triplet-prefixed tools had shipped for months and still caused a five-host round | §2 |
| No sink for findings | "pre-existing, out of scope" items stayed in devlog Open sections and came back as new issues | §3 |
| Gates invented mid-campaign | the linkage gate and the el9 parity check each failed work that was already built | §4 |
| Decisive checks ran at belfem | mixed MKL threading layers and `--as-needed` were found after upload | §4 |
| No pilot across builders | the pprof test failure showed on R10 after R9 was done; spral on debug failed on the first DEB host after all RPM hosts were done | §5 |
| Rebuilds for non-payload changes | scotch and libunwind were rebuilt so that `%changelog` matched; a DEB-only fix put a rebuild on RPM hosts | §6 |
| Publishing per host | noble debug and gcc were published, then relinked | §7 |
| Audit gate skipped | the MKL threading change and the openmpi PRRTE fix went in without an audit | §8 |

Two causes are engineering, not policy, and are in the backlog: the RPM and unix/deb builders set
up different build environments (`CPATH`, `LIBRARY_PATH`, argument expansion, `--as-needed`,
`flavor_pre/post`), and builds depend on undeclared host state.
