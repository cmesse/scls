---
description: Build and install the entire SCLS stack on this host, flavor by flavor — for a new VM or a from-scratch rebuild. Same auto-fix and halt rules as /update-build.
argument-hint: "[--flavors debug,gcc,mkl] [--no-cleanup]"
---

Build the full stack on this build host: $ARGUMENTS

Use this to bring up a **new build VM** or to rebuild a flavor from nothing. For rebuilding only
what an update campaign changed, use `/update-build` instead — this skill builds every package in
the flavor's build order, including the ones that did not change.

**Read [`doc/BUILD_EXECUTION.md`](../../doc/BUILD_EXECUTION.md) before step 1 and follow it.**
Preflight, the auto-fix classes, the halt protocol, cleanup and reporting are all there and apply
unchanged. This file differs from `/update-build` in exactly one place: the engine.

---

## 1. Preflight

`doc/BUILD_EXECUTION.md` §1 in full. On a genuinely new VM expect §1.3 to fail — that is the
normal first-run path: print the sudo bootstrap block, stop, and resume once Christian has run it.

Two additional checks that only matter from scratch:

- **`flavor.conf`.** Confirm `gcc_toolset:` and `extra_packages:` match this host. A RHEL 8-era
  host needs a toolset or its own `gcc`/`binutils` in `extra_packages:`; getting this wrong is not
  visible until something deep in the stack fails to compile. If they look wrong for the detected
  distro, say so and stop — these are build-configuration, not something to adjust silently.
- **Space.** A full stack is roughly 40 GB of scratch plus the prefix. Check before, not at PETSc.

## 2. Flavor sequence

Same as `/update-build` §3, and `flavor.conf` is owned and restored the same way: `debug` → `gcc`
→ `mkl`, `gcc` → `mkl` on `AMZN`, original value restored at the end including on a halt, never
committed.

## 3. Engine — `./scls build all`

Unlike an update run, here the whole build order *is* the target, so use the wrapper's own loop
rather than driving packages one at a time:

```bash
set -o pipefail
./scls build all 2>&1 | tee work/logs/$F/build-all.$(date +%H%M%S).log
```

It already resolves the order, does install-before-build resume, and holds a sudo credential with
a background keepalive for the whole run. Re-invoking it after a fix resumes where it stopped —
that resume behaviour is the reason to use it and the reason not to reimplement it.

On a non-zero exit:

1. Find the failing package from the `[N] build:` / `[N] install:` banner nearest the end of the
   log, and its error from the lines after it.
2. Triage per `doc/BUILD_EXECUTION.md` §3. One attempt per class per package; a second failure of
   the same class on the same package is a stop, not another fix.
3. Commit the fix, re-run `./scls build all`, and note the resume point in the report.
4. Anything outside the three classes → `doc/BUILD_EXECUTION.md` §4, halt the run.

Keep a count of resumes. More than three or four auto-fixes in one flavor is itself a finding —
it usually means the manifests in `devel` were generated on a different distro than this one, and
that is worth telling Christian before grinding through forty more packages.

## 4. Cleanup and report

`doc/BUILD_EXECUTION.md` §5 and §6, with one difference: on a first-ever build of this host,
cleanup step 2 (uninstalling stack packages that no longer exist) has nothing to compare against
and is skipped — say so rather than reporting it as clean.

The report names the host column, each flavor with its package count from
`build_order.py --names-only`, every auto-fix with its commit and class, and the wall-clock. State
explicitly that this is one host: a green full-stack build here says nothing about the other three
columns.
