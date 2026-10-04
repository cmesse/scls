# Hwloc Changelog

## Version 2.14.0-2 - Sat Oct 03 2026
- Tools ship under their plain names (`lstopo`, `hwloc-bind`, ...). Since the builder's first
  commits it passed `--target=<host>` to every autotools configure, and hwloc's
  `AC_CANONICAL_TARGET` then installed every program as `<triplet>-<name>`
  (`x86_64-redhat-linux-lstopo`, `x86_64-apple-darwin24.6.0-lstopo`). The builder no longer passes
  `--target` (Christian, 2026-10-03, D3). Library and SONAME (`libhwloc.so.15`) unchanged.

## Version 2.14.0-1 - Tue Aug 18 2026
- Updated to version 2.14.0

## Version 2.13.0-1 - Mon Apr 13 2026
- Updated to version 2.13.0

## Version 2.12.1-1 - Fri Apr 03 2026
- Initial SCLS package for hwloc 2.12.1
