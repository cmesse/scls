# Devlog 2026-08-17 — STRUMPACK OpenMP tasking lost on the mkl flavor

**Date:** 2026-08-17
**Topic:** Why the shipped `scls-mkl-strumpack` has both OpenMP tasking features compiled out, and what else the same mechanism reaches
**AIs involved:** Claude, Codex, Grok (`/cross-review --jury`)
**Claude Confidence:** high on the root cause and the mkl-only scope; medium-high (~80%) that the mechanism reproduces identically on Linux
**Auditor Confidence:** Codex high, Grok high on builder facts / medium (~65%) on the probe root cause
**Flavor / Host:** mkl (also gcc, debug, intel, lbl, gcc-mkl-cuda) on the macOS dev host — no `rpmbuild`
**Upstream References:** upstream STRUMPACK 8.0.0 `CMakeLists.txt:113-126` (the two probes), `:606-610` (OpenMP target), `:214`/`:246` (BLAS probe, FATAL_ERROR-gated), `src/StrumpackConfig.h.in:34,74-75`, `cmake/taskloop.cpp`, `cmake/taskdepend.cpp`
**Verification:** generation gate (`rpm_builder.py --spec-only` across all recipes x 6 Linux flavors, old vs new) plus local cmake 4.3.2 experiments reproducing the probe failure, plus inspection of the published RPM payloads from belfem.lbl.gov. No `rpmbuild`, no install test, no scaling measurement — those are **pending a Linux build host**.

## Summary

A BELFEM-side handoff reported that `/opt/scls/mkl` ships a STRUMPACK 8.0.0 with
`STRUMPACK_USE_OPENMP_TASKLOOP` and `STRUMPACK_USE_OPENMP_TASK_DEPEND` compiled out,
and hypothesised that the RPM build environment could not compile OpenMP at all.

The report is correct; the hypothesis is not. `find_package(OpenMP)` succeeded — the
shipped library is OpenMP-parallel. What failed is upstream's two `try_compile`
probes, and the reason is a **stack-level defect in SCLS's own cmake arguments**:
`-lgomp` inside `CMAKE_<LANG>_STANDARD_LIBRARIES` causes any `try_compile` that links
an OpenMP imported target to link with **no OpenMP runtime at all** and fail.

STRUMPACK is simply the package where the silently-lost feature was measurable.

## Key Findings

- **Confirmed and scoped from the published artifacts.** `scls-mkl-strumpack-8.0.0-1`
  has both macros `#undef` on el9, el10 and amzn2023; `scls-gcc-` and `scls-debug-`
  have both `#define`. The complete `StrumpackConfig.h` diff between the gcc and mkl
  payloads is exactly those two lines. macOS `/opt/scls` is fine. Deterministic,
  mkl-only.
- **`find_package(OpenMP)` succeeded.** Shipped mkl
  `lib/cmake/STRUMPACK/strumpack-targets.cmake:65` lists `OpenMP::OpenMP_CXX`, which
  upstream only sets under `if(OpenMP_FOUND)`; the shipped `libstrumpack.so.8.0.0`
  references `GOMP_parallel` / `GOMP_task` and has `libgomp.so.1` NEEDED.
  `#define STRUMPACK_USE_OPENMP` comes from the CMake *option*, not from detection,
  so it never proved OpenMP was found.
- **Root cause — `-lgomp` in `CMAKE_<LANG>_STANDARD_LIBRARIES` poisons `try_compile`.**
  Bisected locally with `/opt/scls/bin/cmake` 4.3.2 against upstream's own
  `cmake/taskloop.cpp`:

  | `CMAKE_CXX_STANDARD_LIBRARIES` | probe | probe link line |
  |---|---|---|
  | unset / `-lm` / `-lm -ldl` / `-lthis_lib_does_not_exist` | TRUE | ends with `libgomp` |
  | `-lmkl_gf_lp64 -lmkl_core -lpthread -lm -ldl` (no `-lgomp`) | TRUE | ends with `libgomp` |
  | `-lgomp` / `-lm -lgomp` / the full MKL line | **FALSE** | no `-fopenmp`, no OpenMP runtime |

  The value is *not* forwarded into the try_compile, but its presence drops the
  OpenMP target's runtime from the probe link, so the probe dies on undefined
  `GOMP_parallel` / `GOMP_taskloop`. The outer library link is unaffected, which is
  exactly why the shipped library is OpenMP-parallel while the probes said no.
- **This predicts the field evidence.** gcc/debug emit
  `-DCMAKE_CXX_STANDARD_LIBRARIES=-lm` → probes pass. mkl/intel emit the MKL line
  containing `-lgomp` (`python/build_common.py:785-819` via
  `python/math_common.py:38`) → probes fail.
