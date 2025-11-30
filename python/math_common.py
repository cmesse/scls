#!/usr/bin/env python3
from typing import Dict
from pathlib import Path

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

    args = []

    if linalg == 'mkl':
        # MKL base path and rpath
        args.append('-Wl,-rpath,%{mklroot}/lib -L%{mklroot}/lib')

        # ScaLAPACK if parallel
        if parallel:
            if interface == 'lp64':
                args.append('-lmkl_scalapack_lp64')
            else:
                args.append('-lmkl_scalapack_ilp64')

        # Interface layer
        if interface == 'lp64':
            args.append('-lmkl_intel_lp64')
        else:
            args.append('-lmkl_intel_ilp64')

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

        # BLACS for parallel
        if parallel:
            if interface == 'lp64':
                args.append('-lmkl_blacs_openmpi_lp64')
            else:
                args.append('-lmkl_blacs_openmpi_ilp64')

        # OpenMP runtime
        if use_omp:
            if compiler == 'gcc' or (compiler == 'clang' and omp_threading == 'openmp'):
                args.append('-lgomp')
            elif compiler in ['icx', 'icpx', 'icc']:
                args.append('-liomp5')

        # System libraries
        args.append('-lpthread -lm -ldl')

    elif linalg == 'accelerate':
        # ScaLAPACK if parallel (must be built against Accelerate)
        if parallel:
            args.append('-lscalapack')

        # Apple Accelerate framework
        args.append('-framework Accelerate')

        # OpenMP runtime (if needed)
        if use_omp:
            # On macOS with clang, we use libgomp from GCC
            args.append('-lgomp')

        # System libraries
        args.append('-lpthread -lm')

    elif linalg in ['reference', 'lapack', None]:  # Handle all reference implementations
        # ScaLAPACK if parallel
        if parallel:
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