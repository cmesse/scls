#!/usr/bin/env python3
import os
import re
from typing import Dict, Optional
from pathlib import Path


# ---------------------------------------------------------------------------
# Compiler family — the single source of truth
#
# The stack's rule is: the OpenMP runtime follows the COMPILER, never the math
# library. GCC emits calls into libgomp, Intel's compilers into libiomp5, and
# MKL's threading layer must match whichever one the compiler emitted code for.
# Loading two OpenMP runtimes into one process is the failure mode this exists
# to prevent, so exactly one function decides the family and everything else
# derives from it.
#
# Before this was centralised the decision was duplicated in nine places that
# disagreed: exact-match on 'gcc', family-match on three GNU names,
# default-to-GNU, substring match on the compiler name ('icc' is a substring of
# 'mpicc'), and a flavor-name test. That inconsistency is what let the RPM
# builder's mpicc/mpicxx override silently drop -fopenmp and the MKL threading
# layer. Add new consumers here; do not re-derive a family locally.
# ---------------------------------------------------------------------------

_FAMILY_BY_NAME = {
    'gcc': 'gnu', 'g++': 'gnu', 'gfortran': 'gnu',
    'icx': 'intel', 'icpx': 'intel', 'icc': 'intel', 'icpc': 'intel',
    'ifx': 'intel', 'ifort': 'intel',
    'clang': 'llvm', 'clang++': 'llvm', 'flang': 'llvm',
}

# Compiler wrappers must never reach the resolver: they hide the underlying
# compiler, which is precisely how a wrong ABI used to be chosen silently.
_MPI_WRAPPERS = {
    'mpicc', 'mpicxx', 'mpic++', 'mpiCC', 'mpifort', 'mpif77', 'mpif90',
    'mpiicc', 'mpiicpc', 'mpiifort', 'mpiicx', 'mpiicpx', 'mpiifx',
}

# Trailing version suffix on a compiler binary: gcc-15, gfortran-14.2, clang-18
_VERSION_SUFFIX = re.compile(r'-\d+(?:\.\d+)*$')


def _normalize_compiler(name: str) -> str:
    """Reduce a compiler setting to a bare binary name.

    Handles absolute paths (the flavors' bootstrap_compilers use /usr/bin/gcc,
    and the gcc-toolset rewrite in rpm_builder produces
    /opt/rh/gcc-toolset-N/root/usr/bin/gcc) and versioned binaries (gcc-15,
    as used by the Homebrew toolchain on macOS).
    """
    base = os.path.basename(str(name).strip())
    return _VERSION_SUFFIX.sub('', base)


def _family_of(name: str, role: str) -> str:
    """Map one compiler setting to 'gnu' | 'intel' | 'llvm', or raise."""
    binary = _normalize_compiler(name)
    if binary in _MPI_WRAPPERS:
        raise ValueError(
            f"compiler_family: {role}={name!r} is an MPI wrapper. The wrapper "
            f"hides the underlying compiler, so the OpenMP runtime and MKL ABI "
            f"cannot be derived from it. Resolve the flavor's native compilers "
            f"first (rpm_builder.RPMBuilder.math_flavor() does this)."
        )
    if binary not in _FAMILY_BY_NAME:
        raise ValueError(
            f"compiler_family: {role}={name!r} is not a known compiler. Add it "
            f"to math_common._FAMILY_BY_NAME with its OpenMP runtime family "
            f"('gnu' -> libgomp, 'intel' -> libiomp5, 'llvm' -> libomp) rather "
            f"than letting it fall through to a default, which would pick an "
            f"OpenMP runtime and MKL threading layer at random."
        )
    return _FAMILY_BY_NAME[binary]


