# Open issues — 2026-10-04

**Written:** 2026-10-04 on the macOS dev host, branch `ipopt` at `8802c45`, before merging `ipopt`
into `main`.
**Replaces:** `open_issues_20260927.md`, `r9_round2_20261003.md`, `round2_el10_amzn2023.md`,
`spral_recipe.md`, `asc2026_final_upgrade.md`, `apple_silicon_report_fixes.md` and the completed
plan files (all removed in the same commit; they stay in git history). Each item below was
re-checked against the tree on 2026-10-04 unless it says otherwise. Closed items were dropped,
not carried; their records are in the devlogs named in §8.

Still separate, because they carry their own analysis:
- `todo/scotch_metis_prefix.md` — the `-DBUILD_LIBSCOTCHMETIS` question
- `todo/extra_packages_unix_deb_override.md` — bugs B1 and B2
- `todo/libhsl_source_selection.md` — HSL policy §9, cited by `scripts/build_libhsl.py` and
  `scripts/hsl/assemble_sources.sh`
- `todo/rebuild_campaign_20260922.md` — closed campaign, kept as the layout reference for
  `/update-plan` and because 16 changelogs and `/stage-drop` cite it

Tick items here as they close. Record findings in the devlog or changelog, not only here.

---

## 1. Release — round 2 is built everywhere and staged nowhere

Round 2 is built and installed on R9, R10 (debug/gcc/mkl), AMZN (gcc/mkl), U24 and U26
(debug/gcc/mkl). No drop has been staged or uploaded from any host.

- [ ] **Stage and upload round 2** with `/stage-drop`, one flavor at a time (debug → gcc → mkl),
      one drop in flight, each after belfem promotes the previous one. Upload only after the belfem
      coordinator's size OK **and** Christian's go-ahead.
      - [ ] R9 debug / gcc / mkl
      - [ ] R10 debug / gcc / mkl
      - [ ] AMZN gcc / mkl
      - [ ] U24 debug / gcc / mkl
      - [ ] U26 debug / gcc / mkl
      New NEVRAs per drop: environment 2026-3, gperftools 2.18.1-2, scotch 7.0.15-2, hwloc 2.14.0-2,
      libunwind 1.8.3-3, spral 2025.09.18-1, ipopt 3.14.20-1, `scls-<F>` 2026-2; on the RPM hosts
      also openmpi 5.0.11-2 and (debug) lapack 3.12.1-2. Everything else goes under
      `already_published:`.
      `stage_to_belfem.sh` records `git_head`, so restage right before each upload, on the merged
      commit. mkl: `check_mkl_linkage.sh` before READY.
      belfem's arrival checks: gperftools NEEDs the SCLS `libunwind.so.8`; scotch NEEDED
      `libz`/`libbz2`/`liblzma` match its new Requires; mkl objects carry one threading layer.
- [ ] **Website:** regenerate with ipopt and deploy. The template changes are in the tree
      (`8a5f7f6`, `0b37bd3`, `84efaca`); nothing is deployed.
