#!/usr/bin/env bash
#
# prune_old_packages.sh — keep only the newest build artifact per package.
#
# Every rebuild leaves the previous version's .rpm / .src.rpm / .deb sitting in
# the output tree. They accumulate, they make "which one is current?" ambiguous,
# and `./scls install` picks by mtime, so a stale file that got touched can be
# installed by accident.
#
# This groups artifacts by (kind, flavor, package, arch) — so scls-debug-cmake
# and scls-mkl-cmake are tracked separately, as are the binary and source RPMs —
# then keeps the newest N by version-release and removes the rest.
#
# DRY RUN BY DEFAULT. Nothing is deleted without --apply.
#
# Usage:
#   scripts/prune_old_packages.sh                  # report what would go
#   scripts/prune_old_packages.sh --apply          # actually delete
#   scripts/prune_old_packages.sh --keep 2         # keep the newest two
#   scripts/prune_old_packages.sh --flavor debug   # restrict to one flavor
#   scripts/prune_old_packages.sh --package vtk    # restrict to one package
#
# Exit status: 0 on success, 1 on usage error, 2 if a directory is unreadable.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APPLY=0
KEEP=1
ONLY_FLAVOR=""
ONLY_PACKAGE=""

# Search roots. RPM/SRPM live under rpmbuild/ for the RPM builder; unix_builder
# writes to work/pkgs and work/spkgs, which is also where .debs land.
SEARCH_DIRS=(
    "$PROJECT_ROOT/rpmbuild/RPMS"
    "$PROJECT_ROOT/rpmbuild/SRPMS"
    "$PROJECT_ROOT/work/pkgs"
    "$PROJECT_ROOT/work/spkgs"
)

usage() {
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)    APPLY=1; shift ;;
        --keep)     KEEP="${2:-}"; shift 2 ;;
        --flavor)   ONLY_FLAVOR="${2:-}"; shift 2 ;;
        --package)  ONLY_PACKAGE="${2:-}"; shift 2 ;;
        --dir)      SEARCH_DIRS=("${2:-}"); shift 2 ;;
        -h|--help)  usage 0 ;;
        *)          echo "unknown option: $1" >&2; usage 1 >&2 ;;
    esac
done

if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || [[ "$KEEP" -lt 1 ]]; then
    echo "--keep must be a positive integer (got '$KEEP')" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Collect artifacts as: <group-key>|<version-release>|<path>
#
# Filenames are parsed from the RIGHT, because both flavor names and package
# names contain hyphens (scls-debug-superlu-dist) and only the trailing
# -version-release.arch.ext portion has a fixed shape.
#
#   RPM/SRPM:  scls-<flavor>-<pkg>-<version>-<release>.<arch>.rpm
#   DEB:       scls-<flavor>-<pkg>_<version>-<release>_<arch>.deb
# ---------------------------------------------------------------------------
collect() {
    local d f base stem ver rel arch kind key
    for d in "${SEARCH_DIRS[@]}"; do
        [[ -d "$d" ]] || continue
        if [[ ! -r "$d" ]]; then
            echo "cannot read $d" >&2
            exit 2
        fi
        while IFS= read -r -d '' f; do
            base="$(basename "$f")"
            case "$base" in
                *.src.rpm)
                    [[ "$base" =~ ^(.+)-([^-]+)-([^-]+)\.src\.rpm$ ]] || continue
                    stem="${BASH_REMATCH[1]}"; ver="${BASH_REMATCH[2]}"; rel="${BASH_REMATCH[3]}"
                    kind="srpm"; arch="src"
                    ;;
                *.rpm)
                    [[ "$base" =~ ^(.+)-([^-]+)-([^-]+)\.([^.]+)\.rpm$ ]] || continue
                    stem="${BASH_REMATCH[1]}"; ver="${BASH_REMATCH[2]}"
                    rel="${BASH_REMATCH[3]}"; arch="${BASH_REMATCH[4]}"
                    kind="rpm"
                    ;;
                *.deb)
                    [[ "$base" =~ ^(.+)_([^_]+)-([^_-]+)_([^_]+)\.deb$ ]] || continue
                    stem="${BASH_REMATCH[1]}"; ver="${BASH_REMATCH[2]}"
                    rel="${BASH_REMATCH[3]}"; arch="${BASH_REMATCH[4]}"
                    kind="deb"
                    ;;
                *) continue ;;
            esac

            # stem is scls-<flavor>-<pkg>; filter on it when asked.
            if [[ -n "$ONLY_FLAVOR" && "$stem" != scls-"$ONLY_FLAVOR"-* ]]; then
                continue
            fi
            if [[ -n "$ONLY_PACKAGE" ]]; then
                # package name is the tail; allow the deb '_' -> '-' rewrite
                local want="${ONLY_PACKAGE//_/-}"
                [[ "$stem" == *-"$want" ]] || continue
            fi

            key="${kind}|${stem}|${arch}"
            printf '%s\t%s\t%s\n' "$key" "${ver}-${rel}" "$f"
        done < <(find "$d" -type f \( -name '*.rpm' -o -name '*.deb' \) -print0)
    done
}

