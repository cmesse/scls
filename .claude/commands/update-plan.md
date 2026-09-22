---
description: Skill 1 of the update workflow — scan upstream, let Christian decide the exclusions, edit recipes, write the rebuild tracker on devel. Skill 2 (/update-build) compiles and installs from that tracker.
argument-hint: "[--dry-run] [--flavors gcc,mkl,debug]"
---

Prepare an SCLS update campaign: $ARGUMENTS

This is **skill 1 of two**. It ends with recipes edited and a tracker committed on `devel`. It
never builds anything. Building and installing is `/update-build` (skill 2), which reads the
tracker this skill writes. The tracker is the contract between the two; its format is fixed by
`todo/rebuild_campaign_20260922.md` and section 5 below — do not invent a new layout.

`--dry-run` stops after step 3 (report only, no edits). `--flavors` overrides the binary-flavor
set (default `gcc,mkl,debug`, the `PUBLIC_FLAVORS` of `python/generate_website.py`).

Hard rules, in force for every step:

- **No build-configuration change without Christian's explicit approval in this conversation**
  (`CLAUDE.md`, top section). This skill changes `version:` and `release:` only. If an upgrade
  needs a configure/cmake option, a dependency, a flavor or a new patch to build, stop, describe
  it with the blast radius, and wait.
- **Christian decides the exclusions.** Step 2 produces candidates; it does not produce a list of
  approved bumps. Ask, then proceed with the answer. Never infer "he will want this".
- **All work goes on `devel`.** Never commit to `main`. If the tree is on `main`, switch first
  (`git checkout devel`, creating it from `origin/devel` if missing) and say so.
- Register: neutral, factual. Evidence discipline from `doc/AI_COLLABORATION_PROTOCOL.md` §11 —
  the macOS dev host cannot run `rpmbuild`; everything here tops out at the generation gate.

Follow the steps IN ORDER.

## 1. Scan

Run `python python/update_checker.py all` **twice** and union the "Updates available" and
"Major version blocked by pin" sections. The checker is nondeterministic run to run
(unauthenticated GitHub API rate limiting is read as "up to date"); a package missing from one
run and present in the other is real. Keep the strategy column — commit pins need different
handling from releases.

## 2. Sort into candidates and standing exclusions

Apply these rules mechanically and show both lists. The rules are the ones already in force in
`todo/rebuild_campaign_20260922.md` §C; extend the table there if a new rule is added.

Excluded automatically, listed with the reason, never bumped by this skill:

| Rule | How to detect | Example |
|---|---|---|
| Not shipped as a binary | `include_flavors:` is `[]`, or names only `macos` / `lbl` / `intel` | openssl, automake, suitesparse, zlib |
| Commit pin | strategy `github_commit` | gklib, parmetis — moving gklib forces metis + parmetis (`doc/GKLIB_STATIC_POLICY.md`) |
| Major held by pin | listed under "blocked by pin" | hdf5 2.x |
| Apple tag series | zlib's `github_tag` on apple-oss-distributions | `100 → 100.120.1` is not a version |
| GPL-3 linkable library | `license:` is GPL-3/LGPL-3-family and the recipe is not a build-only tool (`doc/LICENSE_POLICY.md`) | FFTW is the canonical case — a distribution constraint, not a version judgement; it stays out of the binary flavors whatever upstream ships |

Everything else is a **candidate**. Present them as one table — package, current, upstream,
major-or-minor, direct dependents from `python/build_order.py` — and then **stop and ask
Christian which candidates to skip**. Major bumps get a one-line risk note (what links it, e.g.
"strumpack links butterflypack") but the decision is his. Record every skip with his stated
reason in §C of the tracker; do not add a `max_major` pin unless he asks for one.

With `--dry-run`, report the two lists and the candidate table, then stop.

## 3. Rebuild set and pre-flight

From the approved bumps:

1. **Cascade.** Reverse-dependency closure over the `->` lines of
   `python python/build_order.py recipes --flavor <f>` for each binary flavor, union across
   flavors. Packages with no `->` still count as nodes. `cmake` is a build tool and is **not** a
   cascade trigger (ASC 2026 precedent, tracker §C); `googletest` likewise. Everything reachable
   from an approved bump through a runtime dependency is in.
2. **Download.** Substitute `%{version}` in each bumped recipe's `source.url` and fetch the new
   tarball into the scratchpad (`curl -sSfL`). A 404 is a stop: the recipe URL pattern is stale
   (release-series directories — openmpi, hwloc, vtk — are the usual cause).
