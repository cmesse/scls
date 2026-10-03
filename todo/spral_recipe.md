# Plan — `spral` recipe and Ipopt `--with-spral`

**Status (2026-10-03):** D1(a), D2, D3 approved by Christian 2026-10-02. Recipe, meson builder
support and Ipopt change implemented (uncommitted, branch `ipopt`). Round-1 implementation review
done (`tmp/ai_exchange/review_spral_meson.md`); all fixes approved and applied 2026-10-03 (see
the devlog `devlog/dl20261003_spral_recipe.md`). Next: first real build on an EL9 host, `files/spral.txt`,
round-2 audits.
**Branch:** `ipopt`. **Date:** 2026-10-02. Related: `todo/libhsl_build_script.md` (HSL is a
separate, private track; SPRAL is public).

## 1. Why

SPRAL's SSIDS is an open, parallel sparse symmetric-indefinite solver in the HSL MA97/MA86 family,
from the same STFC group. It gives every user an MA97-class alternative to MUMPS in Ipopt, using
only public packages. HSL stays the licensee-only extra.

## 2. Decisions

- [x] Meson and Ninja are acceptable as **build-time-only** host tools (Christian, 2026-10-01).
  This is consistent with CLAUDE.md "No Python / language bindings": build-time use of system Python
  is fine, and SCLS's own builders already need it. Neither tool is shipped or required at install time.
- [ ] **D1 — how SCLS drives meson.** `configure.type: custom` always appends `make` after the
  configure command (`templates/default.spec.j2:181-197`), so meson cannot use it as is.
  - (a) **Recommended:** a first-class `configure.type: meson` in `rpm_builder`, `unix_builder` (deb inherits) and the spec template. It mirrors the cmake path:
    - `meson setup build --prefix=%{prefix} <args>`
    - `meson compile -C build`
    - `meson test -C build` (if tests are on)
    - `DESTDIR=%{buildroot} meson install -C build`

    This is a builder change, needs approval, and is reusable for future meson-built packages.
  - (b) Hack: `configure.command` runs meson + ninja and writes a stub `Makefile` so the trailing `make` is a no-op. No builder change, but opaque and fragile.
- [ ] **D2 — ship Ipopt 3.14.20-1 with SPRAL from the start.** Ipopt has not been released yet,
  so adding `spral` now avoids a second release. Recommendation: yes.
- [ ] **D3 — hwloc.** Optional in SPRAL (`meson.build:84,99-101`). The stack ships hwloc
  (`recipes/hwloc.yaml`). Recommendation: link it, so SSIDS can see the machine topology. Cost: it
  becomes a hard runtime dependency of `libspral`.

## 3. Upstream facts (SPRAL master = `v2025.09.18`, read 2026-10-01)

- **Licence:** BSD-3 (`LICENCE`; GitHub labels it "Other"). Allowed under `doc/LICENSE_POLICY.md`.
- **Releases:** date-versioned GitHub releases (`v2025.09.18`, `v2025.05.20`, …).
- **Build:** meson ≥ 0.63.0 only (`meson.build:6`); there is no autotools or CMake build. C, C++11 and Fortran.
- **Options** (`meson_options.txt`):
  - `gpu` (default true), `tests` (true), `binaries` (true), `examples` (false), `modules` (true), `openmp` (true)
  - `libblas` / `liblapack` / `libmetis` / `libhwloc` (names) with `*_path`
  - `libmetis_version` (`'5'`), `metis64` (false)
- **BLAS/LAPACK lookup:** `dependency(name)` first, which is pkg-config, then `fc.find_library(name)` (`meson.build:72-81`). METIS and hwloc are looked up with `find_library` only (`:83-84`).
- **OpenMP:** `-fopenmp` per language, and it hard-adds `-lgomp` to every link (`:150-167`). For Intel compilers it uses `-liomp5`.
- **Installs:**
  - `libspral` (shared)
  - headers (`install_headers`, `:213`)
  - Fortran modules (if `modules`)
  - the `spral_ssids` binary (if `binaries`, `:205-209`)
- **Ipopt 3.14.20 side:**
  - `--with-spral` checks for `spral_ssids.h` and links `spral_ssids_solve` (`configure.ac:230-243`). That is only done for double precision with 32-bit integers, which holds for all SCLS flavors.
  - Ipopt calls `spral_ssids_analyse_ptr32` and `spral_ssids_factor_ptr32` (`IpSpralSolverInterface.cpp:481,572`), both present in SPRAL's `include/spral_ssids.h:81,95`.
  - The default solver stays `mumps`, because MUMPS and MKL Pardiso outrank SPRAL (`IpAlgBuilder.cpp:232-242`). Users opt in with `linear_solver spral`.
- **Runtime requirement:** `OMP_CANCELLATION=TRUE` and `OMP_PROC_BIND=TRUE` must be set before the program starts (SPRAL `README.md:48-49`). Ipopt only warns when they are missing (`IpSpralSolverInterface.cpp:594`).

## 4. Recipe sketch — `recipes/spral.yaml` (needs approval)

