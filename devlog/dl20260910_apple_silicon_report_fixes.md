# Devlog 2026-09-10 — Fixes from the first Apple Silicon bootstrap report

**Date:** 2026-09-10
**Topic:** Patch the seven findings of a colleague's M2 Pro bootstrap of the `macos` flavor (`tmp/scls_arm64_report.md`, main@399ae12) without access to an arm64 host
**AIs involved:** Claude (Fable 5.1), Codex (round 1 gpt-5.6-terra/high, round 2 gpt-6-astra/xhigh), Grok (grok-4.6, high then xhigh)
**Claude Confidence:** high on F2/F3/F6/F7, high on the unix side of F4/F5, medium (~80%) on the RPM-side F5 parity code (dead on every Linux recipe today)
**Auditor Confidence:** high (both auditors, both rounds); round 2 requested changes on F2 and the changelog text, all applied and re-gated
**Flavor / Host:** Intel macOS dev host (GCC 16.1.0 in /opt/scls, no rpmbuild, no arm64); report host M2 Pro, macOS 25.2, zsh
**Upstream References:** GKlib e2856c2 `CMakeLists.txt:29,94`, `apps/gkuniq.c:69`, `Makefile:62`; PETSc 3.25.0 and 3.25.4 `config/PETSc/options/arch.py:29-67` (byte-identical), `config/configure.py:73-89`
**Verification:** level 2 for the shell templates (rendered and sourced under bash 5.3 and zsh 5.9); level 3 for everything else (`--spec-only` diffs vs pre-patch baselines, `validate_project.py`, `build_order.py`, `check_args` / `generate_rpm_file_list` unit calls). Apple Silicon builds of the patched recipes are **pending an arm64 host**.

## Summary

The report was right about every diagnosis and wrong about one fix. All seven findings are now
patched; the round structure was plan → blind Codex+Grok audit → patch → blind Codex+Grok audit,
with executable gates in between. Two things the report did not know:

- **F7's suggested fix would have broken PETSc on every flavor.** `configure.env: PETSC_ARCH: ""`
  is passed through verbatim by all three builders (`patch_common.py:413-445`,
  `templates/default.spec.j2:124`), and PETSc's own configure aborts on an empty arch
  (`arch.py:66-67`, "PETSC_ARCH cannot be empty string"). The fix is to pass
  `PETSC_ARCH=arch-<os>-c-opt` as a configure *argument* (argDB beats the environment with a
  logged warning, `arch.py:45-57`), mirroring what `build:` and `install:` already pinned.
- **F2 has a third zsh defect the report missed.** Both path helpers use `${!var}` indirection,
  which zsh rejects as "bad substitution" before it ever reaches the reported `read -ra`. Under
  zsh the old script therefore did *nothing* to PATH and set a wrong `SCLS` root silently.

## Key Findings

