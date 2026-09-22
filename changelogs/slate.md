# Slate Changelog

## Version 2025.05.28-3 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuilt because openmpi, blaspp, lapackpp changed in the 2026-09-22 campaign (`todo/rebuild_campaign_20260922.md`). With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so the release is bumped.

## Version 2025.05.28-2 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: the runtime (`-lgomp` / `-liomp5`) is no
  longer passed in `CMAKE_<LANG>_STANDARD_LIBRARIES`, so upstream's configure-time
  OpenMP probes link correctly instead of failing on undefined `GOMP_*` and
  silently compiling out the features they gate. No source change; the mkl and
  intel flavors are the ones whose generated build differs.

## Version 2025.05.28-1 - Sat Apr 04 2026
- Initial SCLS package for slate 2025.05.28
