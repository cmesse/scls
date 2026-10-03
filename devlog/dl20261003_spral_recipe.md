# Devlog 2026-10-03 — SPRAL recipe, `configure.type: meson`, Ipopt `--with-spral`

**Date:** 2026-10-01 → 2026-10-03
**Topic:** new `recipes/spral.yaml` (SPRAL 2025.09.18, BSD-3-Clause), the stack's first meson
build; Ipopt 3.14.20-1 links it. Plan: `todo/spral_recipe.md`.
**AIs involved:** Claude Opus (EL9 dev host); Codex gpt-5.6-terra and Grok 4.7 (round-1 blind
implementation audits, `tmp/ai_exchange/review_spral_meson.md`).
**Flavor / Host:** EL9 (Rocky 9) dev host, which has a CUDA toolkit in `/usr/local/cuda`; RPM.
**Verification:** `--spec-only` for every recipe × {gcc, mkl, debug, intel, gcc-mkl-cuda, lbl},
before and after this session's fixes: only `ipopt` and `spral` specs differ.
`validate_project.py`: 0 errors, 0 warnings. **Scratch RPM builds of spral for gcc and mkl
on EL9** with meson 1.12.1 from pip (`~/Applications/python`) and `rpmbuild --nodeps`, because a pip meson
does not satisfy `BuildRequires: meson` in rpmdb. These RPMs are evidence only, not for staging. A
shipping build needs the distro `meson`/`ninja-build` (CRB on EL9).

## Decisions (Christian)

- 2026-10-01: meson and ninja are acceptable as build-time-only host tools.
- 2026-10-02: D1(a) first-class `configure.type: meson`; D2 ship Ipopt 3.14.20-1 with SPRAL; D3
  link hwloc.
- 2026-10-03: approve all round-1 fixes below. Remove `spral_ssids` at install. Gate CUDA with a
  patch, not an environment override. lbl gets `Requires: hwloc-libs`.

## Round-1 findings and what was done

