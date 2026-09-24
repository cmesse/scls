#!/usr/bin/env bash
# grant_pkg_sudo.sh — give the SCLS build user passwordless sudo for the host package
# manager, so a build campaign does not stall on a password prompt nobody can see.
#
# What actually needs the grant (checked against the code, not assumed):
#   * `./scls install P` — the builders shell out to `sudo dnf install -y` /
#     `sudo apt-get install -y` to install the RPMs/DEBs they just built
#     (python/rpm_builder.py:_dnf_install_rpms, python/deb_builder.py:_apt_install_deb*).
#   * Class D repairs during a campaign — installing a missing host package by hand
#     (doc/BUILD_EXECUTION.md §"Class D"). `rpm_build_requires:` is NOT auto-installed
#     by anything in python/; it becomes spec BuildRequires / deb Build-Depends.
#
# Usage, on the Linux build host:
#   scripts/grant_pkg_sudo.sh                     # dry run: print the rule, change nothing
#   scripts/grant_pkg_sudo.sh --apply             # install it (escalates with sudo once)
#   scripts/grant_pkg_sudo.sh --check             # is the grant in place and effective?
#   scripts/grant_pkg_sudo.sh --remove            # take it away again
#   scripts/grant_pkg_sudo.sh --user mockbuild --apply
#   scripts/grant_pkg_sudo.sh --scope all --apply  # see below; you must ask for this one
#
# Two scopes:
#   --scope pkg  (default) only /usr/bin/{dnf,apt-get,dpkg,rpm}.
#   --scope all  blanket NOPASSWD plus `Defaults:<user> verifypw=never`. Never the
#                default: it has to be typed. It is the honest choice for a dedicated
#                compilation VM, because `--scope pkg` does not actually lower the ceiling
#                — dnf and rpm run package scriptlets as root — while it does fail the two
#                places the build workflow tests sudo generically: `sudo -n true`
#                (doc/BUILD_EXECUTION.md §1.3, /update-build preflight) and `sudo -v` with
#                its keepalive (`scls build all`). `--check` prints both so the trade is
#                visible either way. On anything that is not a disposable build VM, stay
#                with pkg and fix the two call sites instead.
#
# Writes exactly one file: /etc/sudoers.d/scls-build, 0440 root:root.
#
# A syntax error anywhere under /etc/sudoers.d breaks sudo for every user on the host,
# including the sudo needed to delete the broken file. So --apply:
#   0. refuses to touch anything if `visudo -c` already fails (the host is broken first);
#   1. writes the fragment to /etc/sudoers.d/.scls-build.staging — a name the includedir
#      ignores, because names containing '.' are skipped — already root:root and 0440;
#   2. runs `visudo -cf` on those exact bytes, before they are ever live;
#   3. renames it into place (atomic, same directory), keeping a copy of any previous
#      fragment in .scls-build.bak;
#   4. runs the whole-ruleset `visudo -c`, and on failure puts the previous content back.
# If sudoers is still invalid after that rollback, this script does NOT exit — it is the
# only root process you have left, so it opens a root shell on the terminal instead.
#
# NOTE: NOPASSWD on a package manager is equivalent to root on this host — package
# scriptlets run as root. This is a build-VM grant, not a workstation one.

set -euo pipefail

DROPIN=/etc/sudoers.d/scls-build
STAGE=/etc/sudoers.d/.scls-build.staging   # '.' on purpose: includedir skips it
BACKUP=/etc/sudoers.d/.scls-build.bak      # same
MARKER='# managed by scls scripts/grant_pkg_sudo.sh'

# Christian's four commands, as static paths. Deliberately NOT probed for existence:
# visudo does not require the binary to exist, sudo never matches a missing path, and
# probing is how a Debian host that happens to carry /usr/bin/rpm would get a grant for
# it that nobody asked for.
CMDS="/usr/bin/dnf, /usr/bin/apt-get, /usr/bin/dpkg, /usr/bin/rpm"

