# Vtk Changelog

## Version 9.7.0-1 - Tue Aug 18 2026
- 2026-09-10: the macos flavor's `-isystem` paths for the SCLS libstdc++ are
  now derived from the installed GCC via the new gcc_version and gcc_machine
  recipe macros (probed from the prefix's bin/g++) instead of a
  hardcoded `include/c++/16.1.0/x86_64-apple-darwin24.6.0`, which broke as
  soon as the GCC version or the host (Apple Silicon: 16.2.0,
  aarch64-apple-darwin25.2.0) moved. macos now also `requires: gcc`. The
  registry `cflags` include path was corrected from `vtk-9.6` to `vtk-9.7`
  (stale since the 9.7.0 bump; affects the registry entry on every flavor).
  VTK on macOS is still compiled with Apple clang by design. No release bump;
  the Linux cmake lines are unchanged.
- Updated to version 9.7.0
- Rebuild for the OpenMP runtime fix: `-fopenmp` is now injected from
  `features.openmp` directly rather than via the math flags, which only ran when
  `features.math` was truthy. This recipe declares `openmp: true` but was
  compiled without the flag.
- Source URL series directory corrected to `release/9.7`; it still pointed at
  `release/9.6`, so the 9.7.0 tarball 404'd.
- The package now owns the directories it creates. The auto-generated file list
  claimed `%dir` only one level below `lib/` and `share/` and never under
  `include/`, leaving 258 directories unowned -- the whole `include/vtk-9.7`
  tree and all of `lib/cmake/vtk-9.7`. RPM never removes a directory it does not
  own, so the 9.6 -> 9.7 upgrade orphaned `lib/cmake/vtk-9.6` and
  `share/vtk-9.6`, leaving a stale `find_package(VTK)` config resolvable. Fixed
  in `templates/default.spec.j2` for all `rpm_files_auto` recipes; this package
  was re-wrapped from the existing payload rather than recompiled, so every file
  digest is unchanged.

## Version 9.6.2-1 - Tue Jun 09 2026
- Updated to version 9.6.2

## Version 9.6.1-1 - Sat Apr 04 2026
- Initial SCLS package for vtk 9.6.1
