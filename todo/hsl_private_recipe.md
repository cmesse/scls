# Plan — private `hsl` recipe (libhsl.so for Ipopt's runtime loader)

**Status:** SUPERSEDED 2026-10-01 by [`libhsl_build_script.md`](libhsl_build_script.md) — HSL is built by a standalone script, not a recipe; Coin-HSL not needed (GALAHAD subset); one METIS (the stack's). Kept for the record of the packaging leak paths.
**Original status:** plan, awaiting maintainer decisions (§2) and the review gate (§8). Nothing under
`recipes/`, `python/`, `scripts/`, `patches/`, `files/` has been edited.
**Branch:** `ipopt`. **Date:** 2026-09-30.

## 1. Goal and non-goals

Give a licensee a one-switch way to build `libhsl.so` from HSL sources they obtained themselves,
so the **unchanged, public** `libipopt` can use MA97/MA57 at runtime (`linear_solver ma97` +
`hsllib`). Public repos never carry HSL source, binaries, or a dependency on them.

- **No change to `recipes/ipopt.yaml`.** It already configures `--without-hsl` with the runtime
  loader on. Verified in upstream Ipopt 3.14.20:
  - The loader is created only for solvers not linked in (`src/Algorithm/IpAlgBuilder.cpp:1140-1152`).
  - The default library name is `libhsl.<shlibext>` (`:303-308`).
  - Each solver resolves its symbols lazily, only when selected (`src/Algorithm/LinearSolvers/IpMa97SolverInterface.cpp:305-311`, `IpMa57TSolverInterface.cpp:313-317`).
  - The default `linear_solver` stays `mumps`, because linked solvers win over loaded ones (`IpAlgBuilder.cpp:207-252`). So a missing `libhsl` changes nothing for users who don't ask for it.
- Non-goal: MA27, MA28, MC30, HSL_MA77. MA28 and MC30 are used only when HSL is linked at build
  time (`IpLinearSolversRegOp.cpp:119`, `IpEquilibrationScaling.cpp:19`).
- Later, not now: HSL_MA86 + HSL_MC68 + MC19 once Coin-HSL arrives (requested 2026-09-30). That
  would be a source swap inside this recipe; Ipopt is untouched.

## 2. Decisions for Christian (block implementation)

- [ ] ~~**D1 — where libhsl is installed.** The HSL Academic Licence 2.0 §2.1 grants *personal*~~
  use and forbids sharing use with any third party "regardless of whether such third party is from
  the same institution" (§2.1.2).
  - (a) RPM/.deb into the flavor prefix `%{prefix}/lib`. Ipopt finds it with no `hsllib` option, but the library is visible to every user of the host.
  - (b) unix_builder only, into a per-user prefix (e.g. `~/.local/scls-hsl/<flavor>`). Users set `hsllib /abs/path/libhsl.so` in `ipopt.opt`.
  - Recommendation: allow (a) only on single-user hosts, and document that the licensee decides. Whether it is compliant is Christian's or LBNL licensing's call, not ours.
- [ ] ~~**D2 — version string.** The package bundles several upstream releases. Recommendation:~~
  SCLS date version `2026.09.30`, with the component versions pinned in the recipe and changelog.
  When Coin-HSL lands, switch to its version (`2024.05.15`).
- [ ] ~~**D3 — how "never download" is enforced.** Today a missing tarball falls through to~~
  `curl -fL <source.url>` (`python/build_common.py:434-462`), and `source.url` is mandatory
  (eager default in `rpm_builder.py:1976-1981`; `validate_project.py:134-145`).
  - (a) **Recommended:** a new recipe key `source.fetch: never`. The builders then refuse to download and fail with a message naming the expected file and the cache directory.
  - (b) No builder change: point `url` at the HSL product page. Fragile, because it relies on the HTML failing tar validation, and it sends a request to STFC on every miss.
- [ ] ~~**D4 — platforms.** Recommendation: every flavor may opt in (`include_flavors: []` plus~~
  `extra_packages:`), macOS included (`libhsl.dylib`; Ipopt's default `hsllib` follows
  `IPOPT_SHAREDLIBEXT`).

## 3. Source contents (verified 2026-09-30 against the tarballs in `tmp/HSL/`)

| Tarball | Used | What we take |
|---|---|---|
| `hsl_ma97-2.8.1.tar.gz` | yes | `src/common.f common90.f90 ddeps90.f90 hsl_ma97d.f90 hsl_ma97d_ciface.f90` (double only) |
| `ma57-3.11.3.tar.gz` | yes | `src/ma57d.f ddeps.f` (Ipopt calls F77 `ma57{a,b,c,e,i}d`) |
| `hsl_ma57-5.3.2.tar.gz` | no | F95 wrapper; Ipopt does not use it |
| `hsl-galahadd-5.20000.0.tar.gz` | no | templated GALAHAD build; symbol names not verified against Ipopt |

Facts established:
- `hsl_ma97d_ciface.f90` defines all seven C symbols Ipopt loads (`ma97_{default_control,analyse,factor,factor_solve,solve,finalise,free_akeep}_d`).
- The `ma97_control` and `ma97_info` structs in Ipopt's `hsl_ma97d.h` are token-identical to the package's `include/hsl_ma97d.h`.
- **Duplicate symbols.** `ma57/ddeps.f` and `hsl_ma97/common.f` both define 20 routines: a set of shared F77 helper routines. The code of all 20 is identical once comment lines are stripped (per-routine hash). Each routine must be compiled exactly once, or the shared-library link fails.
- **METIS 4 interface.** Both packages call METIS 4's Fortran entry point
  `metis_nodend(n, xadj, adjncy, numflag=1, options, invperm, perm)` . They detect a stub by `perm(1) == -1` after a probe call on a
  1×1 or 2×2 graph. The stack's METIS is 5.2.1 with 32-bit `idx_t`, which matches default Fortran
  `INTEGER` (`recipes/metis.yaml:37-38`), but METIS 5 has no `metis_nodend_`.

## 4. Build design

`configure.type: custom`. We build with our own small Makefile, not the packages' autotools,
because we want one library, double precision only, and the stack's METIS and math line.

- [ ] ~~`patches/hsl/scls-build.patch`: a `/dev/null` patch that adds two files to the source tree~~
  (precedent: `patches/gcc/gcc-16.2.0-darwin-aarch64-homebrew.patch`). The patch is SCLS code and is
  publishable, but it stays out of any published SRPM because §5 suppresses the SRPM entirely.
  - `scls_metis4_shim.c`: `metis_nodend_` → `METIS_SetDefaultOptions` + `METIS_OPTION_NUMBERING=1` + `METIS_NodeND`, passing `invperm, perm` through positionally.
    - Special-case `n <= 1` and graphs with no off-diagonal edges; the probe calls use such graphs, and METIS 5 behaviour on them is not assumed.
    - Map `METIS_ERROR*` to a failure the callers already handle, and never return `perm(1) = -1` for a real graph.
  - `Makefile.scls`, in two steps:
    1. Dedupe: extract the 20 duplicated routines from `ma57/ddeps.f`, **assert** each is code-identical to the `common.f` copy, and drop it. Fail the build on any mismatch instead of silently keeping one.
    2. Compile in Fortran module order: `common90` → `ddeps90` → `hsl_ma97d` → `ciface`. Then link `libhsl.so.<N>` with `-fopenmp` (MA97 is OpenMP-parallel), `-L%{prefix}/lib -lmetis`, and `%{math_ldflags}`. SONAME `libhsl.so.1`; the unversioned `libhsl.so` symlink ships in the runtime package, because that is what Ipopt dlopens.
- [ ] ~~Unpacking: Source0 = `hsl_ma97-2.8.1.tar.gz`. `ma57-3.11.3.tar.gz` goes in `extra_sources:` with `fetch: never`, extracted by `tar -xf %{sources}/…` (precedent: `recipes/gcc.yaml:66-68`).~~
- [ ] ~~Install: `lib/libhsl.so*` plus `share/doc/scls-hsl/LICENCE`, which the licence requires to be retained. No headers: Ipopt carries its own.~~
- [ ] ~~`files/hsl.txt` manifest, `changelogs/hsl.md`, `registry:` with ldflags `-L%{prefix}/lib -lhsl`.~~
- [ ] ~~MKL flavors: `%{math_ldflags}` carries the flavor's single threading layer, per `doc/MKL_ABI_POLICY.md` "Threading-layer uniformity". `scripts/check_mkl_linkage.sh` must pass on `libhsl.so`.~~

## 5. Keeping it private — the guards (all need approval; they touch `python/` and `scripts/`)

A single recipe key drives everything, instead of more hand-synced lists: **`distribution: private`**.

- [ ] ~~**G1 — no source package.** `rpm_builder` runs `rpmbuild -bb` instead of `-ba` for private recipes (`python/rpm_builder.py:2027`). `deb_builder` skips `create_source_package` (`deb_builder.py:1925-1926`). The source tarball then never leaves `rpmbuild/SOURCES` / `work/sources`, which are git-ignored (`.gitignore:5-6`).~~
- [ ] ~~**G2 — not in the published meta-package.** `extra_packages` entries currently become Requires/Depends of `scls-<flavor>` (`rpm_builder.py:2491-2500`, `deb_builder.py:1958-1966`). Private recipes must be left out, the same way `META_EXCLUDED = {'gklib'}` is.~~
- [ ] ~~**G3 — staging refuses it.** `scripts/stage_to_belfem.sh:170-183` and `scripts/deb_drop_select.py:52-55,133-135` read `distribution: private` from the recipe and exclude it with a reason. Also close the gap the survey found: both tables match only the binary's short name, so a subpackage (`hsl-foo`) would slip through. Match on the `SOURCERPM` / `.dsc` source name as well. `suitesparse` stays in `NEVER_SHIP_REASON`: its reason (GPL-2) is different.~~
- [ ] ~~**G4 — never downloaded.** `source.fetch: never` (D3a), for Source0 and `extra_sources`.~~
- [ ] ~~**G5 — never committed.** Add ignore patterns for HSL tarballs outside `tmp/` (`patches/*.tar.gz` is not ignored today).~~
- [ ] ~~**G6 — build-order and website.** `include_flavors: []` already keeps it out of `build_order`, `next`, and `generate_website.py` (`build_order.py:30-40`; `generate_website.py:100-104`). Add a test that a private recipe never appears in either.~~

Prerequisite bug (independent of HSL, but blocks D4 on U24/U26/macOS):
- [ ] ~~**B1 — `unix_builder`/`deb_builder` ignore `extra_packages`.** `unix_builder.py:91-92` raises for any recipe `should_build_package` rejects, with no `extra_packages` override. Only `rpm_builder.py:383-395` honours it. Port the override.~~

## 6. Verification

- [ ] ~~**Spec-diff gate:** `--spec-only` for every recipe × flavor before and after the builder change. The only diff allowed is the new `hsl` spec. This proves G1/G2/G4 are inert for existing recipes.~~
- [ ] ~~Build `hsl` on one RPM flavor and one .deb flavor. Then check:~~
  - `nm -D libhsl.so` shows the 12 Ipopt symbols (7 MA97 + 5 MA57).
  - `ldd` resolves to the stack's `libmetis` and the flavor's math libraries only.
  - On MKL flavors, `check_mkl_linkage.sh` passes.
- [ ] ~~METIS shim: the MA97 and MA57 built-in examples reach the METIS path (not the MC47 fallback); check `info%ordering` / `INFO(36)`.~~
- [ ] ~~Ipopt end-to-end with no Ipopt rebuild: `hs071` with `linear_solver ma97`, `ma57` and `mumps`, all converging to the same optimum. Also `linear_solver ma86` must fail cleanly on a missing symbol.~~
- [ ] ~~dlopen search path: confirm that `libipopt`'s `RUNPATH` finds `%{prefix}/lib/libhsl.so` with no `hsllib` option (glibc `dlopen` searches the caller's `DT_RUNPATH`). On macOS, check the equivalent.~~
- [ ] ~~Leak checks after the build:~~
  - no `scls-*-hsl*.src.rpm` in `rpmbuild/SRPMS`
  - no `hsl` `.dsc` in `work/spkgs`
  - `scls-<flavor>` meta Requires has no hsl
  - a `stage_to_belfem.sh` dry run lists hsl under EXCLUDED
  - `git status` shows no tarball

