#!/usr/bin/env python3
from typing import Dict
from pathlib import Path


def get_mkl_interface_lib(flavor: Dict) -> str:
    """Return the MKL Fortran interface library name (without -l prefix).

    The interface library encodes the Fortran calling convention. MKL ships
    two variants matching the two common Fortran ABIs:
      - 'mkl_gf_{lp64,ilp64}'    — gfortran (GCC) name mangling
      - 'mkl_intel_{lp64,ilp64}' — Intel ifort/ifx name mangling
    Mixing them within a single flavor is incorrect and produces either
    link-time unresolved symbols or subtle runtime corruption, so this
    is the single source of truth used across math_common, rpm_builder,
    unix_builder, and build_common.
    """
    cc = flavor.get('compilers', {}).get('cc', 'gcc')
    interface = flavor.get('math', {}).get('interface', 'lp64')
    family = 'intel' if cc in ('icx', 'icpx', 'icc') else 'gf'
    return f'mkl_{family}_{interface}'


def get_mkl_serial_link_line(flavor: Dict) -> str:
    """Canonical MKL serial (non-ScaLAPACK) link line for the given flavor.

    Used by %{mkl_linker_flags} expansion and anywhere else a package
    needs the raw MKL BLAS+LAPACK link line without ScaLAPACK/BLACS.
    """
    cc = flavor.get('compilers', {}).get('cc', 'gcc')
    iface = get_mkl_interface_lib(flavor)
    if cc in ('icx', 'icpx', 'icc'):
        threading = 'mkl_intel_thread'
        omp_rt = 'iomp5'
    else:
        threading = 'mkl_gnu_thread'
        omp_rt = 'gomp'
    return (f'-l{iface} -l{threading} -lmkl_core '
            f'-l{omp_rt} -lpthread -lm -ldl')


def get_mkl_mpi_link_line(flavor: Dict) -> str:
    """Canonical ScaLAPACK-enabled MKL link line.

    Per the stack's ScaLAPACK policy (see math_common.get_math_link_line),
    we do NOT use libmkl_scalapack/libmkl_blacs on MKL flavors. Instead we
    prefix the stack's own -lscalapack (built against MKL BLAS/LAPACK) to
    the serial MKL line. This keeps the link line identical regardless of
    whether the host's MKL ships ScaLAPACK or which BLACS variant it has.
    """
    return ('-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib -lscalapack '
            + get_mkl_serial_link_line(flavor))


