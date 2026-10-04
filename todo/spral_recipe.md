# Tracker — SPRAL recipe and Ipopt `--with-spral`

**Status (2026-10-03):** implemented, reviewed in three rounds, committed on branch `ipopt`:
`12f9816`, `1d2d97d`, `14eea2c`, `d8bc5d7`. Decisions and evidence are in
`devlog/dl20261003_spral_recipe.md`; reviews in `tmp/ai_exchange/review_spral_{meson,round2,round3}.md`.
Next: the shipping builds, starting on an EL9 VM.

Unpublished, so no release bumps until they ship (Christian, 2026-10-03):
`spral 2025.09.18-1`, `ipopt 3.14.20-1`, `environment 2026-3`.

## Decisions (Christian)

- `configure.type: meson` is a first-class builder type (2026-10-02).
- Ipopt 3.14.20-1 ships with SPRAL linked; the default solver stays `mumps` (2026-10-02).
- SPRAL links the stack's hwloc (lbl: the system hwloc, `Requires: hwloc-libs`) (2026-10-02).
- CUDA is patched out unless `-Dgpu=true`; `spral_ssids` is not shipped (2026-10-03).
- meson and ninja come from pip on every host, unpinned, not BuildRequires; no Homebrew (2026-10-03).
- OpenMP: activate sets `OMP_CANCELLATION=TRUE` when spral is installed and never `OMP_PROC_BIND`.
  Ipopt's `%check` tests that environment; SPRAL's unit tests keep upstream's (2026-10-03).

## Shipping builds

Host prep, once per host: `python3 -m pip install --user meson ninja` (the Python `flavor.conf`
selects), with the pip user bin directory on `PATH`. Per flavor, in order: `environment`, `spral`,
`ipopt` (`./scls build` / `./scls install`).

Checks per flavor:
- the spral build log says `Library hwloc found: YES` (upstream's hwloc probe is optional)
- `meson test` 9/9
- `readelf -d libspral.so`: prefix RPATH, metis/hwloc/math NEEDED, no CUDA
- Ipopt `%check` passes, including the hs071 run with `linear_solver spral`
- MKL flavors: configure reports MKL Pardiso, and
  `scripts/check_mkl_linkage.sh --flavor <f> --prefix /opt/scls/<f>` passes

| Host / flavor | environment | spral | ipopt |
|---|---|---|---|
| EL9 VM gcc | [x] | [x] | [x] |
| EL9 VM mkl | [x] | [x] | [x] |
| EL9 VM debug | [x] | [x] | [x] |
| EL10 VM (R10) debug, gcc, mkl | [x] | [x] | [x] |
| AMZN 2023 VM gcc, mkl | [x] | [x] | [x] |
| lbl (LBL hosts) | [ ] | [ ] | [ ] |
| U24 / U26 .deb (debug, gcc, mkl) | [ ] | [ ] | [ ] |
| macOS | [ ] | [ ] | [ ] |
| intel (source build) | [ ] | [ ] | [ ] |

The EL9 dev host has scratch builds only (pip meson with `rpmbuild --nodeps` for spral gcc/mkl;
ipopt gcc/mkl). They are evidence, not for staging.

## Open verification

- [ ] **Multi-core run.** On a host with `nproc` > 1, run hs071 (or a larger KKT system) with
  `linear_solver spral`, `OMP_CANCELLATION=TRUE`, no `OMP_PROC_BIND`, `OMP_NUM_THREADS` > 1. It
  should solve with SSIDS warning 50 only. Activate deliberately does not set `OMP_PROC_BIND`:
  with Open MPI binding policy `none`, every rank would pin its first thread to the same core.
- [ ] **macOS:** `otool -l libspral.dylib` shows the header pad from `-headerpad_max_install_names`.
- [ ] **intel:** the MKL path baked into the spec at generation time agrees with what `setvars.sh`
  sets in `%build` (`readelf -d`, `check_mkl_linkage.sh`).
- [ ] **EL8:** current meson needs Python >= 3.7; select it through `flavor.conf` `python:`.
- [ ] **This dev host:** reinstall the current `scls-mkl-scalapack` (2.2.3-4) and
  `scls-mkl-armadillo` (15.6.0-2); the stale ones fail `check_mkl_linkage.sh`.

## Follow-ups (pre-existing, separate changes; each needs approval)

- [ ] unix/deb ignore `configure.flavor_pre` / `configure.flavor_post` for every configure type.
  rpm_builder runs them. Live case: openmpi's gcc-mkl-cuda CUDA-support check never runs on .deb
  hosts.
- [ ] `build_common.setup_environment` sets the MKL environment only when the flavor *name*
  contains "mkl" (`build_common.py:1044`), so intel gets none on unix/deb. Mirror the RPM
  `mkl_root` change (math.linalg).
- [ ] `rpm_builder.py:1740` replaces `%{mklroot}` without a `None` guard. This is latent: every
  flavor that uses the token now sets `mkl_root`.
- [ ] deactivate removes `OMP_CANCELLATION` even if the user changed it after activating. P2,
  accepted for now.
