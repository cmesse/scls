# Devlog 2026-09-04 — MUMPS macOS install-name handover: already fixed in the builder

**Date:** 2026-09-04
**Topic:** Triage a BELFEM handover (origin: BELFEM `dl20260527_mumps_macos_install_names.md`) reporting that SCLS MUMPS dylibs ship with relative/bare install IDs (`../lib/libdmumps.dylib`, `libmumps_common.dylib`, `../../lib/libpord.dylib`) and that SCLS has no package-side fix
**AIs involved:** Claude (this session); no auditor dispatched — read-only triage against git history
**Claude Confidence:** high (~90%) that the builder-side fix exists and covers MUMPS; unverified whether the installed `/opt/scls` on the Mac post-dates it
**Auditor Confidence:** n/a
**Flavor / Host:** Linux x86_64 dev host; no macOS host in this session
**Upstream References:** none
**Verification:** level 5 — static trace of `python/unix_builder.py`, `recipes/mumps.yaml`, `templates/mumps/Makefile.inc.j2`, `tools/fix_macos_install_names.sh`, and `git log -S fix_macos_dylib_install_names`. Nothing executed on macOS.

## Summary

The handover's premise — "package-side defect, no fix so far except a hand patch of one binary" — is stale. SCLS commit `f171e7d` ("fix install names on macos", 2026-05-27 10:47 CDT, the same day as the BELFEM devlog) added a post-install normalizer that rewrites every locally-resolvable dylib ID and load command to an absolute `<prefix>/lib/...` path. It runs on every macOS recipe install, so MUMPS is covered without a recipe change. What the handover cannot know from the BELFEM side, and what this session cannot verify from Linux, is whether the MUMPS actually installed under `/opt/scls` on the Mac was built after that commit.

## Key Findings

- **The fix is generic, not MUMPS-specific.** `UnixBuilder.fix_macos_dylib_install_names()` (`python/unix_builder.py:1729`) is called from the recipe install path (`python/unix_builder.py:850`) after files land in the prefix. For each installed `.dylib` it reads the ID via `otool -D` and the load commands via `otool -L`; any name that is bare (`libmumps_common.dylib`), relative (`../lib/libdmumps.dylib`), or `@rpath/...` and whose basename exists in `<prefix>/lib` is rewritten with `install_name_tool -id` / `-change` to the absolute path. Names already absolute, or `@executable_path`/`@loader_path`, are left alone. This covers both the IDs and the internal `libdmumps -> libmumps_common/libpord` chain the handover flags.
- **Same commit, same day as the BELFEM observation.** `f171e7d` also added `tools/fix_macos_install_names.sh`, a standalone repair for an already-installed prefix (default `/opt/scls`, `--dry-run` supported). That is almost certainly the "external fix" the BELFEM devlog records as having produced absolute `otool -D` output on 2026-05-27. Neither the SCLS changelogs nor the devlog recorded it — only `changelogs/gcc.md:36` has a one-line mention — which is why the BELFEM session could not find it.
- **Header padding was addressed too.** `flavors/macos.yaml` ldflags and `get_cmake_args()` (`python/build_common.py:764`) gained `-Wl,-headerpad_max_install_names`, and cmake packages get `CMAKE_INSTALL_NAME_DIR=<prefix>/lib`. MUMPS is a vendor-Makefile build (`configure.type: custom_makefile`), so it relies on the post-install normalizer rather than a correct link-time ID.
- **Why the IDs were bad in the first place.** `templates/mumps/Makefile.inc.j2` sets `SONAME = -install_name` on macOS, but the upstream `src/Makefile` passes the relative `-o` target as the name, and `recipes/mumps.yaml` links PORD by hand with `-shared -o ../../lib/libpord.dylib` and no `-install_name`, so ld defaults the ID to that relative path. This was left as-is deliberately: the normalizer is the fix (handover option 2), not a link-step change (option 1).
- **Answers to the handover's open questions.** (1) MUMPS 5.9.1, vendor `Makefile.inc` shared target via the Jinja template; PORD linked in `build.lp64_pre`. (2) Only `dmumps`, `mumps_common`, `pord` are built and shipped — no s/c/z variants (install glob and registry ldflags agree). (3) The normalizer runs for every macOS package, so any other vendor-Makefile recipe gets the same treatment; the handover's `otool -D` audit loop remains the right check.
- **MUMPS has been rebuilt twice since the fix upstream-wise** (5.9.0 on 2026-06-09, 5.9.1 on 2026-08-18), so any macOS rebuild since May went through the normalizer.

## Open Questions

- **Is the installed `/opt/scls` MUMPS on the Mac post-`f171e7d`?** Cannot be determined from this host. Check with `for f in /opt/scls/lib/lib{dmumps,mumps_common,pord}.dylib; do otool -D $f; otool -L $f | grep -E 'mumps|pord'; done` or `tools/fix_macos_install_names.sh --dry-run`. If stale, rebuild mumps or run the tool without `--dry-run`.
- **No `codesign` after `install_name_tool`.** Neither the Python normalizer nor the shell tool re-signs. Recent cctools re-sign linker-signed ad-hoc binaries automatically, which is presumably why the May repair loaded, but this has never been recorded as verified on Apple silicon. If a dylib fails to load with a signature error, add `codesign --force --sign -` after the rewrite.
- **BELFEM side is unchanged.** Load commands are baked into BELFEM binaries at link time; binaries built before the package repair need a relink or the hand patch in the handover regardless of what SCLS does.

## Decisions

- No SCLS code or recipe change. The handover can be retired on the SCLS side once the Mac's installed prefix is confirmed post-fix.
