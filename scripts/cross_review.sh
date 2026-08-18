#!/usr/bin/env bash
# cross_review.sh — auditor-dispatch driver for the frozen three-AI review protocol
# (doc/AI_COLLABORATION_PROTOCOL.md). This script only talks to the auditors;
# pre-registration, citation verification, and the reconciliation table are the
# caller's (Claude's) job — see .claude/commands/cross-review.md.
#
# Usage:
#   cross_review.sh [--jury]  [path]     parallel, blind Codex + Grok audits (default)
#   cross_review.sh --relay   [path]     sequential; each auditor sees the thread so far
#   cross_review.sh --quick   <commit>   one auditor (commit-hash parity), for the post-commit hook
#
# Target: no path -> `git diff HEAD` (clean tree -> last commit); path -> that file.
# Jury/relay append to tmp/ai_exchange/$AI_EXCHANGE_SLUG.md via the existing
# ask_codex.sh / ask_grok.sh wrappers; --quick appends to tmp/ai_exchange/autoreview.md
# under a lock and raises tmp/ai_exchange/AUTOREVIEW_P0.flag on P0/CRITICAL findings.
# Env: AI_EXCHANGE_SLUG (exchange topic, default "scratch"), DIFF_CAP (default 400 lines).
#
# Portability note: macOS is the primary dev host and ships no flock(1) and only
# bash 3.2 at /bin/bash, so the serialization below uses an atomic mkdir lock and
# no bash-4-only expansions. Do not "simplify" either back to the GNU-only form.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Optional environment pin for bare invocations (git hooks get a minimal PATH).
# Create scripts/ai_env.sh locally if `codex` / `grok` are not on the hook's PATH.
[ -f "$ROOT/scripts/ai_env.sh" ] && . "$ROOT/scripts/ai_env.sh"
SCRIPTS="$ROOT/.claude/scripts"
EXDIR="$ROOT/tmp/ai_exchange"
DIFF_CAP="${DIFF_CAP:-400}"
mkdir -p "$EXDIR"

MODE="jury"
case "${1:-}" in
    --jury)  shift ;;
    --relay) MODE="relay"; shift ;;
    --quick) MODE="quick"; shift ;;
    --*)     echo "cross_review.sh: unknown flag $1" >&2; exit 1 ;;
esac
TARGET="${1:-}"
SLUG="${AI_EXCHANGE_SLUG:-scratch}"

timestamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }
upper() { printf '%s' "$1" | tr 'a-z' 'A-Z'; }

# Truncate stdin at DIFF_CAP lines with an explicit marker ($1 = label).
cap_lines() {
    awk -v cap="$DIFF_CAP" -v label="$1" \
        'NR <= cap { print } END { if ( NR > cap )
             printf "\n[%s truncated at %d of %d lines — read the listed files in the repository yourself for the rest]\n", label, cap, NR }'
}

SUBJECT_FILE=$(mktemp "${TMPDIR:-/tmp}/crossrev_subject_XXXXXX")
PROMPT_FILE=$(mktemp "${TMPDIR:-/tmp}/crossrev_prompt_XXXXXX")
trap 'rm -f "$SUBJECT_FILE" "$PROMPT_FILE"' EXIT

# --- Resolve the review subject --------------------------------------------
if [ "$MODE" = "quick" ]; then
    [ -n "$TARGET" ] || { echo "cross_review.sh: --quick needs a commit" >&2; exit 1; }
    # Never review mid-rebase; skip merge commits (noisy diffs).
    GITDIR="$(git -C "$ROOT" rev-parse --absolute-git-dir)"
    { [ -d "$GITDIR/rebase-merge" ] || [ -d "$GITDIR/rebase-apply" ]; } && exit 0
    SHA="$(git -C "$ROOT" rev-parse --verify "$TARGET^{commit}")"
    git -C "$ROOT" rev-parse -q --verify "$SHA^2" >/dev/null && exit 0
    DESC="commit ${SHA:0:12}"
    { git -C "$ROOT" show --no-color "$SHA" | cap_lines "diff of $DESC"
      printf '\nChanged files:\n'
      git -C "$ROOT" show --name-only --format= "$SHA"
    } > "$SUBJECT_FILE"
