# Devlog 2026-10-03 — Private libhsl build for Ipopt's runtime loader

**Participants:** Claude (explore/propose), Codex gpt-6-astra + Grok 4.7 (blind plan audit), Christian (decisions)
**Branch:** `ipopt` (uncommitted)
**Auditor Confidence:** high (plan round); implementation round pending
**Exchange:** `tmp/ai_exchange/review_libhsl_plan.md`
**Plans:** `todo/libhsl_source_selection.md` (current), `todo/libhsl_build_script.md`, `todo/hsl_private_recipe.md` (superseded)

## Summary

HSL's linear solvers are proprietary (HSL Academic Licence 2.0: personal use, no sharing,
no commercial use). SCLS now provides *public build tooling* with which a licensee builds a
private `libhsl` from their own original tarballs; SCLS itself ships no HSL source, binary,
package or dependency, and `recipes/ipopt.yaml` is unchanged (`--without-hsl`, runtime
loader on). Built and gated on this EL9 host for `gcc`, `mkl` and `debug`, and run end-to-end through the peer session's freshly built Ipopt.

Three designs were considered over 2026-09-30 → 10-03 and two rejected:
1. A packaged `hsl` recipe: rejected. Four leak paths in the packaging system (SRPM bundles
   the tarball, meta-package Requires, staging matches only the main name, builder curls a
   missing source) would each have needed a new guard (`todo/hsl_private_recipe.md`).
