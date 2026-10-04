# Round 2 on EL10 and Amazon Linux 2023 — build instructions

**Written:** 2026-10-03, from the R9 session, for the R10 and AMZN build hosts.
**Columns:** R10 debug/gcc/mkl, AMZN gcc/mkl (AMZN has no debug column).
**Status of the reference host:** R9 finished all three flavors on 2026-10-03, with every package below
built, installed and checked. Results and the problems hit there are in
`devlog/dl20261003_r9_round2.md` and `todo/r9_round2_20261003.md`. Nothing is staged yet.
**Ruling (Christian, 2026-10-03):** round 2 is the final round over all distros and carries the whole
open list. Upload only after the belfem coordinator's size OK **and** Christian's go-ahead.

---

## What this round fixes

| Package | New NEVRA | Why |
|---|---|---|
| environment | 2026-3 | activate sets `OMP_CANCELLATION` for SPRAL |
| `scls-<F>` (meta) | 2026-2 | spral and ipopt join the 2026 stack (`meta_release: 2`) |
| gperftools | 2.18.1-2 | RPM builds silently lost libunwind (no include path); now `CPPFLAGS=-I<prefix>/include` plus a configure check |
| scotch | 7.0.15-2 | compression on everywhere; declared zlib/bzip2/xz deps; configure check |
| hwloc | 2.14.0-2 | tools under plain names (`lstopo`, not `x86_64-redhat-linux-lstopo`) |
| libunwind | 1.8.3-3 | no triplet prefix; upstream test programs no longer shipped |
| openmpi | 5.0.11-2 | `--with-prrte=internal` (campaign row 30) |
| lapack | 3.12.1-2, **debug only** | `-ffp-contract=off` (campaign row 31) |
| spral | 2025.09.18-1 (new) | SSIDS for Ipopt; released for building 2026-10-03 (macOS done) |
| ipopt | 3.14.20-1 (new) | links MUMPS and SPRAL; default solver stays mumps |

The builder change behind hwloc and libunwind (D3) applies to every autotools package. The builder
no longer passes `--target`, and every package fails to build if it installs a `<triplet>-<name>`
program (gcc is exempt). Only hwloc and libunwind change on Linux. Anything else that trips the guard
is a new finding: halt and report it, don't work around it.

No consumer rebuild is needed: the SONAMEs of libscotch, libhwloc, libunwind and libmpi are unchanged.

## 1. Preflight (once per host)

- [ ] `git fetch && git switch ipopt && git pull`. Build from `origin/ipopt` at or after the commit
      that carries this file (`21f141e` or later: it carries the gperftools pprof skip, and R9 and
      R10 are built from it). Do not build from `devel` until `ipopt` is merged there.
- [ ] meson and ninja on `PATH` for spral: `python3 -m pip install --user meson ninja`, or link them
      from an existing venv into `~/.local/bin`. Do **not** put a venv's whole `bin/` on `PATH`,
      because its `python3` would shadow the system one for every other build.
- [ ] Passwordless sudo for the package manager. `sudo -n dnf --version` passing is **not** proof: a
      cached login answers yes too, and on R9 an install failed mid-chain when the cache lapsed.
      Check that `/etc/sudoers.d/scls-build` exists (`sudo -n scripts/grant_pkg_sudo.sh --check`);
      if it doesn't, Christian runs `scripts/grant_pkg_sudo.sh --user <user> --scope all --apply`
      (`/grant-pkg-sudo`). Without it, keep the login warm with `sudo -n -v` every minute.
- [ ] The new build dependencies install cleanly: `sudo dnf install zlib-devel bzip2-devel xz-devel`.
      On AL2023, check that these names resolve before starting.
- [ ] `flavor.conf` is tracked (default `macos`). Set the flavor per section, and run
      `git checkout flavor.conf` at the end. Never commit it.

