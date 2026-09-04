#!/usr/bin/env bash
# ask_grok.sh — request an independent audit / refutation from Grok and record it in the AI-only exchange (./tmp/ai_exchange/<slug>.md).
#
# Purpose:
#   Symmetric counterpart to ask_codex.sh. Allows the primary AI (Claude) to spawn
#   a fresh Grok instance (different training data / company) as a precision auditor
#   and refutation partner for the SCLS build system. Enforces the collaboration protocol:
#     - Distinct attributed voice (# GROK header)
#     - Role preamble forces reading CLAUDE.md + doc/AI_COLLABORATION_PROTOCOL.md
#     - Emphasis on refutation, independent verification, calibrated claims
#     - File:line evidence required for every claim
#     - Read-only / constrained execution (sandbox + tool allowlist)
#     - Output appended to the shared exchange channel for the record
#     - Result echoed to stdout so the caller sees it inline
#
# Usage (exactly parallel to ask_codex.sh):
#   .claude/scripts/ask_grok.sh "Audit recipes/petsc.yaml:88-140 for the mkl link line..."
#   .claude/scripts/ask_grok.sh -      (reads prompt from stdin)
#   echo "prompt text" | .claude/scripts/ask_grok.sh
#   AI_EXCHANGE_SLUG=petsc_mkl_link .claude/scripts/ask_grok.sh "..."
#
# Configuration (env overrides):
#   GROK_BIN              Path to the Grok CLI (default: `grok` on $PATH, else $HOME/.grok/bin/grok)
#   GROK_SANDBOX          Sandbox profile (default: read-only)
#   GROK_TOOLS            Comma-separated tool allowlist (default: read_file,grep,list_dir)
#                         Shell/write tools MUST stay off this list — see "Headless footgun" below.
#   GROK_MAX_TURNS        Agent turn budget (default: 30; raise for large multi-file audits)
#   GROK_MODEL            grok-4.6|grok-4.5 (default: grok-4.6)
#   GROK_EFFORT           low|medium|high|xhigh (default: xhigh)
#                         The old list here also advertised none|minimal|max, which grok-4.6 does
#                         not offer; max and ultra are excluded on purpose (ultra delegates to
#                         subagents, against the --no-subagents this wrapper passes).
#                         The xhigh default was chosen to reproduce what ~/.grok/config.toml gave
#                         on 2026-08-30, so turning the knob on changed the record, not the depth.
#                         That is an observation, not a guarantee — if the vendor config drifts,
#                         this default stays put and the two diverge.
#                         Historical note: GROK_EFFORT once failed with HTTP 400. That came from
#                         the retired grok-build backend and expired with it.
#   GROK_RETRIES          Fresh-session attempts (default: 5; failures can cluster in time)
#   GROK_MIN_CHARS        Minimum accepted body length after quality gate (default: 200)
#   GROK_REQUIRE_HEADING  Require a '##' markdown section (default: 1). Set 0 only for diagnostics.
#   GROK_RESUME_SALVAGE   If 1 (default), on narration-only/Cancelled try one --resume finish pass
#                         reusing the session that already read files.
#   GROK_PERMISSION_MODE  Optional --permission-mode override. Only `default` and
#                         `bypassPermissions` are meaningful via the CLI flag on grok ≥0.2.x;
#                         omit (default) and rely on sandbox + tool allowlist for read-only.
# Project root is auto-detected from the script location (<root>/.claude/scripts/).
#
# Headless footgun (grok CLI 0.2.111 — root cause of "narration-only" audits):
#   In headless mode, a tool that would prompt for permission is cancelled. Critically,
#   when run_terminal_command is in a tool batch and gets cancelled, the ENTIRE turn ends
#   with stopReason=Cancelled (exit code still 0). Stdout / JSON .text then contains only
#   the lead-in narration ("I'll audit…") and never the final ## sections.
#   Math audits that "want a quick python check" hit this almost deterministically — failures
#   cluster by prompt type, not as independent coin-flips. Retries alone do not fix it.
#   Mitigation: --tools allowlist without shell + quality gate that rejects Cancelled /
#   narration-only bodies + optional --resume salvage to finish from files already read.
#
# Invocation notes:
#   - --prompt-file + --output-format json (extract .text / stopReason / sessionId)
#   - --sandbox read-only + --tools allowlist (NOT --permission-mode plan — that is a no-op policy)
#   - --verbatim, --no-memory, --no-subagents
#
# After successful run it appends:
#     ---
#     # GROK 2026-06-12 12:34:56 PDT  (model=grok-4.6, effort=xhigh)
#     <Grok's full response body>
# An unchosen knob is stamped [defaulted] so the record distinguishes a selected depth from
# an inherited one.
#
# Then prints the body to stdout.
#
# This wrapper itself only ever writes to ./tmp/ai_exchange/<slug>.md (the AI-only exchange tier).

