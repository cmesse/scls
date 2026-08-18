# SCLS Devlog Index

Session summaries for AI-assisted work on SCLS, newest first. One line per entry.
See [`doc/AI_COLLABORATION_PROTOCOL.md`](../doc/AI_COLLABORATION_PROTOCOL.md) §6 for
what belongs here, the required header, and the `dlYYYYMMDD_topic.md` naming.

This directory is the **tracked durable record**. The AI-to-AI exchange under
`tmp/ai_exchange/` is git-ignored scratch and gets swept; `todo/` is git-ignored too.
If a conclusion is not here, in `changelogs/<package>.md`, or in a `doc/*.md` policy
file, it is lost.

## Entries

- [dl20260817_ai_collaboration_setup.md](dl20260817_ai_collaboration_setup.md) — ported the BELFEM AI collaboration tooling and protocol to SCLS
- [dl20260817_strumpack_openmp_tasking.md](dl20260817_strumpack_openmp_tasking.md) — mkl-flavor STRUMPACK lost its OpenMP tasking: `-lgomp` in `CMAKE_<LANG>_STANDARD_LIBRARIES` poisons cmake `try_compile` probes
- [dl20260818_asc2026_upgrade_plan.md](dl20260818_asc2026_upgrade_plan.md) — ASC 2026 final upgrade: 14 upstream bumps, 5 rebuild-only packages, build order, and the decisions to settle first
