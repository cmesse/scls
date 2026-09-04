# SCLS AI Collaboration Protocol

**Date:** 2026-08-17
**Purpose:** Roles, communication standards, quality gates, and file conventions for Claude/Codex/Grok cooperation in the SCLS build system.
**Status:** Official extension of `CLAUDE.md` and `CODEX.md`. This file is the authoritative protocol.
**Origin:** Adapted from the BELFEM collaboration protocol. SCLS is a Python + YAML packaging system, not a C++/MPI solver — the roles carry over, the audit checklist and evidence ladder do not.

---

## 0. Instruction Precedence

If guidance conflicts across collaboration docs, apply this order:

1. `doc/AI_COLLABORATION_PROTOCOL.md` (this file)
2. `CLAUDE.md` (repository-specific guidance, architecture, build commands)
3. `CODEX.md` (pointer file — directs auditors to `CLAUDE.md`)
4. `README.md` (project philosophy and user-facing model)

Policy documents — `doc/LICENSE_POLICY.md`, `doc/MKL_ABI_POLICY.md`, `doc/MACOS_BUILD.md` — are authoritative within their own subject and override general guidance there.

---

## 1. Roles

**Claude Code — Primary AI (broad exploration)**

- Navigates recipes, flavors, and the Python builders; proposes recipe changes, version bumps, and refactors
- Writes implementation plans, documentation, and code changes
- Handles upstream lookups (release notes, `configure --help`, upstream build files) and license research
- Scope limit: flag spec-file expansion semantics, RPM/DEB metadata effects, cross-builder divergence, and license classification for auditor review rather than assuming they are correct

**Codex — Secondary AI (precision audit)**

- Audits Claude's findings for recipe/spec correctness, shell quoting and expansion, file-manifest accuracy, and Python logic errors in `python/`
- Double-checks critical claims: `%{buildroot}` vs `%{prefix}` handling, dependency completeness under `AutoReqProv: no`, flavor gating
- Validates the low-level correctness that broad exploration misses
- **Must prefer independent verification** over simple agreement, and ground audits in `CLAUDE.md` plus the relevant `doc/*_POLICY.md`
- Scope limit: does not restructure the builder architecture or change packaging policy unilaterally

**Grok — Secondary AI (refutation partner)**

- Symmetric to Codex, different training data and vendor; its value is disagreement, not synthesis
- Hunts over-claims, false operational detail, wrong file:line citations, and untested assumptions about upstream build systems
- Read-only, no shell (see §9)

---

## 2. Audience Tiers & the Communication Channel

### Audience Tiers

Collaboration artifacts are organized by their **reader**, and lifetime follows audience:

- **AI-only artifacts** — read only by AIs (the exchange). Ephemeral, machine-parseable, disposable. No human ever navigates them, so they can be garbage-collected aggressively.
- **AI+human artifacts** — read by both AIs and humans (`./devlog/` session logs, `changelogs/<package>.md`, `doc/*.md`, `./todo/` planning files). Curated for a human skimming for decisions.

An artifact is ephemeral **iff no human ever needs to return to it**. The boundary between the tiers is a **distillation** step, not a copy: at thread/session close the signal is *lifted* from the AI-only scratch into the durable record before the scratch is swept. That distillation is what makes aggressive GC of the AI-only tier safe.

**Format follows audience.** AI-only files stay machine-parseable — keep the `# AI`, `## Audit`, and `Confidence:` markers so the receiving model can orient — but need no human-prose polish. AI+human files are curated and distilled for a human reader.

### What is tracked in git, and what is not

This matters for where a conclusion is safe. Only the AI-only exchange is ephemeral; everything an AI or a human might come back to is tracked:

| Path | Tracked in git? | Tier |
|------|-----------------|------|
| `./tmp/ai_exchange/<slug>.md` | **No** (`tmp/` is git-ignored) | AI-only, ephemeral |
| `./devlog/` | **Yes** | AI+human, durable |
| `changelogs/<package>.md` | **Yes** | AI+human, durable |
| `doc/*.md` | **Yes** | AI+human, durable |
| `./todo/` | **Yes** | AI+human, durable |

`./todo/` is tracked in SCLS, so a live plan or build tracker reaches every machine — including the Linux build host, which is where most of the work in a `todo/` file actually happens. It is still **forward-looking planning, not the record of a conclusion**: `todo/` says what is intended, `devlog/` says what was found and decided. A finding that exists only as a to-do item is a finding nobody wrote down — if it is not in `devlog/`, `changelogs/`, or `doc/`, treat it as lost.

