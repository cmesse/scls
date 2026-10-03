# Plan — `scripts/build_libhsl.py`: a private libhsl for Ipopt's runtime loader

**Status:** plan, awaiting the review gate (§7). Supersedes `todo/hsl_private_recipe.md`, the
packaged-recipe design. No file under `recipes/`, `python/`, `scripts/`, `patches/` or `files/`
has been edited.
**Branch:** `ipopt`. **Date:** 2026-10-01.

## 0. Revision 2026-10-03 — source is Coin-HSL, script implemented

Christian added `coinhsl-2024.05.15.tar.gz` (plus standalone `hsl_ma77-6.5.0`, `hsl_ma86-1.7.4`
and `hsl_mc68-3.3.3`) to `tmp/HSL/`. Coin-HSL replaces the GALAHAD subset as the source. §2 and
§4 below describe the superseded GALAHAD design and are kept for the record.

Why Coin-HSL:
- **Exactly Ipopt's set:** MA27, MA28, MA57, MC19, HSL_MA77, HSL_MA86, HSL_MA97, HSL_MC68. About 30 plain `.f`/`.f90` files, with no preprocessing or templating.
- **No bundled METIS.** It has only its METIS 5 adapter (`metis/metis5_adapter.c`, `metis5.f90`) against an external `libmetis`, so the stack's METIS is used with no edit of any HSL file.
- **HSL_MC68 is already inside.** It ships in `common/deps90.f90`; `hsl_mc68/meson.build` keeps its own `files()` line commented out for that reason. The standalone `hsl_mc68` tarball is not needed.

Implemented: `scripts/build_libhsl.py`.
- Reads the bundle's `meson.build` files as a manifest (comments stripped) and orders Fortran modules by `module`/`use` scan.
- Compiles with the flavor's compilers and flags, plus `-fallow-argument-mismatch` on gfortran ≥ 10, as upstream does.
- Links `libcoinhsl.so` against the stack's `libmetis` and the flavor math line with `--no-as-needed`, then installs it with a `libhsl.so` symlink and `share/doc/hsl/LICENCE`.
- Refuses build or install directories inside the work tree.
- `.gitignore` blocks HSL tarball, tree and library names anywhere in the repo.

Gates run 2026-10-03 on this EL9 host (gfortran 11), installing to a scratch prefix:
- [x] `gcc`:
  - all 41 Ipopt loader symbols defined
  - no `METIS_*` defined; `METIS_NodeND` and `METIS_SetDefaultOptions` are undefined and resolve to `/opt/scls/gcc/lib/libmetis.so.0`
  - the dlopen smoke test passes
  - `NEEDED`: libmetis, libopenblas, libgomp, libgfortran, libm, libgcc_s, libquadmath, libc
  - `RPATH /opt/scls/gcc/lib`
- [x] `mkl`: the same checks pass; `NEEDED` has `libmkl_gf_lp64`, `libmkl_gnu_thread`, `libmkl_core`, libgomp; `check_mkl_linkage.sh`: "PASS — mkl is self-consistent".
- [ ] `debug`, `macos`, `intel` not run.
- [ ] Ipopt end-to-end (`hs071` with `hsllib` and `linear_solver ma97`/`ma57`/`ma86`/`ma77`/`ma27`): needs an installed Ipopt; pending.

Version comparison, Coin-HSL 2024.05.15 vs the standalone tarballs. Code compared with comment lines stripped; versions from Coin-HSL's `ChangeLog`.

| Package | In Coin-HSL | Standalone | Code difference |
|---|---|---|---|
| HSL_MA97 | 2.8.1 | 2.8.1 | none |
| MA57 | 3.11.3 | 3.11.3 | none beyond the METIS call renamed to Coin-HSL's adapter (`hsl_metis`) |
| HSL_MA86 | 1.7.4 | 1.7.4 | module-name case only |
| HSL_MC68 | 3.3.3 | 3.3.3 | (same version) |
| HSL_MA77 | 6.4.0 | **6.5.0** | one real fix: the `input_reals` routine, when the previous factorization was singular or not positive definite |

- [ ] Decide whether the script should overlay HSL_MA77 6.5.0 (`hsl_ma77d.f90`; the C interface is unchanged) when that tarball is present. MA77 is Ipopt's out-of-core solver and is rarely selected.

## 1. Decisions taken (Christian, 2026-09-30 / 10-01)

