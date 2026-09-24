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
#   GROK_DISALLOWED_TOOLS Removed even when --tools would keep them
#                         (default: search_tool,use_tool). The allowlist cannot drop those
#                         MCP meta-tools; --disallowed-tools can, and it wins when both are
#                         set. Set it to empty to leave them available. Unset keeps the default.
#   GROK_MAX_TURNS        Agent turn budget (default: 80). Multi-file audits were cut off at
#                         30 and again at 60 while still reading files.
#   GROK_MODEL            grok-4.7|grok-4.6|grok-4.5 (default: grok-4.7, the current seat —
#                         Christian's decision, 2026-09-23). Older ids stay allowlisted so an
#                         earlier round can be reproduced.
#                         grok-4.7-build-fast is the CLI's coding model, not an audit tier,
#                         and is deliberately not listed.
#                         The seat lives in three places that must agree:
#                         doc/AI_COLLABORATION_PROTOCOL.md §9.1, scripts/cross_review.sh's
#                         allowlist, and this default. The unattended post-commit --quick row
#                         deliberately stays on grok-4.6 — that is the cheap rung, the same
#                         reason its Codex column is luna rather than terra.
#   GROK_EFFORT           low|medium|high|xhigh (default: xhigh)
#                         The old list here also advertised none|minimal|max, which these models
#                         do not offer; max and ultra are excluded on purpose (ultra delegates to
#                         subagents, against the --no-subagents this wrapper passes).
#                         grok-4.5's menu is low|medium|high. Pairing it with the xhigh
#                         default is rejected before the call.
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
#                         reusing the session that already read files. A cancelled turn is
#                         never accepted before this has been tried — see the quality gate.
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
#   Mitigation: --tools allowlist without shell (plus --disallowed-tools for the MCP
#   meta-tools the allowlist cannot drop) + a quality gate that rejects permission-cancel,
#   refusal, aborted and narration-only bodies + --resume salvage to finish from files
#   already read. A generic `cancelled` turn carrying a complete-looking ## body is held
#   back as a last-resort fallback: salvage runs first, and if nothing finishes cleanly the
#   held body is filed with its stop reason stamped on the # GROK line and a truncation
#   warning in the entry, rather than silently passing as a finished audit.
#
# Invocation notes:
#   - --prompt-file + --output-format json (extract .text / stopReason / sessionId)
#   - --sandbox read-only + --tools allowlist + --disallowed-tools for the MCP meta-tools
#     (NOT --permission-mode plan — that is a no-op policy)
#   - --verbatim, --no-memory, --no-subagents
#
# After successful run it appends:
#     ---
#     # GROK 2026-06-12 12:34:56 PDT  (model=grok-4.6, effort=xhigh)
#     <Grok's full response body>
# A turn that did not reach end_turn adds ', stop=<reason>[/<category>]' to that header, and
# a last-resort body filed after every attempt failed also carries a POSSIBLY TRUNCATED
# blockquote — on stdout as well as in the file, so the caller sees it inline.
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
# search_tool / use_tool stay in the schema after --tools. Disallow them unless the caller
# sets GROK_DISALLOWED_TOOLS (including to empty, which leaves them available).
if [ -z "${GROK_DISALLOWED_TOOLS+x}" ]; then
    GROK_DISALLOWED_TOOLS="search_tool,use_tool"
fi
GROK_MAX_TURNS="${GROK_MAX_TURNS:-80}"

# --- Depth selection: model + reasoning effort -------------------------------
# Validated before any prompt is read, so a typo costs no billed call.
GROK_MODEL_CHOSEN=1
GROK_EFFORT_CHOSEN=1
if [ -z "${GROK_MODEL:-}" ];  then GROK_MODEL="grok-4.7"; GROK_MODEL_CHOSEN=0;  fi
if [ -z "${GROK_EFFORT:-}" ]; then GROK_EFFORT="xhigh";   GROK_EFFORT_CHOSEN=0; fi

