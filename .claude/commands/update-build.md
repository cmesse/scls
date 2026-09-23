---
description: Skill 2 of the update workflow — build and install a rebuild campaign on one build host, flavor by flavor, fixing manifest/patch/system-dep drift automatically and halting on anything else.
argument-hint: "[--flavors debug,gcc,mkl] [--from <pkg>] [--retry-blocked] [--tracker <path>] [--no-cleanup]"
---

Execute a rebuild campaign on this build host: $ARGUMENTS

This is **skill 2 of two**. `/update-plan` (skill 1) runs on the dev host and ends with recipes,
changelogs and manifests edited and a tracker committed on `devel`. This skill compiles and
installs what that campaign changed. **It never changes a package version, a configure option, a
dependency list or a flavor.**

**Read [`doc/BUILD_EXECUTION.md`](../../doc/BUILD_EXECUTION.md) before step 1 and follow it.** It
holds the preflight, the per-package build/install cycle, the three auto-fix classes, the halt
protocol, cleanup and reporting. This file only adds what is specific to an update run: which
packages, in which order, across which flavors, and how the tracker is kept.

Arguments: `--flavors` overrides the default sequence. `--from <pkg>` resumes at a row.
`--retry-blocked` re-attempts cells marked `--`. `--tracker <path>` overrides tracker selection.
`--no-cleanup` skips §5 of the execution doc.

---

## 1. Preflight

`doc/BUILD_EXECUTION.md` §1 in full — host classification, `devel` + `git pull --ff-only`,
`sudo -n true` (with the bootstrap block if it fails: **this is the first-run setup for a new VM**
and the run stops there until it is done), disk space, log directory, and **§1.6 the drift
sweep**.

§1.6 matters most here, because a tracker is exactly the condition under which it is easiest to
skip. The tracker tells you which packages to build; it says nothing about the packages it
omits. Run the sweep over the full `build_order.py` list for each flavor in the sequence,
subtract the tracker's rows, and **stop and ask if anything is left** — those are packages this
run will not fix and will nevertheless build on top of.

Then report the host column (`R9` / `R10` / `AMZN` / `U24`) and the flavor sequence you are about
to run, and only then start building.

## 2. Target set

**Primary: the tracker.** The newest `todo/rebuild_campaign_*.md` on `devel`, unless `--tracker`
names one. Section A is the package list and the build order; the `G` column marks packages that
could be built in parallel, but build them serially — a parallel make inside one package already
saturates these VMs.

**Fallback: compute it.** If no tracker exists (an ad-hoc bump, or a host that has fallen behind
by more than one campaign), derive the stale set yourself. Do not use
`get_next_unbuilt_package()` — it treats "a registry file exists" as done and is blind to version
changes, which is exactly the case here. Compare the installed NEVRA against the recipe:

```bash
for p in $(python python/build_order.py recipes --flavor $F --names-only); do
    want=$(python -c "import yaml;r=yaml.safe_load(open('recipes/$p.yaml'));print(f\"{r['version']}-{r.get('release',1)}\")")
    have=$(rpm -q --qf '%{VERSION}-%{RELEASE}' scls-$F-$p 2>/dev/null | sed "s/$(rpm --eval '%{dist}')\$//")
    [ "$want" = "$have" ] || echo "$p  $have -> $want"
done
```

(`dpkg-query -W -f='${Version}'` on U24.) The output is already in build order. Show it and
confirm the list with Christian before building — a computed set has no §C to say what was
deliberately left out.

## 3. Flavor sequence

Default **`debug` → `gcc` → `mkl`**, and on the `AMZN` column **`gcc` → `mkl`** — Amazon Linux
does not ship `debug`. `debug` is the canary: it uses the Netlib reference BLAS and unoptimised
flags, so it surfaces manifest drift and compile errors fastest and without MKL in the picture.

`flavor.conf` is git-tracked. This skill owns it for the duration of the run:

1. Record the original `flavor:` value.
2. Rewrite only that line between flavors — leave `python:`, `gcc_toolset:` and `extra_packages:`
   exactly as the host has them.
3. Restore the original value at the end of the run, including on a halt.
4. **Never commit `flavor.conf`.** If it shows up in `git status` at the end, the restore failed —
   fix that before reporting.

Finish a flavor completely before switching. A halt in `debug` (`doc/BUILD_EXECUTION.md` §4) stops
the whole run, not just that flavor: the same failure is waiting in `gcc` and `mkl`.

## 4. Per package

`doc/BUILD_EXECUTION.md` §2 for the cycle and §3 for triage. In addition, for each row of section
A whose cell for this (column, flavor) is `[ ]`:

- `[x]` already → skip silently.
- `n/a` → skip; the package is not in this flavor's build order. Cross-check against
  `build_order.py --names-only` once at the start of the flavor: a package the tracker calls `n/a`
  that the resolver *does* list means the tracker and the recipes disagree, which is a stop.
- `--` → skip unless `--retry-blocked`.

After a successful install, tick the cell to `[x]` in place. Edit only that one cell; never
reflow the table, never touch section C.

**Committing.** Auto-fixes are committed immediately, one commit each, with the message from the
class in `doc/BUILD_EXECUTION.md` §3 — they are what another host needs to pull. Tracker ticks are
committed once per completed flavor (`chore(tracker): <column> <flavor> — N packages built and
installed`) and once at the end of the run, not per package: a commit per cell buries the fixes in
noise. **No pushes.**

## 5. Cleanup and report

`doc/BUILD_EXECUTION.md` §5 and §6. Specific to an update run:

- The dated `## Status` line names the column, the flavors completed, and the package counts —
  e.g. `2026-09-22 — R9: debug 25/25, gcc 25/25, mkl 25/25 installed. 2 manifest fixes (a1b2c3d, e4f5g6h).`
- The final message to Christian must say plainly what is **not** done: the other three columns,
  and any flavor cut short. This host's green run says nothing about the others.
- If manifest fixes were committed here, say so prominently — those commits need to reach the
  other build hosts before they hit the same drift, and nothing pushes them automatically.
