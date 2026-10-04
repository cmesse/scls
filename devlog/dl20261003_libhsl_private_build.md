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
- **Coin-HSL vs standalone tarballs:** the versions of MA97, MA86, MC68 and MA57 in
  Coin-HSL 2024.05.15 equal the standalone releases on hand; HSL_MA77 is 6.4.0 in Coin-HSL
  and 6.5.0 standalone (a newer release). The standalone MA57 targets the METIS 4 interface
  while Coin-HSL's copy is wired to its METIS 5 adapter, so standalone-first was rejected.
  (Details of the comparison stay in the untracked exchange; they describe licensed content.)
- **Override safety** (auditor finding, adopted): a `use`-module check is not enough. Every
  file under a standalone's `src/` and `include/` must classify as identical / replace /
  deps (byte-equal per F77 unit or F90 module, trailing whitespace ignored) / ignore, else
  stop. The MA77 6.5.0 tarball on hand classifies cleanly under that rule.
- **Builder helper not reusable:** `build_common.get_cmake_args` sets C/CXX standard
  libraries only (`:858-859`), defaults `no_as_needed=False` (`:731`), forces
  `CMAKE_BUILD_TYPE=Release`. An explicit CMakeLists was written instead.
- **The MA77 gate discriminates versions.** Its refactorization test requires HSL_MA77
  >= 6.5.0: a Coin-HSL-only build (6.4.0) does not pass it, a build with the 6.5.0 override
  does (forward error 3e-16). The test therefore runs in "basic" mode for base-only builds.

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
- `scripts/hsl/tests/ma77_factor_solve.c` — indefinite factor/solve, plus a refactorization test for HSL_MA77 >= 6.5.0.
- `scripts/hsl/tests/test_assemble.sh` — 16 synthetic cases (dummy tarballs), all pass.
- `scripts/hsl/tests/ipopt_hs071.c` — integration gate: hs071 via Ipopt's C interface with a chosen `linear_solver` and `hsllib`.
- `scls` wrapper — routes `build hsl` / `install hsl` to `scripts/build_libhsl.py` before any
  builder (Christian, 2026-10-03: "we just shouldn't create a package file"). Final shape
  (Christian, later the same day: "so that it behaves as with the other libraries"): `build`
  only builds and checks, staging the result owner-only under `$TMPDIR/scls-hsl-<uid>/<flavor>`;
  `install` asks install type (local = `~/.local/scls-hsl/<flavor>` 0700/0600; global = stack
  prefix via sudo), licence type (academic | commercial; academic + global only after confirming
  sole use of the machine), and acceptance (licence files from the tarballs + SCLS's statement of
  what is confirmed), records all of it in `build-info.yaml`, publishes, and deletes the stage.
  Rationale: compliance is the licensee's responsibility; SCLS distributes nothing.
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
| MA77 factor/solve (+ refactorization with the 6.5.0 override) | PASS | PASS |
| `check_mkl_linkage.sh` | — | PASS |
| `--no-overrides` (6.4.0): refactorization test not passed; now skipped in basic mode | ✓ | — |
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
- No link-time HSL in Ipopt, not even as an opt-in (Christian's question, 2026-10-03: a global
  HSL install must not make Ipopt link against it). Verified: `--without-hsl` sets
  `coin_has_hsl=skipping` in configure, and Ipopt's probe is pkg-config (`coinhsl.pc`) +
  headers, which the HSL install does not ship. The gain of linking (MA27 as Ipopt's default
  solver) is not worth an HSL-derived, unpackageable `libipopt`.
