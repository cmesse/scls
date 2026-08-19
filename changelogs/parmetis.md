# Parmetis Changelog

## Version 4.0.3-2 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: `-fopenmp` is now injected from
  `features.openmp` directly rather than via the math flags, which only ran when
  `features.math` was truthy. This recipe declares `openmp: true` but was compiled
  without the flag. No source change; all flavors' generated builds differ.

## Version 4.0.3-1 - Fri Apr 03 2026
- Initial SCLS package for parmetis 4.0.3