### Communication Channel — `./tmp/ai_exchange/<slug>.md` (AI-only, ephemeral)

The AI-to-AI exchange is a set of **sharded, ephemeral, per-task files** under `./tmp/ai_exchange/`: one file per topic, `./tmp/ai_exchange/<slug>.md`, where `<slug>` is a short `lowercase_underscore` topic tag (e.g. `petsc_mkl_soname`). **One topic per file.** Either AI may create, read, or append to the file for the current task at any time.

These files are AI-only scratch: machine-parseable, disposable, and never committed. The durable record of any conclusion lives in the devlog (§6), not here. Do not archive them — they are swept, not retained (see §10).

### Entry Format

Copy this format exactly for every entry:

```markdown
# CLAUDE 2026-08-17 14:20:00 PDT
## Query / Finding
Confidence: medium (~65%)

Body of the message. Reference specific files and line numbers.
Invite the partner AI to challenge the claim.

---

# CODEX 2026-08-17 14:25:30 PDT
## Audit & Verdict
Confidence: high

Codex's analysis. Checklist items addressed (with N/A noted).
Counter-points or confirmation with independent evidence.

---

# CLAUDE 2026-08-17 14:27:15 PDT
## Resolution / Next Action

Summary of outcome. What to do next.

---
```

**Rules:**
- Always start with `# AI_NAME YYYY-MM-DD HH:MM:SS TZ`
- One topic per file (`./tmp/ai_exchange/<slug>.md`); start a **new file** for a new topic
- No archiving and no size threshold — these files are ephemeral. Distil the conclusion into the devlog (§6) before the file becomes GC-eligible (see §10).

---

## 3. Communication Style — Calibrated Uncertainty

AIs are typically trained to sound confident. In this project, we do the opposite: **communicate uncertainty honestly** so the partner AI and the user can assess claims independently.

### Three-Tier Confidence

| Tier | Meaning | Action for receiving AI |
|------|---------|------------------------|
| **high** | Strong evidence, verified in the recipe/builder source and/or the upstream tarball | Spot-check is sufficient |
| **medium** (~N%) | Likely correct but not fully verified; add approximate % when helpful | Verify before acting on it |
| **low** | Educated guess, needs investigation | Treat as hypothesis, investigate independently |

### Examples

```
install.post in recipes/vtk.yaml:212 writes to %{buildroot}%{prefix}/share, which the
RPM post-processor will rewrite into a double %{buildroot}. [confidence: high —
confirmed against rpm_builder.py:_rewrite_install_post and the generated spec]

I think the missing symbol comes from the ScaLAPACK link line, but it could equally be
the OpenBLAS threading layer. [confidence: low — the build log is ambiguous]

Bumping hdf5 to 1.16 should not need a files/hdf5.txt change, since the cmake dir is
not version-stamped. [confidence: medium (~70%) — I read the 1.14 install tree, not
the 1.16 one]
```

**Why this matters:** when Claude says "I'm ~70% sure the manifest is unaffected," the auditor can spend its budget on that specific claim instead of re-reading the whole recipe.

**A note on the dev host.** The primary development host for SCLS is macOS (see §11). Many claims about RPM behaviour therefore *cannot* be executed here. Confidence must reflect that: "the spec generates correctly" is verifiable on macOS; "the RPM installs cleanly" is not, and must be stated as medium-or-below pending a Linux build host.

---

## 4. Audit Checklist

Before signing off on a Claude finding, the auditor addresses **only the relevant items**. Items that don't apply should be marked "N/A" — there is no requirement to comment on all nine for a localized fix.

