# Environment Changelog

## Version 2026-1 - Thu Sep 10 2026
- 2026-09-10: `share/scls/activate`, `activate.sh` and `deactivate.sh` are
  now sourceable from zsh (the macOS login shell) as well as bash. Under zsh
  the old scripts computed `SCLS` two directories above `$PWD` (no
  `BASH_SOURCE`) with no error, and the path helpers aborted on `${!var}`
  indirection before ever reaching `read -a`; downstream consumers such as
  BELFEM's find_scls.cmake then saw a wrong root. The scripts self-locate via
  `BASH_SOURCE` or zsh's prompt escape for the current file, fail loudly under any other shell, use only
  POSIX parameter expansion and `case` in the helpers, and run their body
  under a function-local `emulate -L sh` on zsh so a user's globsubst /
  extended_glob / nounset options cannot break them. They now also prune the
  install's own `$SCLS/` prefix and the bare `$SCLS` entry that
  CMAKE_PREFIX_PATH carries, not only the literal `/opt/scls/`, so
  PATH-style variables of a custom-prefix flavor are cleaned up too. Verified by sourcing the rendered
  scripts under bash 5.3 and zsh 5.9 (plain and with strict options).