MODE=""
FORCE=0
USER_NAME=""
SCOPE=pkg
SCOPE_EXPLICIT=0   # so a bare --apply cannot silently change the scope of an existing grant

die() { echo "grant_pkg_sudo.sh: $*" >&2; exit 1; }

set_mode() {
    [ -z "$MODE" ] || die "--apply, --check and --remove are mutually exclusive"
    MODE="$1"
}

# $1 = flag as typed, $2 = candidate value, $3 = remaining arg count (0 for --flag=value)
need_operand() {
    [ "$3" -eq 0 ] || [ "$3" -ge 2 ] || die "$1 needs a value"
    case "$2" in
        '') die "$1 needs a value" ;;
        -*) die "$1 needs a value, got '$2'" ;;
    esac
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user)    need_operand --user "${2:-}" $#; USER_NAME="$2"; shift 2 ;;
        --scope)   need_operand --scope "${2:-}" $#; SCOPE="$2"; SCOPE_EXPLICIT=1; shift 2 ;;
        --scope=*) need_operand --scope= "${1#--scope=}" 0; SCOPE="${1#--scope=}"
                   SCOPE_EXPLICIT=1; shift ;;
        --user=*)  need_operand --user= "${1#--user=}" 0; USER_NAME="${1#--user=}"; shift ;;
        --apply)   set_mode apply;  shift ;;
        --check)   set_mode check;  shift ;;
        --remove)  set_mode remove; shift ;;
        --force)   FORCE=1; shift ;;
        -h|--help) sed -n '2,50p' "$0"; exit 0 ;;
        *)         die "unknown argument: $1 (see --help)" ;;
    esac
done
MODE="${MODE:-dryrun}"

case "$SCOPE" in
    pkg|all) ;;
    *) die "--scope takes 'pkg' or 'all', not '$SCOPE'" ;;
esac

[ "$(uname -s)" = "Linux" ] || \
    die "Linux build hosts only (this host is $(uname -s)); macOS builds never sudo-install"

# --- target user -------------------------------------------------------------
# Resolved BEFORE any escalation, so re-exec under sudo cannot change who the rule is
# written for. $SUDO_USER is honoured only when we are already root — i.e. it was set by
# a real sudo invocation — so an exported SUDO_USER on an unprivileged command line
# cannot slip a different subject into the fragment the operator is about to authorise.
if [ -z "$USER_NAME" ]; then
    if [ "$(id -u)" -eq 0 ]; then
        USER_NAME="${SUDO_USER:-root}"
    else
        USER_NAME="$(id -un)"
    fi
fi
printf '%s' "$USER_NAME" | LC_ALL=C grep -Eq '^[A-Za-z_][A-Za-z0-9_-]*$' || \
    die "refusing to interpolate '$USER_NAME' into sudoers; expected a plain user name"
case "$USER_NAME" in
    root) die "refusing to write a sudoers rule for root" ;;
    ALL)  die "refusing to write a rule for a user literally named ALL (it is a sudoers keyword)" ;;
esac
id -- "$USER_NAME" >/dev/null 2>&1 || die "no such user: $USER_NAME"

# Deterministic by construction: --apply compares this against the installed file with
# cmp and reports `unchanged`, so a re-run must produce byte-identical content. Nothing
# host- or time-dependent belongs in here.
if [ "$SCOPE" = "all" ]; then
    CONTENT="$MARKER