elif [ -n "$TARGET" ]; then
    FILE="$TARGET"
    [ -f "$FILE" ] || FILE="$ROOT/$TARGET"
    [ -f "$FILE" ] || { echo "cross_review.sh: no such file: $TARGET" >&2; exit 1; }
    DESC="file $TARGET"
    cap_lines "$DESC (full file at $TARGET)" < "$FILE" > "$SUBJECT_FILE"
else
    if git -C "$ROOT" diff --quiet HEAD -- ; then
        SHA="$(git -C "$ROOT" rev-parse HEAD)"
        DESC="last commit ${SHA:0:12} (working tree clean)"
        { git -C "$ROOT" show --no-color "$SHA" | cap_lines "diff of $DESC"
          printf '\nChanged files:\n'
          git -C "$ROOT" show --name-only --format= "$SHA"
        } > "$SUBJECT_FILE"
    else
        DESC="working-tree diff vs HEAD ($(git -C "$ROOT" branch --show-current))"
        { git -C "$ROOT" diff --no-color HEAD | cap_lines "$DESC"
          printf '\nChanged files:\n'
          git -C "$ROOT" diff --name-only HEAD
        } > "$SUBJECT_FILE"
    fi
fi

# --- Priming (split by mode — jury stays minimal, blind) --------------------
PRIME_JURY="You are an independent reviewer of a change to the SCLS build system. Cite file:line for every claim. State a confidence level (high / medium / low) per finding."
PRIME_RELAY="$PRIME_JURY Find what the prior reviewers whose findings appear in the exchange thread missed."
PRIME_QUICK="$PRIME_JURY Label every finding with a severity: P0 (must fix), P1 (should fix), or P2 (minor). Only write the token P0 when reporting an actual P0 finding; for a clean result write 'no must-fix findings' without using the severity tokens."

# What a reviewer of THIS repository should be looking for. Kept short — the
# wrappers already point each auditor at CLAUDE.md and the protocol's checklist.
SUBJECT_FOCUS="Review the content below for defects, risks, and violations of the conventions in CLAUDE.md and doc/AI_COLLABORATION_PROTOCOL.md §4. Weight these highest: install-hook macro errors (%{buildroot} vs %{prefix} in install.commands vs install.post), missing runtime dependencies (AutoReqProv is off, so nothing else catches them), files/<package>.txt drift and hard-coded version directories, flavor-gating mistakes, divergence between rpm_builder.py / deb_builder.py / unix_builder.py, shell quoting in emitted build commands, and license or ABI policy violations. Read-only — modify nothing and start no build."

build_prompt() {  # $1 = priming
    { printf '%s\n\n' "$1"
      printf 'Review subject: %s.\n' "$DESC"
      printf '%s\n\n' "$SUBJECT_FOCUS"
      printf -- '--- BEGIN REVIEW SUBJECT ---\n'
      cat "$SUBJECT_FILE"
      printf -- '--- END REVIEW SUBJECT ---\n'
    } > "$PROMPT_FILE"
}

run_auditor() {  # $1 = codex|grok, $2 = exchange slug
    AI_EXCHANGE_SLUG="$2" "$SCRIPTS/ask_$1.sh" - < "$PROMPT_FILE"
}

# cat the temp-slug exchange file into stdout, or an honest failure entry; then remove it.
collect() {  # $1 = temp slug file, $2 = voice name, $3 = exit code
    if [ -s "$1" ]; then cat "$1"
    else printf '\n---\n\n# %s %s\n## Audit FAILED\nWrapper exit %s — no usable audit produced (see %s/_cross_review.log).\n' \
                "$2" "$(timestamp)" "$3" "$EXDIR"
    fi
    rm -f "$1"
}

