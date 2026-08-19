# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

SCLS (Scientific Core Library Stack) is a Python-based build system for creating optimized scientific computing packages. It manages compilation and packaging of scientific software with different optimization flavors (e.g., gcc, mkl, debug, intel, lbl, macos) for both Linux (RPM) and macOS systems.

Read [`README.md`](README.md) first for the project philosophy, supported build modes, and the intended user-facing model. Use this file for repository-specific implementation guidance.

## License

This repository is licensed under the Lawrence Berkeley National Laboratory BSD variant, SPDX identifier `BSD-3-Clause-LBNL`. See [`LICENSE`](LICENSE) for the canonical text.

## Architecture

The build system has three main components:

1. **Recipe System** (`recipes/*.yaml`): Package definitions containing metadata, dependencies, build instructions, and configuration options
2. **Flavor System** (`flavors/*.yaml`): Platform and compiler-specific configurations (optimization flags, math libraries, MPI implementations)
3. **Builder System** (`python/`): Python modules that process recipes and flavors to generate build artifacts

Key modules:
- `rpm_builder.py`: Generates RPM SPEC files and builds RPMs for Linux systems
- `deb_builder.py`: Builds .debs for Debian/Ubuntu hosts. Uses `dpkg-deb`'s default compressor (zstd on Ubuntu 22.04+); the SCLS reprepro on belfem.lbl.gov is built from current EL9 sources so it ingests zstd-compressed .debs without `-Zxz`. Don't add `-Zxz` to "match" other call sites — there's nothing to match; the entire stack has shipped `.zst` from day one.
- `unix_builder.py`: Direct Unix-style builds and installs for Linux/macOS (also serves as the macOS builder)
- `build_order.py`: Resolves dependencies and determines parallel build order
- `build_common.py`: Shared utilities for downloading, extracting, building packages
- `math_common.py`: Math library configuration (MKL, reference BLAS/LAPACK, ScaLAPACK)
- `patch_common.py`: Patch management system

## Build Commands

### Using the `scls` wrapper (preferred)

The `scls` wrapper reads the active flavor from `flavor.conf` (YAML format) and dispatches to the correct builder (RPM on RHEL-family Linux, unix_builder elsewhere).

`flavor.conf` fields:
- `flavor:` (required) — active flavor name (e.g., `gcc`, `mkl`, `debug`)
- `python:` (optional) — path to the Python interpreter; defaults to `python3`
- `gcc_toolset:` (optional) — Red Hat gcc-toolset version (e.g., `15`); sources `/opt/rh/gcc-toolset-N/enable` for RHEL 8 hosts
- `extra_packages:` (optional) — list of packages to build even though the recipe's `include_flavors:` allowlist excludes the active flavor; also added to the meta-package's Requires

Available flavors and their install prefixes:

| Flavor   | Prefix            | Compiler | Math        |
|----------|-------------------|----------|-------------|
| `gcc`    | `/opt/scls/gcc`   | GCC      | OpenBLAS    |
| `mkl`    | `/opt/scls/mkl`   | GCC      | Intel MKL   |
| `debug`  | `/opt/scls/debug` | GCC      | Reference   |
| `intel`  | `/opt/scls/intel` | Intel    | Intel MKL   |
| `lbl`    | `/opt/scls/lbl`   | GCC      | OpenBLAS    |
| `macos`  | `/opt/scls`       | GCC      | OpenBLAS    |

Commands:

```bash
./scls build <package>       # Build a package
./scls build next            # Build the next unbuilt package in dependency order
./scls install <package>     # Install the last built RPM (Linux RPM mode only)
./scls install next          # Install the next unbuilt package's RPM
./scls spec <package>        # Generate SPEC file only (Linux RPM mode)
./scls list                  # List installed packages
```

