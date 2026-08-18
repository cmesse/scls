#!/usr/bin/env bash
# review_status.sh — commits since the last auto-review entry, plus open P0 flags.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AR="$ROOT/tmp/ai_exchange/autoreview.md"
FLAG="$ROOT/tmp/ai_exchange/AUTOREVIEW_P0.flag"

LAST=""
if [ -f "$AR" ]; then
    LAST="$(grep -oE '^## commit [0-9a-f]{7,40}' "$AR" | tail -1 | awk '{ print $3 }')"
fi

if [ -n "$LAST" ] && git -C "$ROOT" cat-file -e "$LAST" 2>/dev/null; then
    N="$(git -C "$ROOT" rev-list --count "$LAST..HEAD")"
    echo "commits since last auto-review: $N (last reviewed: ${LAST:0:12})"
else
    echo "commits since last auto-review: unknown (no auto-review entries yet)"
fi

if [ -s "$FLAG" ]; then
    echo "OPEN P0 FLAGS ($FLAG):"
    cat "$FLAG"
else
    echo "no open P0 flags"
fi
