# GCC Changelog

## Version 16.2.0-1 - Tue Aug 18 2026
- Updated to version 16.2.0
- Added a bin/cc symlink to the C compiler. bin/gcc, bin/g++ and bin/c++ were
  all created but cc was not, so anything falling back to the historical cc
  name (autotools' AC_PROG_CC, hand-written Makefiles) missed the stack
  compiler and picked up the system one. Noticed on macOS, but the symlink
  block is shared, so lbl was affected the same way.

## Version 15.2.0-1 - Fri Nov 29 2024
- Updated: GCC compiler collection to version 15.2.0
- Added: Support for latest C++26 features
- Fixed: macOS SDK path configuration
- Changed: Configure script sed replacement for version detection
- Added: Program suffix -scls to avoid conflicts with system GCC

## Version 15.1.0-1 - Thu Nov 14 2024
- Initial SCLS package for GCC 15.1.0
- Built with GMP, MPFR, and MPC dependencies
- Enabled languages: C, C++, Fortran, LTO
- Configured for single architecture (disabled multilib)
- macOS: Fixed dylib install names for proper linking