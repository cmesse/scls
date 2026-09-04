# Plan: Apple Silicon support for the `macos` GCC build

**Status:** round-1 jury done (Codex terra/high, Grok 4.6/high) — see amendments below. S1–S5 implemented 2026-09-04; round 2 (Codex terra/xhigh, Grok 4.6/xhigh) closed — two prose overclaims fixed, arch: validation tightened. Remaining work needs an Apple Silicon host.
**Author:** Claude, 2026-09-04
**Hardware caveat:** no Apple Silicon build host is available. Everything below is applied blind;
the highest evidence level reachable is a static source trace (protocol §11 level 5) plus an
Intel-Mac regression build showing the gated patch is *not* applied there.

## Background

- `recipes/gcc.yaml` builds GCC 16.2.0 for flavors `lbl` (Linux RPM) and `macos` (unix_builder).
- Upstream GCC 16.2.0 has no `aarch64-apple-darwin` target. Homebrew builds GCC on Apple Silicon by
  applying Iain Sandoe's Darwin branch (`https://github.com/iains/gcc-16-branch`), vendored in
  homebrew-core as `Patches/gcc/gcc-16.2.0.diff` and applied under `on_macos do` — i.e. on **all**
  macOS hosts, Intel included.
- The patch (fetched from homebrew-core `4a334d2f90f786c3fc86cbc9cf72b2f13961b078`, "gcc 16.2.0",
  2026-08-20): 5898 lines / 205825 bytes, sha256
  `578a78ae0bc62a02f260b6a20c7f23e71deee16ed644e9cb5619247be4df5a71`, git-style `a/` `b/` paths
  (`-p1`), 73 files, 4 new files (`gcc/config/aarch64/darwin.h`, `gcc/config/aarch64/t-aarch64-darwin`,
  `libgcc/config/aarch64/t-darwin`, `gcc/cumulative-args.h`). It does not touch `libatomic/`, so it is
  disjoint from the existing `patches/gcc/libatomic-darwin-posix-lock-visibility.patch`
  (which touches only `libatomic/config/posix/host-config.h`). A copy for reviewers sits at
  `tmp/review/gcc-16.2.0-darwin-aarch64-homebrew.patch` (git-ignored).
- What already works without changes:
  - `python/unix_builder.py:124-130` sets `self.host = aarch64-apple-darwin<uname -r>` when
    `platform.machine() == 'arm64'`, and `python/build_common.py:684-685` passes
    `--host=%{host} --build=%{host}` — the same `--build=aarch64-apple-darwinNN` Homebrew adds.
  - Patches are applied (`unix_builder.py:1417`) before `configure()` runs, and `configure.pre`
    commands run inside `configure()` (`unix_builder.py:320-323`), so the recipe's
    `find . -name configure -exec sed …` runs on the *patched* `configure` files. Good — that sed is
    idempotent text replacement, not a hunk.
  - The `install.flavor_post` / `flavor_final_post` dylib loops are `[ -f ]`-guarded, so the absence
    of `libquadmath` on aarch64 is harmless.
- What is missing: the patch system (`python/patch_common.py:14-95`) selects patches by `all` /
  `lp64` / `ilp64` / `<flavor>` keys only. There is no architecture axis.

## Design decision: gate on arm64, not on all macOS

Homebrew applies the branch on Intel too. SCLS will apply it only on arm64:

- The Intel `macos` build of 16.2.0 is the validated state (level 2 evidence, Intel dev host). Applying
  a 73-file branch there would invalidate that evidence for no user-visible gain.
- On arm64 the patch is mandatory (no target otherwise), so gating cannot make arm64 worse.
- Cost: the two macOS architectures build slightly different compilers. Acceptable while arm64 is
  "patched, untested"; revisit once an arm64 host exists.

## Steps