# Scope: all — asked for explicitly with --scope all. $USER_NAME gets root-equivalent sudo
# on this host, which is the honest description of a compilation VM's build account.
# Narrowing the rule to the package manager would not lower that ceiling (dnf and rpm run
# package scriptlets as root) and would fail the two places the build workflow tests sudo
# generically: \`sudo -n true\` (doc/BUILD_EXECUTION.md §1.3, /update-build preflight) and
# \`sudo -v\` plus its keepalive (\`scls build all\`).
# The verifypw line is what covers \`sudo -v\`; the NOPASSWD rule alone does not. sudoers(5):
# \"a user may only run 'sudo -v' without a password if all of the user's entries for the
# current host have the NOPASSWD tag. This behavior may be overridden via the verifypw and
# listpw options.\" A %wheel rule that also matches this user carries the implicit PASSWD
# tag, so the default verifypw=all keeps prompting. verifypw is the documented override for
# -v; \`!authenticate\` is NOT — that one governs running commands and is itself overridden
# by the PASSWD/NOPASSWD tags.
# Regenerate or remove with:
#   scripts/grant_pkg_sudo.sh --user $USER_NAME --scope all --apply|--remove
$USER_NAME ALL=(ALL) NOPASSWD: ALL
Defaults:$USER_NAME verifypw=never"
else
    CONTENT="$MARKER
# Scope: pkg. Lets $USER_NAME install SCLS-built RPMs/DEBs (./scls install, which shells out
# to sudo dnf/apt-get install -y) and repair missing host packages during a build campaign,
# without an interactive password prompt.
# This does NOT satisfy \`sudo -n true\` (/update-build preflight) or \`sudo -v\` (the
# \`scls build all\` keepalive) — neither is one of the commands below. --check shows it.
# Regenerate or remove with:
#   scripts/grant_pkg_sudo.sh --user $USER_NAME --scope pkg --apply|--remove
$USER_NAME ALL=(root) NOPASSWD: $CMDS"
fi

# --- reporting ---------------------------------------------------------------
# Never prompts: every probe here is `sudo -n`. Two different things are reported and
# they are labelled, because a passing policy query is not proof that a build's
# `sudo dnf install` will run.
# Which scope the installed fragment was written with, read back from the `# Scope:` line
# both fragments carry. Empty when there is no file, or when it is not one of ours.
# Needs root; callers guard on that.
installed_scope() {
    [ -f "$DROPIN" ] || return 0
    # The marker check is the point: without it, an unmanaged fragment that happens to
    # contain a `# Scope:` line would be reported as ours and could trip the scope guard.
    grep -qF "$MARKER" "$DROPIN" || return 0
    sed -n 's/^# Scope: \([a-z][a-z]*\).*/\1/p' "$DROPIN" | head -1
}

