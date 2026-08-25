# 2026-08-24 — SUNDIALS 7.8.0 test failures and the openmpi/PRRTE drop

## Purpose

You are picking this up on a different host (probably a RedHat-family box) and
need to know what problem was diagnosed on the Ubuntu 24.04 build host, what
fixes were committed to the recipes, and how to tell whether the same failure
mode is present on your host. Two independent problems were untangled in the
same session — read both sections, they interact.

## Symptom the user reports

`./scls build sundials` on the debug (or gcc) flavor fails at the ctest stage.
Twenty tests fail, all named `test_*_mpi_*`, `*_parallel_*`, `test_nvector_petsc_*`,
`ark_test_heat2D_mri_*`, or `test_sunnonlinsol_petscsnes`. Plus a preceding
symbol-lookup crash on `test_sundials_logger`.

## Fix 1 — sundials `test.commands` prepends LD_LIBRARY_PATH

**Failure signature.** `ctest` aborts almost immediately with:
```
test_sundials_logger: symbol lookup error: [...]/test_sundials_logger:
    undefined symbol: SUNLogger_SetQueueAndFlushMsgFns
```
Discovery is `PRE_TEST` (recipe sets `-DCMAKE_GTEST_DISCOVER_TESTS_DISCOVERY_MODE=PRE_TEST`),
so cmake runs the binary at ctest time to enumerate cases — and dies.

**Root cause.** `SUNLogger_SetQueueAndFlushMsgFns` is new in 7.8.0. CMake's
build RUNPATH on the test binaries starts with `%{prefix}/lib` (pulled in via
`-L` from GTest / MPI / PETSc), then the in-tree build dirs. So the loader
resolves `libsundials_core.so.7` to the *installed* 7.7.0 copy instead of the
just-built 7.8.0, and any new symbol lookup fails. 7.7.0 didn't hit this
because the older lib satisfied every symbol referenced by its own tests.

