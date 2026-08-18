# Devlog 2026-08-17 — AI Collaboration Tooling Ported from BELFEM

**Date:** 2026-08-17
**Topic:** Port the BELFEM multi-AI collaboration protocol, wrapper scripts, and cross-review driver into SCLS, adapted for a Python + YAML packaging codebase
**AIs involved:** Claude, Codex, Grok (both wrappers exercised end-to-end against this repository)
**Claude Confidence:** high on the mechanical port, medium (~70%) on whether the audit checklist in §4 is the right set of nine items — that will need a few real rounds to settle
**Flavor / Host:** macOS dev host, active flavor `mkl` per `flavor.conf`
**Verification:** executable — both wrappers ran live against this repository and appended correctly-formatted entries to `tmp/ai_exchange/wrapper_smoketest.md`; `scripts/cross_review.sh` exercised in all three modes (`--jury`, `--relay`, `--quick`) plus a concurrent-lock contention case against a throwaway git repo with stub auditors; delta hook smoke-tested to correct `additionalContext` JSON; `bash -n` clean on all six shell scripts and `json.load` clean on `.claude/settings.json`. Not verified: the post-commit hook has never fired on a real commit.

## Summary

Christian copied `ask_codex.sh` and `ask_grok.sh` from BELFEM into `.claude/scripts/` and asked
for both the scripts and the BELFEM collaboration protocol to be adapted to SCLS. The copied
artifacts were BELFEM-shaped in three ways that made them inoperative here: they pointed auditors
at `AGENTS.md` and `doc/coding_philosophy.md` (neither exists in SCLS), their audit mandate was
C++17/MPI/ownership (irrelevant to a build system), and the delta hook hard-coded
`/home/christian/codes/belfem` plus GNU `stat -c`, so it silently no-opped on macOS.

The port keeps BELFEM's structure — audience tiers, calibrated confidence, the frozen three-AI
round, the evidence ladder — and replaces the domain content wholesale.

## Key Findings

- The copied `.claude/commands/cross-review.md` referenced `scripts/cross_review.sh`, which had not
  been copied. Source located at `/Users/christian/codes/belfem/scripts/cross_review.sh` and ported.
- BELFEM's `cross_review.sh` sources `scripts/scls_env.sh` — that file pins the **SCLS toolchain for
  BELFEM's** builds and has no meaning inside SCLS itself. Dropped; replaced with an optional
  `scripts/ai_env.sh` hook for pinning `codex`/`grok` onto a git-hook's minimal PATH.
- `--quick` mode depended on `flock(1)` and the bash-4 `${var^^}` expansion. macOS has neither
  reliably (`flock` is absent entirely; `/bin/bash` is 3.2). Replaced with an atomic `mkdir` lock
  with a 30-minute stale-lock break, and `tr` for the case fold.
- `todo/` and `tmp/` are both git-ignored in SCLS, unlike BELFEM where `todo/` is tracked. The
  protocol therefore cannot treat `todo/` as a durable record — `devlog/` (new, tracked) is the
  durable tier, alongside `changelogs/` and `doc/`.
- The macOS dev host cannot run `rpmbuild`, which caps the evidence ladder at the spec-generation
  gate for any RPM claim. This is written into §11 as an explicit ceiling rather than left implicit.

- The live smoke test validated the rewritten preambles: Codex answered from `CLAUDE.md`, and Grok
  independently refused the docs-only citation and traced the real behaviour to
  `python/rpm_builder.py:614-619` (`install.post` prefix rewrite) and `:639-646` (`install.commands`
  left alone), then named its own evidence ceiling as pending a Linux `rpmbuild`. Grok also noted
  that `unix_builder.py:735-737` remaps `%{prefix}` in post to the staged destroot — the same recipe
  convention holding for a different reason across builders.

## Changes Made / Proposed

- `doc/AI_COLLABORATION_PROTOCOL.md` (new) — the SCLS protocol. Same eleven sections as BELFEM's,
  with an SCLS audit checklist (recipe/flavor gating, install-hook macro expansion, file manifests,
  `AutoReqProv: no` dependency completeness, cross-builder consistency, lib/lib64, licensing, MKL
  ABI, update metadata), an upstream-first rule replacing the literature-first rule, and an evidence
  ladder rebuilt around builds and spec generation. The nonfree-module exception is dropped — SCLS
  has no proprietary subtree.
- `.claude/scripts/ask_codex.sh`, `.claude/scripts/ask_grok.sh` — repointed at `CLAUDE.md` +
  `doc/AI_COLLABORATION_PROTOCOL.md`, project-root variable renamed off `BELFEM`, and the audit
  mandates rewritten around packaging defects. Grok's no-shell rule now also forbids starting builds.
- `scripts/cross_review.sh` (new) — ported with `--jury`/`--relay`/`--quick`, macOS-portable locking,
  and SCLS review priming.
- `scripts/install_autoreview_hook.sh`, `scripts/review_status.sh` (new) — opt-in post-commit
  auto-review, gated on `SCLS_AUTOREVIEW=1` (default off), never blocks a commit.
- `.claude/hooks/ai_exchange_delta.sh` — repo-root resolution via `$CLAUDE_PROJECT_DIR`, `wc -c`
  instead of `stat -c`, and grok/cross-review added to the trigger regex.
- `.claude/settings.json` (new) — registers the delta hook, which was previously unregistered.
- `.gitignore` — ignore `.claude/ai_exchange_pos.txt` (hook cursor state).
- `CLAUDE.md`, `CODEX.md` — pointers to the protocol.

## Open Questions

- The §4 checklist is a first cut. Whether nine items is the right granularity, and whether
  "cross-builder consistency" deserves to be split out from "install hooks", should be revisited
  after a handful of real rounds.
- The auto-review hook has never fired from a real `git commit` — `--quick` was driven directly.
  The P0 negation filter is inherited from BELFEM unchanged and its false-positive rate on
  packaging prose is unknown; the stub test confirmed only that a literal `P0:` raises the flag.
- The stub-auditor test used a throwaway repo, so the driver's git-subject resolution is proven
  but its interaction with SCLS's own history (merge commits, large recipe diffs vs `DIFF_CAP=400`)
  is not.

## Files Updated

- doc/AI_COLLABORATION_PROTOCOL.md
- devlog/README.md
- devlog/dl20260817_ai_collaboration_setup.md
- .claude/scripts/ask_codex.sh
- .claude/scripts/ask_grok.sh
- .claude/hooks/ai_exchange_delta.sh
- .claude/commands/cross-review.md
- .claude/settings.json
- scripts/cross_review.sh
- scripts/install_autoreview_hook.sh
- scripts/review_status.sh
- .gitignore
- CLAUDE.md
- CODEX.md
