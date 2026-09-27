# Ipopt Changelog

## Version 3.14.20-1 - Sat Sep 26 2026
- Initial SCLS package for Ipopt 3.14.20 (EPL-2.0).
- Linear solvers: the stack's MPI MUMPS on every flavor; MKL Pardiso is
  enabled automatically on the MKL flavors because `--with-lapack-lflags`
  carries `libmkl_core`, where configure finds the `pardiso` symbol.
- Built without ASL (no `ipopt` executable), HSL, SPRAL and Java; the
  runtime dlopen loader stays on so users may supply `libhsl` /
  `libpardiso` themselves. sIpopt is built.
- `libipopt` links `libmpi` and initialises MPI as a singleton when loaded
  (upstream default `--enable-mpiinit`), because the MUMPS it links is the
  MPI build.