def get_math_link_line(flavor: Dict, recipe: Dict) -> str:
    """Generate math library link line based on flavor and recipe settings"""
    # Get flavor settings
    math_config = flavor.get('math', {})
    omp_threading = math_config.get('threading', 'openmp')  # Fixed: was flavor.get('math', 'threading')
    linalg = math_config.get('linalg', 'reference')
    interface = math_config.get('interface', 'lp64')

    # Get compiler to determine OpenMP library
    compiler = flavor.get('compilers', {}).get('cc', 'gcc')

    # Get recipe features
    features = recipe.get('features', {})
    use_omp = features.get('openmp', False)
    use_mpi = features.get('mpi', False)
    math_type = features.get('math', None)  # 'serial', 'parallel', or None

    # Determine if we need parallel math libs
    parallel = (math_type == 'parallel') or (use_mpi and math_type)
    # Strict parallel: needs actual ScaLAPACK symbols, not just per-rank
    # BLAS. 'mpi:true + math:serial' packages do not call ScaLAPACK.
    needs_scalapack = (math_type == 'parallel')

    args = []

    if linalg == 'mkl':
        # MKL base path and rpath. oneAPI 2024+ installs into MKLROOT/lib
        # directly; older oneAPI (and some offline installers) use the
        # legacy MKLROOT/lib/intel64 layout. List both so the linker's
        # -L search covers either, and bake both into rpath so runtime
        # resolution matches. This mirrors build_common.py's
        # cmake_library_path, keeping the two sources consistent.
        args.append(
            '-Wl,-rpath,%{mklroot}/lib/intel64 -Wl,-rpath,%{mklroot}/lib '
            '-L%{mklroot}/lib/intel64 -L%{mklroot}/lib'
        )

        # ScaLAPACK (our build) goes first so it resolves against MKL
        # BLAS/LAPACK that follows. See get_mkl_mpi_link_line for rationale.
        if needs_scalapack:
            args.append('-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib -lscalapack')

        # Interface library (compiler-specific: mkl_gf for GCC, mkl_intel for ICX)
        args.append(f'-l{get_mkl_interface_lib(flavor)}')

        # Threading layer
        if use_omp:
            if compiler == 'gcc' or (compiler == 'clang' and omp_threading == 'openmp'):
                args.append('-lmkl_gnu_thread')
            elif compiler in ['icx', 'icpx', 'icc']:
                args.append('-lmkl_intel_thread')
        else:
            args.append('-lmkl_sequential')

        # Core library
        args.append('-lmkl_core')

        # OpenMP runtime
        if use_omp:
            if compiler == 'gcc' or (compiler == 'clang' and omp_threading == 'openmp'):
                args.append('-lgomp')
            elif compiler in ['icx', 'icpx', 'icc']:
                args.append('-liomp5')

        # System libraries
        args.append('-lpthread -lm -ldl')

    elif linalg == 'accelerate':
        # ScaLAPACK if parallel (must be built against Accelerate).
        # Mirror the prefix/lib -L + rpath dance used by the other branches
        # so produced binaries can resolve libscalapack at runtime without
        # relying on LIBRARY_PATH from the build host.
        if needs_scalapack:
            args.append('-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib -lscalapack')

        # Apple Accelerate framework
        args.append('-framework Accelerate')

        # OpenMP runtime (if needed)
        if use_omp:
            # On macOS with clang, we use libgomp from GCC
            args.append('-lgomp')

        # System libraries
        args.append('-lpthread -lm')

    elif linalg == 'openblas':
        # OpenBLAS provides BLAS+LAPACK via compat symlinks
        args.append('-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib')

        if needs_scalapack:
            args.append('-lscalapack')

        args.append('-lopenblas')

        # OpenMP runtime
        if use_omp:
            if compiler == 'gcc':
                args.append('-lgomp')
            elif compiler in ['icx', 'icpx', 'icc']:
                args.append('-liomp5')
            elif compiler == 'clang':
                if flavor.get('platform') == 'macos':
                    args.append('-lgomp')
                else:
                    args.append('-lomp')

        # System libraries
        args.append('-lpthread -lm -ldl')

    elif linalg in ['reference', 'lapack', None]:  # Handle all reference implementations
        # ScaLAPACK if parallel
        if needs_scalapack:
            args.append('-lscalapack')

        # LAPACK and BLAS
        args.append('-llapack -lblas')

        # OpenMP runtime
        if use_omp:
            if compiler == 'gcc':
                args.append('-lgomp')
            elif compiler in ['icx', 'icpx', 'icc']:
                args.append('-liomp5')
            elif compiler == 'clang':
                # Platform-specific
                if flavor.get('platform') == 'macos':
                    args.append('-lgomp')  # Use GCC's OpenMP on macOS
                else:
                    args.append('-lomp')  # LLVM's OpenMP on Linux

        # System libraries
        args.append('-lpthread -lm -ldl')

    return ' '.join(args)


def get_math_compile_flags(flavor: Dict, recipe: Dict) -> str:
    """Generate math-related compile flags based on flavor and recipe settings"""
    # Get compiler
    compiler = flavor.get('compilers', {}).get('cc', 'gcc')

    # Get recipe features
    features = recipe.get('features', {})
    use_omp = features.get('openmp', False)

    # Get math configuration
    math_config = flavor.get('math', {})
    linalg = math_config.get('linalg', 'reference')

    args = []

    # MKL include path
    if linalg == 'mkl':
        args.append('-I%{mklroot}/include')

    # OpenMP flags
    if use_omp:
        if compiler in ['icx', 'icpx', 'icc']:
            args.append('-qopenmp')
        elif compiler in ['gcc', 'g++', 'gfortran']:
            args.append('-fopenmp')
        elif compiler in ['clang', 'clang++']:
            # Yes, clang uses -fopenmp, but needs appropriate runtime library
            args.append('-fopenmp')
            # On macOS, might need to specify OpenMP headers location
            if flavor.get('platform') == 'macos':
                # Assuming GCC is installed in standard location
                args.append('-I%{prefix}/gcc/lib/gcc/x86_64-apple-darwin*/*/include')

    return ' '.join(args)


def nv_hpc_compiler_path(flavor: Dict) -> str:
    sdk = str(flavor.get('nvidia').get('hpc'))
    return "/opt/nvidia/hpc_sdk/Linux_x86_64/{:s}/compilers".format(sdk)

def get_cuda_path(flavor: Dict) -> str:
    sdk = str(flavor.get('nvidia').get('hpc'))
    gds = str(flavor.get('nvidia').get('gds'))
    return "/opt/nvidia/hpc_sdk/Linux_x86_64/{:s}/math_libs/{:s}/targets/x86_64-linux".format(sdk, gds)

def get_nv_gpu_targets(flavor: Dict) -> str:
    """Get NVIDIA GPU target architecture from flavor configuration"""
    return flavor.get('nvidia', {}).get('target', 'sm_80')