set -euo pipefail

# --- Configuration (override via environment if needed) ---
# Grok CLI resolution — must stay portable across machines and user names
# (Linux $HOME=/home/<user>, macOS $HOME=/Users/<user>):
#   1. explicit $GROK_BIN
#   2. `grok` on $PATH
#   3. the default installer location $HOME/.grok/bin/grok
if [ -z "${GROK_BIN:-}" ]; then
    if command -v grok >/dev/null 2>&1; then
        GROK_BIN="$(command -v grok)"
    else
        GROK_BIN="$HOME/.grok/bin/grok"
    fi
fi
if [ ! -x "$GROK_BIN" ]; then
    echo "ask_grok.sh: Grok CLI not found or not executable: $GROK_BIN" >&2
    echo "Install the Grok CLI, put it on \$PATH, or set GROK_BIN=/path/to/grok." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ask_grok.sh: python3 is required to parse grok --output-format json" >&2
    exit 1
fi

# Script lives in <root>/.claude/scripts/ — project root is two levels up.
SCLS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Resolve the per-task AI-only exchange file: ./tmp/ai_exchange/<slug>.md
# slug precedence: explicit $AI_EXCHANGE_SLUG > session tag from $CLAUDE_CODE_SESSION_ID > "scratch".
sanitize_slug() {
    printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_' '_' | sed 's/_\{2,\}/_/g; s/^_//; s/_$//'
}
if [ -n "${AI_EXCHANGE_SLUG:-}" ]; then
    SLUG="$(sanitize_slug "$AI_EXCHANGE_SLUG")"
elif [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
    SLUG="sess_$(sanitize_slug "${CLAUDE_CODE_SESSION_ID:0:8}")"
else
    SLUG="scratch"
fi
[ -n "$SLUG" ] || SLUG="scratch"
EXCHANGE_DIR="$SCLS_ROOT/tmp/ai_exchange"
EXCHANGE="$EXCHANGE_DIR/$SLUG.md"
mkdir -p "$EXCHANGE_DIR"
[ -f "$EXCHANGE" ] || : > "$EXCHANGE"

GROK_SANDBOX="${GROK_SANDBOX:-read-only}"
# Read-only audit tool surface. Shell/write tools must stay OFF this list.
# Expand via GROK_TOOLS only if an audit legitimately needs more (e.g. web_search).
GROK_TOOLS="${GROK_TOOLS:-read_file,grep,list_dir}"
GROK_MAX_TURNS="${GROK_MAX_TURNS:-30}"

# --- Depth selection: model + reasoning effort -------------------------------
# Validated before any prompt is read, so a typo costs no billed call.
GROK_MODEL_CHOSEN=1
GROK_EFFORT_CHOSEN=1
if [ -z "${GROK_MODEL:-}" ];  then GROK_MODEL="grok-4.6"; GROK_MODEL_CHOSEN=0;  fi
if [ -z "${GROK_EFFORT:-}" ]; then GROK_EFFORT="xhigh";   GROK_EFFORT_CHOSEN=0; fi

case "$GROK_MODEL" in
    grok-4.6|grok-4.5) ;;
    *)
        echo "ask_grok.sh: unknown GROK_MODEL '$GROK_MODEL'. Allowed: grok-4.6 grok-4.5" >&2
        exit 1
        ;;
esac
case "$GROK_EFFORT" in
    low|medium|high|xhigh) ;;
    *)
        echo "ask_grok.sh: unknown GROK_EFFORT '$GROK_EFFORT'" >&2
        echo "Allowed: low medium high xhigh (none, minimal, max and ultra are excluded)" >&2
        exit 1
        ;;
esac

