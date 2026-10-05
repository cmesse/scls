# Backlog

The only place where deferred work lives (`doc/CAMPAIGN_POLICY.md` §3). Append a finding here in
the session that makes it, with its source. `/update-plan` reads this file first; Christian picks
what joins the next campaign. Remove an entry when it is done; the record of the work is the devlog
and the changelog.

Nothing in §2–§9 blocks the running campaign (`todo/rebuild_campaign_20261004.md`). Staging of
round 2 and the campaign in one drop per flavor: §1 and `todo/campaign_20261004_hosts.md`.

Last full re-check against the tree: 2026-10-04 (macOS dev host). §9 was carried over from devlog
"Open" sections and has **not** been re-checked.

`todo/rebuild_campaign_20260922.md` is a closed campaign, kept as the layout reference for
`/update-plan` and because 16 changelogs and `/stage-drop` cite it.

---

## 1. Release — the 2026-10-04 math campaign, with round 2 on the RPM hosts

Round 2 is published for U24 (noble) and U26 (resolute) since 2026-10-05 UTC. On R9, R10
(debug/gcc/mkl) and AMZN (gcc/mkl) it is built and installed and was never staged. The math
campaign (`todo/rebuild_campaign_20261004.md`) adds six packages per flavor on every host. The RPM
drops carry round 2 and the campaign together; the Ubuntu drops carry the campaign.
Per-host instructions: `todo/campaign_20261004_hosts.md`.

- [ ] **Build the campaign:** pilot on R9 and U24, then R10, AMZN and U26 on the commit Christian
      releases.
- [ ] **Stage and upload** with `/stage-drop` once all five hosts have passed: 14 drops, one in
      flight, debug → gcc → mkl per host, each after the belfem coordinator's size OK, the
      promotion of the previous drop and Christian's go-ahead.
- [ ] **Website:** regenerate with ipopt and the new versions and deploy, after the campaign is
      published (the table shows recipe versions). The template changes are in the tree
      (`8a5f7f6`, `0b37bd3`, `84efaca`, and the 2026-10-05 license wording and build-tools table,
      `devlog/dl20261005_license_policy_no_gpl.md`); nothing is deployed.
- [ ] **Branch names in the workflow.** `/update-plan`, `/update-build`, `/build-stack` and
      `doc/BUILD_EXECUTION.md` §0 and §1.2 name `devel` as the working branch. Decide what replaces
      it before `devel` is deleted, and edit those four files to match.
- [ ] **macOS:** rebuild scotch, petsc and slepc for the prefix (two-level namespace: the existing
      `libpetsc` names Scotch's library for `ParMETIS_V3_PartKway`), plus hwloc, armadillo and
      sundials at the new versions, and mumps 5.9.1-3 (`0a256a1`; no build change on macOS,
      version parity only). ipopt 3.14.20-1 is unchanged on macOS.

## 2. Decisions pending (Christian)

- [ ] **Version bumps not taken on 2026-10-04:** vtk 9.7.1 (Christian: next week), openssl 3.6.5
      (macOS only), butterflypack 5.0.0 (major; declined for now).
- [ ] **Held by PETSc 3.26.0's pins** (`doc/CAMPAIGN_POLICY.md` §9): scotch 7.0.16 (patch ready in
      `patches/scotch/archive/`), superlu_dist 9.3.0, cmake 4.4.4. They become candidates when
      PETSc moves.
- [ ] **hdf5 is a major version behind PETSc's pin** (1.14.6 against 2.2.0; `max_major: 1`).
      Christian, 2026-10-04: not this round. netcdf and exodus depend on it.
- [ ] **Compression dependencies outside scotch (optional).** netcdf (bzip2, zstd) and libunwind
      (xz, on every Linux flavor but `lbl`) link host libraries that no recipe declares; the
      `-devel` packages are host prep (`doc/BUILD_EXECUTION.md` §1.1b). Declaring them is a metadata
      change: the binaries already link these libraries on every host. Radius: netcdf and libunwind
      only, 14 builds each, no cascade. netcdf -2 and libunwind -3 are published (libunwind -3 on
      noble and resolute), so both need a release bump. `libzstd` (runtime) has no .deb mapping yet. scotch is
      done (7.0.15-2).
- [ ] **PRRTE and libnl (informational).** Ubuntu's PRRTE builds the `prtereachable/netlink`
      component (libnl comes in with the rdma dev packages); el9's does not. Enabling it on RPM
      touches openmpi only (no cascade, SONAMEs unchanged); openmpi 5.0.11-2 is published on noble
      and resolute, so it would be -3 on all five hosts (14 builds). The Ubuntu openmpi .deb
      links libnl without declaring it (covered transitively by ucx → libibverbs1).

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
- [ ] **lapack license notice (P2):** the binary packages ship no LAPACK LICENSE; `files/lapack.txt`
      has none.
