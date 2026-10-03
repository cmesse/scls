# Plan — HSL source selection (Coin-HSL vs standalone) and a private provenance bundle

> **AUDITOR INSTRUCTION — read first.** HSL is proprietary, under the STFC HSL Academic
> Licence 2.0. Do **not** open, list, extract, or quote anything under `tmp/HSL/`, any
> `coinhsl-*`, `hsl_*`, `hsl-galahad*` or `ma57-*` archive or tree, or any `libcoinhsl` /
> `libhsl` binary, wherever it is on this machine. Everything you need about HSL is stated
> below as file names, version numbers, module names and exported symbol names. Audit this
> plan and `scripts/build_libhsl.py` only. Reading HSL content would send it to a third party,
> which the licence forbids.

**Status (2026-10-03):** reviewed (round 1, `tmp/ai_exchange/review_libhsl_plan.md`), decisions D2–D4 taken, **§9 implemented** and gated on gcc + mkl; see `devlog/dl20261003_libhsl_private_build.md`. Implementation review round pending.
**Branch:** `ipopt`. **Date:** 2026-10-03.
**Builds on:** `todo/libhsl_build_script.md` §0, where the Coin-HSL-based script is implemented and gated on `gcc` and `mkl`.

## 0. Decision (Christian, 2026-10-03, after this plan went to review)

- [x] Keep the **original tarballs**; no repacked "SCLS tarball" of HSL sources. §4 (bundle) is
  superseded. Its provenance and licence parts move into the assembly step below.
- [x] A **bash script** extracts the original tarballs and assembles **one target source
  directory** before compilation: Coin-HSL as the base, plus any verified standalone override
  (§3, today HSL_MA77 6.5.0).
- [x] CMake (§4b) compiles the assembled tree.
- [x] Only SCLS's scripts are shareable. HSL sources and binaries are never shared, so the
  scripts carry no licence issue.
- [ ] ~~HSL tarballs are kept outside the work tree (pre-registration P1, auditor hygiene).~~
  Christian, 2026-10-03: not needed. `tmp/` is git-ignored, and the auditors have full disk
  access regardless of where the tarballs sit, so moving them buys nothing. Sources stay in
  `tmp/HSL/`. The guard that matters stays in place: `.gitignore` blocks HSL names everywhere.
  So does the rule that no HSL content goes into anything tracked or into audit prompts.

Resulting layout (all public SCLS code, no HSL content):
- `scripts/hsl/assemble_sources.sh <tarball-dir> <target-dir>`:
  - SHA-256 of every input
  - extract Coin-HSL
  - per override: version compare, `must_match` byte checks, dependency-identity checks, then copy the replacement files
  - copy every package's `LICENCE` to `<target>/LICENCES/LICENCE.<package>-<version>`
  - write `<target>/PROVENANCE.txt` (inputs, SHA-256, versions, files replaced and why)
  - refuses any target inside the work tree
- `scripts/hsl/CMakeLists.txt`: builds `libcoinhsl` from `<target>`, the stack's METIS, and the given math line.
- `scripts/build_libhsl.py` becomes the flavor-aware driver:
  - runs the assembly script
  - configures CMake with the flavor's compilers, flags and math line
  - self-check
  - install, including `LICENCES/` and `PROVENANCE.txt` under `share/doc/hsl/`

## 1. What Christian asked for (2026-10-03)

1. Use HSL_MA77 **6.5.0** (standalone) instead of Coin-HSL's 6.4.0.
2. Consider preferring the standalone package sources over the Coin-HSL copies in general.
3. Produce "our own tarball with our SCLS-specific build script and the sources that we used",
   with the licence files provided correctly.

## 2. Facts established (Claude, 2026-10-03, by reading the archives locally)

Inputs in `tmp/HSL/` (git-ignored):
- `coinhsl-2024.05.15`
- standalone `hsl_ma77-6.5.0`, `hsl_ma86-1.7.4`, `hsl_ma97-2.8.1`, `hsl_mc68-3.3.3`, `ma57-3.11.3`, `hsl_ma57-5.3.2`
- `hsl-galahadd-5.20000.0`, which is no longer used

