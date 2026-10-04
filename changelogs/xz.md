# XZ Changelog

## Version 5.8.4-1 - Sat Oct 03 2026
- New recipe for `macos` and `lbl`, the flavors that build their own toolchain (Christian, 2026-10-03). macOS: the Apple SDK has no `lzma.h`, which scotch's .xz graph-file support needs, and older macOS has no xz to read .tar.xz. lbl: the host's `xz-devel` cannot be assumed. Mainline Linux flavors keep the distro `xz-devel`/`xz-libs`.
- Ships shared liblzma, headers, `liblzma.pc`, and the 0BSD tools `xz`, `xzdec`, `lzmadec`, `lzmainfo` with the LZMA Utils links (`unxz`, `xzcat`, `lzma`, `unlzma`, `lzcat`) and man pages. No static library, no docdir files, no NLS.
- `--disable-scripts`: `xzgrep`, `xzdiff`, `xzless` and `xzmore` are GPLv2+ and do not ship.
- `bootstrap: true`: built with the host compiler, before the stack's GCC.
- 5.6.0 and 5.6.1 (CVE-2024-3094) are excluded from the update checker and refused at configure time.
- Built and tested on macOS (x86_64, Apple clang): `make check` 21/21. The bundled LGPL `getopt_long` is not compiled (`LIBOBJS=''`). The lbl RPM and `files/xz.txt` are unverified until the first lbl build.