# Per-knob provenance, so the stamp says WHICH knob was left unchosen.
GROK_MODEL_TAG="$GROK_MODEL"
GROK_EFFORT_TAG="$GROK_EFFORT"
if [ "$GROK_MODEL_CHOSEN" -eq 0 ];  then GROK_MODEL_TAG="$GROK_MODEL [defaulted]";   fi
if [ "$GROK_EFFORT_CHOSEN" -eq 0 ]; then GROK_EFFORT_TAG="$GROK_EFFORT [defaulted]"; fi
if [ "$GROK_MODEL_CHOSEN" -eq 0 ] || [ "$GROK_EFFORT_CHOSEN" -eq 0 ]; then
    echo "ask_grok.sh: depth not selected by the caller — using model=$GROK_MODEL effort=$GROK_EFFORT" >&2
    echo "Pick a row from the depth-selection table in doc/AI_COLLABORATION_PROTOCOL.md and set GROK_MODEL / GROK_EFFORT." >&2
fi
# Failures can cluster (same prompt keeps asking for shell → Cancelled). Default 5
# with backoff; tools allowlist is the real fix for the shell-cancel streak.
GROK_RETRIES="${GROK_RETRIES:-5}"
GROK_MIN_CHARS="${GROK_MIN_CHARS:-200}"
GROK_REQUIRE_HEADING="${GROK_REQUIRE_HEADING:-1}"
GROK_RESUME_SALVAGE="${GROK_RESUME_SALVAGE:-1}"
GROK_PERMISSION_MODE="${GROK_PERMISSION_MODE:-}"

# Collect prompt from argument or stdin (same contract as ask_codex.sh)
if [ $# -eq 0 ] || [ "$1" = "-" ]; then
    AUDIT_PROMPT=$(cat)
else
    AUDIT_PROMPT="$*"
fi

if [ -z "$AUDIT_PROMPT" ]; then
    echo "Usage: ask_grok.sh \"<focused audit / refutation prompt>\"  OR  ask_grok.sh - (reads stdin)" >&2
    echo "Example: ask_grok.sh \"Audit recipes/vtk.yaml and files/vtk.txt against each other after the 9.5 bump: does every installed path appear in the manifest, and are version-stamped cmake dirs written as %{version}? Challenge every operational detail with file:line evidence.\"" >&2
    exit 1
fi

# Guard: if the caller expanded GROK_TOOLS to include shell, refuse — that recreates the footgun.
case ",$GROK_TOOLS," in
    *,run_terminal_command,*|*,run_terminal_cmd,*|*,Bash,*|*,bash,*)
        echo "ask_grok.sh: GROK_TOOLS includes a shell tool ($GROK_TOOLS)." >&2
        echo "Headless grok cancels the whole turn when shell needs permission (stopReason=Cancelled)," >&2
        echo "leaving only a lead-in narration. Remove shell from GROK_TOOLS." >&2
        exit 1
        ;;
esac

# --- Role preamble ---
FULL_PROMPT="You are Grok (xAI) acting as the independent precision-audit and refutation partner for SCLS (the secondary AI role, symmetric to Codex).

SCLS (Scientific Core Library Stack) is a Python + YAML build system that compiles and packages scientific software into RPMs, DEBs, and macOS packages across several optimization flavors (gcc, mkl, debug, intel, lbl, macos). It is a packaging and build-orchestration codebase, not an application: the defects that matter are wrong generated build commands, wrong spec macros, incomplete dependency and file lists, and license/ABI policy violations.

BEFORE YOU ANSWER ANYTHING, read these two files from the project root:
  - CLAUDE.md                            (architecture, build commands, repo conventions)
  - doc/AI_COLLABORATION_PROTOCOL.md     (the AI roles, the audit checklist, the evidence ladder, the required format)

Also read the policy doc relevant to the task when it applies: doc/LICENSE_POLICY.md (what may be redistributed), doc/MKL_ABI_POLICY.md (MKL SONAME handling), doc/MACOS_BUILD.md.

This task's AI-only exchange thread is at:
  $EXCHANGE
Read it first (it may be empty or hold prior entries) so you have the conversation context before auditing.