**Licence texts**
- Every standalone tarball carries the same `LICENCE`: the full *HSL Academic Licence 2.0* text, 225 lines, identical SHA-256 across all six.
- Coin-HSL carries a 5-line notice: use and distribution are permitted only under a licence obtained via the STFC licensing portal, on its terms.

**Versions.** From Coin-HSL's `ChangeLog` (newest entry 2024-05-15) against the standalone tarball names. Code compared after stripping comments and whitespace:

| Package | Coin-HSL | Standalone | Code difference |
|---|---|---|---|
| HSL_MA97 | 2.8.1 | 2.8.1 | none |
| HSL_MA86 | 1.7.4 | 1.7.4 | module-name letter case only |
| HSL_MC68 | 3.3.3 | 3.3.3 | same version; inside Coin-HSL it lives in `common/deps90.f90` |
| MA57 | 3.11.3 | 3.11.3 | Coin-HSL calls its own METIS adapter `hsl_metis`; the standalone calls METIS 4's `METIS_NODEND` |
| HSL_MA77 | 6.4.0 | **6.5.0** | a newer release (one bug fix) |
| MA27, MA28, MC19 | in Coin-HSL | no standalone tarball here | — |

**HSL_MA77 6.5.0 as a drop-in for Coin-HSL's copy:**
- Its C interface files (`hsl_ma77{d,s}_ciface.f90`) and headers (`hsl_ma77{d,s}.h`) are byte-identical to Coin-HSL's.
- It `use`s eight modules: eight dependency modules. All eight are in Coin-HSL's `common/deps90.f90`, and the assembler verifies them against Coin-HSL.
- Only `hsl_ma77d.f90` and `hsl_ma77s.f90` change.

## 3. Source selection — options

**A (recommended): Coin-HSL is the base; a standalone package replaces Coin-HSL's files only when it is strictly newer and passes drop-in checks.**
- Coin-HSL is one dependency set that STFC assembled and tested together for Ipopt.
- It is the only source of MA27, MA28 and MC19 here.
- Its MA57 is the one wired to the METIS 5 adapter.

**B (rejected): standalone first, Coin-HSL as fallback.**
- MA57: the standalone calls `METIS_NODEND` (METIS 4 ABI). Using it would bring back our own METIS 4→5 shim, which Coin-HSL's adapter exists to avoid.
- MA27, MA28 and MC19 would still come from Coin-HSL, so two dependency sets would be merged. Each standalone ships its own copies of shared routines (`common.f`, `*deps*.f90`), which must then be de-duplicated, as found for the GALAHAD-era plan (20 duplicate F77 routines between ma57 and ma97).
- For equal versions there is no code gain (table above).

### Override rules (option A)

An override table in the script is keyed by package. Each entry has:
- the standalone tarball glob
- `replace`: standalone path → Coin-HSL path
- `must_match`: C interface and headers, which must already be identical
- the standalone dependency files whose modules must match Coin-HSL's

An override is applied only if all of the following hold. Otherwise the build stops with an explanation, never silently.
1. **Version.** The standalone version, parsed from the tarball name `hsl_xxNN-X.Y.Z`, is strictly newer than the version Coin-HSL's `ChangeLog` records. The ChangeLog is parsed for the newest `HSL_XXNN vA -> vB` or `HSL_XXNN vB` line. Equal → use Coin-HSL. Older → ignore and print a note. Unparseable → stop.
2. **Interface.** Every `must_match` file is byte-identical. A changed C interface or header is an ABI change for Ipopt's loader (Ipopt carries its own copies of these headers), so it needs a human look.
3. **Dependencies.** Every Fortran module that the replacement files `use` and that the standalone also ships in its own dependency files is code-identical (comments and whitespace stripped) to the module of the same name in Coin-HSL's `common/deps90.f90`. A newer dependency would otherwise be silently replaced by Coin-HSL's older one.
4. **Post-build.** The existing self-check passes: all 41 Ipopt loader symbols, no METIS definitions, `libmetis` from the stack, the dlopen smoke test, and on MKL flavors `check_mkl_linkage.sh`.

