---
description: Set up passwordless sudo for the package manager on a Linux build host, so ./scls install and Class D repairs do not stall on a password prompt. Claude prepares and verifies; Christian runs the one privileged command.
argument-hint: "[--user <name>] [--scope pkg|all] [--check]"
---

Set up (or verify) package-manager sudo on this build host: $ARGUMENTS

`scripts/grant_pkg_sudo.sh` does the mechanical work. This file owns the gates and the judgement.

---

## 0. What the grant is actually for

The builders shell out to the host package manager themselves:

- `./scls install P` → `sudo dnf install -y` / `sudo dnf reinstall -y`
  (`python/rpm_builder.py:_dnf_install_rpms`) and `sudo apt-get install -y`
  (`python/deb_builder.py:_apt_install_deb` / `_apt_install_debs`).
- Class D repairs (`doc/BUILD_EXECUTION.md`) — installing a missing host package by hand
  in the middle of a campaign.

It is **not** for `rpm_build_requires:`. Nothing in `python/` installs those: they become spec
`BuildRequires` (`python/rpm_builder.py:1773-1784`), and on the DEB side
`deb_builder.check_system_build_deps` *raises* with an `apt-get install` line for a human to run
(`python/deb_builder.py:1692-1730`). Say that plainly if asked to "make the build install its own
dependencies" — this grant does not do that and neither does anything else in the stack.

## 1. Linux only, and Claude does not run the privileged step

macOS never sudo-installs anything; the script refuses to run there, and so should you.

Claude runs `--check` and the dry run. Claude does **not** run `--apply`: the first apply needs a
sudo password on a real TTY, which the Bash tool does not have. Hand Christian the single line:

```
! scripts/grant_pkg_sudo.sh --user <name> --scope <pkg|all> --apply
```

Read §2 and §4 before filling in the scope, and say which one you are proposing and why — the two
are not interchangeable and the default is the narrow one.

Then re-run `scripts/grant_pkg_sudo.sh --check` yourself to verify the result. If `!` cannot carry
the password prompt in his client, he runs the same line in his own terminal.

## 2. Which scope, and state the blast radius once

`--scope pkg` (the default) grants four commands, statically: `/usr/bin/dnf`,
`/usr/bin/apt-get`, `/usr/bin/dpkg`, `/usr/bin/rpm` — Christian's own list. Paths that do not exist
on the host are inert (sudo never matches a missing path), so the same fragment is correct on EL
and on Debian. `yum` is deliberately **not** granted: only `python/scls.py` has a `yum` fallback,
and every target host (R9, R10, AMZN, U24) resolves `dnf`.

`--scope all` grants a blanket NOPASSWD rule plus `Defaults:<user> verifypw=never`. It is never the
default; it has to be typed.

Be straight about the trade rather than implying pkg is the safe one:

- **pkg is not a lower ceiling.** `dnf install` and `rpm -i` run package scriptlets as root, so
  NOPASSWD on either is already root on that host. What pkg buys is a narrower *audit trail*, not
  less privilege.
- **pkg does cost two working call sites.** `sudo -n true` (/update-build preflight) and `sudo -v`
  (the `scls build all` keepalive) are not among the four commands, so they keep prompting — see §4.
- **`all` is the coherent choice for a disposable compilation VM**, which is what SCLS build hosts
  are. On anything that is not one, stay with pkg and fix the two call sites instead.
- `verifypw=never` is in the `all` fragment because a blanket `NOPASSWD` alone does not satisfy
  `sudo -v` **when the user is also matched by another, password-tagged entry** — typically
  `%wheel ALL=(ALL) ALL` on an EL host. sudoers(5): "a user may only run `sudo -v` without a
  password if all of the user's entries for the current host have the NOPASSWD tag. This behavior
  may be overridden via the **verifypw** and listpw options." A matching `%wheel` rule carries the
  implicit `PASSWD` tag, so the default `verifypw=all` keeps prompting. (If the build user is in no
  such group, NOPASSWD alone would be enough and `verifypw=never` is simply inert.) `listpw` and
  `timestamp_timeout` are not needed: nothing in the flow uses `sudo -l`, and neither setting
  depends on a warm credential cache. `!authenticate` is **not** the knob
  for this — it governs running commands and is itself overridden by the PASSWD/NOPASSWD tags. An
  earlier draft of this skill had that wrong; if you see `!authenticate` in a fragment on a host,
  it is from that draft.

Either way this is a build-host grant. It does not belong on a workstation.

## 3. Safety properties worth not breaking

A syntax error under `/etc/sudoers.d` breaks sudo for **everyone**, including the sudo needed to
repair it. The script therefore:

0. refuses to change anything if `visudo -c` already fails — a host that is broken before the run
   must not be able to blame this script for it;
1. writes the fragment to `/etc/sudoers.d/.scls-build.staging` — a name the `includedir` skips,
   because names containing `.` are ignored — already `root:root` and `0440`;