`./scls install <package>` installs only the newest build of each package name,
selected by version-release rather than mtime, and once the transaction succeeds
it deletes the artifacts it superseded (binary and matching source RPM, or .deb).
That keeps one build per package in the output tree so the next install has
nothing stale to choose from. Pruning happens *after* the install, never before,
so a failed install still has the previous artifact to fall back on. Set
`SCLS_KEEP_OLD_ARTIFACTS=1` to keep them. For bulk cleanup across packages and
flavors, use `scripts/prune_old_packages.sh` (dry run by default).

### Direct builder invocation

```bash
# RPM SPEC file only (Linux):
python python/rpm_builder.py --package <package> --flavor <flavor> --spec-only

# Build RPM package (Linux):
python python/rpm_builder.py --package <package> --flavor <flavor>

# Generic Unix-style build/install:
python python/unix_builder.py --package <package> --flavor <flavor> build install

# macOS build with PKG creation:
python python/unix_builder.py --package <package> --flavor macos build install pkg

# Build order:
python python/build_order.py recipes --flavor <flavor>
# or use: ./buildorder
```

## Key Configuration Patterns

### Recipe Structure
Recipes in `recipes/*.yaml` define:
- Package metadata (name, version, source URL, license)
- Dependencies (can be flavor-specific via dict with `all:`, `<flavor>:` keys)
- Build configuration (configure type: autotools/cmake/custom/none)
- Features (fortran, mpi, openmp, math requirements)
- Flavor restrictions (`include_flavors:` allowlist, `exclude_flavors:` blocklist). If `include_flavors:` is omitted, the package builds for all flavors; an explicit empty list (`include_flavors: []`) means the recipe is never built by default and must be opted in via `extra_packages:` in `flavor.conf`.
- Pre/post build commands
- Test commands

### Flavor Configuration
Flavors in `flavors/*.yaml` specify:
- Platform (linux/macos)
- Compilers (cc, cxx, fc)
- Optimization flags (cflags, cxxflags, fcflags)
- Math library configuration (MKL, reference BLAS)
- MPI implementation
- Installation prefix
- Optional inheritance (`inherits:` field for flavor fallback)

### Build Order and Groups
- The `environment` package always builds first (Group 0), before all other packages
- Remaining packages are topologically sorted by dependency into groups
- Packages within the same group can be built in parallel
- The registry at `{prefix}/share/scls/registry/{package}.yaml` tracks built packages

### Build Process Flow
1. Load recipe and flavor configurations
2. Check if package should be built for flavor (via `should_build_package`)
3. Download and extract source tarball
4. Apply patches if defined (flavor-aware patch selection)
5. Configure (autotools/cmake)
6. Build with parallel make
7. Run tests if defined
8. Package or install directly (RPM for Linux when applicable, direct Unix install otherwise, PKG for macOS when requested)
9. Write registry entry to mark package as built

## Important Conventions

### Directory layout
- RPM builds use the repo-local `rpmbuild/` tree (explicit `_topdir`)
- Sources are cached in `work/`
- Build artifacts go to `work/`
- Patches are stored in `patches/<package>/`
- File tracking for packages stored in `files/<package>.txt`

### lib / lib64 (Linux From Scratch convention)
- On Linux, the `environment` package creates `lib64/` and symlinks `lib -> lib64`
- On macOS, `lib/` is used directly with no `lib64` split
- All other packages install into `lib/` — the symlink handles the rest on Linux

### Install hooks: `commands` vs `post`

Two install hooks exist and they handle `%{buildroot}` / `%{prefix}` differently — a gotcha when adding install-time logic (e.g. shipping an upstream `LICENSE` into the RPM).

- **`install.commands`** replaces the default install step. Write destinations as `%{buildroot}%{prefix}/…` explicitly. The RPM builder expands `%{prefix}` in place and leaves `%{buildroot}` alone; `unix_builder` handles `%{buildroot}` on its side. CWD is the source root.
- **`install.post`** appends commands after the default install step. Write destinations as `%{prefix}/…` (no `%{buildroot}`) — the RPM builder's post-processor rewrites the literal prefix to `%{buildroot}%{prefix}` for you, so writing `%{buildroot}%{prefix}` yourself produces a double `%{buildroot}` in the generated spec. CWD depends on the configure type: for cmake out-of-source builds it's the `build/` subdirectory, so use `../` to reach source-root files (e.g. upstream `LICENSE_en.txt`).
- `%{srcdir}` resolves to `$PWD` at spec-generation time. It's only safe in hooks where the shell's `$PWD` is the source root — e.g. `install.commands`, but *not* `install.post` for cmake recipes.

