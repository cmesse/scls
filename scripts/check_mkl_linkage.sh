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
#   scripts/check_mkl_linkage.sh --flavor mkl --dir work/staging/<DROP>/ubuntu/pkgs
#
# Exit 0 = uniform, 1 = violation, 2 = usage/environment error.

set -u -o pipefail
# Never test a match with `cmd | grep -q` here: grep -q exits at the first match,
# the writer can then die of SIGPIPE, and pipefail turns the match into a miss
# (load-dependent false PASS/FAIL, found on U26 2026-10-01). Use here-strings.

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
[ -n "$FLAVOR" ] || { echo "usage: $0 --flavor <f> [--prefix DIR | --dir PKGDIR]" >&2; exit 2; }
[ -n "$PREFIX" ] || [ -n "$DIR" ] || { echo "error: need --prefix or --dir" >&2; exit 2; }
# Resolve to absolute paths: RPMs are extracted after cd'ing into a scratch dir,
# where a relative --dir no longer points anywhere.
[ -n "$DIR" ] && DIR=$(realpath -e -- "$DIR" 2>/dev/null || echo "$DIR")
[ -n "$PREFIX" ] && PREFIX=$(realpath -e -- "$PREFIX" 2>/dev/null || echo "$PREFIX")
command -v readelf >/dev/null || { echo "error: readelf not found (binutils)" >&2; exit 2; }

# The expected model comes from the flavor file, never from a hardcoded list, so
# a new flavor is covered the day it is added rather than silently unchecked.
read -r LINALG THREADING FAMILY INTERFACE < <(python3 - "$REPO" "$FLAVOR" <<'PY'
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
# The family rule lives in math_common.compiler_family; reuse it rather than re-derive it.
sys.path.insert(0, str(pathlib.Path(repo) / "python"))
from math_common import compiler_family
fam = "intel" if compiler_family(f) == "intel" else "gnu"
print(math.get("linalg", "reference"), math.get("threading", "openmp"), fam,
      math.get("interface", "lp64"))
PY
) || { echo "error: could not read flavors/$FLAVOR.yaml" >&2; exit 2; }

echo "flavor:    $FLAVOR (linalg=$LINALG threading=$THREADING toolchain=$FAMILY)"

# Collect the ELF files to inspect. Packages (.rpm or .deb) are extracted to a
# scratch dir: reading DT_NEEDED needs the real object, and grepping the
# compressed payload for library names gives false hits from .cmake files and
# docs that merely mention them.
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
        # A partial extract would hide objects from the gate, so a failure stops it.
        ( cd "$d" && rpm2cpio "$f" 2>/dev/null | cpio -idm --quiet 2>/dev/null ) \
            || { echo "error: could not extract $(basename "$f")" >&2; exit 2; }
        n=$((n + 1))
    done
    for f in "$DIR"/*.deb; do
        [ -e "$f" ] || continue
        d="$WORK/$(basename "$f" .deb)"; mkdir -p "$d"
        dpkg-deb -x "$f" "$d" 2>/dev/null \
            || { echo "error: could not extract $(basename "$f")" >&2; exit 2; }
        n=$((n + 1))
    done
    echo "extracted: $n binary packages"
    ROOT="$WORK"
else
    [ -d "$PREFIX" ] || { echo "error: $PREFIX is not a directory" >&2; exit 2; }
    ROOT="$PREFIX"
fi

mapfile -t ELVES < <(find "$ROOT" -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) 2>/dev/null \
                     | while read -r f; do [ "$(head -c4 "$f" 2>/dev/null | tr -d '\0')" = $'\x7fELF' ] && echo "$f"; done)
echo "elf files: ${#ELVES[@]}"
[ "${#ELVES[@]}" -gt 0 ] || { echo "error: no ELF objects found — wrong path?" >&2; exit 2; }

needed_all=$(for f in "${ELVES[@]}"; do readelf -d "$f" 2>/dev/null \
    | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p'; done | sort -u)

# Report which object carries an offending NEEDED entry, not just that one does:
# the whole point is that the outlier is a single library among hundreds.
carriers() {
    for f in "${ELVES[@]}"; do
        n=$(readelf -d "$f" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p')
        grep -qE "$1" <<< "$n" && echo "    $(basename "$f")"
    done | sort -u | sed -n '1,12p'   # sed reads to EOF: no SIGPIPE into sort
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

    # Per-object rule (belfem verifier, 2026-09-29): every object that NEEDs any
    # libmkl_* must NEED the interface, the threading layer, core and the OpenMP
    # runtime DIRECTLY, as el9 links them. Ubuntu's default --as-needed left six
    # mkl objects with only libmkl_gf_lp64 and the rest arriving transitively.
    # The flavor-wide set above cannot see that: it was uniform all along.
    iface="libmkl_$([ "$FAMILY" = intel ] && echo intel || echo gf)_${INTERFACE:-lp64}"
    want="$iface $expect libmkl_core"
    [ "$expect" != libmkl_sequential ] && want="$want $([ "$FAMILY" = intel ] && echo libiomp5 || echo libgomp)"
    partial=0
    for f in "${ELVES[@]}"; do
        n=$(readelf -d "$f" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p')
        grep -q '^libmkl_' <<< "$n" || continue
        lack=""
        for w in $want; do grep -q "^$w\.so" <<< "$n" || lack="$lack $w"; done
        if [ -n "$lack" ]; then
            [ "$partial" -eq 0 ] && echo "  objects missing a direct MKL NEEDED:"
            echo "    $(basename "$f"): lacks$lack"
            partial=$((partial + 1))
        fi
    done
    [ "$partial" -eq 0 ] || fail "$partial object(s) NEED libmkl_* without all of: $want"

    if grep -q 'libmkl_rt' <<< "$needed_all"; then
        fail "libmkl_rt present. It is the single-dynamic-library model and picks its threading layer at runtime; alongside the layered libs the layer in force depends on load order"
        echo "  carried by:"; carriers 'libmkl_rt'
    fi
    if grep -qE 'libmkl_(scalapack|blacs)' <<< "$needed_all"; then
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
    grep -q 'libmkl' <<< "$needed_all" && { fail "MKL linked into a non-MKL flavor"; carriers 'libmkl'; }
fi

echo
[ "$RC" -eq 0 ] && echo "PASS — $FLAVOR is self-consistent" || echo "FAIL — see violations above"
exit $RC
