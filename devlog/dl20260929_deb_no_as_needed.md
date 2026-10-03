# Devlog 2026-09-29 — U24 .deb publishing, and Ubuntu's `--as-needed` breaking el9 link parity

**Date:** 2026-09-28 → 2026-09-29
**Topic:** stage and upload the U24 (noble) drops to belfem; the MKL drop exposed that Ubuntu links drop direct `NEEDED` entries that el9 keeps
**AIs involved:** Claude Opus (U24 host session, scls-5f); belfem coordinator session ("Server"); U26 host session (peer, ran the blind audits: Codex gpt-5.6-terra, Grok 4.7)
**Flavor / Host:** U24 = Ubuntu 24.04.5 VM, GCC 13, binutils 2.42, DEB; flavors debug, gcc, mkl
**Verification:** debug and gcc drops uploaded, verified and promoted by belfem. mkl drop staged and gate-passed under the old rule, then cancelled before upload. `--no-as-needed` fix: `--spec-only` byte-identical for the RPM path on all packages (U26); static review by two auditors; **rebuild and per-object el9 parity comparison still pending.**

## Summary

`scripts/stage_to_belfem.sh` could not stage `.deb` files ("DEB staging not implemented"). It now can
(`cec9012`), per contract v1.6 (`ubuntu/pkgs`, `ubuntu/spkgs`) with the manifest body belfem proposed
for v1.7. The published state is read from noble's signed `InRelease`, `Packages.gz` and `Sources.gz`,
and binaries map to source packages through the `.dsc` `Binary:` field
(`scripts/deb_drop_select.py`). READY is now one file per drop.

- `U24-debug-20260928T2049Z`: 106 files, 1496853220 B. Promoted 2026-09-28.
- `U24-gcc-20260929T2105Z`: 103 files, 810025878 B. Promoted 2026-09-29.
- `U24-mkl-20260929T2145Z`: 99 files. Staged with a one-time `?nocache` index patch (Christian), then
  **cancelled**, see below.

## Decisions (Christian)

- One reprepro base per Ubuntu release, versions untagged. noble stays at `/scls/ubuntu`; resolute is
  nested at `/scls/ubuntu/resolute` with its own pool. `deb_builder` writes the keyring's URI and suite
  from `VERSION_CODENAME` (`APT_REPO_BY_CODENAME`).
- `environment` stays at 2026-2. The local rebuild differs from the published one only in a README
  section and a date stamp, so it is not re-shipped.
- Closed `no_source:` list: `scls-archive-keyring`, `scls-<F>`, `scls-<F>-environment`. See
  `doc/LICENSE_POLICY.md`, Source Availability.
- `.deb` links use `-Wl,--no-as-needed` on every flavor. Affected packages are rebuilt at their current
  versions **without a bump**. For noble debug/gcc packages that are already published, Christian
  explicitly overrides contract v1.2 ("Yes, I override because, that is authorized").

## The `--as-needed` finding

belfem compared the mkl drop with the published el9 RPMs. Six objects (libparpack, libdmumps,
libsmumps, libpetsc, libslate, libslepc) NEED only `libmkl_gf_lp64`. They get `libmkl_core` and
`libmkl_gnu_thread` through another library's chain. On el9, all six NEED all four MKL libraries
directly. The cause: Ubuntu's gcc passes `--as-needed` to ld by default and el9's does not.
`scripts/check_mkl_linkage.sh` passed the drop because it checked the flavor-wide set, which was
uniform. The defect is per object.

belfem then compared the published noble debug and gcc packages with el9. About 220 objects per flavor
differ, all in the same direction: noble is missing direct NEEDED entries for libopenblas/libblas,
libscalapack or libgomp. They are in butterflypack, mumps, superlu, lapackpp, and (libgomp only) vtk,
sundials, metis, parmetis, slepc, ucx and zfp.

Fix, on branch `review/u24-deb-as-needed`:
- `build_common.NO_AS_NEEDED` goes first in `CMAKE_*_LINKER_FLAGS`, and `unix_builder` puts it first
  in `LDFLAGS` / `%{ldflags}`, on Linux only. `rpm_builder` is untouched.
- `check_mkl_linkage.sh` gains a per-object rule. Any object NEEDing `libmkl_*` must directly NEED
  the interface library, threading layer, core and OpenMP runtime. On the pre-fix mkl prefix it
  fails exactly the six objects.

## Audit reconciliation (U26, blind Codex + Grok; Grok saw Codex's verdict)

Fixed on the branch: environment, meta and keyring are now version-checked against
`recipes/environment.yaml` before they can take the `no_source` path (Grok, P2). The todo resolute
path is corrected. The doc wording now says only a drop that *ships* a generated package lists it
under `no_source:`. The MKL interface is read from `math.interface`, and the Intel toolchain test
compares the compiler's basename (so `mpicc` no longer matches `icc`).

