# Slepc Changelog

## Version 3.25.1-3 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuild of the scotch reverse-dependency
  closure (scotch, mumps, strumpack, petsc, slepc, sundials) after an unexplained
  `-DBUILD_LIBSCOTCHMETIS` flip was found in `recipes/scotch.yaml` (95da949, 2026-04-01).
  With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so each
  package in the closure gets a new release.

## Version 3.25.1-2 - Tue Aug 18 2026
- Rebuild against petsc 3.25.4. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 3.25.1-1 - Tue Jun 09 2026
- Updated to version 3.25.1

## Version 3.25.0-1 - Mon Apr 13 2026
- Updated to version 3.25.0

## Version 3.24.3-1 - Sat Apr 04 2026
- Initial SCLS package for slepc 3.24.3
