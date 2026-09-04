# GCC Changelog

## Version 16.2.0-1 - Tue Aug 18 2026
- 2026-09-04, macos flavor on Apple Silicon only: vendored Iain Sandoe's
  aarch64-apple-darwin branch as patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch,
  byte-identical to homebrew-core Patches/gcc/gcc-16.2.0.diff at commit
  4a334d2f90f786c3fc86cbc9cf72b2f13961b078 ("gcc 16.2.0", 2026-08-20), sha256
  578a78ae0bc62a02f260b6a20c7f23e71deee16ed644e9cb5619247be4df5a71. Upstream GCC
  has no aarch64-apple-darwin target, so without it the build cannot configure
  on Apple Silicon. Gated with the new `arch: arm64` patch-entry key, so the
  Intel macOS build and the lbl RPM are untouched (the lbl spec differs only
  in this %changelog text); no release bump for that reason. The patch is version-locked:
  re-fetch the matching Homebrew diff on every GCC bump. Evidence so far is a
  clean `patch -p1 --dry-run` of both macos patches against the upstream
  16.2.0 tarball (GNU patch, Linux host); there is no Apple Silicon build
  evidence yet. See devlog/dl20260904_gcc_apple_silicon_patch.md.
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