## 7. Documentation

- [ ] ~~`doc/LICENSE_POLICY.md`: new section "Non-redistributable packages" covering what `distribution: private` means, the HSL licence clauses, and that the licensee owns the compliance decision.~~
- [ ] ~~`recipes/ipopt.yaml` comment and the Ipopt changelog: how to enable HSL (`linear_solver ma97`, `hsllib`), with no build change.~~
- [ ] ~~`CLAUDE.md`: one paragraph pointing to the policy, like the GKlib and MKL notes.~~
- [ ] ~~Devlog `dl2026MMDD_hsl_private_recipe.md` + index line.~~

## 8. Review gate (CLAUDE.md → `doc/AI_COLLABORATION_PROTOCOL.md`)

- [ ] ~~Christian decides D1–D4.~~
- [ ] ~~Two blind audits of this plan (Codex + Grok via `/cross-review`). Focus:~~
  - the METIS 4→5 shim semantics (`invperm`/`perm` order, the tiny-graph probes)
  - whether the `-bb` change fully prevents source leaks
  - the meta-package exclusion
  - the licence reading
- [ ] ~~Implement: B1, G1–G6, then the recipe, patch and manifest.~~
- [ ] ~~Two blind audits of the implementation, then adjust.~~
- [ ] ~~Commit messages name each option and guard and why. No bare "package updates".~~

**Blast radius:** `hsl` is a leaf; nothing depends on it at build time, and Ipopt is untouched.
The builder and staging changes are gated on `distribution: private` / `fetch: never`, and the
spec-diff gate in §6 proves that. B1 changes behaviour only for recipes listed in `extra_packages:`.
