# 2026-09-25 — MKL threading-layer uniformity: two layers in one process, and the gate that missed it

A build-configuration change, scoped in mid-campaign after belfem rejected a drop. It was **not**
part of the 2026-09-22 campaign, and the distinction matters enough to lead with it: the campaign's
own verification recorded the defective state as correct.

## Summary

On MKL-class flavors, `libscalapack.so` linked `libmkl_sequential` while the other 256 MKL
references in `/opt/scls/mkl` linked `libmkl_gnu_thread`, and `libarmadillo.so` linked `libmkl_rt`
*and* the layered `gf_lp64`/`gnu_thread`/`core` trio. Both are configurations Intel documents as
unsupported. Fixed in `python/math_common.py` and `recipes/armadillo.yaml`, with releases bumped to
`scalapack 2.2.3-4` and `armadillo 15.6.0-2`, plus a new per-flavor linkage gate that fails a drop
before `READY` is written.

## Key findings

**1. The defect is real at the loader, not just in the link line.** `ldd libpetsc.so.3.25.5` loads
both `libmkl_gnu_thread.so.3` and `libmkl_sequential.so.3` — the latter pulled in through
`libscalapack.so.2.2`, which petsc links alongside the threaded layer it links directly. Which
layer's symbols win depends on load order. `ldd libarmadillo.so.15.6.0` similarly shows
`libmkl_rt.so.3` beside `libmkl_gnu_thread.so.3`; `mkl_rt` resolves its threading layer at runtime
from `MKL_THREADING_LAYER` while the layered libraries bind at link time, so the two models
disagree by construction. Census across the flavor: **256** `gnu_thread`, **1** `sequential`,
**1** `mkl_rt`.

**2. Root cause was a recipe-level gate on a flavor-level property.** Two macros produce MKL link
lines and only one consulted the recipe:

| macro | function | consulted `features.openmp`? |
|---|---|---|
| `%{math_ldflags}` | `get_math_link_line(flavor, recipe)` | yes — this was the bug |
| `%{mkl_linker_flags}` | `get_mkl_serial_link_line(flavor)` | no |

`threaded = use_omp and mkl_threading_mode(...) == 'threaded'` meant any recipe declaring
`features.openmp: false` took the `-lmkl_sequential` branch. Only four recipes use
`%{math_ldflags}` (`scalapack`, `arpack-ng`, `blaze`, `slate`), and of those only `scalapack` both
declares `openmp: false` and ships a shared object — which is why exactly one library in the stack
was affected. `blaspp` and `lapackpp` also declare `openmp: false` but use `%{mkl_linker_flags}`,
so they were threaded all along. The divergence between the two macros is the real defect; the
single wrong library was its only visible symptom.

**3. The campaign's verification passed it, and that is the more dangerous artifact.** The
2026-09-23 entry in `todo/rebuild_campaign_20260922.md` records a "scalapack provenance" check that
ran `readelf -d` on this exact library, listed `libmkl_sequential.so.3` in its output, and
concluded "exactly as policy requires". The check was not wrong about what it asked — ScaLAPACK
must come from the stack and not from `libmkl_scalapack` — it simply never asked whether the flavor
was self-consistent. A per-package check structurally cannot see this class of defect: every
object involved is well-formed on its own and only wrong in company. That tracker line has been
corrected; left alone it would have certified the same state through the next campaign.

**4. No cascade rebuild.** `libscalapack.so.2.2` keeps its SONAME and exported ABI, and all eleven
consumers link that exact string, so they resolve the new library at runtime unchanged.
`doc/MKL_ABI_POLICY.md` triggers consumer rebuilds on an MKL *major SONAME* bump, which this is
not. `armadillo` is a leaf. Two packages rebuild, not the upper half of the stack.

**5. `gcc` and `debug` have no analogue.** Measured, not assumed: `/opt/scls/gcc` is 235/235
`libgomp.so.1` with `libopenblas.so.0` as the sole BLAS provider; `/opt/scls/debug` is 234/234
`libgomp.so.1` with reference `libblas`/`liblapack` only. The R9-debug and R9-gcc drops, already
promoted, need nothing.

## Changes made

- **`python/math_common.py`** — `get_math_link_line`: dropped `use_omp` from the `threaded`
  decision, so the flavor's `math.threading:` is the single source of truth on both macro paths.
  Rationale is in a comment at the site.