Still open:
- The rebuild has to settle whether slepc (`skip_compiler_env`, inherits PETSc's link flags), MUMPS
  (`LIBPAR`/`LIBSEQ` and the raw PORD link) and libtool ordering actually pick up the flag.
- Non-MKL objects have no per-object parity gate here yet; belfem's verifier backstops it, and U26
  offered its comparison script.
- The keyring is selected into every drop until one is promoted. Sequencing prevents a double ship
  today, but there is no guard.
- `recipes/environment.yaml` says `BSD-3-Clause`, while the repo is `BSD-3-Clause-LBNL`. Pre-existing;
  it's a recipe edit and needs approval.

## CDN incident

After each promotion, Cloudflare kept serving the pre-promotion `Packages.gz` and `Sources.gz` next to
the fresh `InRelease`, which gives every apt client a Hash Sum mismatch. The staging script's index
hash check caught it both times. belfem's httpd now sends `Cache-Control: no-cache, max-age=0` on
`dists/`, and the index fetch adds a `?nocache=` query.

## First relink attempt: libtool defeats `-Wl,--no-as-needed`

The rebuild at `6291844` stopped after its first package. libevent's new libraries still NEEDED
only `libc` (el9: also `libssl`, `libcrypto`), although its Makefile had
`LDFLAGS = -Wl,--no-as-needed …`. libtool's link template is
`$CC -shared $pic_flag $libobjs $deplibs $compiler_flags …`, so every `-Wl` flag lands after the
libraries it was meant to govern. The auditors had named this risk.

What works: Ubuntu injects the flag through gcc's `*link` spec (`%{!fsanitize=*:--as-needed}`),
which is emitted before all objects and libraries. A gcc `specs` file in
`$(gcc -print-file-name=)` without that token restores el9 behaviour for gcc, g++ and gfortran,
whatever the flag order. Christian chose this host-level fix over passing `-specs=<path>`, because
hdf5 (`h5cc`), PETSc and pkg-config files record LDFLAGS and would embed a build-host path.
`doc/BUILD_EXECUTION.md` §1.1a documents it. `deb_builder` refuses to build until it is in effect:
it links an unused `-lgomp` with each flavor compiler and requires it in NEEDED.

The same run also showed that a same-version reinstall fails once the SCLS apt source is
configured: apt sees the local rebuild as a downgrade of the repo copy. The reinstall path now
passes `--allow-downgrades` (Christian).

## UCX MAD module on Ubuntu

The el9 builds ship `lib/ucx/libucx_perftest_mad.so`, and the Ubuntu builds did not. el9's rdma-core
devel packages include the InfiniBand MAD headers; Debian splits them into `libibmad-dev` and
`libibumad-dev`. Christian accepted the resulting runtime dependency and chose a .deb-only route:
`packaging/system_packages.yaml` maps `libibverbs-devel` and `libibverbs` to lists (deb_builder now
accepts list values). The ucx recipe and the RPM specs are unchanged, and `changelogs/ucx.md` is
left alone because it feeds the RPM `%changelog`. `doc/BUILD_EXECUTION.md` §1.1b notes the host
packages.

## `check_mkl_linkage.sh` gave load-dependent results (fixed in `f69e8a3`)

U26's mkl staging failed the per-object rule for two objects that did NEED all four libraries,
and two immediate reruns passed. The cause was `set -o pipefail` combined with
`echo "$n" | grep -q PATTERN`. `grep -q` exits at its first match; if `echo` is still writing, it
dies of SIGPIPE, and pipefail turns the match into a miss. The same pattern guarded the
`libmkl_rt`, ScaLAPACK/BLACS and MKL-in-a-non-MKL-flavor tests, where a miss is a false
**pass**. U26's reproducer, on libpetsc's 40-line NEEDED list under a concurrent rebuild:
2 false negatives in 20,000 iterations (0.01%), and 0 in 20,000 as a here-string. At about 4 tests
× 19 MKL objects per gate run, that's roughly a 1% chance of a spurious result per run. Every match
now uses a here-string, and a comment at the top of the script forbids the pattern. The U24 debug
drop uploaded before the fix took only the non-MKL branch, and the el9 parity check and belfem's
own verification confirmed it independently.

## Outcome (2026-10-02)

The relink ran with the gcc specs override in place, `SCLS_JOBS=4` for vtk, and a supervisor that
would retry at fewer jobs. It never had to retry. debug finished 2026-10-01 03:49Z, gcc 14:46Z and
mkl 2026-10-02 00:45Z. Per-object el9 parity for all three flavors: every object matched, no
el9-only objects (ucx ships `libucx_perftest_mad.so`), and HARD 0 apart from gperftools' four
`libunwind.so.8` objects. Christian ruled the recipe the reference there; the RPM fix is deferred to
round 2. ALLOWED: libquadmath (gfortran spec), libmvec (toolchain), libbz2 `.so.1`/`.so.1.0` (SONAME
spelling) and libnl (PRRTE). `check_mkl_linkage` with the per-object rule passes for mkl; the six
objects that NEEDed only `libmkl_gf_lp64` now NEED all four.

Drops: `U24-debug-20261001T0427Z` (130 files, 68 replace_published) and `U24-gcc-20261001T2226Z`
(123 files, 63 replace_published) are promoted. `U24-mkl-20261002T0118Z` (144 files, 22
replace_published, 27 new versions) is uploaded, along with `scls-archive-keyring` 2026-2: belfem
moved noble's base to `/scls/ubuntu/noble`, the old paths are compatibility symlinks, and
`KEYRING_RELEASE_BY_CODENAME` gives noble release 2 and resolute 1.

On the way, the disk filled twice, both times during vtk's install. Superseded source packages and
finished vtk build trees were removed; nothing current was lost. Existing noble installs keep the
old files of replaced packages until they run `apt install --reinstall`, because the versions are
unchanged (Christian declined a `+b1` suffix).
