#!/bin/bash
# Assert that a flavor's shipped ELF objects agree on ONE math/threading model.
#
# Why this exists. SCLS sets AutoReqProv: no, so RPM/DEB metadata records nothing
# about which MKL threading layer or BLAS provider a binary is bound to. The
# binding lives only in DT_NEEDED, and a mismatch surfaces at runtime, not at
# install time. On 2026-09-25 exactly that slipped through: libscalapack linked
# libmkl_sequential while all 256 other MKL references in the same flavor linked
# libmkl_gnu_thread, so `ldd libpetsc.so` loaded BOTH threading layers into one
# process — a configuration Intel documents as unsupported. It had been shipping
# for at least one release and the campaign's own provenance check passed it,
# because that check asked "is ScaLAPACK ours?" and never "is the flavor
# self-consistent?". See devlog/dl20260925_mkl_threading_uniformity.md.
#
# The rule this encodes is per-FLAVOR uniformity, which no per-package check can
# see: every offender here is individually well-formed and only wrong in company.
#
# Usage:
#   scripts/check_mkl_linkage.sh --flavor mkl --prefix /opt/scls/mkl
#   scripts/check_mkl_linkage.sh --flavor mkl --dir work/staging/<DROP>/el9/x86_64
#
# Exit 0 = uniform, 1 = violation, 2 = usage/environment error.

set -u -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLAVOR=""; PREFIX=""; DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --flavor) FLAVOR="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --dir)    DIR="$2";    shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "$FLAVOR" ] || { echo "usage: $0 --flavor <f> [--prefix DIR | --dir RPMDIR]" >&2; exit 2; }
[ -n "$PREFIX" ] || [ -n "$DIR" ] || { echo "error: need --prefix or --dir" >&2; exit 2; }
command -v readelf >/dev/null || { echo "error: readelf not found (binutils)" >&2; exit 2; }

# The expected model comes from the flavor file, never from a hardcoded list, so
# a new flavor is covered the day it is added rather than silently unchecked.
read -r LINALG THREADING FAMILY < <(python3 - "$REPO" "$FLAVOR" <<'PY'
import sys, yaml, pathlib
repo, flavor = sys.argv[1], sys.argv[2]
f = yaml.safe_load(open(pathlib.Path(repo) / "flavors" / f"{flavor}.yaml")) or {}
seen = {flavor}
while f.get("inherits") and f["inherits"] not in seen:      # follow the fallback chain
    seen.add(f["inherits"])
    parent = yaml.safe_load(open(pathlib.Path(repo) / "flavors" / f"{f['inherits']}.yaml")) or {}
    parent.update({k: v for k, v in f.items() if k != "inherits"})
    f = parent
math = f.get("math", {}) or {}
cc = str((f.get("compilers", {}) or {}).get("cc", "gcc"))
fam = "intel" if any(t in cc for t in ("icx", "icc", "ifx")) else "gnu"
print(math.get("linalg", "reference"), math.get("threading", "openmp"), fam)
PY
) || { echo "error: could not read flavors/$FLAVOR.yaml" >&2; exit 2; }

echo "flavor:    $FLAVOR (linalg=$LINALG threading=$THREADING toolchain=$FAMILY)"

# Collect the ELF files to inspect. RPMs are extracted to a scratch dir: reading
# DT_NEEDED needs the real object, and grepping the compressed payload for
# library names gives false hits from .cmake files and docs that merely mention
# them.
WORK=""
cleanup() { [ -n "$WORK" ] && rm -rf "$WORK"; }
trap cleanup EXIT

