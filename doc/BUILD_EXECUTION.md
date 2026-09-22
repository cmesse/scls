# SCLS Build Execution — the shared build/install loop

This is the procedure that actually compiles and installs packages on a build host. It is the
common core of two entry points and is not invoked on its own:

- **`/update-build`** — rebuild the packages an update campaign changed (`.claude/commands/update-build.md`).
- **`/build-stack`** — build the whole stack from nothing (`.claude/commands/build-stack.md`).

Both read this file first. Everything below applies to both unless a section says otherwise.
Scope of the split: the entry point decides *which packages and in what order*; this file decides
*what happens to one package*, *what may be fixed automatically*, and *when to stop*.

`/update-plan` is the other half of the update workflow and runs on the dev host: it edits
recipes and writes the tracker. Nothing in this file ever changes a package version.

---

## 0. Non-negotiables

1. **The build-configuration approval rule in `CLAUDE.md` stands.** §3 below defines three narrow
   auto-fix classes that Christian approved on 2026-09-22 for unattended runs. They are the
   *entire* carve-out. Configure/CMake options, dependency lists, `include_flavors:`/
   `exclude_flavors:`, compilers, flags, prefixes, new patches and version changes are **not** in
   it — any of those means stop and ask, even when the fix looks obvious and even when it is the
   only thing between you and a green build.
2. **Never push.** Auto-fixes are committed on `devel` and left for Christian to review and
   propagate. Four build hosts share one upstream; a push from an unattended run is how two of
   them end up disagreeing about a manifest.
3. **Never build on the macOS dev host.** It cannot run `rpmbuild` (`doc/AI_COLLABORATION_PROTOCOL.md`
   §11). If `uname -s` is not `Linux`, refuse and say why.
4. **A package counts as done only when `./scls install` exits 0** and the installed NEVRA matches
   the recipe. "Built" is not "installed"; a tracker cell is ticked on the second, never the first.
5. **Destructive host operations get explicit confirmation** — uninstalling stack packages,
   `prune_old_packages.sh --apply`, anything touching the published repository. Building and
   installing do not; that is the job.

---

## 1. Preflight — once per host, per session

Run all of this before the first build and report the result as a short block. Any failure here
stops the run; none of it is fixable mid-flight.

**1.1 Host.** `uname -s` = `Linux`. Read `/etc/os-release` and classify the host into exactly one
tracker column:

| `ID` / `VERSION_ID` | Column | Package format | Builds `debug`? |
|---|---|---|---|
| `rocky`/`rhel`/`almalinux` 9.x | `R9` | RPM | yes |
| `rocky`/`rhel`/`almalinux` 10.x | `R10` | RPM | yes |
| `amzn` 2023 | `AMZN` | RPM | **no** |
| `ubuntu` 24.04 | `U24` | DEB | yes |

Anything else: stop and report. The `scls` wrapper's own RPM/DEB detection must agree — if
`./scls list` reports a format you did not expect, trust the wrapper and stop.

**1.2 Git.** Be on `devel` (`git checkout devel` if not, and say so). `git pull --ff-only` once,
here, so that manifest fixes committed from another host are picked up before anything is built —
never mid-run, where it could change a recipe between a build and its install. Record `HEAD`;
the final report quotes it. A dirty tree at preflight is reported and left alone: it is either
Christian's work in progress or a previous run's unfinished business, and either way the run
does not start on top of it without him saying so.

**1.3 Sudo.** The builders shell out to `sudo dnf install -y` / `sudo apt-get install -y`
themselves (`python/rpm_builder.py:290-296`, `python/deb_builder.py:168-200`), so sudo must work
*non-interactively* or every install in the run blocks on a password prompt you cannot see.

Test: `sudo -n true`.

- Exit 0 → proceed.
- Non-zero → this host has not been set up. Print the bootstrap block below, ask Christian to run
  one of the two options, and **stop**. Do not attempt a run that will stall at the first install.