YOUR MANDATE (different from the primary AI):
- Your job is **refutation and blind-spot detection**, not agreeable synthesis or high-level summary.
- Prefer **independent verification** and challenge over echoing or softening claims.
- Actively hunt for, in roughly this order of value to the project:
  * install-hook macro errors — install.commands takes explicit %{buildroot}%{prefix}/…, install.post takes bare %{prefix}/… because the RPM post-processor rewrites it; %{srcdir} is \$PWD at spec-generation time and is unsafe wherever the shell CWD is not the source root (e.g. install.post for cmake recipes, where CWD is build/)
  * missing runtime dependencies — AutoReqProv is deliberately off, so nothing in the RPM/DEB metadata catches a miss; the recipe must name every one
  * files/<package>.txt drift — paths that are installed but unlisted, listed but never installed, or version-stamped directories hard-coded as x.y.z instead of %{version}
  * flavor-gating errors — include_flavors vs exclude_flavors, flavor-specific dependency dicts, and the opt-in-only meaning of an explicit empty include_flavors list
  * cross-builder divergence — rpm_builder.py, deb_builder.py, and unix_builder.py must agree; rpm_builder.py is the one most often left behind, so check it explicitly
  * shell quoting and expansion bugs in emitted build/configure/install commands
  * license and ABI policy violations, and stale or misapplied patches under patches/<package>/
  * over-claims that cannot be proven from the code and docs you can read, and incorrect file:line citations