3. **Patches.** For every patch the recipe lists, `patch -p1 --dry-run -N -F0` against the new
   tree. Outcomes: clean → keep; applies only with fuzz → refresh the context here (rpmbuild
   runs `--fuzz=0`; skill 2 may also refresh offset-only drift unattended, but it should not
   have to); reverse-applies → upstreamed, drop it from the recipe and `git rm` the file, and
   name the upstream change in the changelog — **skill 2 halts on a reverse-applying patch, so
   this is the only place it gets caught**; fails → stop and report, that is a real port.
4. **Manifests.** grep `files/<pkg>.txt` for the old version string. Version-stamped
   *directories* need nothing (`rpm_builder.get_file_list()` globs them). Version-stamped
   *files* (`libopenblas-r0.3.33.so`, `conf/modules/petsc/3.25.4`) are edited by hand. A package
   crossing a minor series (ucx 1.20 → 1.22) may gain files; say so in the changelog and the
   tracker §B as "expect a manifest refresh at the first Linux build".
5. **Recipe-internal version strings.** grep the recipe body for the old version outside
   `version:` (hard-coded paths, `extract_dir:`, release-series URLs) — exodus once shipped the
   previous year's tarball under a new version number this way.

## 4. Edit

- Bumped packages: `version:` → new, `release:` → `1` if the field exists (leave it absent
  otherwise — absent means 1).
- Cascade packages: `release:` +1, adding the field after `version:` if absent.
- `changelogs/<pkg>.md`: new stanza at the top, `## Version <ver>-<rel> - <Day Mon DD YYYY>`.
  Bumped: `- Updated to version X` plus one bullet per patch dropped/refreshed or manifest edit.
  Cascade: `- Release bump only, no recipe content change: rebuilt because <deps> changed in the
  <date> campaign (`todo/rebuild_campaign_<date>.md`). With `AutoReqProv: no` a rebuild at an
  unchanged NEVRA is invisible to dnf/apt, so the release is bumped.`
- A release stanza written by an earlier, never-built campaign for the same package is
  **replaced**, not stacked.

Validate before writing the tracker: every recipe parses (`yaml.safe_load`), `build_order.py`
resolves for every binary flavor, `python python/rpm_builder.py --package <p> --flavor gcc
--spec-only` regenerates each bumped package at the new `Version:`/`Release:` and with the
expected `Patch` count.

## 5. Tracker and commit

Write `todo/rebuild_campaign_YYYYMMDD.md` with exactly these sections, copying the header block
and legend from `todo/rebuild_campaign_20260922.md`:

- **A. The campaign** — one row per package in `build_order.py` order for `gcc` (append
  anything only in another flavor in that flavor's order), columns
  `| # | G | Package | why | R9 DBG | R9 GCC | R9 MKL | R10 DBG | R10 GCC | R10 MKL | AMZN GCC | AMZN MKL | U24 DBG | U24 GCC | U24 MKL |`.
  `G` = build_order group. Package cell `name old → new` for bumps, `name ver-old → -new` for
  cascade. `why` = `up` or `casc (dep, dep)`. Cells start `[ ]`, or `n/a` where the package is
  not in that flavor's build order.
- **B. Verified on the dev host** — what was checked and the evidence level; what was not.
- **C. Deliberately not in the campaign** — the exclusion table, including Christian's skips
  with his reason.
- **D. Running it** — the `./scls` sequence, `debug` first.
- **Status** (dated lines) and **Blockers** (empty).

Commit on `devel` in one commit: recipes, changelogs, manifests, dropped patches, tracker.
Message: `chore(deps): <date> rebuild campaign -- <n> upstream bumps and their cascade`, body
listing bumps, cascade, patches dropped (with the upstream change named), manifest edits, what
was verified and what was not, and what was skipped with the reason. **Do not push** — Christian
propagates `devel` to the build hosts himself; skill 2 follows the same rule and adds its own
commits (per completed flavor, plus one per unattended auto-fix) on top of this one.

## 6. Report

Short: branch and commit, the count of bumps and cascade packages, per-flavor build counts, the
skips, and the two things skill 2 must expect (manifest drift candidates, canary flavor). Then
hand off: `/update-build` (skill 2, one session per build VM, execution rules in
`doc/BUILD_EXECUTION.md`) reads the tracker from here. `/build-stack` is the other consumer of
that core and is for new-VM bring-up, not for updates.