**Fix.** `recipes/sundials.yaml` `test.commands` now prepends every in-tree
`build/src/**/lib*.so*` directory to `LD_LIBRARY_PATH` before calling `ctest`.
Uses absolute paths (relative paths break because ctest chdir's into each
test's working dir). Verify by looking at the recipe — the block starts with
`libdirs=$(find "$PWD/src" -name 'lib*.so*' ...)`.

**Diagnosis on your host.** If sundials tests immediately die with
`undefined symbol: SUNLogger_*`, the recipe fix is either missing or
LD_LIBRARY_PATH is being clobbered. Confirm with:
```
grep -A4 'test:' recipes/sundials.yaml | head
```
Should show the `libdirs=...` line.

## Fix 2 — openmpi missing PRRTE (`prterun`, `prte`, `libprrte`)

**Failure signature.** Once the sundials LD_LIBRARY_PATH fix is in place, the
next wall is 20 MPI-launched tests failing with:
```
Open MPI's mpirun command was unable to find an underlying prterun
```
`/opt/scls/<flavor>/bin/mpirun --version` also fails with the same message.

**Root cause.** The installed `scls-<flavor>-openmpi_5.0.10-2` `.deb` shipped
`libmpi.so`, `libopen-pal.so`, `liboshmem.so`, `mpirun`, `ompi_info`, and the
compiler wrappers — but zero PRRTE content. No `prte`, `prterun`, `prted`,
`pterm`, `prte_info`, `libprrte.so.3.0.13`, `share/prte/`, or `include/prte/`.
OpenMPI 5.x `mpirun` is a tiny launcher that execs `${prefix}/bin/prterun`;
with prterun missing, every MPI-launched process fails to start.

**Confusing part — read carefully.** This failure is INTERMITTENT. The exact
same recipe, on the exact same Ubuntu 24.04 host, produced:
- 2026-08-23 15:41 — batch ASC-2026 rebuild → broken (no PRRTE in the deb)
- 2026-08-23 21:01 — targeted rebuild of same NEVRA → correct (PRRTE present)
- 2026-08-24 01:11 — batch gcc-flavor rebuild → broken again
- 2026-08-24 12:32 — targeted rebuild → correct

No recipe change between those runs, no code change since 2026-08-19. My
initial "flex missing → LEX=: → prterun silently dropped" hypothesis is
**wrong**: the 21:01 debug rebuild succeeded without flex installed. The
tarball ships `hostfile_lex.c` newer than `hostfile_lex.l` deliberately so
consumers don't need flex, and Python's `tarfile.extractall(filter='data')`
preserves mtimes. The real trigger is unknown — most likely a race in
`make -j8` under system load that skips `3rd-party/prrte/src/tools/`
install-recursive without erroring out, but that's a hypothesis, not
confirmed. Do not repeat my mistake of writing "flex fixed it" as if it were
the root cause.

**Fix applied (defence in depth, not root-cause).**
- `recipes/openmpi.yaml`: `release: 3`, added `flex` to
  `rpm_build_requires.all:`. Cost is zero; matches what RHEL/Rocky base groups
  already carry; eliminates one class of silent-failure mode should automake's
  LEX rule ever fire (if a future host has flex missing AND mtimes are skewed
  from patching).
- `packaging/system_packages.yaml`: added `flex: flex` mapping so
  `deb_builder.check_system_build_deps` fails loudly on any Ubuntu host that
  lacks it.

**Diagnosis on any host — this is the check that matters.** Given a suspect
openmpi install under `/opt/scls/<flavor>`:
```
/opt/scls/<flavor>/bin/mpirun --version     # must print "mpirun (Open MPI) 5.0.10"
ls /opt/scls/<flavor>/bin/prterun           # must exist as symlink → prte
dpkg -L scls-<flavor>-openmpi | grep -c prterun   # Ubuntu
rpm -ql scls-<flavor>-openmpi | grep -c prterun   # RedHat
```
If `mpirun --version` prints the "unable to find prterun" banner, or the
`prterun` file is missing, the openmpi install is broken regardless of what
the NEVRA claims. Rebuild openmpi for that flavor — a single targeted
`./scls build openmpi` has empirically worked in every case observed.

**Cross-check the actual .deb / .rpm** rather than the installed tree, because
the pruner deletes superseded artifacts by default:
```
dpkg -c /path/to/scls-<flavor>-openmpi_*.deb | grep -Ec 'prte|prterun|libprrte'
```
A correct openmpi package on this stack has ~3078 files under
`/opt/scls/<flavor>/`. A broken one has ~2685. That ~400 file gap is the
missing PRRTE tree.

**Regression path if this recurs undetected.** OpenMPI's `libmpi.so` is still
present in a broken package, so every downstream package's *link* step
succeeds. But any downstream `test:` step that shells out to `mpirun` / `mpiexec`
fails. On this stack that's SUNDIALS, PETSc (implicitly, via `mpiexec`),
HDF5, SLATE, MUMPS, ScaLAPACK, ARPACK-NG, SuperLU_DIST, STRUMPACK,
BUTTERFLYPACK, SLEPc. If tests aren't gate-of-packaging for those recipes,
the failure is invisible until a user runs `mpirun` on the installed stack.

**Rebuilding order to recover from a broken openmpi.** Rebuild openmpi first,
verify the tools land in the destdir (`find work/build/destdir -name prterun`
before packaging finishes), install the fresh package, then rebuild any
downstream package whose test step actually exercises MPI. Link-only
consumers don't need a rebuild.

## What was left uncommitted at handoff

Diff since last commit (5 files, 51 insertions, 2 deletions):
- `recipes/openmpi.yaml`
- `recipes/sundials.yaml`
- `packaging/system_packages.yaml`
- `changelogs/openmpi.md`
- `changelogs/sundials.md`

Plus pre-existing untracked `flavor.conf` changes from the flavor-switching we
did during diagnosis.

## Follow-up on a Rocky 9.8 host (2026-08-24)

The RedHat-side question above was investigated on Rocky Linux 9.8. Summary:
**not observed on RHEL, but RHEL is structurally just as exposed.** Two of the
claims made earlier in this document turned out to be wrong; they are corrected
below rather than edited out, so the reasoning stays auditable.

### Empirically clean — 7/7 builds good

| Artifact | Total files | PRRTE files | `prterun` |
|---|---|---|---|
| `scls-{debug,gcc,mkl}-openmpi-5.0.10-1` (May 2026) | 2969-2970 | 323 | present |
| `scls-{debug,gcc,mkl}-openmpi-5.0.10-2` (Aug 2026) | 3016-3017 | 364 | present |

All three installed flavors print `mpirun (Open MPI) 5.0.10`, carry
`bin/prterun -> prte`, and ship `libprrte.so.3.0.13`. Every openmpi package ever
built on this host contains all five PRRTE tools.

Note the file-count baseline **differs from the Ubuntu numbers quoted above**:
~3017 is correct on RHEL, not ~3078. Do not port that threshold across distros
-- check for `prterun` directly instead.

### Why RHEL has not tripped it

Both preconditions for the flex mechanism are absent here:

1. `flex-2.6.4-9.el9` is installed, so `3rd-party/prrte/Makefile` carries
   `LEX = flex`; the `LEX=:` no-op fallback cannot engage.
2. In the leftover build tree, `hostfile_lex.c` (12:26:15) is newer than
   `hostfile_lex.l` (12:21:29), so automake's LEX rule never fires at all.

### Correction 1 — the packagers do NOT protect RHEL

It is tempting to assume the RPM path is safe because SCLS ships `files/*.txt`
manifests and rpmbuild fails loudly on a listed-but-missing file. That is true
for 51 of 55 recipes. **openmpi is not one of them.** It sets
`rpm_files_auto: true` (`recipes/openmpi.yaml:10`), which
`templates/default.spec.j2:342` implements as:

```
find %{buildroot}%{prefix} -type f -o -type l | sed 's|^%{buildroot}||' > %{_builddir}/filelist.txt
```

`%files` is therefore *whatever the buildroot happens to contain*. A short
install yields a smaller-but-valid RPM and `rpmbuild` exits 0 -- the same silent
failure mode as the `.deb`. The unprotected set is exactly four recipes:
`openmpi`, `ucx`, `vtk`, `libunwind`.

Nor do tests catch it: openmpi's `test:` is `make check`, which runs the in-tree
unit tests before install and never invokes `prterun`.

Related: `files/openmpi.txt` is stale -- a 4.x-era manifest listing `orterun`,
`orted`, `ortecc`, `mpiCC`, with **zero** PRRTE entries (1015 lines against 3017
files shipped). It is inert today because `rpm_files_auto` bypasses it, but
anyone flipping that flag off to regain a safety net would break the build
immediately.

### Correction 2 — the `make -j install` race hypothesis cannot be right

Open question 1 previously blamed a `make -j8 install-recursive` race. Neither
install path is parallel:

- **RPM:** `rpm --eval '%make_install'` on Rocky 9.8 gives
  `/usr/bin/make install DESTDIR=... INSTALL="/usr/bin/install -p"` -- no `-j`.
  (`_smp_mflags` is `-j8`, but `%make_install` does not reference it.)
- **deb:** `python/deb_builder.py:572` runs
  `['make', 'install', f'DESTDIR={self.destdir}']` -- no `-j`.

Only the *build* step is parallel. If a race is responsible, it is in
`make -j8` build, not install, and `make -j1 install` would not have fixed it.

### Guard added

Since the root cause is still unknown on either distro, `recipes/openmpi.yaml`
now gates on the symptom: an `install.post` assertion that `prte`, `prterun`,
`prted`, `pterm`, `prte_info` and `libprrte.so` exist in the install tree,
exiting non-zero with an explanatory message when they do not. It renders into
`%install` ahead of the filelist step (line 151 vs 184 in the generated spec),
so a short install fails the build instead of shipping.

Scoped to 5.x via `case %{version} in 5.*)`, because the lbl flavor pins 4.1.6
and uses ORTE, not PRRTE; lbl renders `case 4.1.6 in 5.*)` and no-ops.
`%{version}` is substituted at generation time by both `rpm_builder.check_args`
and `unix_builder.check_args`, so the guard is live on RPM, deb and macOS paths
alike.

Verified on Rocky 9.8: `rpmspec -P` parses the generated spec; the shell logic
was exercised standalone against a complete tree (passes), a PRRTE-less tree
(fails), a dangling `prterun` symlink with `prte` removed (fails), and a 4.1.6
tree with only ORTE (no-ops). **Not yet verified by a full `rpmbuild` run** --
that is the outstanding gate.

### Trap hit while adding the guard: `%install` in changelog prose

The first `rpmbuild` of the guarded spec failed with:

```
error: line 300: second %install
```

This was **not** the guard. `changelogs/<package>.md` is copied verbatim into
the spec's changelog section, and the changelog entry written for this work
described the guard as rendering "into `%install`". RPM expands macros in
changelog text, and `%install` is a *defined macro* whose expansion begins with
a newline (`rpm --eval '%install'` prints an empty line then `%install`). The
newline pushes the token to column 0, where the parser reads it as a genuine
section header -- hence "second %install".

It is specific to that one word. Tested on Rocky 9.8, every other spec section
name is inert in changelog prose because none of them is a macro:

| Written in changelog | `rpm --eval` result | Effect |
|---|---|---|
| `%install` | newline + `%install` | **breaks the spec parse** |
| `%files`, `%prep`, `%build`, `%check`, `%clean`, `%package`, `%changelog`, `%post`, `%pre`, `%postun`, `%preun`, `%description` | returned unexpanded | harmless |

So `changelogs/petsc.md:9`, which mentions `%files`, is fine and needs no edit.
Only the percent-prefixed word "install" has to be avoided in changelog prose.

Worth knowing because the failure surfaces at a line number deep in the
changelog, hundreds of lines away from whatever you actually just changed,
which makes it read like a defect in the new build logic.

Process note: this got through because the spec was validated with `rpmspec -P`
*before* the changelog entry was written, so the text that broke it was never in
the spec that passed. Generate the spec last, after every file the generator
reads.

## Open questions for future work

1. **What actually triggers the intermittent PRRTE drop?** Still unknown, and
   now without a leading hypothesis -- see Correction 2. The install is serial
   on both distros, so look at the parallel *build* instead: capture
   `make V=1 -j8` output on a broken build and check whether
   `3rd-party/prrte/src/tools/` linked at all, or whether a subdir failure was
   swallowed. The new guard makes a recurrence loud, which should also make it
   easier to catch in the act.
2. **Is Rocky affected?** Structurally yes, empirically not observed in 7/7
   builds -- see above. The two flex preconditions are absent on Rocky, which
   may be the whole explanation, or may be coincidence given the failure is
   intermittent even on Ubuntu.
3. **Should `ucx`, `vtk` and `libunwind` get the same treatment?** They share
   `rpm_files_auto: true` and therefore the same silent-drop exposure. No
   failure has been observed for any of them; the question is whether a
   critical-file assertion is worth adding pre-emptively.
