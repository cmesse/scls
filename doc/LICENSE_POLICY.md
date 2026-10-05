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

### Published Binaries

Every package in a published binary flavor (`gcc`, `mkl` and `debug`, the RPM and DEB
repositories) carries a license compatible with SCLS's own `BSD-3-Clause-LBNL`
distribution. That means one of:

- a permissive license (see *Permissive Libraries*);
- a weak-copyleft license whose obligations attach to the library itself and leave
  the license of code that links against it alone: LGPL, CeCILL-C, EPL-2.0 (see
  *Weak-Copyleft Libraries*).

**No GPL, in any version.** A GPL-licensed package is not part of a published binary
flavor. The one place where the output of GPL code is linked into what ships is the
GCC runtime (libgcc, libstdc++, libgfortran), which is covered by the GCC Runtime
Library Exception.

GPL is allowed in the build scripts, for build tools only (see *GPL Build Tools*).

### Permissive Libraries

BSD, MIT, Apache, ISC, zlib, NetCDF-style, and similar permissive licenses are
preferred for linkable libraries. They are usually suitable for all SCLS
flavors, subject to normal notice preservation.

### GPL Linkable Libraries

GPL linkable libraries are not included in distributed binary flavors, GPL-2 and
GPL-3 alike. The version of the GPL is not the deciding factor: what matters is
whether SCLS ships the code as something downstream applications link against.

This is a pragmatic scientific-computing decision. The GPL can be a reasonable
license for some projects, but it is a poor fit for low-level numerical
libraries intended to sit underneath many unrelated downstream applications.
For a stack like SCLS, a GPL library creates too much uncertainty for users
who need to link mixed-license scientific software.

FFTW is the canonical example of a technically excellent numerical library that
is often avoided in binary stacks because its GPL licensing makes downstream
linking policy difficult. SCLS should not put users in that position.

SuiteSparse is the GPL-2 case. It carries GPL-2.0-or-later components alongside
LGPL-2.1, BSD-3-Clause and Apache-2.0 ones, and it is therefore **not shipped as a
binary**: `recipes/suitesparse.yaml` sets `include_flavors: []`, so it is never built
by default and must be opted into explicitly via `extra_packages:` for local use.
Source availability would not rescue it — the objection is to distributing the binary
at all, not to the compliance paperwork.

History: before 2026-09-23 this document said GPL-2-or-later libraries were "not
automatically excluded" and named SuiteSparse as acceptable when packaged with
complete source. That was never the practice: every GPL package in the recipe set is
a build tool or GCC, and SuiteSparse has carried `include_flavors: []` throughout.
The rule was restated as "published binaries are BSD-3-compatible, no GPL; GPL only
for build tools" on 2026-10-05 (Christian).

### GPL Build Tools

GPL build tools, of any GPL version, are acceptable in the build scripts when they
are only executed during the build. They exist in the recipe set because a source
build needs them where the system does not provide them: on macOS, and on Unix
systems for which SCLS publishes no binaries. In practice they are built on the
`macos` and `lbl` flavors, where SCLS builds its own compiler and build tools
rather than using the distribution's.

Examples include tools such as Autoconf, Automake, Libtool, GNU Make, GNU sed,
GNU m4, Texinfo, Bison, pkg-config, and Binutils. These tools do not become part
of the delivered numerical libraries simply because they were used to build them.

GCC is also acceptable as a compiler. Its runtime libraries, including libgcc
and libstdc++, are distributed with the GCC Runtime Library Exception, which is
designed to permit linking with non-GPL programs. GCC is the single case where
the output of GPL code is linked into what we ship.

### Weak-Copyleft Libraries

LGPL, CeCILL-C and EPL-2.0 are not the GPL and are not affected by the GPL rule
above. LGPL libraries follow *LGPL Libraries* below; CeCILL-C libraries (`mumps`,
`scotch`) follow *CeCILL-C Libraries*; both CeCILL-C packages ship on all flavors.

Ipopt is EPL-2.0 and ships on all flavors. EPL-2.0 is a weak-copyleft license: a
work that only contains declarations and interfaces of the library in order to link
to it or bind to it by name is not a "Modified Work" under EPL-2.0 section 1, so an
application that calls an unmodified `libipopt` keeps its own license. Distributing
the Ipopt binary still requires its source and license text, which the
*Source Availability* section below covers. How this applies to a particular
downstream product is a question for that product's counsel.

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

### Proprietary Libraries Built by the Licensee (HSL)

Some solvers that Ipopt can use are proprietary and licensed to an individual, not to a
site. The HSL linear solvers (MA27, MA57, HSL_MA77, HSL_MA86, HSL_MA97, HSL_MC68, MC19; see
[`HSL_BUILD.md`](HSL_BUILD.md) for which tarballs a licensee provides and how to build)
are the standing case: the HSL Academic Licence grants *personal* use, forbids sharing
the software or its use with anyone, including colleagues at the same institution, and
forbids commercial use. For these, SCLS follows one rule: **the scripts are public,
the sources and binaries are private.**

- SCLS ships **no** HSL source, no HSL binary, no package that depends on HSL, and no
  recipe. `recipes/ipopt.yaml` configures `--without-hsl`; Ipopt's runtime loader
  (`hsllib`) stays on so a licensee can supply the library themselves.
