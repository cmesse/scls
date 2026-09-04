# Devlog 2026-09-04 — Apple Silicon GCC patch, gated on arm64

**Date:** 2026-09-04
**Topic:** Vendor Homebrew's `aarch64-apple-darwin` GCC 16.2.0 branch patch into `patches/gcc/` and add an `arch:` filter to the patch system so it applies only on Apple Silicon hosts of the `macos` flavor
**AIs involved:** Claude (plan + implementation), Codex (gpt-5.6-terra, high → xhigh), Grok (grok-4.6, high → xhigh)
**Claude Confidence:** high (~85%) on the mechanics; unknowable on the arm64 bootstrap itself
**Auditor Confidence:** round 1 — Codex high, Grok high on C1–C5 and challenged Q2 (refuted from upstream source, see below); round 2 — Codex "do-not-ship" and Grok "ship-with-fixes" on the same two prose overclaims (G2 spec identity, "-march=native is safe") plus lax `arch:` validation; all three fixed, no code rework requested
**Flavor / Host:** `macos` (arm64 target) reviewed from a Linux x86_64 dev host; no Apple Silicon machine exists in the project
**Upstream References:** homebrew-core `4a334d2f90f786c3fc86cbc9cf72b2f13961b078` "gcc 16.2.0" (2026-08-20), `Patches/gcc/gcc-16.2.0.diff`, sha256 `578a78ae0bc62a02f260b6a20c7f23e71deee16ed644e9cb5619247be4df5a71`; branch source https://github.com/iains/gcc-16-branch; upstream `gcc-16.2.0/gcc/config/aarch64/aarch64.h:1545`, `gcc/common/config/aarch64/aarch64-common.cc:510-590`, `gcc/config/aarch64/aarch64-cores.def:186-202`; LLVM `clang/lib/Driver/ToolChains/Arch/AArch64.cpp:154` @ llvmorg-15.0.0
**Verification:** level 4 — `patch -p1 --dry-run` and then a real sequential apply of both macos patches (libatomic first, Darwin branch second) against the extracted upstream `gcc-16.2.0.tar.xz` with GNU patch on Linux: 73 files, 0 rejects, 0.06 s (vs the 60 s `apply_patches` timeout). Level 3 — `python python/rpm_builder.py --package gcc --flavor lbl --spec-only`: byte-identical before/after the code and recipe changes; after the changelog bullet was added the only delta is the `%changelog` text (rpm_builder injects `changelogs/gcc.md` verbatim, `templates/default.spec.j2:433`), so a rebuilt lbl RPM would carry different changelog metadata under the same NVR — accepted, the bullet documents a shipped patch and lbl binaries are unaffected (Codex round 2 flagged this; the alternative is to keep the note out of the package changelog). Unit checks of `get_patches_from_recipe` with injected `arch` (`arm64`/`aarch64` → 2 patches, `x86_64`/`amd64` → 1, `lbl` → 0, list and empty-list forms, bad type raises `BuildError`). **Levels 1–2 on Apple Silicon are unreachable: no arm64 host.** Everything about the actual bootstrap, `hw.cpufamily` detection, dylib install names, and codegen is *reviewed*, not verified.

## Summary

Upstream GCC has no `aarch64-apple-darwin` target; Homebrew builds GCC on Apple Silicon by applying Iain Sandoe's Darwin branch, now vendored in homebrew-core for exactly our version. SCLS vendors that file byte-identically as `patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch` and applies it through a new, orthogonal `arch:` key on dict-style patch entries, so the validated Intel `macos` build and the `lbl` RPM are untouched. Homebrew applies the branch on all macOS hosts; SCLS deliberately does not (see Key Findings). Two blind audits (round 1, high) approved the direction and sharpened the implementation; round 2 (xhigh) audited the diff.

## Key Findings

