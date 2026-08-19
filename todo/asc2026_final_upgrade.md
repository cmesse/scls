# ASC 2026 — final upgrade build tracker

**Date:** 2026-08-17, updated 2026-08-18
**Purpose:** last package upgrade before the ASC 2026 release. One row per package,
one cell per (distro, flavor) build.
**Scope:** 28 packages. This is the full transitive set for a flavor, derived on
2026-08-18 from `python python/build_order.py recipes --flavor debug` plus a
reverse-dependency closure over every recipe whose version or release changed —
not just the packages with upstream bumps.
**Column grouping** (Markdown has no merged header cells, so the prefixes carry it):

```
           ||      RHEL 9     ||     RHEL 10     || AMZN 2023 || Ubuntu 24 LTS
Package    || DBG | GCC | MKL || DBG | GCC | MKL || GCC | MKL || DBG | GCC | MKL
```

**Cell legend:** `[ ]` to do · `[x]` built **and installed** · `n/a` not built for
that flavor · `--` blocked (add a note under Blockers)

A cell is only ticked once the package is both rebuilt and installed on that host.
Built-but-not-installed stays `[ ]`; note it under Status instead.

---

## A. The campaign — all 28 packages, in build order

`why` explains what forces the rebuild: **up** = upstream version bump, **rel** =
release bump for the OpenMP runtime fix (commit `a101f89`), **casc** = unchanged
recipe, rebuilt because a dependency is.

| # | Package | why | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | cmake 4.3.3 → 4.4.2 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 2 | libevent 2.1.12 → 2.1.13 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 3 | ucx 1.20.0 → 1.20.1 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 4 | gklib 0.0.1-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 5 | googletest 1.17.0 → 1.18.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 6 | hwloc 2.13.0 → 2.14.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 7 | vtk 9.6.2 → 9.7.0 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 8 | zfp 1.0.1-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 9 | metis 5.2.1-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 10 | pmix 5.0.10-1 → -2 | casc (hwloc, libevent) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 11 | openmpi 5.0.10-1 → -2 | casc (hwloc, ucx, pmix) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 12 | superlu 7.0.1-1 → -2 | casc (metis) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 13 | hdf5 1.14.6-1 → -2 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 14 | parmetis 4.0.3-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 15 | scalapack 2.2.3-1 → -2 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 16 | scotch 7.0.11 → 7.0.13 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 17 | arpack-ng 3.9.1-1 → -2 | casc (openmpi) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 18 | mumps 5.9.0 → 5.9.1 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 19 | netcdf 4.10.0 → 4.10.1 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 20 | slate 2025.05.28-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 21 | superlu_dist 9.2.1-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 22 | armadillo 15.2.7 → 15.4.2 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 23 | butterflypack 4.1.0-1 → -2 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 24 | exodus 2025.10.14 → 2026.08.11 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 25 | strumpack 8.0.0-2 → -3 | rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 26 | petsc 3.25.2 → 3.25.4 | up | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 27 | slepc 3.25.1-1 → -2 | casc (petsc) | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| 28 | sundials 7.7.0 → 7.8.0 | up + rel | [x] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

Rows 1–28 are already in dependency order: building top to bottom is always safe.

## Build groups (parallelism)

From `python python/build_order.py recipes --flavor debug`. Packages in the same
group are independent and can build concurrently.

| group | packages in this campaign |
|---|---|
| 2 | cmake, libevent, ucx |
| 3 | gklib, googletest, hwloc, vtk, zfp |
| 4 | metis, pmix |
| 5 | openmpi, superlu |
| 6 | hdf5, parmetis, scalapack, scotch |
| 7 | arpack-ng, mumps, netcdf, slate, superlu_dist |
| 8 | armadillo, butterflypack, exodus |
| 9 | strumpack |
| 10 | petsc |
| 11 | slepc, sundials |

## Not part of this campaign

Gated to flavors this matrix does not cover. They still need their version bumps
landed in recipe + changelog for the `lbl` and `macos` builds:

- **binutils** 2.46.0 → 2.47 — `include_flavors: ['lbl']`
- **gcc** 16.1.0 → 16.2.0 — `include_flavors: ['lbl', 'macos']`. Also gained a
  `bin/cc` symlink on 2026-08-18; `gcc`, `g++` and `c++` existed but `cc` did not,
  so anything falling back to the historical name picked up the system compiler.
- **libtool** 2.5.4 → 2.6.2 — `include_flavors: ['macos']`

Retired (never built in any flavor, no dependents, recoverable from git history):
**ensmallen**, **mlpack** (2026-08-18) and **cereal** (2026-08-19). cereal was
orphaned when mlpack went; nothing in the stack referenced it afterwards. The
README's Boost rationale named all three as examples, so that sentence was
rewritten to stop citing packages that no longer exist.