2. A script around the GALAHAD HSL subset: rejected once Coin-HSL arrived; the subset bundles
   its own METIS (symbol clash with the stack's) and needs preprocessing.
3. **Chosen:** Coin-HSL 2024.05.15 as base, a bash assembler applying verified standalone
   overrides, our own CMakeLists, a Python driver. One METIS (the stack's) via Coin-HSL's
   own METIS 5 adapter.

## Key Findings

- **Ipopt needs nothing.** Upstream 3.14.20 creates the HSL loader only for solvers not
  linked in (`IpAlgBuilder.cpp:1140-1152`), defaults `hsllib` to `libhsl.<ext>` (`:303-308`),
  resolves each solver's symbols lazily, and keeps `mumps` as default because linked solvers
  outrank loaded ones (`:207-252`). Loader symbol set: 41 names (4 MA27, 5 MA57, 1 MC19,
  16 MA77, 6 MA86, 7 MA97, 2 MC68).
- **How Ipopt finds the private library** (verified against the installed `libipopt.so.3`,
  RUNPATH `/opt/scls/gcc/lib`): the default `hsllib` = bare `libhsl.so` fails from a per-user
  prefix ("cannot open shared object file"); `hsllib <full path>` in `ipopt.opt` /
  `AddIpoptStrOption` works with no environment at all. `LD_LIBRARY_PATH` would also work but
  is vetoed by SCLS policy (Christian, 2026-10-03), and `DYLD_LIBRARY_PATH` is ignored by
  macOS's hardened runtime. Ipopt has no HSL-specific environment variable. The clean
  no-configuration route is the stack prefix: `LD_DEBUG=libs` from an executable with **no**
  rpath shows `dlopen("libhsl.so")` searching `/opt/scls/gcc/lib` as "RUNPATH from file
  libipopt.so.3". Hence `./scls install hsl` (below); an `IPOPT_HSLLIB` patch was considered
  and dropped as unnecessary divergence from upstream.
- **Coin-HSL vs standalone tarballs** (code compared, comments stripped): MA97 2.8.1,
  MA86 1.7.4, MC68 3.3.3, MA57 3.11.3 identical in substance; **HSL_MA77 is 6.4.0 in
  Coin-HSL and 6.5.0 standalone**, one fix in `input_reals` after a singular / not-posdef
  factorization. Standalone MA57 calls METIS 4's `METIS_NODEND`; Coin-HSL's copy calls its
  `hsl_metis` adapter, so standalone-first was rejected.
- **Override safety** (auditor finding, adopted): a `use`-module check is not enough. Every
  file under a standalone's `src/` and `include/` must classify as identical / replace /
  deps (byte-equal per F77 unit or F90 module) / ignore, else stop. For MA77 6.5.0 that
  classification is clean: only `hsl_ma77{d,s}.f90` change; all 8 shared modules and the one
  F77 helper are byte-identical to Coin-HSL's.
- **Builder helper not reusable:** `build_common.get_cmake_args` sets C/CXX standard
  libraries only (`:858-859`), defaults `no_as_needed=False` (`:731`), forces
  `CMAKE_BUILD_TYPE=Release`. An explicit CMakeLists was written instead.
- **The MA77 gate discriminates versions.** Built from Coin-HSL's 6.4.0 (`--no-overrides`),
  `ma77_factor_solve` fails at exactly the `input_reals` bug (flag -11) and nothing is
  installed; with 6.5.0 it passes (forward error 3e-16).

## Changes Made

New, all SCLS code, no HSL text:
- `scripts/build_libhsl.py` — driver: flavor env via `math_common`, assemble → cmake →
  `cmake --install` to staging → self-check → publish; `build-info.yaml` with script blob
  hashes, expanded flags, resolved `DT_NEEDED`.
- `scripts/hsl/assemble_sources.sh` — pins Coin-HSL 2024.05.15 component versions,
  ChangeLog cross-check, numeric version compare, classified override, safe extraction,
  `LICENCES/`, `PROVENANCE.txt`, refuses in-repo target.
- `scripts/hsl/CMakeLists.txt` — one `coinhsl` target, Fortran linker, OpenMP on Fortran,
  `--no-as-needed`, stack METIS by full path, math line as list, RPATH linked in.
- `scripts/hsl/tests/ma77_factor_solve.c` — indefinite factor/solve + the 6.5.0 regression.
- `scripts/hsl/tests/test_assemble.sh` — 16 synthetic cases (dummy tarballs), all pass.
- `scripts/hsl/tests/ipopt_hs071.c` — integration gate: hs071 via Ipopt's C interface with a chosen `linear_solver` and `hsllib`.
- `scls` wrapper — `./scls build hsl [--sources DIR] [--prefix DIR]` routes to
  `scripts/build_libhsl.py` before any builder is reached (Christian, 2026-10-03: "we just
  shouldn't create a package file"); per-user prefix. `./scls install hsl` is the stack-prefix
  variant: licence texts from the user's tarballs are printed, acceptance is required (`yes` on a
  tty or `--accept-licence`), files are published with `sudo install`, acceptance is recorded in
  `build-info.yaml`. Christian's rationale: compliance is the licensee's responsibility
  (single-user machine, or a commercial/site licence); SCLS distributes nothing.
- Implementation review (Codex gpt-6-astra + Grok 4.7, `tmp/ai_exchange/review_libhsl_impl.md`)
  found and I fixed: macOS — the dylib keeps a **hard** install name (Christian: `@rpath` is not used
  in the stack), so the pre-publish MA77 test executable is rewritten with `install_name_tool
  -change` to the staged file and re-signed, instead of trusting the id that points at the final
  path; `--work-dir` inside the stack prefix now refused; `tar | grep -q` guards replaced
  by a one-shot listing (pipefail/SIGPIPE could fail open) with structural link checks and a
  symlink ban; the F77/F90 unit splitter now reports coverage and the build stops when headers
  and parsed units disagree (was: zero units = pass); test harness counter lost in a subshell;
  NaN-safe MA77 check; stack `bin/` first on PATH and compilers verified; flavor `ldflags`
  (macOS headerpad) honoured; empty CMake option lists no longer passed; incomplete pins
  refused; `IGNORED_GLOBS` no longer globbed against cwd; physical paths in the in-repo check;
  scratch tree removed on every exit path. Three synthetic tests added for the archive and
  parser cases (20/20).
- `.gitignore` — HSL tarball/tree/library names blocked repo-wide.
- `doc/LICENSE_POLICY.md` — "Proprietary Libraries Built by the Licensee (HSL)" (D3).

## Gates (this host, EL9, gfortran 11, stack cmake 4.4.2)

| gate | gcc | mkl |
|---|---|---|
| 41 Ipopt symbols defined, no `METIS_*`/`gk_*` defined | ✓ | ✓ |
| `DT_NEEDED` resolve: stack `libmetis.so.0`, stack OpenBLAS / MKL `gf_lp64`+`gnu_thread`+`core` | ✓ | ✓ |
| RPATH linked in (`/opt/scls/<f>/lib` [+ MKL dirs]); works after build tree removed | ✓ | ✓ |
| dlopen smoke | ✓ | ✓ |
| MA77 factor/solve + 6.5.0 regression | PASS | PASS |
| `check_mkl_linkage.sh` | — | PASS |
| `--no-overrides` (6.4.0) fails the MA77 gate, installs nothing | ✓ | — |
| `test_assemble.sh` | 16/16 | — |

| gate | debug |
|---|---|
| all of the above except MKL check; `-Og -g` preserved (no `-O2` appended); lapack/blas resolve to `/opt/scls/debug/lib` | ✓ |

**Ipopt end-to-end (gcc):** against the peer session's freshly built `libipopt` 3.14.20 in
`rpmbuild/BUILD/Ipopt-releases-3.14.20` (read-only; not installed), `hs071_cpp` with an
`ipopt.opt` of `hsllib <scratch>/libhsl.so` + `linear_solver X`, X ∈ {mumps, ma27, ma57, ma77,
ma86, ma97}: all six report "running with linear solver X" (mumps is the linked default), all
six "EXIT: Optimal Solution Found", all six objective 1.7014017031783709e+01. The unchanged
Ipopt recipe (`--without-hsl`, loader on) therefore works with the HSL track. Evidence level:
full build of both sides on this host.

**Installed-package gate (gcc), 2026-10-03 15:xx:** after the peer installed
`scls-gcc-ipopt-3.14.20-1.el9`, `scripts/hsl/tests/ipopt_hs071.c` (our own hs071 through
Ipopt's public C interface, linked against `/opt/scls/gcc/lib/libipopt.so.3`) with
`hsllib <scratch>/libhsl.so`: mumps, ma27, ma57, ma77, ma86, ma97 all `Solve_Succeeded`,
objective 17.0140171404. `LD_DEBUG=libs` shows exactly one METIS in the process —
`/opt/scls/gcc/lib/libmetis.so.0` — for libipopt, libdmumps, libspral and libcoinhsl alike.
(`spral` needs `OMP_CANCELLATION=TRUE`, as the SPRAL track documents; with it, same optimum.)
Evidence level: installed package.

Not run: `macos`, `intel`.

## Decisions (Christian)

- Standalone script, not a recipe; Ipopt untouched (2026-09-30).
- One METIS, the stack's; no meson; own build (2026-10-01).
- Original tarballs + bash assembler + CMake; scripts public, sources private (2026-10-03).
- D2: real MA77 factor-and-solve gate — yes. D3: HSL section in LICENSE_POLICY — yes.
  D4: no symbol-export restriction. Test scratch-file names made SCLS's own.
- Library name: file `libcoinhsl.so` (SONAME, what it contains) + `libhsl.so` symlink
  (Ipopt's default). Recommended; a diff-against-HSL-example approach for the test was
  advised against (a diff embeds HSL text as context/removed lines).

## Open

- `./scls install hsl` on a terminal with sudo (the only path not executed here).
- `macos` / `intel` runs.
