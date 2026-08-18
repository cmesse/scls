---
description: Three-AI review round — Claude pre-registers, Codex + Grok audit headless, then verification + reconciliation
argument-hint: "[--jury|--relay] [path]"
---

Run one round of the frozen three-AI cross review on: $ARGUMENTS

Target: no path → the working-tree diff (`git diff HEAD`; clean tree → the last commit). A path argument → review that file (recipe, flavor, builder module, manifest, policy doc) instead. Mode: `--jury` (default) = parallel, blind, independent audits; `--relay` = sequential, each auditor sees the thread so far. Never mix the two in one round.

Follow these steps IN ORDER — the ordering is the protocol (`doc/AI_COLLABORATION_PROTOCOL.md` vocabulary applies):

1. **Resolve the target** and pick a topic slug `review_<topic>` (lowercase_underscore). The exchange file is `tmp/ai_exchange/<slug>.md`. Note the active flavor from `flavor.conf` — most claims in SCLS are flavor-conditional and a review that ignores the flavor is reviewing the wrong thing.

2. **Pre-register.** Review the target yourself, completely, BEFORE any auditor is invoked. Write your full findings to the exchange file as a `# CLAUDE <timestamp>` entry in the house format: every finding with file:line citations and per-finding confidence (high / medium / low). This entry is FROZEN once written — never edit it afterwards; all later material is appended below it.

3. **Dispatch the auditors.** Run as its own single background Bash command (never nested in a compound/piped command) and wait for it to finish:
   `AI_EXCHANGE_SLUG=<slug> scripts/cross_review.sh --jury [path]` (or `--relay`).
   The auditors run headless and read-only via the existing `ask_codex.sh` / `ask_grok.sh` wrappers and append their entries to the exchange file themselves.

4. **Verification pass.** Read the auditor entries from the exchange file. Re-check EVERY file:line citation against the actual source. Label each finding CONFIRMED / REFUTED / UNVERIFIABLE, quoting the evidence line under each label. Append this as a new `# CLAUDE <timestamp>` entry with a `## Verification` section.

5. **Reconciliation table.** Append at the end of the exchange file:
   `| finding | raised by | verdict | severity (P0–P2) | evidence | agreement |`
   The **evidence** column names the highest evidence-ladder level backing the verdict (`doc/AI_COLLABORATION_PROTOCOL.md` §11: installed package > full build > generation gate > upstream artifact > source trace > upstream docs > AI agreement). Rules: two-plus independent raisers = high confidence, but agreement is the WEAKEST evidence tier and never upgrades a verdict past source-trace level. Single-raiser findings are flagged "needs human adjudication" — never auto-resolved. **Packaging policy, licensing, and redistribution questions are NEVER settled by vote** — route them to Christian explicitly.
   Remember the dev-host ceiling: on macOS, `rpmbuild` does not run, so any finding about RPM install behaviour tops out at the generation gate (`--spec-only`) and must be written as pending a Linux build host rather than resolved.

6. **Report to the user:** a short summary plus the P0/P1 list only; the full record stays in the exchange file. NEVER apply fixes as part of this command — fixes are a separate, explicitly approved step (protocol §7: recipe/flavor/builder edits need explicit approval).
   **Stop condition (protocol §11):** do not propose another review round unless there is a material change to a recipe, flavor, manifest, patch, or builder; new build evidence; reviewer disagreement on a load-bearing point; or a policy boundary (licensing, ABI, redistribution, cross-builder divergence). Otherwise the next step is the executable gate — a `--spec-only` run, a build on a Linux host, an install test — not another review.
