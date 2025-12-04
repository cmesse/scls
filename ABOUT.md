# The Scientific Core Libraries Stack

The Scientific Core Libraries Stack (SCLS) is a curated collection of open-source numerical libraries for high-performance computing. The primary target is x86_64 systems running Enterprise Linux (RHEL, Rocky, Alma), with development support for macOS.

## What We Provide

SCLS delivers production-ready builds of the scientific computing ecosystem: sparse solvers (PETSc, MUMPS, STRUMPACK, SuperLU), dense linear algebra (OpenBLAS, ScaLAPACK), graph partitioners (METIS, ParMETIS, SCOTCH), I/O libraries (HDF5, NetCDF), and their dependencies—all built to work together.

## Philosophy: Curated Over Configurable

Unlike general-purpose build frameworks that offer unlimited flexibility, SCLS is deliberately opinionated. We make choices so you don't have to:

**Compiler**: GCC is the default. It's open source, has excellent Fortran support for legacy numerical codes, and produces reliable, performant binaries. Intel compilers are available as an alternative flavor for those with licenses.

**Math Libraries**: Intel MKL is the recommended backend for production use on Intel hardware—it's heavily optimized and freely available. OpenBLAS provides a fully open-source alternative with good performance.

**Integer Interface**: LP64 (32-bit integers) is the default. This is what most scientific codes expect, what most libraries are tested with, and sufficient for problems up to ~2 billion unknowns. ILP64 (64-bit integers) is available for truly massive problems, but comes with compatibility trade-offs.

**MPI**: OpenMPI is the default implementation. It's well-maintained, widely deployed, and works reliably across different network fabrics.

**Numerical Integrity**: We never use `-ffast-math`. Floating-point reproducibility and IEEE compliance matter in scientific computing. We use `-O2` or `-O3` with careful flag selection.

**Shared Libraries**: We build shared libraries by default. This reduces disk footprint, allows security updates without rebuilding dependents, and matches how modern systems work.

## Why This Matters

HPC administrators know the pain: a researcher's custom environment breaks after an update, or two packages require incompatible library versions, or a build that worked on one node fails on another. SCLS eliminates this friction by providing a coherent, reproducible stack.

We trade flexibility for reliability. If you need HDF5 built with seventeen custom options, use Spack. If you want HDF5 that works correctly with PETSc, NetCDF, and the rest of your scientific software, use SCLS.

## Target Audience

- HPC centers deploying numerical software for researchers
- Scientific computing teams who need reliable builds
- Anyone who values "it just works" over "configure it yourself"
