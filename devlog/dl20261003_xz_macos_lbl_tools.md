# Devlog 2026-10-03 — xz on macos and lbl, with tools; lbl consumers use the stack's xz

**Date:** 2026-10-03
**Topic:** `recipes/xz.yaml` (5.8.4, added macOS-only and library-only in `cbdbf2b`) now also
builds on lbl and ships the 0BSD tools; libunwind and scotch use it on lbl.
**AIs involved:** Claude Fable 5.1 (macOS dev host); Codex gpt-5.6-terra `high` and Grok 4.7 `high`,
blind plan round and two blind implementation rounds (`tmp/ai_exchange/plan_xz_recipe.md`,
`impl_xz_recipe.md`, `impl_xz_lbl_tools.md`).
**Claude Confidence:** macOS high; lbl RPM medium (~60%), no rpmbuild.
**Flavor / Host:** macos on the macOS dev host (x86_64, Apple clang); lbl by spec generation only.
**Upstream References:** xz 5.8.4 tarball: `configure --help`, `COPYING`, `src/*/Makefile.am`,
`m4/getopt.m4`.
**Verification:** level 2 on macOS — `./scls build xz` exit 0, `make check` 21/21, `files/xz.txt`
equals the `DESTDIR` install list (modulo `.dylib`/`.so`, `liblzma.la`, licence files). Level 3
for Linux — `--spec-only` before/after for scotch and libunwind on gcc, mkl, debug, intel,
gcc-mkl-cuda, lbl; `build_order.py`; `validate_project.py` 0 errors; `update_checker.py xz`.
**Not run:** any `rpmbuild`; a live install into `/opt/scls` (needs sudo), so scotch on macOS
against the stack's liblzma is untested.

## Decisions (Christian, 2026-10-03)

- **Rule.** On packaged distributions (RPM/DEB flavors) autotools, xz and similar are part of the
  distribution and are not recompiled. The unix builder and macOS serve systems with no SCLS
  packages (e.g. EL8) or no rights to install packages; for `macos` and `lbl` a self-provided xz is
  the safe choice. This supersedes "lbl uses the distro xz-devel" in `cbdbf2b`.
- Ship the tools: older macOS has no `xz`, so `.tar.xz` sources could not be read.
- libunwind stays at release 3 and scotch at 7.0.15-2: neither is published.

## Changes

- `recipes/xz.yaml`: `include_flavors: [macos, lbl]`; `bootstrap: true`; the `--disable-xz`,
  `--disable-xzdec`, `--disable-lzmadec`, `--disable-lzmainfo`, `--disable-lzma-links` flags
  removed; `--disable-scripts` (GPLv2+), `--disable-doc`, `--disable-nls`, `--disable-static` and
  the CVE-2024-3094 ban kept; `registry:` flags added, since xz installs `liblzma.pc`, not `xz.pc`.
- `files/xz.txt`: Linux `.so` form, tools, LZMA Utils links, man pages, headers listed one by one.
- `recipes/libunwind.yaml`: `requires: {lbl: [xz]}`. On lbl xz (rank 1) is installed before
  libunwind configures, and libunwind enables minidebuginfo when it finds liblzma. Spec changes on
  lbl only.
- `recipes/scotch.yaml`: lbl `requires: xz`; `xz-devel`/`xz-libs` moved from `all:` to `gcc:`,
  `mkl:`, `intel:`, with `lbl: []` to stop the fallback to the inherited `gcc:`. lbl spec swaps
  the host packages for `scls-lbl-xz`; the other five Linux specs differ only in line order.

## Audit findings

| finding | source | outcome |
|---|---|---|
| libunwind on lbl would link the prefix liblzma undeclared | Codex P0, Grok P1 (plan) | declared |
| macOS tools link the bundled LGPL `getopt_long` | Codex P0 (plan) | refuted: `LIBOBJS=''`, `COND_GNULIB_TRUE='#'` in `config.log`; glibc not configured here |
| `%{prefix}/include/lzma` directory line: unix uninstall does not recurse | Codex P1, Grok P2 | headers listed individually |
| `lbl: []` stops the inherited `gcc:` fallback in rpm and deb builders | both | confirmed (`build_common.py:285`) |
| generated lbl specs carried stale changelogs | Codex P2 | regenerated |