### MKL ABI handling

See [`doc/MKL_ABI_POLICY.md`](doc/MKL_ABI_POLICY.md). Applies to every flavor with `math.linalg: mkl` (`mkl`, `intel`, `gcc-mkl-cuda`). The MKL major SONAME (`libmkl_core.so.3` etc.) is baked into every consumer's `DT_NEEDED` at link time, and SCLS's `AutoReqProv: no` policy (deliberate — keeps deps deterministic and prevents `/usr/lib64/liblapack` sneak-in) means RPM/DEB metadata does not capture that SONAME. SONAME mismatches therefore surface at runtime, not install time; the mitigation is a CI rebuild on the affected build host when Intel bumps the MKL major. Linking against the unversioned `libmkl_*.so` symlink does *not* future-proof this — the SONAME is read from the resolved library's `DT_SONAME` at link time, regardless of the filename passed to `-l`.

### GKlib is static by design

See [`doc/GKLIB_STATIC_POLICY.md`](doc/GKLIB_STATIC_POLICY.md). GKlib builds as
`libGKlib.a` and is absorbed whole into `libmetis.so` (639 `gk_*` symbols), giving
downstreams the single-library `-lmetis` interface METIS 5.1.0 had. It is not shipped
shared: upstream publishes no releases, we pin a commit, and no SOVERSION is set, so a
shared build would carry an unversioned SONAME that `AutoReqProv: no` could never catch.
GKlib is therefore a build-time dependency only — nothing resolves against it at runtime.
A GKlib change means rebuilding metis and parmetis.

### Licensing

See [`doc/LICENSE_POLICY.md`](doc/LICENSE_POLICY.md) for the full package policy and rationale. Short version: distributed binary flavors avoid GPL-3 linkable libraries (FFTW is the canonical reason); GPL-3 build tools are fine when only executed during the build; GPL-2, LGPL, and CeCILL-C scientific libraries are allowed with source and notice compliance; GMP/MPFR/MPC use system `*-devel` packages on mainline Linux binary flavors and are built in-stack only on `lbl` and `macos`. Source RPMs and (on macOS) source-plus-binary DMGs are how SCLS satisfies the source-availability obligations.

### No Python / language bindings in the stack

SCLS deliberately does not ship Python, and recipes disable Python bindings (and other language-specific bindings such as Julia, R, Go) by default. The reason is that interpreter choice is highly site- and user-specific — system Python, pyenv, conda, spack, module files all coexist — and pinning one would conflict with users' own environments. Build-time use of the system Python as a tool (e.g. PETSc's configure, meson generators) is fine; what we avoid is runtime ABI coupling between the stack and a user's interpreter.

When adding a new recipe that offers language bindings, default to turning them off (`-DBUILD_PYTHON_BINDINGS=OFF`, etc.). Do not propose adding a Python recipe.

### Flavor-specific package restrictions
- `gcc` and `binutils` are only built for specific flavors (see their `include_flavors:` lists); on hosts where the system toolchain is too old (e.g. RHEL 8), they can be added to `extra_packages:` in `flavor.conf` or a `gcc_toolset:` can be specified instead
- Most flavors (gcc, mkl, debug, etc.) use the system compiler toolchain
- The `lbl` flavor builds its own GCC and binutils
- macOS builds GCC but uses system binutils

## Update Checker

`python/update_checker.py` checks upstream sources for newer versions of packages in the stack. Each recipe may declare an `update:` block; without one the package is reported as `undetermined`.

Usage:

