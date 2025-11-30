# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

SCLS (Scientific Computing Library Stack) is a Python-based build system for creating optimized scientific computing packages. It manages compilation and packaging of scientific software with different optimization flavors (e.g., gcc-debug, gcc-mkl, intel-mkl, macos) for both Linux (RPM) and macOS systems.

## Architecture

The build system has three main components:

1. **Recipe System** (`recipes/*.yaml`): Package definitions containing metadata, dependencies, build instructions, and configuration options
2. **Flavor System** (`flavors/*.yaml`): Platform and compiler-specific configurations (optimization flags, math libraries, MPI implementations)  
3. **Builder System** (`python/`): Python modules that process recipes and flavors to generate build artifacts

Key modules:
- `rpm_builder.py`: Generates RPM SPEC files and builds RPMs for Linux systems
- `mac_builder.py`: Direct builds for macOS without SPEC files
- `build_order.py`: Resolves dependencies and determines parallel build order
- `build_common.py`: Shared utilities for downloading, extracting, building packages
- `math_common.py`: Math library configuration (MKL, reference BLAS/LAPACK, ScaLAPACK)
- `patch_common.py`: Patch management system

## Build Commands

### Generate RPM SPEC file only (Linux):
```bash
python python/rpm_builder.py --package <package> --flavor <flavor> --spec-only
# or use the shortcut:
./mkspec <package>  # Uses gcc-debug flavor by default
```

### Build RPM package (Linux):
```bash
python python/rpm_builder.py --package <package> --flavor <flavor>
```

### Build for macOS:
```bash
python python/mac_builder.py --package <package> --flavor macos
```

### Determine build order for packages:
```bash
python python/build_order.py recipes --flavor <flavor>
```

### Generate website documentation:
```bash
./makeweb
# or
python python/generate_website.py --template web/scls.html.j2
```

## Key Configuration Patterns

### Recipe Structure
Recipes in `recipes/*.yaml` define:
- Package metadata (name, version, source URL, license)
- Dependencies (can be flavor-specific)
- Build configuration (configure type, arguments, environment)
- Features (fortran, mpi, openmp, math requirements)
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

### Build Process Flow
1. Load recipe and flavor configurations
2. Check if package should be built for flavor (via `should_build_package`)
3. Download and extract source tarball
4. Apply patches if defined
5. Configure (autotools/cmake)
6. Build with parallel make
7. Run tests if defined
8. Package (RPM for Linux, PKG for macOS)

## Testing

Individual package tests are defined in recipe files under the `test:` section. Run tests during build by including test commands in the recipe.

## Important Notes

- RPM builds require rpmbuild directory structure at `rpmbuild/`
- Sources are cached in `work/sources/`
- Build artifacts go to `work/build/`
- Patches are stored in `patches/<package>/`
- File tracking for packages stored in `files/<package>.txt`
- The system supports both serial and parallel math libraries
- MPI-enabled builds automatically use MPI compiler wrappers