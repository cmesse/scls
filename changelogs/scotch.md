# Scotch Changelog

## Version 7.0.13-1 - Tue Aug 18 2026
- Updated to version 7.0.13
- Refreshed scotch-shared.patch for 7.0.13. Upstream changed the lines above
  the scotcherr target, so hunk 2's leading context no longer matched and
  rpmbuild's `--fuzz=0` rejected it. The patch's actual changes are unchanged;
  only the context was regenerated.

## Version 7.0.11-1 - Fri Apr 03 2026
- Initial SCLS package for scotch 7.0.11