- [ ] **`files/petsc.txt` and `files/slepc.txt` carry the literal version** in
      `lib/{petsc,slepc}/conf/modules/<pkg>/<version>` and are edited by hand on every bump;
      `%{version}` would do (Codex, 2026-10-04 implementation audit).
- [ ] **vtk dead option:** `-DVTK_BUILD_SCALED_SOA_ARRAYS=OFF` (`recipes/vtk.yaml:41`) is unused
      since VTK 9.7.0.
- [ ] **CPATH / LIBRARY_PATH audit.** The DEB/unix build environment exports
      `CPATH=<prefix>/include` and `LIBRARY_PATH=<prefix>/lib`; RPM does not. Two packages have
      changed what they build because of it (openmpi's PRRTE, `950c074`; spral's CBLAS-gated test,
      `d908cfc`). Audit the other recipes with bundled components or `rpm_files_auto: true` (ucx,
      vtk, libunwind, hdf5, petsc), and decide whether the DEB env should set these at all
      (`python/`, six-step gate).
- [ ] **ipopt, `intel` flavor: `libsipopt.so` still has no MKL directory in its RUNPATH.** The
      2026-10-04 fix is `configure.flavor_pre` under the key `mkl`, which matches `mkl` and
      `gcc-mkl-cuda` but not `intel` (`python/build_common.py` `get_flavor_names`). Untested flavor.
- [ ] **`scls-<F>-examples` 2026-1 is regenerated whenever the flavor meta-package is built.** The
      round-2 meta build (2026-10-03) left new `scls-{debug,gcc,mkl}-examples-2026-1` RPMs and
      SRPMs in the R9 output tree that are not byte-identical to the ones published on
      2026-08-19 (belfem, R9-mkl-20261005T0551Z: noarch header differs with identical payload,
      src payload differs). On mkl, Requires and file list equal the installed 2026-08-19
      package. They are never in a payload (same NEVRA as published), so nothing shipped. Either
      the examples meta gets its own release like `meta_release`, or the meta build stops
      rewriting it.

## 4. Builders and scripts (`python/`, `scripts/`; approval and the review gate)

- [ ] **`build next`, `build all` and `order` ignore `extra_packages:`** on every builder:
      `build_order.py` does not read it, so an opted-in package builds only when named
      (`./scls build <pkg>`). Left open when the explicit-build path was fixed on 2026-10-04.
      Consequence on unix/deb: with `extra_packages: [gcc]`, every package that lists `gcc` as a
      dependency now requires the prefix gcc, `build next` never schedules it, and
      `DebBuilder._flavor_builds_own_gcc` still injects the system compilers. Build gcc by name
      first, or teach `build_order.py` and that helper the opt-in (Grok, implementation audit).
- [ ] **`stage_to_belfem.sh` globs `scls-<F>-*`,** which for `gcc` also matches
      `scls-gcc-mkl-cuda-*`. Pre-existing; found by Grok on 2026-10-04.
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
- [ ] **Builder license warning is keyed on the substring `GPL-3`.** `python/rpm_builder.py:2323-2328`
      and `python/unix_builder.py:1544-1549` warn "GPL-3 libraries must NOT be distributed" when
      `'GPL-3' in license`: true for LGPL-3 (mpfr, mpc), false for `GPL 2.0`, `GPL-2.0-or-later`
      and gmp's `GPLv2+`, and it also fires for the intended GPL build tools. `deb_builder.py` has
      no counterpart. Align with `doc/LICENSE_POLICY.md` as restated 2026-10-05 (no GPL of any
      version in published binaries). Found by both auditors in the 2026-10-05 plan round.
- [ ] **No license gate on what is staged.** The staging selectors hard-code SuiteSparse as
      never-shippable (`scripts/stage_to_belfem.sh:173`, `scripts/deb_drop_select.py:59`). A new
      GPL recipe enabled for a public flavor would build and could enter a drop;
      `python/generate_website.py` refuses to render in that case, but `./makeweb` is not a
      shipment gate.
- [ ] **sudo keepalive under sudo-rs (U26).** `scls build all` refreshes with `sudo -n -v`
      (`scls:168-176`), which sudo-rs rejects even with `--scope all`. Test
      `sudo -n apt-get --version` / `sudo -n dnf --version` instead, or switch U26 to sudo.ws.
- [ ] deactivate removes `OMP_CANCELLATION` even if the user changed it after activating. P2,
      accepted for now.
- [ ] **`scripts/hsl/tests/test_assemble.sh` case "outside hardlink with blank in target
      refused" fails on R9** (expected failure, got success; 20 other cases pass). Pre-existing:
      fails identically on `810d9df` before the 2026-10-05 spelling change. Not reproduced on
      another host yet; probably tar member handling on EL9. (`dl20261005_american_spelling_license`)

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
- [ ] **U24 and U26 share one physical host and slow each other down.** On 2026-10-05 U26 needed
      two hours for a flavor that U24 built in 35 minutes, and 44 minutes once the U24 VM was off;
      a single-core loop varied fourfold between consecutive runs. Not diagnosed from inside the
      VM. Check the host (temperature, frequency, vCPU overcommit) before the next campaign, or
      keep building the Ubuntu hosts one after the other (`devlog/dl20261005_u26_math_campaign.md` §5).