- **`recipes/armadillo.yaml`** — `mkl`, `intel` and `cuda` branches: `ALLOW_MKL_LINUX=OFF`,
  `CMAKE_DISABLE_FIND_PACKAGE_MKL=TRUE`, explicit `BLAS_LIBRARY`/`LAPACK_LIBRARY=%{math_ldflags}`.
  `BLA_VENDOR=Intel10_64lp` retained deliberately — it pins CMake's `FindBLAS` away from a
  host OpenBLAS and is orthogonal to the `find_package(MKL)` path that added `mkl_rt`. The
  `armadillo-add-allow-mkl-option.patch` is kept and simply not enabled, because other flavors
  reference the option. All three MKL-class branches were fixed rather than only `mkl`: the defect
  is identical in each, and a half-fix would resurface the moment `intel` is built.
- **Releases** — `scalapack 2.2.3-4`, `armadillo 15.6.0-2`, with the reason recorded next to the
  field and in `changelogs/`.
- **`scripts/check_mkl_linkage.sh`** (new) — per-flavor linkage gate. Reads the expected model from
  `flavors/<f>.yaml` (following `inherits:`) rather than a hardcoded list, extracts the payload
  RPMs, and asserts over real `DT_NEEDED`: exactly one MKL threading layer matching the flavor's
  declaration, no `libmkl_rt`, no `libmkl_scalapack`/`libmkl_blacs`; for non-MKL flavors, one
  OpenMP runtime, one BLAS provider, and no MKL at all. It names the carrying library, since the
  point is to find one outlier among hundreds. Runs against a staged drop (`--dir`) or an installed
  prefix (`--prefix`).
- **`scripts/stage_to_belfem.sh`** — the gate runs during `--build`, *before* `READY` is written,
  so a violation produces a drop that physically cannot be uploaded rather than a warning.

## Verification

- **Spec diff, all 36 mkl specs before/after**: exactly three change — `scalapack`, `armadillo`,
  `blaze`. No mkl spec mentions `mkl_sequential` or `mkl_rt` afterwards.
- **Containment**: five `gcc` specs regenerate byte-identical, confirming the change cannot leak
  outside `linalg == mkl`.
- **Gate self-test**: run against the *un-rebuilt* `/opt/scls/mkl` it fails with both violations
  and names `libscalapack.so.2.2.3` and `libarmadillo.so.15.6.0`; against `/opt/scls/gcc` and
  `/opt/scls/debug` it passes. A gate that could not reproduce the known defect would be worthless,
  so this was run before the fix was installed.
- **scalapack 2.2.3-4 builds and its own test suite passes 72/72** against the threaded MKL.

## Open questions

- **Thread oversubscription, accepted not solved.** ScaLAPACK's MKL BLAS calls are now threaded, so
  an MPI job with one rank per core can oversubscribe. Nothing in `recipes/environment.yaml` or the
  installed profile sets `MKL_NUM_THREADS` or `MKL_THREADING_LAYER`. Pinning them was offered and
  Christian chose the fix *without* pinning, so this is a known, accepted trade-off rather than an
  oversight. It is the obvious follow-up if users report MPI performance regressions on `mkl`.
  Note the historical reading: `features.openmp: false` with `math: serial` on reference ScaLAPACK
  looks like a deliberate conservative choice, and this change reverses its practical effect.
- **`blaze` changes but is not rebuilt.** Its spec now carries the threaded line, but it is
  header-only (1682 files, no ELF), so its `DT_NEEDED` cannot move and no release was bumped. A
  future rebuild for any other reason will pick the new line up silently. Recorded so the next
  spec diff does not look mysterious.
- **The two-auditor gate did not run.** `CLAUDE.md` routes build-configuration changes through
  `doc/AI_COLLABORATION_PROTOCOL.md`'s plan → two blind audits → implement → two blind audits. On
  this host neither auditor is reachable: the `grok` CLI is not installed, and `codex` fails with
  `HTTP 401 … access token could not be refreshed`. This change therefore rests on the empirical
  evidence above, not on an independent review, and that gap is deliberately recorded rather than
  papered over. Re-running the audit before the change reaches other columns is worth doing.

## Files updated

`python/math_common.py`, `recipes/armadillo.yaml`, `recipes/scalapack.yaml`,
`changelogs/armadillo.md`, `changelogs/scalapack.md`, `scripts/check_mkl_linkage.sh` (new),
`scripts/stage_to_belfem.sh`, `doc/MKL_ABI_POLICY.md`, `todo/rebuild_campaign_20260922.md`,
and this devlog. Staging history for the same day is in
`devlog/dl20260925_r9_gcc_mkl_stage_drops.md`.
