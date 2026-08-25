# Sundials Changelog

## Version 7.8.0-1 - Wed Aug 19 2026
- Updated to version 7.8.0
- Prepend the in-tree build library directories to LD_LIBRARY_PATH when running
  ctest. 7.8.0 introduces new libsundials_core symbols (e.g.
  SUNLogger_SetQueueAndFlushMsgFns) that the unit tests exercise, and CMake's
  build RPATH places the external link paths (which include %{prefix}/lib
  through GTest/MPI/PETSc) ahead of the in-tree build dirs. On a stack that
  already carries an older SUNDIALS, the loader therefore picked the stale
  installed library and the new symbol lookup failed, aborting `ctest`.
- Added the new sunnonlinsolauto module to the file manifest: 7.8.0 ships
  sunnonlinsol_auto.h and libsundials_sunnonlinsolauto. Nothing was removed.
- Dropped sundials-petsc-3.25-snesmonitorset.patch: 7.8.0 fixes this upstream,
  and does it better -- cv_petsc_ex7.c now guards the destroy-callback cast
  with `#if PETSC_VERSION_GE(3, 25, 0)` and PETSc's own PetscCtxDestroyFn
  typedef, instead of hard-coding one signature.
- Refreshed sundials-use-system-gtest.patch for 7.8.0. Upstream inserted an
  INSTALL_GTEST block above the line the patch targets, drifting the context
  far enough that even the default patch fuzz could not absorb it. The change
  itself is unaltered: uncomment find_package(GTest) so the stack's GTest is
  found before the FetchContent fallback.

## Version 7.7.0-2 - Tue Aug 18 2026
- Rebuild for the OpenMP runtime fix: the runtime (`-lgomp` / `-liomp5`) is no
  longer passed in `CMAKE_<LANG>_STANDARD_LIBRARIES`, so upstream's configure-time
  OpenMP probes link correctly instead of failing on undefined `GOMP_*` and
  silently compiling out the features they gate. No source change; the mkl and
  intel flavors are the ones whose generated build differs.

## Version 7.7.0-1 - Mon Apr 13 2026
- Updated to version 7.7.0
- Split example programs into sundials-examples subpackage

## Version 7.6.0-1 - Sat Apr 04 2026
- Initial SCLS package for sundials 7.6.0
