# Armadillo Changelog

## Version 15.6.0-2 - Fri Sep 25 2026
- **Stopped armadillo's own MKL detection from adding `libmkl_rt` — recipe content change.**
  `libarmadillo.so.15.6.0` linked `libmkl_rt.so.3` *and* the layered
  `libmkl_gf_lp64` / `libmkl_gnu_thread` / `libmkl_core` trio. `mkl_rt` is MKL's single-dynamic-
  library interface, which selects its threading layer at runtime from `MKL_THREADING_LAYER`;
  the layered libraries bind it at link time. Mixing the two models in one binary means the
  layer in force depends on load order and environment. Intel supports one or the other.
- `-DALLOW_MKL_LINUX=ON` (the option added by `armadillo-add-allow-mkl-option.patch`) is the
  path that pulled in `mkl_rt`. It is now `OFF` on the `mkl`, `intel` and `cuda` branches, with
  `-DCMAKE_DISABLE_FIND_PACKAGE_MKL=TRUE` and explicit `BLAS_LIBRARY`/`LAPACK_LIBRARY` set to
  `%{math_ldflags}` — the same shape the gcc/debug/lbl branches already used for OpenBLAS.
  The patch is retained and simply not enabled; other flavors rely on the option existing.
- `-DBLA_VENDOR=Intel10_64lp` is kept deliberately. It pins CMake's own `FindBLAS` to the Intel
  layered libraries so a host-installed OpenBLAS cannot win the search order, and is orthogonal
  to the `find_package(MKL)` path that produced `mkl_rt`.
- armadillo is a leaf: nothing in the stack depends on it, so nothing downstream rebuilds.
- Scoped in by Christian on 2026-09-25; not part of the 2026-09-22 campaign.

## Version 15.6.0-1 - Tue Sep 22 2026
- Updated to version 15.6.0
- Manifest drift, found on the first Linux build (R9/debug): upstream consolidated
  `fn_strans.hpp` + `fn_trans.hpp` into `fn_xtrans.hpp` and `fn_inplace_strans.hpp` +
  `fn_inplace_trans.hpp` into `fn_inplace_xtrans.hpp`, and added the new `cubemul` and
  `permute` features. `files/armadillo.txt`: 4 headers removed, 8 added. Transpose
  functionality is unchanged — `op_strans_*`, `op_htrans_*` and `xtrans_mat_*` are all
  still present, and every added header is referenced by the master `armadillo` header.

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
