# Devlog 2026-09-04 — Auditor Depth Selection Ported from BELFEM

**Date:** 2026-09-04
**Topic:** Adopt the BELFEM way of calling the Codex and Grok CLIs — explicit model + reasoning-effort knobs, validated up front and stamped into every exchange entry
**AIs involved:** Claude (port); Codex and Grok each exercised once as a smoke test
**Claude Confidence:** high — mechanical port, both wrappers ran live
**Flavor / Host:** Linux build host (EL9), codex-cli 0.152.0, grok 1.0.13
**Verification:** executable — `bash -n` clean on the three scripts; every validation branch (bad model, bad effort, missing depth in `cross_review.sh --jury`/`--relay`) exits 1 before any billed call; one live `gpt-5.6-luna`/`low` Codex call and one live `grok-4.6`/`low` Grok call each returned a body and appended a `(model=…, effort=…)`-stamped entry. Not verified: a real `--jury` or `--quick` round at the new depths.

## Summary

Christian copied the updated `ask_codex.sh` / `ask_grok.sh` from BELFEM into `tmp/` and asked
that SCLS adopt the way they call the APIs. The wrappers were re-derived from the SCLS copies
(SCLS root variable, SCLS role preambles, SCLS examples kept) with the BELFEM mechanics applied.

## Changes Made

- `.claude/scripts/ask_codex.sh`: `CODEX_MODEL` (default `gpt-5.6-terra`) and `CODEX_EFFORT`
  (default `medium`), validated before stdin is read; passed as `-m` and
  `-c model_reasoning_effort=` ahead of the positional `-`. Header stamps both, with `[defaulted]`
  per unchosen knob and a stderr warning.
- `.claude/scripts/ask_grok.sh`: `GROK_MODEL` (default `grok-4.6`) and `GROK_EFFORT` (default
  `xhigh`, no longer optional). `--model`/`--effort` live inside `run_grok` so the `--resume`
  salvage pass keeps the depth. Stop reasons are normalised (snake_case in grok 1.0.13, CamelCase
  earlier) so `end_turn`/`cancelled`/`refusal` gates cannot silently stop matching. `set -e` is no
  longer re-enabled inside `run_grok` (a nonzero grok exit used to kill the retry loop). Sandbox
  greps are case-insensitive and a failed sandbox-profile build gets a host-problem diagnosis.
- `scripts/cross_review.sh`: `--jury`/`--relay` refuse to run without all four depth variables and
  reject bad values before dispatching either leg; `--quick` pins `gpt-5.6-luna`/`medium` and
  `grok-4.6`/`medium` and forces them onto the wrappers by prefix assignment. The synthetic
  `Audit FAILED` entry and the final `done` line carry the depth.
- `doc/AI_COLLABORATION_PROTOCOL.md` §9.1: depth-selection table with SCLS subjects (prose sweep,
  narrow claim, recipe/builder diff, round ≥ 2 / policy boundary, unattended quick).
- `.claude/commands/cross-review.md`: dispatch line now shows the four variables.

## Open Questions

- The `[defaulted]` defaults reproduce the vendor configs as of 2026-08-30; nothing in-repo checks
  that they still do.
- `gpt-5.6-sol` is allowlisted but unnamed by any row, pending a measured comparison against terra.