report() {
    local c rc_policy rc_exec pm am_root=0
    [ "$(id -u)" -eq 0 ] && am_root=1

    if [ "$am_root" -eq 1 ]; then
        if [ -f "$DROPIN" ]; then
            echo "file:   $DROPIN (present, scope=$(installed_scope))"
            sed 's/^/  | /' "$DROPIN"
        else
            echo "file:   $DROPIN (absent)"
        fi
    else
        echo "file:   $DROPIN (not readable as $(id -un); re-run under sudo to see it)"
    fi

    for c in /usr/bin/dnf /usr/bin/apt-get /usr/bin/dpkg /usr/bin/rpm; do
        [ -x "$c" ] || continue
        rc_policy=no
        if [ "$am_root" -eq 1 ]; then
            sudo -n -U "$USER_NAME" -l "$c" >/dev/null 2>&1 && rc_policy=yes
        elif [ "$(id -un)" = "$USER_NAME" ]; then
            sudo -n -l "$c" >/dev/null 2>&1 && rc_policy=yes
        else
            rc_policy="unknown (running as $(id -un), not $USER_NAME)"
        fi
        echo "policy: $c -> $rc_policy"
    done

    # Execution probe on the command the builders actually call, in the exact unqualified
    # shape they call it (`sudo dnf`, resolved through secure_path).
    pm=""
    [ -x /usr/bin/dnf ] && pm=dnf
    [ -z "$pm" ] && [ -x /usr/bin/apt-get ] && pm=apt-get
    if [ -n "$pm" ]; then
        rc_exec=no
        if [ "$am_root" -eq 1 ]; then
            sudo -n -u "$USER_NAME" sudo -n "$pm" --version >/dev/null 2>&1 && rc_exec=yes
        elif [ "$(id -un)" = "$USER_NAME" ]; then
            sudo -n "$pm" --version >/dev/null 2>&1 && rc_exec=yes
        else
            rc_exec="unknown (running as $(id -un), not $USER_NAME)"
        fi
        echo "exec:   sudo -n $pm --version as $USER_NAME -> $rc_exec"
    fi

    # The two generic tests the repo's own workflows run. A --scope pkg grant fails both by
    # construction; that is not a defect in the grant, it is what scoping means.
    local rc_true=no rc_v=no
    if [ "$am_root" -eq 1 ]; then
        sudo -n -u "$USER_NAME" sudo -n true >/dev/null 2>&1 && rc_true=yes
        sudo -n -u "$USER_NAME" sudo -n -v   >/dev/null 2>&1 && rc_v=yes
    elif [ "$(id -un)" = "$USER_NAME" ]; then
        sudo -n true >/dev/null 2>&1 && rc_true=yes
        sudo -n -v   >/dev/null 2>&1 && rc_v=yes
    else
        rc_true="unknown (running as $(id -un), not $USER_NAME)"; rc_v="$rc_true"
    fi
    echo "flow:   sudo -n true as $USER_NAME -> $rc_true  (/update-build preflight)"
    echo "flow:   sudo -n -v   as $USER_NAME -> $rc_v  (scls build all keepalive)"
    # Both flow probes can read yes off a live sudo timestamp rather than off this grant:
    # timestamp_type defaults to tty and timestamp_timeout to 5 minutes, and a rule such as
    # %wheel authorises `true` once the ticket is warm. Immediately after --apply the ticket
    # IS warm, by construction — the escalation just authenticated on this terminal. Say so
    # rather than letting a pkg grant look like an all grant for five minutes.
    echo "        (a 'yes' here can come from a live sudo timestamp on this terminal, not"
    echo "         from the grant. For a cold answer: run 'sudo -k' and re-run --check from"
    echo "         a fresh login, on a terminal that has not just used sudo.)"
}

case "$MODE" in
check)
    report
    echo
    echo "note: 'policy' is what sudoers permits, 'exec' runs the builders' own invocation,"
    echo "      'flow' runs the two generic tests /update-build and 'scls build all' use."
    echo "      Under --scope pkg the two 'flow' lines are expected to say no."
    exit 0
    ;;
dryrun)
    echo "would write $DROPIN (0440 root:root), scope=$SCOPE:"
    printf '%s\n' "$CONTENT" | sed 's/^/  | /'
    echo
    echo "sequence --apply performs, as root:"
    echo "  0. visudo -c                    # refuse outright if the host is already broken"
    echo "  1. write the text above to $STAGE (0440 root:root; ignored by includedir)"
    echo "  2. visudo -cf $STAGE            # validate the exact bytes, before they go live"
    echo "  3. cp -p $DROPIN $BACKUP        # only if a drop-in is already there"
    echo "  4. mv -f $STAGE $DROPIN         # atomic rename within the same directory"
    echo "  5. visudo -c                    # whole-ruleset check"
    echo "  6. on failure at 5: restore $BACKUP (or remove $DROPIN), re-run visudo -c,"
    echo "     and if it STILL fails, open a root shell rather than exit"
    echo
    echo "run it with:  scripts/grant_pkg_sudo.sh --user $USER_NAME --scope $SCOPE --apply"
    echo
    report
    exit 0
    ;;
esac

# --- privileged modes --------------------------------------------------------
# One escalation, here, so everything below is a plain root operation. `sudo test` and
# `sudo cat` would each need their own prompt and are not covered by the grant anyway.
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "need root and there is no sudo; re-run as root"
    SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    ARGV=(--user "$USER_NAME" "--$MODE")
    # Only forwarded when the caller actually typed it: passing it unconditionally would
    # make the root child treat the default as an explicit choice and skip the
    # scope-change guard below.
    [ "$SCOPE_EXPLICIT" -eq 1 ] && ARGV+=(--scope "$SCOPE")
    [ "$FORCE" -eq 1 ] && ARGV+=(--force)
    echo "grant_pkg_sudo.sh: escalating with sudo — you may be asked for your password" >&2
    exec sudo -- bash "$SELF" "${ARGV[@]}"
