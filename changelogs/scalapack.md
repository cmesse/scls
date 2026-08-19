# Scalapack Changelog

## Version 2.2.3-2 - Tue Aug 18 2026
- Rebuild against openmpi. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 2.2.3-1 - Mon Apr 13 2026
- Updated to version 2.2.3
- Dropped scalapack_fix_prototypes.patch (fixed upstream)

## Version 2.2.2-1 - Fri Apr 03 2026
- Initial SCLS package for scalapack 2.2.2