- Every non-trivial claim **must** be backed by specific file paths and line numbers (or an explicit \"I could not read X, here is the limitation\").
- State confidence explicitly (high / medium / low, with ~% when helpful) and ground it in what you actually verified.
- **Name the evidence level.** The primary dev host is macOS and cannot run rpmbuild, so claims about RPM install behaviour cannot be settled by reading source. Say plainly when a finding needs an executable gate (a real build, an rpmbuild run, an install test on a Linux host) instead of implying it is settled.
- Use the exchange format conventions. The wrapper script adds the '# GROK <timestamp> (model=..., effort=...)' header itself — do NOT write any '# GROK' header, timestamp or model/effort stamp yourself. Start directly with '## Audit & Refutation' (or similar ## sections such as '## Verified Claims', '## Refuted / Challenged Claims', '## Open Risks', '## Checklist Items (N/A noted)').
- This is a **read-only** audit. Available tools are file read/search only (read_file, grep, list_dir).
- **CRITICAL — no shell, no subprocess:** Do NOT call run_terminal_command / bash / python. In headless mode a shell permission cancel aborts the entire turn and only your lead-in sentence is returned. Never try to run a build, rpmbuild, or the scls wrapper. Do all checks by reading files and reasoning. Do not modify files.
- Keep lead-in narration to at most one short sentence, then produce the full ## audit body in the same final message. Never end the turn with only \"I'll check…\" / \"Next I'll…\".
- Do not be sycophantic. If something looks wrong or underspecified, say so plainly and cite evidence.

AUDIT / REFUTATION REQUEST (focused task from the primary AI):
$AUDIT_PROMPT

Remember: the value of this invocation is the parts where you genuinely disagree with or tighten the primary AI's statements. But do NOT manufacture refutations: if the claims under audit hold up, say so plainly ('## Verified Claims' with evidence) — a clean bill of health backed by file:line citations is a fully valid and useful result.

FINAL MESSAGE REQUIREMENT: your last message must contain the complete audit under ## headings. Tool-call turns may be silent; the closing message must BE the audit, not a promise to write one."

# Finish prompt for --resume salvage after a Cancelled / narration-only turn.
FINISH_PROMPT="Your previous headless turn ended early (often stopReason=Cancelled when a shell tool was permission-cancelled, or you only emitted lead-in narration).

You already have file contents from earlier tool calls in this session. Do NOT call run_terminal_command / bash / python. Do NOT re-read everything unless essential.

Write the COMPLETE audit now, starting with ## sections (## Audit & Refutation / ## Verified Claims / ## Refuted / Challenged Claims / ## Open Risks as appropriate). Include file:line evidence and confidence tiers. The final message must BE the audit body, not a promise to write one."

# --- Temp files ---
TMPOUT=$(mktemp "${TMPDIR:-/tmp}/grok_response_XXXXXX")
TMPERR=$(mktemp "${TMPDIR:-/tmp}/grok_err_XXXXXX")
PROMPT_FILE=$(mktemp "${TMPDIR:-/tmp}/grok_prompt_XXXXXX")
FINISH_FILE=$(mktemp "${TMPDIR:-/tmp}/grok_finish_XXXXXX")
META_FILE=$(mktemp "${TMPDIR:-/tmp}/grok_meta_XXXXXX")
trap 'rm -f "$TMPOUT" "$TMPERR" "$PROMPT_FILE" "$FINISH_FILE" "$META_FILE"' EXIT

printf '%s\n' "$FULL_PROMPT" > "$PROMPT_FILE"
printf '%s\n' "$FINISH_PROMPT" > "$FINISH_FILE"

# Always set now that GROK_EFFORT is defaulted rather than left empty. Kept as an array
# for symmetry with PERM_ARGS and because "${arr[@]}" is the set -u-safe expansion.
EFFORT_ARGS=(--effort "$GROK_EFFORT")

PERM_ARGS=()
if [ -n "$GROK_PERMISSION_MODE" ]; then
    PERM_ARGS=(--permission-mode "$GROK_PERMISSION_MODE")
fi

# Parse grok JSON → writes META_FILE as: stopReason\nsessionId\ntext_byte_length
# prints body text on stdout. Exit 2 = unparseable.
parse_grok_json() {
    local aJsonFile="$1"
    local aMetaFile="$2"
    python3 - "$aJsonFile" "$aMetaFile" <<'PY'
import json, sys
path, meta_path = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        with open(meta_path, "w", encoding="utf-8") as m:
            m.write("\n\n0\n")
        sys.exit(0)
    data = json.loads(raw)
except (OSError, json.JSONDecodeError) as e:
    print(f"ask_grok.sh: failed to parse grok JSON output: {e}", file=sys.stderr)
    sys.exit(2)

text = data.get("text")
if text is None:
    text = ""
if not isinstance(text, str):
    text = str(text)

stop = data.get("stopReason") or data.get("stop_reason") or ""
sid = data.get("sessionId") or data.get("session_id") or ""

with open(meta_path, "w", encoding="utf-8") as m:
    m.write(f"{stop}\n{sid}\n{len(text)}\n")

sys.stdout.write(text)
if text and not text.endswith("\n"):
    sys.stdout.write("\n")
PY
}

# Split fused "##" onto its own line (lead-in + heading with no newline).
fix_fused_heading() {
    perl -0pe 's/^(.*?[^\n])(\#\#+ )/$1\n\n$2/s'
}

# Quality gate: 0 = usable, 1 = reject (retry/salvage).
# Rejects: empty, a cancelled/aborted/refusal stopReason, missing ## (if required),
# below GROK_MIN_CHARS, pure lead-in narration patterns.
# grok CLI 1.0.13 reports the TURN stop reason in snake_case.  Documented set
# (docs/user-guide/14-headless-mode.md): end_turn, max_tokens, max_turn_requests,
# refusal, cancelled.  Earlier builds used CamelCase (EndTurn, Cancelled), and the
# docs call the list non-exhaustive.
#
# permission_cancelled and aborted are NOT turn stop reasons -- permission_cancelled
# is a StopCancelled hook-matcher reason (docs/user-guide/10-hooks.md).  They are
# matched below only as forward-defensive coverage in case the headless projector
# ever promotes a category token into this field; a 1.0.13 cancel arrives as
# 'cancelled' and is caught by that arm.
#
# Fold spellings to one token so a future casing change cannot silently disable
# the gates below.  Display still uses the raw value.
normalize_stop_reason() {
    printf '%s' "$1" | tr -d '_-' | tr '[:upper:]' '[:lower:]'
}

quality_gate() {
    local aText="$1"
    local aStop="$2"
    local aLen
    local tStop

    tStop=$(normalize_stop_reason "$aStop")
    case "$tStop" in
        permissioncancelled)
            echo "quality_gate: stopReason=$aStop (headless permission cancel — usually shell tool)" >&2
            return 1
            ;;
        cancelled|canceled|aborted)
            echo "quality_gate: stopReason=$aStop (turn did not finish; cause not classified)" >&2
            return 1
            ;;
        refusal)
            echo "quality_gate: stopReason=$aStop (model refused the prompt)" >&2
            return 1
            ;;
    esac

    aText=$(fix_fused_heading <<< "$aText")
    aLen=$(printf '%s' "$aText" | wc -c | tr -d ' ')

    if [ -z "$aText" ] || [ "$aLen" -eq 0 ]; then
        echo "quality_gate: empty body" >&2
        return 1
    fi

    if [ "$GROK_REQUIRE_HEADING" != "0" ] && ! grep -q '##' <<< "$aText"; then
        echo "quality_gate: no '##' section heading (narration-only lead-in likely); len=$aLen" >&2
        return 1
    fi

    if [ "$aLen" -lt "$GROK_MIN_CHARS" ]; then
        echo "quality_gate: body too short ($aLen < GROK_MIN_CHARS=$GROK_MIN_CHARS)" >&2
        return 1
    fi

    # Lead-in-only patterns that still managed a tiny ## stub are rare; the min-chars gate covers them.
    return 0
}