Table entries: HSL_MA77, HSL_MA86, HSL_MA97, which are pure F90 modules plus C interfaces. Not in the table:
- **MA57**: METIS ABI differs (above).
- **HSL_MC68**: no separate file in Coin-HSL.

Today this yields exactly one override, HSL_MA77 6.5.0. MA86 and MA97 are equal, so Coin-HSL's copies are used.

**Open question O1 (to auditors).** Is an extra functional gate needed for an override, e.g. compiling and running the standalone package's own `example/` against the built library? Today that only exists for MA77, MA86 and MA97, and it would run HSL's example programs locally only.

## 4. ~~Private bundle ("our own tarball")~~ — superseded by §0 (original tarballs + assembly script)

Proposed flag: `--bundle DIR` writes `scls-hsl-<coinhsl-version>[+hsl_ma77-6.5.0].tar.gz` containing:
- the **original, unmodified** input tarballs that were actually used: Coin-HSL plus each applied override. They are not repacked or merged, so every package keeps its own `LICENCE`, `README` and `ChangeLog` in place.
- `LICENCES/`: one copy of each distinct licence text, named by source (`LICENCE.coinhsl-2024.05.15`, `LICENCE.hsl_ma77-6.5.0`), so the terms are visible without unpacking.
- `build_libhsl.py` at the version used, plus its git commit hash.
- `PROVENANCE.yaml`: for each input, its name, version and SHA-256; which Coin-HSL files each override replaced and why; and the gate results.
- `README-PERSONAL-USE.txt`: who may use it (the licensee only, per HSL Academic Licence 2.0 §2.1), that it must not be shared even within the same institution (§2.1.2), and how to rebuild.

Further rules:
- **Rebuild from a bundle:** `build_libhsl.py --sources <unpacked bundle>`. The script verifies every SHA-256 against `PROVENANCE.yaml` before building.
- **Location:** default `~/.local/scls-hsl/bundles/`. A path inside the work tree is refused, as for `--prefix` and `--build-dir`. `.gitignore` already blocks HSL names anywhere in the tree.

**Licence decision D1 — Christian's, not a vote.** The academic licence permits copies only as "a reasonable number of back-up copies" (§2.1.4) and forbids sharing (§2.1.2). The bundle is a personal backup copy of unmodified tarballs plus SCLS's own script and metadata. It is never staged, never committed, and never given to anyone, including other LBL staff, each of whom needs their own licence. Whether that reading holds is for Christian (or LBNL licensing) to confirm.

**Alternative to the bundle:** the script records SHA-256 and versions of its inputs in `share/hsl/build-info.yaml` and keeps the user's original tarballs where they are. This needs no new archive. The cost is that reproducibility depends on the user keeping those originals.

## 4b. Build backend: our own CMakeLists.txt (Christian, 2026-10-03)

Proposal: replace the script's hand-written compile and link stage with an SCLS-owned
`scripts/hsl/CMakeLists.txt`. It is public: our code only, with no HSL content.

**The Python driver keeps everything that is SCLS- or licence-specific:**
- locating and verifying inputs (SHA-256)
- source selection and overrides (§3)
- unpacking into a scratch tree outside the work tree
- the bundle (§4)
- the self-check
- provenance

**CMake does the build:**
- **Fortran module ordering.** CMake scans `module`/`use` itself, so the script's regex scanner (`fortran_waves`) goes away.
- **OpenMP.** `find_package(OpenMP)` for Fortran and C, giving the flavor compiler's runtime (`-fopenmp` / `-qopenmp`).
- **BLAS/LAPACK.** Taken as given, not discovered:
  - the driver passes the flavor's `%{math_ldflags}` line, already validated by `math_common` and the MKL threading-layer policy
  - CMake's `FindBLAS` is not used, because it could pick a different MKL layer or a system `/usr/lib64` BLAS
  - Open question O2: whether to reuse `build_common.get_cmake_args` (and its `CMAKE_<LANG>_STANDARD_LIBRARIES` handling) for exactly this, rather than a parallel path.