| # | Item | What to check |
|---|------|---------------|
| 1 | **Recipe schema & flavor gating** | `include_flavors:` allowlist vs `exclude_flavors:` blocklist; omitted allowlist = all flavors, explicit `include_flavors: []` = opt-in only via `extra_packages:`; flavor-specific dependency dicts (`all:` + `<flavor>:` keys) resolve for every active flavor |
| 2 | **Install hooks & macro expansion** | `install.commands` takes explicit `%{buildroot}%{prefix}/…`; `install.post` takes bare `%{prefix}/…` because the RPM post-processor rewrites it — writing `%{buildroot}` there yields a double prefix. `%{srcdir}` is `$PWD` at spec-generation time and is only safe where the shell CWD is the source root (not in `install.post` for cmake recipes, where CWD is `build/`) |
| 3 | **File manifests** | `files/<package>.txt` matches what the build actually installs; version-stamped directories use `%{version}` rather than a literal `x.y.z`; no unowned directories, no missing or stale entries after a version bump |
| 4 | **Dependencies & build order** | `AutoReqProv: no` is deliberate — RPM/DEB metadata will **not** discover a missing dependency, so every runtime dependency must be explicit in the recipe. `environment` builds first; `build_order.py` must still resolve without a cycle |
| 5 | **Cross-builder consistency** | A change to one of `rpm_builder.py` / `deb_builder.py` / `unix_builder.py` must be checked against the other two. **Standing rule: always double-check `rpm_builder.py`** — it is the one with the most macro/spec subtlety and the easiest to leave behind |
| 6 | **Platform conventions** | Linux installs into `lib64/` with `lib -> lib64`; macOS uses `lib/` with no split. macOS additionally needs install-name fixups (`tools/fix_macos_install_names.sh`). No `-Zxz` on `dpkg-deb` — the stack has shipped zstd from day one |
| 7 | **Licensing policy** | `doc/LICENSE_POLICY.md` governs. No GPL-3 *linkable* libraries in distributed binary flavors; GPL-3 *build tools* are fine; GMP/MPFR/MPC come from system `*-devel` on mainline Linux flavors and are built in-stack only on `lbl`/`macos`; upstream license files must reach the package |
| 8 | **ABI and stack policy** | MKL major SONAME handling per `doc/MKL_ABI_POLICY.md`; no Python or other language bindings shipped (build-time use of system Python as a tool is fine — runtime ABI coupling to a user's interpreter is not) |
| 9 | **Update metadata & bump hygiene** | The `update:` block's strategy and `max_major:` pin are valid for the upstream in question; a version bump also updates `changelogs/<package>.md` and re-checks `files/<package>.txt` and every patch in `patches/<package>/` for drift |

---

## 5. Upstream-First Rule (Conditional)

SCLS has no literature routing. Its analogue is the **upstream source of truth**: the actual tarball in `work/`, the upstream `configure --help`, `CMakeLists.txt`, `INSTALL`, release notes, and license files.

Upstream verification is **mandatory** when the task involves:
- Adding, removing, or changing a configure/cmake flag
- Claiming which files a package installs, or editing `files/<package>.txt`
- Any license classification or `doc/LICENSE_POLICY.md` decision
- A version bump, or a claim that a patch in `patches/<package>/` still applies
- A claim about an upstream dependency requirement or minimum version

Upstream verification is **not required** for:
- Localized style fixes, typos, formatting
- Changes internal to the Python builders that do not alter emitted build commands
- Documentation edits that do not assert upstream behaviour

**When upstream is consulted, cite it concretely:** `upstream <package> <version>, <path>:<line>` for a file in the extracted tarball, or the release-notes URL. "The docs say" without a locatable source is not a citation, and the auditor should reject it as such.

---

## 6. Session Documentation — Devlogs in `./devlog/`

At the end of every meaningful session, create a devlog summary in `./devlog/` and update `./devlog/README.md` with a one-line entry linking the new file.

**The devlog is the durable AI+human distillation of the ephemeral exchange (§2).** The per-task `./tmp/ai_exchange/<slug>.md` files are AI-only scratch and are swept — and in SCLS `tmp/` is git-ignored, so nothing there ever reaches the repository. At session close, **lift the conclusion** — what was confirmed, refuted, or left open, with file:line evidence and confidence — into the devlog *before* the exchange file becomes GC-eligible.

**Division of durable records:**

- `./devlog/` — *what was investigated and decided, and why* (backward-looking, session-scoped)
- `changelogs/<package>.md` — *what changed in a package's shipped version* (user-facing, per-package). A version bump must land here regardless of whether a devlog is written
- `doc/*.md` — *standing policy* that outlives any one session. If a session establishes a rule rather than a fact, it belongs in a policy doc, and the devlog links to it
- `./todo/` — forward-looking planning and live trackers, **tracked**. Never the sole home of a conclusion: a plan records intent, a devlog records what was established

**Todo-file checkboxes (standing rule):** whenever a `./todo/` file lists steps, give each step a GitHub checkbox (`- [ ]`). Keep the boxes live: tick a box (`- [x]`) the moment its step completes, and **strike through** (`~~step text~~`) a step that becomes obsolete rather than deleting it, so abandoned approaches stay visible.

### Filename Format

`dlYYYYMMDD_topic.md`

Examples:
- `dl20260817_ai_collaboration_setup.md`
- `dl20260820_petsc_mkl_soname_audit.md`
- `dl20260822_vtk_manifest_drift.md`

### Required Header

Fill only the applicable fields:

```markdown
# Devlog 2026-08-17 — Topic

**Date:** 2026-08-17
**Topic:** Brief description
**AIs involved:** Claude, Codex, Grok
**Claude Confidence:** medium (~70%)
**Auditor Confidence:** high
**Flavor / Host:** mkl on macOS dev host (no rpmbuild available)
**Upstream References:** upstream hdf5 1.14.6, CMakeLists.txt:412
**Verification:** spec generation — `python python/rpm_builder.py --package hdf5 --flavor mkl --spec-only` clean @ <commit> (see §11; "reviewed" != "verified", name the highest evidence level actually reached)

## Summary

Brief description of findings and outcomes.

## Key Findings

- Finding 1 (with file:line references)
- Finding 2

## Changes Made / Proposed

- List of files modified, with brief rationale

## Open Questions

- Anything unresolved, especially anything that needs a Linux build host

## Files Updated

- recipes/foo.yaml
- files/foo.txt
```

### When to Write a Devlog

- End of any debugging or investigation session
- After a recipe refactor, a builder change, or a non-trivial version bump
- When resolving a significant exchange thread from `./tmp/ai_exchange/<slug>.md`

---

## 7. Edit Safety Rule

- **Investigation and review = read-only by default.**
- Writing to `./tmp/ai_exchange/` (AI-only exchange), `./todo/`, and `./devlog/` is always allowed.
- **Edits to `recipes/`, `flavors/`, `files/`, `patches/`, and `python/` only after the user explicitly says editing is approved.**
- Never invoke a real build (`./scls build`, `rpmbuild`, `dpkg-deb`) as part of an *investigation*. Builds are long, they write into `work/` and `rpmbuild/`, and on a shared host they are not free. Spec generation (`--spec-only`) and build-order resolution are read-only-ish and always fine.

---

## 8. Quick Start for Every Session

1. Read `CLAUDE.md` → this file (`doc/AI_COLLABORATION_PROTOCOL.md`).
2. Read the relevant policy doc (`doc/LICENSE_POLICY.md`, `doc/MKL_ABI_POLICY.md`, `doc/MACOS_BUILD.md`) if the task touches its subject.
3. Check the active flavor in `flavor.conf` — nearly every claim in SCLS is flavor-conditional.
4. Decide upstream-first or code-first (§5).
5. Open or append to the AI-only exchange for the current task, `./tmp/ai_exchange/<slug>.md`.
6. State your confidence and wait for the auditor when the exchange channel is in use.

---

## 9. Claude-Initiated Audit

Claude can invoke Codex or Grok directly — without waiting for the user to relay a prompt — when an independent check is warranted. This is the primary mechanism for covering blind spots that arise from training on different data and different company incentives.

### When Claude should call an auditor

Call proactively when:

- A claim about **spec/macro expansion, shell quoting, or generated build commands** could go either way and getting it wrong breaks a package
- A **dependency-completeness** claim is asserted but not proven — `AutoReqProv: no` means nothing catches a miss but a runtime failure on a user's machine
- A **licensing classification** affects what may be redistributed
- A **file manifest** claim after a version bump would silently ship a broken package
- Claude's own confidence is **medium or below** on anything that reaches a published repository

Do **not** call an auditor for typos, formatting, changelog prose, or anything where Claude is already high-confidence and the blast radius is a single local build.

### How to invoke

```bash
.claude/scripts/ask_codex.sh "Your audit prompt here"
.claude/scripts/ask_grok.sh  "Your audit prompt here"
```

Or pipe a longer prompt:

```bash
echo "Audit recipes/vtk.yaml install.post for a double %{buildroot}..." | .claude/scripts/ask_codex.sh -
```

Each script:
1. Resolves the per-task AI-only exchange path `./tmp/ai_exchange/<slug>.md` (slug from `$AI_EXCHANGE_SLUG`, else a sanitized session tag `sess_<id>` from `$CLAUDE_CODE_SESSION_ID`, else `scratch`), creating it if absent, and instructs the auditor to read the existing thread first
2. Prepends the role preamble (the auditor reads `CLAUDE.md` and this protocol)
3. Runs the auditor CLI read-only, rooted at the SCLS repo
4. Appends a `# CODEX` / `# GROK <timestamp>  (model=…, effort=…)` entry to the resolved exchange file
5. Echoes the response to stdout so Claude sees it inline

To pin a topic file explicitly, set `AI_EXCHANGE_SLUG=<topic>` before invoking either wrapper.

### 9.1 Depth Selection

Both wrappers take a model and a reasoning effort, and stamp both into the exchange entry. Choose
them before dispatch; do not let them default. The defaults exist so a bare invocation still works,
not as a tier — they were chosen to reproduce what the vendor configs gave on the day the wrappers
pinned them (2026-08-30), and an unchosen knob is marked `[defaulted]` in the record precisely so it
is not mistaken for a choice. That correspondence is an observation of a local config, not something
this repository can check; if the vendor config drifts, the wrapper defaults stay put.

| Subject | Codex | Grok |
|---|---|---|
| Prose sweep of an ordinary guide, README, or changelog; citation and doc-claim mechanics | `gpt-5.6-luna`, `medium` | not used |
| Prose sweep of a dense policy document (license policy, MKL ABI policy, this protocol) | `gpt-5.6-terra`, `medium` | not used |
| Single narrow claim (one macro expansion, one dependency, one manifest line), round 1 | `gpt-5.6-terra`, `medium` | `high` |
| Recipe, flavor, or builder-diff audit, round 1 | `gpt-5.6-terra`, `high` | `high` |
| Round ≥ 2, a round-1 split verdict, or a policy-boundary subject (license redistribution, MKL SONAME, cross-builder divergence, anything that reaches a published repository) | `gpt-5.6-terra`, `xhigh` | `xhigh` |
| Unattended post-commit `--quick` | `gpt-5.6-luna`, `medium` | `grok-4.6`, `medium` |

Grok's model column is `grok-4.6` throughout; only the effort varies.

```bash
CODEX_MODEL=gpt-5.6-terra CODEX_EFFORT=high AI_EXCHANGE_SLUG=<slug> .claude/scripts/ask_codex.sh - < prompt.md
GROK_MODEL=grok-4.6 GROK_EFFORT=high        AI_EXCHANGE_SLUG=<slug> .claude/scripts/ask_grok.sh  - < prompt.md
```

Four things the table encodes:

- **The key is the subject's scope and the round number, not the confidence of the claim under
  audit.** The claim's confidence is the thing being tested; ordering a cheap round because you feel
  sure is exactly backwards when you are confidently wrong.
- **The second rung raises effort, not model.** Moving both knobs at once makes it impossible to
  learn which one helped. `gpt-5.6-sol` is allowlisted as an escape hatch but is named by no row,
  pending a measured comparison on a real SCLS diff.
- **Effort is capped at `xhigh`.** This is a cost-and-conservatism policy, not a proven
  constraint: `max` has shown no measured benefit, and `ultra` is documented by the vendor as
  delegating to subagents — a different execution shape than the single-agent read-only audit the
  wrappers assume. Raise the cap only with a measurement.
- **Effort is not a substitute for a sharp prompt.** A narration-stub answer ("I'll check…") is a
  prompt-shape defect; no effort setting fixes it.

`scripts/cross_review.sh --jury` and `--relay` refuse to run unless all four variables are set, and
name this table when they do. `--quick` pins the cheap row itself and forces it onto the auditors,
so the unattended post-commit hook cannot be retuned by whatever shell happened to commit.

### Workflow

1. **Write a Claude query entry** to `./tmp/ai_exchange/<slug>.md` first (standard `# CLAUDE` header, §2 format), stating your claim and confidence.
2. **Call the script** with a focused audit prompt referencing specific files/lines, and with the
   depth from §9.1 set explicitly.
3. **Read the response** from stdout (or from the delta hook on the next prompt).
4. **Write a resolution entry** (`# CLAUDE … ## Resolution`) summarising what was confirmed, refuted, or left open.

### Three-AI round

`/cross-review` runs the frozen round: Claude pre-registers its own findings, `scripts/cross_review.sh` dispatches Codex and Grok (blind `--jury` by default, sequential `--relay` optional), then Claude verifies every citation and writes the reconciliation table. See `.claude/commands/cross-review.md`.

An opt-in post-commit hook (`scripts/install_autoreview_hook.sh`, gated on `SCLS_AUTOREVIEW=1`) runs a single auditor over each commit in the background and raises `tmp/ai_exchange/AUTOREVIEW_P0.flag` on P0 findings. `scripts/review_status.sh` reports the backlog. The hook never blocks a commit and is off unless the env var is set.

### Prompt quality

A good audit prompt is specific:

> "Audit `recipes/petsc.yaml:88-140`: with flavor `mkl`, does the generated configure line pass a consistent BLAS/LAPACK pair, or can `--with-blaslapack-dir` and the explicit `--with-scalapack-lib` resolve to different MKL threading layers? Check against `python/math_common.py`."

A poor prompt is vague:

> "Check if the petsc recipe is correct."

---

## 10. File Summary

| Path | Audience | Purpose | Lifetime |
|------|----------|---------|----------|
| `./tmp/ai_exchange/<slug>.md` | AI-only | Live, per-task AI-to-AI exchange (sharded by topic) | Ephemeral, git-ignored; sweep files older than 14 days |
| `./tmp/ai_exchange/autoreview.md` | AI-only | Post-commit auto-review log (`--quick` mode) | Ephemeral, git-ignored |
| `./tmp/ai_exchange/AUTOREVIEW_P0.flag` | AI+human | Open P0 findings from auto-review; clear when addressed | Ephemeral, git-ignored |
| `./devlog/dlYYYYMMDD_topic.md` | AI+human | Session summaries — the durable distillation | **Tracked**, persistent |
| `./devlog/README.md` | AI+human | Devlog index, one line per entry | **Tracked**, persistent |
| `changelogs/<package>.md` | AI+human | Per-package shipped-version history | **Tracked**, persistent |
| `doc/*.md` | AI+human | Standing policy (license, MKL ABI, macOS, this protocol) | **Tracked**, persistent |
| `./todo/*.md` | AI+human | Forward-looking task planning and live build trackers | **Tracked**, persistent |

---

## 11. Evidence Hierarchy

### "Reviewed" is not "verified"

A finding or change is *reviewed* when a static audit is complete. It is *verified* only when an executable gate has passed. Devlogs and exchange entries must not write "verified" for read-only work — write "reviewed", or name the actual gate that ran.

### Evidence ladder

Strongest first:

1. **Installed package** — the RPM/DEB installs on a clean target host and a dependent package builds against it
2. **Full package build** — `./scls build <package>` completes for the flavor, tests in the recipe's `test:` block pass, and the produced file list matches `files/<package>.txt`
3. **Generation gate** — `python python/rpm_builder.py --package X --flavor Y --spec-only` produces the expected spec, and `python python/build_order.py recipes --flavor Y` resolves without a cycle
4. **Upstream artifact inspection** — the claim is read out of the extracted tarball in `work/`, upstream `configure --help`, or the upstream build files
5. **Static source trace** — file:line reading of the recipe, flavor, or builder
6. **Upstream documentation consistency** — the claim matches release notes or upstream docs not independently checked against the source
7. **AI reviewer agreement** — concurring independent audits

Lower levels support, never replace, higher ones. Reviewer agreement is the weakest tier: three concurring audits do not lift a claim past level 5. Packaging-policy and licensing questions are adjudicated by Christian regardless of level.

### The macOS dev-host ceiling

The primary development host is macOS. `rpmbuild` does not run there, so **levels 1 and 2 are generally unreachable for RPM claims on the dev host, and level 3 is the practical ceiling.** This is not a defect of the work; it is a fact that must be stated rather than papered over. Any claim requiring level 1 or 2 is written as *pending a Linux build host*, and the devlog's `Verification:` line names the level actually reached. `unix_builder.py` builds do run on macOS, so macOS-flavor claims can reach level 2 locally.

### Review stop condition

A new audit round on the same subject requires at least one of:

- a **material change** to a recipe, flavor, manifest, patch, or builder since the last round,
- **new build evidence** (a failing or passing build, an install log, a generated spec),
- **reviewer disagreement** on a load-bearing point,
- a **policy boundary**: licensing, ABI, redistribution, or cross-builder divergence.

Otherwise the next step is the executable gate — a `--spec-only` run, a build on a Linux host, an install test — not another review.