```
=== SCLS build host sudo setup (one time per VM) ===

Option A — passwordless for the package manager only (recommended):

  sudo tee /etc/sudoers.d/scls-build >/dev/null <<EOF
  $(id -un) ALL=(root) NOPASSWD: /usr/bin/dnf, /usr/bin/apt-get, /usr/bin/dpkg, /usr/bin/rpm
  EOF
  sudo chmod 0440 /etc/sudoers.d/scls-build
  sudo visudo -c

  Scoped to the four binaries the builders call, so it is not a blanket NOPASSWD.
  Nothing to re-prime after a reboot.

Option B — non-expiring timestamp, primed once:

  sudo tee /etc/sudoers.d/scls-timeout >/dev/null <<'EOF'
  Defaults timestamp_timeout=-1
  Defaults !tty_tickets
  EOF
  sudo chmod 0440 /etc/sudoers.d/scls-timeout
  sudo -v          # enter the password once

  `!tty_tickets` is not optional here. Each command in an automated run may get a
  different pty, and sudo's default per-tty timestamps would make the credential
  primed in one command invisible to the next — the prompt would come back
  mid-run despite the infinite timeout.
```

**1.4 Space.** `df -h` on the repo filesystem and on the install prefix. A full stack build needs
roughly 40 GB of scratch in `work/` and `rpmbuild/`. Below ~20 GB free, say so before starting
rather than dying inside PETSc.

**1.5 Log directory.** `mkdir -p work/logs`. `work/` is git-ignored, so logs never reach a commit.
Every build and install writes `work/logs/<flavor>/<pkg>.{build,install}.log`.

---

## 2. The per-package cycle

For one package `P` under flavor `F`:

```bash
./scls build P   2>&1 | tee work/logs/$F/P.build.log
./scls install P 2>&1 | tee work/logs/$F/P.install.log
```

Use `set -o pipefail` or check `${PIPESTATUS[0]}` — `tee` returns 0 even when the build failed,
and a run that mistakes a failed build for a success will happily install the previous artifact.

1. **Build.** Non-zero → §3 triage.
2. **Install.** Non-zero → §3 triage. An install failure after a successful build is usually a
   dependency ordering problem or a leftover artifact, not a compile issue; read the dnf/apt
   transaction output, not the build log.
3. **Verify the NEVRA.** The install is only believed if the installed version matches the recipe:

   ```bash
   # RPM hosts
   rpm -q --qf '%{VERSION}-%{RELEASE}\n' scls-$F-P   # strip the trailing dist tag before comparing
   # DEB hosts
   dpkg-query -W -f='${Version}\n' scls-$F-P
   ```

   against `version:` and `release:` (absent `release:` means `1`) in `recipes/P.yaml`. A mismatch
   means dnf kept an older package or the artifact selection picked the wrong file — stop, this is
   not something to fix by rebuilding.
