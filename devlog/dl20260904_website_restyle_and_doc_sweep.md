# Devlog 2026-09-04 — Website restyle in the generator, and a documentation sweep

**Date:** 2026-09-04
**Topic:** Port a hand-edited `scls.html` restyle back into `web/scls.html.j2` / `python/generate_website.py`; sweep README, `doc/`, `CLAUDE.md`, and the website template for stale claims after the Apple Silicon patch and the GCC 16 bump
**AIs involved:** Claude (this session); the Apple Silicon patch itself ran two Codex+Grok rounds — see `dl20260904_gcc_apple_silicon_patch.md`
**Claude Confidence:** high (~90%)
**Auditor Confidence:** n/a for the website and doc sweep (prose and template work, not dispatched); the GCC patch has its own devlog
**Flavor / Host:** Linux x86_64 dev host; website rendered with `python3 python/generate_website.py`
**Upstream References:** Homebrew `Formula/g/gcc.rb` (gcc 16.2.0, versioned binaries `gcc-16`); Red Hat Application Streams life-cycle table (gcc-toolset-15 on RHEL 8.10, Nov 2025)
**Verification:** generation gate — rendered the original `HEAD` template and the patched template and diffed the two HTML outputs: hunk-for-hunk identical to the user-supplied `scls.html` diff, including whitespace; final render after the sweep parses with balanced tags (12 `<section>`/12 `</section>`, empty tag stack). Doc claims were checked by static trace against `scls`, `flavors/`, `templates/`, `python/`, and `recipes/` (level 5), plus two external lookups (Homebrew formula, Red Hat life-cycle page) at level 6.

## Summary

The user supplied a diff of the *generated* `scls.html` (new stylesheet/font links, token-based inline CSS, `<section class="section-band">` structure with `.section-head` captions, hero eyebrow + `<h1>`, `.table-scroll` wrappers, new footer, prose edits). It was applied to the Jinja template rather than the output, with the three flavor bullets — generated in `generate_flavor_descriptions()` — updated in the generator (`<code>x86-64-v3</code>`, `<code>-Og -g</code>`, "Valgrind"). The template's Jinja constructs (flavor loop, `license_display` map, package tables) were preserved. Afterwards, every doc was swept for claims invalidated by the Apple Silicon patch and by GCC 16.

## Key Findings

- **Template vs. output.** The website is generated; a diff against `scls.html` has to be re-expressed against `web/scls.html.j2`. Two non-obvious spots: the `license_display` Jinja block sits between "Git Repository" and "Packages", so the `</section>` for Git Repository has to go *after* it to reproduce the requested blank-line layout; and the flavor bullets are not in the template at all (`python/generate_website.py:112-131`).
- **Generator autoescape is off**, so HTML in the flavor description strings passes through — that is how `<code>` markup reaches the bullets. Fine for repo-controlled strings; do not feed recipe-derived text through that path unescaped.
- **Stale claims found and fixed:**
  - `doc/MACOS_BUILD.md`: "Apple Clang can build GCC 15" and 18 Homebrew `gcc-15`/`g++-15`/`gfortran-15` paths → 16 (Homebrew's formula is at 16.2.0, as is `recipes/gcc.yaml`).
  - `web/scls.html.j2`: "(Apple Clang building GCC 15)" → 16; Apple Silicon paragraph → "patch vendored, no arm64 build evidence".
  - `README.md`: Apple Silicon status in three places; `./scls check-updates` missing from the command list.
  - `CLAUDE.md`: `./scls order` and `./scls check-updates` missing; `./scls install` described as "Linux RPM mode only" — it works in RPM, DEB, and Unix modes (`scls:43-44,367`).
- **Claims re-verified and left alone:** the flavors table vs `flavors/` (7 flavors, `lbl` site prefix); macOS bootstrap order vs `flavors/macos.yaml`; runtime subcommands vs `templates/scls-*.sh.j2`; activation exports (`SCLS`, `SCLS_FLAVOR`, `PETSC_DIR`/`PETSC_ARCH` empty, `SLEPC_DIR`, `MPI_HOME`; no `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` set, stale `/opt/scls/` entries stripped); `scls-<flavor>-examples` exists for RPM (`rpm_builder.py:2500`) and not for DEB (`deb_builder.py:1870`); `unix_builder … pkg` action; no Boost/Python recipes; the GPL-3/LGPL-3 tool list vs recipe licenses; `scls-release` 2026-1 and `scls-archive-keyring` naming; EL9/EL10/AL2023 in `templates/scls-release.spec`; `gcc_toolset: 15` on RHEL 8 (Red Hat lists gcc-toolset-15 on 8.10); the VTK-on-macOS note vs `recipes/vtk.yaml`. Policy docs carry only dated worked examples (cmake 4.3.2, strumpack 8.0.0) — historical, not current claims.
- **Wrapper `release` subcommand** exists as a back-compat shim for `./scls build scls-release` (`scls:125-131`); deliberately not added to user-facing docs.

## Changes Made / Proposed

- `web/scls.html.j2` — restyle ported (head links, inline CSS, header/nav, sectioned main, table wrappers, footer, prose), Apple Silicon and GCC 16 wording.
- `python/generate_website.py` — flavor bullet strings.
- `doc/MACOS_BUILD.md`, `README.md`, `CLAUDE.md` — as listed above.
- Also in this session, recorded separately: the Apple Silicon patch (`dl20260904_gcc_apple_silicon_patch.md`).

## Open Questions

- Nothing open for the website or docs. The repo still carries unrelated uncommitted work on the auditor wrappers (`.claude/scripts/ask_*.sh`, `scripts/cross_review.sh`, `doc/AI_COLLABORATION_PROTOCOL.md`, `dl20260904_auditor_depth_selection.md`); it was not touched here and should be committed separately.
- `scls.html` itself is not tracked; run `./makeweb` to regenerate before publishing.

## Files Updated

- web/scls.html.j2
- python/generate_website.py
- doc/MACOS_BUILD.md
- README.md
- CLAUDE.md
- devlog/dl20260904_website_restyle_and_doc_sweep.md (this file), devlog/README.md