fi

cleanup() { rm -f "$STAGE"; }
trap cleanup EXIT

# Reached only when sudoers does not validate and we are already root. Exiting here is
# exactly how a host loses sudo altogether, so this function does not exit while it can
# still hand over a working root shell.
panic_broken_sudoers() {
    echo >&2
    echo "=== grant_pkg_sudo.sh: /etc/sudoers.d DOES NOT VALIDATE ======================" >&2
    echo "sudo may now refuse to run for every user on this host." >&2
    if [ -f "$DROPIN" ]; then echo "  $DROPIN exists" >&2; else echo "  $DROPIN is removed" >&2; fi
    if [ -f "$BACKUP" ]; then echo "  previous fragment kept at $BACKUP" >&2; fi
    echo "Repair it from the root shell below — do not close this terminal:" >&2
    echo "  visudo -c                     # what is wrong, and where" >&2
    echo "  rm -f $DROPIN                 # or: mv -f $BACKUP $DROPIN" >&2
    echo "==============================================================================" >&2
    if [ -t 0 ] && [ -t 2 ]; then
        echo "Opening a root shell. Exit it once 'visudo -c' passes." >&2
        exec bash -i
    fi
    echo "stdin is not a terminal, so no rescue shell can be opened from here." >&2
    echo "Get a root console NOW (console login or root password) and repair it." >&2
    exit 1
}

PRE_OK=1
if ! visudo -c >/dev/null 2>&1; then PRE_OK=0; fi

if [ "$MODE" = remove ]; then
    if [ ! -f "$DROPIN" ]; then
        echo "absent: $DROPIN — nothing to remove"
        exit 0
    fi
    if ! grep -qF "$MARKER" "$DROPIN" && [ "$FORCE" -ne 1 ]; then
        echo "grant_pkg_sudo.sh: $DROPIN was not written by this script:" >&2
        sed 's/^/  | /' "$DROPIN" >&2
        die "re-run with --force to remove it anyway"
    fi
    if [ "$PRE_OK" -eq 0 ]; then
        echo "grant_pkg_sudo.sh: note — sudoers already failed visudo -c BEFORE this removal." >&2
    fi
    cp -p "$DROPIN" "$BACKUP"
    rm -f "$DROPIN"
    if ! visudo -c >/dev/null 2>&1; then
        if [ "$PRE_OK" -eq 1 ]; then
            # Removing a valid fragment cannot break the rest of the policy; if it did,
            # put it back rather than leave the host in a state we caused.
            if mv -f "$BACKUP" "$DROPIN"; then
                echo "grant_pkg_sudo.sh: restored $DROPIN" >&2
            else
                echo "grant_pkg_sudo.sh: FAILED to restore $BACKUP over $DROPIN" >&2
            fi
            if ! visudo -c >/dev/null 2>&1; then panic_broken_sudoers; fi
            die "sudoers stopped validating when $DROPIN was removed; it has been restored"
        fi
        panic_broken_sudoers
    fi
    rm -f "$BACKUP"
    echo "removed $DROPIN"
    exit 0
fi

# --- apply -------------------------------------------------------------------
# Fail closed: if the policy is already invalid, a live `mv` here would be blamed for it
# and the rollback would restore a broken state. Nothing is touched.
if [ "$PRE_OK" -eq 0 ]; then
    echo "grant_pkg_sudo.sh: the host's sudoers policy ALREADY fails visudo -c." >&2
    echo "  Nothing was changed. Run 'sudo visudo -c', fix that first, then re-run." >&2
    exit 1