# Common grok headless argv prefix (caller adds prompt source + optional --resume).
run_grok() {
    # Args: extra args before redirect... actually we take all as grok args.
    set +e
    # --model and --effort belong here, not at the call site: this function also runs the
    # --resume salvage pass, and a depth set only on the fresh attempt would be silently
    # dropped exactly when the audit is being rescued.
    "$GROK_BIN" "$@" \
        --cwd "$SCLS_ROOT" \
        --model "$GROK_MODEL" \
        --sandbox "$GROK_SANDBOX" \
        --tools "$GROK_TOOLS" \
        --no-memory \
        --no-subagents \
        --max-turns "$GROK_MAX_TURNS" \
        --output-format json \
        --verbatim \
        "${PERM_ARGS[@]}" \
        "${EFFORT_ARGS[@]}" \
        > "$TMPOUT" 2> "$TMPERR"
    local tExit=$?
    # NOTE: do NOT re-enable errexit here. The callers wrap this function in
    # their own set +e / set -e pair; restoring errexit before `return $tExit`
    # makes a nonzero grok exit kill the whole script at the call site
    # (observed 2026-08-25: "attempt 1/5" then silent exit, no retries).
    return $tExit
}

handle_sandbox_or_hard_fail() {
    local aExit="$1"
    if grep -qi "sandbox could not be applied" "$TMPERR"; then
        echo "grok ran WITHOUT the requested sandbox profile '$GROK_SANDBOX':" >&2
        cat "$TMPERR" >&2
        echo "Result discarded (not appended to $EXCHANGE). Fix GROK_SANDBOX and retry." >&2
        exit 1
    fi
    if [ "$aExit" -ne 0 ]; then
        if grep -qiE "sandbox profile resolve failed|could not enforce its deny list" "$TMPERR"; then
            echo "grok refused to start: sandbox profile '$GROK_SANDBOX' could not be built." >&2
            echo "This is a host problem, not an API or auth problem. Common cause: a path on" >&2
            echo "grok's built-in deny list is unreadable, e.g. /run/podman mode 0700 (the" >&2
            echo "systemd-tmpfiles default) blocking resolution of /run/podman/podman.sock." >&2
        fi
        echo "grok invocation failed (exit $aExit):" >&2
        cat "$TMPERR" >&2
        if [ -s "$TMPOUT" ]; then
            echo "Partial output (if any):" >&2
            cat "$TMPOUT" >&2
        fi
        exit "$aExit"
    fi
}

# --- Main attempt loop (fresh sessions) + optional resume salvage per attempt ---
RESULT=""
STOP_REASON=""
SESSION_ID=""
USABLE=0

