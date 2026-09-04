# SCLS

SCLS, the Scientific Core Library Stack, is an opinionated build and packaging system for scientific computing libraries.

The project exists to solve a specific problem: getting a consistent, usable stack of numerical libraries built and installed across real machines, not idealized ones. That includes modern Enterprise Linux systems with RPM packaging, Debian/Ubuntu systems with DEB packaging, older or awkward Linux environments where native packaging is not an option, and macOS on Intel — Apple Silicon has the required GCC patch vendored but no build evidence yet.

## Copyright Notice

Scientific Core Library Stack (SCLS) Copyright (c) 2026,
The Regents of the University of California,
through Lawrence Berkeley National Laboratory
(subject to receipt of any required approvals from the U.S. Dept. of Energy).
All rights reserved.

If you have questions about your rights to use or distribute this software,
please contact Berkeley Lab's Intellectual Property Office at
IPO@lbl.gov.

NOTICE.  This Software was developed under funding from the U.S. Department
of Energy and the U.S. Government consequently retains certain rights.  As
such, the U.S. Government has been granted for itself and others acting on
its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the
Software to reproduce, distribute copies to the public, prepare derivative 
works, and perform publicly and display publicly, and to permit others to do so.

## License

SCLS is licensed under the Lawrence Berkeley National Laboratory BSD variant, SPDX identifier `BSD-3-Clause-LBNL`. See [`LICENSE`](LICENSE).

## What SCLS Is For

SCLS builds libraries that are meant to work together as a coherent stack: BLAS/LAPACK, MPI-enabled math libraries, sparse solvers, graph partitioners, I/O libraries, and their dependencies.

The goal is not to expose every possible build option. The goal is to produce a stack that is:

- consistent
- reproducible
- installable
- usable by downstream scientific software without constant manual repair

On systems where RPM integration makes sense, SCLS aims to produce packages that can be installed with a normal package manager workflow such as `dnf`. On systems where that is not realistic, SCLS still aims to build and install the same stack directly with Unix-style prefix installs.

## Core Philosophy

SCLS is deliberately opinionated.

This is not a general-purpose meta-build framework. It makes choices so the resulting stack remains coherent:

- GCC is the default toolchain because it is open, reliable, and has strong Fortran support.
- MKL and OpenBLAS are treated as backend choices selected by flavor (`mkl` vs `gcc`), not as an invitation to rebuild everything ad hoc.
- LP64 is the default integer model; ILP64 is supported when it is actually needed.
- OpenMPI is the default MPI implementation.
- Shared libraries are the normal target.
- Numerical correctness matters more than aggressive flag games; this project is not interested in `-ffast-math`.
- Python is not part of the stack. Interpreter choice is too site- and user-specific (system, pyenv, conda, spack, modules), so SCLS does not ship a Python and recipes disable Python (and other language) bindings by default. Users bring their own interpreter and bind against the installed C/C++ libraries themselves.
- Boost is not part of the stack. Modern C++ (C++17/20) has absorbed most of what scientific code historically needed from Boost (`filesystem`, `optional`, `variant`, `any`, `string_view`), and the libraries SCLS cares about either never required Boost or have dropped the dependency. Adding Boost would mean pulling in a very large, slow-to-build tree of sublibraries to satisfy a shrinking set of optional features. Where a recipe offers a "build tests with Boost" switch, SCLS disables it.
- SCLS avoids GPL-3 linkable libraries in distributed binary flavors. GPL-3 build tools are acceptable because they are executed during the build, not linked into the delivered libraries. GPL-2, LGPL, and CeCILL-C scientific libraries may be included when their source and redistribution obligations are practical for SCLS to satisfy. See [`doc/LICENSE_POLICY.md`](doc/LICENSE_POLICY.md) for the package policy and rationale.
- Binaries depend only on what the recipe declares, not on what the build host happens to have. Autodetection at configure or Makefile time is a silent-failure pattern: a missing probe produces a binary that quietly lacks features the recipe claimed it would have. OpenBLAS's OpenMP support is the canonical case — when `getconf _NPROCESSORS_ONLN` returns 1 on a single-CPU build host (mockbuild container, CI runner with cgroup limits, small VM), OpenBLAS silently builds sequential regardless of `USE_OPENMP=1`. Recipes therefore declare explicit caps and build dependencies so the same recipe produces the same binary across build hosts.

