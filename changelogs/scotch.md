# Scotch Changelog

## Version 7.0.15-2 - Sat Oct 03 2026
- 2026-10-04, release kept because 7.0.15-2 is not published (`doc/BUILD_EXECUTION.md` §0.6):
  `-DSCOTCH_METIS_PREFIX=ON`. The METIS/ParMETIS emulation libraries (`libscotchmetisv3`,
  `libscotchmetisv5`, `libptscotchparmetisv3`) now export `SCOTCH_METIS_*` / `SCOTCH_ParMETIS_*`
  (Fortran `scotchf*`) instead of the unprefixed names, which collided with the real METIS and
  ParMETIS: `libpetsc` bound `ParMETIS_V3_PartKway` and `ParMETIS_V3_Mesh2Dual` to Scotch's
  emulation. This is how PETSc builds its own Scotch. File names and SONAMEs are unchanged;
  `libscotch`, `libptscotch`, `libesmumps` and `libptesmumps` are not affected, so mumps and
  strumpack are not rebuilt. A program outside the stack that linked the emulation libraries for the unprefixed
  names must link METIS/ParMETIS instead. Scotch stays at 7.0.15, the version PETSc 3.26.0 pins.
- Compressed graph files (gzip, bzip2, xz) on every flavor (Christian, 2026-10-03). The recipe's
  `-DCOMMON_FILE_COMPRESS_{BZ2,GZ,LZMA}=OFF` were never read by scotch's CMake (its options are
  `USE_ZLIB`, `USE_BZ2`, `USE_LZMA`, default ON, "if found"), so el9 linked all three and Ubuntu
  26.04 only zlib, depending on the build host. Now explicit `-DUSE_*=ON`, a configure check that
  fails when any library is not found, and declared `rpm_build_requires`/`rpm_requires`.
- macOS: zlib and bzip2 from the Apple SDK; liblzma from the new in-stack `xz` recipe (the SDK
  has no `lzma.h`).
- lbl: liblzma from the in-stack `xz` recipe instead of the host's `xz-devel`/`xz-libs`, which cannot be assumed there (Christian, 2026-10-03). Mainline flavors unchanged: their specs differ only in the order of the Requires lines.
- No consumer rebuild: SONAME `libscotch.so.7.0` and API are unchanged, the compression libraries
  are PRIVATE link dependencies of libscotch.

## Version 7.0.15-1 - Tue Sep 22 2026
- Updated to version 7.0.15
- All three patches apply at fuzz 0 against 7.0.15 (`patch --dry-run -F0` on the dev host).

## Version 7.0.13-1 - Tue Aug 18 2026
- Updated to version 7.0.13
- Refreshed scotch-shared.patch for 7.0.13. Upstream changed the lines above
  the scotcherr target, so hunk 2's leading context no longer matched and
  rpmbuild's `--fuzz=0` rejected it. The patch's actual changes are unchanged;
  only the context was regenerated.

## Version 7.0.11-1 - Fri Apr 03 2026
- Initial SCLS package for scotch 7.0.11
