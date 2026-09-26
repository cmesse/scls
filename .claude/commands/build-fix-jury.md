---
description: Unattended-build escalation — when a package fails outside the M/P/D auto-fix classes, diagnose it, run the fix past the Codex + Grok jury, and either land a reviewed local fix or park the package as a blocker and keep building the rest.
argument-hint: "<package> <flavor>"
---

Resolve the build failure of: $ARGUMENTS

This is the SCLS adaptation of BELFEM's `code-with-jury` loop, reshaped for an **unattended**
build run: there is no human at the two stops, so the stops become the jury's verdict and a hard
scope boundary. It sits between `doc/BUILD_EXECUTION.md` §3 (the M/P/D auto-fix classes) and §4
(the halt protocol). Use it only when a failure has already been triaged as *not* M, P or D, or as
M/P/D that hit its own stop condition.

**Authority.** Christian, 2026-09-26, for the U26 full-stack run: "you are authorized to use Fable,
as well as the Astra and Grok jury to attempt fixes". That is the maintainer approval that
`CLAUDE.md` requires for a build-configuration change, **bounded by the scope table below and
valid for local commits only**. Nothing produced by this loop is pushed; Christian reviews every
commit before it reaches another host.

## 1. Scope — what the jury may fix

| Kind of fix | Tier |
|---|---|
| New patch in `patches/<pkg>/` that makes upstream source compile or link with a newer toolchain / libc / CMake / Python (missing `#include`, removed legacy API, stricter C23/C++ defaults, `-Werror` tripping on a new warning *in upstream code*) | **J** — jury may land |
| Test-harness fix: a `test:` command that fails for an environmental reason (oversubscription, missing `HOME`, a hard-coded path), with the tests themselves unchanged | **J** |
| `files/<pkg>.txt` or `packaging/system_packages.yaml` beyond what Class M/D allows, when the jury traces the cause | **J** |
| `python/` builder fix whose effect is confined to the DEB path or to this host's condition, and which the jury confirms is a no-op on R9, R10, AMZN and U24 | **J** at astra depth |
| Build-only environment knob in a recipe (e.g. `CFLAGS+=-std=gnu17` for one package) that does not change the shipped ABI or feature set | **J**, and the comment next to it must say why |
| Turning an upstream option **ON or OFF**, dropping a feature, disabling a test suite, changing `include_flavors:`/`exclude_flavors:`, dependency lists, `rpm_requires`/`rpm_recommends`, versions, compilers, flavor files, prefixes, license-affecting changes | **H** — never landed; park with a proposal |
| Anything that would reach a published repository | **H** |

When in doubt between J and H, it is H. A package parked under H costs one morning decision; a
wrong option flip costs a silent, shipped build difference.

## 2. Two escalation levels

Christian's rule (2026-09-26): use common sense about cost.

| Level | When | Lead | Codex seat | Grok seat |
|---|---|---|---|---|
| **Normal** | a first attempt at an ordinary failure: one missing include, one API rename, a manifest/test-harness cause that is clear from the log | Opus (this session) | `gpt-5.6-terra`, `high` | `grok-4.7`, `high` |
| **Escalated** | the normal attempt failed its gate or drew a split verdict; *or* the failure is obviously hard from the start — a `python/` builder change, anything cross-builder, a link/ABI problem, a cause spanning several packages, a diagnosis that is not clear after reading the log | **Fable** subagent (`Agent`, `model: "fable"`) diagnoses and drafts the plan; Opus verifies and runs the loop | `gpt-6-astra`, `high` | `grok-4.7`, `xhigh` |

A package goes Normal → Escalated at most once. An escalated attempt that still fails is parked.

## 3. The loop

1. **Diagnose.** Read the failing log (`work/logs/<F>/<pkg>.{build,install}.log`), the extracted
   source under `work/build/`, and the recipe. Establish the *cause*, not just the first error line.
   At the Escalated level, hand the log path and the question to the Fable subagent, blind to your
   own hypothesis, and reconcile its diagnosis with yours before writing the plan.
2. **Plan.** Slug `fix_<pkg>_<column>_<flavor>`. Write the plan to
   `tmp/ai_exchange/<slug>.md` as a pre-registered `# CLAUDE <timestamp>` entry: the defect with
   log excerpt, the tier (J or H) and why, the exact files and hunks, what could break on the other
   hosts and flavors, and the **gate** (normally: `./scls build <pkg> && ./scls install <pkg>`
   green, NEVRA verified, the recipe's own tests passing). An **H** plan stops here → step 6.
3. **Plan jury.** `scripts/cross_review.sh --jury tmp/ai_exchange/<slug>.md` with the depth of the
   level from §2 set explicitly (all four variables). Verify every
   citation and write the reconciliation table as in `.claude/commands/cross-review.md` steps 4–5.
   `git status` afterwards — an auditor must not have edited the tree.
4. **Decide (replaces the human stop).** Proceed only when neither auditor has an unrefuted P0/P1
   and neither re-classifies the fix as H. A split verdict at Normal → Escalated; split at
   Escalated → H. Physics, licensing and policy questions are never settled by
   vote → H.
5. **Implement, gate, code jury, commit.** Apply exactly the plan. Run the gate. If it fails at Normal, go
   Escalated with an amended plan through steps 1–4; a failure at Escalated → H. On green, write the diff of your
   own files only (`git diff HEAD -- <files> > tmp/ai_exchange/<slug>.diff`) and run the code
   jury on it at the same depth. Clean → commit locally, with the `CLAUDE.md` record: a comment at
   the change naming why, a line in `changelogs/<pkg>.md`, and the devlog entry. Message the peer
   build session naming the commit. P0/P1 from the code jury → revert, rebuild the previous state
   only if something was installed from it, and park as H.
6. **Park (H, or any exhausted J).** Record the blocker in the run tracker: package, flavor,
   failing command, last ~30 log lines, log path, the proposal with its jury record, and the
   reverse-dependency closure from `python/build_order.py`. Then **skip that package and every
   package that depends on it** for this flavor, and continue with the rest of the build order —
   and with the remaining flavors, where the same package is parked up front if the cause is not
   flavor-specific.

## 3. Limits

- **Budget.** At most two levels (Normal, Escalated) per package, and at most ~6 landed J fixes per flavor. Past
  that the manifests or toolchain are telling you something systemic; park and report.
- **Missing voice.** If Codex or Grok is out of quota, there is nobody to top it up overnight:
  do not proceed on one auditor and do not substitute a blind Claude. Park as H and say which
  voice was missing.
- **Say "built and installed on U26/<flavor>", not "verified"**, and never claim a fix holds on
  the other hosts: it was gated here only.
- **Never push.** Never touch the published repository.
