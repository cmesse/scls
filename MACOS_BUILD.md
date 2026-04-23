# Building SCLS on macOS

The `macos` flavor builds the full scientific library stack from source on
macOS using the `./scls` Unix build wrapper. This document covers prerequisites,
the build flow, and what to do when the GCC bootstrap fails.

## Status

- **Intel Macs:** the currently developed and tested platform.
- **Apple Silicon:** planned but unverified. Most likely to surface bootstrap
  issues.

macOS support is beta. Expect to read build logs.

## Prerequisites

- **Xcode Command Line Tools** — install with:

  ```bash
  xcode-select --install
  ```

  You need a working `clang`, `clang++`, `ld`, and `as` on `PATH`.

- **General comfort with the Unix toolchain** — installing CLT, understanding
  how linker and sysroot settings work, and knowing what to do when a build
  log points at an SDK or path issue.

- **Disk and time.** Budget a few tens of GB of disk (stack plus build
  artifacts) and several hours of wall-clock for the first full build. The
  `macos` flavor is the largest because it also builds its own GCC for
  Fortran support.

No Fortran-capable compiler is required up front — SCLS produces its own
GCC during the build. If the Clang-based bootstrap step fails, Homebrew's
prebuilt GCC is the supported fallback (see below).

## Build flow

Clone the repository:

```bash
git clone https://github.com/cmesse/scls.git
cd scls
```

Set the active flavor:

```bash
echo "flavor: macos" > flavor.conf
```

Build and install packages in dependency order until everything is done:

```bash
./scls build next
./scls install next
# repeat until `./scls build next` reports nothing to do
```

Activate the environment:

```bash
source /opt/scls/share/scls/activate
```

The `macos` flavor installs into `/opt/scls` directly (no `/macos`
subdirectory), because it is the only flavor on this platform. The Linux
flavors use a per-flavor prefix (`/opt/scls/gcc`, `/opt/scls/mkl`, and so
on) because several flavors coexist on the same host.

After activation, the installed `scls` command on `PATH` exposes a few
runtime queries: `scls help` lists them (`scls flavor`, `scls list`,
`scls info <package>`, `scls env`, `scls prefix`, `scls license`,
`scls deactivate`). This is distinct from the repo-local `./scls` wrapper
used during the build, which handles `build`, `install`, `spec`, `list`,
`order`, and `check-updates`. The wrapper has no `help` subcommand — run it
without arguments to see its usage.

## The GCC bootstrap

The macOS flavor builds a set of bootstrap packages with Apple Clang before
SCLS's own GCC takes over. The full order (from `flavors/macos.yaml`) is:
`m4`, `openssl`, `texinfo`, `zlib`, `autoconf`, `automake`, `bison`,
`libtool`, `make`, `pkg-config`, `sed`, `cmake`, and then `gcc`. Everything
built after `gcc` uses the SCLS-owned GCC.

The `gcc` step is the single most fragile part of the bootstrap sequence:

- Xcode SDK and sysroot path changes between Xcode versions have repeatedly
  broken the bootstrap in the wild.
- Apple's linker (`ld-prime` on newer Xcode) behaves differently from
  mainline `ld64` in ways that sometimes trip GCC's multi-stage build.
- Apple Clang occasionally lags mainline LLVM in flags GCC's `configure`
  expects.
- On Apple Silicon, the ARM64 bootstrap was spotty in GCC 11–13; GCC 14/15
  are much better but not yet 100 % clean.

Apple Clang *can* build GCC 15, and on a matched Xcode + SDK combination the
bootstrap works out of the box. If it does not, the next section describes
the two Homebrew-based fallbacks.

## If the Clang bootstrap fails

Install Homebrew's prebuilt GCC:

```bash
brew install gcc
```

Homebrew installs GCC as versioned binaries. The exact paths depend on the
CPU:

| Platform      | Paths                                                      |
|---------------|------------------------------------------------------------|
| Intel         | `/usr/local/bin/gcc-15`, `g++-15`, `gfortran-15`           |
| Apple Silicon | `/opt/homebrew/bin/gcc-15`, `g++-15`, `gfortran-15`        |

Pick one of the two routes below.

### Route 1 — Use Homebrew GCC directly

Quickest path to a working stack. The resulting stack depends on Homebrew
being installed on the host.

Edit `flavors/macos.yaml`. On **Intel Macs**:

```yaml
compilers:
  cc:  /usr/local/bin/gcc-15
  cxx: /usr/local/bin/g++-15
  fc:  /usr/local/bin/gfortran-15

bootstrap_compilers:
  cc:  /usr/local/bin/gcc-15
  cxx: /usr/local/bin/g++-15

bootstrap_packages:
  - m4
  - openssl
  - texinfo
  # ...
  # remove `- gcc` so SCLS does not build its own GCC
```

On **Apple Silicon**, use `/opt/homebrew/bin/gcc-15`, `g++-15`, and
`gfortran-15` in the same three places.

### Route 2 — Use Homebrew GCC only to bootstrap SCLS's own GCC

Slower, but produces a completely independent build environment. The
resulting stack does not depend on Homebrew at runtime.

Edit `flavors/macos.yaml`. On **Intel Macs**:

```yaml
bootstrap_compilers:
  cc:  /usr/local/bin/gcc-15
  cxx: /usr/local/bin/g++-15
```

On **Apple Silicon**, use `/opt/homebrew/bin/gcc-15` and
`/opt/homebrew/bin/g++-15`.

Leave `compilers` and `bootstrap_packages` unchanged. SCLS will then build
its own GCC inside `/opt/scls` using Homebrew's GCC as the stage-0
compiler, and the final stack points only at `/opt/scls/bin/gcc` and
friends.
