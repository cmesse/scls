# XZ Changelog

## Version 5.8.4-1 - Sat Oct 03 2026
- New recipe, macOS only: liblzma for scotch's .xz graph-file support (the Apple SDK has no
  `lzma.h`). Library only (`--disable-xz`, `--disable-scripts`, ... per LFS ch. 6), so no GPL
  scripts ship. 5.6.0 and 5.6.1 (CVE-2024-3094) are excluded from the update checker and refused
  at configure time (Christian, 2026-10-03).
- Library-only install checked on the EL9 build host with 5.8.3, the LFS stable version (headers, `liblzma.so.5.8.3`, `liblzma.pc`;
  `liblzma.la` removed by the builders). The macOS manifest is unverified until the first macOS build.
