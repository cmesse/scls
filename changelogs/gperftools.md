# Gperftools Changelog

## Version 2.18.1-2 - Sat Oct 03 2026
- Link the stack's libunwind on RPM builds. 2.18.1-1 on el9/el10/amzn built without it: the RPM
  %build environment carried `-L%{prefix}/lib` but no include path, so configure did not find
  `libunwind.h` and `--enable-libunwind` fell back to gcc's unwinder silently, while the package
  still Required `scls-<F>-libunwind`. Linux builds now get `CPPFLAGS=-I%{prefix}/include`, and
  configure fails unless `src/config.h` defines `USE_LIBUNWIND` (Christian, 2026-10-03;
  `todo/open_issues_20260927.md` §1).
- Skip the five pprof-dependent checks on every host (`ac_cv_path_PPROF_PATH=`). Upstream enables
  them whenever any `pprof` is on PATH and expects the Go pprof; with the Perl `/usr/bin/pprof`
  from EPEL, `profiler_unittest.sh` (`--unit=ms`) and both `heap-profiler*_unittest.sh` (`--hide=`)
  failed. `sampling_test` and `sampling_debug_test` are skipped with them. Test-only: installed
  files are unchanged, and the release stays -2 because -2 was not yet published (Christian,
  2026-10-04).

## Version 2.18.1-1 - Thu Apr 02 2026
- Updated to version 2.18.1

## Version 2.17.2 - Wed Dec 10 2025
- initial build