# EL9 and EL10: rebuild ipopt on debug and gcc at the unchanged release; re-run gate G2

**Written:** 2026-10-05 on the AMZN build host, on Christian's instruction.
**For:** the EL9 session (tracker column `R9`) and the EL10 session (column `R10`).
**Tracker:** `todo/rebuild_campaign_20261004.md` (row 8, gate G2). **Policy:** `doc/CAMPAIGN_POLICY.md`.

## Why

Two things changed on 2026-10-05, after EL9 and EL10 had finished the campaign.

1. **ipopt 3.14.20-1 is rebuilt on every flavor, at the unchanged release.** Until now only the mkl
   package was rebuilt (RUNPATH fix `0a256a1`); debug and gcc were "kept: build unchanged" and
   carry the older `%changelog`. Christian wants the changelogs identical across flavors:
   "I would rebuild ipopt anyways so that the changelogs are identical", and on the release:
   "I override this rule for this time. We don't need to bump"; for this file: "We don't bump the
   versions. I override for this time." In the belfem session: "yes, I confirm the override. I
   will also rebuild ipopt for el9 and el10".
   `scls-{debug,gcc}-ipopt-3.14.20-1` is published and signed on el9 and el10, so the rebuilt
   package replaces a published RPM at the same NEVRA. That is the override.
2. **Gate G2 was rewritten** (`11e38af`). As first written it could not run on mkl where the loader
   dies under `LD_BIND_NOW=1` (EL9 and AMZN; EL10 was not affected). The new text is in the
   tracker. EL9 mkl has only hand-made substitute evidence on record; both hosts re-run the gate.

Nothing else changes: no recipe, manifest, patch or `python/` edit, no release bump, no other
package. The build steps of ipopt on debug and gcc are unchanged; the spec differs in
`%changelog` only.

## What is already in place

- `scripts/stage_to_belfem.sh --replace FILE --replace-reason TEXT` works on the RPM path
  (`b333cf8`). A binary package named in FILE whose NEVRA is published goes into the payload with
  its SRPM, and both are written under `replace_published:`. A name that selects nothing stops the
  script. Without `--replace` the selection is unchanged.
  Evidence so far: select-only runs on AMZN (no `--replace`: 0 files; `--replace scls-gcc-ipopt`:
  2 files, `replace_published: 2`; unknown name: exit 2), and one real drop:
  `AMZN-gcc-20261005T1033Z` (2 files) was staged with `--build`, uploaded, and verified by belfem
  with the manifest accepted as written.
- belfem is patched for the same interface (Server session, 2026-10-05). Its verifier fails a
  published NEVRA in the payload that is not under `replace_published:`, a listed NEVRA that is not
  published or not in the payload, a listed NEVRA whose `SHA256HEADER` and `PAYLOADDIGEST` equal
  the published copy, and an entry without `reason: <text>`. On promotion it moves the published
  files to the attic, signs the new ones and regenerates the repodata.
- Known consequences, stated to Christian by belfem: clients with cached metadata can see a
  checksum mismatch on this one package for up to 48 h (`dnf clean metadata`); machines that
  already installed 3.14.20-1 keep the old build.

## Steps, per host

Flavors: **debug, then gcc.** mkl is not rebuilt: its ipopt already has today's changelog.

### 1. Sync

```bash
git checkout flavor.conf
git fetch --prune && git switch ipopt && git pull --ff-only   # 11e38af or later
git log --oneline -1
```

Set `python:` in `flavor.conf` as the host needs it (EL10: hosts file §6). Never commit `flavor.conf`.

### 2. Rebuild and install, per flavor

