# Plan (C5) — take the OpenMP runtime out of `CMAKE_<LANG>_STANDARD_LIBRARIES`

**Date:** 2026-08-18
**Author:** Claude (step 1 of the six-step script-change gate)
**Scope:** `python/build_common.py`, `python/math_common.py`. No bash changes.
**Status:** COMPLETE through step 6.

- [x] 1. plan written  - [x] 2. audited (Codex + Grok)  - [x] 3. decisions taken
- [x] 4. implemented   - [x] 5. re-audited              - [x] 6. amendments applied

## Step 3 decisions

Both auditors accepted the conditional direction and both independently refuted the
plan's safety claim: `features.openmp: true` does NOT guarantee `-fopenmp` in CFLAGS,
because `get_math_compile_flags` runs only when `features.math` is truthy. That left
**gklib, metis, parmetis and vtk** in the strip set with no SCLS-injected flag.

Adopted Codex's first option — make the flag injection independent of `features.math`
(C5.3) — rather than narrowing the strip, so `features.openmp` now means what it says.
**Scoped to `configure.type: cmake`**: injecting for every `features.openmp` recipe also
changed `openblas` (type `none`, manages its own flags via `USE_OPENMP=1`), which is a
foundational package and pure scope creep. `custom_makefile` (mumps) already renders
`openmp_flag` into its own `Makefile.inc`; `custom` (petsc) pins its runtime explicitly.
Both auditors accepted the cmake-only scope in round 2.