def compiler_family(flavor: Dict) -> str:
    """Return 'gnu', 'intel' or 'llvm' for the flavor's native compilers.

    Every OpenMP flag, OpenMP runtime library, MKL threading layer and MKL
    interface library in the stack derives from this one answer.

    Raises ValueError if the flavor's C, C++ and Fortran compilers do not
    belong to the same family, if any of them is an MPI wrapper, or if one is
    unrecognised. Raising is deliberate: every one of those cases previously
    produced a silently wrong link line, and spec generation is cheap enough
    that a misconfigured flavor should fail there rather than at runtime on a
    user's machine.
    """
    compilers = flavor.get('compilers', {}) or {}
    seen = {}
    for role in ('cc', 'cxx', 'fc'):
        if compilers.get(role):
            seen[role] = _family_of(compilers[role], role)
    if not seen:
        raise ValueError(
            "compiler_family: flavor defines no cc/cxx/fc compilers; cannot "
            "determine the OpenMP runtime or MKL ABI."
        )
    families = set(seen.values())
    if len(families) > 1:
        detail = ', '.join(f'{r}={compilers[r]} -> {f}' for r, f in seen.items())
        raise ValueError(
            f"compiler_family: flavor mixes compiler families ({detail}). One "
            f"process cannot host two OpenMP runtimes, and MKL's interface "
            f"library encodes a single Fortran ABI."
        )
    return families.pop()


def openmp_flag(flavor: Dict) -> str:
    """Compile flag that enables OpenMP for this flavor's compilers."""
    return '-qopenmp' if compiler_family(flavor) == 'intel' else '-fopenmp'


def openmp_runtime_lib(flavor: Dict) -> str:
    """Link flag for the OpenMP runtime this flavor's compilers emit against."""
    family = compiler_family(flavor)
    if family == 'intel':
        return '-liomp5'
    if family == 'llvm':
        # macOS builds link GCC's runtime (see doc/MACOS_BUILD.md); Linux
        # clang uses LLVM's own. Currently unreachable — every SCLS flavor is
        # gnu or intel — but preserved rather than silently changed.
        return '-lgomp' if flavor.get('platform') == 'macos' else '-lomp'
    return '-lgomp'


def mkl_threading_lib(flavor: Dict) -> str:
    """MKL threading layer matching this flavor's OpenMP runtime."""
    family = compiler_family(flavor)
    if family == 'intel':
        return 'mkl_intel_thread'
    if family == 'llvm':
        raise ValueError(
            "mkl_threading_lib: MKL with an LLVM toolchain is not defined for "
            "this stack. MKL ships GNU and Intel threading layers only; "
            "pairing either with libomp mixes OpenMP runtimes. Choose a gnu or "
            "intel flavor, or add an explicit policy here."
        )
    return 'mkl_gnu_thread'


def mkl_threading_mode(flavor: Dict, recipe: Optional[Dict] = None) -> str:
    """'threaded' or 'sequential' — whether MKL uses a threading layer.

    This is what the flavor's `math.threading:` field means. It does NOT choose
    *which* OpenMP runtime is used; that follows the compiler. The field is
    also cross-checked against the compiler family, so a flavor that claims
    `threading: intel` while compiling with GCC fails here instead of shipping
    a mixed runtime.
    """
    declared = str((flavor.get('math', {}) or {}).get('threading', 'openmp'))
    if declared not in ('openmp', 'intel', 'sequential'):
        raise ValueError(
            f"mkl_threading_mode: unknown math.threading: {declared!r}. Valid "
            f"values are 'openmp' (GNU/LLVM toolchains), 'intel' (Intel "
            f"toolchain) and 'sequential' (no MKL threading layer)."
        )
    family = compiler_family(flavor)
    if declared == 'sequential':
        if recipe and (recipe.get('features', {}) or {}).get('openmp'):
            raise ValueError(
                "mkl_threading_mode: flavor declares math.threading: sequential "
                "but the recipe sets features.openmp: true. Sequential MKL and "
                "an OpenMP-threaded consumer is a contradiction — pick one."
            )
        return 'sequential'
    if declared == 'intel' and family != 'intel':
        raise ValueError(
            f"mkl_threading_mode: flavor declares math.threading: intel but "
            f"compiles with the {family} toolchain. The MKL threading layer "
            f"must match the compiler's OpenMP runtime."
        )
    if declared == 'openmp' and family == 'intel':
        raise ValueError(
            "mkl_threading_mode: flavor declares math.threading: openmp but "
            "compiles with the intel toolchain; say `intel` so the intent and "
            "the compiler agree."
        )
    return 'threaded'


