# Devlog 2026-10-01 — U26 (Ubuntu 26.04 resolute): deployment prep, relink, el9 parity, local drops

**Date:** 2026-09-28 → 2026-10-01
**Topic:** prepare the first resolute (.deb) drops from U26: repo, upload path, keyring, relink without `--as-needed`, per-object el9 parity, local staging
**AIs involved:** Claude Opus (U26 host session); U24 build session and belfem "Server" session (peers, over Remote Control); Codex gpt-5.6-terra and Grok 4.7 (blind audits)
**Flavor / Host:** U26 = Ubuntu 26.04.1 VM, GCC 15.2.0-16ubuntu1, DEB; debug, gcc, mkl
**Verification:** built and installed on U26 (all packages force-rebuilt at the same version-release with the gcc specs override); per-object DT_NEEDED parity against the published el9 RPMs: HARD 0 on debug (497/497 matched), gcc (493/493), mkl (492/492); `scripts/check_mkl_linkage.sh` PASS (fc07a7f); `U26-debug-20261001T1302Z` staged with `--build` (sha256sum -c OK). All three drops uploaded and promoted (see Addendum).

## Summary

U26's resolute drops are ready but not uploaded. Upload order (belfem): U24 noble first, then
U26 debug → gcc → mkl, each after the previous drop is promoted and after Christian's go-ahead.
Rulings and repo-side changes made along the way are on `devel` (U24 commits; see
`dl20260929_deb_no_as_needed.md`); this entry records what U26 did and found.

## Publishing path (done)

- resolute is a separate reprepro base nested at `/scls/ubuntu/resolute` (Christian 2026-09-28),
  live since 2026-09-30 02:26 UTC. U26 gpgv-verified InRelease (VALIDSIG 1FBC2823…835E8A44) and the
  index hashes; `conf/` and `db/` return 403.
- U26 upload key `scls-upload-u26` (SHA256:omDGwIvG…ZniJM), belfem host key pinned after Christian
  confirmed SHA256:8iDhHWaQ…Ew. 4-part access test PASS (write 0, read-back 12, shell 255, `../` 12).
- `scls-archive-keyring_2026-1_all.deb` built from `APT_REPO_BY_CODENAME`: `URIs:
  https://belfem.lbl.gov/scls/ubuntu/resolute`, `Suites: resolute`; exactly one key; approved by belfem;
  installed on U26. It ships once, in the first resolute drop (debug).
- Generated packages ship without a source package (closed `no_source:` list; Christian 2026-09-28).

## Relink without `--as-needed`

- `-Wl,--no-as-needed` in LDFLAGS (c3eab87) did not reach libtool links (U24 found it on libevent).
  The working fix is the host gcc specs file (`doc/BUILD_EXECUTION.md` §1.1a), enforced by
  `deb_builder.assert_links_without_as_needed`. On U26: the sed token matches gcc 15.2's `*link` spec twice on
  one line (the doc now uses `sed …/g`; the installed file still has the inert android-branch copy,
  so reinstall it at a quiet moment); guard PASS for gcc/g++/gfortran and the MPI wrappers.
- First U26 rebuild was halted before any linking package rebuilt; restarted after the specs file
  was installed. Spot check after hwloc/lapack: libevent (5 libs) and libhwloc match el9 exactly.

## el9 parity (per-object DT_NEEDED)

