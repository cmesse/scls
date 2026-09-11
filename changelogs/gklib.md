# Gklib Changelog

## Version 0.0.1-2 - Tue Aug 18 2026
- 2026-09-10, macos flavor only: add `-DNO_X86=ON` via `configure.flavor_args`.
  apps/gkuniq.c uses x86 inline asm (clflush/sfence) that the arm64 assembler
  rejects, so `scls build gklib` died at 89 percent on Apple Silicon; upstream's own
  NO_X86 option (CMakeLists.txt:29, apps/gkuniq.c:69 is its only consumer)
  removes it. libGKlib.a is unchanged and every Linux spec is identical apart from
  this changelog; no release bump for that reason. First reported and build-verified by the
  M2 Pro bootstrap of 2026-09-10 (devlog/dl20260910_apple_silicon_report_fixes.md).
- Rebuild for the OpenMP runtime fix: `-fopenmp` is now injected from
  `features.openmp` directly rather than via the math flags, which only ran when
  `features.math` was truthy. This recipe declares `openmp: true` but was compiled
  without the flag. No source change; all flavors' generated builds differ.

## Version 0.0.1-1 - Fri Apr 03 2026
- Initial SCLS package for gklib 0.0.1