- [x] HSL is handled completely independently of Ipopt and of the package system. It is a
  standalone build script, not a recipe: no RPM, .deb, SRPM, meta-package entry, staging or registry.
- [x] `recipes/ipopt.yaml` is unchanged. Upstream Ipopt 3.14.20 facts:
  - It already loads HSL at runtime (`--without-hsl`, loader on).
  - The default library name is `libhsl.<shlibext>` (`src/Algorithm/IpAlgBuilder.cpp:303-308`).
  - Solvers resolve their symbols lazily, only when selected.
  - The default `linear_solver` stays `mumps`, because linked solvers win (`:207-252`).
- [x] Coin-HSL is not needed. `hsl-galahadd-5.20000.0.tar.gz` (the GALAHAD HSL subset) covers
  every routine Ipopt's loader can use. The standalone `ma57-3.11.3`, `hsl_ma57-5.3.2` and
  `hsl_ma97-2.8.1` tarballs are not used.
- [x] MA27 is not required. It is in the subset anyway, so it comes along for free.
- [x] **One METIS only: the stack's** (`/opt/scls/<flavor>/lib/libmetis.so`, 5.2.1). The subset's
  bundled METIS copy is not compiled.
- [x] **No meson.** We write our own build (Christian, 2026-10-01). The subset's `meson.build`
  files are read only as a source manifest, never executed and never edited.
- [x] **Licence reading confirmed by Christian (2026-10-01):** building with our own METIS and our
  own build script is fine. The one hard constraint is that the sources (and anything built from
  them) are never shared.

## 2. Source facts (from the tarball, 2026-10-01)

- **Upstream build system.** Meson (`hsl_subset/meson.build`, project `hsl_subset` 1.1.0). It
  builds one shared library, `libhsl_subset.so`, with single and double precision. We do not use
  it (§1); §4 reproduces what it does.
- **Symbols match Ipopt with 32-bit integers.** The `_64` renames apply only under
  `INTEGER_64` (`include/hsl_subset_double.h`, `include/hsl_subset_ciface_double.h`):

  | Ipopt solver | Symbols exported by the subset |
  |---|---|
  | MA97 | `ma97_*_d` |
  | MA86 | `ma86_*_d` |
  | MA77 | `ma77_*_d` |
  | MC68 (ordering) | `mc68_order_i`, `mc68_default_control_i` |
  | MA57 | `ma57{a,b,c,e,i}d` |
  | MA27 | `ma27{a,b,c,i}d` |
  | MC19 (scaling) | `mc19ad` |

  - The C-interface files are in the build (`src/hsl_ma97/meson.build:1` and the equivalents for MA86, MA77 and MC68).
- **What the subset needs from METIS:**
  - Only `METIS_SetDefaultOptions` and `METIS_NodeND`, both called from COIN-OR's adapter `src/hsl_metis/hsl_metis5_adapter.c:32,76-78` (EPL). The Fortran side calls `hsl_metis`, which binds to the adapter (`src/hsl_metis/hsl_metis.f90:25`).
  - The adapter already handles MA57's 1-vertex self-loop probe (`:21-29`).
  - The adapter includes the subset's own `include/hsl_metis.h`: `METIS_NOPTIONS 40`, `IDXTYPEWIDTH 32`.
  - The stack's `metis.h` has `METIS_NOPTIONS 40` and `IDXTYPEWIDTH 32` too, so the ABI matches. `REALTYPEWIDTH` differs (32 vs 64), but `real_t` does not appear in `METIS_NodeND` or `METIS_SetDefaultOptions`. An auditor should confirm that.
- **Where the bundled METIS comes in.** Two places only:
  - `meson.build:167`: `subdir('src/metis')` adds about 45 C files to `libhsl_subset_c_src`.
  - `meson.build:93`: `'src/metis/include'` in `hsl_subset_include`.
- **Why the bundled copy cannot stay** (moot without meson, but it is why §4 skips `src/metis`). In the 32-bit build its symbols keep their normal names
  (renames apply only under `INTEGER_64`). They would collide with the stack's `libmetis.so`,
  which also absorbs GKlib, in any process that loads Ipopt + MUMPS. That rules out both copies.
- **OpenMP.** Fortran is built with `-fopenmp` (`meson.build:38`). MA97 and MA86 are parallel.
- **BLAS/LAPACK.** `libblas` and `liblapack` are single library names resolved with
  `fc.find_library` (`meson.build:25-26`).

