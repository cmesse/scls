#!/usr/bin/env bash
# assemble_sources.sh — assemble one HSL source tree for libcoinhsl from a
# licensee's ORIGINAL HSL tarballs (SCLS, BSD-3-Clause-LBNL).
#
# HSL is proprietary (STFC HSL licence). This script is SCLS code and contains no
# HSL source; it only unpacks archives the licensee obtained themselves, into a
# directory outside the SCLS work tree. Nothing it produces may be shared.
#
# Usage: assemble_sources.sh [--no-overrides] <tarball-dir> <target-dir>
#
#   <target-dir>/src/         Coin-HSL tree, with verified standalone overrides
#   <target-dir>/originals/   Coin-HSL files an override replaced (for audit)
#   <target-dir>/LICENCES/    LICENCE.<package>-<version> of every tarball used
#   <target-dir>/PROVENANCE.txt
#
# Policy (todo/libhsl_source_selection.md §9):
#   * Coin-HSL is the base. Its release must be pinned below; an unknown release
#     stops, because the override table is only valid for a reviewed base.
#   * A standalone package replaces Coin-HSL's copy only if its version is
#     strictly newer than the pinned one (numeric compare; equal/older = skip),
#     and only if EVERY file under its src/ and include/ classifies as:
#       identical  byte-equal to Coin-HSL's file of the same role
#       replace    the intended change; copied over Coin-HSL's file
#       deps       each F77 unit / F90 module byte-equal (trailing blanks
#                  ignored) to the same unit in Coin-HSL common/deps*.f*;
#                  compared, never copied
#       ignore     autotools files
#     Anything unclassified or mismatching stops the build. Only file names and
#     hashes are printed, never source text.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

die()  { echo "assemble_sources: error: $*" >&2; exit 1; }
note() { echo "assemble_sources: $*"; }

