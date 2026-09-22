# Scotch Changelog

## Version 7.0.13-2 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuild of the scotch reverse-dependency
  closure (scotch, mumps, strumpack, petsc, slepc, sundials) after an unexplained
  `-DBUILD_LIBSCOTCHMETIS` flip was found in `recipes/scotch.yaml` (95da949, 2026-04-01).
  With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so each
  package in the closure gets a new release.

## Version 7.0.13-1 - Tue Aug 18 2026
- Updated to version 7.0.13
- Refreshed scotch-shared.patch for 7.0.13. Upstream changed the lines above
  the scotcherr target, so hunk 2's leading context no longer matched and
  rpmbuild's `--fuzz=0` rejected it. The patch's actual changes are unchanged;
  only the context was regenerated.

## Version 7.0.11-1 - Fri Apr 03 2026
- Initial SCLS package for scotch 7.0.11