- **METIS.** `find_library(metis PATHS <stack>/lib NO_DEFAULT_PATH)` and `metis.h` from `<stack>/include`. One METIS, the stack's.
- **Targets**, "all libraries in one go":
  - one shared `coinhsl` target with `OUTPUT_NAME coinhsl` (Ipopt dlopens `libhsl` → symlink)
  - Open question O3: also emit per-package shared libraries (`libhsl_ma97.so`, …) for direct non-Ipopt use? Ipopt itself needs only the one library. Per-package libraries would duplicate the shared dependency routines across libraries.
- **RPATH and install name.** `INSTALL_RPATH <stack>/lib` plus the MKL lib dir on MKL flavors, `--no-as-needed` on Linux (SCLS link policy), and `INSTALL_NAME_DIR` on macOS. That replaces the hand-built link line.
- **Compile flags.** The flavor's `cflags` and `fflags` (via `CMAKE_<LANG>_FLAGS`), plus `-fallow-argument-mismatch` on GNU Fortran ≥ 10, applied per source the way Coin-HSL's `meson.build` applies it globally.
- **Source list.** The driver passes the selected file list explicitly (`-DHSL_SOURCES=…`, or a generated `sources.cmake` in the scratch tree). CMakeLists.txt itself contains no HSL file names beyond what is already public in this plan.
- **The cmake binary.** The stack's own `<stack>/bin/cmake` when present; otherwise the system cmake (≥ 3.20 for reliable Fortran module dependency scanning — to be confirmed).

Trade-off: one more file (CMakeLists.txt) and a CMake dependency, against about 120 lines of
compile, link and module-order code in Python that CMake does natively and more portably
(macOS, Intel `ifx`).

## 5. What the installed library carries

The install goes under `<prefix>/share/doc/hsl/`:
- `LICENCE.coinhsl-<v>` plus `LICENCE.<pkg>-<v>` for every override applied
- `PROVENANCE.yaml`, the same content as in the bundle

Today only the Coin-HSL `LICENCE` is installed.

## 6. Out of scope and unchanged

- Ipopt recipe, SPRAL work, packaging: untouched.
- No HSL content goes to auditors, devlogs, changelogs or anything tracked. Only names, versions, symbols and our own code.
- No change to `.gitignore` beyond what §0 of `libhsl_build_script.md` added.

## 7. Gates after implementation

- [ ] Rebuild on `gcc` and `mkl` with the MA77 override. Self-check passes; `build-info` and `PROVENANCE` show `HSL_MA77 6.5.0` replacing 6.4.0.
- [ ] Negative tests, run against synthetic stand-in tarballs created in a scratch directory (no HSL content):
  - an override with an older version is ignored
  - an equal version is ignored
  - a header mismatch stops the build
  - a dependency-module mismatch stops the build
- [ ] Bundle round-trip: create, unpack elsewhere, rebuild with SHA-256 verification, and get the same exported symbol set.
- [ ] `git status` is clean of any HSL name.

## 8. Review questions for Codex and Grok

1. Is option A over B justified, and are the four override rules enough to make a newer standalone a safe drop-in? What is missing? For example: F77 routines in a standalone's `common.f` that Coin-HSL's `deps.f` also defines; `-fallow-argument-mismatch`; single-precision files.
2. ChangeLog parsing as the version source for Coin-HSL: is that robust enough, or should versions be pinned in the script?
3. Bundle: is "original tarballs plus `LICENCES/` plus `PROVENANCE`" the right shape? Anything that would make it look like redistribution-ready material?
4. Anything in `scripts/build_libhsl.py` as it stands (already gated on `gcc`/`mkl`) that conflicts with this plan or with CLAUDE.md.
5. CMake backend (§4b): cleaner than the Python compile and link stage? Specifically: CMake's Fortran module scanning on gfortran/ifx; the rpath and `--no-as-needed` handling versus SCLS's `get_cmake_args`; passing the math line without `FindBLAS`; whether per-package libraries (O3) are worth it.

## 9. Review outcome (Codex gpt-6-astra + Grok 4.7, 2026-10-03) — final design

Full record: `tmp/ai_exchange/review_libhsl_plan.md`. §4 is superseded by §0. §5 and §7 are
replaced by this section wherever they conflict.