- `version: 2025.09.18`. Source: the GitHub tag `v%{version}`. `update: {strategy: github_release, repo: ralna/spral, tag_prefix: "v"}`.
- `license: BSD-3-Clause`.
- `requires: [metis, hwloc]`; math comes from the flavor (`features.math`). `features: {fortran: true, openmp: true, mpi: false}`.
- `rpm_build_requires: [meson, ninja-build]`, plus `packaging/system_packages.yaml` entries for .deb hosts (`meson`, `ninja-build`). On macOS, document the Homebrew requirement.
- Meson args:
  - `-Dgpu=false`: no CUDA in the stack. Explicit, so a host with nvcc cannot change what ships.
  - `-Dtests=true`, `-Dbinaries=false` (no user-facing executable needed), `-Dexamples=false`, `-Dmodules=true`
  - `-Dlibmetis=metis -Dlibmetis_path=%{prefix}/lib -Dlibmetis_version=5`, plus `-Dc_args/-Dfortran_args=-I%{prefix}/include`. One METIS: the stack's.
  - `-Dlibhwloc=hwloc -Dlibhwloc_path=%{prefix}/lib -Dlibhwloc_include=%{prefix}/include` (if D3 is yes)
- **BLAS/LAPACK — open item O1:**
  - OpenBLAS flavors: `-Dlibblas=openblas -Dliblapack=openblas -Dlibblas_path=%{prefix}/lib`.
  - Reference flavor (debug): `blas` / `lapack` from the stack.
  - MKL flavors: try MKL's pkg-config module for the flavor's threading layer through `dependency()`. It must match `%{math_ldflags}`, never `mkl-dynamic-*-rt`. Verify with `scripts/check_mkl_linkage.sh`. Fallback: `find_library(mkl_core)` plus the full `%{math_ldflags}` in `-Dfortran_link_args`.
- **Intel flavor:** SPRAL links `-liomp5` itself. Check that this matches the flavor's OpenMP runtime.
- `test: meson test -C build`, with `OMP_CANCELLATION=TRUE OMP_PROC_BIND=TRUE` set for the test run only.
- `registry: {cflags: "-I%{prefix}/include", ldflags: "-L%{prefix}/lib -lspral"}`.
- `files/spral.txt` from the first real build; `changelogs/spral.md`.

## 5. Ipopt change (needs approval)

- [ ] `recipes/ipopt.yaml`:
  - `requires` gains `spral`.
  - Configure arg `--with-spral-cflags=-I%{prefix}/include`, and `--with-spral-lflags=-L%{prefix}/lib -lspral` plus the libraries SPRAL needs when linked (metis, hwloc, math line, `-lgomp`/`-lstdc++` as required). To confirm against Ipopt's `AC_COIN_CHK_LIBHDR` link test.
  - A comment explaining why, per CLAUDE.md.
- [ ] Changelog `ipopt.md` 3.14.20-1: replace "Built without … SPRAL" with the SPRAL entry and the `OMP_*` note.
- [ ] Build order (verified for `gcc` 2026-10-02):
  - `spral` lands in group 5, after metis (group 4) and hwloc (group 3).
  - `ipopt` stays in group 8, since it already waits for mumps.
  - No new reverse dependencies: nothing depends on Ipopt.

## 6. Runtime environment

- [ ] Do **not** set `OMP_PROC_BIND` stack-wide in the `environment` package. It pins threads for every OpenMP program, and that can badly hurt multi-rank-per-node MPI jobs.
- [ ] Document both variables: the Ipopt changelog, a recipe comment, and the website's Ipopt entry. Suggest exporting them only in the job script that uses `linear_solver spral`.

## 7. Verification

- [ ] Meson availability per build host: EL8, EL9 (CRB/EPEL?), U24, U26, macOS. Each must provide ≥ 0.63. Record what each host provides. If one is too old, decide between a host-local `pip install --user meson` (build tool only) and skipping that host.
- [ ] Spec-diff gate for the builder change (D1a): `--spec-only` for every recipe × flavor before and after. Only `spral` (new) and `ipopt` may differ.
- [ ] `meson test` passes on `gcc`, `mkl` and `debug`.
- [ ] `ldd libspral.so` shows the stack's metis and hwloc and the flavor's math libraries. `check_mkl_linkage.sh` passes on the MKL flavors.
- [ ] Ipopt `hs071` with `linear_solver spral`, with the `OMP_*` variables set, converges to the same optimum as `mumps`. Without them, we see the documented warning, not a wrong answer.
- [ ] `ldd libipopt.so` contains `libspral` and still exactly one `libmetis`.

## 8. Review gate

- [ ] Christian decides D1–D3.
- [ ] Two blind audits of this plan (`/cross-review`). Focus:
  - D1a builder design
  - the O1 MKL route
  - Ipopt's `--with-spral-lflags` completeness
  - the `-lgomp` hard-link on Intel and MKL flavors
- [ ] Implement in order: builder (D1a), `spral` recipe, Ipopt change.
- [ ] Two blind audits of the implementation, then adjust.
- [ ] Commit messages name each option and why (CLAUDE.md).

## Follow-ups found in review (2026-10-03, pre-existing, not part of the SPRAL commit)

- [ ] unix/deb ignore `configure.flavor_pre` / `configure.flavor_post` for every configure type
  (rpm_builder handles them). Live case: openmpi's gcc-mkl-cuda CUDA-support check never runs on
  .deb hosts.
- [ ] `build_common.setup_environment` sets the MKL environment only when the flavor *name*
  contains "mkl" (`build_common.py:1044`); intel (math.linalg: mkl) gets none on unix/deb. The RPM
  `mkl_root` was switched to math.linalg in this change; mirror that decision here.
- [ ] intel RPM: the spec bakes the MKL path at generation time, while %build sources setvars.sh.
  Confirm they agree on an intel build host (`readelf -d`, `check_mkl_linkage.sh`).
- [ ] `OMP_PROC_BIND`: multi-core hs071/SSIDS run with `OMP_CANCELLATION` only, then Christian
  decides whether activate should also set it.
- [ ] macOS: spral build, then `otool -l libspral.dylib` to confirm the header pad.