for (( ATTEMPT = 1; ATTEMPT <= GROK_RETRIES; ATTEMPT++ )); do
    : > "$TMPOUT"; : > "$TMPERR"; : > "$META_FILE"

    echo "ask_grok.sh: attempt $ATTEMPT/$GROK_RETRIES (fresh session, tools=$GROK_TOOLS)" >&2

    set +e
    run_grok --prompt-file "$PROMPT_FILE"
    GROK_EXIT=$?
    set -e
    handle_sandbox_or_hard_fail "$GROK_EXIT"

    set +e
    RESULT=$(parse_grok_json "$TMPOUT" "$META_FILE")
    PARSE_EXIT=$?
    set -e
    if [ $PARSE_EXIT -eq 2 ]; then
        echo "ask_grok.sh: grok returned non-JSON or unparseable output:" >&2
        cat "$TMPOUT" >&2
        cat "$TMPERR" >&2
        exit 1
    fi

    STOP_REASON=$(sed -n '1p' "$META_FILE" | tr -d '\r')
    SESSION_ID=$(sed -n '2p' "$META_FILE" | tr -d '\r')
    RESULT=$(fix_fused_heading <<< "$RESULT")

    if quality_gate "$RESULT" "$STOP_REASON"; then
        USABLE=1
        break
    fi

    echo "ask_grok.sh: attempt $ATTEMPT rejected (stopReason=${STOP_REASON:-unknown}, session=${SESSION_ID:-none})" >&2
    if [ -n "$RESULT" ]; then
        echo "ask_grok.sh: rejected body preview: $(printf '%s' "$RESULT" | head -c 160 | tr '\n' ' ')…" >&2
    fi

    # Resume salvage: finish the audit in the same session that already read files.
    # This specifically targets permission_cancelled turns where tool results exist but
    # the final ## body never arrived.
    if [ "$GROK_RESUME_SALVAGE" = "1" ] && [ -n "$SESSION_ID" ]; then
        echo "ask_grok.sh: resume salvage on session $SESSION_ID …" >&2
        : > "$TMPOUT"; : > "$TMPERR"; : > "$META_FILE"
        set +e
        run_grok --prompt-file "$FINISH_FILE" --resume "$SESSION_ID"
        GROK_EXIT=$?
        set -e
        # Resume can fail if session vanished; treat as soft and continue retry loop.
        if [ $GROK_EXIT -eq 0 ] && ! grep -qi "sandbox could not be applied" "$TMPERR"; then
            set +e
            RESULT=$(parse_grok_json "$TMPOUT" "$META_FILE")
            PARSE_EXIT=$?
            set -e
            if [ $PARSE_EXIT -eq 0 ]; then
                STOP_REASON=$(sed -n '1p' "$META_FILE" | tr -d '\r')
                RESULT=$(fix_fused_heading <<< "$RESULT")
                if quality_gate "$RESULT" "$STOP_REASON"; then
                    echo "ask_grok.sh: resume salvage succeeded" >&2
                    USABLE=1
                    break
                fi
                echo "ask_grok.sh: resume salvage still failed quality gate (stopReason=${STOP_REASON:-unknown})" >&2
            fi
        else
            echo "ask_grok.sh: resume salvage invoke failed (exit $GROK_EXIT); continuing retries" >&2
            if [ -s "$TMPERR" ]; then
                cat "$TMPERR" >&2
            fi
        fi
    fi

    # Backoff grows with attempt index; failures can cluster in time, so wait longer than
    # independent-coin-flip would suggest (3s, 8s, 15s, 24s, …).
    if [ "$ATTEMPT" -lt "$GROK_RETRIES" ]; then
        SLEEP_S=$(( ATTEMPT * ATTEMPT + 2 * ATTEMPT ))
        echo "ask_grok.sh: backing off ${SLEEP_S}s before next fresh attempt …" >&2
        sleep "$SLEEP_S"
    fi
done

if [ "$USABLE" -ne 1 ]; then
    echo "ask_grok.sh: failed to obtain a usable audit after $GROK_RETRIES attempt(s)." >&2
    echo "Last stopReason=${STOP_REASON:-unknown} session=${SESSION_ID:-none}" >&2
    echo "Nothing was appended to $EXCHANGE." >&2
    echo "Hints:" >&2
    echo "  - Ensure GROK_TOOLS has no shell tools (current: $GROK_TOOLS)" >&2
    echo "  - Raise GROK_MAX_TURNS for large audits (current: $GROK_MAX_TURNS)" >&2
    echo "  - Raise GROK_RETRIES / GROK_MIN_CHARS as needed" >&2
    echo "  - Do not call bare 'grok -p' for audits; use this wrapper" >&2
    if [ -s "$TMPOUT" ]; then
        echo "Last raw JSON:" >&2
        cat "$TMPOUT" >&2
    fi
    exit 1
fi

# Non-end_turn but still usable (e.g. max turns with a real body) — warn.
case "$(normalize_stop_reason "$STOP_REASON")" in
    endturn|"")
        ;;
    *)
        echo "ask_grok.sh: WARNING — stopReason='$STOP_REASON' (accepted after quality gate)." >&2
        echo "Consider raising GROK_MAX_TURNS (current: $GROK_MAX_TURNS) if the body looks truncated." >&2
        ;;
esac

# --- Record in the exchange channel with distinct # GROK voice ---
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

{
    printf '\n---\n\n'
    printf '# GROK %s  (model=%s, effort=%s)\n' "$TIMESTAMP" "$GROK_MODEL_TAG" "$GROK_EFFORT_TAG"
    printf '%s\n' "$RESULT"
} >> "$EXCHANGE"

# --- Echo to the caller (Claude) ---
printf '%s\n' "$RESULT"
