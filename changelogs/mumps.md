# Mumps Changelog

## Version 5.9.1-3 - Sun Oct 04 2026
- MKL flavors: the MKL directories (`<mklroot>/lib/intel64`, `<mklroot>/lib`) are added to the RUNPATH of `libdmumps.so`, `libsmumps.so` and `libmumps_common.so` (`RPATH_OPT` in `templates/mumps/Makefile.inc.j2`). The three libraries NEED the MKL interface, threading and core libraries (`libmkl_gf_lp64`, `libmkl_gnu_thread`, `libmkl_core` on the `mkl` flavor) but carried the prefix in RUNPATH only, so `ldd -r libdmumps.so` reported them as not found and gate G3 of the 2026-10-04 campaign failed on R9 mkl. Programs ran because another library had loaded MKL first.
- Other flavors: no change to the build. Rebuilt at release 3 on every flavor for version parity (Christian, 2026-10-04).
- No SONAME, header or file-name change; petsc and ipopt are not rebuilt for it.

## Version 5.9.1-2 - Tue Sep 22 2026
- Release bump only, no recipe content change: rebuilt because openmpi, scotch, scalapack, parmetis changed in the 2026-09-22 campaign (`todo/rebuild_campaign_20260922.md`). With `AutoReqProv: no` a rebuild at an unchanged NEVRA is invisible to dnf/apt, so the release is bumped.

## Version 5.9.1-1 - Tue Aug 18 2026
- Updated to version 5.9.1

## Version 5.9.0-1 - Tue Jun 09 2026
- Updated to version 5.9.0

## Version 5.8.2-1 - Sat Apr 04 2026
- Initial SCLS package for mumps 5.8.2
