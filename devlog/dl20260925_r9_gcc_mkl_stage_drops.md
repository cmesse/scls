# 2026-09-25 — R9-gcc and R9-mkl staged and uploaded to belfem; two findings

Drops two and three of the R9 campaign, `/stage-drop` for the `gcc` and `mkl` flavors, each ending
where the skill ends: READY uploaded, reported. Nothing signed, promoted or published from this
host. With these, all three R9 columns are staged and R9 is done on this side.

Sections 1 and 2 are the gcc drop and the contract reconciliation; §3 is the finding that came out
of it; §4 is a false alarm worth recording; §5 is the mkl drop; §6 is state.

## 1. The gcc drop

    drop:               R9-gcc-20260925T0929Z
    file_count:         53   (28 binaries + 25 SRPMs)
    total_bytes:        792492951
    sha256(SHA256SUMS): 143779e8ca9672e43848db7d0009b03f4ecb905afd01425e3ab16c0b56305e90
    excluded:           1
    already_published:  24
    git_head:           15bdbd2993e1c4f1e865fffb201baf43580fb26e

Both gates held and neither was inferred. Christian approved this exact drop name in session;
belfem (claude-06) gave the size OK separately (12 GB free, incoming/ empty, ~11.2 GB left after,
against a 2 GB floor). belfem's own message that Christian had approved was treated as a prompt to
ask him, not as the gate — per `.claude/commands/stage-drop.md` §2, a peer cannot approve an
outbound transfer on his behalf.

Upload used `--upload --drop`, so the staged bytes whose size was approved are the bytes that went;
the script re-verified (`sha256sum -c` over all 53, READY matched SHA256SUMS) and did not restage.
Payload rsync returned 0, then READY went as its own transfer. No 23/24, no 12, no 255.

**Verification was of the staged tree, not of the script's counters** — §6's "test the mechanism,
do not reason about it". Independent `sha256sum -c` over all 53 files; `find`/byte-sum reproduced
53 and 792492951; SHA256SUMS had 53 lines; layout `el9/{x86_64,source}` with no `noarch/`; payload
∩ already_published empty as a set intersection rather than a count comparison; READY outside the
drop dir at `work/staging/READY`. Full accounting: of the 41 installed `scls-gcc-*` packages, every
one is in the payload, in already_published, or is the single exclusion.

The exclusion is suitesparse, licence first:

    scls-gcc-suitesparse-7.12.2-1.el9.x86_64  reason: licence — GPL-2 linkable, not shipped as a
    binary (doc/LICENSE_POLICY.md); recipe carries include_flavors: [] so it is never built by default

**Evidence ceiling.** The claim this host can make is "uploaded". Arrival, signature and promotion
are belfem's to confirm; the upload key is force-commanded write-only, so nothing on that side can
be listed, verified or deleted from here.

## 2. Contract v1.6 reconciliation — behaviour current, header stale

belfem reports the transfer contract is now v1.6; `scripts/stage_to_belfem.sh:4` still says
"Written against transfer contract v1.5". §1 of the skill says a version mismatch is a stop.
Reconciled rather than stopped, because the sole v1.5 → v1.6 delta is that the suitesparse
`excluded:` reason leads with the governing rule, and that shipped in `a580f09`; the ordering is
implemented at `scripts/stage_to_belfem.sh:151-154`, evaluating the NEVER_SHIP licence check before
the artifact-presence and version-match checks.

This drop *demonstrates* the ordering rather than merely asserting it: a suitesparse binary RPM
exists in the tree, so under v1.5 ordering the presence check would have passed and some other
reason would have been emitted. Licence won. belfem agreed this is a reconciliation, not a stop.
Only the line-4 comment is stale — cosmetic, unfixed, deliberately not touched mid-drop.

## 3. Finding — selection by `rpm -qa` can drop a package with no trace

**Open. Needs Christian's decision; nothing changed.**

Selection is driven by `rpm -qa` of *installed* packages
(`scripts/stage_to_belfem.sh:199`). A package that is not installed on the build host can therefore
never be selected — and unlike an exclusion it leaves no `excluded:` line, so the manifest cannot
show that it was skipped. It simply is not there.

Found while accounting for this drop containing no noarch RPMs at all: `scls-gcc` (the meta) and
`scls-gcc-examples` are not installed here. Benign this time — both are published at `2026-1`, this
campaign did not rebuild them, so nothing was withheld.

The latent case is not benign. The meta-package's Requires are generated from the flavor's package
set plus `extra_packages:`, so a campaign that changes that set bumps the meta's release. On a host
where the meta is not installed, that new NEVRA would be omitted from the drop silently, and the
repository would carry a meta-package pointing at the previous set. This is the same failure shape
as rows 26–29 of `todo/rebuild_campaign_20260922.md`: the host was silently behind its own recipes
and only an outside question surfaced it.

belfem's proposal, which I agree with: drive selection from the recipes or `build_order.py` and
cross-check *that* against what is installed, so a package that cannot be shipped gets its own line
with a reason instead of disappearing. That is a `scripts/` change and it is not urgent enough to
make mid-campaign — R9-mkl should go out under the mechanism that R9-debug and R9-gcc went out
under, and this should land before the next campaign, not during this one.