# Every temporary file/dir this script makes is listed here and removed at exit;
# on a failed run the partially assembled target (which holds HSL source) is
# removed too, so no exit path leaves HSL content behind.
TMPS=()
TARGET=""
cleanup() {
    local rc=$?
    [ ${#TMPS[@]} -gt 0 ] && rm -rf "${TMPS[@]}"
    if [ $rc -ne 0 ] && [ -n "$TARGET" ] && [ -d "$TARGET" ]; then
        rm -rf "$TARGET/src" "$TARGET/originals" "$TARGET/LICENCES" "$TARGET/PROVENANCE.txt" \
               "$TARGET/PROVENANCE.txt.tmp" "$TARGET/.unpack"
    fi
}
trap cleanup EXIT

NO_OVERRIDES=0
if [ "${1:-}" = "--no-overrides" ]; then NO_OVERRIDES=1; shift; fi
[ $# -eq 2 ] || die "usage: $0 [--no-overrides] <tarball-dir> <target-dir>"
SRC_DIR="$(cd "$1" && pwd -P)" || die "no such directory: $1"
TARGET="$2"

# --- refuse a target inside the work tree ------------------------------------
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd -P)"   # physical path: a symlink cannot hide the work tree
case "$TARGET/" in
    "$REPO"/*) die "target $TARGET is inside the SCLS work tree; HSL sources must stay outside it" ;;
esac
[ -z "$(ls -A "$TARGET")" ] || die "target $TARGET is not empty"

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# --- pinned Coin-HSL releases -------------------------------------------------
# coinhsl version -> versions of the packages an override may replace. Taken from
# the release's ChangeLog when it was reviewed; the ChangeLog is re-read at build
# time only as a cross-check, and a disagreement stops the build.
coin_pin() {   # $1 coin version, $2 package -> pinned version (empty if unknown)
    case "$1:$2" in
        2024.05.15:HSL_MA77) echo 6.4.0 ;;
        2024.05.15:HSL_MA86) echo 1.7.4 ;;
        2024.05.15:HSL_MA97) echo 2.8.1 ;;
        *) echo "" ;;
    esac
}

# --- override table -------------------------------------------------------------
# Paths: standalone path (inside its tarball) = Coin-HSL path (inside coinhsl tree).
override_spec() {   # $1 package -> lines "class standalone_path coin_path"
    local p lc
    case "$1" in
        HSL_MA77|HSL_MA86|HSL_MA97)
            lc="$(echo "$1" | tr 'A-Z' 'a-z')"
            for p in d s; do
                echo "replace   src/${lc}${p}.f90         ${lc}/${lc}${p}.f90"
                echo "identical src/${lc}${p}_ciface.f90  ${lc}/C/${lc}${p}_ciface.f90"
                echo "identical include/${lc}${p}.h       ${lc}/C/${lc}${p}.h"
            done
            echo "deps      src/common.f         common/deps.f"
            echo "deps      src/common90.f90     common/deps90.f90"
            echo "deps      src/ddeps90.f90      common/deps90.f90"
            echo "deps      src/sdeps90.f90      common/deps90.f90"
            echo "ignore    src/Makefile.am      -"
            echo "ignore    src/Makefile.in      -"
            ;;
        *) die "no override spec for $1" ;;
    esac
}
OVERRIDE_PACKAGES="HSL_MA77 HSL_MA86 HSL_MA97"
# Present in a licensee's download set but deliberately never used:
#   ma57-*, hsl_ma57-*  standalone MA57 calls METIS 4's METIS_NODEND; Coin-HSL's copy
#                       uses its METIS 5 adapter. hsl_ma57 is a different package line.
#   hsl_mc68-*          HSL_MC68 lives inside Coin-HSL's common/deps90.f90.
#   hsl-galahad*        superseded GALAHAD subset.
IGNORED_GLOBS=('ma57-*.tar.gz' 'hsl_ma57-*.tar.gz' 'hsl_mc68-*.tar.gz' 'hsl-galahad*.tar.gz')

# --- safe extraction ------------------------------------------------------------
safe_extract() {   # $1 tarball, $2 destination; prints the single top-level dir
    local tb="$1" dest="$2" top listing
    # List once into files, then inspect them. A `tar | grep -q` pipeline under
    # pipefail can report failure when grep exits early and tar gets SIGPIPE,
    # which would turn a detected unsafe member into a silent pass.
    # Member paths come from the plain listing, never from columns of the verbose
    # one: GNU tar and bsdtar (macOS) lay those out differently (the name is field
    # 6 in one, field 9 in the other). LC_ALL=C pins the "link to" marker.
    listing="$(mktemp)"; TMPS+=("$listing" "$listing.names")
    # Callers run this in a command substitution, so TMPS above is lost with the
    # subshell: every exit path below removes the two files itself.
    LC_ALL=C tar -tvzf "$tb" > "$listing" || { rm -f "$listing"; die "$(basename "$tb"): cannot list archive"; }
    [ -s "$listing" ] || { rm -f "$listing"; die "$(basename "$tb"): empty archive listing"; }
    { LC_ALL=C tar -tzf "$tb" | sed -e 's#^\./##' > "$listing.names"; } \
        || { rm -f "$listing" "$listing.names"; die "$(basename "$tb"): cannot list archive"; }
    if grep -E '(^/|^\.\.(/|$)|/\.\.(/|$))' "$listing.names" >/dev/null; then
        rm -f "$listing" "$listing.names"; die "$(basename "$tb"): unsafe member path (absolute or ..)"
    fi
    # Hardlinks: refused if the target is absolute or has a '..' component. The
    # line is split on every " link to " and each piece after the first is tested,
    # so a target (or a name) containing blanks or the marker cannot hide one.
    if awk '$1 ~ /^h/ { n = split($0, p, " link to "); for (i = 2; i <= n; i++) print p[i] }' "$listing" \
         | grep -E '(^/|^\.\.(/|$)|/\.\.(/|$))' >/dev/null; then
        rm -f "$listing" "$listing.names"; die "$(basename "$tb"): link member pointing outside the archive"
    fi
    # Symlinks of any kind are refused outright: the classification step compares
    # regular files and would otherwise follow a link to content it never checked.
    if awk '$1 ~ /^l/ { c++ } END { exit !(c > 0) }' "$listing"; then
        rm -f "$listing" "$listing.names"; die "$(basename "$tb"): archive contains symlinks; refusing"
    fi
    top="$(sed -e 's#/.*##' "$listing.names" | grep -v '^$' | sort -u)"
    rm -f "$listing" "$listing.names"
    [ "$(printf '%s\n' "$top" | wc -l | tr -d ' ')" = 1 ] || die "$(basename "$tb"): not a single top-level directory"
    mkdir -p "$dest"
    tar -xzf "$tb" -C "$dest" --no-same-owner --no-same-permissions
    printf '%s\n' "$top"
}

one_match() {   # $1 glob -> path; dies on >1; empty on 0
    local m=()
    shopt -s nullglob; m=("$SRC_DIR"/$1); shopt -u nullglob
    [ ${#m[@]} -le 1 ] || die "more than one tarball matches $1: ${m[*]##*/}"
    [ ${#m[@]} -eq 1 ] && printf '%s\n' "${m[0]}" || true
}

version_gt() {   # numeric dotted compare: is $1 > $2 ?
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | tail -1)" = "$1" ]
}

# --- per-unit hashes for dependency comparison -----------------------------------
# F90: one hash per module (module ... end module). F77: one hash per program unit,
# keyed by its SUBROUTINE/FUNCTION name. Trailing whitespace is ignored; nothing else.
unit_hashes() {   # $1 file -> lines "kind:name sha256", then "COVERAGE headers=H units=U"
    # The caller dies unless H == U > 0: a unit the splitter does not recognise
    # (END SUBROUTINE form, tab indentation, END followed by a comment) must stop
    # the build rather than silently escape comparison.
    local f="$1" d u
    d="$(mktemp -d)"; TMPS+=("$d")
    # Portable awk (no gawk extensions): lower-case copies for matching only.
    awk -v f="$f" -v d="$d" '
        { line = $0; sub(/[ \t\r]+$/, "", line); lc = tolower(line) }
        f ~ /\.f90$/ {
            if (lc ~ /^[ \t]*module[ \t]+[a-z0-9_]+/ && lc !~ /^[ \t]*module[ \t]+procedure/) headers++
            if (out == "" && lc ~ /^[ \t]*module[ \t]+[a-z0-9_]+[ \t]*(!.*)?$/ && lc !~ /^[ \t]*module[ \t]+procedure/) {
                n = lc; sub(/^[ \t]*module[ \t]+/, "", n); sub(/[ \t!].*$/, "", n)
                out = d "/mod:" n
            }
            if (out != "") print line > out
            if (out != "" && lc ~ /^[ \t]*end[ \t]*module([ \t]|$)/) { close(out); out = ""; units++ }
            next
        }
        {
            if (lc ~ /^[ \t]*[^!c*].*(^|[ \t])(subroutine|function)[ \t]+[a-z0-9_]+/ && lc !~ /^[ \t]*end[ \t]/) headers++
            if (buf == "" && line ~ /^[ \t]*$/) next
            buf = buf line "\n"
            if (uname == "" && lc ~ /^      .*(subroutine|function)[ \t]+[a-z0-9_]+/) {
                u = lc; sub(/^.*(subroutine|function)[ \t]+/, "", u); sub(/[^a-z0-9_].*$/, "", u)
                uname = "f77:" u
            }
            if (lc ~ /^[ \t]+end[ \t]*$/) {
                if (uname != "") { o = d "/" uname; printf "%s", buf > o; close(o); units++ }
                buf = ""; uname = ""
            }
        }
        END { cov = d "/.coverage"; printf "COVERAGE headers=%d units=%d\n", headers, units > cov }
    ' "$f"
    for u in "$d"/*; do
        [ -e "$u" ] && echo "$(basename "$u") $(sha256 "$u")"
    done
    cat "$d/.coverage"
    rm -rf "$d"   # also in TMPS for the failure path
}
check_coverage() {   # $1 label, stdin = unit_hashes output -> echoes everything but the trailer
    local cov h u
    cov="$(grep '^COVERAGE ' | head -1)"
    h="${cov#*headers=}"; h="${h%% *}"; u="${cov##*units=}"
    [ -n "$cov" ] || die "$1: unit splitter produced no coverage record"
    [ "$u" -gt 0 ] || die "$1: no Fortran units recognised; cannot compare dependencies"
    [ "$h" = "$u" ] || die "$1: $h unit headers but only $u units parsed; unrecognised unit form"
}

# --- Coin-HSL base -----------------------------------------------------------------
COIN_TB="$(one_match 'coinhsl-*.tar.gz')"
[ -n "$COIN_TB" ] || die "no coinhsl-*.tar.gz in $SRC_DIR"
WORK="$TARGET/.unpack"
COIN_TOP="$(safe_extract "$COIN_TB" "$WORK/coin")"
mv "$WORK/coin/$COIN_TOP" "$TARGET/src"
COIN_VER="$(sed -n "s/^[[:space:]]*version[[:space:]]*:[[:space:]]*'\([^']*\)'.*/\1/p" "$TARGET/src/meson.build" | head -1)"
[ -n "$COIN_VER" ] || die "cannot read the Coin-HSL version from meson.build"
for pkg in $OVERRIDE_PACKAGES; do
    [ -n "$(coin_pin "$COIN_VER" "$pkg")" ] || die "Coin-HSL $COIN_VER has no pin for $pkg in this script; review the release and add all pins"
done
note "base: coinhsl-$COIN_VER"

mkdir -p "$TARGET/LICENCES" "$TARGET/originals"
cp "$TARGET/src/LICENCE" "$TARGET/LICENCES/LICENCE.coinhsl-$COIN_VER"

PROV="$TARGET/PROVENANCE.txt"
{
    echo "# Assembled HSL source tree for a private libcoinhsl build (SCLS)."
    echo "# Licensee use only; never share this tree or anything built from it."
    echo "assembler_git_blob: $(git -C "$REPO" hash-object "$SCRIPT_DIR/assemble_sources.sh" 2>/dev/null || echo unknown)"
    echo "assembled: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "base: coinhsl-$COIN_VER $(basename "$COIN_TB") sha256=$(sha256 "$COIN_TB")"
} > "$PROV"

# ChangeLog cross-check: the newest line naming a package must end in the pinned version.
changelog_version() {   # $1 package -> last vX.Y.Z on the first line mentioning it
    grep -m1 -E "(^|[^A-Za-z0-9_])$1[[:space:]]+v[0-9]" "$TARGET/src/ChangeLog" | grep -o -E 'v[0-9]+(\.[0-9]+)+' | tail -1 | tr -d v
}

# --- overrides ---------------------------------------------------------------------------
for pkg in $OVERRIDE_PACKAGES; do
    pin="$(coin_pin "$COIN_VER" "$pkg")"
    cl="$(changelog_version "$pkg" || true)"
    [ "$cl" = "$pin" ] || die "$pkg: Coin-HSL ChangeLog says '${cl:-?}', pin says $pin"
    lc="$(echo "$pkg" | tr 'A-Z' 'a-z')"
    tb="$(one_match "${lc}-*.tar.gz")"
    [ -n "$tb" ] || { note "$pkg: no standalone tarball; using Coin-HSL $pin"; continue; }
    ver="$(basename "$tb" .tar.gz)"; ver="${ver#${lc}-}"
    echo "$ver" | grep -E -q '^[0-9]+(\.[0-9]+)+$' || die "$pkg: cannot parse version from $(basename "$tb")"
    if [ "$NO_OVERRIDES" = 1 ]; then
        note "$pkg: standalone $ver present; --no-overrides, using Coin-HSL $pin"
        echo "override: $pkg skipped (--no-overrides), coinhsl has $pin" >> "$PROV"; continue
    fi
    if ! version_gt "$ver" "$pin"; then
        note "$pkg: standalone $ver is not newer than Coin-HSL's $pin; using Coin-HSL"
        echo "override: $pkg skipped, standalone $ver <= coinhsl $pin" >> "$PROV"; continue
    fi

    top="$(safe_extract "$tb" "$WORK/$lc")"
    sa="$WORK/$lc/$top"
    spec="$(override_spec "$pkg")"
    # Every file under src/ and include/ must be classified.
    while IFS= read -r f; do
        rel="${f#$sa/}"
        echo "$spec" | awk -v r="$rel" '$2 == r {found=1} END {exit !found}' \
            || die "$pkg $ver: unclassified file $rel; review the package before using it"
    done < <(find "$sa/src" "$sa/include" \( -type f -o -type l \) | sort)

    # Dependency units: what Coin-HSL provides.
    coin_units="$WORK/coin_units.txt"
    for cf in common/deps.f common/deps90.f90; do
        unit_hashes "$TARGET/src/$cf" > "$coin_units.part"
        check_coverage "coinhsl $cf" < "$coin_units.part"
        grep -v '^COVERAGE ' "$coin_units.part"
    done | sort > "$coin_units"; rm -f "$coin_units.part"

    replaced=""
    while read -r cls spath cpath; do
        [ -n "$cls" ] || continue
        case "$cls" in
            identical)
                [ -f "$sa/$spath" ] || die "$pkg $ver: expected $spath is missing"
                cmp -s "$sa/$spath" "$TARGET/src/$cpath" \
                    || die "$pkg $ver: $spath differs from Coin-HSL $cpath (interface change; sha256 $(sha256 "$sa/$spath") vs $(sha256 "$TARGET/src/$cpath"))" ;;
            deps)
                [ -f "$sa/$spath" ] || continue
                [ -s "$sa/$spath" ] || continue        # empty dependency file: nothing to compare
                unit_hashes "$sa/$spath" > "$WORK/sa_units.txt"
                check_coverage "$pkg $ver $spath" < "$WORK/sa_units.txt"
                while read -r unit hash; do
                    [ "$unit" = "COVERAGE" ] && continue
                    want="$(awk -v u="$unit" '$1 == u {print $2; exit}' "$coin_units")"
                    [ -n "$want" ] || die "$pkg $ver: $spath defines $unit, which Coin-HSL does not have"
                    [ "$want" = "$hash" ] || die "$pkg $ver: $spath unit $unit differs from Coin-HSL's ($hash vs $want)"
                done < "$WORK/sa_units.txt"
                ;;
            replace)
                [ -f "$sa/$spath" ] || die "$pkg $ver: expected $spath is missing"
                mkdir -p "$TARGET/originals/$(dirname "$cpath")"
                cp "$TARGET/src/$cpath" "$TARGET/originals/$cpath"
                cp "$sa/$spath" "$TARGET/src/$cpath"
                replaced="$replaced $cpath"
                echo "  replaced: $cpath coinhsl_sha256=$(sha256 "$TARGET/originals/$cpath") new_sha256=$(sha256 "$TARGET/src/$cpath")" >> "$PROV.tmp" ;;
            ignore) ;;
        esac
    done <<< "$spec"

    cp "$sa/LICENCE" "$TARGET/LICENCES/LICENCE.$lc-$ver"
    echo "override: $pkg $pin -> $ver $(basename "$tb") sha256=$(sha256 "$tb")" >> "$PROV"
    cat "$PROV.tmp" >> "$PROV"; rm -f "$PROV.tmp"
    note "$pkg: $pin -> $ver (replaced:$replaced)"
done

for g in "${IGNORED_GLOBS[@]}"; do
    shopt -s nullglob; for tb in "$SRC_DIR"/$g; do
        note "ignored (out of scope): $(basename "$tb")"
        echo "ignored: $(basename "$tb")" >> "$PROV"
    done; shopt -u nullglob
done

rm -rf "$WORK"
note "assembled tree: $TARGET/src"