case "$GROK_MODEL" in
    grok-4.7|grok-4.6|grok-4.5) ;;
    *)
        echo "ask_grok.sh: unknown GROK_MODEL '$GROK_MODEL'. Allowed: grok-4.7 grok-4.6 grok-4.5" >&2
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

# grok-4.5 advertises low|medium|high only. The xhigh default would 400 on that menu.
if [ "$GROK_MODEL" = "grok-4.5" ] && [ "$GROK_EFFORT" = "xhigh" ]; then
    echo "ask_grok.sh: grok-4.5 does not offer effort xhigh (menu: low medium high)." >&2
    echo "Set GROK_EFFORT=high, or use grok-4.6 / grok-4.7 for xhigh." >&2
    exit 1
fi

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
FINISH_PROMPT="Your previous headless turn ended early (stopReason=Cancelled when a shell tool was permission-cancelled, when the turn budget --max-turns ran out while you were still reading files, or when you only emitted lead-in narration).

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

# Parse grok JSON → writes META_FILE as:
#   stopReason\nsessionId\ntext_byte_length\ncancellationCategory
# prints body text on stdout. Exit 2 = unparseable.
# cancellationCategory is optional. grok 1.0.41 reports a turn-budget death as
# stopReason=cancelled; the category, when the projector includes it, says why. It is
# diagnostic only here — nothing gates on it (a generic nested "reason" can land in it).
parse_grok_json() {
    local aJsonFile="$1"
    local aMetaFile="$2"
    python3 - "$aJsonFile" "$aMetaFile" <<'PY'
import json, sys
path, meta_path = sys.argv[1], sys.argv[2]

def first_str(obj, keys):
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

try:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        with open(meta_path, "w", encoding="utf-8") as m:
            m.write("\n\n0\n\n")
        sys.exit(0)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON is {type(data).__name__}, expected object")
except (OSError, ValueError, json.JSONDecodeError) as e:
    print(f"ask_grok.sh: failed to parse grok JSON output: {e}", file=sys.stderr)
    sys.exit(2)

text = data.get("text")
if text is None:
    text = ""
if not isinstance(text, str):
    text = str(text)

stop = data.get("stopReason") or data.get("stop_reason") or ""
sid = data.get("sessionId") or data.get("session_id") or ""
cat_keys = ("cancellationCategory", "cancellation_category")
category = first_str(data, cat_keys)
if not category:
    for nest in ("cancellationContext", "cancellation_context"):
        category = first_str(data.get(nest), cat_keys + ("reason",))
        if category:
            break

with open(meta_path, "w", encoding="utf-8") as m:
    m.write(f"{stop}\n{sid}\n{len(text)}\n{category}\n")

sys.stdout.write(text)
if text and not text.endswith("\n"):
    sys.stdout.write("\n")
PY
}

# Split fused "##" onto its own line (lead-in + heading with no newline).
fix_fused_heading() {
    perl -0pe 's/^(.*?[^\n])(\#\#+ )/$1\n\n$2/s'
}