## 4. R10's "missing commits" — nothing was missing

belfem relayed that the R10 host (scls-ae) could not pull v1.6 `stage_to_belfem.sh` or the
`/stage-drop` skill from `origin/devel`, and asked for a push. No push was needed:
`git ls-remote origin refs/heads/devel` returns `15bdbd2`, local `devel` is identical, and
`61e3e3b`, `fc3edbe`, `c27485d`, `772a9fe`, `a580f09` are all ancestors of it. `main` is at
`7f6b13c` and carries none of them, which is the likely explanation. Also worth noting for whoever
hits this next: the skill is `.claude/commands/stage-drop.md`, not `.claude/skills/`.

## 5. The mkl drop

    drop:               R9-mkl-20260925T0946Z
    file_count:         51   (27 binaries + 24 SRPMs)
    total_bytes:        763250549
    sha256(SHA256SUMS): da4a7b70530f8e277d6ef9a25926b74ff695ab140fb1916f83d55b39d18a3503
    excluded:           1
    already_published:  28
    git_head:           15bdbd2993e1c4f1e865fffb201baf43580fb26e

Same gate discipline and the same verification battery as §1, all clean: independent `sha256sum -c`
over the 51 staged files, `find`/byte-sum reproducing 51 and 763250549, `el9/{x86_64,source}` with
no `noarch/`, payload ∩ already_published empty as a set intersection, READY outside the drop dir.
Of 42 installed `scls-mkl-*` packages every one is in the payload, in already_published, or is the
single exclusion (suitesparse, licence first, as for gcc).

belfem staged this against the published list this host already held, having regenerated its own
after the gcc promotion and confirmed only `scls-gcc-*` lines moved. Rather than take that on
trust, the risk it implies was checked directly: all 28 already_published entries and all 51
payload lines are `scls-mkl-*`, so the stale `scls-debug-*` and `scls-gcc-*` lines in the local
copy could not have participated in the selection at all. The staleness is real and harmless, and
the reason it is harmless is structural rather than incidental.

**MKL ScaLAPACK rule verified in the bits, before upload.** `doc/MKL_ABI_POLICY.md` and the
standing rule require MKL flavors to link the stack's own ScaLAPACK, never `libmkl_scalapack*` or
`libmkl_blacs*`. belfem said it would check this with `readelf -d` on extracted files after
arrival. Running the equivalent *before* upload was the better order, because a drop is immutable
once READY lands and a violation found afterwards costs a whole promotion cycle. All 27 binary
payloads were decompressed and searched for those two names as literal strings: zero occurrences
anywhere. `libscalapack` is referenced by butterflypack, mumps, petsc, slepc, strumpack and
scalapack itself. This is weaker than belfem's `readelf` pass — a string hit could in principle sit
in a non-ELF file, and absence of the string is the direction that matters here — so it was
reported to belfem as corroboration, not as a substitute. RPM `Requires` are useless for this
question under `AutoReqProv: no`, which is exactly why both checks read the shipped files.

## 6. State

R9-debug promoted and cleared on belfem (51 files signed under key 835e8a44, superseded files
parked in an attic, repodata and `repomd.xml.asc` good).

R9-gcc uploaded and, per belfem, passing every check on arrival: READY equal to
sha256(SHA256SUMS) and to `143779e8…5e90`; `sha256sum -c` OK on all 53; byte sum exactly
792492951; file set equal to the SHA256SUMS paths; modes 2775/664 group `scls` (the `-p`
lesson from §6 holding in practice); manifest NEVRA list equal to the payload recomputed from
the RPM headers; zero overlap with the published list regenerated after the debug promotion;
arch and directory placement right; every binary's SRPM present; 24/24 already_published digests
matching the repo; the one exclusion suitesparse, licence first. Every payload file supersedes
exactly one published version, 772 MB superseded. **These are belfem's checks reported over the
relay, not this host's** — the ceiling in §1 stands. Now with Christian for promotion.

R9-gcc has since been promoted and cleared on belfem: 53 files in the repo and signed under key
835e8a44, the 53 superseded files parked in the attic, repodata listing the new versions and both
`repomd.xml.asc` signatures good.

R9-mkl uploaded and with belfem, awaiting the arrival checks and promotion. Nothing is queued on
this host.

**All three R9 columns are now staged** — debug and gcc promoted, mkl in flight. R10, AMZN and U24
remain untouched open columns in `todo/rebuild_campaign_20260922.md`; each needs a build host, which
is a separate conversation.

One operational note from belfem, recorded because it explains an asymmetry someone will hit: the
promote script signs in place, so a drop's `SHA256SUMS` no longer matches the repo copies after
promotion, and its resume path now accepts changed files only if they carry Christian's signature
and pass `rpm -K`. Nothing changes on the staging side — `SHA256SUMS` is computed pre-signature here
and is only meaningful until signing. It does mean a digest quoted from this host can never be
re-checked against the promoted copy, which is the same reason `already_published` comparisons use
`SHA256HEADER` + `PAYLOADDIGEST` rather than a file checksum (§6 of the skill).