- [ ] `flavor.conf` is tracked with `macos` as the committed default. Each build host:
      `git checkout flavor.conf` before pulling the merged branch.

## 8. Engineering causes behind the 2026-09/10 rework (`doc/CAMPAIGN_POLICY.md` §10)

- [ ] **One build environment for both builders.** rpm_builder and unix/deb_builder differ in
      `CPATH`/`LIBRARY_PATH`, LDFLAGS for math recipes, `configure.args` expansion,
      `configure.flavor_pre/post`, `flavor_env`, and the MKL environment. Six incidents trace to
      this (PRRTE, gperftools libunwind, spral `cblas.h`, ipopt F1, `--as-needed`, intel MKL env).
- [ ] **Builds depend on undeclared host state:** installed `-devel` packages, EPEL's `pprof`, a
      venv on `PATH`, an earlier install of the same package in the prefix. Options: a clean-room
      build (mock/chroot), or a host baseline check in preflight.
- [ ] **Port belfem's arrival checks into the repo as gates:** the per-object el9 parity check
      (§4, not started) and the installed-versus-recipe selection for staging (§9).
- [ ] **Working branch after `devel` is deleted.** `/update-plan`, `/update-build`, `/build-stack`
      and `doc/BUILD_EXECUTION.md` §0.2 and §1.2 name `devel`.

## 9. Carried from devlog "Open" sections on 2026-10-04 — not re-checked

Staging and tooling:
- [ ] `stage_to_belfem.sh` selects from `rpm -qa`, so a package that is not installed is dropped
      with no `excluded:` line (the meta-package is the risky case). Drive selection from the
      recipes and cross-check against what is installed. (`dl20260925_r9_gcc_mkl_stage_drops` §3)
- [ ] Upload mode reprints `excluded:` from current host state, not from the staged MANIFEST.
      (`dl20260925_r10_build_and_publish`)
- [ ] `stage_to_belfem.sh:4` header names an old contract version. (`dl20260925_r9_gcc_mkl_stage_drops` §2)
- [ ] The keyring is selected into every drop until one is promoted; sequencing prevents a double
      ship, no guard does. (`dl20260929_deb_no_as_needed`)
- [ ] `BUILD_EXECUTION.md` §5.2 orphan check reports subpackages (`blas`, `cblas`, `lapacke`,
      `*-examples`) as orphans. (`dl20260923_r9_rebuild_campaign`)
- [ ] `./scls install hsl` leaves an empty `/tmp/scls-hsl-<uid>`. (`dl20261004_r10_round2`)
- [ ] `python/scls.py` `_install_direct` continues after a failed removal. (`dl20261003_unix_install_sudo`)
- [ ] `setup_environment` ignores `flavor_env` unless `configure.env` exists
      (`build_common.py:1104-1134`). (`dl20261004_u24_round2`)

Recipes and tests (each needs approval):
- [ ] gperftools pipes `make check` through `tee`, so a test failure cannot fail the build.
- [ ] libunwind has no `test:` block.
- [ ] spral: `ssidst` runs close to meson's 300 s limit on loaded VMs; `meson test -t N` is a
      recipe change.
- [ ] spral on debug: a host with a system-wide `cblas.h` would defeat the `CPATH` fix.
- [ ] `recipes/environment.yaml` says `BSD-3-Clause`; the repository is `BSD-3-Clause-LBNL`.
- [ ] `pkg-config --libs ipopt` carries no rpath.
- [ ] `hwloc-dump-hwdata` (sbin) may not belong in a prefix install.
- [ ] The gperftools .deb installs 59 files, the RPM 73; not investigated.
- [ ] mkl: ScaLAPACK's BLAS is threaded since 2.2.3-4 and nothing pins `MKL_NUM_THREADS`; accepted
      on 2026-09-25, revisit if users report oversubscription.

Verification owed elsewhere:
- [ ] lbl: `scls-lbl-xz`, libunwind and scotch against the prefix liblzma (needs a Linux lbl host).
- [ ] macOS: `files/xz.txt`, hwloc's plain tool names, scotch against the stack liblzma, a real
      `--uninstall`.
- [ ] RPM `%post` registry rewrite with `registry.pc_name` on a Linux host.
- [ ] U26: the gcc specs override still has one inert `--as-needed` entry (Android branch).
- [ ] Ipopt 3.14.20 upstream: an `hsllib` that cannot be loaded segfaults at exit.

## 10. Where the closed work is recorded

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