## 3. Licence

The HSL Academic Licence 2.0 grants personal use (§2.1) and forbids distributing it or sharing
its use, even within the same institution (§2.1.2), and commercial use (§2.1.3). Christian has
confirmed that our own build against our own METIS is acceptable (§1). The constraint we enforce
is **never share**:
- **Personal install.** The default prefix is per-user (`~/.local/scls-hsl/<flavor>`), never `/opt/scls`. An explicit `--prefix` is the licensee's decision.
- **No copies in the repo.** The tarball stays wherever the licensee keeps it. The script unpacks into a scratch build directory outside the git work tree, and refuses a `--sources` or build dir inside it. A `.gitignore` guard (§5) blocks the tarball names as a second line of defence.
- **Nothing to stage.** The script produces no package, so nothing can reach belfem.
- **Auditors see no HSL source.** Codex and Grok review our script and the plan. Facts about HSL files stay as `file:line` citations and symbol names, never pasted source, in `tmp/ai_exchange/` or anywhere tracked.
- **The licence travels with the library.** `share/doc/hsl/LICENCE` is installed next to it.

## 4. Script design — `scripts/build_libhsl.py` (no meson)

Python, so it reuses the stack's own flavor logic instead of a second, hand-written copy.

What meson did that we must reproduce (`hsl_subset/meson.build:33-80,174-229`):
- **Preprocess every Fortran source** with `$FC -cpp -E -I include` into a `double_<name>`
  copy, then compile it. The single-precision pass adds `-DREAL_32`; we skip that pass, because
  Ipopt uses double only.
- **Source lists:**
  - Real-kind sources come from `libhsl_subset_src` (`.f90`) and `libhsl_subset_f_src` (`.f`). We take their double variants only.
  - Kind-independent sources (`*_multi_src`, e.g. `hsl_kinds.f90`, `hsl_mc68i.f90`, `hsl_metis.f90`) are compiled once.
  - C sources (`libhsl_subset_c_src`): only `src/hsl_metis/hsl_metis5_adapter.c` once METIS is excluded.
- **Fortran flags:** `-fopenmp` on Fortran compile and link (`:37-39`).
- **Skip** `src/metis`, and `src/blas` / `src/lapack`, which are only for quadruple precision (`:200-206`).

Steps:
1. **Inputs:**
   - `--sources DIR`: holds `hsl-galahadd-*.tar.gz`; must exist, and nothing is downloaded.
   - `--prefix DIR`: default `~/.local/scls-hsl/<flavor>`.
   - `--flavor`: default from `flavor.conf`.
   - `--build-dir`: default under `$TMPDIR`, never inside the repo.
   - `--keep-build`.
2. **Environment** from the flavor (`flavors/<f>.yaml` via the existing loaders): `CC`, `FC`,
   optimisation flags, and the math line from `math_common.get_math_link_line()`. On MKL flavors
   that line carries the flavor's single threading layer, never `libmkl_rt`
   (`doc/MKL_ABI_POLICY.md`, "Threading-layer uniformity"). meson's single-name `find_library`
   problem (old O1) disappears: we pass the flavor's link line as is.
3. **Source manifest.** Parse `src/*/meson.build` for `libhsl_subset_{src,f_src,multi_src,f_multi_src,c_src} += files(...)`. Exclude `src/metis`, `src/blas`, `src/lapack` and `metis_nodend_dummy.c`.
   - This takes the file list from upstream, not from a list we maintain by hand. A future subset release that adds or renames a file then builds without a script change.
   - Abort if the parse finds an unexpected construct, e.g. a conditional `files()` we don't understand.
   - Open item **O2**: whether to compile everything (simple, and dead code is harmless in a shared library), or only the dependency closure of the Ipopt solvers (smaller). Recommendation: everything.