fi

if ! grep -Eq '^[#@]includedir[[:space:]]+/etc/sudoers.d' /etc/sudoers 2>/dev/null; then
    echo "grant_pkg_sudo.sh: WARNING — /etc/sudoers has no includedir for /etc/sudoers.d." >&2
    echo "  A drop-in there will be written correctly and ignored completely." >&2
fi

umask 077
printf '%s\n' "$CONTENT" > "$STAGE"
chown root:root "$STAGE"
chmod 0440 "$STAGE"
if command -v restorecon >/dev/null 2>&1; then restorecon "$STAGE" 2>/dev/null || true; fi

# Validate the exact bytes that will be renamed into place, while they are already
# root-owned and 0440 inside /etc/sudoers.d. No user-owned temp in the trust path.
if ! visudo -cf "$STAGE"; then
    die "generated fragment failed visudo; $DROPIN untouched"
fi

HAD_OLD=0
if [ -f "$DROPIN" ]; then
    rc=0
    cmp -s "$DROPIN" "$STAGE" || rc=$?
    case "$rc" in
        0)  echo "unchanged: $DROPIN already holds exactly this rule"
            report
            exit 0 ;;
        1)  ;;   # differs — replace it
        *)  die "could not compare $DROPIN with $STAGE (cmp exit $rc); nothing changed" ;;
    esac
    # Both fragments carry the marker, so the managed-file check below would not notice a
    # scope change. A bare --apply must not silently downgrade an `all` grant to `pkg`.
    OLD_SCOPE="$(installed_scope)"
    if [ -n "$OLD_SCOPE" ] && [ "$OLD_SCOPE" != "$SCOPE" ] \
       && [ "$SCOPE_EXPLICIT" -ne 1 ] && [ "$FORCE" -ne 1 ]; then
        echo "grant_pkg_sudo.sh: $DROPIN is a scope=$OLD_SCOPE grant and this run would make" >&2
        echo "  it scope=$SCOPE, which you did not ask for. Pass --scope $SCOPE to mean it," >&2
        echo "  or --scope $OLD_SCOPE to leave it as it is." >&2
        exit 1
    fi
    if ! grep -qF "$MARKER" "$DROPIN"; then
        if [ "$FORCE" -ne 1 ]; then
            echo "grant_pkg_sudo.sh: $DROPIN exists and was not written by this script:" >&2
            sed 's/^/  | /' "$DROPIN" >&2
            die "inspect it, then re-run with --force to replace it"
        fi
        echo "grant_pkg_sudo.sh: --force replacing an unmanaged $DROPIN; previous content:" >&2
        sed 's/^/  | /' "$DROPIN" >&2
        echo "grant_pkg_sudo.sh: a copy is kept at $BACKUP until the new rule validates." >&2
    fi
    cp -p "$DROPIN" "$BACKUP"
    HAD_OLD=1
fi

mv -f "$STAGE" "$DROPIN"

if ! visudo -c >/dev/null 2>&1; then
    if [ "$HAD_OLD" -eq 1 ]; then
        if mv -f "$BACKUP" "$DROPIN"; then
            echo "grant_pkg_sudo.sh: restored the previous $DROPIN" >&2
        else
            echo "grant_pkg_sudo.sh: FAILED to restore $BACKUP over $DROPIN" >&2
        fi
    else
        rm -f "$DROPIN" || echo "grant_pkg_sudo.sh: FAILED to remove $DROPIN" >&2
    fi
    if ! visudo -c >/dev/null 2>&1; then panic_broken_sudoers; fi
    die "whole-ruleset visudo -c failed with the new $DROPIN; rolled back"
fi

if [ "$HAD_OLD" -eq 1 ]; then rm -f "$BACKUP"; fi

echo "installed $DROPIN"
report
echo
echo "Claude still gets a per-call permission prompt for 'sudo dnf …' unless"
echo ".claude/settings.json allows it — that is a separate, opt-in step."
