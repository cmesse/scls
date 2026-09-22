# Mumps Changelog

## Version 5.9.1-2 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuild of the scotch reverse-dependency
  closure (scotch, mumps, strumpack, petsc, slepc, sundials) after an unexplained
  `-DBUILD_LIBSCOTCHMETIS` flip was found in `recipes/scotch.yaml` (95da949, 2026-04-01).
  With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so each
  package in the closure gets a new release.

## Version 5.9.1-1 - Tue Aug 18 2026
- Updated to version 5.9.1

## Version 5.9.0-1 - Tue Jun 09 2026
- Updated to version 5.9.0

## Version 5.8.2-1 - Sat Apr 04 2026
- Initial SCLS package for mumps 5.8.2