4. **Compile order.** Fortran modules must be compiled before the files that `use` them. Scan the preprocessed sources for `module X` / `use X`, topologically sort them, and abort on a cycle or on a `use` of an unknown module other than intrinsics (`iso_c_binding`, `omp_lib`, …). Build with a process pool, wave by wave.
5. **Compile flags:** `-fPIC -O2 -fopenmp`, plus the flavor's Fortran optimisation flags (to be checked: the flavor's `-O3`/`-march` settings for HSL), `-J <moddir>`. The adapter C file gets `-I include` only. It must see the subset's `hsl_metis.h` *or* the stack's `metis.h`, not both; see the audit question in §2.
6. **Link:**
   - Linux: `$FC -shared -fopenmp -Wl,-soname,libhsl.so.1 -o libhsl.so.1 *.o -L<stack>/lib -Wl,-rpath,<stack>/lib -lmetis <math line>`, plus a version script exporting only the Fortran/C API names, so no compiler or METIS internals leak.
   - macOS: `-dynamiclib -install_name <prefix>/lib/libhsl.1.dylib`, the same libraries, and an exported-symbols list.
   - Create the `libhsl.so` / `libhsl.dylib` symlink, the name Ipopt dlopens by default.
7. **Self-check before reporting success:**
   - `nm -D` shows every Ipopt symbol in §2.
   - `nm -D` shows no `METIS_*`, `gk_*` or `libmetis__*` definitions.
   - `ldd` / `otool -L` resolves `libmetis` to the stack's copy and the math libraries to the flavor's.
   - On MKL flavors, run `scripts/check_mkl_linkage.sh`.
   - Compile and run a tiny C smoke test that `dlopen`s the library and calls `ma97_default_control_d` and `mc68_default_control_i`.
8. **Record provenance** in `<prefix>/share/hsl/build-info.yaml`: subset version, flavor,
   compiler, and the SONAMEs of libmetis and the math libraries it linked. A METIS or MKL major
   bump is then visible, since nothing rebuilds libhsl automatically.
9. **Final output:** the line to put in `ipopt.opt` (`hsllib <prefix>/lib/libhsl.so`) and a one-line `linear_solver ma97` hint.

## 5. Repository changes

- [ ] `scripts/build_libhsl.py` (new). This is not a build-configuration file under CLAUDE.md's list, but it goes through the review gate because it is the whole HSL build: manifest parsing, module ordering, link line and export list.
- [ ] `.gitignore`: block the HSL tarball names anywhere in the tree: `hsl-galahad*`, `hsl_ma*`, `ma57-*`, `coinhsl*`, and any unpacked `hsl_subset/`.
- [ ] `doc/LICENSE_POLICY.md`: a short "HSL (licensee-built, never distributed)" section.
- [ ] Ipopt docs: a comment in `recipes/ipopt.yaml` next to `--without-hsl` pointing at the script, plus the Ipopt changelog. That comment is the only `recipes/` touch, and it is comment-only.
- [ ] `CLAUDE.md`: a one-paragraph pointer, like the GKlib and MKL notes.
- [ ] Devlog + index line.

Not needed any more, compared with the packaged design:
- the `distribution: private` flag
- `-bb` instead of `-ba`
- `META_EXCLUDED`
- the staging guard
- `source.fetch: never`

The B1/B2 bugs remain in `todo/extra_packages_unix_deb_override.md`, independent of HSL.

## 6. Verification (Linux build host, then macOS)

- [ ] Run the script on `gcc` (OpenBLAS) and `mkl`. §4 step 6's self-check must pass on both.
- [ ] Ipopt `hs071` with `hsllib` set, using `linear_solver` = `ma97`, `ma57`, `ma86`, `ma77`, `ma27` and `mumps`. All must reach the same optimum. Check that MA57/MA97 report METIS ordering, not the MC47/AMD fallback.
- [ ] The same run with no `hsllib`, after installing to `--prefix /opt/scls/<flavor>` on a throwaway host only. This confirms that `libipopt`'s RUNPATH lets `dlopen` find `libhsl.so` by default.
- [ ] A process that loads Ipopt + MUMPS + libhsl: `LD_DEBUG=bindings` shows `METIS_NodeND` bound to the stack's `libmetis.so.0` only.
- [ ] `git status` is clean after a run, with no tarball or build tree in the repo.

## 7. Review gate

- [ ] Two blind audits of this plan (Codex + Grok, `/cross-review`). Focus:
  - the METIS ABI claim (`REALTYPEWIDTH` mismatch, `METIS_NOPTIONS`)
  - the manifest parser (§4.3), and whether compiling everything is safe (O2)
  - Fortran module ordering (§4.4)
  - the export list and version script (§4.6)
  - the "never share" guards (§3), including that audit prompts carry no HSL source
- [ ] Implement.
- [ ] Two blind audits of the script, then adjust.
- [ ] Commit message names what changed and why.