**Override check: a classified file set, byte-exact.** It replaces rules 1-3 of §3.
- The override table pins `coinhsl` version → `HSL_MA77 6.4.0`, and the standalone version `6.5.0`.
- Coin-HSL's ChangeLog is only a cross-check, and any disagreement with the pin stops the build.
- Versions compare as numeric tuples. Equal or older → skipped before any other check (MA86 and MA97 today).
- `hsl_ma57-*` and `ma57-*` are explicitly out of scope.
- Every file under the standalone's `src/` and `include/` must fall into one class:
  - `identical`: byte-equal to the Coin-HSL file of the same role
  - `replace`: an intended change, copied over Coin-HSL's file
  - `deps`: each F77 unit and each F90 module byte-equal, trailing whitespace ignored, to Coin-HSL's `common/deps.f` / `common/deps90.f90`. Never copied.
  - `ignore`: autotools files
- Any unclassified or mismatching file stops the build, printing names and hashes only, never diffs.
- Verified locally for 6.5.0: every file classifies cleanly; only `hsl_ma77{d,s}.f90` change.
- Gate: the replaced objects' hashes must differ from a build of Coin-HSL's own copies (proof the override was compiled).

**Assembly: `scripts/hsl/assemble_sources.sh <tarball-dir> <target-dir>` (bash).**
- **Safe extraction.** List members first; reject absolute paths, `..`, and symlinks or hardlinks pointing outside. Extract with `--no-same-owner --no-same-permissions`.
- **Exactly-one rule.** Each glob must match exactly one tarball, or zero for an optional override.
- **Output** in `<target>`:
  - the assembled tree
  - `LICENCES/LICENCE.<package>-<version>` for every tarball used, which today means the Coin-HSL notice and the full HSL Academic Licence 2.0 from MA77
  - `PROVENANCE.txt` with inputs, SHA-256 and the classification result
- Refuses a target inside the work tree.

**Build: `scripts/hsl/CMakeLists.txt`, explicit, no `get_cmake_args`.**
- **Compilers.** Flavor `cc`/`fc` are passed as `CMAKE_C_COMPILER`/`CMAKE_Fortran_COMPILER`, so they are set before `project()`.
- **Flags.** No `CMAKE_BUILD_TYPE` flags: only the flavor's `cflags`/`fflags`, plus `-O2` when the flavor has no `-O`.
- **OpenMP** on Fortran only, as upstream meson does. `-fallow-argument-mismatch` is global for GNU Fortran ≥ 10.
- **Sources** come from a generated `sources.cmake`. CMake does the Fortran module scanning.
- **Linking.** One target, `coinhsl`, with Fortran as linker language and `SONAME libcoinhsl.so` pinned (`NO_SONAME OFF`, no `VERSION`). Then:
  - `-Wl,--no-as-needed` first
  - METIS by full path from `find_library(... NAMES metis PATHS <stack>/lib NO_DEFAULT_PATH REQUIRED)`
  - the flavor math line as a CMake list, shlex-tokenised by the driver
- **Paths.** `INSTALL_RPATH` = stack lib (+ MKL lib dirs from the math line); on macOS `INSTALL_NAME_DIR` = the private prefix.
- **Install:** `cmake --install` into a staging directory.

