# Libunwind Changelog

## Version 1.8.3-3 - Sat Oct 03 2026
- No longer ships upstream's test executables (`libexec/libunwind/`, 50 files, which also carried the
  `<triplet>-` prefix from the builder's old `--target`). The builder no longer passes `--target`
  (D3), and `install.post` removes the directory (Christian, 2026-10-03). Libraries, headers and
  `libunwind.so.8` unchanged; nothing that links them needs rebuilding.
- lbl: `requires: xz`. lbl builds xz in-stack and it is installed before libunwind configures, so libunwind's minidebuginfo support links that liblzma; declared because AutoReqProv is off. Same release: 1.8.3-3 is not published (Christian, 2026-10-03). Other flavors unchanged.

## Version 1.8.3-2 - Tue Aug 18 2026
- The package now owns the directories it creates. The auto-generated file list
  claimed `%dir` only one level below `lib/` and `share/` and never under
  `include/`, so nested directories were never removed on erase and were left
  orphaned on upgrade. Fixed in `templates/default.spec.j2` for all
  `rpm_files_auto` recipes; this package was re-wrapped from the existing
  payload rather than recompiled, so every file digest is unchanged.

## Version 1.8.3-1 - Thu Apr 23 2026
- Initial SCLS package.
