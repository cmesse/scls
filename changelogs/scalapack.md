# Scalapack Changelog

## Version 2.2.3-4 - Fri Sep 25 2026
- **MKL threading layer unified — recipe content change, not a rebuild bump.** On MKL-class
  flavors `libscalapack.so` was the only library in the stack linking `libmkl_sequential`; the
  other 256 MKL references in `/opt/scls/mkl` were `libmkl_gnu_thread`. Because petsc, mumps,
  strumpack, butterflypack and slepc all link `libscalapack.so.2.2` as well as the threaded MKL
  layer directly, `ldd libpetsc.so.3.25.5` loaded **both** `libmkl_gnu_thread.so.3` and
  `libmkl_sequential.so.3` into one process. Intel documents that as unsupported, and which
  layer's symbols win depends on load order.
- Cause was in `python/math_common.py:get_math_link_line`, which gated the MKL threading layer on
  the *recipe's* `features.openmp` as well as the flavor's `math.threading:`. This recipe declares
  `openmp: false` (ScaLAPACK has no OpenMP of its own), so it alone took the sequential branch.
  The gate is removed; the flavor is now the single source of truth. No change to this recipe's
  own options.
- **SONAME is unchanged** (`libscalapack.so.2.2`) and the exported ABI is unchanged, so the
  eight downstream packages resolve the new library at runtime with no rebuild.
  `doc/MKL_ABI_POLICY.md` triggers consumer rebuilds on an MKL *major SONAME* bump, which this is
  not.
- Known trade-off, accepted by Christian when scoping this in on 2026-09-25: ScaLAPACK's MKL
  BLAS calls are now threaded, so an MPI job with one rank per core can oversubscribe unless
  `MKL_NUM_THREADS` is set. Nothing in `recipes/environment.yaml` pins it today. Pinning it was
  considered and deliberately deferred — see `devlog/dl20260925_mkl_threading_uniformity.md`.
- Not part of the 2026-09-22 campaign, whose purpose was upstream bumps and the rebuilds they
  force. Scoped in separately on 2026-09-25 after belfem's `readelf` pass on the R9-mkl drop.

## Version 2.2.3-3 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuilt because openmpi changed in the 2026-09-22 campaign (`todo/rebuild_campaign_20260922.md`). With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so the release is bumped.

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
