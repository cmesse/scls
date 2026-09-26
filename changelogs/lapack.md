# Lapack Changelog

## Version 3.12.1-2 - Sat Sep 26 2026
- Build with `-ffp-contract=off` (approved by Christian). Works around a gfortran 15.2
  wrong-code bug: at `-O2 -march=x86-64-v3` the SLP vectorizer miscompiles the complex
  update at `zlaqr5.f:450`, so complex `ZGEEV`/`CGEEV` returned wrong eigenvectors for
  76 <= n < 150 (lapackpp `tester geev`, residual ~3e-3). Found on the U26 (Ubuntu 26.04)
  host; GCC 13 is not affected. No ABI or SONAME change; consumers are not rebuilt.
  See `devlog/dl20260926_u26_lapack_gfortran15_zlaqr5.md`.

## Version 3.12.1-1 - Sun Apr 05 2026
- Initial SCLS package for lapack 3.12.1