- [x] **S1 — `python/patch_common.py`: optional `arch:` field on dict-style patch entries.**
  - Add `normalize_arch(name)`: `arm64`/`aarch64` → `arm64`; `x86_64`/`amd64` → `x86_64`; anything
    else returned lowercased as-is.
  - Add `host_arch()` → `normalize_arch(platform.machine())`; add `import platform` (missing today,
    `patch_common.py:5-11` — Grok).
  - `get_patches_from_recipe(recipe, flavor=None, arch=None)`: `arch` defaults to `host_arch()`, so
    tests and foreign-arch spec generation can inject it instead of monkeypatching `platform` (Grok).
  - In `add_patch_entry`, for dict entries: read `patch_entry.get('arch')` (string or list; any other
    type → `BuildError`, Codex). If present and the current arch is not in the normalized set, print
    `Skipping <file>: arch <a> does not match host <h>` and do not append. `arch: []` skips everywhere.
  - Update the docstring at `patch_common.py:15-24` to document `arch:`.
  - `collect_declared_patch_files` (`patch_common.py:123-142`) already records dict entries by
    `file`, so the stray-file guard in `get_all_patches` (`:174-216`) still recognises the new
    file whether or not it is selected. No change there.
  - `validate_patches` (`:333`) calls `get_all_patches` without a flavor, so flavor-keyed patches
    are already outside its scope; no change.
  - Evaluation happens on the build host at both spec/series generation and apply time
    (`rpm_builder.py:1898-1900`, `deb_builder.py:1454-1456`, `unix_builder.py:1401,1417`), so an
    RPM/DEB built on one arch that carries an arch-gated patch is consistent with the binary it
    ships. Not exercised here (the only user is macos-only), but the semantics are stated.
- [x] **S2 — vendor the patch as `patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch`.**
  Byte-identical to the Homebrew file (no provenance header prepended — keeps the sha256 comparable
  to upstream on the next GCC bump). `.patch` extension, not `.diff`: `discover_patches_in_directory`
  globs `*.patch` (`patch_common.py:107`), and a `.diff` would be invisible to the stray-file guard.
- [x] **S3 — `recipes/gcc.yaml`:**
  ```yaml
  patches:
    macos:
      - libatomic-darwin-posix-lock-visibility.patch
      # Iain Sandoe's Darwin branch as vendored by Homebrew (Patches/gcc/gcc-16.2.0.diff).
      # Upstream GCC has no aarch64-apple-darwin target; without this the build cannot
      # configure on Apple Silicon. Gated to arm64 so the validated Intel build is untouched.
      # Version-locked: re-fetch the matching Homebrew diff on every GCC bump.
      - file: gcc-16.2.0-darwin-aarch64-homebrew.patch
        arch: arm64
  ```
  No configure changes: `--host/--build` already come from `%{host}`; `--with-sysroot=%{sdk}` and
  `--with-native-system-header-dir=/usr/include` are architecture-neutral.
- [x] **S4 — records.** `changelogs/gcc.md`: dated bullet under the existing `16.2.0-1` heading (no
  `release:` bump — both builders default to `1`, and `lbl` output is unchanged; Codex+Grok agree),
  with sha256 + homebrew-core commit + "no arm64 build evidence"; `devlog/dl20260904_gcc_apple_silicon_patch.md`
  + index line (records the Q2 evidence, the Rosetta caveat — `platform.machine()=x86_64` under
  Rosetta skips the patch and builds an Intel triplet — and the M4/M5 → apple-m1 tuning fallback);
  soften the status sentences at `README.md:5,102,153`, `doc/MACOS_BUILD.md:10` and `:96-97`
  (still talks about GCC 11–15 ARM bootstrap quality — Grok), and the website template paragraph
  (`web/scls.html.j2`, "Building from Source") to "patch vendored, no arm64 build evidence yet".
  Never "supported" or "expected to work".
