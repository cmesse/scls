#!/usr/bin/env bash
# install_autoreview_hook.sh [--uninstall] — install the opt-in post-commit auto-review
# hook into the SHARED hooks dir (git-common-dir), so one install covers every worktree.
# The hook is a no-op unless SCLS_AUTOREVIEW=1 and never blocks the commit.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$(cd "$ROOT" && cd "$(git rev-parse --git-common-dir)" && pwd)/hooks"
HOOK="$HOOKS_DIR/post-commit"
MARKER="scls-autoreview"

if [ "${1:-}" = "--uninstall" ]; then
    if [ -f "$HOOK" ] && grep -q "$MARKER" "$HOOK"; then
        rm "$HOOK"
        echo "removed $HOOK"
    else
        echo "no $MARKER post-commit hook installed"
    fi
    exit 0
fi

if [ -f "$HOOK" ] && ! grep -q "$MARKER" "$HOOK"; then
    echo "install_autoreview_hook.sh: refusing to overwrite existing foreign hook: $HOOK" >&2
    exit 1
fi

mkdir -p "$HOOKS_DIR"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# scls-autoreview — opt-in background light review. Must NEVER block the commit
# and never touch the tree. Runs in whatever worktree the commit happened in.
[ "${SCLS_AUTOREVIEW:-0}" = "1" ] || exit 0
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
# Resolve the commit NOW — the background job must not race the next commit.
SHA="$(git rev-parse HEAD 2>/dev/null)" || exit 0
[ -x "$TOP/scripts/cross_review.sh" ] || exit 0
nohup nice -n 19 "$TOP/scripts/cross_review.sh" --quick "$SHA" >/dev/null 2>&1 &
exit 0
EOF
chmod +x "$HOOK"
echo "installed $HOOK"
echo "opt-in per shell: export SCLS_AUTOREVIEW=1 (default OFF; covers all worktrees)"
echo "if codex/grok are not on the hook's PATH, create scripts/ai_env.sh to pin it"
