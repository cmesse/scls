# dl20260923 — R9 completes the 2026-09-22 rebuild campaign

**Date:** 2026-09-22 → 2026-09-23
**Host:** Rocky Linux 9.8, tracker column `R9`, RPM
**Scope:** `/update-build` over `todo/rebuild_campaign_20260922.md`, all three binary flavors
**Result:** complete — `debug` 24/24, `gcc` 25/25, `mkl` 24/24, plus four packages added mid-run
**Commits:** `88a324c` `55f3f0b` `b1e58c4` `fc94ae6` `56d52b9` (tracker), `67c3d4f` `3810fe9`
(Class M fixes), `fc3edbe` (`/stage-drop` skill). **None pushed.**

## Verification gate

Every package was built, installed, and its installed NEVRA compared against its recipe. The
closing gate was stronger than the campaign: a sweep over the **full** `build_order.py` list for
each flavor, not just the 25 campaign rows. All three flavors report every installed package
matching its recipe.

Evidence level is "built and installed on R9". Nothing here says anything about `R10`, `AMZN` or
`U24`, which remain untouched.

## Two Class M auto-fixes

Both are upstream drift, both confirmed on all three flavors, **both still needed on the other
three build hosts — and nothing pushes them.**

**`67c3d4f` armadillo** — 15.4.2 → 15.6.0 consolidated `fn_strans.hpp` + `fn_trans.hpp` into
`fn_xtrans.hpp` and `fn_inplace_strans.hpp` + `fn_inplace_trans.hpp` into
`fn_inplace_xtrans.hpp`, and added the `cubemul` and `permute` feature groups. 4 removed,
8 added.

The instructive part: `rpmbuild` reported only the **four missing** files and failed before
reaching its unpackaged-file check, so the four *new* headers were invisible in the error output
and would have failed the *next* build. Diffing the whole buildroot against the manifest, rather
than patching the reported lines, caught them in one pass. Two entries flagged by that diff were
deliberately **not** acted on: `libarmadillo.so.15`/`.so.15.6.0` are matched by the existing
`libarmadillo.so.*` glob, and the registry yaml is added by the builder.

**`3810fe9` petsc** — dropped a stale `include/petscmat.h.orig` entry. `patch` runs with
`--no-backup-if-mismatch`, which writes a `.orig` **only when a hunk applies with fuzz or
offset**. An earlier version's patch did mismatch, `patch` wrote the backup, and a manifest
regenerated from that buildroot captured it as a deliverable. **Every petsc package shipped since
then carried a stale, unpatched copy of a public header into `include/`.** At 3.25.5 the patch
applies at fuzz 0, no backup appears, and the entry finally broke the build — which is how it
surfaced. Ruled out the dangerous reading first: the log shows `patching file
include/petscmat.h` succeeding at fuzz 0, so this was not a silently-unpatched build.

## Four stale packages that the campaign could never have found

`environment` 2026-1 → 2026-2, `libunwind` 1.8.3-1 → -2, `nlopt` 2.10.1 → 2.11.0 (debug, gcc),
`hwloc` 2.13.0 → 2.14.0 (mkl only). Tracker rows 26–29.

None was in the campaign. All were **installed, not rebuilt**: the correct-version RPMs were
already in the local tree, built and uploaded months ago and then never installed. This is the
built-uploaded-never-installed defect previously seen on 2026-05-12, second occurrence.

Byte-identity with the published copies was **proven, not assumed** — `SHA256HEADER` and
`PAYLOADDIGEST` of all ten local files match the published values belfem supplied. Both tags
exclude the signature header, so they survive signing; a plain file checksum would have differed
on every one for an uninteresting reason. Installing the existing artifacts therefore makes this
host *byte*-identical to the repo rather than merely version-identical. Rebuilding would have
produced the same NEVRA with different bytes, which belfem cannot promote without replacing a
signed file with an unsigned one.

`hwloc` was the consequential one. It is a dependency of `pmix` and `openmpi`, so installing it
**before** the mkl column — rather than after — is the only reason mkl's MPI stack links the same
hwloc as debug and gcc. Both 2.13 and 2.14 carry SONAME `libhwloc.so.15`, so `DT_NEEDED` would
never have exposed the mismatch; confirmation came from `HWLOC_VERSION` in the installed header.