## Open Questions

- **lbl gate (needs a Linux host):** `scls-lbl-xz` unpackaged-file check; whether libunwind's
  minidebuginfo probe sees the prefix `lzma.h` (`%build` exports `PKG_CONFIG_PATH` and `-L`, not
  `CPATH`), by `readelf -d libunwind.so`; scotch's `FindLibLZMA` picking the prefix copy; host gcc
  accepting `-march=x86-64-v3` for the bootstrap build.
- (fixed, see Follow-up) **macOS uninstall vs `.so` manifests.** `build_common.get_package_files()` reads
  `files/<pkg>.txt` literally, so `liblzma.so*` does not match the dylibs and they stay behind on
  `uninstall`. Same pre-existing shape as `files/gmp.txt`; one manifest cannot serve RPM `%files`
  and macOS. Builder question, not changed here.
- (fixed, see Follow-up) **RPM registry for xz:** bare `dependencies:` key (null) for a dependency-free bootstrap package
  (`templates/default.spec.j2`, read by `python/scls.py` with `', '.join`), and no rpath rewrite
  because `%post` probes `pkg-config --exists xz`. Both pre-existing builder behaviour.

## Files Updated

- recipes/xz.yaml, files/xz.txt, changelogs/xz.md
- recipes/libunwind.yaml, changelogs/libunwind.md
- recipes/scotch.yaml, changelogs/scotch.md

## Follow-up, same day: three builder fixes (Christian approved, 2026-10-03)

The three builder items under Open Questions are fixed. Plan and implementation each had a blind
Codex + Grok round (`tmp/ai_exchange/plan_registry_uninstall_fixes.md`,
`impl_registry_uninstall_fixes.md`). No package is recompiled and no release moves.

- **macOS uninstall.** `build_common.get_package_files()` now also yields the macOS names for
  shared-library manifest lines directly under `<prefix>/lib` (`libfoo.so` → `libfoo.dylib`,
  `libfoo.so.1.2` → `libfoo.1.2.dylib`, `libfoo.so.*` → `libfoo.<digits>.dylib`). Lines in
  subdirectories (Open MPI `mca_*.so`, OpenSSL modules) are not mapped. It is a name mapping, not an
  ownership check. Gate: `unix_builder.py --package gmp --uninstall --dry-run --force` on macOS
  lists `libgmp.dylib`, `libgmp.10.dylib`, `libgmpxx.dylib`, `libgmpxx.4.dylib`. No real uninstall
  was run.
- **Null `dependencies:`.** `templates/default.spec.j2` writes `dependencies: []` for a
  dependency-free package (cmake on every RPM flavor; binutils and xz on lbl), and the four readers
  (`python/scls.py` list/info, `build_common.py` reverse dependencies and recursive uninstall) use
  `entry.get('dependencies') or []`, so registry files already installed stay readable.
  `scripts/build_libhsl.py:588` still writes the bare key when it finds no dependencies; the
  readers tolerate it.
- **`registry.pc_name`.** New optional recipe key, default the package name, validated as a plain
  module name. Used by the RPM `%post` probe and by `write_registry_entry`. `recipes/xz.yaml` sets
  `pc_name: liblzma`, and its explicit `ldflags` now carry `-Wl,-rpath,%{prefix}/lib`, because the
  `%post` rewrite only runs when the host has `pkg-config` (Codex P1). RPM and DEB/unix registry
  flags are still not guaranteed identical: `%post` replaces recipe flags with pkg-config output,
  `write_registry_entry` lets recipe flags win.
- Spec check (`--spec-only`, gcc and lbl): scotch and hdf5 unchanged; cmake and binutils differ by
  the one `dependencies: []` line; lbl xz also probes `liblzma`.
- Still open: RPM `%post` on a Linux host; a real macOS uninstall.