- Library name: file `libcoinhsl.so` (SONAME, what it contains) + `libhsl.so` symlink
  (Ipopt's default). Recommended; a diff-against-HSL-example approach for the test was
  advised against (a diff embeds HSL text as context/removed lines).

## Licence compliance round (Codex gpt-6-astra + Grok 4.7, 2026-10-03)

Advisory only — licensing is not settled by vote. Record: `tmp/ai_exchange/review_hsl_licence.md`.
Agreed by all three: SCLS's public tooling distributes no HSL code and is not a derivative work;
linking the stack's METIS/BLAS/OpenMP is, in SCLS's reading, the platform optimisation the
Academic Licence allows. Findings and what changed:
- **Confidentiality (clause 4):** tracked prose had disclosed results of comparing licensed
  sources (internal module names, a bug description, "code-identical" statements). Removed from
  docs, devlog, todos, the test comment and the synthetic fixtures. Public package names, versions
  and the C API symbols (in Ipopt's redistributable headers) stay.
- **Sharing (clause 2.1.2):** the personal install was world-readable (0644) and only the stack
  path asked for acceptance. Now: a prefix under `$HOME` is personal and installed 0700/0600 from
  the root; any prefix outside `$HOME` is a shared install with the same acceptance step as the
  stack. The step prints the licence files from the user's tarballs (Coin-HSL's own is only a
  portal pointer) plus SCLS's statement of the academic terms, says an academic licence does not
  permit a shared install on a multi-user machine, and records user, uid, host, how, time and the
  SHA-256 of the texts shown. Stale `--allow-stack-prefix` text and per-mode messages fixed.
- **Safety:** `--work-dir` was registered for deletion before it was validated — `--work-dir .`
  would have deleted the checkout on the refusal. Now a `--work-dir` must not pre-exist, deletion
  is registered only after all checks, `atexit` + SIGTERM cover interrupts, and the assembler's
  EXIT trap removes its temp files and a half-assembled target. GNU-only `install -D` replaced.
- **Coin-HSL-only builds** failed the MA77 gate (its refactorization test needs 6.5.0); the test
  now runs in basic mode unless the override was applied.
- **Override default — decided (Christian, 2026-10-03):** both auditors doubt that §2.1.4
  covers compiling a newer standalone MA77 in place of Coin-HSL's copy. Christian keeps the
  override default-on, "apply if newer", with `--no-overrides` as the opt-out: both tarballs
  are the licensee's own releases, each used under its own licence. Docs present SCLS's reading
  as a reading and leave the choice with the user.

## Open

- `./scls install hsl` on a terminal with sudo (the only path not executed here).
- `macos` / `intel` runs.

## macOS: first `./scls build hsl` run on a bsdtar host (same day)

`./scls build hsl --sources=./tmp/hsl` on the macOS dev host failed in four places.
All are fixed.

1. **Fixed.** `assemble_sources.sh` `safe_extract` read the member name from field 6
   of `tar -tv`. That is the name on GNU tar and the month on bsdtar (name is field 9),
   so the top-level directory came out as `May` and the unsafe-path check inspected
   the month column. Names now come from `tar -tzf`. Extract-first-then-inspect was
   considered and rejected by both auditors: a stripped absolute member `/top/x`
   passes a one-top-level-dir check, and content is written before validation.
2. **Fixed.** The hardlink check took the target as `$(NF)`, so `../out side.f` was
   tested as `side.f`. The verbose line is now split on every ` link to ` and each
   piece is tested; `LC_ALL=C` pins the marker. Test 12b2 covers it.
3. **Fixed.** BSD awk rejects `printf ... > d "/.coverage"`; the path is assigned to
   a variable first.
4. **Fixed.** `build_libhsl.py` used `prefix` in `cmd_build`, which has not existed
   there since 51451f0 moved the choice of install location to `./scls install hsl`
   (`NameError`, macOS only). Decision (Christian): the stack prefix is known at build
   time for every flavor, so the dylib id is linked in as `<stack>/lib/libcoinhsl.dylib`.
   A global install publishes the checked file unchanged. A macOS local install
   (`~/.local/scls-hsl/<flavor>`) has a different path, so `cmd_install` rewrites the
   id and re-signs ad hoc (`set_macos_dylib_id`): on a copy, renamed over the build-dir
   file only after `codesign -v` and the id verify, and keyed on the current id so a
   global install after a failed local one sets it back. The licence-acceptance record
   is now written after that step and replaces any record from a failed attempt.

Gates: `bash scripts/hsl/tests/test_assemble.sh` on macOS (bsdtar 3.5.3, awk
20200816): passed 21, failed 0. `./scls build hsl --sources=./tmp/hsl` on macOS (x86_64): exit 0,
dlopen smoke and MA77 gate PASS, staged id `/opt/scls/lib/libcoinhsl.dylib`.
`set_macos_dylib_id` exercised on a copy (no-op, to local id, back; dlopen ok).
`./scls install hsl` itself not run (interactive licence acceptance). GNU tar / Linux run of the test script: pending a Linux host. Review: plan and
implementation each audited by Codex (gpt-5.6-terra, high) and Grok (grok-4.7, xhigh).
Not adopted: newline-in-member-name handling; extra fixtures for absolute and
internal hardlinks.
