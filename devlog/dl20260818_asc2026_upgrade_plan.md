# Devlog 2026-08-18 — ASC 2026 final upgrade: plan and open decisions

**Date:** 2026-08-18
**Topic:** the last package upgrade before the ASC 2026 release — what needs
rebuilding, in what order, and what must be decided first
**AIs involved:** Claude (plan), Codex + Grok (audited the builder change this plan
depends on)
**Claude Confidence:** high on the version data and the affected-package set; medium
on the hwloc/libevent SONAME risk, which is unverified
**Flavor / Host:** all flavors, four distros. Planned on the macOS dev host — no
`rpmbuild`, so nothing here is build-verified
**Verification:** `python python/update_checker.py all --json` (2026-08-17) for
versions; `python python/build_order.py recipes --flavor mkl` for ordering;
`--spec-only` diffs for the affected set. Every cell of the matrix is work for a
Linux build host.

## Summary

Fourteen packages have new upstream releases, and five more need rebuilding from the
OpenMP/MKL single-source-of-truth work (commit `80697cd`). This devlog records the
analysis and the decisions still outstanding; the live tick-off matrix lives in
`todo/asc2026_final_upgrade.md`, which is now tracked and so reaches the build host.
The matrix is deliberately not duplicated here — one living copy, no drift.

## Open decisions — settle these BEFORE starting the campaign

1. **C5 — strip the OpenMP runtime from `CMAKE_<LANG>_STANDARD_LIBRARIES`.**
   This is the root-cause fix for the cmake `try_compile` probe defect now documented
   in `doc/MKL_ABI_POLICY.md`. Both auditors rejected it as part of the builder patch:
   it changes the link line of every mkl and intel package, so it needs a full rebuild
   of both stacks plus a `readelf -d` check that packages with `features.math` and
   `features.openmp: false` (armadillo, arpack-ng, blaspp, blaze, lapackpp, scalapack,
   superlu) have not lost their OpenMP `NEEDED` entry.
   **If taken, it must land before the campaign, not after — otherwise the stack is
   built twice.** Packaging/ABI decision: Christian's call, not an AI vote.

2. **Release bumps for butterflypack, slate, superlu_dist.** Their build flags changed
   (`-fopenmp` restored) but their upstream versions did not, so without `release: 2`
   plus a changelog entry the rebuilt RPMs will not supersede what is in the repo.
   Not yet applied — needs approval per protocol §7.

3. **hwloc 2.13 → 2.14 SONAME.** `hwloc` and `libevent` are dependencies of `pmix` and
   `openmpi`, neither of which is getting a version bump, and `AutoReqProv: no` means
   RPM/DEB metadata will not catch a SONAME change — the same failure mode this
   document's parent section describes for MKL. Check `libhwloc.so.*` before and
   after. If the major moves, `pmix` and `openmpi` need release bumps too, and then so
   does everything MPI, which enlarges the campaign substantially.

## Packages with new upstream releases

| package | current → latest | notes |
|---|---|---|
| armadillo | 15.2.7 → 15.4.2 | |
| binutils | 2.46.0 → 2.47 | `include_flavors: ['lbl']` — not in the DBG/GCC/MKL matrix |
| cmake | 4.3.3 → 4.4.2 | build tool only; no downstream rebuild, but it changes every `try_compile` |
| exodus | 2025.10.14 → 2026.08.11 | ~10-month jump; re-check `files/exodus.txt` and patches |
| gcc | 16.1.0 → 16.2.0 | `include_flavors: ['lbl','macos']` — not in the matrix |
| googletest | 1.17.0 → 1.18.0 | |
| hwloc | 2.13.0 → 2.14.0 | SONAME check — see open decision 3 |
| libevent | 2.1.12 → 2.1.13 | SONAME check — see open decision 3 |
| libtool | 2.5.4 → 2.6.2 | `include_flavors: ['macos']` — not in the matrix |
| mumps | 5.9.0 → 5.9.1 | |
| netcdf | 4.10.0 → 4.10.1 | |
| petsc | 3.25.2 → 3.25.4 | |
| scotch | 7.0.11 → 7.0.13 | feeds mumps, petsc, strumpack — sequence first |
| vtk | 9.6.2 → 9.7.0 | `files/vtk.txt` has version-stamped paths; keep X11/XQuartz on macOS |

## Also requires a rebuild (no upstream bump)

| package | reason | state |
|---|---|---|
| sundials 7.7.0 → 7.8.0 | upstream bump *and* `-fopenmp` restored | version bump carries it |
| strumpack 8.0.0-2 | probe pin + `-fopenmp` restored | `release: 2` landed |
| butterflypack 4.1.0 | `-fopenmp` restored | needs `release: 2` |
| slate 2025.05.28 | `-fopenmp` restored | needs `release: 2` |
| superlu_dist 9.2.1 | `-fopenmp` restored | needs `release: 2` |

`slepc` is deliberately excluded: its `configure.type: custom` recipe emits no
`CFLAGS`/`CXXFLAGS`/`FCFLAGS` in the generated spec, so its spec is byte-identical
before and after the builder change. It takes its flags from PETSc and comes along
with the petsc rebuild.

## Build order

From `build_order.py`, mkl flavor. Low group numbers first; packages within a group
are independent.

| group | packages in this campaign |
|---|---|
| 2 | cmake, libevent |
| 3 | googletest, hwloc, vtk |
| 6 | scotch |
| 7 | mumps, netcdf, slate, superlu_dist |
| 8 | armadillo, butterflypack, exodus |
| 9 | strumpack |
| 10 | petsc |
| 11 | sundials |

## Build matrix

Four distros x flavor, AMZN 2023 having no DBG build:

```
           ||      RHEL 9     ||     RHEL 10     || AMZN 2023 || Ubuntu 24 LTS
Package    || DBG | GCC | MKL || DBG | GCC | MKL || GCC | MKL || DBG | GCC | MKL
```

The matrix itself, with one tickable cell per build, is
`todo/asc2026_final_upgrade.md`. `binutils`, `gcc` and `libtool` are flavor-gated out
of it and appear there as `n/a` rows; they still need their version bumps landed for
the `lbl` and `macos` builds.

## Per-package bump hygiene

For each version bump: update `recipes/<pkg>.yaml`, update `changelogs/<pkg>.md`,
re-check `files/<pkg>.txt` for new or renamed installed files and version-stamped
directories (prefer `%{version}`), and re-check `patches/<pkg>/` for hunks that no
longer apply.

## Open Questions

- Does the cmake 4.4.2 bump change `try_compile` behaviour in a way that interacts
  with the `-lgomp` hazard? Re-check one MKL cmake package's installed config header
  after that bump regardless of how C5 is decided.
- Which of the unchecked cmake packages (butterflypack, gklib, metis, parmetis, slate,
  vtk, zfp) silently lost a probe-detected feature on the mkl flavor?
- Actual STRUMPACK scaling payoff, measured from `factor time` lines rather than step
  wall-times.

## Files Updated

- doc/MKL_ABI_POLICY.md (new section on the `-lgomp` try_compile hazard)
- devlog/dl20260818_asc2026_upgrade_plan.md (this file)
- devlog/README.md
