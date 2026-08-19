# Exodus Changelog

## Version 2026.08.11-1 - Tue Aug 19 2026
- Updated to version 2026.08.11
- Corrected source url and extract_dir, which still pointed at the previous
  v2025-10-14 tag. The tag uses dashes where version: uses dots, so neither
  can be interpolated from %{version} and both must be bumped by hand.

## Version 2025.10.14-1 - Sat Apr 04 2026
- Initial SCLS package for exodus 2025.10.14