# Quality gate: 0 = usable, 1 = reject (retry/salvage), 2 = complete-looking body on a
# generic `cancelled` turn — held back as a fallback, NOT accepted yet.
# Rejects outright: empty, permission-cancel / refusal / aborted, missing ## (if required),
# below GROK_MIN_CHARS.
#
# Return 2 is the deliberate difference from the BELFEM wrapper, which accepts a cancelled
# turn as soon as it carries a ## body. That skips the --resume salvage that can still turn
# the same session into a finished audit, and files a possibly truncated body as an ordinary
# completed one. Here salvage runs first; the held body is used only if every attempt fails,
# and then it is stamped and flagged in the exchange entry.
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
    local aCategory="${3:-}"
    local aLen
    local tStop
    local tWhy=""
    local tCancelled=0

    tStop=$(normalize_stop_reason "$aStop")
    case "$tStop" in
        permissioncancelled)
            echo "quality_gate: stopReason=$aStop (headless permission cancel — usually shell tool)" >&2
            return 1
            ;;
        aborted)
            echo "quality_gate: stopReason=$aStop (turn aborted)" >&2
            return 1
            ;;
        refusal)
            echo "quality_gate: stopReason=$aStop (model refused the prompt)" >&2
            return 1
            ;;
        cancelled|canceled|maxturnrequests|maxtokens)
            # Every documented way a turn can die mid-audit. grok 1.0.41 reports a
            # turn-budget death as `cancelled`, but the documented spellings
            # max_turn_requests / max_tokens mean exactly the same thing here: the body
            # may stop mid-sentence. All of them take the hold-and-salvage path, so the
            # salvage the comments advertise is not wired to one spelling only.
            tCancelled=1
            ;;
    esac

    aText=$(fix_fused_heading <<< "$aText")
    aLen=$(printf '%s' "$aText" | wc -c | tr -d ' ')

    if [ -z "$aText" ] || [ "$aLen" -eq 0 ]; then
        tWhy="empty body"
    elif [ "$GROK_REQUIRE_HEADING" != "0" ] && ! grep -q '##' <<< "$aText"; then
        tWhy="no '##' section heading (narration-only lead-in likely); len=$aLen"
    elif [ "$aLen" -lt "$GROK_MIN_CHARS" ]; then
        tWhy="body too short ($aLen < GROK_MIN_CHARS=$GROK_MIN_CHARS)"
    fi

    if [ -n "$tWhy" ]; then
        if [ "$tCancelled" -eq 1 ]; then
            echo "quality_gate: $tWhy; stopReason=$aStop${aCategory:+ category=$aCategory}" >&2
        else
            echo "quality_gate: $tWhy" >&2
        fi
        return 1
    fi

    if [ "$tCancelled" -eq 1 ]; then
        echo "quality_gate: stopReason=$aStop${aCategory:+ category=$aCategory} with a complete-looking body — held as fallback, trying salvage first" >&2
        return 2
    fi

    return 0
}

# Common grok headless argv prefix (caller adds prompt source + optional --resume).
run_grok() {
    # Args: extra args before redirect... actually we take all as grok args.
    set +e
    # --model and --effort belong here, not at the call site: this function also runs the
    # --resume salvage pass, and a depth set only on the fresh attempt would be silently
    # dropped exactly when the audit is being rescued.
    local tDisallow=()
    if [ -n "${GROK_DISALLOWED_TOOLS:-}" ]; then
        tDisallow=(--disallowed-tools "$GROK_DISALLOWED_TOOLS")
    fi
    "$GROK_BIN" "$@" \
        --cwd "$SCLS_ROOT" \
        --model "$GROK_MODEL" \
        --sandbox "$GROK_SANDBOX" \
        --tools "$GROK_TOOLS" \
        "${tDisallow[@]}" \
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
CANCEL_CATEGORY=""
USABLE=0
# Best complete-looking body from a turn that ended `cancelled`. Used only after every
# attempt (including salvage) has failed, and flagged in the exchange entry when it is.
FALLBACK_TEXT=""
FALLBACK_STOP=""
FALLBACK_CATEGORY=""
FALLBACK_LEN=0
TRUNCATED=0

TRUNCATION_NOTE='
> **POSSIBLY TRUNCATED** — no attempt reached end_turn and resume salvage did not finish
> the turn (or was disabled). This body passed the heading and length checks, nothing more.
> Treat the absence of a section as "not reviewed", not "no finding".'

# Append to the exchange and echo to the caller. Defined before the retry loop because the
# hard-fail paths inside the loop use it too: a complete-looking body already paid for on an
# earlier attempt must not be discarded because a later attempt hit a setup error.
file_result() {
    local tTimestamp tStopTag=""
    tTimestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')
    # A turn that did not reach end_turn is stamped on the header line, so a later reader
    # sees that an entry may be cut short without digging for the stderr of this run.
    case "$(normalize_stop_reason "$STOP_REASON")" in
        endturn|"") ;;
        *) tStopTag=", stop=$STOP_REASON${CANCEL_CATEGORY:+/$CANCEL_CATEGORY}" ;;
    esac
    {
        printf '\n---\n\n'
        printf '# GROK %s  (model=%s, effort=%s%s)\n' \
            "$tTimestamp" "$GROK_MODEL_TAG" "$GROK_EFFORT_TAG" "$tStopTag"
        if [ "$TRUNCATED" -eq 1 ]; then printf '%s\n' "$TRUNCATION_NOTE"; fi
        printf '%s\n' "$RESULT"
    } >> "$EXCHANGE"

    # The caller (Claude) reads stdout, so the marker has to be here as well — otherwise a
    # last-resort body reads inline exactly like a finished audit.
    if [ "$TRUNCATED" -eq 1 ]; then printf '%s\n' "$TRUNCATION_NOTE"; fi
    printf '%s\n' "$RESULT"
}