The bias is toward a curated stack rather than an infinitely configurable one. If the requirement is "I need exactly seventeen custom feature toggles for one package," this is the wrong tool. If the requirement is "I need PETSc, HDF5, OpenBLAS, NetCDF, MUMPS, and friends to build and coexist sanely," this is exactly the kind of tool that helps.

## Why Not Just Use System Packages?

Sometimes you should.

But in scientific and HPC environments, system packages often stop being enough:

- the distro is too old
- the available versions do not line up well
- the ABI story is inconsistent across dependencies
- the machine is locked down
- the platform is unusual
- the package set is incomplete

SCLS exists for the cases where you still need a real stack, and you want one build model across Linux and macOS rather than a pile of unrelated one-off installs.

## Build and Install Modes

SCLS supports multiple delivery paths built from the same recipe and flavor model.

### 1. RPM-based Enterprise Linux builds

On RHEL-family Enterprise Linux systems such as RHEL, Rocky Linux, AlmaLinux, CentOS Stream, and Amazon Linux 2023, SCLS can generate SPEC files and build RPMs. This is the preferred route when the target system supports it, because it gives you normal package-manager installation and removal semantics.

### 2. DEB-based Linux builds

On Debian/Ubuntu hosts SCLS produces `.deb` packages from the same recipes and flavors. The builder stages into a DESTDIR buildroot and wraps it with `dpkg-deb --build`, the DEB analogue of the RPM path. A 3.0 (quilt) source-package triplet (`.dsc` + `.orig.tar.<ext>` + `.debian.tar.xz`) is produced alongside the binary for license-compliance parity with source RPMs. Recipe `rpm_build_requires` and `rpm_requires` are translated to Debian names via [`packaging/system_packages.yaml`](packaging/system_packages.yaml); any unknown RHEL name is a hard error, not a silent fallback.

DEB packaging is intentionally less feature-complete than RPM packaging. It can split recipe subpackages such as `*-examples`, but it does not currently build the optional all-examples meta-package that the RPM path emits. Adding full DEB meta-package parity would be extra packaging machinery for little practical improvement in the current stack.

### 3. Generic Unix-style installs

SCLS also supports a direct Unix builder for environments where native packaging is not realistic or not desirable. This is useful for:

- older enterprise Linux systems
- HPC systems with limited admin control
- distributions outside the RPM path
- "Linux From Scratch"-style deployment into a controlled prefix

### 4. Native macOS builds

SCLS supports direct builds on macOS as well. The `macos` flavor is exercised regularly on Intel developer workstations. Apple Silicon has not been built yet: the `aarch64-apple-darwin` GCC branch that Homebrew carries is vendored in `patches/gcc/` and applied automatically on arm64 hosts, but nobody has run the bootstrap, so treat it as untested rather than as expected to work.

## How the Repository Works

The project is built around three core concepts.

### Recipes

[`recipes/`](recipes) contains package definitions. Recipes describe version, sources, dependencies, build system behavior, tests, patches, and feature requirements.

### Flavors