- [ ] **Branch names in the workflow.** `/update-plan`, `/update-build`, `/build-stack` and
      `doc/BUILD_EXECUTION.md` §0 and §1.2 name `devel` as the working branch ("All work goes on
      `devel`. Never commit to `main`."). Decide what replaces it before `devel` is deleted, and
      edit those four files to match.

## 2. Decisions pending (Christian)

- [ ] **`libscotchmetis`** — keep, switch off, or namespace. `todo/scotch_metis_prefix.md`. Needs a
      Linux build plus a PETSc partitioner run to close.
- [ ] **`lbl` openmpi is 4.1.6-2 with no content change**, because `release:` is recipe-wide.
      Accept it, or add a per-flavor release override (build-config change).
- [ ] **Compression dependencies outside scotch (optional).** netcdf still takes bzip2 from
      whatever the host has (U26 without `libbz2-dev` falls back to netcdf's built-in bz2; el9
      links the system library). Same question for libunwind and xz/zstd. scotch is done
      (7.0.15-2).
- [ ] **PRRTE and libnl (informational).** Ubuntu's PRRTE links libnl, el9's does not. Decide only
      if the RPM side should enable it.

## 3. Recipes and manifests (each needs approval)

- [ ] **openmpi, `gcc-mkl-cuda`:** built without `--with-pmix/--with-hwloc/--with-libevent/--with-ucx`.
      Its own `flavor_args` key wins over `mkl`'s and the blocks are not merged, while `requires`
      resolves to the mkl list. Untested flavor.
- [ ] **openmpi, `intel`:** no `requires` key, configured with `--with-prrte=internal` only.
      `flavors/intel.yaml` sources `setvars.sh` and BuildRequires `openmpi-devel`, a second way an
      external PRRTE or MPI could leak in.
- [ ] **openmpi comment (comment-only):** the block above `patches:` in `recipes/openmpi.yaml`
      (lines 18–26) still describes the GCC 16 always-inline patch dropped in 5.0.11-1.
- [ ] **`files/openmpi.txt`** is an ORTE-era list (40 `orte*` entries, no PRRTE). Unused while
      `rpm_files_auto: true`. Delete or regenerate.
- [ ] **lapack runtime dependency (P1):** `scls-<F>-lapack` does not require `scls-<F>-blas`,
      although `liblapack.so.3` NEEDs `libblas.so.3`. The recipe lists `blas` under the same-name
      `lapack` subpackage, which both builders skip without merging its requires. Re-checked
      2026-10-04 with `--spec-only` (debug): the main package requires only `environment`.
- [ ] **lapack licence notice (P2):** the binary packages ship no LAPACK LICENSE; `files/lapack.txt`
      has none.
- [ ] **vtk dead option:** `-DVTK_BUILD_SCALED_SOA_ARRAYS=OFF` (`recipes/vtk.yaml:41`) is unused
      since VTK 9.7.0.
- [ ] **CPATH / LIBRARY_PATH audit.** The DEB/unix build environment exports
      `CPATH=<prefix>/include` and `LIBRARY_PATH=<prefix>/lib`; RPM does not. Two packages have
      changed what they build because of it (openmpi's PRRTE, `950c074`; spral's CBLAS-gated test,
      `d908cfc`). Audit the other recipes with bundled components or `rpm_files_auto: true` (ucx,
      vtk, libunwind, hdf5, petsc), and decide whether the DEB env should set these at all
      (`python/`, six-step gate).

## 4. Builders and scripts (`python/`, `scripts/`; approval and the review gate)

- [ ] **`extra_packages:` is ignored by unix_builder and deb_builder (B1)**, and `NEVER_SHIP`
      matches the binary short name only (B2). `todo/extra_packages_unix_deb_override.md`.
- [ ] **unix/deb ignore `configure.flavor_pre` / `configure.flavor_post`** for every configure
      type; rpm_builder runs them. Live case: openmpi's gcc-mkl-cuda CUDA-support check never runs
      on .deb hosts.
- [ ] **MKL environment keyed on the flavor name.** `build_common.setup_environment` sets it only
      when the name contains "mkl" (`build_common.py:1089`), so `intel` gets none on unix/deb.
      Mirror the RPM `mkl_root` change (`math.linalg`).
- [ ] **`%{mklroot}` replaced without a `None` guard** in `rpm_builder.py` (latent: every flavor
      that uses the token sets `mkl_root`). Carried from `spral_recipe.md`, not re-checked.
- [ ] **One shared el9 parity gate** (Christian, 2026-10-01): turn U26's
      `work/parity/needed_parity.sh` + `score2.py` into a repo-relative `scripts/` tool and hook it
      into `stage_to_belfem.sh` before READY. Two blind audits. Not started; no parity script is in
      `scripts/`.
- [ ] **sudo keepalive under sudo-rs (U26).** `scls build all` refreshes with `sudo -n -v`
      (`scls:168-176`), which sudo-rs rejects even with `--scope all`. Test
      `sudo -n apt-get --version` / `sudo -n dnf --version` instead, or switch U26 to sudo.ws.
- [ ] deactivate removes `OMP_CANCELLATION` even if the user changed it after activating. P2,
      accepted for now.

## 5. Workflow and docs

- [ ] **`doc/BUILD_EXECUTION.md` §1.3 tests sudo with `sudo -n true`** (line 116). Under the
      recommended `--scope pkg` grant that always fails. Same replacement as the keepalive in §4.
- [ ] **`_meta` is not installed by the tracker-driven loop.** Add "install `_meta` at the end of
      each flavor" to `/update-build` and `/build-stack`. This is how vtk went missing on U24.
- [ ] **Drift sweep skips packages that are not installed** (`BUILD_EXECUTION.md` §1.6,
      `[ -z "$have" ] && continue`). Report "not installed" for anything the flavor meta-package
      depends on.
- [ ] **Fresh-Ubuntu-host prep checklist:** `curl` is missing on a 26.04 minimal install; cover the
      auditor sandbox and the sudo grant too.
- [ ] **README.md contradicts `doc/MACOS_BUILD.md` on Apple Silicon.** README lines 5, 102 and 165
      still say "bring-up" and "untested after OpenMPI"; `MACOS_BUILD.md` says the full stack was
      built on arm64 during ASC 2026 and is supported. Found 2026-10-04 while tidying this list.
- [ ] **Changelog files missing:** `changelogs/binutils.md`, `changelogs/libtool.md`.

## 6. Verification still owed

- [ ] **spral / ipopt on `lbl`, `macos`, `intel`.** The three rows were never ticked. The round-2
      instructions say macOS was done on 2026-10-03; confirm and record, including
      `otool -l libspral.dylib` showing the header pad.
- [ ] **intel:** the MKL path baked into the spec at generation time agrees with what `setvars.sh`
      sets in `%build`.
- [ ] **EL8:** meson needs Python >= 3.7; select it through `flavor.conf` `python:`.
- [ ] **EL9 dev host:** reinstall the current `scls-mkl-scalapack` (2.2.3-4) and
      `scls-mkl-armadillo` (15.6.0-2); the stale ones fail `check_mkl_linkage.sh`.
- [ ] **HSL:** `./scls install hsl --global` on a terminal with sudo (Christian). The macOS run
      (`libhsl.dylib`, hard install name) has never been made. `debug` and `intel` not run.
- [ ] **Apple Silicon:** the `hw.cpufamily` detector's `apple-m1` fallback has not been exercised
      on an M4/M5 host.
- [ ] **(optional) GCC bug report** for the `zlaqr5` SLP+FMA wrong code; the reproducer is in U26
      scratch.

## 7. Host notes

- [ ] **U24 auditor sandbox.** bwrap is blocked by
      `kernel.apparmor_restrict_unprivileged_userns=1`, so Codex and Grok audits read nothing
      there. Persist the sysctl, back-port 26.04's `bwrap-userns-restrict` profile, or keep running
      audits from U26 or the dev host. Still blocked on 2026-10-04.
- [ ] **R9 sudo grant is not durable:** there is no `/etc/sudoers.d/scls-build`; the round-2 builds
      ran on a cached login. `scripts/grant_pkg_sudo.sh --user mockbuild --scope all --apply`
      (Christian).
- [ ] `flavor.conf` is tracked with `macos` as the committed default. Each build host:
      `git checkout flavor.conf` before pulling the merged branch.

## 8. Where the closed work is recorded

| Topic | Record |
|---|---|
| Round 2 builds per host | `devlog/dl20261003_r9_round2.md`, `dl20261004_r10_round2.md`, `dl20261004_amzn_round2.md`, `dl20261004_u24_round2.md`, `dl20261004_u26_round2.md` |
| 2026-09-22 campaign, rows 1–31 | `todo/rebuild_campaign_20260922.md`, `devlog/dl20260923_r9_rebuild_campaign.md`, `dl20260925_*` |
| U24 / U26 round-1 drops (promoted) | `devlog/dl20260929_deb_no_as_needed.md`, `dl20261001_u26_resolute_deployment_prep.md` |
| SPRAL recipe, Ipopt `--with-spral` | `devlog/dl20261003_spral_recipe.md` |
| HSL private build | `devlog/dl20261003_libhsl_private_build.md`, `doc/HSL_BUILD.md` |
| gperftools libunwind, scotch compression, triplet prefixes, `SCLS_JOBS` | `devlog/dl20261003_r9_round2.md`, the package changelogs |
| Apple Silicon GCC patch and report fixes | `devlog/dl20260904_gcc_apple_silicon_patch.md`, `dl20260910_apple_silicon_report_fixes.md` |
| ASC 2026 upgrade, OpenMP C5 and single-source plans | `devlog/dl20260818_asc2026_upgrade_plan.md`, `dl20260817_strumpack_openmp_tasking.md` |
