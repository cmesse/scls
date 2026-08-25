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

## Open questions for future work

1. **What actually triggers the intermittent PRRTE drop?** Best guess is a
   `make -j` install-recursive race in `3rd-party/prrte/src/tools/`. Cheap
   next diagnostic: capture a full `make V=1 install` log on a broken build,
   grep for the `install-recursive` line under `3rd-party/prrte/` and for any
   swallowed non-zero exit. If reproducible, force `make -j1 install`
   in the openmpi recipe and see if the failure vanishes.
2. **Is Rocky truly immune, or has it just not been observed?** The failure
   is intermittent even on Ubuntu, so the honest answer is "sample size too
   small to say either way." If it appears on a Rocky host, the diagnosis
   commands above apply identically (`rpm -ql` instead of `dpkg -L`).