```bash
F=debug        # then gcc
sed -i "s/^flavor: .*/flavor: $F/" flavor.conf
rpm -qp --qf '%{SHA256HEADER} %{PAYLOADDIGEST}\n' \
    rpmbuild/RPMS/x86_64/scls-$F-ipopt-3.14.20-1.$(rpm --eval '%{dist}' | sed 's/^\.//').x86_64.rpm   # the published build, "before"
./scls build ipopt && ./scls install ipopt
rpm -q --qf '%{VERSION}-%{RELEASE} built %{BUILDTIME:date}\n' scls-$F-ipopt   # 3.14.20-1, built today
rpm -q --changelog scls-$F-ipopt | head -3                                    # starts with the 2026-10-04 entry
```

Then gate **G3** of the tracker on that flavor (the `ldd -r` loop, `mpirun`, hs071 with mumps and
spral). On AMZN gcc the rebuild took 112 s and G3 passes. If the binary's two digests are equal to
the "before" values, the build was not replaced: stop and report.

### 3. Gate G2, new text, all three flavors

Run G2 from the tracker as it is now, on debug, gcc and mkl (`P=/opt/scls/<F>`). No rebuild is
needed for it. Expected:

- debug, gcc: `G2 PASS`, with both parts.
- mkl on EL9: one `G2 note: no loader log ...` line, then `G2 PASS`.
- mkl on EL10: `G2 PASS` with both parts (the loader survives `LD_BIND_NOW` there).

Anything else is a finding in the policy §2 format. Do not edit the gate on the host.

### 4. Standing gates, then the replacement drop, per flavor

1. Drift sweep empty, `scls-<F>` installed, `scripts/check_mkl_linkage.sh --flavor <F> --prefix /opt/scls/<F>` passes.
2. Regenerate `work/publish/published-<el9|el10>.txt` from belfem's public repodata (x86_64 and
   source `primary.xml`), keeping the old file. With a stale list the replacement is not
   recognised as published and the script refuses the name.
3. Stage:

   ```bash
   echo "scls-$F-ipopt" > /tmp/replace-$F.txt
   scripts/stage_to_belfem.sh --flavor $F --column <R9|R10> \
       --replace /tmp/replace-$F.txt \
       --replace-reason "rebuild at the unchanged release so %changelog matches mkl (Christian 2026-10-05)"
   ```

   Expected, and nothing else: `payload: 1 binaries + 1 source files = 2 files`,
   `replace_published: 2`, `excluded:` as before on that host. Then the same command with
   `--build`. A payload with more than these two files is a finding: report before uploading.
4. Report to belfem over the relay, verbatim from the script: drop name, `file_count`,
   `total_bytes`, `sha256(SHA256SUMS)`, `excluded`, `already_published`, `replace_published`,
   `git_head`, the linkage result, and the binary's "before" and "after" digests.

### 5. Upload

One drop in flight, debug before gcc, each after belfem's size OK and the promotion of the
previous one, and **only on Christian's go-ahead for that drop in your own session**
(`.claude/commands/stage-drop.md` §2). `--upload --drop <DROP>`, so the bytes that were sized are
the bytes that go. Do not commit between `--build` and the upload: the drop records `git_head`.

### 6. Record

- Tracker row 8: the `R9 DBG`, `R9 GCC`, `R10 DBG`, `R10 GCC` cells go from
  `kept: build unchanged` to `[x] (rebuilt 2026-10-05, same release)`, as `AMZN GCC` already did.
- A dated Status line per host: the rebuilds, G3, the G2 results with the new text, the drops.
- A short devlog entry per host, or a section in the host's existing campaign devlog.
- `git checkout flavor.conf`. Commit on the branch; push only on Christian's word.
- Tick below, and delete this file when all four cells and both G2 re-runs are done.

| | EL9 debug | EL9 gcc | EL9 mkl | EL10 debug | EL10 gcc | EL10 mkl |
|---|---|---|---|---|---|---|
| ipopt rebuilt and installed, G3 passes | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| G2, new text | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| replacement drop staged with `--build` | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| uploaded, promoted | [ ] | [ ] | n/a | [ ] | [ ] | n/a |

## Not covered here

U24 and U26 are building the campaign now. Whether they rebuild ipopt on debug and gcc too, and
replace the published .debs, is Christian's decision; this file does not ask for it.
