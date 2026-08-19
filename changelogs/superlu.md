# Superlu Changelog

## Version 7.0.1-2 - Tue Aug 18 2026
- Rebuild against metis 5.2.1-2. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 7.0.1-1 - Mon Apr 13 2026
- Updated to version 7.0.1

## Version 7.0.0-1 - Fri Apr 03 2026
- Initial SCLS package for superlu 7.0.0
