# Openmpi Changelog

## Version 5.0.10-3 - Mon Aug 24 2026
- Add flex to rpm_build_requires for all flavors, and flex -> flex to
  packaging/system_packages.yaml so deb_builder's check_system_build_deps
  fails loudly on any host that lacks it. This is defence in depth, not a
  root-cause fix: the ASC-2026 -2 rebuilds of openmpi on Ubuntu 24.04
  intermittently produced a package with libmpi but no PRRTE tools
  (`prte`/`prterun`/`prted`/`pterm`, plus libprrte.so), yielding a runtime
  `mpirun: unable to find an underlying prterun`. A second rebuild of the
  same 5.0.10-2 NEVRA on the same host (no recipe change, no flex install)
  came out correct, so the trigger isn't purely environmental. Flex is
  nominally optional -- PRRTE ships pre-generated *_lex.c newer than the
  *_lex.l -- but adding it costs nothing, matches what RHEL/Rocky build
  hosts already have, and eliminates one class of "regenerate silently to
  empty" mode should automake's LEX rule ever fire. The real root cause is
  still unknown; document as it is understood.

## Version 5.0.10-2 - Tue Aug 18 2026
- Rebuild against hwloc 2.14.0, ucx 1.20.1, libevent 2.1.13 and pmix. No recipe or source change; the release is
  bumped because the rebuilt binaries differ and `AutoReqProv: no` means
  nothing else would signal that. Without the bump the package keeps its
  previous NEVRA and `dnf upgrade` silently treats it as already current.

## Version 4.1.6-1 - Sat Apr 25 2026
- Updated to version 4.1.6

## Version 5.0.10-1 - Sun Apr 12 2026
- Updated to version 5.0.10

## Version 5.1.0-1 - Sun Apr 12 2026
- Updated to version 5.1.0

## Version 5.0.9-1 - Fri Apr 03 2026
- Initial SCLS package for openmpi 5.0.9