## Status — RHEL 9 / debug (the host this is being run on)

| package | built | installed | note |
|---|---|---|---|
| cmake 4.4.2-1 | yes | yes | `files/cmake.txt` was regenerated; it still named `cmake-4.3` dirs |
| libevent 2.1.13-1 | yes | yes | dropped `libevent-ssl-test-use-sha256.patch`, upstreamed in 2.1.13 |
| ucx 1.20.1-1 | yes | yes | `-Wno-error=` → `-Wno-` flag fix; repackaged to own 34 dirs; dnf reinstall applied |
| gklib 0.0.1-2 | yes | yes | previously failed to build; `-fopenmp` now reaches the compiler |
| googletest 1.18.0-1 | yes | yes | SONAME moved 1.17.0 → 1.18.0; petsc + slepc broken until rebuilt |
| hwloc 2.14.0-1 | yes | yes | URL series dir fix + 5 new amdsmi files; SONAME `.so.15` stable |
| vtk 9.7.0-1 | yes | yes | repackaged in place to own 258 dirs; dnf reinstall applied |
| zfp 1.0.1-2 | yes | yes | no-op on debug (libzfp already linked libgomp); -2 carries the mkl/intel change |
| metis 5.2.1-2 | yes | yes | first package genuinely gaining `-fopenmp`; gklib dropped from runtime Requires |
| pmix 5.0.10-2 | yes | yes | 11 of 383 files changed by the relink; proved the NEVRA-collision case |
| openmpi 5.0.10-2 | yes | yes | configure verified against stack deps; 69 owned dirs from the template fix |
| superlu 7.0.1-2 | yes | yes | relinked against metis 5.2.1-2 |
| hdf5 1.14.6-2 | yes | yes | **Fortran interface enabled** (`--enable-fortran`); 27 .mod files + h5pfc now shipped |
| parmetis 4.0.3-2 | yes | yes | gained `libgomp` NEEDED; last package to drop the gklib Requires |
| scalapack 2.2.3-2 | yes | yes | first source build to exercise the `glob_dir_version()` %files glob |
| scotch 7.0.13-1 | yes | yes | scotch-shared.patch refreshed for 7.0.13; SONAME `libscotch.so.7.0` stable |
| arpack-ng 3.9.1-2 | yes | yes | relinked against openmpi; SONAMEs `.so.2` stable |
| mumps 5.9.1-1 | yes | yes | campaign's first integration point — links new scotch, metis, parmetis, scalapack |
| netcdf 4.10.1-1 | yes | yes | links rebuilt hdf5 C libs; SONAME `libnetcdf.so.22` stable |
| slate 2025.05.28-2 | yes | yes | near no-op on debug (3 of 43 files); -2 carries the intel/mkl link-line change |
| superlu_dist 9.2.1-2 | yes | yes | substantive relink (45 of 96 files) against rebuilt metis/parmetis/openmpi |
| armadillo 15.4.2-1 | yes | yes | manifest's 644 armadillo_bits headers collapsed to one glob; SONAME `.so.15` stable |
| butterflypack 4.1.0-2 | yes | yes | 15 of 98 files changed; relinked against arpack-ng + scalapack |
| exodus 2026.08.11-1 | yes | yes | **recipe url/extract_dir still named v2025-10-14** — would have shipped old code as new |
| strumpack 8.0.0-3 | yes | yes | OpenMP tasking macros confirmed defined; widest integration point |
| petsc 3.25.4-1 | yes | yes | manifest 7880 → 448 lines; repackaged after a `--short-circuit` misstep |

| slepc 3.25.1-2 | yes | yes | cleared the last stale `libgtest.so.1.17.0` reference |
| sundials 7.8.0-1 | yes | yes | bumped past the planned 7.7.0-2; petsc patch dropped as upstreamed, gtest patch regenerated |
## Blockers and things to check

- [ ] **`sudo` needs a password on this VM.** `sudo -n true` fails, so `./scls
      install` cannot run unattended and installs have to be done by hand (ucx was
      installed this way on 2026-08-18). Builds are unaffected.
- [x] **Cascade packages rebuild to an identical NEVRA — fixed.** All seven
      (pmix, openmpi, superlu, hdf5, scalapack, arpack-ng, slepc) now carry
      `release: 2`. Confirmed the hard way: pmix was rebuilt at 5.0.10-1 with 11
      of 383 files changed, and `dnf upgrade` silently did nothing because the
      NEVRA matched — the installed `libpmix.so.2.13.10` still digested to the
      April build. With the bump, `dnf upgrade` behaves normally and no
      `--reinstall` is needed.
