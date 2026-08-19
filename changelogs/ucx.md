# Ucx Changelog

## Version 1.20.1-1 - Tue Jun 09 2026
- Updated to version 1.20.1
- Use -Wno-deprecated-openmp instead of -Wno-error=deprecated-openmp. GCC
  rejects -Wno-error= for a warning name it does not know, so configure's
  first compiler test failed with "C compiler cannot create executables" on
  every GCC older than 16, including el9's system GCC 11.
- The package now owns the directories it creates. The auto-generated file list
  claimed `%dir` only one level below `lib/` and `share/` and never under
  `include/`, so nested directories were never removed on erase and were left
  orphaned on upgrade. Fixed in `templates/default.spec.j2` for all
  `rpm_files_auto` recipes; this package was re-wrapped from the existing
  payload rather than recompiled, so every file digest is unchanged.

## Version 1.20.0-1 - Fri Apr 17 2026
- Initial SCLS package for ucx 1.20.0
