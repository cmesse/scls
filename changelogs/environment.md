# Environment Changelog

## Version 2026-2 - Sun Sep 13 2026
- Declare the host toolchain as a runtime dependency. The installed stack
  is a development stack and users compile against it, but `AutoReqProv: no`
  meant no package pulled in a compiler; RHEL hosts only worked because the
  build hosts already had one. `rpm_requires:` on this recipe now carries
  `gcc`, `gcc-c++`, `gcc-gfortran`, `glibc-devel` and `make` for the flavors
  that build with the host GCC (`gcc`, `mkl`, `debug`, `gcc-mkl-cuda`); on
  Debian that translates to `gcc, g++, gfortran, libc6-dev, make`, the
  build-essential set. `lbl` (ships its own gcc) and `intel` (oneAPI
  compilers, no distro package) get only `make`.
- Add `rpm_recommends:` with `doxygen` as a weak dependency (`Recommends:`
  on both RPM and DEB). Nothing in the stack runs doxygen; it is a
  convenience for developers, and on RHEL 9/10 it lives in CRB, so a hard
  requirement would break `dnf install scls-<flavor>` on a fresh host.
- The generated environment spec now honours the recipe `release:`, emits
  `Requires:`/`Recommends:` and sets `AutoReqProv: no` like every other
  SCLS package.

## Version 2026-1 - Fri Apr 03 2026
- Initial generated environment package for the 2026 stack.
