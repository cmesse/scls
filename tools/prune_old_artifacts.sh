#!/usr/bin/env bash
#
# Remove stale SCLS package artifacts after recipe version bumps.
#
# Default mode is a dry run. Pass --delete to remove the listed files.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DELETE=false
SOURCE_CACHE=true
INCLUDE_BUILD_DIRS=false

FLAVORS=()
PACKAGES=()
OLD_VERSIONS=()

usage() {
    cat <<'EOF'
Usage:
  tools/prune_old_artifacts.sh [options] [package ...]

Options:
  -d, --delete             Delete files. Default is dry-run.
  -f, --flavor FLAVOR      Limit package artifacts to a flavor. Repeatable.
                           Defaults to every flavor in flavors/.
  -v, --version VERSION    Delete only this old upstream version. Repeatable.
                           Without this, deletes versions older/different than
                           the current recipe version for each selected flavor.
  --no-source-cache        Do not prune cached upstream tarballs in
                           rpmbuild/SOURCES or work/sources.
  --include-build-dirs     Also prune old extracted build trees in work/build.
  -h, --help               Show this help.

Examples:
  tools/prune_old_artifacts.sh petsc
  tools/prune_old_artifacts.sh --delete petsc
  tools/prune_old_artifacts.sh --version 3.25.0 --delete petsc
  tools/prune_old_artifacts.sh --flavor gcc --delete petsc

Artifact roots scanned:
  rpmbuild/RPMS, rpmbuild/SRPMS, work/pkgs, work/spkgs,
  rpmbuild/SOURCES, work/sources
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        -d|--delete)
            DELETE=true
            ;;
        --dry-run)
            DELETE=false
            ;;
        -f|--flavor)
            shift
            (($#)) || die "--flavor requires a value"
            FLAVORS+=("$1")
            ;;
        -v|--version)
            shift
            (($#)) || die "--version requires a value"
            OLD_VERSIONS+=("$1")
            ;;
        --no-source-cache)
            SOURCE_CACHE=false
            ;;
        --include-build-dirs)
            INCLUDE_BUILD_DIRS=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while (($#)); do
                PACKAGES+=("$1")
                shift
            done
            break
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            PACKAGES+=("$1")
            ;;
    esac
    shift
done

[[ -d recipes ]] || die "run from the SCLS project root"
[[ -d flavors ]] || die "missing flavors/ directory"

if ((${#FLAVORS[@]} == 0)); then
    while IFS= read -r flavor; do
        FLAVORS+=("$flavor")
    done < <(find flavors -maxdepth 1 -type f -name '*.yaml' \
        -exec basename {} .yaml \; | sort)
fi

if ((${#PACKAGES[@]} == 0)); then
    while IFS= read -r package; do
        PACKAGES+=("$package")
    done < <(find recipes -maxdepth 1 -type f -name '*.yaml' \
        -exec basename {} .yaml \; | sort)
fi

for flavor in "${FLAVORS[@]}"; do
    [[ -f "flavors/${flavor}.yaml" ]] || die "unknown flavor: $flavor"
done

for package in "${PACKAGES[@]}"; do
    [[ -f "recipes/${package}.yaml" ]] || die "unknown package: $package"
done

TMPDIR="${TMPDIR:-/tmp}"
META_FILE="$(mktemp "${TMPDIR%/}/scls-prune-meta.XXXXXX")"
CANDIDATE_FILE="$(mktemp "${TMPDIR%/}/scls-prune-candidates.XXXXXX")"
trap 'rm -f "$META_FILE" "$CANDIDATE_FILE"' EXIT

SCLS_PRUNE_FLAVORS="$(printf '%s\n' "${FLAVORS[@]}")"
SCLS_PRUNE_PACKAGES="$(printf '%s\n' "${PACKAGES[@]}")"
export SCLS_PRUNE_FLAVORS SCLS_PRUNE_PACKAGES

python3 - "$ROOT" > "$META_FILE" <<'PY'
import copy
import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "python"))

from build_common import (  # noqa: E402
    apply_flavor_overrides,
    get_subpackages_for_flavor,
    load_flavor,
    load_recipe,
)


def deb_name(name):
    return name.replace("_", "-")


def normalize(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def merge_platform(recipe, platform_name):
    if platform_name in recipe:
        section = recipe[platform_name] or {}
        if "version" in section:
            recipe["version"] = section["version"]
        if "source" in section:
            recipe["source"] = dict(recipe.get("source", {}) or {})
            recipe["source"].update(section["source"] or {})
    return recipe


def resolved_recipe(package, flavor_name):
    recipe = copy.deepcopy(load_recipe(package))
    flavor = copy.deepcopy(load_flavor(flavor_name))
    recipe = merge_platform(recipe, flavor.get("platform", "linux"))
    recipe = apply_flavor_overrides(recipe, flavor)
    return recipe


def source_template(recipe):
    source = recipe.get("source", {}) or {}
    if source.get("type") == "generated":
        return ""
    return source.get("source0") or source.get("url") or ""


def safe_source_pattern(package, template):
    marker = "%{version}"
    if marker not in template:
        return None
    base = template.rsplit("/", 1)[-1]
    before, after = base.split(marker, 1)
    token = normalize(before + after)
    package_token = normalize(package)
    if package_token not in token:
        return None
    if not before and not after:
        return None
    return before, after


flavors = [x for x in os.environ["SCLS_PRUNE_FLAVORS"].splitlines() if x]
packages = [x for x in os.environ["SCLS_PRUNE_PACKAGES"].splitlines() if x]

source_versions = {}

for package in packages:
    for flavor_name in flavors:
        recipe = resolved_recipe(package, flavor_name)
        version = str(recipe.get("version", ""))
        release = str(recipe.get("release", "1"))

        rpm_main = f"scls-{flavor_name}-{package}"
        rpm_names = [rpm_main]
        deb_main = f"scls-{flavor_name}-{deb_name(package)}"
        deb_names = [deb_main]

        for subpkg in get_subpackages_for_flavor(recipe, flavor_name):
            sub_name = subpkg.get("name", "")
            if not sub_name:
                continue
            rpm_name = f"scls-{flavor_name}-{sub_name}"
            if rpm_name != rpm_main:
                rpm_names.append(rpm_name)
            deb_pkg_name = f"scls-{flavor_name}-{deb_name(sub_name)}"
            if deb_pkg_name != deb_main:
                deb_names.append(deb_pkg_name)

        rpm_names = sorted(set(rpm_names), key=lambda x: (-len(x), x))
        deb_names = sorted(set(deb_names), key=lambda x: (-len(x), x))

        print("\t".join([
            "ARTIFACT",
            package,
            flavor_name,
            version,
            release,
            rpm_main,
            ",".join(rpm_names),
            deb_main,
            ",".join(deb_names),
        ]))

        pattern = safe_source_pattern(package, source_template(recipe))
        if pattern and version:
            source_versions.setdefault((package, pattern[0], pattern[1]), set()).add(version)

for (package, before, after), versions in sorted(source_versions.items()):
    print("\t".join([
        "SOURCE",
        package,
        ",".join(sorted(versions)),
        before,
        after,
    ]))
PY

version_is_selected_old() {
    local version="$1"
    local old

    ((${#OLD_VERSIONS[@]} > 0)) || return 1
    for old in "${OLD_VERSIONS[@]}"; do
        [[ "$version" == "$old" ]] && return 0
    done
    return 1
}

version_is_current() {
    local version="$1"
    local current_csv="$2"
    local current
    local IFS=','

    read -r -a current_versions <<< "$current_csv"
    for current in "${current_versions[@]}"; do
        [[ "$version" == "$current" ]] && return 0
    done
    return 1
}

should_prune_version() {
    local version="$1"
    local current_csv="$2"

    [[ -n "$version" ]] || return 1
    if ((${#OLD_VERSIONS[@]} > 0)); then
        version_is_selected_old "$version"
        return
    fi
    ! version_is_current "$version" "$current_csv"
}

add_candidate() {
    local path="$1"
    local reason="$2"

    [[ -e "$path" ]] || return 0
    printf '%s\t%s\n' "$path" "$reason" >> "$CANDIDATE_FILE"
}

find_rpm_version() {
    local base="$1"
    local names_csv="$2"
    local name rest
    local IFS=','

    read -r -a names <<< "$names_csv"
    for name in "${names[@]}"; do
        if [[ "$base" == "$name"-* ]]; then
            rest="${base#"$name"-}"
            printf '%s\n' "${rest%%-*}"
            return 0
        fi
    done
    return 1
}

find_deb_version() {
    local base="$1"
    local names_csv="$2"
    local name rest
    local IFS=','

    read -r -a names <<< "$names_csv"
    for name in "${names[@]}"; do
        if [[ "$base" == "$name"_* ]]; then
            rest="${base#"$name"_}"
            printf '%s\n' "${rest%%-*}"
            return 0
        fi
    done
    return 1
}

find_deb_source_version() {
    local base="$1"
    local source_name="$2"
    local rest

    [[ "$base" == "$source_name"_* ]] || return 1
    rest="${base#"$source_name"_}"
    case "$base" in
        *.orig.tar.*)
            printf '%s\n' "${rest%%.orig.tar.*}"
            ;;
        *.debian.tar.*|*.dsc)
            printf '%s\n' "${rest%%-*}"
            ;;
        *)
            return 1
            ;;
    esac
}

find_source_cache_version() {
    local base="$1"
    local before="$2"
    local after="$3"
    local middle

    [[ "$base" == "$before"*"$after" ]] || return 1
    middle="${base#"$before"}"
    middle="${middle%"$after"}"
    [[ -n "$middle" ]] || return 1
    printf '%s\n' "$middle"
}

strip_archive_suffix() {
    local text="$1"

    case "$text" in
        *.tar.gz)  text="${text%.tar.gz}" ;;
        *.tgz)     text="${text%.tgz}" ;;
        *.tar.xz)  text="${text%.tar.xz}" ;;
        *.txz)     text="${text%.txz}" ;;
        *.tar.bz2) text="${text%.tar.bz2}" ;;
        *.tbz2)    text="${text%.tbz2}" ;;
        *.tar.zst) text="${text%.tar.zst}" ;;
        *.zip)     text="${text%.zip}" ;;
    esac

    printf '%s\n' "$text"
}

prune_artifact_line() {
    local package="$1"
    local flavor="$2"
    local current_version="$3"
    local _release="$4"
    local rpm_main="$5"
    local rpm_names="$6"
    local deb_main="$7"
    local deb_names="$8"
    local file base version

    if [[ -d rpmbuild/RPMS ]]; then
        while IFS= read -r -d '' file; do
            base="${file##*/}"
            version="$(find_rpm_version "$base" "$rpm_names" || true)"
            if should_prune_version "$version" "$current_version"; then
                add_candidate "$file" "$package/$flavor rpm version $version"
            fi
        done < <(find rpmbuild/RPMS -type f -name '*.rpm' ! -name '*.src.rpm' -print0)
    fi

    if [[ -d rpmbuild/SRPMS ]]; then
        while IFS= read -r -d '' file; do
            base="${file##*/}"
            version="$(find_rpm_version "$base" "$rpm_main" || true)"
            if should_prune_version "$version" "$current_version"; then
                add_candidate "$file" "$package/$flavor source rpm version $version"
            fi
        done < <(find rpmbuild/SRPMS -type f -name '*.src.rpm' -print0)
    fi

    if [[ -d work/pkgs ]]; then
        while IFS= read -r -d '' file; do
            base="${file##*/}"
            version="$(find_deb_version "$base" "$deb_names" || true)"
            if should_prune_version "$version" "$current_version"; then
                add_candidate "$file" "$package/$flavor deb version $version"
            fi
        done < <(find work/pkgs -maxdepth 1 -type f -name '*.deb' -print0)
    fi

    if [[ -d work/spkgs ]]; then
        while IFS= read -r -d '' file; do
            base="${file##*/}"
            version="$(find_deb_source_version "$base" "$deb_main" || true)"
            if should_prune_version "$version" "$current_version"; then
                add_candidate "$file" "$package/$flavor deb source version $version"
            fi
        done < <(find work/spkgs -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.orig.tar.*' -o -name '*.debian.tar.*' \) -print0)
    fi
}

prune_source_line() {
    local package="$1"
    local current_versions="$2"
    local before="$3"
    local after="$4"
    local root file base version

    [[ "$SOURCE_CACHE" == true ]] || return 0

    for root in rpmbuild/SOURCES work/sources; do
        [[ -d "$root" ]] || continue
        while IFS= read -r -d '' file; do
            base="${file##*/}"
            version="$(find_source_cache_version "$base" "$before" "$after" || true)"
            if should_prune_version "$version" "$current_versions"; then
                add_candidate "$file" "$package source cache version $version"
            fi
        done < <(find "$root" -maxdepth 1 -type f -print0)
    done
}

prune_build_dirs_for_source_line() {
    local package="$1"
    local current_versions="$2"
    local before="$3"
    local after="$4"
    local dir_after
    local dir base version

    [[ "$INCLUDE_BUILD_DIRS" == true ]] || return 0
    [[ -d work/build ]] || return 0
    dir_after="$(strip_archive_suffix "$after")"

    while IFS= read -r -d '' dir; do
        base="${dir##*/}"
        version="$(find_source_cache_version "$base" "$before" "$dir_after" || true)"
        if should_prune_version "$version" "$current_versions"; then
            add_candidate "$dir" "$package build tree version $version"
        fi
    done < <(find work/build -mindepth 1 -maxdepth 1 -type d -print0)
}

while IFS=$'\t' read -r kind c1 c2 c3 c4 c5 c6 c7 c8; do
    case "$kind" in
        ARTIFACT)
            prune_artifact_line "$c1" "$c2" "$c3" "$c4" "$c5" "$c6" "$c7" "$c8"
            ;;
        SOURCE)
            prune_source_line "$c1" "$c2" "$c3" "$c4"
            prune_build_dirs_for_source_line "$c1" "$c2" "$c3" "$c4"
            ;;
    esac
done < "$META_FILE"

if [[ ! -s "$CANDIDATE_FILE" ]]; then
    echo "No stale artifacts found."
    exit 0
fi

sort -u "$CANDIDATE_FILE" | while IFS=$'\t' read -r path reason; do
    if [[ "$DELETE" == true ]]; then
        if [[ -d "$path" ]]; then
            rm -rf -- "$path"
        else
            rm -f -- "$path"
        fi
        printf 'deleted: %s (%s)\n' "$path" "$reason"
    else
        printf 'would delete: %s (%s)\n' "$path" "$reason"
    fi
done

if [[ "$DELETE" != true ]]; then
    echo
    echo "Dry run only. Re-run with --delete to remove these files."
fi