**Driver: `scripts/build_libhsl.py`.**
- Platform comes from the flavor only; a Darwin host with a linux flavor is refused. `--prefix` inside the work tree or inside the stack prefix is refused.
- Order: assemble → configure → build → `cmake --install` to staging → self-check on the staged library. The self-check covers:
  - the 41 symbols
  - no METIS definitions
  - every `DT_NEEDED` resolving where the flavor says (stack `libmetis`, stack OpenBLAS or the flavor's MKL)
  - the dlopen smoke test
  - `check_mkl_linkage.sh` on MKL flavors
- Only after a passing check is staging copied into `--prefix`, with `LICENCES/` and `PROVENANCE.txt` under `share/doc/hsl/`.
- `share/hsl/build-info.yaml` records:
  - the `git hash-object` of the driver, the assembly script and CMakeLists, plus a work-tree-dirty flag
  - the flavor
  - the expanded compile and link lines
  - `DT_NEEDED`
- `shlex.split` for flavor flags. No unfiltered `extractall` (extraction moves to the bash assembler).

**Gates**
- [x] `gcc` and `mkl` builds: self-check passes; MA77 gate discriminates 6.4.0 (fails) from 6.5.0 (passes); installed library survives removal of the build tree.
- [x] Synthetic negative tests: `scripts/hsl/tests/test_assemble.sh`, 16/16.
- [x] `git status` is clean of HSL names.
- [x] Ipopt `hs071` with `hsllib` + `linear_solver` mumps/ma27/ma57/ma77/ma86/ma97 against the peer's gcc build tree and then against the installed `scls-gcc-ipopt` (`tests/ipopt_hs071.c`): all optimal, identical objective; one METIS in process (2026-10-03).

**Open, for Christian**
- [x] **D2 — functional MA77 gate.** Christian: yes, a real factor-and-solve. Implemented (`tests/ma77_factor_solve.c`).
  - Codex: required. A factor/solve with residual check, ideally reproducing the fixed case.
  - Grok: the hash gate is enough; HSL's own examples are optional local extras.
  - Proposal: the hash gate is mandatory now. Run the standalone package's own example locally as an optional `--run-examples` step, with output not logged into tracked files. Ipopt `ma77` is the integration test once Ipopt is installed.
- [x] **D3 — `doc/LICENSE_POLICY.md` gets a short HSL section** (done) ("licensee-built, never distributed; scripts public, sources private"). Grok: the decision belongs in policy, not only in `todo/`.
- [x] **D4 — version script.** Christian agreed: none. Export everything. There are no METIS internals in the library, and it stays usable from Fortran as well as from Ipopt.

## 10. Entry point (Christian, 2026-10-03)

- [x] `./scls build hsl [--sources DIR] [--prefix DIR] [--no-overrides]` — routed in the `scls`
  wrapper to `scripts/build_libhsl.py` with the active flavor, before any builder; no recipe,
  spec, registry entry or build-order slot. `--sources` defaults to `tmp/HSL`; install default
  `~/.local/scls-hsl/<flavor>` (per-user, per licence).
- [x] `./scls install hsl` (Christian, 2026-10-03: "isn't it the user's responsibility … print a
  License warning … the user would have to accept the conditions") — same build, then prints the
  licence texts from the user's tarballs, requires `yes` (or `--accept-licence`), publishes into
  `/opt/scls/<flavor>` with `sudo install` (files only; the build never runs as root), records the
  acceptance in `build-info.yaml`. Ipopt then finds `libhsl.so` via `libipopt`'s RUNPATH
  (verified with `LD_DEBUG=libs` from an executable with no rpath of its own).
- [x] `LD_LIBRARY_PATH` route vetoed by Christian (SCLS policy); `DYLD_LIBRARY_PATH` dead on
  macOS anyway. An Ipopt env-var patch (`IPOPT_HSLLIB`) was considered and dropped: the stack
  prefix install covers the "no configuration" case without diverging from upstream.
- [ ] Executable gate still open: `./scls install hsl` on a terminal with sudo (Christian). The
  non-tty path was run: builds, shows licences, refuses, installs nothing.
- [ ] macOS: same command on the dev Mac with `scls-macos-metis` installed; `libhsl.dylib`
  symlink, **hard** install name = `<prefix>/lib/libcoinhsl.dylib` (no `@rpath`, per Christian), stack
  libs by their install names; the pre-publish test is retargeted to staging with
  `install_name_tool -change`. Never run yet.

## 11. Licence round (2026-10-03) — see devlog and `tmp/ai_exchange/review_hsl_licence.md`

- [x] Personal install private (0700/0600); any non-`$HOME` prefix = shared = acceptance.
- [x] Acceptance states the Academic Licence terms in SCLS's words; extended record.
- [x] Confidential-looking prose removed from tracked files.
- [x] `--work-dir` deletion-before-validation fixed; atexit/SIGTERM cleanup; assembler trap.
- [x] Coin-HSL-only build passes (basic MA77 test).
- [x] **Christian (2026-10-03):** the MA77 override stays default-on, "apply if newer"; `--no-overrides` opts out. Rationale: both tarballs are the licensee's own releases, each used under its own licence; the auditors' 2.1.4 doubt is recorded, the decision is the maintainer's.