**How they were found matters more than what they were.** Not by the campaign, and not by this
host: belfem's publishing session questioned an `nlopt-2.10.1` in a drop that did not yet exist,
against the `2.11.0-1` it already serves. That prompted a full installed-vs-recipe sweep, which
found three; re-running the sweep after installing those three — instead of assuming it was
done — found `hwloc`.

## Skill defects found

1. **`/update-build` suppresses its own drift check.** `doc/BUILD_EXECUTION.md` §2 contains
   exactly the right sweep — installed NEVRA vs recipe over `build_order.py --names-only` — but
   gates it behind *"Fallback: compute it. If no tracker exists…"*. Having a tracker therefore
   disables the check that would have caught all four at preflight, before any building. The
   tracker is the package list; it is not a statement about everything the tracker omits.
   **Fix: run the sweep unconditionally in §1 preflight, per flavor, and stop for a ruling if it
   names packages the tracker does not cover.** Not yet applied.

2. **The §5.2 orphan check produces false positives for subpackages.**
   `get_flavor_package_list()` does not know about them, so `blas`, `cblas`, `lapacke` (from
   `lapack`) and the `*-examples` packages appear as orphans on every flavor. 13 of the 16
   entries it reported here were noise, which is how a real entry gets overlooked.

## Correction

An earlier Status entry recorded `petsc-baijmkl-decls.patch` as *"load-bearing on `mkl`/`intel`"*.
**That is wrong for this host.** The installed `/opt/scls/mkl/include/petscconf.h` defines
`PETSC_HAVE_MKL_INCLUDES`, `..._LIBS` and `..._SET_NUM_THREADS` but **neither**
`PETSC_HAVE_MKL_SPARSE` nor `..._SPARSE_OPTIMIZE` — both of the patch's guards are false, so it
is inert on all three R9 flavors and mkl would have built identically without it.

The error was inferring the macro from `mkl_sparse_optimize` being present in `mkl_spblas.h`.
PETSc does not enable MKL sparse because a symbol exists; the recipe passes only
`--with-blaslapack-{include,lib}` and configure did not turn it on. The authoritative source was
the generated `petscconf.h`. The recipe's own comment names **RHEL 10** as the trigger, and that
was read and under-weighted.

What survives: the upstream gating mismatch is real and unfixed in 3.25.5 — verified against the
pristine tarball, `petscmat.h:427` gates all four declarations under `MKL_SPARSE` while
`baijmkl/makefile` requires `MKL_SPARSE_OPTIMIZE` — and oneAPI 2026 has removed `mkl_dcsrmv`.
**Keep the patch.** Expect `R10` to be what actually exercises it.

## mkl-only properties, verified by inspection

- **scalapack provenance.** `readelf -d libscalapack.so` → `libmkl_gf_lp64.so.3`,
  `libmkl_sequential.so.3`, `libmkl_core.so.3`, and no `libmkl_scalapack*`/`libmkl_blacs*`.
- **MKL major SONAME.** Those are `.so.3`, so this column re-aligns mkl after the host's
  `.so.2` → `.so.3` bump. `doc/MKL_ABI_POLICY.md`: `AutoReqProv: no` means RPM metadata never
  captures it, so a rebuild on the affected host is the only fix and inspection the only proof.

## Section B predictions

Both named candidates came through clean — `ucx` 1.20 → 1.22 and `sundials` 7.8 → 7.9 produced
no drift at all. The drift appeared instead in `armadillo` and `petsc`, which section B did not
flag. The prediction method was sound (new minor series ⇒ suspect the manifest); the specific
predictions were not.

## Outstanding

- `67c3d4f` and `3810fe9` must reach `R10`, `AMZN` and `U24` before those hosts hit the same
  drift. Nothing pushes them.
- The §1 preflight fix above is not yet applied.
- `suitesparse` is installed on all three flavors despite `include_flavors: []`, with no SRPM and
  no published copy. Removal is Christian's call.
- 22 superseded artifacts (72.8 MiB) identified by `prune_old_packages.sh`, not yet applied.