- [ ] Host lessons from R10 (2026-10-04), in case they apply: if `./scls build` stops with
      `No module named 'jinja2'`, the system `python3` lacks it; set `python:` in `flavor.conf` to an
      interpreter that has `jinja2` and `yaml` (do not commit `flavor.conf`). The Codex and Grok
      wrappers need a logged-in CLI and `bubblewrap`; they are only needed if a change must be
      audited, not for building.

## 2. Build order, per flavor (debug → gcc → mkl; AMZN: gcc → mkl)

```bash
sed -i 's/^flavor: .*/flavor: <F>/' flavor.conf
for p in environment libunwind gperftools hwloc lapack openmpi scotch spral ipopt _meta; do
    [ "$p" = lapack ] && [ "<F>" != debug ] && continue                      # lapack: debug only
    ./scls build $p && ./scls install $p || break
done
```

`./scls build next` will **not** rebuild the meta-package if `2026-1` is installed (its registry
marker already exists), so build `_meta` explicitly. `./scls install _meta` installs only the newest
`scls-<F>` RPM. Its Requires include spral and ipopt, so they must be installed first.

## 3. Checks after each package

- **environment:** `rpm -q scls-<F>-environment` shows 2026-3.
- **libunwind -3:** `ls <prefix>/libexec/libunwind` does not exist, and no
  `x86_64-*-linux*-*` file remains in `bin/`, `sbin/` or `libexec/`.
- **gperftools -2:** `readelf -d <prefix>/lib/libprofiler.so <prefix>/lib/libtcmalloc.so` NEED
  `libunwind.so.8`. belfem checks this, because it's the reason for -2. Since `21f141e` the recipe
  passes `ac_cv_path_PPROF_PATH=`, so the five pprof-dependent checks are skipped on every host:
  configure prints `checking for pprof... (cached) no`, the suite is 48/48 with 0 FAIL, and
  `sampling_test`, `sampling_debug_test`, `profiler_unittest.sh` and both
  `heap-profiler*_unittest.sh` are absent from the log (R9 and R10, 2026-10-04). A FAIL, or one of
  those five names in the log, is a finding. The installed file list stays at 73 files.
- **hwloc -2:** `<prefix>/bin/lstopo` exists, and `<prefix>/bin/*-lstopo` does not. If the RPM
  fails on unpackaged or missing files, `files/hwloc.txt` disagrees with the install: halt and report.
- **lapack -2 (debug):** ctest passes, then run lapackpp `tester geev` against it
  (`todo/open_issues_20260927.md` §6.8). The host GCC decides whether the zlaqr5 bug shows.
- **openmpi -2:** the configure log says `PRRTE: internal`, `bin/prte` exists, and the SONAMEs are
  still `libmpi.so.40` and `libprrte.so.3`.
- **scotch -2:** the configure check passed (all of `FIND_PACKAGE_MESSAGE_DETAILS_{ZLIB,BZip2,LibLZMA}`
  are in the cache). `readelf -d <prefix>/lib/libscotch.so` NEEDs `libz.so.1`, `libbz2.so.1` and
  `liblzma.so.5`, and `rpm -q --requires scls-<F>-scotch` lists `zlib`, `bzip2-libs` and `xz-libs`.
  belfem compares these two.
- **spral:** the build log says `Library hwloc found: YES`; `meson test` is 9/9;
  `readelf -d <prefix>/lib/libspral.so` NEEDs `libmetis` and `libhwloc.so.15` and nothing CUDA.
- **ipopt:** `%check` passes, including hs071 with `linear_solver spral` ("Optimal Solution Found").
  On mkl, configure reports MKL Pardiso.
