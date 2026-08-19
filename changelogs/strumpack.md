# Strumpack Changelog

## Version 8.0.0-3 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: the runtime (`-lgomp` / `-liomp5`) is no
  longer passed in `CMAKE_<LANG>_STANDARD_LIBRARIES`, so upstream's configure-time
  OpenMP probes link correctly instead of failing on undefined `GOMP_*` and
  silently compiling out the features they gate. No source change; the mkl and
  intel flavors are the ones whose generated build differs.

## Version 8.0.0-2 - Mon Aug 17 2026
- Pin STRUMPACK_USE_OPENMP_TASKLOOP and STRUMPACK_USE_OPENMP_TASK_DEPEND to
  TRUE instead of letting upstream's try_compile probes decide. Both probes
  returned FALSE in the mkl flavor's build environment on el9, el10 and
  amzn2023, so the shipped mkl libstrumpack had its OpenMP tasking code
  paths compiled out and the multifrontal factorization did not scale with
  thread count. The gcc and debug flavors were unaffected.

## Version 8.0.0-1 - Sat Apr 04 2026
- Initial SCLS package for strumpack 8.0.0
