# Superlu Changelog

## Version 7.0.1-3 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuilt because openblas changed in the 2026-09-22 campaign (`todo/rebuild_campaign_20260922.md`). With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so the release is bumped.

## Version 7.0.1-2 - Tue Aug 18 2026
- Rebuild against metis 5.2.1-2. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 7.0.1-1 - Mon Apr 13 2026
- Updated to version 7.0.1

## Version 7.0.0-1 - Fri Apr 03 2026
- Initial SCLS package for superlu 7.0.0