Adopted from round 2: tighten the `get_cmake_args` comment to state the cmake-only
contract; correct the claim that slepc pins its own OpenMP runtime (it inherits
PETSc's); flip `doc/MKL_ABI_POLICY.md` mitigation 1 from "not applied" to applied, with
the outstanding `readelf` gate named.

Rejected: Grok's round-2 amendment 1 (a double space in the stripped link line). Not
reproducible — `repr()` shows `-lmkl_core -lpthread` with a single separator, and Codex
independently failed to reproduce it too.

## Result

Verified at the generation gate across all recipes x seven flavors:

- The 10 `openmp: false` math cmake recipes (armadillo, arpack-ng, blaspp, blaze,
  cereal, exodus, lapackpp, netcdf, scalapack, superlu) are **byte-identical** on every
  flavor — the set both auditors were protecting is untouched.
- MKL flavors (mkl, intel, gcc-mkl-cuda): the 10 built cmake+openmp recipes lose the
  trailing `-lgomp` / `-liomp5` from `CMAKE_<LANG>_STANDARD_LIBRARIES`, nothing else.
- Non-MKL flavors (gcc, debug, lbl): only gklib, metis, parmetis and vtk change, each
  gaining `-fopenmp`.
- `openblas` is untouched.

Decisive check — the local cmake harness against upstream STRUMPACK's own probe source:

```
probe=FALSE   <- -lmkl_gf_lp64 -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl
probe=TRUE    <- -lmkl_gf_lp64 -lmkl_gnu_thread -lmkl_core -lpthread -lm -ldl
```

## Outstanding gate (Linux only)

`readelf -d` on rebuilt `metis` (math-false, runtime via the new injection) and
`strumpack` (math-true) for both `mkl` and `intel`, confirming `NEEDED libgomp.so.1` /
`libiomp5.so` survives. Both auditors named this as the real check; the dev host cannot
run it. Grok additionally flags intel+MPI: `mpicc` must forward `-qopenmp` to icx now
that the `-liomp5` backstop is gone.
**Approved by:** Christian, 2026-08-18 ("make it so") — this is the packaging/ABI
decision that `doc/MKL_ABI_POLICY.md` and the previous round left explicitly to him.

## Problem

`build_common.get_cmake_args:785` sets `CMAKE_C_STANDARD_LIBRARIES` and
`CMAKE_CXX_STANDARD_LIBRARIES` from `math_common.get_mkl_serial_link_line`, whose last
library is the OpenMP runtime (`-lgomp` on GNU flavors, `-liomp5` on Intel).

Measured consequence (`doc/MKL_ABI_POLICY.md`, "A second, unrelated hazard"): when that
variable contains `-lgomp`, any CMake `try_compile` linking an OpenMP imported target
links with **no OpenMP runtime at all** and fails on undefined `GOMP_*`. The outer
library link is unaffected, so the package builds and installs fine and only the
configure-time feature probes lie. That is how `scls-mkl-strumpack` shipped with its
OpenMP tasking compiled out on el9, el10 and amzn2023.

## Why the previous round rejected this, and what changed

Both auditors rejected an unconditional strip because packages that link threaded MKL
but are **not** compiled with `-fopenmp` would lose their OpenMP `NEEDED` entry, and
`AutoReqProv: no` means nothing would catch it.

That objection is answerable, because the two sets are **disjoint**. Measured over all
cmake recipes:

- **Compiled with `-fopenmp`/`-qopenmp`** (`features.openmp: true`) — the set whose
  probes are poisoned: butterflypack, ensmallen, gklib, metis, mlpack, parmetis, slate,
  strumpack, suitesparse, sundials, superlu_dist, vtk, zfp.
- **Link math but not compiled with OpenMP** (`features.math`, `features.openmp: false`)
  — the set the auditors were protecting: armadillo, arpack-ng, blaspp, blaze, cereal,
  exodus, lapackpp, netcdf, scalapack, superlu.
- Intersection: **empty**.

So the strip can be made conditional on `features.openmp`, which is simultaneously:

- exactly the set that needs it (their probes are the ones failing), and
- exactly the set where the runtime is guaranteed by another route — `-fopenmp` /
  `-qopenmp` is already in `CFLAGS`/`CXXFLAGS`/`FCFLAGS` for these recipes as of commit
  `80697cd`, and the compiler driver adds the runtime to every link it performs.

Packages with `features.openmp: false` keep today's link line byte-for-byte. The
auditors' rejection reason is removed rather than argued away.

## Proposed change

### C5.1 — `math_common.get_mkl_serial_link_line` gains an opt-out

```python
def get_mkl_serial_link_line(flavor: Dict, with_openmp_runtime: bool = True) -> str:
```

Default `True`, so `%{mkl_linker_flags}`, `get_mkl_mpi_link_line` and every existing
caller are unchanged. Both auditors asked specifically that `%{mkl_linker_flags}` not be
touched; the default preserves that.

### C5.2 — `build_common.get_cmake_args` passes `False` for OpenMP recipes

```python
uses_openmp = bool((recipe.get('features', {}) or {}).get('openmp'))
std_libs = get_mkl_serial_link_line(flavor, with_openmp_runtime=not uses_openmp)
```

`recipe` is already the first parameter of `get_cmake_args`, so nothing needs threading
through. The existing comment block above that line is rewritten to explain why the
OpenMP runtime is deliberately absent for OpenMP recipes, with a pointer to the policy
doc — otherwise the next person "fixes" it back.

### Not proposed

- No change to `get_mkl_mpi_link_line` or `%{mkl_linker_flags}`.
- No change to the OpenMP runtime *policy* (gnu → gomp, intel → iomp5).
- No recipe or flavor edits. The `recipes/strumpack.yaml` probe pin stays as
  belt-and-braces; it is now redundant but harmless, and removing it would be an
  untested change on top of an untested change.

## Expected effect on generated specs

Only mkl/intel flavors, only recipes with `features.openmp: true`:
`CMAKE_C_STANDARD_LIBRARIES` and `CMAKE_CXX_STANDARD_LIBRARIES` lose their trailing
`-lgomp` (mkl) or `-liomp5` (intel). Everything else byte-identical.

## Verification plan

- [x] `--spec-only` for every recipe x seven flavors, old vs new, diffed
- [x] Assert the ONLY diff is the dropped runtime, and only on the 13 openmp cmake
      recipes on mkl/intel — in particular assert the 10 `openmp: false` math recipes
      are byte-identical
- [x] Re-run the local cmake probe harness with the stripped line to confirm the
      STRUMPACK probes now pass (this is the whole point)
- [x] **Linux gate, cannot be done on the dev host:** `readelf -d` on a rebuilt
      package from each set, confirming (a) an openmp recipe still has
      `NEEDED libgomp.so.1`, via `-fopenmp` rather than via the standard-libraries
      slot, and (b) an `openmp: false` recipe is unchanged

## Open questions for the auditors

1. Is the disjointness argument sound, or is there a package compiled without
   `-fopenmp` that nevertheless relies on the standard-libraries slot for an OpenMP
   symbol it references directly?
2. Does `-fopenmp` at link time reliably add the runtime for **shared library** links
   as well as executables, on both GCC and icx? The whole safety argument rests on it.
3. `features.openmp` gates the *SCLS* compile flags. Can an upstream cmake project with
   `features.openmp: false` still enable OpenMP internally via its own
   `find_package(OpenMP)` and end up needing the runtime we just removed?
4. Does anything other than `get_cmake_args` consume `CMAKE_<LANG>_STANDARD_LIBRARIES`?
5. Is leaving the now-redundant `recipes/strumpack.yaml` probe pin the right call, or
   does a redundant pin become a lie once the root cause is fixed?