- **F2** (`templates/scls-activate.sh.j2`, `scls-deactivate.sh.j2`): rewritten bash+zsh
  portable — self-location via `BASH_SOURCE` or zsh `%x` with a loud failure elsewhere; helpers
  use `eval`-based indirection, a `:`-walk with parameter expansion, and `case` prefix matching;
  no arrays, `[[`, `local`, regex or `read`; the body runs in a function so zsh gets a
  function-local `emulate -L sh` (Grok's request) and the caller's options are untouched. Also
  prunes the install's own `$SCLS/` prefix and the bare `$SCLS` entry, not only the literal
  `/opt/scls/`, so custom-prefix flavors are cleaned up too. `cd` output is silenced during
  self-location (a printing zsh `chpwd` hook otherwise lands inside `SCLS`). The bash-executed `scls-env` / `scls-deactivate` helpers keep their
  shebang and are untouched.
- **F3** (`recipes/gklib.yaml`): `configure.flavor_args: macos: [-DNO_X86=ON]`. Verified in the
  fetched upstream tree that `NO_X86` is a PUBLIC compile definition consumed only by
  `apps/gkuniq.c:69`; nothing under `src/`, so `libGKlib.a` and hence `libmetis.so` are
  unchanged (`doc/GKLIB_STATIC_POLICY.md`). Not `-DGKLIB_BUILD_APPS=OFF`, which drops
  `bin/csrcnv` from the manifest. A future Linux aarch64 flavor needs the same flag (deferred).
- **F4** (`python/unix_builder.py` `generate_rpm_file_list`): a macOS build never overwrites the
  tracked `files/<pkg>.txt` any more; it writes `work/files/<pkg>.txt` (under `project_root/work`,
  which survives the per-build `rmtree` of `work/build`) and prints why. `SCLS_WRITE_TRACKED_FILES=1`
  restores the old write for seeding a new recipe. Both auditors rejected my first "seed if missing"
  variant: the first macOS build of a new package would have created the RPM `%files` input from a
  Darwin tree. Linux unix-mode hosts are unchanged; `deb_builder`/`rpm_builder` never call it.
- **F5** (`recipes/vtk.yaml`, `python/build_common.py`, `unix_builder.py`, `rpm_builder.py`): new
  macros `%{gcc_version}` (`-dumpfullversion`) and `%{gcc_machine}` (`-dumpmachine`), backed by
  `build_common.gcc_identity()`, which probes `<prefix>/bin/<flavor cxx>` explicitly — never PATH
  (the builder's PATH is the developer's; `/usr/bin/g++` is Apple clang and reports
  `arm64-apple-darwin` where GCC says `aarch64-apple-darwin`) — and raises `BuildError` if the
  compiler is missing. The report's claim that a macro "needs a builder change because
  `get_cmake_args` only substitutes `%{prefix}`" was incomplete: the unix cmake argv already goes
  through `check_args` (`unix_builder.py:390`); the RPM cmake argv does **not**
  (`get_cmake_args_with_paths` `processed_args`), so both RPM sites were patched for parity
  (Codex and Grok both insisted). VTK on macOS is still compiled with Apple clang by design; only
  the libstdc++ header paths track the installed GCC. Registry `cflags` fixed `vtk-9.6` → `vtk-9.7`
  (stale since the 9.7.0 bump, visible on every flavor); macos now `requires: gcc`.
- **F6** (`recipes/openmpi.yaml:201`): `lib/libprrte.so` → `lib/libprrte%{libext}`. Substitution
  reaches `install.post` in all three builders (`unix_builder.py:779→:510`, `deb_builder.py:591`,
  `rpm_builder.py:742→:669`, then the prefix→`%{buildroot}%{prefix}` rewrite still applies).
  Linux specs are byte-identical; lbl (4.1.6) stays a no-op.
- **F7** (`recipes/petsc.yaml`): `PETSC_ARCH=arch-linux-c-opt` / `arch-darwin-c-opt` inserted into
  all seven `configure.flavor_args` keys; `gcc:` added to the `build:` and `install:` maps (the
  plain `gcc` flavor resolved no `PETSC_ARCH` at all — `get_flavor_names('gcc') == ['gcc']`).
  `configure.flavor_env` was rejected because `rpm_builder.get_configure_env_vars` walks only
  `configure.env` and would silently omit it from the spec (Grok). Second trigger Grok found:
  `share/scls/activate` itself exports `PETSC_ARCH=""` after PETSc is installed, so anyone who
  sourced the stack and then rebuilt petsc hit the same failure.
- **Docs:** README and `doc/MACOS_BUILD.md` now state what the M2 Pro run established (GCC
  bootstrap, install names, codesign, `-march=native`, 21 bootstrap packages plus gklib and
  openmpi) and what is still unbuilt (everything from openmpi onward; M4/M5 fallback).

## Round 1 (plan audit, blind)

Codex: take F3/F6/F7; revise F4 to never-seed; F5 needs the RPM `processed_args` site and an
explicit `<prefix>/bin/g++` probe. Grok: same two F5 conditions; `emulate -L sh`; `eval` must be
`no_unset`-safe; add an environment changelog; `flavor_env` would miss RPM for F7; plan citation
`unix_builder.py:388` should be `:390`. All taken except Grok's belt-and-suspenders `flavor_env`
(argDB precedence verified in source; a second mechanism to keep in sync is worse). Grok's open
risk "3.25.4 arch.py unread" closed by fetching it: identical to 3.25.0.

## Round 2 (patch audit, blind; Codex gpt-6-astra/xhigh, Grok grok-4.6/xhigh)

Both took F3/F4/F5/F6/F7 as implemented (Codex executed PETSc's `configureArchitecture()` in
isolation: the command-line arch wins over an empty and a non-empty inherited `PETSC_ARCH`, and
3.25.4's `arch.py` is byte-identical to 3.25.0). Changes requested and applied:

- **F2, Codex:** a zsh `chpwd` hook that prints corrupted `SCLS` (the `cd` inside the `$(…)` was
  not silenced) — fixed and re-tested; my wrapper transformation had dropped `clear` — restored.
- **F2, both:** the bare `$SCLS` entry that activation puts on `CMAKE_PREFIX_PATH` survived
  deactivation (pre-existing for `/opt/scls` too) — the helper now also drops an item equal to the
  prefix without its trailing slash; `unset -f` of a never-defined function returns 1 in zsh and
  under bash `set -e` — `|| :`.
- **F2, Grok residuals taken:** the zsh-only `%x` expansion is `eval`-wrapped so no bash parser
  tokenises it (Codex had already sourced it under bash 3.2.57 and 5.3.0); the `emulate` guard
  tests the builtin, not `ZSH_VERSION`.
- **Changelogs, Grok:** the new bullets contained `%{gcc_version}`, `%{prefix}`, `%{libext}`,
  `%x` and `%changelog`; `load_changelog` copies bullets verbatim into the spec's `%changelog`, so
  rpmbuild would macro-expand them. Desigiled. (`changelogs/sundials.md:8` has a pre-existing
  `%{prefix}`; left alone.)
- **F4, Grok:** the `SCLS_WRITE_TRACKED_FILES=1` path was CWD-relative while the default was
  project-root-relative — both are project-root-relative now.
- **Evidence wording, both:** "spec-only diff empty" overclaimed — the `%changelog` section
  differs by construction. Corrected to "identical outside `%changelog`"; re-diffed to confirm the
  only other hunks are the PETSc token and the VTK registry line. PETSc "package unchanged" is now
  "expected unchanged, not build-verified".
- **Residuals recorded, not changed:** activation's exit status is `unset -f`'s (nothing in the
  body returns non-zero); `gcc_identity`'s per-process cache (one package per `scls` invocation);
  the macros must not be reused on `lbl` (its GCC is built `--with-gcc-major-version-only`, so the
  directory is `include/c++/16` while `-dumpfullversion` says `16.2.0`) — documented in the
  docstring; Intel's `icpx` is not a GCC layout.

## Changes Made

`templates/scls-activate.sh.j2`, `templates/scls-deactivate.sh.j2`; `recipes/{gklib,openmpi,petsc,vtk}.yaml`;
`python/{build_common,unix_builder,rpm_builder}.py`; `README.md`, `doc/MACOS_BUILD.md`;
`changelogs/{gklib,openmpi,petsc,vtk}.md`, `changelogs/environment.md` (new);
`.claude/scripts/ask_codex.sh` (gpt-6-astra allowlisted, per Christian);
`todo/apple_silicon_report_fixes.md` (new tracker). No release bumps: no Linux artifact changes
(the petsc spec text gains one token per flavor; the vtk registry entry changes on every flavor).

## Gates run (Intel dev host)

| Gate | Result |
|---|---|
| `validate_project.py` | 0 errors, 0 warnings |
| `build_order.py` macos / lbl | 48+1 / 39+1 groups, unchanged |
| F2 rendered templates sourced twice from `/` with a stale `/opt/scls/stale/bin` on PATH | bash 5.3, /bin/bash 3.2 and zsh 5.9: correct `SCLS`, single `<prefix>/bin` at PATH head, deactivate restores PATH and `CMAKE_PREFIX_PATH`; zsh with a printing `chpwd` hook; zsh with `globsubst rc_expand_param extended_glob nomatch no_unset ksh_arrays sh_word_split`; bash `-e` sourcing deactivate.sh alone; bash with a leaked `ZSH_VERSION`; caller options unchanged |
| F5 `UnixBuilder('vtk','macos').check_args` on the new lines | byte-identical to the previous hardcode (this host: 16.1.0 / x86_64-apple-darwin24.6.0); bogus prefix raises `BuildError` |
| F4 `generate_rpm_file_list` on macOS, CWD=/ | writes `<repo>/work/files/gklib.txt`, `files/` untouched; with the override writes `<repo>/files/gklib.txt` |
| `--spec-only` vs pre-patch baselines (outside `%changelog`, which differs by construction) | openmpi mkl/gcc identical; gklib lbl/gcc identical; petsc gcc: `PETSC_ARCH` token on configure/make/install; petsc lbl: configure only; vtk gcc: registry cflags only |

`petsc --flavor mkl --spec-only` cannot run on this host (`%{libgomp}` needs a Linux gcc) — pre-existing dev-host ceiling.

## Open Questions

- Apple Silicon builds of gklib, openmpi, vtk and petsc with these diffs — the colleague's next
  bootstrap is the gate; MUMPS install names (INC-202) and the M4/M5 `hw.cpufamily` fallback remain.
- SLEPc (`recipes/slepc.yaml`) still inherits a user's `PETSC_ARCH`; part of the general
  env-hermeticity audit the report asked for (`PETSC_ARCH`, `CFLAGS`, `LDFLAGS`, `PKG_CONFIG_PATH`,
  `CMAKE_PREFIX_PATH`, `*_DIR`). Not started.
- The report's opt-in `SCLS_STRICT_PATH` prune: deferred; note its own caveat that the only
  PyYAML-bearing `python3` on that host is the python.org one.
- A Linux aarch64 flavor would need gklib's `-DNO_X86=ON` too; `flavor_args` has no arch axis.
- Stale memory: `project_vtk_x11_macos.md` says VTK on macOS uses X11; the recipe has
  `-DVTK_USE_COCOA=ON -DVTK_USE_X=OFF`. Not touched here.

## Files Updated

See "Changes Made".
