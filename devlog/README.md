# SCLS Devlog Index

Session summaries for AI-assisted work on SCLS, newest first. One line per entry.
See [`doc/AI_COLLABORATION_PROTOCOL.md`](../doc/AI_COLLABORATION_PROTOCOL.md) §6 for
what belongs here, the required header, and the `dlYYYYMMDD_topic.md` naming.

This directory is the **tracked durable record**. The AI-to-AI exchange under
`tmp/ai_exchange/` is git-ignored scratch and gets swept; `todo/` is git-ignored too.
If a conclusion is not here, in `changelogs/<package>.md`, or in a `doc/*.md` policy
file, it is lost.

## Entries

- [dl20260904_mumps_macos_install_names_handover.md](dl20260904_mumps_macos_install_names_handover.md) — triaged the BELFEM MUMPS dylib install-name handover: stale, fixed generically by the macOS post-install normalizer in `f171e7d` (2026-05-27); remaining check is whether the Mac's installed prefix post-dates it
- [dl20260904_website_restyle_and_doc_sweep.md](dl20260904_website_restyle_and_doc_sweep.md) — ported the scls.html restyle into the Jinja template/generator; swept README, doc/, CLAUDE.md and the website for stale GCC 15 and Apple Silicon claims
- [dl20260904_gcc_apple_silicon_patch.md](dl20260904_gcc_apple_silicon_patch.md) — vendored Homebrew's aarch64-apple-darwin GCC 16.2.0 branch patch, gated on arm64 via a new `arch:` patch-entry key; two-round Codex+Grok review, no Apple Silicon build evidence
- [dl20260904_auditor_depth_selection.md](dl20260904_auditor_depth_selection.md) — ported BELFEM's explicit model/effort depth selection into the Codex and Grok wrappers and `cross_review.sh`
- [dl20260817_ai_collaboration_setup.md](dl20260817_ai_collaboration_setup.md) — ported the BELFEM AI collaboration tooling and protocol to SCLS
- [dl20260817_strumpack_openmp_tasking.md](dl20260817_strumpack_openmp_tasking.md) — mkl-flavor STRUMPACK lost its OpenMP tasking: `-lgomp` in `CMAKE_<LANG>_STANDARD_LIBRARIES` poisons cmake `try_compile` probes
- [dl20260818_asc2026_upgrade_plan.md](dl20260818_asc2026_upgrade_plan.md) — ASC 2026 final upgrade: 14 upstream bumps, 5 rebuild-only packages, build order, and the decisions to settle first