[`flavors/`](flavors) contains platform and toolchain choices. A flavor defines the target platform, compilers, optimization flags, math backend, MPI implementation, and install prefix. See [Flavors](#flavors) above for the available flavors and their prefixes.

### Builders

[`python/`](python) contains the code that turns recipes and flavors into actual builds:

- [`python/rpm_builder.py`](python/rpm_builder.py): RPM packaging for Enterprise Linux targets
- [`python/deb_builder.py`](python/deb_builder.py): Debian/Ubuntu `.deb` packaging, including 3.0 (quilt) source packages
- [`python/unix_builder.py`](python/unix_builder.py): direct Unix-style builds and installs
- [`python/build_common.py`](python/build_common.py): shared build logic
- [`python/build_order.py`](python/build_order.py): dependency ordering
- [`python/patch_common.py`](python/patch_common.py): patch selection and application
- [`python/math_common.py`](python/math_common.py): math-library-related configuration

## Repository Layout

- [`recipes/`](recipes): package definitions
- [`flavors/`](flavors): compiler/platform/math configurations
- [`patches/`](patches): package patches
- [`templates/`](templates): SPEC, DEBIAN/control, and related templates
- [`packaging/`](packaging): cross-distribution packaging data (e.g. RHEL→Debian system-package name mapping)
- [`python/`](python): builder implementation
- [`files/`](files): tracked install manifests
- [`changelogs/`](changelogs): package changelog sources (used by both RPM and DEB builders)
- [`rpmbuild/`](rpmbuild): local RPM build tree
- [`debbuild/`](debbuild): local DEB build tracking (marker files for build-order resolution)
- [`work/`](work): downloaded sources and build artifacts (including `work/pkgs` for binary `.deb` output and `work/spkgs` for source packages)

## Flavors

A flavor defines the target platform, compilers, optimization flags, math backend, and install prefix. Each flavor installs into its own prefix, so multiple flavors can coexist.

| Flavor          | Prefix                     | Compiler | Math      | Notes                                       |
|-----------------|----------------------------|----------|-----------|---------------------------------------------|
| `gcc`           | `/opt/scls/gcc`            | GCC      | OpenBLAS  | Default production build                    |
| `mkl`           | `/opt/scls/mkl`            | GCC      | Intel MKL | Requires `intel-oneapi-mkl` RPMs            |
| `debug`         | `/opt/scls/debug`          | GCC      | Reference | `-Og -g`, for valgrind / sanitizers         |
| `intel`         | `/opt/scls/intel`          | Intel    | Intel MKL | Requires Intel oneAPI compilers             |
| `lbl`           | custom site prefix         | GCC      | OpenBLAS  | LBL site-specific                           |
| `macos`         | `/opt/scls`                | GCC      | OpenBLAS  | Intel Macs; Apple Silicon patched, unbuilt  |
| `gcc-mkl-cuda`  | `/opt/scls/gcc-mkl-cuda`   | GCC      | Intel MKL | CUDA-enabled (NVIDIA HPC SDK); untested     |

### Deployment Targets

Flavors map to distinct deployment classes. The target informs which external dependencies are built against the system vs. supplied by the SCLS stack, and which schedulers and fabrics are pulled in.

| Flavor | Install target | Hardware / environment assumption |
|---|---|---|
| `lbl` | LBL HPC compute nodes | InfiniBand fabric and Slurm workload manager; builds against system PMIx, hwloc, libevent, and Slurm to stay binary-compatible with site infrastructure |
| `gcc` / `mkl` / `debug` | Cloud VMs (AWS, Azure, GCP), workstations, non-LBL HPC clusters — distributed via RPM/DEB repos | Mixed: TCP-only on commodity VMs and desktops through RDMA-capable fabric on cloud HPC instances and generic on-prem HPC clusters |
| `macos` | Developer workstation | TCP-only; macOS has no RDMA story |

Two policies follow from this table, and they're worth stating explicitly because the reasoning isn't symmetric.

**Slurm is scoped strictly to `lbl`.** Workstation and cloud installs of `gcc`/`mkl`/`debug` do not pull in a workload manager. Slurm is LBL-specific site infrastructure, not a general assumption — a researcher on an AWS instance or a laptop should not be forced to install `libslurm-dev` to get OpenMPI working.

**High-performance fabrics are supported universally**, except macOS where UCX isn't built at all. UCX in `gcc`/`mkl`/`debug` is configured with `--with-verbs` and `--with-rdmacm`. This matters for more than just on-prem HPC: AWS EFA (Elastic Fabric Adapter, available on `hpc7a`/`p5`/etc.) exposes itself through the libibverbs API, as do Azure HPC Mellanox SKUs. The runtime cost on a host with no fabric is ~500 KB of unused libraries that UCX dlopens and gracefully skips when no hardware is present; the cost of *not* supporting them universally is a ~10× MPI performance cliff on any cloud HPC or non-LBL HPC deployment of `gcc`/`mkl`/`debug`.

Slurm and RDMA fabric are correlated on traditional HPC clusters but not coupled. AWS HPC instances have EFA but no Slurm by default; the policies above handle that case correctly.

### Build host vs. install host

SCLS distinguishes the machine that *produces* packages from the machine that *consumes* them. RPMs and DEBs are typically produced once on a centralized build host (mock/pbuilder container, CI runner, maintainer workstation) and then distributed via a package repository or shared storage to many install hosts. Recipe `rpm_build_requires` / `rpm_requires` declarations describe the build host's and install host's needs respectively; the SCLS `requires:` field describes inter-package dependencies inside the stack.

The practical consequence: installing `libibverbs-dev` on your build host to compile `scls-gcc-ucx` does not mean the resulting package will require `libibverbs-dev` at install time. It requires only `libibverbs1` (the runtime soname package), which is tiny and harmless on machines without IB hardware.

## Quick Start

The `scls` wrapper is the recommended entry point. It reads `flavor.conf` (YAML) to determine the active flavor and dispatches to the appropriate builder.

```yaml
# flavor.conf
flavor: gcc
# gcc_toolset: 15        # uncomment on RHEL 8 to use Red Hat gcc-toolset-15
# extra_packages:        # uncomment to build packages not in the flavor's allowlist
#   - binutils
#   - gcc
```

Build and install the full flavor in dependency order:

```bash
./scls build all
```

For a granular or resumable flow, build and install the next package:

```bash
./scls build next
./scls install next
```

Build a specific package:

```bash
./scls build petsc
./scls install petsc
```

Other commands:

```bash
./scls spec petsc          # Generate SPEC file only (RPM mode)
./scls list                # List installed packages
./scls order               # Show build order
./scls check-updates       # Check upstream sources for newer versions
```

### Runtime environment

Each installed flavor ships activation scripts at both `activate` and
`activate.sh`. The canonical short form is:

```bash
source /opt/scls/<flavor>/share/scls/activate
```

Activation adds the prefix's `bin/` directory to `PATH`, exposes package
metadata through `PKG_CONFIG_PATH` and `CMAKE_PREFIX_PATH`, and exports
package-specific variables when the relevant package is installed. It does not
add the stack's `lib/` directory to `LD_LIBRARY_PATH` or `DYLD_LIBRARY_PATH`;
runtime lookup is handled by rpaths. The script does remove stale SCLS entries
from loader-path variables when switching between flavors.

For PETSc, `PETSC_DIR` points at the installed SCLS prefix and `PETSC_ARCH` is intentionally empty:

```text
PETSC_DIR=/opt/scls/<flavor>
PETSC_ARCH=
```

SCLS installs PETSc as an installed-prefix package, not as an in-place PETSc source tree with a runtime architecture directory, so consume it through `PETSC_DIR`, `pkg-config`, CMake, or PETSc's installed configuration files under `lib/petsc/conf`.

### Optional examples

PETSc, SLEPc, and SUNDIALS install their upstream tutorial/example sources under `%{prefix}/share/<package>/examples/`. In RPM builds, these are split into `<package>-examples` subpackages and are not pulled in by the flavor meta-package. An optional companion meta-package, `scls-<flavor>-examples`, is built alongside `scls-<flavor>` and groups all of them; install it if you want the examples on disk. DEB builds produce the per-package example subpackages but do not currently produce an all-examples meta-package.

### Direct builder invocation

For cases where the wrapper is not suitable:

```bash
# RPM SPEC file only (Enterprise Linux):
python python/rpm_builder.py --package <package> --flavor <flavor> --spec-only

# Build RPM package (Enterprise Linux):
python python/rpm_builder.py --package <package> --flavor <flavor>

# Generic Unix-style build/install:
python python/unix_builder.py --package <package> --flavor <flavor> build install

# macOS build with PKG creation:
python python/unix_builder.py --package <package> --flavor macos build install pkg

# Build order:
python python/build_order.py recipes --flavor <flavor>
```

## Operational Notes

- RPM builds use the project-local [`rpmbuild/`](rpmbuild) tree.
- Sources are cached under [`work/`](work).
- Patches are stored under [`patches/<package>/`](patches).
- File manifests live under [`files/`](files).
- Package metadata for installed stacks is tracked in the SCLS registry under the chosen prefix.

## Documentation for Agents

- [`CLAUDE.md`](CLAUDE.md) contains repository guidance for Claude Code.
- [`CODEX.md`](CODEX.md) points Codex-style agents at the same repository guidance.


## Status

SCLS is a pragmatic working project, not a polished framework. The implementation is opinionated because the problem is opinionated: scientific libraries either fit together as a stack or they do not.

That tradeoff is intentional.
