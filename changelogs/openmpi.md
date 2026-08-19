# Openmpi Changelog

## Version 5.0.10-2 - Tue Aug 18 2026
- Rebuild against hwloc 2.14.0, ucx 1.20.1, libevent 2.1.13 and pmix. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 4.1.6-1 - Sat Apr 25 2026
- Updated to version 4.1.6

## Version 5.0.10-1 - Sun Apr 12 2026
- Updated to version 5.0.10

## Version 5.1.0-1 - Sun Apr 12 2026
- Updated to version 5.1.0

## Version 5.0.9-1 - Fri Apr 03 2026
- Initial SCLS package for openmpi 5.0.9
