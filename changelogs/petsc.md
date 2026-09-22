# Petsc Changelog

## Version 3.25.5-1 - Tue Sep 22 2026
- Updated to version 3.25.5
- `files/petsc.txt`: `lib/petsc/conf/modules/petsc/3.25.4` → `3.25.5`. `petsc-baijmkl-decls.patch` applies at fuzz 0.

## Version 3.25.4-1 - Wed Aug 19 2026
- 2026-09-10: `PETSC_ARCH=arch-<os>-c-opt` is now passed to configure as an
  argument for every flavor, matching what build/install already pinned, and
  the plain `gcc` flavor gets the same build/install entries the others had.
  Configure used to inherit an exported PETSC_ARCH (common in PETSc users'
  shells; `share/scls/activate` exports an empty one) and write its output
  there, after which make failed with "No rule to make target
  arch-darwin-c-opt/lib/petsc/conf/petscvariables". Note PETSc rejects an
  empty PETSC_ARCH outright (config/PETSc/options/arch.py:66-67), so the
  obvious `env: PETSC_ARCH: ""` is not a fix. The generated configure line
  gains one token on all flavors; the package is expected to be unchanged
  (the value is PETSc's own default for --with-debugging=0), so no release
  bump -- not build-verified on Linux yet.
- Updated to version 3.25.4
- Dropped lib/petsc/bin/petsclogformat.py from the file manifest; upstream no
  longer installs it.
- Removed 7431 individually listed files under share/petsc/{datafiles,examples,
  xml} from the manifest. The petsc-examples subpackage already claims those
  directories recursively, and the main %files excludes the same paths, so the
  entries were redundant -- their only effect was to break the build whenever
  upstream added or removed an example (3.25.2 -> 3.25.4 dropped 86 and added
  281). share/petsc/{bin,matlab,saws,suppressions} stay listed: the subpackage
  does not claim them.

## Version 3.25.2-1 - Mon Jun 08 2026
- Updated to version 3.25.2

## Version 3.25.0-1 - Mon Apr 13 2026
- Updated to version 3.25.0

## Version 3.24.5-1 - Sat Apr 04 2026
- Initial SCLS package for petsc 3.24.5
