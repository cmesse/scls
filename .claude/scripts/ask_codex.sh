#!/usr/bin/env bash
# ask_codex.sh — request an independent audit from Codex and record it in the AI-only exchange.
#
# Usage:
#   ask_codex.sh "Audit this specific claim or file section..."
#   ask_codex.sh -      (reads prompt from stdin)
#   echo "prompt" | ask_codex.sh
#   AI_EXCHANGE_SLUG=petsc_mkl_link ask_codex.sh "..."      # pin the per-task topic file
#   CODEX_BIN=/path/to/codex ask_codex.sh "..."             # override the CLI location
#
# The script prepends a role preamble so Codex knows its audit context, then appends
# the formatted response under a # CODEX header to the per-task AI-only exchange file
# ./tmp/ai_exchange/<slug>.md (audience tier: AI-only, ephemeral — see the protocol §2/§10).
# Codex's response is also echoed to stdout for Claude to read inline.

# Codex CLI resolution — must stay portable across machines and user names
# (Linux $HOME=/home/<user>, macOS $HOME=/Users/<user>):
#   1. explicit $CODEX_BIN
#   2. `codex` on $PATH
#   3. the npm global location $HOME/Applications/npm/bin/codex
if [ -n "${CODEX_BIN:-}" ]; then
    CODEX="$CODEX_BIN"
elif command -v codex >/dev/null 2>&1; then
    CODEX="$(command -v codex)"
else
    CODEX="$HOME/Applications/npm/bin/codex"
fi
if [ ! -x "$CODEX" ]; then
    echo "ask_codex.sh: Codex CLI not found or not executable: $CODEX" >&2
    echo "Install the Codex CLI, put it on \$PATH, or set CODEX_BIN=/path/to/codex." >&2
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
    # session id (e.g. 798c6b0c-...) reliably reaches this subprocess; shard per session
    SLUG="sess_$(sanitize_slug "${CLAUDE_CODE_SESSION_ID:0:8}")"
else
    SLUG="scratch"
fi
[ -n "$SLUG" ] || SLUG="scratch"
EXCHANGE_DIR="$SCLS_ROOT/tmp/ai_exchange"
EXCHANGE="$EXCHANGE_DIR/$SLUG.md"
mkdir -p "$EXCHANGE_DIR"
[ -f "$EXCHANGE" ] || : > "$EXCHANGE"

# Collect prompt from argument or stdin
if [ $# -eq 0 ] || [ "$1" = "-" ]; then
    AUDIT_PROMPT=$(cat)
else
    AUDIT_PROMPT="$*"
fi

if [ -z "$AUDIT_PROMPT" ]; then
    echo "Usage: ask_codex.sh \"<audit prompt>\"  OR  ask_codex.sh - (reads stdin)" >&2
    echo "Example: ask_codex.sh \"Audit recipes/vtk.yaml install.post: does it produce a double %{buildroot} in the generated spec? Check against python/rpm_builder.py.\"" >&2
    exit 1
fi

# Prepend role context so Codex reads the protocol and applies the checklist.
# The preamble is kept short to avoid consuming too much of the context window.
FULL_PROMPT="You are the Codex AI conducting a read-only audit for SCLS (Scientific Core Library Stack),
a Python + YAML build system that compiles and packages scientific software into RPMs, DEBs, and
macOS packages across several optimization flavors (gcc, mkl, debug, intel, lbl, macos).

Before answering, read these files in the project root:
  - CLAUDE.md                            (architecture, build commands, conventions)
  - doc/AI_COLLABORATION_PROTOCOL.md     (your role, the audit checklist, the required format)
Read the policy doc relevant to the task if it touches licensing (doc/LICENSE_POLICY.md),
MKL ABI (doc/MKL_ABI_POLICY.md), or macOS (doc/MACOS_BUILD.md).

This task's AI-only exchange thread is at:
  $EXCHANGE
Read it first (it may be empty or hold prior entries) so you have the conversation context before auditing.

WHAT MATTERS IN THIS CODEBASE (protocol §4 has the full checklist):
- Recipe/flavor gating: include_flavors vs exclude_flavors, flavor-specific dependency dicts,
  and the opt-in-only meaning of an explicit empty include_flavors list.
- Macro expansion in install hooks: install.commands takes explicit %{buildroot}%{prefix}/…,
  install.post takes bare %{prefix}/… because the RPM post-processor rewrites it. %{srcdir} is
  \$PWD at spec-generation time and is unsafe wherever the shell CWD is not the source root.
- files/<package>.txt manifests: they must match what is actually installed; version-stamped
  directories belong in %{version} form, not a hard-coded x.y.z.
- AutoReqProv is deliberately off, so RPM/DEB metadata will NOT catch a missing dependency —
  every runtime dependency must be explicit in the recipe.
- The three builders (rpm_builder.py, deb_builder.py, unix_builder.py) must stay consistent.
  Always double-check rpm_builder.py when any build logic changes.
- Linux uses lib64/ with lib -> lib64; macOS uses lib/ with no split.

Key rules:
- Prefer independent verification over agreement; challenge assumptions.
- State a confidence tier (high / medium / low) and ground it in evidence you actually checked.
- Format your response starting with '## Audit & Verdict' then 'Confidence: <tier>'.
- Reference specific file paths and line numbers wherever possible.
- Note explicitly when a claim can only be settled by an executable gate (a real build, an
  rpmbuild run, an install test) rather than by reading source — the primary dev host is macOS
  and cannot run rpmbuild, so such claims stay open rather than being assumed correct.
- This is a read-only audit: do not modify any files, and do not start a build.

AUDIT REQUEST:
$AUDIT_PROMPT"

TMPOUT=$(mktemp "${TMPDIR:-/tmp}/codex_response_XXXXXX")
TMPERR=$(mktemp "${TMPDIR:-/tmp}/codex_err_XXXXXX")
TMPPROMPT=$(mktemp "${TMPDIR:-/tmp}/codex_prompt_XXXXXX")
trap 'rm -f "$TMPOUT" "$TMPERR" "$TMPPROMPT"' EXIT

# The prompt goes through a file and stdin (`codex exec -`), never through
# argv: a large prompt — an inlined review bundle broke here at ~128 KiB with
# "Argument list too long" — exceeds the kernel's per-argument limit, while
# stdin has none. The redirect also guarantees a clean EOF, so the known
# codex-exec hang on an open stdin cannot occur.
printf '%s\n' "$FULL_PROMPT" > "$TMPPROMPT"

"$CODEX" exec \
    --sandbox read-only \
    -C "$SCLS_ROOT" \
    --output-last-message "$TMPOUT" \
    - < "$TMPPROMPT" \
    >/dev/null 2>"$TMPERR"

CODEX_EXIT=$?
if [ $CODEX_EXIT -ne 0 ]; then
    echo "codex exec failed (exit $CODEX_EXIT):" >&2
    cat "$TMPERR" >&2
    exit $CODEX_EXIT
fi

RESULT=$(cat "$TMPOUT")
if [ -z "$RESULT" ]; then
    echo "codex returned an empty response" >&2
    exit 1
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

{
    printf '\n---\n\n'
    printf '# CODEX %s\n' "$TIMESTAMP"
    printf '%s\n' "$RESULT"
} >> "$EXCHANGE"

printf '%s\n' "$RESULT"