4. **Record.** Tick the tracker cell (entry point's job — see `/update-build` §4), append to the
   run's in-memory result table.

Do not run `./scls build all` inside these loops. It resolves its own order and would build
packages the campaign did not ask for; the entry point owns the package list.

---

## 3. Triage — what may be fixed without asking

Three classes, approved 2026-09-22. Each has a symptom that identifies it, a bounded fix, and an
explicit condition under which it is *not* that class and the run stops. When a failure does not
match one of the three, or matches but hits its stop condition, go to §4. When in doubt it is §4:
the cost of a false stop is a message to Christian; the cost of a false fix is a silent
build-configuration change, which is exactly what `CLAUDE.md` exists to prevent.

Attempt each class **once** per package. A second failure of the same class on the same package
is not drift — it means the fix was wrong. Stop.

### Class M — manifest drift in `files/<pkg>.txt`

The common case, and the reason this automation exists.

**Symptoms.** `rpmbuild` ends with `Installed (but unpackaged) file(s) found:` followed by the
offending paths, or with `File not found: .../BUILDROOT/...` for a manifest entry the build no
longer produces. On DEB hosts the equivalent surfaces from `deb_builder` as missing/extra staged
files.

**Evidence.** `rpmbuild -ba` runs without `--clean` (`python/rpm_builder.py:2025`), so the
buildroot survives the failure. Enumerate it rather than trusting the error text alone:

```bash
find rpmbuild/BUILDROOT/scls-$F-P-*/ -type f -o -type l | sed "s|.*$PREFIX|%{prefix}|" | sort
```

**Fix.** Edit `files/P.txt` to match what the build produced, following the conventions already in
the file and in `rpm_builder.get_file_list()`:

- Entries are `%{prefix}`-relative.
- Versioned shared libraries collapse to the pair `%{prefix}/lib/libfoo.so` + `%{prefix}/lib/libfoo.so.*`.
- Version-stamped **directories** need no edit — `get_file_list()` collapses them and
  `glob_dir_version()` rewrites the trailing version to a glob.
- Version-stamped **files** (`libopenblas-r0.3.34.so`, `bin/vtkWrapPython-9.6`) are listed
  individually and must be edited by hand.
- `%{version}` is not a substitute for a partial version in a directory name; RPM expands it to
  the full recipe version.

**Every added line must correspond to a file that exists in the buildroot.** Never add a path
speculatively to silence an error, and never delete an entry merely because it is missing —
a file that disappeared from the install may be a build-option regression, which is §4.

**Stop instead if:** the drift is large enough to suggest a different build (e.g. an entire
`lib/cmake/` tree gone), or the missing file is a library another recipe links against. A minor
series bump adding a handful of headers is drift; a package losing its `.so` is not.

**Commit.** `fix(files): P manifest drift on <column> — N added, M removed`, body naming the files
and the version transition that caused it. Then re-run the build from §2 step 1.

### Class P — patch refresh, offsets only

**Symptoms.** The patch step fails under `--fuzz=0`, or reports hunks succeeding at an offset.

**Diagnosis.** `patch -p1 --dry-run -N -F0 < patches/P/<patch>` against the extracted tree.

**Fix.** Only when every hunk still applies and only the line numbers moved: regenerate the patch
against the new tree so it applies at fuzz 0 and offset 0. The patch's *content* — what it
changes and why — must be byte-identical in effect. Diff the before/after applied trees if there
is any doubt.

**Stop instead if:** any hunk fails outright, or the patch reverse-applies (upstream took it).
Reverse-application means the patch should be *dropped*, and dropping a patch is a recipe change —
`/update-plan`'s job, not this one.

**Commit.** `fix(patches): refresh P/<patch> for <version> (context only, no semantic change)`.

### Class D — missing system build dependency

**Symptoms.** configure/CMake fails on a header, library or tool that a distro package provides
and this host simply does not have installed.

**Fix.**
1. Identify the provider: `dnf provides '*/<header>'` (RPM) or `apt-file search <header>` (DEB).
2. Install it on the host.
3. Add the **RHEL** name to `rpm_build_requires:` in `recipes/P.yaml` — flat list, or the
   per-flavor dict with `all:` if one is already there. Add a comment naming the header or symbol
   that forced it, per `CLAUDE.md`.
4. **Add the Debian translation to `packaging/system_packages.yaml`.** A RHEL name referenced by a
   recipe with no entry there is a hard error in `deb_builder` — omitting this breaks the Ubuntu
   host the next time it builds this package.
5. Add a line to `changelogs/P.md`.

**On a DEB host this fix runs backwards, and that is where it can go wrong.** `apt-file` gives you
a Debian name, the recipe key wants the RHEL one, and there is no `dnf` on the host to resolve it.
Establish the RHEL name from evidence, not convention: a reverse lookup in
`packaging/system_packages.yaml` (the Debian name already appears as a value for some RHEL key),
or the same package already named in another recipe. If neither settles it, **stop and ask** —
a guessed RHEL name is accepted silently by the Ubuntu build and breaks `R9`, `R10` and `AMZN` the
next time any of them builds this package, with nothing in this run to indicate it happened.

**This is the one class that edits `recipes/`,** and it is confined to the three system-package
keys. `rpm_build_requires:` affects the build host only; `rpm_requires:`/`rpm_recommends:` change
what ships and are **not** in the carve-out — if the missing library is needed at *runtime*, stop
and ask.

**Stop instead if:** the missing dependency is a library SCLS itself builds (that is a build-order
or dependency-list problem), or installing it would change what gets linked into the shipped
package (e.g. an optional accelerator that CMake auto-detects). Class D is for build tools and
headers that were always expected to be present, not for adding capability.

**Commit.** `build(deps): P needs <sysdep> on <column> — <header/symbol> at configure time`.

---

## 4. Halt protocol

When a failure is outside §3:

1. **Stop this flavor.** Do not start the next package, and do not move to the next flavor — a
   `debug` failure is the canary for `gcc` and `mkl`, and proceeding past it wastes hours.
2. **Leave a resumable tree.** Any partial auto-fix is either finished and committed or reverted.
   Never leave a half-edited manifest; the next run would read it as the current state.
3. **Record the blocker** where the entry point says (tracker `## Blockers` for `/update-build`,
   the run report otherwise): package, column, flavor, the exact failing command, the last ~30
   lines of the log, and the log path.
4. **Report** to Christian: one paragraph of diagnosis, the specific decision needed, and — when
   the fix would be a build-configuration change — the option, what breaks without it, and the
   rebuild blast radius from `python/build_order.py`. That is the `CLAUDE.md` ask, pre-assembled,
   so he can answer in one message instead of three.

Do not retry a failed build unchanged. The builds are long and a retry that changes nothing is an
hour spent proving the same thing twice. (Transient download failures are the exception: a 404 is
a stop, but a connection reset on a tarball fetch may be retried once.)

---

## 5. Cleanup — after the last flavor completes

In this order. Steps 1 and 3 are routine; steps 2 and 4 are destructive and confirmed each time.

1. **Superseded artifacts.** `./scls install` already prunes what it supersedes per package.
   Catch the rest — other flavors, builds that were never installed:
   `scripts/prune_old_packages.sh` (dry run, always), show the list, then `--apply`.
2. **Stack packages that no longer exist.** Compare the installed set against the flavor's
   package list:
   ```bash
   rpm -qa --qf '%{NAME}\n' 'scls-'$F'-*' | sort > /tmp/installed
   python -c "import sys; sys.path.insert(0,'python'); from build_order import get_flavor_package_list; print('\n'.join(sorted('scls-$F-'+p for p in get_flavor_package_list('recipes','$F'))))" > /tmp/expected
   comm -23 /tmp/installed /tmp/expected
   ```
   Anything in the difference is a rename, a dropped recipe, or a package whose `include_flavors:`
   changed. **List it, explain each entry, and remove only after Christian confirms.** A package
   that is merely not yet rebuilt in this campaign must never appear here — if one does, the
   comparison is wrong, not the stack.
3. **Build trees.** Remove `work/build/*` for completed packages. **Keep `work/sources/`** — the
   tarball cache is expensive to refill and is shared across flavors. Keep `work/logs/`.
4. **Published repository.** Pruning superseded packages from the reprepro / createrepo tree on
   belfem.lbl.gov is **never** part of an automated run. It is outward-facing and irreversible for
   anyone who has already synced. Propose it as a separate step; do it only on an explicit
   instruction naming the repository.

---

## 6. Reporting

**Always:** a final message with the result table (package × flavor, one line per flavor), the
auto-fixes applied with their commit hashes and class (M/P/D), the blockers, and the elapsed
wall-clock. Name the gate that ran — "built and installed on R9/debug" — never "verified".

**When a tracker is in play:** a dated line under its `## Status`, and blockers under
`## Blockers`. Never rewrite section C.

**Devlog** (`devlog/dlYYYYMMDD_<topic>.md`, format in `doc/AI_COLLABORATION_PROTOCOL.md` §6) when
the run produced any auto-fix or any blocker. A clean run that changed nothing gets the Status
line only — a devlog per green build is noise that buries the ones that matter.
