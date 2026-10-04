# Environment Changelog

## Version 2026-3 - Sat Oct 03 2026
- `activate` exports `OMP_CANCELLATION=TRUE` when SPRAL is installed (its
  registry entry exists) and the user has not set the variable; `deactivate`
  removes it only if activate set it; `scls env` lists it. SPRAL's SSIDS
  solver (Ipopt `linear_solver spral`) fails without it: hs071 ends in
  "Restoration Failed" (devlog/dl20261003_spral_recipe.md). `OMP_PROC_BIND`,
  which SPRAL also asks for, is deliberately not set, since it would pin the
  threads of every OpenMP program.
- New field `meta_release: 2` for the flavor meta-packages (not this
  package's release). `scls-<flavor>` becomes 2026-2 on RPM and DEB because
  spral and ipopt join its Requires; 2026-1 is already published and is
  never replaced. Both builders, `scripts/deb_drop_select.py`, and the
  website's scls-release/keyring links now read real releases instead of
  assuming 1 (Christian, 2026-10-03).

## Version 2026-2 - Sun Sep 13 2026
- Declare the host toolchain as a runtime dependency. The installed stack
  is a development stack and users compile against it, but `AutoReqProv: no`
  meant no package pulled in a compiler; RHEL hosts only worked because the
  build hosts already had one. `rpm_requires:` on this recipe now carries
  `gcc`, `gcc-c++`, `gcc-gfortran`, `glibc-devel` and `make` for the flavors
  that build with the host GCC (`gcc`, `mkl`, `debug`, `gcc-mkl-cuda`); on
  Debian that translates to `gcc, g++, gfortran, libc6-dev, make`, the
  build-essential set. `lbl` (ships its own gcc) and `intel` (oneAPI
  compilers, no distro package) get only `make`.
- Add `rpm_recommends:` with `doxygen` as a weak dependency (`Recommends:`
  on both RPM and DEB). Nothing in the stack runs doxygen; it is a
  convenience for developers, and on RHEL 9/10 it lives in CRB, so a hard
  requirement would break `dnf install scls-<flavor>` on a fresh host.
- The generated environment spec now honours the recipe `release:`, emits
  `Requires:`/`Recommends:` and sets `AutoReqProv: no` like every other
  SCLS package.

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
- 2026-04-03: Initial generated environment package for the 2026 stack.
