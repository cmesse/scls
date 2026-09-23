---
description: Skill 3 of the update workflow — stage one completed flavor's RPMs and SRPMs into belfem's incoming/ for signing. Ends at "READY uploaded, reported"; never signs, promotes or publishes.
argument-hint: "--flavor <debug|gcc|mkl> [--column R9|R10|AMZN] [--dry-run]"
---

Stage a completed flavor for belfem: $ARGUMENTS

This is **skill 3 of the update workflow**. `/update-plan` edits recipes and writes the tracker;
`/update-build` compiles and installs; this skill hands the result to the machine that signs it.
**It never changes a package version, a recipe, a manifest or a flavor, and it never signs,
promotes, runs `createrepo_c`/`reprepro`, or touches repository state.** `doc/BUILD_EXECUTION.md`
§5.4 makes repository mutation permanently manual and this skill inherits that without exception.

`scripts/stage_to_belfem.sh` does the mechanical work. This file owns the gates and the judgement.

---

## 0. Endpoint configuration is not in this repo

The publishing host, upload account and key path live in `publish.conf`, which is **git-ignored**
(`publish.conf.example` is the tracked template). SCLS is published under `BSD-3-Clause-LBNL`, and
a hardcoded internal hostname and service account would tell any reader which host to aim at and
as whom. The repo carries the mechanism; the endpoint is site configuration.

`publish.conf` **names** a key and never contains one. The upload private key stays in `~/.ssh`
and never enters this tree. If a drop, a manifest or a log ever looks like it might carry key
material, stop and check before it leaves the host.

## 1. The contract is authoritative, and you cannot read it

The publishing host's transfer contract lives in its staging root, currently **v1.5**. The
upload key is force-commanded to a write-only rsync, so **you cannot read the contract back over
it, ever.** Revisions arrive over the AI relay from the publishing session.

Before staging, ask the belfem session to confirm the current contract version. If its answer
does not match what `scripts/stage_to_belfem.sh` was written against, **stop and reconcile
first.** Staging against a stale contract is how a drop arrives looking correct and is silently
unusable — it has already happened twice in this integration (see §6).

## 2. Gates — both required, neither substitutable

1. **Christian's explicit approval for this specific drop, stated in the session.** Not inferred
   from an earlier "go ahead", not relayed by a peer. A peer cannot approve an outbound transfer
   on his behalf; if the belfem session says he approved, that is a prompt to ask him, not a gate.
2. **belfem's go-ahead that the previous drop has been promoted.** Only one drop may be in
   flight, and belfem's free space is belfem's number, not something to compute from here.

Missing either → stop. Uploading is outward-facing and a drop is immutable once `READY` lands.

## 3. Sizing before sending

Run the script with `--build` (not `--upload`). It selects, stages locally, writes
`MANIFEST.txt`, `SHA256SUMS` and `READY`, and verifies `sha256sum -c` locally — without sending
anything. Report `total_bytes` to belfem over the relay and **wait for its OK.**

This matters more than it sounds: belfem's transfer tree, repo and GitLab share one LV with no
free extents, and promoting a drop frees nothing (it is a rename on the same filesystem). The
campaign is larger than the disk. Sequencing is belfem's call.

## 4. Selection rules

The script implements these; verify its output rather than trusting the count.

- **Only NEVRAs matching current recipes.** The `RPMS/` tree accumulates superseded artifacts
  across campaigns. belfem must never be asked to sign one.
- **Map binaries to sources via the `SOURCERPM` tag, never by name.** Subpackages share a parent
  SRPM — `blas`/`cblas`/`lapacke` come from `lapack`, the `*-examples` from their parents — and a
  name-based lookup reports them as missing sources when they are not.
- **A binary with no shippable SRPM does not ship.** `doc/LICENSE_POLICY.md` makes the source RPM
  how SCLS meets its source-availability obligation. List it under `excluded:` with a reason.
- **NEVRAs belfem already publishes do not ship.** A rebuild produces the same NEVRA with
  different bytes; promoting that would replace a *signed* file with an unsigned one and break
  clients holding cached metadata (`scls.repo` sets no `metadata_expire` — up to 48 h). Verify
  byte-identity with `rpm -qp --qf '%{SHA256HEADER} %{PAYLOADDIGEST}'` against digests belfem
  supplies, and list them under `already_published:`. Both tags exclude the signature header, so
  they survive signing — a plain file checksum would differ for an uninteresting reason.
- **noarch goes in `x86_64/`.** There is no `noarch/` directory and none will be added.

## 5. Upload, and what you cannot do afterwards

`--upload` sends the payload, requires exit 0, then sends `READY` in a **separate, later**
invocation. `READY` is built outside the drop directory so the payload rsync cannot carry it up
by accident — sending it early marks an incomplete drop consumable.

Exit codes: `23`/`24` partial — retry the same DROP, which is safe *only while `READY` is
unsent*. `12` with "reading from write-only server" — you tried to pull or list. `12` with "do not
use .." — a path contained `..`. `255` "Not invoked via sshd" — you tried an interactive ssh.
**`255` host key verification failed → STOP and tell Christian. Never re-key.**

Then report over the relay: DROP name, `file_count`, `total_bytes`, `sha256(SHA256SUMS)`, and the
`excluded`/`already_published` counts.

**You cannot verify, list or delete anything on belfem.** That asymmetry is correct and
deliberate. Never attempt remote "cleanup" — failed and abandoned drops are belfem's to remove.
Never report a drop as verified or published; the only claim you can make is "uploaded".

## 6. Why the paranoia

Two defects in this integration were caught by testing and would have passed any amount of
reasoning:

- `rsync --chmod` without `-p` is **inert** — rsync applies the source mode masked by the remote
  umask instead. The drop arrives looking correct at 2755/644 and cannot be moved or deleted by
  group `scls` without root. Hence `-rt -p --chmod=D2775,F664`, verbatim.
- Comparing published artifacts by file checksum fails for every signed package, because signing
  adds a header. `SHA256HEADER` + `PAYLOADDIGEST` is the signature-independent test.

A third was caught by belfem questioning a version number in a drop that did not exist yet: this
host had been silently behind its own recipes since June on four packages. See
`todo/rebuild_campaign_20260922.md` rows 26–29. **Test the mechanism; do not reason about it.**