- **`_meta`:** `rpm -q scls-<F>` shows 2026-2.
- **After each flavor:** `find <prefix> -name 'x86_64-redhat-linux-*'` returns nothing. Then the
  multi-core SPRAL run: build `examples/hs071_cpp` from the Ipopt source tree against the installed
  prefix (`source <prefix>/share/scls/activate`, `pkg-config --cflags --libs ipopt`, plus
  `-Wl,-rpath,<prefix>/lib` because the `.pc` file carries no rpath), put `linear_solver spral` in
  `ipopt.opt`, and run with `OMP_NUM_THREADS=<nproc>`. Activate must show `OMP_CANCELLATION=TRUE`
  and no `OMP_PROC_BIND`.
- **mkl, after the last package:** `scripts/check_mkl_linkage.sh --flavor mkl --prefix /opt/scls/mkl`
  passes. belfem's verifier now requires every object that NEEDs any `libmkl_*` to directly NEED
  `gf_lp64 + gnu_thread + core + libgomp`, with no second threading layer.

## 3b. HSL script test (once per host, any one flavor; gcc on R9)

Christian puts the licensee's `coinhsl-*.tar.gz` and `hsl_ma77-*.tar.gz` in `/tmp` on the VM. They
are licensed: never copy them into the repo, a drop or an artifact. Christian's instruction for this
test (2026-10-03): academic licence, single user, local install, then uninstall. Uninstalling is
part of the test.

```bash
sed -i 's/^flavor: .*/flavor: gcc/' flavor.conf
./scls build hsl --sources /tmp                                      # builds + checks, installs nothing
./scls install hsl --local --licence academic --accept-licence       # ~/.local/scls-hsl/gcc, 0700/0600
```

- Build: every gate passes (symbols, no bundled METIS, dependencies resolve to the stack, dlopen
  smoke test, `MA77 functional gate: PASS`); the log has no "Fortran 2018 deleted feature" lines;
  the scratch tree under `/tmp/scls-hsl-*` holding HSL source is gone afterwards.
- Use: with the hs071 binary from §3, `ipopt.opt` containing
  `hsllib $HOME/.local/scls-hsl/gcc/lib/libhsl.so` and `linear_solver <s>` solves for each of
  ma27, ma57, ma77, ma86, ma97.
- Uninstall: `rm -rf ~/.local/scls-hsl/gcc` (a local install has no registry entry), then confirm
  `find / -xdev -name 'libcoinhsl*' -o -name 'libhsl.*'` finds nothing.
- Known upstream behaviour, not a failure of the test: with an `hsllib` that cannot be loaded, Ipopt
  3.14.20 prints "Library loading failure" and then segfaults at exit.

## 4. Staging (`/stage-drop`, one flavor at a time)

- **Not before Christian says so.** R9 itself has not staged yet (2026-10-03).
- Column `R10` or `AMZN`. One drop in flight: the next one only after belfem promotes the previous.
- New NEVRAs only. belfem's published list (2026-10-03): gperftools 2.18.1-1, openmpi 5.0.11-1,
  scotch 7.0.15-1, environment 2026-1/2026-2, `scls-<F>` 2026-1 are published, and spral/ipopt are not.
  Confirm R10's and AMZN's own lists with the coordinator before staging.
- Per drop, send the coordinator: name, file_count, total_bytes, sha256(SHA256SUMS), git_head and the
  linkage result. Upload after the coordinator's size OK **and** Christian's go-ahead.

## 5. Halt conditions

Stop and report, instead of patching, if:
- the triplet guard fires for any package other than hwloc or libunwind;
- scotch's configure check fails (a compression `-devel` package is missing or not found);
- gperftools' configure check fails (`USE_LIBUNWIND` missing from `src/config.h`);
- any recipe, flavor or `python/` change looks necessary. Those need Christian's approval
  (CLAUDE.md, "Build Configuration Changes Require Explicit Approval").

## 6. Record

- Tick the R10/AMZN cells in `todo/rebuild_campaign_20260922.md` rows 30–31, and the matching rows in
  `todo/spral_recipe.md`.
- Write a devlog `devlog/dl2026MMDD_<r10|amzn>_round2.md` with the check outputs and any deviations.
