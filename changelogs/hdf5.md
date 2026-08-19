# Hdf5 Changelog

## Version 1.14.6-2 - Tue Aug 18 2026
- Enabled the Fortran interface (`--enable-fortran`). `features.fortran: true`
  was already declared, and the registry entry advertised it, but nothing
  passed the flag to configure -- the package had shipped no Fortran interface
  at all. Adds libhdf5_fortran, libhdf5hl_fortran, the h5*/hdf5 .mod files and
  the h5pfc wrapper (h5pfc rather than h5fc because this is a parallel build),
  plus the H5f90i/H5config_f headers and the libhdf5_hl_fortran.so alias that
  HDF5 installs next to libhdf5hl_fortran.so.
- Rebuild against openmpi. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 1.14.6-1 - Fri Apr 03 2026
- Initial SCLS package for hdf5 1.14.6
