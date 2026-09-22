# Scotch Changelog

## Version 7.0.15-1 - Tue Sep 22 2026
- Updated to version 7.0.15
- All three patches apply at fuzz 0 against 7.0.15 (`patch --dry-run -F0` on the dev host).

## Version 7.0.13-1 - Tue Aug 18 2026
- Updated to version 7.0.13
- Refreshed scotch-shared.patch for 7.0.13. Upstream changed the lines above
  the scotcherr target, so hunk 2's leading context no longer matched and
  rpmbuild's `--fuzz=0` rejected it. The patch's actual changes are unchanged;
  only the context was regenerated.

## Version 7.0.11-1 - Fri Apr 03 2026
- Initial SCLS package for scotch 7.0.11