```bash
python python/update_checker.py all              # check all recipes
python python/update_checker.py cmake            # check a single recipe
python python/update_checker.py all --json       # machine-readable output
python python/update_checker.py all --verify-downloads   # HEAD-check derived URLs
```

Supported strategies (set under `update:` in the recipe):

- `github_release` — latest GitHub release (`repo: owner/name`, optional `tag_prefix`)
- `github_tag` — latest semver-sorted tag (`repo: owner/name`, optional `tag_prefix`, `version_transform: dots_to_dashes`)
- `github_commit` — pin to a commit hash (`repo: owner/name`)
- `gitlab` — GitLab tag/release (`instance:`, `repo:`)
- `gnu_ftp` — GNU FTP mirror listing (`ftp_path:`)
- `html_regex` — scrape any page with a regex (`url:`, `pattern:` with a single capture group for the version)
- `skip` — explicitly do not check (pair with a `reason:`)

`max_major: N` is an orthogonal constraint: the checker filters out releases whose major component exceeds `N` and reports the highest within-pin version as the latest, surfacing the higher major separately as "blocked by pin". Use it to hold back ABI-breaking upstream bumps until downstreams have been re-validated. It can be combined with an explicit `strategy:` or layered on top of auto-detection (just `update: { max_major: N }`).

When bumping a version, also update `changelogs/<package>.md`, and re-check `files/<package>.txt` and any patches for drift (patch hunks, hard-coded version directories like `lib/cmake/<pkg>-<x.y.z>/`, new installed files). Version-stamped *directories* need no manifest edit: `rpm_builder.get_file_list()` collapses them to a single `%files` entry and `glob_dir_version()` rewrites the trailing version to a glob (`share/cmake-4.4` -> `share/cmake-[0-9]*`), which RPM expands against the buildroot. Version-stamped *files* (e.g. `bin/vtkWrapPython-9.6`) are listed individually and still need the manifest regenerated. Note `%{version}` is not a substitute where the directory carries only part of the version — RPM expands it to the full recipe version (`4.4.2`) while the directory is `4.4`.

## AI Collaboration

Multi-AI work in this repository follows [`doc/AI_COLLABORATION_PROTOCOL.md`](doc/AI_COLLABORATION_PROTOCOL.md) — read it before invoking an auditor or writing to the exchange. Short version:

- **Roles:** Claude explores and proposes; Codex and Grok audit read-only. Invoke them with `.claude/scripts/ask_codex.sh` / `.claude/scripts/ask_grok.sh` (prompt as an argument, or `-` for stdin).
- **Exchange:** AI-to-AI scratch lives in `tmp/ai_exchange/<slug>.md`, one topic per file. It is git-ignored and ephemeral. Pin the topic with `AI_EXCHANGE_SLUG=<topic>`.
- **Durable record:** `devlog/dlYYYYMMDD_topic.md` (tracked) is where a session's conclusions must land, alongside `changelogs/<package>.md` for version history and `doc/*.md` for standing policy. `todo/` is tracked too, so live plans and build trackers reach the build host — but it records intent, never the sole home of a finding.
- **Three-AI round:** `/cross-review` — Claude pre-registers its own findings, `scripts/cross_review.sh` dispatches both auditors blind, then Claude verifies every citation and writes the reconciliation table.
- **Auto-review:** opt-in post-commit auditor, installed by `scripts/install_autoreview_hook.sh` and gated on `SCLS_AUTOREVIEW=1`. `scripts/review_status.sh` shows the backlog and any open P0 flags.
- **Evidence discipline:** "reviewed" is not "verified". Name the gate that actually ran. The macOS dev host cannot run `rpmbuild`, so RPM claims top out at `--spec-only` generation and are written as pending a Linux build host.
- **Edit safety:** investigation is read-only by default; `recipes/`, `flavors/`, `files/`, `patches/`, and `python/` are edited only after explicit approval.

## Testing

Individual package tests are defined in recipe files under the `test:` section. Run tests during build by including test commands in the recipe.