- [x] **S5 — gates that can run here.**
  - `get_patches_from_recipe(..., arch='arm64')` and `arch='x86_64'` on the gcc recipe with the macos
    flavor: 2 vs 1 patches; `arch='aarch64'` normalizes to the same as `arm64`; bad type raises.
  - `python python/rpm_builder.py --package gcc --flavor lbl --spec-only`: generated spec identical
    before/after (the selector is shared by all three builders).
  - `patch -p1 --dry-run` of both patches, in recipe order, against an extracted upstream
    gcc-16.2.0 tarball (GNU patch on the Linux dev host; evidence level 4). macOS BSD `patch` with
    the four `/dev/null` new-file hunks is a stated residual risk — the recipe is `bootstrap: true`
    and must use the host `patch` (`unix_builder.py:1276`).
  - Wall time of that apply vs. the 60 s `apply_patches` timeout (`patch_common.py:294`).
  - `git status` lists exactly: `python/patch_common.py`, `patches/gcc/<new>.patch`, `recipes/gcc.yaml`,
    `changelogs/gcc.md`, `devlog/…`, `devlog/README.md`, `README.md`, `doc/MACOS_BUILD.md`,
    `web/scls.html.j2`, `todo/gcc_apple_silicon_patch.md` (S5 previously said "five files" — wrong).

## Round-1 outcome (2026-09-04)

- Q1 gating: both auditors — stay arm64-only. Grok adds two Intel-side reasons: the branch drops two
  `fixincludes` Darwin fixes (count 251→249) and moves `libd10-uwfef.a` between `extra_parts` cases.
- Q2 `-march=native`: Codex accepted, Grok challenged (assumed the spec maps `-march=native` → `arch`).
  Refuted from upstream source: `gcc-16.2.0/gcc/config/aarch64/aarch64.h:1545` routes a lone
  `-march=native` to `local_cpu_detect(cpu)` → `-mcpu=apple-m{1,2,3}`, which upstream accepts
  (`aarch64-cores.def:186-202`). The `arch` branch is taken only with `-mcpu=*`/`-mtune=*` also present;
  no recipe or flavor sets those. Apple clang has accepted `-march=native` on AArch64 since LLVM 15.
  **No flavor flag change.** M4/M5 hosts fall back to `apple-m1` tuning.
- Q3: dict-entry `arch:`; both auditors reject a top-level `macos-arm64` key.
- Q4: no `release:` bump.
- Q5: no Homebrew prefix or `--with-*` assumptions; libgcc floor `-mmacosx-version-min=11.0`.

## Open questions for the jury (round 1, as posed)

1. **Gating.** Any reason to follow Homebrew and apply on Intel too? The branch also patches generic
   Darwin code (`gcc/config/darwin.cc`, `darwin-driver.cc`, `collect2.cc`, `fixincludes/`) — is any
   of that a fix Intel users are currently missing, strong enough to justify re-validating Intel?
2. **`-march=native`.** `flavors/macos.yaml` passes `-march=native` in all flag sets. The branch
   modifies `gcc/config/aarch64/driver-aarch64.cc`; does it implement host-CPU detection on Darwin
   so that `-march=native` is accepted by the resulting compiler *and* by the stage-2/3 bootstrap?
   If not, arm64 needs a flavor-level flag override.
3. **`arch:` semantics.** String-or-list on dict entries is the minimal extension. Is a top-level
   `patches: {macos-arm64: [...]}` key (through `resolve_flavor_key`) preferable? I say no: it would
   make `arm64` look like a flavor component and collide with the hyphen-splitting in
   `get_flavor_names`.
4. **Release number.** `recipes/gcc.yaml` has no `release:` field; the change is invisible to `lbl`.
   Changelog as a dated entry under a new `16.2.0-2` heading without bumping `release:`, or bump it?
5. Anything in the patch that assumes Homebrew's prefix layout or its `--with-*` configure args
   (e.g. `libgcc/config/aarch64/t-darwin`, `gcc/config/aarch64/darwin.h`)? I read the file list, not
   every hunk.