- [ ] **OPEN NOW: petsc and slepc are unresolvable.** googletest versions its
      shared libs by full version, so installing 1.18.0 on 2026-08-18 removed
      `libgtest.so.1.17.0`, which both `libpetsc.so.3.25.0` and
      `libslepc.so.3.25.0` carry as `DT_NEEDED`. `ldd` reports "not found" for
      both. They are rows 26 and 27, so the campaign closes this — but until
      then anything loading PETSc or SLEPc on this host fails. Nothing else in
      the stack links gtest; sundials uses it for its test suite only.
- [x] **hwloc 2.13 → 2.14 SONAME — checked, stable.** Both ship
      `libhwloc.so.15` (only `.15.10.2` → `.15.10.3` moves). Verified after
      install that `libmpi.so.40` still resolves it. No blast radius beyond the
      packages already in the campaign.
- [ ] **`%check` is unreliable for already-installed packages.** Every stack
      binary carries `DT_RPATH=/opt/scls/debug/lib`, which outranks
      `LD_LIBRARY_PATH`, so a freshly built utility loads the *old installed*
      library during `%check`. This made hwloc 2.14.0's
      `test-hwloc-diffpatch.sh` segfault; forced against its own library with
      `LD_PRELOAD` it exits 0. Same class as the 2026-05-14 uninstall-on-rebuild
      stale-lib issue. Treat `%check` failures on upgraded packages as suspect
      until re-run against the new library.
- [x] **Unowned directories — root cause found and fixed.** The
      `rpm_files_auto` file list in `templates/default.spec.j2` claimed `%dir`
      only at `-maxdepth 1` under `lib/` and `share/`, and never under
      `include/`. RPM cannot remove a directory it does not own, so every
      versioned tree was orphaned on upgrade. For vtk that was 258 directories.
      The template now claims every directory at depth >= 2 under the prefix
      (first level excluded: it belongs to `environment`, and `lib` is a symlink
      to `lib64` on Linux). All four `rpm_files_auto` recipes are handled: vtk
      (+258 dirs), ucx (+34) and libunwind (+1) were re-wrapped from their
      existing payloads with digests unchanged; openmpi needs nothing extra
      because it is a cascade rebuild at row 11 and will pick the template up
      from source. vtk and ucx kept their release (unreleased artifacts);
      libunwind went to 1.8.3-2.
- [x] **parmetis gklib Requires — cleared.** The 4.0.3-2 rebuild dropped it.
      No package in the stack now declares a runtime dependency on gklib.
- [ ] **Orphaned vtk-9.6 directories on this host.** After the 9.7.0 upgrade,
      `/opt/scls/debug/lib/cmake/vtk-9.6` and `/opt/scls/debug/share/vtk-9.6`
      remain and `rpm -qf` reports both as "not owned by any package". The
      shared libraries and `bin/` wrappers were replaced cleanly; only these two
      directories lingered. A downstream `find_package(VTK)` could resolve the
      stale 9.6 config. Safe to remove by hand once confirmed nothing needs it.
- [ ] **Dead cmake option in the vtk recipe.** VTK 9.7.0 reports
      `VTK_BUILD_SCALED_SOA_ARRAYS` as an unused manually-specified variable.
      Harmless, but it should be dropped from `recipes/vtk.yaml`.
- [ ] **openmpi has hwloc's URL bug latent.** `recipes/openmpi.yaml` hard-codes
      the release series directory (`v5.0/`, and `v4.1/` in the lbl override)
      while interpolating `%{version}` into the filename, exactly as hwloc did.
      A minor bump will 403. Not triggered this cycle — openmpi is a cascade
      rebuild at its current version.
- [ ] **libevent 2.1.12 → 2.1.13 SONAME — checked, stable.** The rebuilt RPM
      still ships `libevent-2.1.so.7`, same as 2.1.12. No wider rebuild forced.
- [x] **slepc 3.25.1 against petsc 3.25.4 — fine.** 3.25.1 is the newest SLEPc
      release; SLEPc patch-releases independently of PETSc, so there is no
      3.25.4 to match. It built and links `libpetsc.so.3.25` cleanly.
- [x] **exodus 2025.10.14 → 2026.08.11 — no manifest drift.** Despite the
      ~10-month jump the file set is unchanged at 35 entries, and exodus has no
      patches. The real problem was the stale source url, recorded above.