mapfile -t ROWS < <(collect | sort -t$'\t' -k1,1 -k2,2V)

if [[ ${#ROWS[@]} -eq 0 ]]; then
    echo "No .rpm/.src.rpm/.deb artifacts found under:"
    printf '  %s\n' "${SEARCH_DIRS[@]}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Walk the sorted rows; within each group the newest KEEP entries survive.
# sort -V above puts oldest first, so everything except the last KEEP goes.
# ---------------------------------------------------------------------------
declare -A GROUP_COUNT
for row in "${ROWS[@]}"; do
    key="${row%%$'\t'*}"
    GROUP_COUNT["$key"]=$(( ${GROUP_COUNT["$key"]:-0} + 1 ))
done

declare -A SEEN
TO_DELETE=()
KEPT=()
for row in "${ROWS[@]}"; do
    IFS=$'\t' read -r key vr path <<< "$row"
    idx=$(( ${SEEN["$key"]:-0} + 1 ))
    SEEN["$key"]=$idx
    total=${GROUP_COUNT["$key"]}
    if (( idx <= total - KEEP )); then
        TO_DELETE+=("$path")
    else
        KEPT+=("$key|$vr")
    fi
done

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
echo "Scanned: ${#ROWS[@]} artifacts in ${#GROUP_COUNT[@]} groups (keeping newest $KEEP per group)"
echo

if [[ ${#TO_DELETE[@]} -eq 0 ]]; then
    echo "Nothing to prune — every group already has at most $KEEP version(s)."
    exit 0
fi

# Group the report by package stem so it reads as "cmake: dropping X, keeping Y".
declare -A REPORTED
for row in "${ROWS[@]}"; do
    IFS=$'\t' read -r key vr path <<< "$row"
    total=${GROUP_COUNT["$key"]}
    (( total > KEEP )) || continue
    if [[ -z "${REPORTED[$key]:-}" ]]; then
        REPORTED["$key"]=1
        IFS='|' read -r kind stem arch <<< "$key"
        printf '%s  [%s/%s]\n' "$stem" "$kind" "$arch"
    fi
done | sort -u

echo
freed=0
for f in "${TO_DELETE[@]}"; do
    sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
    freed=$(( freed + sz ))
    printf '  DELETE  %s\n' "${f#"$PROJECT_ROOT"/}"
done

echo
for k in $(printf '%s\n' "${KEPT[@]}" | sort -u); do
    IFS='|' read -r kind stem arch vr <<< "$k"
    printf '  keep    %-34s %-6s %-8s %s\n' "$stem" "$kind" "$arch" "$vr"
done

printf '\n%d file(s), %.1f MiB\n' "${#TO_DELETE[@]}" "$(awk "BEGIN{print $freed/1048576}")"

if [[ $APPLY -eq 0 ]]; then
    echo
    echo "DRY RUN — nothing deleted. Re-run with --apply to remove the files above."
    exit 0
fi

echo
for f in "${TO_DELETE[@]}"; do
    rm -f -- "$f"
    printf 'deleted %s\n' "${f#"$PROJECT_ROOT"/}"
done
printf '\nRemoved %d file(s).\n' "${#TO_DELETE[@]}"
