# Superlu_dist Changelog

## Version 9.2.1-2 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: the runtime (`-lgomp` / `-liomp5`) is no
  longer passed in `CMAKE_<LANG>_STANDARD_LIBRARIES`, so upstream's configure-time
  OpenMP probes link correctly instead of failing on undefined `GOMP_*` and
  silently compiling out the features they gate. No source change; the mkl and
  intel flavors are the ones whose generated build differs.

## Version 9.2.1-1 - Sat Apr 04 2026
- Initial SCLS package for superlu_dist 9.2.1
