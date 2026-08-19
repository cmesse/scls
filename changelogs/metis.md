# Metis Changelog

## Version 5.2.1-2 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: `-fopenmp` is now injected from
  `features.openmp` directly rather than via the math flags, which only ran when
  `features.math` was truthy. This recipe declares `openmp: true` but was compiled
  without the flag. No source change; all flavors' generated builds differ.

## Version 5.2.1-1 - Fri Apr 03 2026
- Updated to version 5.2.1

## Version 5.1.0-1 - Mon Dec 15 2025
- Initial SCLS package for metis 5.1.0
