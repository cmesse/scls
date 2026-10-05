# American spelling: "license" everywhere SCLS speaks for itself; HSL flags accept both

**Date:** 2026-10-05
**Host:** R9 build host (EL9), docs and scripts only; no package built.
**Commits:** this record and the spelling change across `doc/`, `CLAUDE.md`, `web/`, `scls`,
`scripts/`, `todo/`, `.gitignore`, and one comment in `recipes/xz.yaml`. No build option,
dependency, manifest or patch changed; nothing requires a rebuild.

## 1. Why

The repository wrote "licence" (British) wherever HSL was discussed, because STFC spells its
documents that way, and "license" (American) everywhere else. The Codex language sweep of
2026-10-05 flagged the mix repeatedly. Christian's ruling: American English consistently.

## 2. What changed

- Prose: `licence`, `licences`, `Licence` -> American spelling in every tracked file except
  the dated devlog entries, which stay as written.
- Kept as-is, deliberately: the upstream file name `LICENCE` (SPRAL and Coin-HSL ship it under
  that name; the recipe, `files/spral.txt`, `files/hsl.txt` and the HSL assembler copy it
  verbatim and the assembler's `LICENCES/` directory mirrors it), the STFC portal URL
  `licences.stfc.ac.uk`, and the title "HSL Academic Licence" where STFC's document is named.
- `scripts/build_libhsl.py install`: the flags are now `--license` and `--accept-license`;
  `--licence` and `--accept-licence` remain accepted as aliases, so earlier notes and scripts
  keep working. `argparse` dest is `license` / `accept_license`.
- `build-info.yaml` keys written at install: `license_type`, `license_acceptance`,
  `license_texts_sha256` (were `licence_*`). Only the install step of the same script
  version reads them back, so a staged build is unaffected; global installs made before this
  date carry the old keys, which nothing reads.

## 3. Gates

- `python3 -m py_compile` on the two Python scripts; `bash -n` on the shell scripts and `scls`.
- `build_libhsl.py install --help` lists both spellings; a parse check with each spelling
  yields the same namespace.
- `scripts/hsl/tests/test_assemble.sh`: 20 pass, 1 fails ("outside hardlink with blank in
  target refused"). The same test fails on the committed tree before this change on this
  host, so it is pre-existing; recorded in `todo/backlog.md` §4.
- `./makeweb` regenerates the page with the new wording.
