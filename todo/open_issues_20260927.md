# Open issues after the 2026-09-22 campaign — 2026-09-27

**Written:** 2026-09-27, from the U24 session, before the U24 VM was shut down.
**State at writing:** `origin/devel` = `1c66cb8`. U24 and U26 columns are built and installed. Nothing
has been staged or uploaded from either Ubuntu host. Tracker: `todo/rebuild_campaign_20260922.md`.
Devlogs: `devlog/dl20260926_u24_openmpi_prrte_external.md`, `devlog/dl20260926_u26_lapack_gfortran15_zlaqr5.md`,
`devlog/dl20260927_u26_full_stack_build.md`.

Tick items here as they close. Record findings in the devlog or changelog, not only here.

---

## 1. Rebuilds still owed on the RPM hosts

Both fixes were made on the Ubuntu hosts. Under the one-NEVRA-per-recipe-state policy, the
release bumps have to reach every host that already published the old NEVRA. Neither bump cascades.

- [ ] **openmpi 5.0.11-1 → -2** (tracker row 30): R9 debug/gcc/mkl, R10 debug/gcc/mkl, AMZN gcc/mkl.
      Rebuild and install **openmpi only**, then stage. Commit `950c074` adds `--with-prrte=internal`.
      The RPM -1 builds already took the internal PRRTE (their guards passed), so the payload should be
      equivalent. Check `PRRTE: internal` in each configure log anyway, and confirm the SONAMEs are
      still `libmpi.so.40` / `libprrte.so.3`.
- [ ] **lapack 3.12.1-1 → -2, debug only** (tracker row 31): R9 debug, R10 debug. Rebuild lapack alone; its
      four subpackages (blas, cblas, lapack, lapacke) move together. Commit `80a972a` adds
      `-ffp-contract=off` (gfortran 15.2 `zlaqr5` wrong-code). GCC 13/14 hosts aren't affected;
      the rebuild is only for NEVRA consistency.