- What SCLS publishes is build tooling only: `scripts/build_libhsl.py`,
  `scripts/hsl/assemble_sources.sh`, `scripts/hsl/CMakeLists.txt` and the functional
  test under `scripts/hsl/tests/`. These contain no HSL text. The test exercises MA77
  through its documented C API and is compiled against the licensee's own header at
  build time.
- The licensee supplies the **original, unmodified** HSL tarballs. The assembler
  unpacks them into a directory outside the SCLS work tree, keeps each package's
  `LICENCE` under `LICENCES/`, and records inputs and checksums in `PROVENANCE.txt`.
  HSL *sources* never enter the work tree or the stack prefix.
- `./scls build hsl` only builds and checks; the result is staged owner-only under the
  system temporary directory. `./scls install hsl` installs it after three explicit answers, recorded
  in `share/hsl/build-info.yaml`, and then deletes the staged build:
  - install type: *local* (`~/.local/scls-hsl/<flavor>`, owner-only, Ipopt needs
    `hsllib <full path>`) or *global* (`/opt/scls/<flavor>`, readable by every user, owned
    by no package, published with sudo; Ipopt's default `hsllib` finds it via RUNPATH).
    A global install also writes a registry entry (`share/scls/registry/hsl.yaml`) so that
    `./scls list` shows it and `unix_builder.py --uninstall -p hsl` can remove it. That entry
    and the tracked `files/hsl.txt` (installed path names only) are a record of that private
    install; they are not a package and contain nothing HSL-derived;
  - license type: *academic* (personal, non-commercial, no sharing even within the
    institution; a global install is refused unless the user confirms being the machine's
    sole user) or *commercial* (an agreement with STFC whose terms the user holds);
  - acceptance: the license files from the user's tarballs are shown with SCLS's statement
    of what the user confirms for that combination; typed `yes` or `--accept-license`.
  SCLS grants no rights and distributes nothing; compliance is the licensee's. `LD_LIBRARY_PATH`
  / `DYLD_LIBRARY_PATH` are not an option here or anywhere in SCLS.
- `.gitignore` blocks HSL tarball, tree and library names anywhere in the repository.
  Nothing HSL-derived may be committed, staged to a repository host, pasted into a
  devlog or audit prompt, or given to another person. Each user needs their own
  license and their own build.
- Linking against the stack's own METIS, BLAS/LAPACK and OpenMP runtime is, in SCLS's
  reading, the platform optimization the Academic Licence allows a licensee; Coin-HSL
  itself ships the adapter for an external METIS. The optional override that takes a
  solver's sources from a newer standalone release the user also holds combines two of
  the user's distributions in one build; whether that is within their license is the
  user's decision (`--no-overrides` builds Coin-HSL as shipped). SCLS states its reading
  and grants nothing; compliance with the personal-use, no-sharing and non-commercial
  terms is the licensee's responsibility.

## Source Availability

For Linux RPM distribution, SCLS should provide matching source RPMs for binary
RPMs. The source package must correspond to the binary package: upstream
tarball, recipe, generated spec behavior, patches, build flags, and package
metadata should be sufficient to reproduce the build in the intended
environment.

For macOS distribution, SCLS may provide binary package contents together with
the original upstream source tarballs and SCLS build recipes on the same DMG.
This keeps source access coupled to the distributed binary artifact.

For Debian/Ubuntu distribution, the same rule holds with Debian source packages:
each shipped `.deb` comes with its `.dsc`, `.orig.tar.*` and `.debian.tar.*`.
The one exception is a closed list of packages that SCLS generates itself and
that contain no upstream code: `scls-archive-keyring` (APT key and sources
file), the flavor meta-packages `scls-<flavor>` (dependencies only) and
`scls-<flavor>-environment` (SCLS's own activation scripts and configuration).
Their source is the SCLS repository, published under `BSD-3-Clause-LBNL`, so
they may ship without a source package. A drop that ships one of them lists it
under `no_source:` with this exact reason:

`SCLS-generated packaging, no upstream source; source in the SCLS repository`

A package that is already published is listed under `already_published:` as usual. Any
other binary without a source package is not shipped, and the list grows only by
explicit decision (Christian, 2026-09-28).

## Current Policy Summary

- Published binaries: BSD-3-Clause-compatible licenses only, no GPL of any version
  (the GCC runtime is linked under the GCC Runtime Library Exception).
- Allowed: permissive libraries.
- Allowed with compliance review: weak-copyleft libraries (LGPL, CeCILL-C, EPL-2.0).
- Not in distributed binary flavors: GPL linkable libraries, GPL-2 and GPL-3 alike.
- Allowed in the build scripts: GPL build tools used only during the build
  (macOS, Unix systems without SCLS binaries, the `lbl` toolchain).
- Avoid as SCLS-owned Linux binary packages: GMP, MPFR, MPC.
- Prefer system packages for: GMP, MPFR, MKL, and other libraries where the
  system or vendor package is the clean redistribution boundary.
- Never shipped, licensee-built only: HSL (public build scripts, private sources
  and binaries).
