# SPRAL Changelog

## Version 2025.09.18-1 - Fri Oct 02 2026
- Initial SCLS package for SPRAL 2025.09.18 (BSD-3-Clause), the first
  meson-built recipe (new `configure.type: meson` in the builders).
- Built against the stack's METIS 5 and hwloc; no bundled METIS.
- The flavor's full BLAS/LAPACK line is passed as link args with
  `-Db_asneeded=false`, matching the stack's `--no-as-needed` link policy.
- The link args lead with the flavor's full `LDFLAGS`: a `-D*_link_args`
  option replaces `LDFLAGS` from the environment, so without this the MKL
  and debug flavors lose the prefix RUNPATH for metis and hwloc, and macOS
  loses `-headerpad_max_install_names`.
- CPU only (`-Dgpu=false`). Patched (`spral_gpu_off_no_cuda.patch`) so
  meson skips the nvcc and CUDA probes unless `gpu=true`; upstream links
  libcudart/libcublas whenever a build host has CUDA, even with
  `gpu=false`.
- `--buildtype=plain` (SCLS flags only) with `b_ndebug=true`, so asserts
  are off except on the debug flavor.
- The `spral_ssids` driver is removed at install (the tag has no
  `-Dbinaries` option); no Fortran modules.
- BSD notice installed as `share/licenses/spral/LICENCE`.
- lbl links the system hwloc and Requires `hwloc-libs`.
- Build host needs meson >= 0.63.0 and ninja (build time only).
- Runtime: SSIDS needs `OMP_CANCELLATION=TRUE`, or its factorisation fails.
  The stack's `activate` sets it when SPRAL is installed (environment
  2026-3). `OMP_PROC_BIND=TRUE` is recommended for performance, but it is
  not set globally because it pins every OpenMP program's threads.
