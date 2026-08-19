# Libunwind Changelog

## Version 1.8.3-2 - Tue Aug 18 2026
- The package now owns the directories it creates. The auto-generated file list
  claimed `%dir` only one level below `lib/` and `share/` and never under
  `include/`, so nested directories were never removed on erase and were left
  orphaned on upgrade. Fixed in `templates/default.spec.j2` for all
  `rpm_files_auto` recipes; this package was re-wrapped from the existing
  payload rather than recompiled, so every file digest is unchanged.

## Version 1.8.3-1 - Thu Apr 23 2026
- Initial SCLS package.