# Called on the paths that abandon the run: file a held body before failing out.
flush_fallback_if_any() {
    [ -n "$FALLBACK_TEXT" ] || return 0
    RESULT="$FALLBACK_TEXT"
    STOP_REASON="$FALLBACK_STOP"
    CANCEL_CATEGORY="$FALLBACK_CATEGORY"
    TRUNCATED=1
    echo "ask_grok.sh: filing the held body from an earlier attempt before failing out" >&2
    file_result
    FALLBACK_TEXT=""
}

# $1 = body, $2 = stopReason, $3 = category. Keeps the longest candidate seen.
remember_fallback() {
    local tLen
    tLen=$(printf '%s' "$1" | wc -c | tr -d ' ')
    if [ "$tLen" -gt "$FALLBACK_LEN" ]; then
        FALLBACK_TEXT="$1"; FALLBACK_STOP="$2"; FALLBACK_CATEGORY="$3"; FALLBACK_LEN="$tLen"
    fi
}

for (( ATTEMPT = 1; ATTEMPT <= GROK_RETRIES; ATTEMPT++ )); do
    : > "$TMPOUT"; : > "$TMPERR"; : > "$META_FILE"

    echo "ask_grok.sh: attempt $ATTEMPT/$GROK_RETRIES (fresh session, tools=$GROK_TOOLS)" >&2

    set +e
    run_grok --prompt-file "$PROMPT_FILE"
    GROK_EXIT=$?
    set -e
    if [ "$GROK_EXIT" -ne 0 ] || grep -qi "sandbox could not be applied" "$TMPERR"; then
        flush_fallback_if_any
    fi
    handle_sandbox_or_hard_fail "$GROK_EXIT"

    set +e
    RESULT=$(parse_grok_json "$TMPOUT" "$META_FILE")
    PARSE_EXIT=$?
    set -e
    if [ $PARSE_EXIT -eq 2 ]; then
        echo "ask_grok.sh: grok returned non-JSON or unparseable output:" >&2
        cat "$TMPOUT" >&2
        cat "$TMPERR" >&2
        flush_fallback_if_any
        exit 1
    fi

    STOP_REASON=$(sed -n '1p' "$META_FILE" | tr -d '\r')
    SESSION_ID=$(sed -n '2p' "$META_FILE" | tr -d '\r')
    CANCEL_CATEGORY=$(sed -n '4p' "$META_FILE" | tr -d '\r')
    RESULT=$(fix_fused_heading <<< "$RESULT")

    QG=0
    quality_gate "$RESULT" "$STOP_REASON" "$CANCEL_CATEGORY" || QG=$?
    if [ "$QG" -eq 0 ]; then
        USABLE=1
        break
    fi
    if [ "$QG" -eq 2 ]; then
        remember_fallback "$RESULT" "$STOP_REASON" "$CANCEL_CATEGORY"
    fi

    echo "ask_grok.sh: attempt $ATTEMPT rejected (stopReason=${STOP_REASON:-unknown}, category=${CANCEL_CATEGORY:-none}, session=${SESSION_ID:-none})" >&2
    if [ -n "$RESULT" ]; then
        echo "ask_grok.sh: rejected body preview: $(printf '%s' "$RESULT" | head -c 160 | tr '\n' ' ')…" >&2
    fi

    # Resume salvage: finish the audit in the same session that already read files.
    # Targets permission_cancelled turns where tool results exist but the final ## body
    # never arrived, and turn-budget cutoffs reported as a generic `cancelled`.
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
                CANCEL_CATEGORY=$(sed -n '4p' "$META_FILE" | tr -d '\r')
                RESULT=$(fix_fused_heading <<< "$RESULT")
                QG=0
                quality_gate "$RESULT" "$STOP_REASON" "$CANCEL_CATEGORY" || QG=$?
                if [ "$QG" -eq 0 ]; then
                    echo "ask_grok.sh: resume salvage succeeded" >&2
                    USABLE=1
                    break
                fi
                if [ "$QG" -eq 2 ]; then
                    remember_fallback "$RESULT" "$STOP_REASON" "$CANCEL_CATEGORY"
                fi
                echo "ask_grok.sh: resume salvage still failed quality gate (stopReason=${STOP_REASON:-unknown}, category=${CANCEL_CATEGORY:-none})" >&2
            fi
        else
            echo "ask_grok.sh: resume salvage invoke failed (exit $GROK_EXIT); continuing retries" >&2
            if [ -s "$TMPERR" ]; then
                cat "$TMPERR" >&2
            fi
        fi
    elif [ "$GROK_RESUME_SALVAGE" = "1" ]; then
        echo "ask_grok.sh: no sessionId on the rejected turn; resume salvage skipped" >&2
    fi

    # Backoff grows with attempt index; failures can cluster in time, so wait longer than
    # independent-coin-flip would suggest (3s, 8s, 15s, 24s, …).
    if [ "$ATTEMPT" -lt "$GROK_RETRIES" ]; then
        SLEEP_S=$(( ATTEMPT * ATTEMPT + 2 * ATTEMPT ))
        echo "ask_grok.sh: backing off ${SLEEP_S}s before next fresh attempt …" >&2
        sleep "$SLEEP_S"
    fi
