# Petsc Changelog

## Version 3.25.4-1 - Wed Aug 19 2026
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