Rule (belfem, Christian's el9-parity ruling): HARD = MKL/BLAS/LAPACK/OpenBLAS/ScaLAPACK/OpenMP/MPI and
every library from the SCLS prefix — must be identical; ALLOWED = toolchain, glibc and distro
runtime, each with a cause derived from `nm -D` (imports ∩ exports). Tooling (scratch, handed to U24):
`needed_parity.sh` + `score2.py`; bz2 SONAME alias (RHEL `libbz2.so.1` = Debian `libbz2.so.1.0`).

Pre-fix HARD baseline: gcc 1738, mkl 2741, debug 1796. After the relink: 0 on all three.

Findings and how they were settled:
- **gperftools** links SCLS libunwind on Ubuntu; el9/el10 RPMs use none (the RPM env exports no
  `CPATH`, so configure silently misses `libunwind.h`). Ruled: recipe is the reference, RPM fix in
  round 2 — reported as ACCEPTED (4 objects per flavor).
- **ucx `libucx_perftest_mad.so`** was el9-only: Ubuntu splits MAD into libibmad/libibumad. Ruled:
  map them (e873f4c); debug ucx re-run; el9-only now 0.
- **bz2 / xz / zstd**: el9 build hosts have the `-devel` packages undeclared. Ruled: Ubuntu hosts
  install `libbz2-dev`, `liblzma-dev`, `libzstd-dev` (host prep + map, 6870d4c, 5a8bf93). Rebuild set
  from el9 NEEDED: libunwind (minidebuginfo), scotch, netcdf. No compression diffs remain.
- **scotch** `COMMON_FILE_COMPRESS_*=OFF` are inert (scotch 7.0.15 reads `USE_ZLIB/USE_LZMA/USE_BZ2`,
  `CMakeLists.txt:115-117`). Round 2 decision, `todo/open_issues_20260927.md` §8.
- Remaining ALLOWED: libquadmath missing (gfortran's `libgfortran.spec` links it `--as-needed`,
  not referenced), libmvec extra (gcc 15 vectorizes libm calls, real use), libnl over-linked on PRRTE
  tools (libprrte uses it).

## check_mkl_linkage.sh gave load-dependent results

The first mkl staging failed the per-object rule on two objects that really NEED all four MKL libs;
two reruns on the same drop passed. Cause: `set -o pipefail` with `echo "$x" | grep -q PAT` — grep
exits at the first match, echo dies of SIGPIPE, and pipefail turns a match into a miss. Reproduced on
U26: 2 / 20000 false negatives (here-string: 0 / 20000). The same pattern guarded the `libmkl_rt`,
scalapack/blacs and MKL-in-non-MKL checks (false PASS direction). Fixed by U24 in f69e8a3 (here-strings)
and fc07a7f (no `head` in carriers, failed extract stops the gate); blind audits by Codex and Grok
confirmed both.

## State at writing

- `U26-debug-20261001T1302Z`: 153 files, 2106566215 bytes, sha256(SHA256SUMS) 6244993f…efb3d8,
  git_head fc07a7f, no_source 3 (keyring, meta, environment). Ready; not uploaded.
- `U26-mkl-20261001T1113Z` staged but superseded: it still carries the keyring. gcc and mkl get
  restaged after U26-debug is promoted, so the keyring lands in `already_published`.
- Host changes on U26: gcc specs override, libarchive-tools, libibmad-dev/libibumad-dev,
  libbz2-dev/liblzma-dev/libzstd-dev, keyring installed. Drivers (git-ignored): `tmp/u26_build_loop.sh`
  (now with resumable `U26_FORCE=1`), `tmp/u26_overnight_chain.sh`, `tmp/u26_compress_rebuild.sh`.

## Open — needs Christian

1. Go-ahead for each U26 upload, in order, after U24 noble.
2. Reinstall the gcc specs override on U26 with `sed …/g` at a quiet moment (cosmetic).
3. Round 2 (`todo/open_issues_20260927.md` §8): ipopt, gperftools RPM libunwind, scotch compression
   options, PRRTE/libnl (informational).

## Addendum 2026-10-01 — uploaded, promoted, client-verified

Christian approved the U26 drops ahead of U24 mkl; one drop in flight, each after belfem's "slot free".

| Drop | files | bytes | sha256(SHA256SUMS) | upload rc (payload/READY) | state |
|---|---|---|---|---|---|
| U26-debug-20261001T1302Z | 153 | 2106566215 | 6244993f…b3d8 | 0 / 0 | promoted |
| U26-gcc-20261001T2316Z | 149 | 949645519 | 9f462f2d…9482 | 0 / 0 | promoted |
| U26-mkl-20261001T2320Z | 145 | 918997073 | b2571ff9…b366 | 0 / 0 | promoted |

gcc and mkl were restaged after the debug promotion so the keyring is `already_published`
(no_source = meta + environment only). Client check on U26 after the last promotion: the resolute
index has 126 packages (debug 44, gcc 41, mkl 40, keyring), all 126 downloaded `.deb`s are
byte-identical to the U26 builds, metas plus `scls-<F>-petsc` reinstall cleanly from
`/scls/ubuntu/resolute`, and `ldd` on all 348 MKL-linked objects in `/opt/scls/mkl` resolves exactly
one `libmkl_core` and one `libmkl_gnu_thread` with nothing unresolved.

Also during the upload window: the website template now lists one APT repo per Ubuntu release and
drops the Apple Silicon "beta" label (8a5f7f6, generated locally, not deployed), and
`doc/MACOS_BUILD.md` records the full arm64 build during ASC 2026 per Christian (8771963).
