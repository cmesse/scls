# Round 2 on EL10 and Amazon Linux 2023 — build instructions

**Written:** 2026-10-03, from the R9 session, for the R10 and AMZN build hosts.
**Columns:** R10 debug/gcc/mkl, AMZN gcc/mkl (AMZN has no debug column).
**Status of the reference host:** R9 debug is in progress. Results, and every problem hit there, are in
`todo/r9_round2_20261003.md`. Read its Status and Blockers sections before starting, because a fix
found on R9 may already be committed.
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
| spral | 2025.09.18-1 (new) | **hold**: macOS fixes may still land; wait for the go |
| ipopt | 3.14.20-1 (new) | **hold**, same reason |

The builder change behind hwloc and libunwind (D3) applies to every autotools package. The builder
no longer passes `--target`, and every package fails to build if it installs a `<triplet>-<name>`
program (gcc is exempt). Only hwloc and libunwind change on Linux. Anything else that trips the guard
is a new finding: halt and report it, don't work around it.

No consumer rebuild is needed: the SONAMEs of libscotch, libhwloc, libunwind and libmpi are unchanged.

## 1. Preflight (once per host)

- [ ] Check out the commit named in R9's tracker (branch `ipopt` until it merges into `devel`). Every
      R9 fix so far is in `ipopt` at or after `4a9354b`.
- [ ] meson and ninja on `PATH` for spral: `python3 -m pip install --user meson ninja`, or link them
      from an existing venv into `~/.local/bin`. Do **not** put a venv's whole `bin/` on `PATH`,
      because its `python3` would shadow the system one for every other build.
- [ ] `sudo -n dnf --version` works without a prompt (`/grant-pkg-sudo`).
- [ ] The new build dependencies install cleanly: `sudo dnf install zlib-devel bzip2-devel xz-devel`.
      On AL2023, check that these names resolve before starting.
- [ ] `flavor.conf` is tracked (default `macos`). Set the flavor per section, and run
      `git checkout flavor.conf` at the end. Never commit it.

## 2. Build order, per flavor (debug → gcc → mkl; AMZN: gcc → mkl)

```bash
sed -i 's/^flavor: .*/flavor: <F>/' flavor.conf
for p in environment libunwind gperftools hwloc lapack openmpi scotch; do   # lapack: debug only
    ./scls build $p && ./scls install $p || break
done
# spral, ipopt: only after Christian's go
./scls build _meta && ./scls install _meta                                   # last, after spral + ipopt
```

`./scls build next` will **not** rebuild the meta-package if `2026-1` is installed (its registry
marker already exists), so build `_meta` explicitly. `./scls install _meta` installs only the newest
`scls-<F>` RPM. Its Requires include spral and ipopt, so they must be installed first.

## 3. Checks after each package

- **environment:** `rpm -q scls-<F>-environment` shows 2026-3.
- **libunwind -3:** `ls <prefix>/libexec/libunwind` does not exist, and no
  `x86_64-*-linux*-*` file remains in `bin/`, `sbin/` or `libexec/`.
- **gperftools -2:** `readelf -d <prefix>/lib/libprofiler.so <prefix>/lib/libtcmalloc.so` NEED
  `libunwind.so.8`. belfem checks this, because it's the reason for -2. Expected test noise:
  `profiler_unittest.sh` and both `heap-profiler*_unittest.sh` fail when the host's
  `/usr/bin/pprof` (EPEL pprof 2.9.1) is picked up. This is pre-existing and doesn't fail the build.
  Record it; don't fix it in this round.
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
- **spral / ipopt** (after the go): see `todo/spral_recipe.md` "Shipping builds".
- **mkl, after the last package:** `scripts/check_mkl_linkage.sh --flavor mkl --prefix /opt/scls/mkl`
  passes. belfem's verifier now requires every object that NEEDs any `libmkl_*` to directly NEED
  `gf_lp64 + gnu_thread + core + libgomp`, with no second threading layer.

## 4. Staging (`/stage-drop`, one flavor at a time)

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
