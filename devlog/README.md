# SCLS Devlog Index

Session summaries for AI-assisted work on SCLS, newest first. One line per entry.
See [`doc/AI_COLLABORATION_PROTOCOL.md`](../doc/AI_COLLABORATION_PROTOCOL.md) §6 for
what belongs here, the required header, and the `dlYYYYMMDD_topic.md` naming.

This directory is the **tracked durable record**. The AI-to-AI exchange under
`tmp/ai_exchange/` is git-ignored scratch and gets swept; `todo/` is git-ignored too.
If a conclusion is not here, in `changelogs/<package>.md`, or in a `doc/*.md` policy
file, it is lost.

## Entries

- [dl20261005_license_policy_no_gpl.md](dl20261005_license_policy_no_gpl.md) — licence policy restated: published binaries BSD-3-compatible (permissive or weak copyleft), no GPL of any version; GPL only for build tools; website build-tools table gains pkg-config and the generator refuses to render a policy violation

- [dl20261004_campaign_policy_and_math_campaign.md](dl20261004_campaign_policy_and_math_campaign.md) — devlog review for procedure gaps, new campaign policy, PETSc 3.26 math campaign, and the measurement that Scotch's ParMETIS emulation shadowed the real ParMETIS in PETSc (`SCOTCH_METIS_PREFIX`)

