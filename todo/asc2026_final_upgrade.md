# ASC 2026 — final upgrade build tracker

**Date:** 2026-08-17
**Purpose:** last package upgrade before the ASC 2026 release. One row per package,
one cell per (distro, flavor) build.
**Version data:** `python python/update_checker.py all --json`, run 2026-08-17.
**Column grouping** (Markdown has no merged header cells, so the prefixes carry it):

```
           ||      RHEL 9     ||     RHEL 10     || AMZN 2023 || Ubuntu 24 LTS
Package    || DBG | GCC | MKL || DBG | GCC | MKL || GCC | MKL || DBG | GCC | MKL
```

**Cell legend:** `[ ]` to do · `[x]` built + installed · `n/a` not built for that
flavor · `--` blocked (add a note under Blockers)

---

## A. Packages with new upstream releases

| Package | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| armadillo 15.2.7 → 15.4.2 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| binutils 2.46.0 → 2.47 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| cmake 4.3.3 → 4.4.2 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| exodus 2025.10.14 → 2026.08.11 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| gcc 16.1.0 → 16.2.0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| googletest 1.17.0 → 1.18.0 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| hwloc 2.13.0 → 2.14.0 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| libevent 2.1.12 → 2.1.13 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| libtool 2.5.4 → 2.6.2 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| mumps 5.9.0 → 5.9.1 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| netcdf 4.10.0 → 4.10.1 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| petsc 3.25.2 → 3.25.4 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| scotch 7.0.11 → 7.0.13 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| vtk 9.6.2 → 9.7.0 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

Three rows are `n/a` across the board — they are gated to flavors this matrix does not
cover, so they carry no work here unless a host opts them in via `extra_packages:` in
`flavor.conf`:

- **binutils** — `include_flavors: ['lbl']`
- **gcc** — `include_flavors: ['lbl', 'macos']`
- **libtool** — `include_flavors: ['macos']`

They still need their version bumps landed in the recipe + changelog for the `lbl` and
`macos` builds; they just are not part of the DBG/GCC/MKL campaign.

## B. Also requires a rebuild this cycle (no upstream bump)

From the OpenMP/MKL work earlier today. Not part of your list — drop the section if you
would rather track it separately, but these ship changed build flags and will otherwise
be missed.

| Package | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sundials 7.7.0 → 7.8.0 (upstream bump) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| strumpack 8.0.0-2 (release bump, done) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| butterflypack 4.1.0-2 (release bump, TODO) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| slate 2025.05.28-2 (release bump, TODO) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| superlu_dist 9.2.1-2 (release bump, TODO) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

`slepc` is deliberately absent: its `configure.type: custom` recipe emits no
`CFLAGS`/`CXXFLAGS`/`FCFLAGS` in the generated spec, so the restored `-fopenmp` reaches
it only through PETSc. It comes along with the petsc rebuild.

## Build order

Dependency groups from `python python/build_order.py recipes --flavor mkl`. Build low
group numbers first; packages within a group are independent.

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

## Blockers and things to check before starting

- [ ] **hwloc 2.13 → 2.14 SONAME.** `hwloc` is a dependency of `pmix` and `openmpi`
      (groups 4 and 5), neither of which is getting a version bump. `AutoReqProv: no`
      means RPM/DEB metadata will not catch a SONAME change — the same failure mode
      `doc/MKL_ABI_POLICY.md` documents for MKL. Check `libhwloc.so.*` before and
      after; if the major moves, `pmix` and `openmpi` need release bumps too, and then
      so does everything MPI.
- [ ] **libevent 2.1.12 → 2.1.13** — same question, one level lower (`hwloc`, `pmix`,
      `openmpi` all depend on it). A patch-level bump should be SONAME-stable, but
      confirm rather than assume.
- [ ] **cmake 4.3.3 → 4.4.2** is a build tool only; no runtime linkage, so it does not
      force downstream rebuilds. It does change every `try_compile` in the stack —
      relevant given the `-lgomp` probe defect found today (see
      `devlog/dl20260817_strumpack_openmp_tasking.md`). Worth re-checking one MKL cmake
      package's config header after the bump.
- [ ] **exodus 2025.10.14 → 2026.08.11** is a ~10-month jump. Re-check
      `files/exodus.txt` and any patches for drift.
- [ ] **vtk 9.6.2 → 9.7.0** — minor bump, but `files/vtk.txt` embeds version-stamped
      paths. Also keep the X11/XQuartz choice on macOS.
- [ ] **scotch 7.0.11 → 7.0.13** feeds mumps, petsc and strumpack — sequence it before
      them (it is group 6, they are 7/9/10).
- [ ] **Open decision (C5):** whether to strip the OpenMP runtime from
      `CMAKE_<LANG>_STANDARD_LIBRARIES`. If taken, it changes the link line of every
      mkl and intel package and this whole campaign should run after it, not before.
      See `todo/openmp_single_source_of_truth.md`.

## Per-package bump hygiene (applies to every row in A)

For each: update `recipes/<pkg>.yaml` version, update `changelogs/<pkg>.md`, re-check
`files/<pkg>.txt` for new/renamed installed files and version-stamped directories
(prefer `%{version}`), and re-check `patches/<pkg>/` for hunks that no longer apply.

## Evidence status

Versions above are from the update checker's derived URLs; none were downloaded and no
build was run. The dev host is macOS, so `rpmbuild` is unavailable — every cell in this
matrix is work for a Linux build host.
