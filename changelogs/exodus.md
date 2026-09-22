# Exodus Changelog

## Version 2026.08.11-2 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuilt because hdf5, netcdf, openmpi changed in the 2026-09-22 campaign (`todo/rebuild_campaign_20260922.md`). With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so the release is bumped.

## Version 2026.08.11-1 - Tue Aug 19 2026
- Updated to version 2026.08.11
- Corrected source url and extract_dir, which still pointed at the previous
  v2025-10-14 tag. The tag uses dashes where version: uses dots, so neither
  can be interpolated from %{version} and both must be bumped by hand.

## Version 2025.10.14-1 - Sat Apr 04 2026
- Initial SCLS package for exodus 2025.10.14
