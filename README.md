# SCLS

SCLS, the Scientific Core Library Stack, is an opinionated build and packaging system for scientific computing libraries.

The project exists to solve a specific problem: getting a consistent, usable stack of numerical libraries built and installed across real machines, not idealized ones. That includes modern Linux systems with RPM packaging, older or awkward Linux environments where native packaging is not an option, and macOS on both Intel and Apple Silicon.

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
- Boost is not part of the stack. Modern C++ (C++17/20) has absorbed most of what scientific code historically needed from Boost (`filesystem`, `optional`, `variant`, `any`, `string_view`), and the libraries SCLS cares about (cereal, ensmallen, mlpack 4.x, etc.) either never required Boost or have dropped the dependency. Adding Boost would mean pulling in a very large, slow-to-build tree of sublibraries to satisfy a shrinking set of optional features. Where a recipe offers a "build tests with Boost" switch, SCLS disables it.
- GPL-3 libraries are not distributed as part of the stack. The project targets BSD-3 compatibility for anything downstream code links against, which excludes libraries like FFTW (GPL-2+). GPL-3 *build tools* — autoconf, automake, libtool, make, sed, m4, binutils — are fine to use: they are executed as binaries during the build, not linked into the resulting libraries, so their license does not propagate to the output. GCC is similarly fine to use as a compiler because libgcc and libstdc++ ship under GPL with the GCC Runtime Library Exception, which explicitly permits linking the runtime into non-GPL binaries.

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

### 1. RPM-based Linux builds

On RPM-oriented Linux systems, SCLS can generate SPEC files and build RPMs. This is the preferred route when the target system supports it, because it gives you normal package-manager installation and removal semantics.

### 2. Generic Unix-style installs

SCLS also supports a direct Unix builder for environments where native packaging is not realistic or not desirable. This is useful for:

- older enterprise Linux systems
- HPC systems with limited admin control
- distributions outside the RPM path
- "Linux From Scratch"-style deployment into a controlled prefix

### 3. Native macOS builds

SCLS supports direct builds on macOS as well. That includes older Intel Macs and should also extend to Apple Silicon through the same general recipe and flavor machinery.

## How the Repository Works

The project is built around three core concepts.

### Recipes

[`recipes/`](recipes) contains package definitions. Recipes describe version, sources, dependencies, build system behavior, tests, patches, and feature requirements.

### Flavors

[`flavors/`](flavors) contains platform and toolchain choices. A flavor defines the target platform, compilers, optimization flags, math backend, MPI implementation, and install prefix. See [Flavors](#flavors) above for the available flavors and their prefixes.

### Builders

[`python/`](python) contains the code that turns recipes and flavors into actual builds:

- [`python/rpm_builder.py`](python/rpm_builder.py): RPM-oriented Linux packaging
- [`python/unix_builder.py`](python/unix_builder.py): direct Unix-style builds and installs
- [`python/build_common.py`](python/build_common.py): shared build logic
- [`python/build_order.py`](python/build_order.py): dependency ordering
- [`python/patch_common.py`](python/patch_common.py): patch selection and application
- [`python/math_common.py`](python/math_common.py): math-library-related configuration

## Repository Layout

- [`recipes/`](recipes): package definitions
- [`flavors/`](flavors): compiler/platform/math configurations
- [`patches/`](patches): package patches
- [`templates/`](templates): SPEC and related templates
- [`python/`](python): builder implementation
- [`files/`](files): tracked install manifests
- [`changelogs/`](changelogs): RPM changelog sources
- [`rpmbuild/`](rpmbuild): local RPM build tree
- [`work/`](work): downloaded sources and build artifacts

## Flavors

A flavor defines the target platform, compilers, optimization flags, math backend, and install prefix. Each flavor installs into its own prefix, so multiple flavors can coexist.

| Flavor   | Prefix            | Compiler | Math      | Notes                                |
|----------|-------------------|----------|-----------|--------------------------------------|
| `gcc`    | `/opt/scls/gcc`   | GCC      | OpenBLAS  | Default production build             |
| `mkl`    | `/opt/scls/mkl`   | GCC      | Intel MKL | Requires `intel-oneapi-mkl` RPMs     |
| `debug`  | `/opt/scls/debug` | GCC      | Reference | `-Og -g`, for valgrind / sanitizers  |
| `intel`  | `/opt/scls/intel` | Intel    | Intel MKL | Requires Intel oneAPI compilers      |
| `lbl`    | `/opt/scls/lbl`   | GCC      | OpenBLAS  | LBL site-specific, builds own GCC    |
| `macos`  | `/opt/scls/macos` | GCC      | OpenBLAS  | macOS (Intel + Apple Silicon)        |

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

Build and install the next package in dependency order:

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
```

### Optional examples

PETSc, SLEPc, and SUNDIALS install their upstream tutorial/example sources under `%{prefix}/share/<package>/examples/`. These are split into `<package>-examples` subpackages and are not pulled in by the flavor meta-package. An optional companion meta-package, `scls-<flavor>-examples`, is built alongside `scls-<flavor>` and groups all of them; install it if you want the examples on disk.

### Direct builder invocation

For cases where the wrapper is not suitable:

```bash
# RPM SPEC file only (Linux):
python python/rpm_builder.py --package <package> --flavor <flavor> --spec-only

# Build RPM package (Linux):
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

## License

SCLS is licensed under the Lawrence Berkeley National Laboratory BSD variant, SPDX identifier `BSD-3-Clause-LBNL`. See [`LICENSE`](LICENSE).

## Status

SCLS is a pragmatic working project, not a polished framework. The implementation is opinionated because the problem is opinionated: scientific libraries either fit together as a stack or they do not.

That tradeoff is intentional.
