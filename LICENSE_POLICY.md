# SCLS License Policy

This document describes the packaging policy SCLS uses when deciding whether a
library belongs in the distributed stack. It is engineering policy, not legal
advice. When in doubt, ask project leadership and counsel before adding a new
dependency to a binary flavor.

SCLS itself is licensed under the Lawrence Berkeley National Laboratory BSD
variant, SPDX identifier `BSD-3-Clause-LBNL`; see [`LICENSE`](LICENSE). The
packages built by SCLS keep their upstream licenses.

## Goals

SCLS is a scientific library stack. The packages are meant to be linked by a
wide range of downstream codes: open source, lab internal, vendor-supplied,
commercial, and legacy applications with unclear licensing history.

The license policy therefore optimizes for:

- broad scientific reuse;
- low-friction binary redistribution on Linux;
- clear source availability through recipes, source RPMs, source tarballs, and
  patches;
- avoiding license terms that make normal downstream linking impractical.

## Practical Rules

### Permissive Libraries

BSD, MIT, Apache, ISC, zlib, NetCDF-style, and similar permissive licenses are
preferred for linkable libraries. They are usually suitable for all SCLS
flavors, subject to normal notice preservation.

### GPL-3 Linkable Libraries

GPL-3 linkable libraries are not included in distributed binary flavors.

This is a pragmatic scientific-computing decision. GPL-3 can be a reasonable
license for some projects, but it is a poor fit for low-level numerical
libraries intended to sit underneath many unrelated downstream applications.
For a stack like SCLS, a GPL-3 library creates too much uncertainty for users
who need to link mixed-license scientific software.

FFTW is the canonical example of a technically excellent numerical library that
is often avoided in binary stacks because its GPL licensing makes downstream
linking policy difficult. SCLS should not put users in that position.

### GPL-3 Build Tools

GPL-3 build tools are acceptable when they are only executed during the build.

Examples include tools such as Autoconf, Automake, Libtool, GNU Make, GNU sed,
GNU m4, Texinfo, Bison, and Binutils. These tools do not become part of the
delivered numerical libraries simply because they were used to build them.

GCC is also acceptable as a compiler. Its runtime libraries, including libgcc
and libstdc++, are distributed with the GCC Runtime Library Exception, which is
designed to permit linking with non-GPL programs.

### GPL-2 Libraries

GPL-2-or-later libraries are not automatically excluded.

They may be included when the project decides their scientific value justifies
the compliance obligations and when SCLS can provide corresponding source,
patches, build recipes, and license notices through the normal source RPM or
source-tarball distribution path.

SuiteSparse components such as UMFPACK are in this category. They are useful
scientific libraries and are acceptable in SCLS when packaged with complete
source availability and clear license metadata.

### LGPL Libraries

LGPL libraries may be included when SCLS can satisfy the normal LGPL
requirements.

For Linux binary flavors, prefer dynamic linking. Avoid statically folding LGPL
libraries into unrelated SCLS libraries unless there is a clear relinking story.

GMP, MPFR, and MPC need special treatment. They are LGPL/GPL-family libraries
used by important parts of the scientific stack, but SCLS should not ship them
as SCLS-owned binary packages for the mainline Linux binary flavors. Instead,
recipes should use the system-provided `gmp-devel` and `mpfr-devel` packages at
build time and depend on the corresponding system runtime packages.

The exceptions are flavors where SCLS is not distributing general Linux binary
packages, such as the LBL HPC flavor, and macOS builds where distribution is
handled as source-plus-binary media.

### CeCILL-C Libraries

CeCILL-C libraries, such as MUMPS and Scotch, are acceptable. CeCILL-C is a
weak-copyleft library license broadly comparable in intent to LGPL. Binary
redistribution still requires attention to source availability, license text,
and notice requirements.

### Proprietary Runtime Dependencies

Some flavors intentionally rely on external proprietary runtimes, most notably
Intel oneAPI MKL for the `mkl` and `intel` flavors. SCLS should depend on the
vendor-provided RPMs rather than copying vendor libraries into SCLS packages.

## Source Availability

For Linux RPM distribution, SCLS should provide matching source RPMs for binary
RPMs. The source package must correspond to the binary package: upstream
tarball, recipe, generated spec behavior, patches, build flags, and package
metadata should be sufficient to reproduce the build in the intended
environment.

For macOS distribution, SCLS may provide binary package contents together with
the original upstream source tarballs and SCLS build recipes on the same DMG.
This keeps source access coupled to the distributed binary artifact.

## Current Policy Summary

- Allowed: permissive libraries.
- Allowed: GPL-3 build tools used only during build.
- Allowed with compliance review: GPL-2-or-later scientific libraries.
- Allowed with compliance review: LGPL and CeCILL-C libraries.
- Avoid in distributed binary flavors: GPL-3 linkable libraries.
- Avoid as SCLS-owned Linux binary packages: GMP, MPFR, MPC.
- Prefer system packages for: GMP, MPFR, MKL, and other libraries where the
  system or vendor package is the clean redistribution boundary.