- [ ] **Changelogs missing for most of the upstream bumps.** As of 2026-08-18,
      armadillo, exodus, googletest, hwloc, mumps, netcdf and petsc have no entry
      for their new version; `binutils` and `libtool` have no changelog file at
      all. `ensure_changelog_exists()` will auto-stub them at spec time with a
      generic message if nobody writes a real one first.
- [ ] **Patch drift unverified** for armadillo (1 patch) and petsc (1 patch).
      libevent's 5 remaining patches were verified to apply against 2.1.13.
- [x] **C5 open decision — taken.** The OpenMP runtime is stripped from
      `CMAKE_<LANG>_STANDARD_LIBRARIES` for cmake recipes with `features.openmp`
      (commit `a101f89`). The measured blast radius across all recipes × 4 flavors
      is exactly 10 packages: butterflypack, slate, strumpack, sundials,
      superlu_dist and zfp change on intel+mkl only; gklib, metis, parmetis and
      vtk change on all four flavors. `slepc` is unaffected — its spec is
      byte-identical, so it appears here only as a petsc cascade.
- [x] **cmake 4.3.3 → 4.4.2 is a build tool only** — no runtime linkage, so it
      forces no downstream rebuilds. It does change every `try_compile` in the
      stack; still worth spot-checking one MKL cmake package's config header.

- [ ] **Patch checks must use `--fuzz=0`.** rpmbuild applies patches with
      `--fuzz=0`; plain `patch --dry-run` defaults to fuzz 2 and will report a
      drifted patch as applying cleanly. This hid scotch-shared.patch's stale
      context until the real build rejected it. Always dry-run with `--fuzz=0`.

- [ ] **Recipes with hand-written source URLs need checking on every bump.**
      exodus's `version:` was bumped to 2026.08.11 while its `url:` and
      `extract_dir:` still named v2025-10-14 -- the tag uses dashes so
      `%{version}` cannot be interpolated. That would have packaged the previous
      release under the new version number, silently. `update_checker.py` does
      NOT catch it (it compares `version:` to upstream and never reads the url);
      `--verify-downloads` did not flag it either. The same hand-maintained-URL
      risk applies to hwloc, vtk and openmpi (release series directories).

- [ ] **Never use `rpmbuild --short-circuit` for a package you intend to
      install.** RPM stamps short-circuited output with
      `rpmlib(ShortCircuited) <= 4.9.0-1`, and dnf refuses it with "transaction
      check vs depsolve". It is a `%files`-testing tool only. To repackage an
      existing payload without recompiling, extract it with `rpm2cpio | cpio`
      and rebuild the metadata via `rpmrebuild -s <spec> -p <rpm>` (which
      comments the marker out), then `rpmbuild --buildroot <staging> -bb`. That
      is the route used for vtk, ucx, libunwind and petsc 3.25.4.

- [x] **sundials 7.8.0 — taken.** Bumped 2026-08-19, superseding the 7.7.0-2
      release bump (release reset to 1). Both patches failed against 7.8.0:
      `sundials-petsc-3.25-snesmonitorset.patch` is now obsolete (upstream guards
      the cast with `#if PETSC_VERSION_GE(3, 25, 0)` and PETSc's own
      `PetscCtxDestroyFn`, which is better than our hard-coded signature) and was
      dropped; `sundials-use-system-gtest.patch` had drifted too far for even
      default fuzz and was regenerated. 7.8.0 adds the sunnonlinsolauto module
      (4 files) to the manifest; nothing was removed.

## Per-package bump hygiene

For each: update `recipes/<pkg>.yaml` version, update `changelogs/<pkg>.md`,
re-check `patches/<pkg>/` for hunks that no longer apply, and re-check
`files/<pkg>.txt` for new or renamed installed files.

Version-stamped *directories* no longer need a manifest edit — `get_file_list()`
collapses them and `glob_dir_version()` rewrites the trailing version to a glob
(`share/cmake-4.4` → `share/cmake-[0-9]*`), which RPM expands against the
buildroot. Version-stamped *files* (e.g. `bin/vtkWrapPython-9.6`) are listed
individually and still need the manifest regenerated from a build.

## Evidence status

Rows 1–3 were built on an el9 x86_64 host (`rpmbuild` available, gcc 11.5.0),
against the `debug` flavor. **All 28 rows are built and installed. The RHEL 9 / debug column is complete.**

Everything in the RHEL 10, AMZN 2023 and Ubuntu 24 columns is untouched, as are
the GCC and MKL columns on RHEL 9. The MKL flavor additionally carries the
outstanding `.so.2` → `.so.3` host rebuild noted in `doc/MKL_ABI_POLICY.md`.

No package in this campaign has been runtime-tested. `%check` did not run for
libevent (its recipe defines no `test:` section) or ucx.