- **Exposure beyond STRUMPACK.** Any mkl/intel cmake package whose configure runs a
  `try_compile` against an OpenMP imported target. cmake+openmp recipes built by
  default: butterflypack, gklib, metis, parmetis, slate, strumpack, sundials,
  superlu_dist, vtk, zfp. Spot-checked clean: `sundials_config.h` and
  `superlu_dist_config.h` are byte-identical between the published gcc and mkl RPMs.
  The rest are unchecked.
- **Separate RPM-builder defect (`python/rpm_builder.py`).** The MPI override
  replaces `flavor['compilers']` with `mpicc`/`mpicxx`/`mpifort` before `math_common`
  sees it, and `math_common` branches on the compiler family name
  (`math_common.py:18,32-40,64,102-118,195,213-219`). Consequences: `-fopenmp`
  silently dropped from CFLAGS/CXXFLAGS/FFLAGS/FCFLAGS for every mpi+openmp+math
  recipe; on mkl, `%{math_ldflags}` emitted MKL with **no threading layer at all**;
  on intel, MPI recipes took the gfortran MKL ABI. `unix_builder.py:212-216` does not
  mutate the flavor dict, so macOS was always correct — an RPM-path-only divergence.
  This does **not** explain the STRUMPACK probes (it is flavor-independent).

## Changes Made / Proposed

Made (before the collaboration protocol landed this session, i.e. without the §7
approval step — which is why they went through a full `/cross-review` round):

- `python/rpm_builder.py` — added `RPMBuilder.math_flavor()` and routed five
  `math_common` call sites through the native (non-MPI-wrapper) compilers.
- `recipes/strumpack.yaml` — `release: 2`; pinned
  `-DSTRUMPACK_USE_OPENMP_TASKLOOP=TRUE` / `-DSTRUMPACK_USE_OPENMP_TASK_DEPEND=TRUE`.
- `changelogs/strumpack.md` — 8.0.0-2 entry.

Proposed, **not applied** (awaiting Christian's approval):

1. **P0 regression, intel flavor.** `get_cmake_args_with_paths` still passes the
   MPI-mutated `self.flavor` into `get_cmake_args` (`rpm_builder.py:1457-1459`), so
   `CMAKE_CXX_STANDARD_LIBRARIES` keeps the gfortran MKL ABI while
   `TPL_BLAS_LIBRARIES` now takes the Intel ABI — a mixed ABI on one cmake line that
   my own patch introduced. Fix: pass `self.math_flavor()`.
2. **P0 root cause.** Remove the OpenMP runtime (`-lgomp` / `-liomp5`) from
   `CMAKE_<LANG>_STANDARD_LIBRARIES` in `build_common.get_cmake_args`. Stack-wide MKL
   link-line change, touches `doc/MKL_ABI_POLICY.md` territory — Christian's call,
   not settleable by AI vote.
3. **P2.** Correct two over-claims in the `recipes/strumpack.yaml` comment: "fails
   loudly at compile time" (an unsupported pragma is a warning absent
   `-Werror=unknown-pragmas`) and "GCC >= 11" (RHEL 8 hosts run gcc 8 unless
   `gcc_toolset:` is set; the real floor is GCC 6 / OpenMP 4.5).

## Cross-review outcome

Full record: `tmp/ai_exchange/review_strumpack_openmp_tasking.md` (ephemeral).

- Codex and Grok independently raised the intel mixed-ABI regression — **confirmed**.
- Grok pointed at `CMAKE_<LANG>_STANDARD_LIBRARIES` as the mkl-only differentiator.
  Its stated mechanism (the probe must resolve `-lmkl_*`) is wrong — the value is not
  forwarded — but the direction was right and led to the root cause.
- Codex claimed the recipe pin is a no-op because raw `try_compile` overwrites a
  seeded result — **refuted** by measurement: a seeded `FALSE` survives on a source
  that compiles, and a seeded `TRUE` survives on a source that is not valid C++.
  Codex read `cmCoreTryCompile.cxx` from CMake master and cited the guard belonging
  to the `check_<lang>_source_compiles` API, which upstream does not use.
- Grok also flagged the "fails loudly" and "GCC >= 11" over-claims (confirmed), the
  bundling of two unrelated changes (confirmed, process), and a latent
  bootstrap+MPI gap (confirmed but inert — no bootstrap recipe has math or openmp).

## Open Questions

- Does the `-lgomp` de-duplication reproduce identically on Linux? The logic is
  platform-independent CMake, but it was measured on macOS. **Needs a Linux host.**
- Which of the other mkl cmake packages silently lost a probe-detected feature?
- Does enabling tasking shift STRUMPACK's documented numerical-cliff ctest
  exclusions? Pending a Linux `%check`.
- The actual scaling payoff. Compare `factor time` from `hphiTrun -v`, never step
  wall-times — thread count perturbs the nonlinear convergence path.

## Files Updated

- python/rpm_builder.py
- recipes/strumpack.yaml
- changelogs/strumpack.md
- devlog/dl20260817_strumpack_openmp_tasking.md (this file)
- devlog/README.md