2. runs `visudo -cf` on *those exact bytes*, before they are ever live;
3. `mv`s it into place (atomic rename within one directory), keeping any previous fragment in
   `.scls-build.bak`;
4. runs the whole-ruleset `visudo -c`, and on failure restores the previous fragment — it never
   deletes content it replaced;
5. if sudoers is *still* invalid after that rollback, does **not** exit. The escalated process is
   the only root on the host at that moment, so it opens an interactive root shell on the
   terminal instead. That is why the apply step belongs in a human's terminal.

If you ever rewrite this, keep the order. Validating a user-owned file in `/tmp` and then copying
it is not the same thing: it is a TOCTOU, and `visudo -cf` may refuse a non-root-owned path.

The fragment is deliberately free of timestamps and hostnames: `--apply` compares it byte-for-byte
against what is installed and reports `unchanged`, which only works if a re-run produces identical
content.

## 4. What `--scope pkg` does not cover — read this before promising an unattended run

A command-scoped `NOPASSWD` does not satisfy `sudo -n true` or `sudo -v`, because neither is one of
the granted commands. Three places in this repo test sudo that way:

| place | test | under `--scope pkg` | under `--scope all` |
|---|---|---|---|
| `doc/BUILD_EXECUTION.md` §1.3 | `sudo -n true` | fails → `/update-build` stops at preflight | expected to pass **when this drop-in is evaluated last among the matching command rules** |
| `.claude/commands/update-build.md` §1 | repeats the same test | same | same condition |
| `scls` (`build all`, lines 151-168) | `sudo -v` + `sudo -n -v` keepalive | still prompts, or exits | expected to pass via `verifypw=never` |

Every cell in the `all` column is **unverified** — see the gate below. The script checks that
`/etc/sudoers` has an includedir for `/etc/sudoers.d`, but not that the include comes *after*
`%wheel` or another later policy source, which is what "evaluated last" depends on.

So the choice is: `--scope all` and the repo plausibly needs no changes, or `--scope pkg` and those
three call sites have to move to a scoped test. My recommendation for SCLS build VMs is
`--scope all` — they are compilation-only hosts and pkg does not lower the ceiling anyway — but as
of 2026-09-23 that is a recommendation Christian has not yet accepted, not a standing decision, and
the `all` column above has never been run on a Linux host. **Do not present it as settled.**

The one gate that settles it: on the build host, as the build user, after `sudo -k`, on a terminal
that has not just used sudo — `sudo -n true`, then `sudo -n -v`. Until that has been seen passing,
`--scope all` is a plan and the three call sites are still open.

Under pkg, **do not report "the host is now set up for unattended builds"** — report that
`./scls install P` no longer prompts while the preflight and the keepalive still do.

If the three call sites are ever moved, the replacement test is `sudo -n dnf --version` (or
`sudo -n apt-get --version`): non-mutating, and unlike `sudo -n true` it tests the invocation shape
the builders actually use. That edit needs Christian's approval, and the `scls` one is a wrapper
change under the six-step script gate.

Independently of the scope: `doc/BUILD_EXECUTION.md` §1.3 still prints the old
`tee`-then-`visudo -c` block as the setup recipe. That block validates *after* the file is live.
Point at `scripts/grant_pkg_sudo.sh` instead, and say why, rather than letting someone paste it.

## 5. Harness side is separate and opt-in

Even with the grant in place, Claude gets a per-call permission prompt for `sudo dnf …` unless
`.claude/settings.json` allows it. Offer it; do not edit `settings.json` unasked. `/update-config`
is the skill for that if he says yes.

## 6. Steps

1. `scripts/grant_pkg_sudo.sh --check` — report the file state (including which scope is
   installed), the policy answer per command, the execution probe, and the two `flow:` lines.
   Distinguish them: "policy" is what sudoers permits, "exec" is `sudo -n dnf --version` actually
   running as the build user, "flow" is the two generic tests the workflows use.
2. If a grant is already in place, say which scope it is and whether that is the one wanted. The
   script is idempotent **per (user, scope)** and reports `unchanged` rather than rewriting; a
   scope change is a real rewrite and needs an explicit `--scope`.
3. Otherwise run the dry run, show Christian the fragment and the sequence, name the scope you are
   proposing and why, and hand him the `--apply` line with the target user filled in (default is
   the invoking user, or `$SUDO_USER`).
4. After he runs it, re-run `--check` and quote the `exec:` line as the evidence. Do **not** quote
   a `flow: … -> yes` seen in the same terminal that just ran `--apply` as evidence: the sudo
   timestamp is warm there (tty-scoped, 5 minutes by default), so a `%wheel` rule can be what
   answered, not the grant. The cold check is `sudo -k` and then `--check` from a fresh login.
5. Record nothing in `changelogs/` — this touches no package. A devlog entry is warranted only if
   the host setup changed something a later session would otherwise have to rediscover.

Removal is `scripts/grant_pkg_sudo.sh --remove` (also privileged, also his to run). It refuses to
delete a fragment it did not write unless `--force` is given.