if [ -n "$DIR" ]; then
    [ -d "$DIR" ] || { echo "error: $DIR is not a directory" >&2; exit 2; }
    WORK=$(mktemp -d) || exit 2
    n=0
    for f in "$DIR"/*.rpm; do
        [ -e "$f" ] || continue
        case "$(basename "$f")" in *.src.rpm) continue ;; esac   # sources carry no ELF
        d="$WORK/$(basename "$f" .rpm)"; mkdir -p "$d"
        ( cd "$d" && rpm2cpio "$f" 2>/dev/null | cpio -idm --quiet 2>/dev/null )
        n=$((n + 1))
    done
    echo "extracted: $n binary RPMs"
    ROOT="$WORK"
else
    [ -d "$PREFIX" ] || { echo "error: $PREFIX is not a directory" >&2; exit 2; }
    ROOT="$PREFIX"
fi

mapfile -t ELVES < <(find "$ROOT" -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) 2>/dev/null \
                     | while read -r f; do head -c4 "$f" 2>/dev/null | grep -q $'\x7fELF' && echo "$f"; done)
echo "elf files: ${#ELVES[@]}"
[ "${#ELVES[@]}" -gt 0 ] || { echo "error: no ELF objects found — wrong path?" >&2; exit 2; }

needed_all=$(for f in "${ELVES[@]}"; do readelf -d "$f" 2>/dev/null \
    | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p'; done | sort -u)

# Report which object carries an offending NEEDED entry, not just that one does:
# the whole point is that the outlier is a single library among hundreds.
carriers() {
    for f in "${ELVES[@]}"; do
        readelf -d "$f" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p' \
            | grep -qE "$1" && echo "    $(basename "$f")"
    done | sort -u | head -12
}

RC=0
fail() { echo "VIOLATION: $1"; RC=1; }

if [ "$LINALG" = "mkl" ]; then
    if [ "$THREADING" = "sequential" ]; then expect="libmkl_sequential"
    elif [ "$FAMILY" = "intel" ];        then expect="libmkl_intel_thread"
    else                                      expect="libmkl_gnu_thread"; fi

    layers=$(echo "$needed_all" | grep -oE 'libmkl_(sequential|gnu_thread|intel_thread)' | sort -u)
    count=$(echo "$layers" | grep -c . )
    echo "layers:    $(echo $layers) (expected exactly: $expect)"

    [ "$count" -eq 1 ] || fail "$count MKL threading layers in one flavor; mixing them is unsupported and load-order dependent"
    [ "$count" -eq 1 ] && [ "$layers" != "$expect" ] && fail "threading layer is $layers, flavor declares $expect"
    for l in $layers; do [ "$l" != "$expect" ] && { echo "  carried by:"; carriers "$l"; }; done

    if echo "$needed_all" | grep -q 'libmkl_rt'; then
        fail "libmkl_rt present. It is the single-dynamic-library model and picks its threading layer at runtime; alongside the layered libs the layer in force depends on load order"
        echo "  carried by:"; carriers 'libmkl_rt'
    fi
    if echo "$needed_all" | grep -qE 'libmkl_(scalapack|blacs)'; then
        fail "libmkl_scalapack/libmkl_blacs present — ScaLAPACK must come from the stack (doc/MKL_ABI_POLICY.md)"
        echo "  carried by:"; carriers 'libmkl_(scalapack|blacs)'
    fi
else
    # Non-MKL flavors: one OpenMP runtime and one BLAS provider.
    omp=$(echo "$needed_all" | grep -oE 'lib(gomp|omp|iomp5)\.so[.0-9]*' | sed 's/\.so.*//' | sort -u)
    ompn=$(echo "$omp" | grep -c .)
    echo "omp rt:    $(echo $omp)"
    [ "$ompn" -le 1 ] || { fail "$ompn OpenMP runtimes in one flavor; two runtimes in a process is undefined"; \
                           for l in $omp; do echo "  $l carried by:"; carriers "$l"; done; }

    blas=$(echo "$needed_all" | grep -oE 'lib(openblas|blas|flexiblas|mkl_rt)\.so[.0-9]*' | sed 's/\.so.*//' | sort -u)
    echo "blas:      $(echo $blas)"
    echo "$needed_all" | grep -q 'libmkl' && { fail "MKL linked into a non-MKL flavor"; carriers 'libmkl'; }
fi

echo
[ "$RC" -eq 0 ] && echo "PASS — $FLAVOR is self-consistent" || echo "FAIL — see violations above"
exit $RC
