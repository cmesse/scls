# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

SCLS (Scientific Core Library Stack) is a Python-based build system for creating optimized scientific computing packages. It manages compilation and packaging of scientific software with different optimization flavors (e.g., gcc, mkl, debug, intel, lbl, macos) for both Linux (RPM) and macOS systems.

Read [`README.md`](README.md) first for the project philosophy, supported build modes, and the intended user-facing model. Use this file for repository-specific implementation guidance.

## License

This repository is licensed under the Lawrence Berkeley National Laboratory BSD variant, SPDX identifier `BSD-3-Clause-LBNL`. See [`LICENSE`](LICENSE) for the canonical text.

## Architecture

The build system has three main components:

1. **Recipe System** (`recipes/*.yaml`): Package definitions containing metadata, dependencies, build instructions, and configuration options
2. **Flavor System** (`flavors/*.yaml`): Platform and compiler-specific configurations (optimization flags, math libraries, MPI implementations)
3. **Builder System** (`python/`): Python modules that process recipes and flavors to generate build artifacts

Key modules:
- `rpm_builder.py`: Generates RPM SPEC files and builds RPMs for Linux systems
- `unix_builder.py`: Direct Unix-style builds and installs for Linux/macOS (also serves as the macOS builder)
- `build_order.py`: Resolves dependencies and determines parallel build order
- `build_common.py`: Shared utilities for downloading, extracting, building packages
- `math_common.py`: Math library configuration (MKL, reference BLAS/LAPACK, ScaLAPACK)
- `patch_common.py`: Patch management system

## Build Commands

### Using the `scls` wrapper (preferred)

The `scls` wrapper reads the active flavor from `flavor.conf` (YAML format) and dispatches to the correct builder (RPM on RHEL-family Linux, unix_builder elsewhere).

`flavor.conf` fields:
- `flavor:` (required) — active flavor name (e.g., `gcc`, `mkl`, `debug`)
- `python:` (optional) — path to the Python interpreter; defaults to `python3`
- `gcc_toolset:` (optional) — Red Hat gcc-toolset version (e.g., `15`); sources `/opt/rh/gcc-toolset-N/enable` for RHEL 8 hosts
- `extra_packages:` (optional) — list of packages to build even though the recipe's `flavors:` allowlist excludes the active flavor; also added to the meta-package's Requires

Available flavors and their install prefixes:

| Flavor   | Prefix            | Compiler | Math        |
|----------|-------------------|----------|-------------|
| `gcc`    | `/opt/scls/gcc`   | GCC      | OpenBLAS    |
| `mkl`    | `/opt/scls/mkl`   | GCC      | Intel MKL   |
| `debug`  | `/opt/scls/debug` | GCC      | Reference   |
| `intel`  | `/opt/scls/intel` | Intel    | Intel MKL   |
| `lbl`    | `/opt/scls/lbl`   | GCC      | OpenBLAS    |
| `macos`  | `/opt/scls/macos` | GCC      | OpenBLAS    |

Commands:

```bash
./scls build <package>       # Build a package
./scls build next            # Build the next unbuilt package in dependency order
./scls install <package>     # Install the last built RPM (Linux RPM mode only)
./scls install next          # Install the next unbuilt package's RPM
./scls spec <package>        # Generate SPEC file only (Linux RPM mode)
./scls list                  # List installed packages
```

### Direct builder invocation

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
# or use: ./buildorder
```

## Key Configuration Patterns

### Recipe Structure
Recipes in `recipes/*.yaml` define:
- Package metadata (name, version, source URL, license)
- Dependencies (can be flavor-specific via dict with `all:`, `<flavor>:` keys)
- Build configuration (configure type: autotools/cmake/custom/none)
- Features (fortran, mpi, openmp, math requirements)
- Flavor restrictions (`flavors:` allowlist, `exclude_flavors:` blocklist)
- Pre/post build commands
- Test commands

### Flavor Configuration
Flavors in `flavors/*.yaml` specify:
- Platform (linux/macos)
- Compilers (cc, cxx, fc)
- Optimization flags (cflags, cxxflags, fcflags)
- Math library configuration (MKL, reference BLAS)
- MPI implementation
- Installation prefix
- Optional inheritance (`inherits:` field for flavor fallback)

### Build Order and Groups
- The `environment` package always builds first (Group 0), before all other packages
- Remaining packages are topologically sorted by dependency into groups
- Packages within the same group can be built in parallel
- The registry at `{prefix}/share/scls/registry/{package}.yaml` tracks built packages

### Build Process Flow
1. Load recipe and flavor configurations
2. Check if package should be built for flavor (via `should_build_package`)
3. Download and extract source tarball
4. Apply patches if defined (flavor-aware patch selection)
5. Configure (autotools/cmake)
6. Build with parallel make
7. Run tests if defined
8. Package or install directly (RPM for Linux when applicable, direct Unix install otherwise, PKG for macOS when requested)
9. Write registry entry to mark package as built

## Important Conventions

### Directory layout
- RPM builds use the repo-local `rpmbuild/` tree (explicit `_topdir`)
- Sources are cached in `work/`
- Build artifacts go to `work/`
- Patches are stored in `patches/<package>/`
- File tracking for packages stored in `files/<package>.txt`

### lib / lib64 (Linux From Scratch convention)
- On Linux, the `environment` package creates `lib64/` and symlinks `lib -> lib64`
- On macOS, `lib/` is used directly with no `lib64` split
- All other packages install into `lib/` — the symlink handles the rest on Linux

### Licensing
- The project targets BSD-3 compatibility for distributed packages
- GPL-3 licensed packages (binutils, make, sed, etc.) emit a build-time warning
- GPL-3 libraries must NOT be distributed as part of the stack; local builds only
- FFTW is excluded from the stack for this reason

### Flavor-specific package restrictions
- `gcc` and `binutils` are only built for specific flavors (see their `flavors:` lists); on hosts where the system toolchain is too old (e.g. RHEL 8), they can be added to `extra_packages:` in `flavor.conf` or a `gcc_toolset:` can be specified instead
- Most flavors (gcc, mkl, debug, etc.) use the system compiler toolchain
- The `lbl` flavor builds its own GCC and binutils
- macOS builds GCC but uses system binutils

## Testing

Individual package tests are defined in recipe files under the `test:` section. Run tests during build by including test commands in the recipe.