- **No arch axis existed.** `python/patch_common.py:get_patches_from_recipe` keyed only on `all`/`lp64`/`ilp64`/`<flavor>`. A top-level `macos-arm64` key was rejected by both auditors: `get_flavor_names()` (`build_common.py:235-280`) hyphen-splits flavor names, so it would never resolve for the flavor `macos` and would look like a flavor component. `arch:` inside a dict entry is orthogonal and composes with every existing key. `collect_declared_patch_files()` records dict entries by `file` regardless of `arch`, so the stray-file guard still recognises the vendored file on Intel hosts. The file is `.patch`, not `.diff`, because `discover_patches_in_directory()` globs `*.patch` only.
- **Host triplet and configure already fit.** `unix_builder.py:126-130` sets `aarch64-apple-darwin<uname -r>` on arm64; `build_common.py:681-687` emits `--host`, `--build`, and `--target` from it — Homebrew's explicit `--build=aarch64-apple-darwinNN` is already covered. The patch's `config.gcc` cases (`aarch64*-*-darwin2*`, `aarch64-*-darwin*`) match that triplet. Patches are applied (`unix_builder.py:1417`) before `configure.pre` (`:320-323`), so the recipe's `sed` over `configure` files runs on the patched tree.
- **`-march=native` (Q2): the upstream-spec trace routes it to `-mcpu`; ARM execution remains unverified. This was the one point the jury split on.** Grok assumed the old spec that maps `-march=native` to `local_cpu_detect(arch)`, which with the Darwin detector would yield `-march=apple-m1` and be rejected by `aarch64_validate_march` (it searches `all_architectures` only, `aarch64-common.cc:510-548`). Upstream 16.2.0 `aarch64.h:1545` reads `%{march=native:%<march=native %:local_cpu_detect(%{mcpu=*|mtune=*:arch;:cpu})}`: a lone `-march=native` is routed to the `cpu` branch and becomes `-mcpu=apple-m{1,2,3}`, which `aarch64_validate_mcpu` accepts (`apple-m1`…`apple-m5` are in `aarch64-cores.def`). The patch does not redefine that spec (no `local_cpu_detect` hunk). The `arch` branch is only taken when `-mcpu=*`/`-mtune=*` is also present; no recipe or flavor sets either (grep clean). Apple clang, which compiles stage 1 and every bootstrap package before GCC exists, has accepted `-march=native` on AArch64 since LLVM 15. **No flavor flag change.** Residual: the Darwin detector knows A12/M1/M2/M3 `hw.cpufamily` values only; M4/M5 hosts fall back to `DEFAULT_ARCH "apple-m1"` — a tuning miss, not a failure.
- **Why not apply on Intel like Homebrew.** The Intel 16.2.0 build is the project's only level-2 macOS evidence. The branch also changes generic Darwin code (`gcc/config/darwin.cc`, `darwin-driver.cc`, `collect2.cc`, `fixincludes/` — which drops two Darwin header fixes, 251→249 — and moves `libd10-uwfef.a` between `libgcc/config.host` `extra_parts` cases). Nothing there is a demonstrated Intel fix. Revisit only if Intel hits Darwin 27 version mapping or Mach-O LTO `collect2` issues, or once an arm64 host has validated the branch.
- **No Homebrew assumptions in the diff.** No `HOMEBREW`, `/opt/homebrew`, or `/usr/local` literals. Hard-coded and appropriate: `libgcc/config/aarch64/t-darwin` `-mmacosx-version-min=11.0`, `config.gcc` `with_cpu=${with_cpu:-apple-m1}` default.
- **Release number.** `recipes/gcc.yaml` has no `release:`; both builders default to `1` (`rpm_builder.py:522`, `deb_builder.py:222`). Bumping would respin the unchanged `lbl` RPM; the changelog gets a dated bullet under `16.2.0-1` instead.
- **Rosetta.** `platform.machine()` reports `x86_64` in a Rosetta shell; the patch is skipped and an Intel toolchain is configured. Documented as unsupported in `doc/MACOS_BUILD.md`.
- **Residual risks that need an arm64 host:** BSD `patch` handling of the four `/dev/null` new-file hunks (the recipe is `bootstrap: true`, so host `patch` is used — GNU patch on Linux is clean; macOS BSD patch is untested); the three-stage bootstrap under `darwinpcs`; `install_name_tool` post steps; a Fortran/C++ hello world.

## Changes Made / Proposed

- `python/patch_common.py` — `import platform`; `normalize_arch()`, `host_arch()`; `get_patches_from_recipe(recipe, flavor=None, arch=None)` and `get_all_patches(..., arch=None)` with `arch:` (string or list of strings) on dict entries, skip with a log line on mismatch, `BuildError` on a malformed value including a bare `arch:` (YAML null) and non-string list members (Codex round 2); docstring.
- `patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch` — byte-identical vendored copy (no provenance header, so the sha256 stays comparable to upstream on the next bump).
- `recipes/gcc.yaml` — second `macos` patch entry with `arch: arm64` and a provenance/version-lock comment.
- `changelogs/gcc.md` — dated bullet under `16.2.0-1`.
- `README.md:5,102,153`, `doc/MACOS_BUILD.md:10-15,96-98`, `web/scls.html.j2` ("Building from Source") — status softened to "patch vendored, no arm64 build evidence"; never "supported".
- `todo/gcc_apple_silicon_patch.md` — the plan, round-1 amendments, checkboxes.

## Open Questions

- Everything at evidence levels 1–2 on Apple Silicon: does the bootstrap complete, does BSD `patch` create the four new files, do the dylib post-install steps hold, does `hw.cpufamily` detection pick a sensible CPU on M4/M5.
- Whether to follow Homebrew and apply the branch on Intel too, once (and only once) an arm64 host has validated it.
- `files/gcc.txt` is the lbl/`lib64` manifest, but a macOS install regenerates it unconditionally (`unix_builder.py:852,948`); the first arm64 build will dirty it and the result must be inspected before any lbl packaging use (Codex round 2).
- On the next GCC bump: re-fetch `Patches/gcc/gcc-<version>.diff` from homebrew-core, rename, re-record sha256 + commit. The recipe comment and changelog say so; the update checker does not enforce it.

## Files Updated

- python/patch_common.py
- patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch (new)
- recipes/gcc.yaml
- changelogs/gcc.md
- README.md
- doc/MACOS_BUILD.md
- web/scls.html.j2
- todo/gcc_apple_silicon_patch.md (new)
- devlog/dl20260904_gcc_apple_silicon_patch.md (this file), devlog/README.md