done

# Nothing finished cleanly, but a cancelled turn did produce a complete-looking body and
# salvage had its chance. File that rather than throw the audit away — marked, not silent.
if [ "$USABLE" -ne 1 ] && [ -n "$FALLBACK_TEXT" ]; then
    echo "ask_grok.sh: no attempt reached end_turn; filing the held body from" \
         "stopReason=${FALLBACK_STOP:-unknown}${FALLBACK_CATEGORY:+ category=$FALLBACK_CATEGORY} as POSSIBLY TRUNCATED" >&2
    RESULT="$FALLBACK_TEXT"
    STOP_REASON="$FALLBACK_STOP"
    CANCEL_CATEGORY="$FALLBACK_CATEGORY"
    TRUNCATED=1
    USABLE=1
fi

if [ "$USABLE" -ne 1 ]; then
    echo "ask_grok.sh: failed to obtain a usable audit after $GROK_RETRIES attempt(s)." >&2
    echo "Last stopReason=${STOP_REASON:-unknown} category=${CANCEL_CATEGORY:-none} session=${SESSION_ID:-none}" >&2
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
        echo "ask_grok.sh: WARNING — stopReason='$STOP_REASON'${CANCEL_CATEGORY:+ category=$CANCEL_CATEGORY} (accepted after quality gate)." >&2
        echo "Consider raising GROK_MAX_TURNS (current: $GROK_MAX_TURNS) if the body looks truncated." >&2
        ;;
esac

# --- Record in the exchange channel with distinct # GROK voice, and echo to the caller ---
file_result