- [ ] `lbl` openmpi becomes **4.1.6-2 with no content change**, because `release:` is recipe-wide. `lbl` is
      source-only and untracked. Either accept that, or add a per-flavor release override (a
      build-config change that needs Christian's approval).

## 2. Staging and upload (deferred by Christian)

- [ ] **U24 drops**: debug, gcc, mkl. Use `/stage-drop`, one flavor at a time.
  - **Do not stage the rebuilt `scls-<F>` 2026-1 meta .debs.** `deb_builder` hard-codes the meta
    release to 1 (`python/deb_builder.py:1924`), so the rebuilt metas carry the same NEVRA as the ones
    already published on belfem. Their Depends are identical, but the bytes differ. List them under
    `already_published:`.
  - The same applies to any other package whose NEVRA is already published. Check against belfem's
    published list for noble before staging.
  - **2026-09-28 status:** `stage_to_belfem.sh` now stages .debs (contract v1.6 layout `ubuntu/pkgs`,
    `ubuntu/spkgs`; manifest body per belfem's proposed v1.7). The published state comes from noble's
    signed `InRelease`/`Packages.gz`/`Sources.gz` (126 .debs, 107 sources), verified against
    `RPM-GPG-KEY-SCLS`. All three drops are staged locally, gates PASS, **not uploaded**:
    - `U24-debug-*`: 31 .debs + 25 sources (75 files), 1496853220 B
    - `U24-gcc-*`: 28 .debs + 25 sources (75 files), 810025878 B
    - `U24-mkl-*`: 27 .debs + 24 sources (72 files), 779669318 B. Linkage gate: `gnu_thread` only, on
      both the drop and the full `/opt/scls/mkl` prefix (491 ELF).
    - Each drop lists 24 entries under `already_published:`, including the metas and `environment 2026-2`.
      For `scls-<F>` 2026-1 and `scls-<F>-environment` 2026-2 the local rebuild differs from the
      published copy. They are never re-shipped (v1.2); the manifest notes the difference.
  - Upload key: `~/.ssh/scls_upload` (SHA256:4BmdyYN0…HcGU), installed on belfem as `scls-upload-u24`.
    The belfem host key is pinned (Christian confirmed SHA256:8iDhHWaQ…Ew). The 2026-09-28 20:47Z access
    test was refused with `Permission denied (publickey)`: the key isn't in belfem's authorized_keys yet.
    Next: Christian installs it, rerun the 4-part test, then debug → gcc → mkl, one drop in flight, each after
    belfem's promote.
  - Restage right before each upload so `git_head` names the commit that carries the DEB path.
- [ ] **U26 drops.** This is a new distro (Ubuntu 26.04), so there's probably no published repo yet.
      Coordinate the suite name and repo setup with belfem first.
- [x] `scripts/stage_to_belfem.sh` keeps one shared READY file across drops, so staging a second drop
      overwrites the first one's READY. This was found on AMZN and is still open. Fix it (READY per
      drop, outside the rsynced payload) before staging several flavors in a row, or rewrite READY
      before each upload. The fix is a `scripts/` change and needs approval.
      **Fixed 2026-09-28:** READY is now `$STAGE/READY.<DROP>` (approved by Christian), on the RPM path too.

## 3. openmpi recipe items found in the post-commit review (not caused by `950c074`)

Each of these is a build-configuration or recipe edit and needs Christian's approval.

- [ ] `gcc-mkl-cuda` builds openmpi without `--with-pmix/--with-hwloc/--with-libevent/--with-ucx`.
      Its own `flavor_args` key wins over `mkl`'s, and `resolve_flavor_key` doesn't merge blocks.
      Meanwhile `requires` resolves to the mkl list, so it depends on the stack pmix/hwloc but
      configure may never be pointed at them. This was already the case at `8a4b68e`. The flavor is
      untested.
- [ ] `intel` openmpi has no `requires` key and configures with the single flag
      `--with-prrte=internal`. `flavors/intel.yaml` also sources oneAPI `setvars.sh` and
      BuildRequires `openmpi-devel`, which is another way an external PRRTE or MPI could leak in.
- [ ] The comment above `patches:` in `recipes/openmpi.yaml` (about lines 18-26) still describes the
      GCC 16 always-inline patch, which was dropped in 5.0.11-1. It's a comment-only fix.
- [ ] `files/openmpi.txt` is an ORTE-era list (`orterun`/`orted`, no PRRTE). It's unused while
      `rpm_files_auto: true`, but it would be wrong if that were ever turned off. Delete or regenerate it.

## 4. The CPATH / LIBRARY_PATH mechanism behind the openmpi bug

- [ ] The DEB/unix build environment exports `CPATH=<prefix>/include` and `LIBRARY_PATH=<prefix>/lib`
      (`python/build_common.py:1002-1005`). Any package whose configure *prefers* an already
      installed copy of itself (or of a bundled component) over its own can silently change what it
      builds when rebuilt on top of an old install. RPM builds don't export these. Audit the other
      recipes with bundled third-party components or `rpm_files_auto: true` (ucx, vtk, libunwind,
      hdf5, petsc's `--download-*`?) for the same pattern. Also consider whether the DEB env should
      set these at all (a `python/` change, which needs approval and the six-step script gate).

## 5. Workflow / doc fixes

- [ ] `doc/BUILD_EXECUTION.md` §1.3 still tests sudo with `sudo -n true`. Under the recommended
      `--scope pkg` grant this **always fails**, so `/update-build` preflight wrongly reports that
      sudo isn't set up. Replace it with `sudo -n apt-get --version` / `sudo -n dnf --version`, as
      `.claude/commands/grant-pkg-sudo.md` §4 already proposes. The `scls build all` keepalive
      (`sudo -v`) has the same problem. Both are doc/wrapper changes and need approval.
- [ ] Hosts that never ran `./scls install _meta`: U24 had built its flavor metas in August but
      never installed them, so `vtk` (a leaf only the meta pulls in) was missing on every flavor. Add
      "install `_meta` at the end of each flavor" to `/update-build` and `/build-stack`. It's already
      the last entry of `build_order.py`, but the tracker-driven loop skips it.
- [ ] The drift sweep in BUILD_EXECUTION §1.6 skips packages that aren't installed (`[ -z "$have" ] &&
      continue`). That is exactly how the missing vtk went unnoticed on U24. Consider reporting
      "not installed" for packages that the flavor meta-package depends on.

## 6. From U26 (Ubuntu 26.04 host)

Reported by the U26 session. Details are in `devlog/dl20260927_u26_full_stack_build.md` and
`devlog/dl20260926_u26_lapack_gfortran15_zlaqr5.md`. Items 6.1–6.3 were spot-checked on U24 and hold there too.

- [ ] **6.1 lapack runtime Depends (P1, pre-existing).** `scls-<F>-lapack` has no Depends on
      `scls-<F>-blas`, although `liblapack.so.3` has `libblas.so.3` in `DT_NEEDED`. Confirmed on U24:
      `Depends: scls-debug-environment` only. `blas` is listed under the same-name `lapack`
      subpackage, which `rpm_builder.py:2370` / `deb_builder.py:704` skip without merging its requires.
      This is a dependency-list change and needs Christian.
- [ ] **6.2 lapack license notice (P2, pre-existing).** The binary packages ship no LAPACK LICENSE
      (BSD requires one); `files/lapack.txt` has none, and nothing is under `share/licenses/` on U24.
- [ ] **6.3 U26 DEB publishing isn't wired up.** (Original finding: the keyring hard-coded
      `Suites: noble`, and untagged .deb versions from U24 and U26 would collide in one reprepro pool.)
      **Decided 2026-09-28 (Christian):** one reprepro repo per distro, each with its own pool. Versions stay
      untagged. noble is unchanged at `/scls/ubuntu`; resolute is a separate reprepro base nested at
      `/scls/ubuntu/resolute` (Christian, 2026-09-28, confirmed on belfem). The staging side is
      done: column `U26` maps to `resolute`, and the script refuses to run on a host whose `VERSION_CODENAME`
      doesn't match. `deb_builder` now writes the keyring's URI and Suite from `VERSION_CODENAME`
      (`APT_REPO_BY_CODENAME`, 2026-09-29). Still open: rebuild the keyring on U26, and belfem's second
      reprepro base plus its `update_repo` entry.
- [ ] **6.4 sudo-rs on 26.04.** `sudo -n -v` fails even with `--scope all` (sudo-rs ignores
      `verifypw`), so `scls build all`'s keepalive (`scls:151-168`) can't work there. Either
      switch U26's sudo alternative to sudo.ws, or make the keepalive test `sudo -n apt-get --version`.
      This is a wrapper change, and overlaps §5's `sudo -n true` item.
- [ ] **6.5 Parallelism knob.** `get_parallel_jobs()` is `cpu_count` with no override. vtk debug
      ran out of memory at `-j8` in 15 GB on U26, which capped heavy packages with `PYTHON_CPU_COUNT=4`
      in a local driver. A supported knob (env `SCLS_JOBS`, or a per-recipe `max_jobs`) would make
      that reproducible. It's a builder change.
- [ ] **6.6 Fresh-Ubuntu-host prep checklist.** A 26.04 minimal install has no `curl`
      (`check_host_tools` needs it). Also cover the Codex/Grok sandbox (§7) and the sudo grant.
- [ ] **6.7 (optional) GCC bug report** for the `zlaqr5` SLP+FMA wrong code; there's a standalone
      reproducer in U26 scratch. Note that OpenBLAS escapes it only because its `Makefile:318-319` adds
      `-fno-tree-vectorize` for gfortran, so an OpenBLAS CMake build would lose that protection.
- [ ] **6.8 R9/R10 debug lapack -2 (row 31).** After rebuilding, also run lapackpp `tester geev`
      there. The host GCC version decides whether it's exposed, and LAPACK's own ctest doesn't catch the bug.

## 7. Host notes (U24 VM)

- [ ] **Codex/Grok sandbox.** Ubuntu 24.04 ships no bwrap AppArmor profile, so with
      `kernel.apparmor_restrict_unprivileged_userns=1` both auditors return audits that read nothing.
      Christian set it to 0 on U24 **non-persistently**, so it is back to 1 after this shutdown. Choose
      one of: persist the sysctl via `/etc/sysctl.d/`, back-port Ubuntu 26.04's `bwrap-userns-restrict`
      profile (untested on apparmor 4.0.1), or run audits from U26 or the dev host. Rule of thumb: an
      audit that cites no file:line did not run.
- [ ] Optional disk cleanup on U24 (9 GB free at shutdown): `sudo apt-get clean` (about 0.8 GB),
      `rm -rf work/build/*` (about 0.4 GB). `patched/` is already gone.
- [ ] U24 state at shutdown: `flavor.conf` = `lbl` (restored), sudo grant `--scope pkg` active, MKL
      2026.1.0-236, suitesparse removed from all flavors, desktop/snaps removed, repo-local git
      identity set, `gh` authenticated.
