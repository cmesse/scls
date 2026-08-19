# Pmix Changelog

## Version 5.0.10-2 - Tue Aug 18 2026
- Rebuild against hwloc 2.14.0 and libevent 2.1.13. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 5.0.10-1 - Mon Apr 13 2026
- Updated to version 5.0.10

## Version 5.0.8-1 - Fri Apr 03 2026
- Initial SCLS package for pmix 5.0.8