- [dl20261004_u26_round2.md](dl20261004_u26_round2.md) — U26 round 2 built and installed on debug/gcc/mkl (GCC 15.2); spral debug `CPATH` fix reproduced, audits for `d908cfc`; release-bump rule (`BUILD_EXECUTION.md` §0.6); HSL script test on gcc
- [dl20261004_u24_round2.md](dl20261004_u24_round2.md) — U24 round 2 built and installed on debug/gcc/mkl; spral debug `CPATH` fix for the unix/deb builders (`d908cfc`); mkl `ssidst` against meson's 300 s limit; HSL script test on gcc
- [dl20261004_amzn_round2.md](dl20261004_amzn_round2.md) — AMZN round 2 on gcc/mkl: same nine NEVRAs as R9/R10, every §3 check passes (gperftools pprof skip held with Perl pprof present), MKL linkage PASS, HSL script test on gcc; nothing staged
- [dl20261004_r10_round2.md](dl20261004_r10_round2.md) — R10 round 2 on debug/gcc/mkl: linking fixes, spral + ipopt, HSL script test; gperftools pprof-dependent checks skipped (`ac_cv_path_PPROF_PATH=`), agreed with R9 and audited
- [dl20261003_r9_round2.md](dl20261003_r9_round2.md) — R9 round 2 built and installed on debug/gcc/mkl: gperftools+libunwind, scotch compression, `--target` removal with a triplet-program guard, meta release 2, spral + ipopt; HSL script test; nothing staged yet
- [dl20261003_xz_macos_lbl_tools.md](dl20261003_xz_macos_lbl_tools.md) — xz 5.8.4 now builds on `macos` and `lbl` with the 0BSD tools (rule: packaged distros use distro xz, self-building flavors provide their own); libunwind and scotch use the stack's xz on lbl; built and tested on macOS, lbl RPM gate pending
- [dl20261003_spral_recipe.md](dl20261003_spral_recipe.md) — new SPRAL 2025.09.18 recipe (SSIDS, BSD-3, first `configure.type: meson`), CUDA-probe patch, Ipopt 3.14.20 `--with-spral` + SPRAL `%check`, activate sets `OMP_CANCELLATION`; RPM autotools arg expansion/quoting fix; intel `%{mklroot}`→None fix; oneAPI repo gated per flavor; three review rounds
- [dl20261003_libhsl_private_build.md](dl20261003_libhsl_private_build.md) — private libhsl for Ipopt from a licensee's own HSL tarballs: Coin-HSL base + verified MA77 6.5.0 override, bash assembler, own CMakeLists, MA77 factor/solve gate; scripts public, sources private; gcc + mkl gated
- [dl20261001_u26_resolute_deployment_prep.md](dl20261001_u26_resolute_deployment_prep.md) — U26 resolute debug/gcc/mkl uploaded, promoted and apt-verified: resolute repo + upload key + keyring, relink via gcc specs, per-object el9 parity HARD 0 on debug/gcc/mkl, bz2/xz/zstd host packages, check_mkl_linkage pipefail/SIGPIPE flake
- [dl20260929_deb_no_as_needed.md](dl20260929_deb_no_as_needed.md) — U24 .deb drops to belfem (debug, gcc promoted; mkl cancelled); Ubuntu's default `--as-needed` broke per-object el9 link parity, so `.deb` links now use `--no-as-needed`; closed `no_source:` list; CDN stale-index incident
- [dl20260927_u26_full_stack_build.md](dl20260927_u26_full_stack_build.md) — U26 (Ubuntu 26.04) first full-stack build: debug 37, gcc 37, mkl 36 installed; sudo-rs, curl, vtk OOM job cap; MKL linkage PASS
- [dl20260926_ipopt_recipe.md](dl20260926_ipopt_recipe.md) — new Ipopt 3.14.20 recipe (EPL-2.0, MPI MUMPS, MKL Pardiso for free); macOS build + 7/7 tests; found that the RPM builder writes autotools configure args verbatim (no SCLS-macro expansion, no quoting) — fix prototyped, awaiting approval; one blind Codex+Grok round
- [dl20260926_u26_lapack_gfortran15_zlaqr5.md](dl20260926_u26_lapack_gfortran15_zlaqr5.md) — U26 (Ubuntu 26.04): gfortran 15.2 SLP+FMA wrong code in reference LAPACK `zlaqr5` gave wrong complex eigenvectors for 76≤n<150; lapack 3.12.1-2 builds with `-ffp-contract=off`
- [dl20260925_r10_build_and_publish.md](dl20260925_r10_build_and_publish.md) — R10 column of the 2026-09-22 campaign built and published (4 drops); MKL threading fix rebuilt on all flavors; relative `--stage` gate bug fixed
- [dl20260913_environment_toolchain_requires.md](dl20260913_environment_toolchain_requires.md) — environment now Requires the host toolchain and Recommends doxygen; new `rpm_recommends:` field; generated spec honours `release:`
- [dl20260904_mumps_macos_install_names_handover.md](dl20260904_mumps_macos_install_names_handover.md) — triaged the BELFEM MUMPS dylib install-name handover: stale, fixed generically by the macOS post-install normalizer in `f171e7d` (2026-05-27); remaining check is whether the Mac's installed prefix post-dates it
- [dl20260904_website_restyle_and_doc_sweep.md](dl20260904_website_restyle_and_doc_sweep.md) — ported the scls.html restyle into the Jinja template/generator; swept README, doc/, CLAUDE.md and the website for stale GCC 15 and Apple Silicon claims
- [dl20260910_apple_silicon_report_fixes.md](dl20260910_apple_silicon_report_fixes.md) — patched the seven findings of the first Apple Silicon bootstrap report (zsh activation, gklib NO_X86, macOS manifest hazard, vtk libstdc++ macros, openmpi PRRTE guard, PETSc PETSC_ARCH); report's empty-PETSC_ARCH fix refuted against PETSc source; two blind Codex+Grok rounds
- [dl20260904_gcc_apple_silicon_patch.md](dl20260904_gcc_apple_silicon_patch.md) — vendored Homebrew's aarch64-apple-darwin GCC 16.2.0 branch patch, gated on arm64 via a new `arch:` patch-entry key; two-round Codex+Grok review, no Apple Silicon build evidence
- [dl20260904_auditor_depth_selection.md](dl20260904_auditor_depth_selection.md) — ported BELFEM's explicit model/effort depth selection into the Codex and Grok wrappers and `cross_review.sh`
- [dl20260817_ai_collaboration_setup.md](dl20260817_ai_collaboration_setup.md) — ported the BELFEM AI collaboration tooling and protocol to SCLS
- [dl20260817_strumpack_openmp_tasking.md](dl20260817_strumpack_openmp_tasking.md) — mkl-flavor STRUMPACK lost its OpenMP tasking: `-lgomp` in `CMAKE_<LANG>_STANDARD_LIBRARIES` poisons cmake `try_compile` probes
- [dl20260818_asc2026_upgrade_plan.md](dl20260818_asc2026_upgrade_plan.md) — ASC 2026 final upgrade: 14 upstream bumps, 5 rebuild-only packages, build order, and the decisions to settle first
