# Ipopt Changelog

## Version 3.14.20-1 - Sat Sep 26 2026
- 2026-10-04, release kept: RPM builds on MKL flavors add the MKL directories to
  `LDFLAGS` (`configure.flavor_pre`), so `libsipopt.so` gets them in its RUNPATH.
  It NEEDs `libmkl_*` but was linked through `libipopt.la`, which drops
  `-Wl,-rpath`, and carried the prefix only (found on R9 mkl). Other flavors and
  the unix/deb builders are unchanged. The release stays 3.14.20-1 by Christian's
  manual override (2026-10-04: "we do not bump ipopt, this is a manual override";
  "nobody knows that the U26 repo exists. The vast majority of the community uses
  EL. The risk that one user downloaded U24 in the meantime is extremely low").
  el9 mkl had not been published. This entry does not change the unix/deb build
  commands; the Ubuntu packages are rebuilt at the same version as a precaution
  and the published mkl one is replaced (Christian, 2026-10-04: "We can rebuild
  ipopt on deb, better safe than sorry. No version bump").
- Initial SCLS package for Ipopt 3.14.20 (EPL-2.0).
- Linear solvers: the stack's MPI MUMPS on every flavor; MKL Pardiso is
  enabled automatically on the MKL flavors because `--with-lapack-lflags`
  carries `libmkl_core`, where configure finds the `pardiso` symbol.
- SPRAL (SSIDS) is linked on every flavor (`--with-spral`); select it with
  `linear_solver spral`. The default solver stays `mumps`. SPRAL needs
  `OMP_CANCELLATION=TRUE`, which the stack's `activate` sets when SPRAL is
  installed (environment 2026-3); without it the solve fails. SPRAL also
  recommends `OMP_PROC_BIND=TRUE` for performance; set that per job.
- `%check` also solves hs071 with `linear_solver spral` and fails the
  build unless Ipopt reports SPRAL and an optimal solution.
- Built without ASL (no `ipopt` executable), HSL and Java; the runtime
  dlopen loader stays on so users may supply `libhsl` / `libpardiso`
  themselves. sIpopt is built.
- `libipopt` links `libmpi` and initialises MPI as a singleton when loaded
  (upstream default `--enable-mpiinit`), because the MUMPS it links is the
  MPI build.