# Atomic mkdir lock — flock(1) does not exist on macOS. Stale locks older than
# 30 min are broken open so a killed auto-review cannot wedge every later commit.
LOCKDIR="$EXDIR/.autoreview.lock"
acquire_lock() {
    local tries=0
    while ! mkdir "$LOCKDIR" 2>/dev/null; do
        if [ -d "$LOCKDIR" ] && [ -z "$(find "$LOCKDIR" -maxdepth 0 -mmin -30 2>/dev/null)" ]; then
            echo "cross_review.sh: breaking stale lock $LOCKDIR" >&2
            rm -rf "$LOCKDIR"
            continue
        fi
        tries=$((tries + 1))
        [ "$tries" -gt 600 ] && { echo "cross_review.sh: lock timeout" >&2; return 1; }
        sleep 1
    done
    return 0
}
release_lock() { rm -rf "$LOCKDIR"; }

LOG="$EXDIR/_cross_review.log"
case "$MODE" in
jury)
    build_prompt "$PRIME_JURY"
    JC="$EXDIR/${SLUG}_jury_codex.md"; JG="$EXDIR/${SLUG}_jury_grok.md"
    rm -f "$JC" "$JG"
    run_auditor codex "${SLUG}_jury_codex" >/dev/null 2>>"$LOG" & CPID=$!
    run_auditor grok  "${SLUG}_jury_grok"  >/dev/null 2>>"$LOG" & GPID=$!
    CRC=0; GRC=0
    wait "$CPID" || CRC=$?
    wait "$GPID" || GRC=$?
    # Blind round done — merge both voices into the main thread in fixed order.
    { collect "$JC" CODEX "$CRC"; collect "$JG" GROK "$GRC"; } | tee -a "$EXDIR/$SLUG.md"
    ;;
relay)
    build_prompt "$PRIME_RELAY"
    run_auditor codex "$SLUG" 2>>"$LOG" || echo "cross_review.sh: codex relay leg failed (continuing)" >&2
    run_auditor grok  "$SLUG" 2>>"$LOG" || echo "cross_review.sh: grok relay leg failed" >&2
    ;;
quick)
    build_prompt "$PRIME_QUICK"
    case "${SHA: -1}" in
        [02468ace]) AUDITOR=codex ;;
        *)          AUDITOR=grok  ;;
    esac
    QSLUG="autoreview_${SHA:0:12}"
    QT="$EXDIR/$QSLUG.md"
    rm -f "$QT"
    QRC=0
    run_auditor "$AUDITOR" "$QSLUG" >/dev/null 2>>"$LOG" || QRC=$?
    TS="$(timestamp)"
    P0LINE=""
    if [ -s "$QT" ]; then
        # negation filter: "No P0/P1 defect ..." must not raise the flag
        P0LINE="$(grep -E '\bP0\b|\bCRITICAL\b' "$QT" | grep -m1 -viE 'no (p0|p0/p1|critical)|without p0|zero p0' || true)"
        P0LINE="${P0LINE:0:160}"
    fi
    acquire_lock || exit 1
    trap 'release_lock; rm -f "$SUBJECT_FILE" "$PROMPT_FILE"' EXIT
    { printf '\n## commit %s %s auditor=%s\n' "$SHA" "$TS" "$AUDITOR"
      collect "$QT" "$(upper "$AUDITOR")" "$QRC"
    } >> "$EXDIR/autoreview.md"
    if [ -n "$P0LINE" ]; then
        printf '%s %s %s: %s\n' "${SHA:0:12}" "$TS" "$AUDITOR" "$P0LINE" \
            >> "$EXDIR/AUTOREVIEW_P0.flag"
    fi
    release_lock
    ;;
esac
echo "cross_review.sh: done ($MODE, $DESC)" >&2