| finding | sev | fix |
|---|---|---|
| `-Dbinaries=false` exists on SPRAL master, not on tag `v2025.09.18`; `meson setup` aborts | P0 | option removed; tag always builds `spral_ssids`, `install.post` removes it |
| `libspral` links libcudart/libcublas whenever meson finds CUDA, even with `-Dgpu=false` (tag `meson.build:21,84-86`) | P0 | `patches/spral/spral_gpu_off_no_cuda.patch`: skip the nvcc and CUDA probes unless `gpu=true` |
| RPM autotools `configure.args` not expanded or quoted (`dl20260926_ipopt_recipe.md` F1) | P0 | `rpm_builder.get_direct_configure_command`: `check_args` + quote-if-space, keeping `%{prefix}`, `%{cuda}`, `%{host}` as RPM macros |
| unix test/install without build in the same run steps into `build/`, then `meson -C build` | P1 | `unix_builder.run`: no `build/` step for meson recipes |
| `-D*_link_args` replaces `LDFLAGS` (meson `environment.py`), losing the prefix RUNPATH on mkl, intel, gcc-mkl-cuda, debug | P1 | link args lead with `-L%{prefix}/lib -Wl,-rpath,%{prefix}/lib` |
| BSD `LICENCE` not installed | P1 | `install.post` into `share/licenses/spral/` |
| lbl: no runtime Requires on the system hwloc | P1 | `rpm_requires: lbl: [hwloc-libs]`; Debian map `hwloc-libs: libhwloc15` |
| `buildtype=plain` leaves asserts on | P2 | `-Db_ndebug=true` per flavor, `false` on debug |
| unversioned meson BuildRequires (needs ≥ 0.63.0) | P2 | `meson >= 0.63.0`; Debian map stays unversioned, since the dpkg-query host check takes bare names and every supported Ubuntu ships ≥ 1.3 |
| unix/deb meson install ignores `install.args` | P2 | passed through, as the spec template does |
| macOS meson/ninja prerequisite undocumented | P2 | `doc/MACOS_BUILD.md` |
| `O_level: 3` overrides debug `-Og`; recipe comment wrong | P2 | **comment fixed, `O_level` kept**: gcc/mkl/lbl/intel CFLAGS carry no `-O` level, so dropping it would build them at `-O0` (debug's carry `-Og`, which `O_level` overrides). Same as the other 105 `O_level` recipes. |

Not fixed, noted:
- `intel` renders `None` for `%{mklroot}` (`rpm_builder` derives `mkl_root` from the flavor name).
  This is pre-existing. With the F1 fix it now also shows in `scls-intel-ipopt.spec`. intel is
  source-build only.
- Ipopt `%check` runs hs071 with the default solver, so it never exercises SPRAL.
- The CBLAS-gated SSMFE tests are skipped (`cblas.h` is not on SPRAL's include path). Library
  content is unaffected.

## Blast radius

- Builder changes: no existing spec changes. The F1 fix keeps binutils' `--host=%{host}` as the RPM
  macro; expanding it would have changed the triplet from `x86_64-redhat-linux-gnu` to
  `x86_64-redhat-linux`.
- New package `spral` (group 5); `ipopt` (unreleased) gains it.

## Build evidence (2026-10-03, EL9, scratch)

- gcc and mkl: `meson test` 9 OK, 0 fail, with `OMP_CANCELLATION`/`OMP_PROC_BIND` set.
- The CUDA patch applies. Only the `*_nocuda` / `*_no_cuda` sources are compiled, and `libspral`
  has no CUDA NEEDED although `/usr/local/cuda` exists on the host.
- gcc `libspral.so` NEEDED: libgomp, libopenblas.so.0, libmetis.so.0, libhwloc.so.15, libgfortran,
  libstdc++, libm, libmvec, libgcc_s, libc. RPATH `/opt/scls/gcc/lib`. `ldd` resolves everything
  into the prefix.
- mkl `libspral.so` NEEDED: libmkl_gf_lp64.so.3, libmkl_gnu_thread.so.3, libmkl_core.so.3 (the
  flavor's model), libgomp, metis, hwloc. RPATH `/opt/scls/mkl/lib` plus the two MKL dirs.
- Payload: 10 headers, `lib/libspral.so`, `share/licenses/spral/LICENCE`. No `bin/spral_ssids`.
  `files/spral.txt` written from it, `rpm_files_auto` removed. Rebuilt on gcc and mkl with the manifest.
- SONAME is the unversioned `libspral.so` (upstream sets no soversion), as mumps already ships. A
  SPRAL bump therefore means rebuilding ipopt.

## Ipopt 3.14.20 with SPRAL (gcc, EL9, plain rpmbuild — no --nodeps)

- `scls-gcc-spral` (scratch build) installed; `rpm_builder --package ipopt --flavor gcc` succeeds.
- The F1 fix holds in the real `%build`: `'--with-lapack-lflags=…'`, `'--with-mumps-lflags=…'` and
  `'--with-spral-lflags=-L/opt/scls/gcc/lib -lspral'` each reach configure as one word.
- `config.h`: `IPOPT_HAS_MUMPS 1`, `IPOPT_HAS_SPRAL 1`, `IPOPT_HAS_PARDISO_MKL` undefined (as
  expected on OpenBLAS). `make test`: 7 × "Test passed!" (these use MUMPS).
- `libipopt.so.3` NEEDED: libspral, libdmumps, libmumps_common, libpord, libopenblas.so.0,
  libmpi.so.40, libstdc++, libm, libc, ld-linux, libgcc_s. RUNPATH `/opt/scls/gcc/lib`. `ldd`: one
  libmetis.so.0, everything from the prefix.
- hs071 (`test/hs071_cpp`, solver chosen through `ipopt.opt`):

  | solver | environment | result |
  |---|---|---|
  | mumps | — | 7 iterations, f* = 1.7014017031783709e+01, Optimal |
  | spral | `OMP_CANCELLATION=TRUE OMP_PROC_BIND=TRUE` | 7 iterations, same f* to all digits, Optimal |
  | spral | `OMP_CANCELLATION=TRUE` only | 7 iterations, Optimal |
  | spral | `OMP_PROC_BIND=TRUE` only | "Maybe one forgot … OMP_CANCELLATION" ×3, **Restoration Failed** after 1 iteration |
  | spral | neither | same failure |

  So a missing `OMP_CANCELLATION` is not a harmless warning: SSIDS's factorisation fails and Ipopt
  aborts. `OMP_PROC_BIND` only affects thread placement; this VM has `nproc` = 1, so its effect
  cannot be measured here.

- Independent check by the HSL session (scls-bb), against the *installed* `scls-gcc-ipopt`, from
  its own C-interface driver (`scripts/hsl/tests/ipopt_hs071.c`):
  - `linear_solver spral` without `OMP_CANCELLATION` → status -2 (Restoration_Failed).
  - With `OMP_CANCELLATION=TRUE` → status 0, same objective.
  - `LD_DEBUG` shows a single `libmetis.so.0` (`/opt/scls/gcc/lib`) shared by libipopt, libdmumps
    and libspral.

## Ipopt 3.14.20 on mkl (EL9, plain rpmbuild)

- `scls-gcc-ipopt` and `scls-mkl-spral` installed by Christian. The HSL session (scls-bb) was told,
  so it can re-run its hsllib check against the installed library.
- mkl build succeeds. `config.h`: `IPOPT_HAS_MUMPS 1`, `IPOPT_HAS_PARDISO_MKL 1`,
  `IPOPT_HAS_SPRAL 1`. `make test`: 7 passed. The new `%check` hs071 run with spral reports spral
  and an optimal solution.
- `libipopt` NEEDED: libspral, dmumps, mumps_common, pord, mkl_gf_lp64, mkl_gnu_thread, mkl_core,
  libgomp, libmpi, plus the C/C++ runtime.
- hs071 with `linear_solver pardisomkl`: optimal, f* = 1.7014017031783709e+01.
- `check_mkl_linkage.sh --dir` over the new `scls-mkl-{spral,ipopt}` RPMs: PASS (3 ELF files,
  only `libmkl_gnu_thread`).
- `check_mkl_linkage.sh --prefix /opt/scls/mkl`: **FAIL, pre-existing and not caused by this
  work.** The host has `scls-mkl-scalapack-2.2.3-2` (links `libmkl_sequential`) and
  `scls-mkl-armadillo-15.4.2-1` (links `libmkl_rt`). The recipes already fix both (scalapack -4,
  armadillo 15.6.0-2); the installed RPMs are stale. Until they are reinstalled, mkl Ipopt on
  this host loads the old ScaLAPACK through MUMPS.

## Decisions after the hs071 result (Christian, 2026-10-03)

- `templates/scls-activate.sh.j2` exports `OMP_CANCELLATION=TRUE` when
  `share/scls/registry/spral.yaml` exists and the variable is unset. A shell-local marker
  `_SCLS_SET_OMP_CANCELLATION` lets `deactivate` remove only its own value. `scls env` lists the
  variable. `OMP_PROC_BIND` is not set. Environment release 2 → 3.
  Tested by sourcing the rendered scripts in bash and zsh, with spral absent, with spral present,
  and with a user value `FALSE`; all three behave as intended.
- `recipes/ipopt.yaml` `%check` also runs `test/hs071_cpp` with `linear_solver spral` and
  `OMP_CANCELLATION=TRUE`. It passes in the gcc rpmbuild, and the same command returns 1 without
  the variable.

## Install path: Intel's oneAPI repo gated by flavor (Christian, 2026-10-03)

`dnf install` of a local .rpm still refreshes every enabled repo. On this host the `oneAPI` repo
(`repo_gpgcheck=1`) asks to import Intel's rotated metadata key `0x53D04109`, which is missing from
the root repo keyring (last written 2023). So any install can fail on a repo it does not use.
`rpm_builder._dnf_install_rpms` and `scls.py _install_rpm` now pass `--disablerepo=<id>` for every
repo whose URL is on `yum.repos.intel.com`, unless the flavor has `math.linalg: mkl` or Intel
compilers. On: mkl, intel, gcc-mkl-cuda. Off: gcc, debug, lbl, macos. The ids come from the .repo
files' URLs, not a hard-coded name. Install-time only: no spec or package content changes.
Not yet verified on the MKL flavors whether `sudo dnf -y` imports the key by itself.

## Round-2 review and fixes (2026-10-03)

The review is in `tmp/ai_exchange/review_spral_round2.md`: Codex gpt-5.6-terra xhigh and Grok 4.7
xhigh, jury, on the scoped diff. `origin/devel` was merged into `ipopt` (`9aac449`) before
verification. No P0. Fixes approved by Christian and applied:

- **intel `%{mklroot}` → "None" (P1, Codex + Grok).** `RPMBuilder.mkl_root` is now set when
  `math.linalg == 'mkl'` *or* the name contains "mkl" (a superset, so the mkl and gcc-mkl-cuda specs
  are unchanged).
  - 16 intel specs besides spral/ipopt change: `None/…` and literal `-I%{mklroot}/include` become the real MKL path.
  - `scls-intel-armadillo.spec` now generates; it used to crash on `replace('%{mklroot}', None)`.
  - No spec anywhere contains `None/`. No non-intel spec outside spral/ipopt changed.
  - The env exports at `rpm_builder.py` ~:860/:1487 remain name-gated; intel gets MKL from
    `setvars.sh`.
- **macOS headerpad (P1, Claude).** spral link args are now `%{ldflags} %{math_ldflags}`, the
  flavor's whole LDFLAGS. On the unix/deb builders `%{ldflags}` already ends with the math line, so
  it appears twice there, which is harmless.
- **P2s:**
  - The hwloc comment now says `required: false`, with a log check to run.
  - Ipopt's SPRAL `%check` removes its temp dir and ends in `test $ok -eq 0` rather than `exit`.
  - `_intel_oneapi_repo_ids` skips unreadable or non-UTF-8 `.repo` files.
  - Devlog wording on `-O` corrected.
- **Gate:**
  - `--spec-only` for all recipes × 6 flavors; `validate_project` passes.
  - Rebuilt spral gcc (9/9 tests, `Library hwloc found: YES`, RPATH `/opt/scls/gcc/lib`; scratch
    `--nodeps`).
  - Rebuilt ipopt gcc (7 tests plus the SPRAL check, temp dir removed; plain rpmbuild).
- **Open:**
  - `OMP_PROC_BIND` needs a multi-core run, and the activate policy is Christian's call.
  - deactivate clobbers a value the user changed after activation (P2, accepted for now).
  - unix/deb ignore `configure.flavor_pre/post` for all configure types (pre-existing; e.g.
    openmpi's gcc-mkl-cuda CUDA check never runs on .deb). To track separately.

## Round-3 review (2026-10-03)

`tmp/ai_exchange/review_spral_round3.md`: Codex gpt-5.6-terra xhigh and Grok 4.7 xhigh, on the four
fixes only. No P0; all three reviewers confirm the fixes. Found pre-existing and outside this change:
- unix/deb set the MKL environment only for flavor names containing "mkl"
  (`build_common.py:1044`), so an intel unix/deb build gets no MKLROOT/CPATH.
- On intel, the spec bakes the MKL path at generation time while `%build` sources setvars.sh;
  the two can diverge.
- The new `except OSError` is unreachable (`ConfigParser.read` already swallows it); only the
  UnicodeDecodeError catch matters.
Both pre-existing items go to `todo/spral_recipe.md` follow-ups with the `configure.flavor_pre/post`
gap. Post-fix gcc `readelf`: NEEDED libopenblas.so.0, libmetis.so.0, libhwloc.so.15; RPATH
/opt/scls/gcc/lib; no CUDA.

## Pending

- [x] Install spral (gcc, mkl) and ipopt (gcc).
- [x] Ipopt gcc build, `ldd libipopt.so`, hs071 with `linear_solver spral`.
- [x] Ipopt mkl, `IPOPT_HAS_PARDISO_MKL`, check_mkl_linkage on the new RPMs.
- [ ] Reinstall current `scls-mkl-scalapack` (-4) and `scls-mkl-armadillo` (15.6.0-2) on this host.
- [ ] Rebuild and install `environment` 2026-3 per flavor.
- [ ] Shipping builds with distro meson; debug, lbl, U24/U26 .deb, macOS.
- [ ] Round-2 blind audits of the combined diff.
