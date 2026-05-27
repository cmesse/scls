#!/usr/bin/env bash
set -euo pipefail

prefix="/opt/scls"
libdir=""
dry_run=0
verbose=0

usage() {
    cat <<'USAGE'
Usage: tools/fix_macos_install_names.sh [options]

Rewrite local @rpath dylib install names under an SCLS prefix to absolute
paths in that prefix's lib directory.

Options:
  --prefix PATH   SCLS prefix to repair (default: /opt/scls)
  --libdir PATH   Library directory to repair (default: PREFIX/lib)
  --dry-run       Print install_name_tool commands without changing files
  --verbose       Print every dylib as it is inspected
  -h, --help      Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            [[ $# -ge 2 ]] || { echo "error: --prefix requires a path" >&2; exit 2; }
            prefix="$2"
            shift 2
            ;;
        --libdir)
            [[ $# -ge 2 ]] || { echo "error: --libdir requires a path" >&2; exit 2; }
            libdir="$2"
            shift 2
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        --verbose)
            verbose=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$libdir" ]]; then
    libdir="$prefix/lib"
fi

if [[ ! -d "$libdir" ]]; then
    echo "error: library directory not found: $libdir" >&2
    exit 1
fi

command -v otool >/dev/null 2>&1 || { echo "error: otool not found" >&2; exit 1; }
if [[ "$dry_run" -eq 0 ]]; then
    command -v install_name_tool >/dev/null 2>&1 || {
        echo "error: install_name_tool not found" >&2
        exit 1
    }
fi

rewrite_local_name() {
    local install_name="$1"
    local rel=""
    local candidate=""

    case "$install_name" in
        @rpath/*)
            rel="${install_name#@rpath/}"
            candidate="$libdir/$rel"
            if [[ -e "$candidate" ]]; then
                printf '%s\n' "$candidate"
                return 0
            fi
            ;;
    esac

    return 1
}

run_install_name_tool() {
    if [[ "$dry_run" -eq 1 ]]; then
        printf 'install_name_tool'
        printf ' %q' "$@"
        printf '\n'
    else
        install_name_tool "$@"
    fi
}

files_seen=0
ids_changed=0
deps_changed=0

while IFS= read -r dylib; do
    files_seen=$((files_seen + 1))
    if [[ "$verbose" -eq 1 ]]; then
        echo "inspect: $dylib"
    fi

    dylib_id="$(otool -D "$dylib" 2>/dev/null | sed -n '2s/^[[:space:]]*//p')" || true
    if [[ -n "$dylib_id" ]]; then
        if new_id="$(rewrite_local_name "$dylib_id")"; then
            if [[ "$new_id" != "$dylib_id" ]]; then
                run_install_name_tool -id "$new_id" "$dylib"
                ids_changed=$((ids_changed + 1))
            fi
        fi
    fi

    while IFS= read -r linked_name; do
        [[ -n "$linked_name" ]] || continue
        [[ "$linked_name" != "$dylib_id" ]] || continue

        if new_name="$(rewrite_local_name "$linked_name")"; then
            if [[ "$new_name" != "$linked_name" ]]; then
                run_install_name_tool -change "$linked_name" "$new_name" "$dylib"
                deps_changed=$((deps_changed + 1))
            fi
        fi
    done < <(otool -L "$dylib" 2>/dev/null | awk 'NR > 1 { print $1 }')
done < <(find "$libdir" -type f -name '*.dylib' -print | sort)

echo "inspected dylibs: $files_seen"
echo "dylib IDs changed: $ids_changed"
echo "dependency names changed: $deps_changed"

if [[ "$dry_run" -eq 1 ]]; then
    echo "dry run only; no files were modified"
fi
