# Armadillo Changelog

## Version 15.4.2-1 - Tue Aug 18 2026
- Updated to version 15.4.2
- Collapsed the 644 individually listed armadillo_bits headers in
  files/armadillo.txt into a single `armadillo_bits/*.hpp` glob. 15.4.2 added
  op_find_aux_bones.hpp and op_find_aux_meat.hpp, which failed the build as
  unpackaged files; the directory is flat, contains only headers, and no other
  package installs into it, so the glob removes this drift for good.

## Version 15.2.7-1 - Tue Jun 09 2026
- Updated to version 15.2.7

## Version 15.2.6-1 - Sun Apr 19 2026
- Upstream point release (15.2.4 → 15.2.6); no SCLS recipe changes.

## Version 15.2.4-1 - Sat Apr 04 2026
- Initial SCLS package for armadillo 15.2.4