def get_mkl_interface_lib(flavor: Dict) -> str:
    """Return the MKL Fortran interface library name (without -l prefix).

    The interface library encodes the Fortran calling convention. MKL ships
    two variants matching the two common Fortran ABIs:
      - 'mkl_gf_{lp64,ilp64}'    — gfortran (GCC) name mangling
      - 'mkl_intel_{lp64,ilp64}' — Intel ifort/ifx name mangling
    Mixing them within a single flavor is incorrect and produces either
    link-time unresolved symbols or subtle runtime corruption. Derived from
    compiler_family, which asserts that cc/cxx/fc agree — so this stays a
    Fortran-ABI decision even though it is expressed once for the flavor.
    """
    interface = flavor.get('math', {}).get('interface', 'lp64')
    family = compiler_family(flavor)
    if family == 'llvm':
        raise ValueError(
            "get_mkl_interface_lib: MKL with an LLVM toolchain is not defined "
            "for this stack — see mkl_threading_lib for the reasoning. Keeping "
            "the policy to a single sentence means this raises too rather than "
            "quietly picking the gfortran ABI."
        )
    return f"mkl_{'intel' if family == 'intel' else 'gf'}_{interface}"


def get_mkl_serial_link_line(flavor: Dict) -> str:
    """Canonical MKL serial (non-ScaLAPACK) link line for the given flavor.

    Used by %{mkl_linker_flags} expansion and anywhere else a package
    needs the raw MKL BLAS+LAPACK link line without ScaLAPACK/BLACS.
    """
    iface = get_mkl_interface_lib(flavor)
    if mkl_threading_mode(flavor) == 'sequential':
        return f'-l{iface} -lmkl_sequential -lmkl_core -lpthread -lm -ldl'
    return (f'-l{iface} -l{mkl_threading_lib(flavor)} -lmkl_core '
            f'{openmp_runtime_lib(flavor)} -lpthread -lm -ldl')


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
    linalg = math_config.get('linalg', 'reference')
    interface = math_config.get('interface', 'lp64')

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

        # Interface library (Fortran ABI — see math_common.compiler_family)
        args.append(f'-l{get_mkl_interface_lib(flavor)}')

        # Threading layer and OpenMP runtime both follow the compiler family.
        threaded = use_omp and mkl_threading_mode(flavor, recipe) == 'threaded'

        if threaded:
            args.append(f'-l{mkl_threading_lib(flavor)}')
        else:
            args.append('-lmkl_sequential')

        # Core library
        args.append('-lmkl_core')

        if threaded:
            args.append(openmp_runtime_lib(flavor))

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

        # OpenMP runtime — follows the compiler family. On macOS this
        # resolves to libgomp for both gnu and llvm toolchains (the llvm case
        # links GCC's runtime; see openmp_runtime_lib).
        if use_omp:
            args.append(openmp_runtime_lib(flavor))

        # System libraries
        args.append('-lpthread -lm')

    elif linalg == 'openblas':
        # OpenBLAS provides BLAS+LAPACK via compat symlinks
        args.append('-Wl,-rpath,%{prefix}/lib -L%{prefix}/lib')

        if needs_scalapack:
            args.append('-lscalapack')

        args.append('-lopenblas')

        # OpenMP runtime — follows the compiler family
        if use_omp:
            args.append(openmp_runtime_lib(flavor))

        # System libraries
        args.append('-lpthread -lm -ldl')

    elif linalg in ['reference', 'lapack', None]:  # Handle all reference implementations
        # ScaLAPACK if parallel
        if needs_scalapack:
            args.append('-lscalapack')

        # LAPACK and BLAS
        args.append('-llapack -lblas')

        # OpenMP runtime — follows the compiler family
        if use_omp:
            args.append(openmp_runtime_lib(flavor))

        # System libraries
        args.append('-lpthread -lm -ldl')

    return ' '.join(args)


def get_math_compile_flags(flavor: Dict, recipe: Dict) -> str:
    """Generate math-related compile flags based on flavor and recipe settings"""
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

    # OpenMP flag — follows the compiler family
    if use_omp:
        args.append(openmp_flag(flavor))
        if compiler_family(flavor) == 'llvm' and flavor.get('platform') == 'macos':
            # clang needs GCC's omp.h on macOS (see doc/MACOS_BUILD.md)
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