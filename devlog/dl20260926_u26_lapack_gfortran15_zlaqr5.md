# Devlog 2026-09-26 — U26: gfortran 15.2 miscompiles reference LAPACK `zlaqr5` (wrong complex eigenvectors)

**Date:** 2026-09-26
**Topic:** first full-stack build on the new U26 host (Ubuntu 26.04, GCC/gfortran 15.2.0-16ubuntu1); `debug` halted at lapackpp's `geev` test
**AIs involved:** Claude Opus (U26 host session, lead); Fable subagent (independent diagnosis); Codex gpt-6-astra/high and Grok 4.7/xhigh (blind plan + code juries under `/build-fix-jury`, Escalated level)
**Flavor / Host:** debug on U26 (DEB)
**Verification:** built and installed on U26/debug: `scls-debug-{blas,cblas,lapack,lapacke} 3.12.1-2`, LAPACK ctest 125/125; lapackpp 2025.05.28-2 full `run_tests.py --quick` passes ("All routines passed"), including complex `geev`. Not built on any other host.

## Summary

lapackpp's own test failed on U26/debug: `tester --dim 100 geev` for types `c` and `z` returned
eigenvector residuals `||A Vr - Vr W||` of 3e-3 to 8e-3 (s/d passed). U24 (GCC 13) passed the same
lapack 3.12.1 + lapackpp. The cause is a gfortran 15.2 wrong-code bug in reference LAPACK's
`zlaqr5.f`, not lapackpp. Fixed by building reference LAPACK with `-ffp-contract=off`
(`recipes/lapack.yaml`, release 3.12.1-2), approved by Christian.

## Key findings

- **Size window.** `tester --type z geev` passes for n <= 75 and fails for n >= 76 (75 = `NMIN` in
  `IPARMQ`, the crossover from `ZLAHQR` to multishift `ZLAQR0/ZLAQR5`). Fable's standalone `ZGEEV`
  sweep found the bad window to be 76 <= n < 150; at n >= 150 `NS=16` selects `KACC22=2`, a different
  update path. LAPACK's own ctest (which does lower `NMIN` via `TESTING/nep.in`, per Codex) does not
  catch it.
- **Actual compile line** (from a scratch configure of the recipe's exact cmake line,
  `SRC/CMakeFiles/lapack_obj.dir/flags.make`):
  `-march=x86-64-v3 -Og -g -fPIC -fno-fast-math -fno-unsafe-math-optimizations -frecursive -O2 -fPIC -frecursive`.
  LAPACK's CMake reduces Release to `-O2` and appends it after the user flags.
- **LD_PRELOAD reproducer.** Rebuilding `zlahqr zlaqr0-5 ztrevc3` with exactly that line reproduces the
  failure; with `-ffp-contract=off`, or without `-march=x86-64-v3`, it passes. Per-file bisection
  (all others contraction-off): only `zlaqr5.f` fails.
- **It is a compiler bug, not FMA sensitivity** (Fable, verified on U26). A single `ZLAQR5` call on a
  dumped input returns a non-similarity (`|Q^H H_in Q - H_out| = 2.2e-3`), which no legal rounding can
  produce. `-fdbg-cnt=vect_slp` bisection isolates one SLP instance at `zlaqr5.f:450`
  (`DO 40`: `H( K+1, J ) = H( K+1, J ) - REFSUM*T1`), emitted as `vfmsubadd231pd`/`vfmaddsub132pd`.
  Standalone kernel (`zlaqr5.f` lines 427-452 plus a driver), worst |dH| against `-O0`:
  `-O2 -march=x86-64-v3` **0.99**; `+ -ffp-contract=off` 0; `-fno-tree-slp-vectorize` 1e-15;
  `-fno-tree-vectorize` 1e-15; `-mno-fma` 0; `-O3` 1e-15. Suitable for a GCC bug report.
- **Flag placement.** The recipe's flag sits before upstream's appended `-O2`; `gfortran -S` of
  `zlaqr5.f` in that order emits 0 `vfmadd*` against 55 without it.
- **OpenBLAS (gcc/lbl/macos flavors) is not exposed today.** OpenBLAS 0.3.34 `Makefile:318-319` writes
  `override FFLAGS = $(LAPACK_FFLAGS) -fno-tree-vectorize` for gfortran into lapack-netlib's
  `make.inc`, which disables the buggy pass. Its bundled LAPACK 3.12.0 `zlaqr5.f` is code-identical.

## Gate results (U26/debug, installed packages)

- `scls-debug-lapack 3.12.1-2`: configure line carries `-ffp-contract=off`; ctest 100 % of 125.
- lapackpp `geev` at n=100: `c` residual 4.8e-7 (was 5.0e-3), `z` 5.7e-16 (was 3.5e-3); "All routines passed".
- Standalone `ZGEEV` against the installed library, max residual: n=75 1.4e-15, 76 6.4e-16,
  100 6.7e-16, 149 7.3e-16, 150 6.8e-16, 200 8.7e-16.

## Decisions (Christian)

- Apply `-ffp-contract=off` to the whole reference LAPACK build (not per file), release 3.12.1-2,
  no cascade (no ABI or SONAME change).

## Open — needs Christian

1. **Pre-existing, found by Codex (P1):** `scls-<F>-lapack` does not declare a dependency on
   `scls-<F>-blas` although `liblapack.so.3` has `DT_NEEDED libblas.so.3`. `blas` is listed under the
   same-name `lapack` subpackage, which both builders skip without merging its `requires`
   (`python/rpm_builder.py:2370`, `python/deb_builder.py:704`). Dependency-list change, not landed.
2. **Pre-existing (P2):** the lapack binary packages ship no LAPACK license notice (BSD requires it).
3. Other debug hosts (R9, R10, U24) pick up 3.12.1-2 on their next lapack build; it was gated only here.
4. Optional: file the GCC bug with the standalone kernel (U26 scratch, not tracked).

Exchange record: `tmp/ai_exchange/fix_lapack_u26_debug.md` (ephemeral).
