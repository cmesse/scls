#!/usr/bin/env bash
# Negative and positive tests for scripts/hsl/assemble_sources.sh, run against
# SYNTHETIC tarballs built here from dummy text. Contains no HSL content and
# needs no HSL tarball. SCLS, BSD-3-Clause-LBNL.
#
# Usage: test_assemble.sh            (uses a fresh mktemp dir outside the repo)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASM="$HERE/../assemble_sources.sh"
T="$(mktemp -d "${TMPDIR:-/tmp}/scls-hsl-test-XXXXXX")"
trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1" >&2; }
bad()  { fail=$((fail+1)); echo "  FAIL $1" >&2; }
# ok/bad write to stderr so expect_ok can return the target dir on stdout.

# --- synthetic Coin-HSL tree ---------------------------------------------------
DEPS_F77=$'      SUBROUTINE DUMMYA(X)\n      X = 1\n      END\n      SUBROUTINE DUMMYB(X)\n      X = 2\n      END\n'
DEPS_F90=$'module mod_alpha\n  integer :: a = 1\nend module mod_alpha\nmodule mod_beta\n  integer :: b = 2\nend module mod_beta\n'
mk_coin() {   # $1 dir
    local d="$1/coinhsl-2024.05.15"
    mkdir -p "$d/common" "$d/hsl_ma77/C"
    printf "project('coinhsl', 'fortran', 'c',\n  version : '2024.05.15')\n" > "$d/meson.build"
    printf '2024-05-15\n   * HSL_MA86 v1.7.3 -> v1.7.4\n   * HSL_MA97 v2.8.0 -> v2.8.1\n2023-11-17\n   * HSL_MA77 v6.3.0 -> v6.4.0\n' > "$d/ChangeLog"
    echo "dummy coin license" > "$d/LICENCE"
    printf '%s' "$DEPS_F77" > "$d/common/deps.f"
    printf '%s' "$DEPS_F90" > "$d/common/deps90.f90"
    for p in d s; do
        echo "module hsl_ma77_$p ! coin body" > "$d/hsl_ma77/hsl_ma77$p.f90"
        echo "module hsl_ma77_${p}_ciface" > "$d/hsl_ma77/C/hsl_ma77${p}_ciface.f90"
        echo "/* header $p */" > "$d/hsl_ma77/C/hsl_ma77$p.h"
    done
    tar -czf "$1/coinhsl-2024.05.15.tar.gz" -C "$1" coinhsl-2024.05.15
    rm -rf "$d"
}
mk_ma77() {   # $1 dir, $2 version, $3 variant (good|extra|hdr|dep)
    local d="$1/hsl_ma77-$2"
    mkdir -p "$d/src" "$d/include"
    echo "dummy standalone license" > "$d/LICENCE"
    for p in d s; do
        echo "module hsl_ma77_$p ! NEW body" > "$d/src/hsl_ma77$p.f90"
        echo "module hsl_ma77_${p}_ciface" > "$d/src/hsl_ma77${p}_ciface.f90"
        echo "/* header $p */" > "$d/include/hsl_ma77$p.h"
    done
    printf '%s' "$DEPS_F77" > "$d/src/common.f"
    printf 'module mod_beta\n  integer :: b = 2\nend module mod_beta\n' > "$d/src/common90.f90"
    printf 'module mod_alpha\n  integer :: a = 1   \nend module mod_alpha\n' > "$d/src/ddeps90.f90"   # trailing blanks: must still match
    : > "$d/src/sdeps90.f90"
    : > "$d/src/Makefile.am"; : > "$d/src/Makefile.in"
    case "$3" in
        extra) echo "module surprise" > "$d/src/hsl_ma77_extra.f90" ;;
        hdr)   echo "/* changed header d */" > "$d/include/hsl_ma77d.h" ;;
        dep)   printf 'module mod_alpha\n  integer :: a = 99\nend module mod_alpha\n' > "$d/src/ddeps90.f90" ;;
    esac
    tar -czf "$1/hsl_ma77-$2.tar.gz" -C "$1" "hsl_ma77-$2"
    rm -rf "$d"
}
expect_fail() {   # $1 label, $2 grep pattern, $3 srcdir
    local out
    if out="$("$ASM" "$3" "$T/out-$RANDOM" 2>&1)"; then bad "$1: expected failure, got success"; return; fi
    if echo "$out" | grep -q -E "$2"; then ok "$1"; else bad "$1: wrong message: $(echo "$out" | tail -1)"; fi
}
TGT=""
expect_ok() {   # $1 label, $2 grep pattern, $3 srcdir -> sets TGT (not a subshell, so
                # ok/bad counters survive)
    local out; TGT="$T/out-$RANDOM"
    if ! out="$("$ASM" "$3" "$TGT" 2>&1)"; then bad "$1: $(echo "$out" | tail -1)"; TGT=""; return 0; fi
    if echo "$out" | grep -q -E "$2"; then ok "$1"; else bad "$1: missing '$2'"; fi
}

echo "assemble_sources.sh tests:"
# 1. happy path: newer version replaces, LICENCES and PROVENANCE written
s="$T/s1"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.5.0 good
expect_ok "newer override applied" 'HSL_MA77: 6.4.0 -> 6.5.0' "$s"; tgt="$TGT"
if [ -n "${tgt:-}" ]; then
    grep -q 'NEW body' "$tgt/src/hsl_ma77/hsl_ma77d.f90" && ok "replacement file in tree" || bad "replacement not copied"
    grep -q 'coin body' "$tgt/originals/hsl_ma77/hsl_ma77d.f90" && ok "original preserved" || bad "original missing"
    [ -f "$tgt/LICENCES/LICENCE.coinhsl-2024.05.15" ] && [ -f "$tgt/LICENCES/LICENCE.hsl_ma77-6.5.0" ] && ok "both licenses" || bad "licenses"
    grep -q 'override: HSL_MA77 6.4.0 -> 6.5.0' "$tgt/PROVENANCE.txt" && ok "provenance line" || bad "provenance"
    cmp -s "$tgt/src/common/deps90.f90" <(printf '%s' "$DEPS_F90") && ok "deps never copied" || bad "deps overwritten"
fi
# 2. equal version skipped
s="$T/s2"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.4.0 good
expect_ok "equal version skipped" 'not newer' "$s"
# 3. older version skipped
s="$T/s3"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.3.9 good
expect_ok "older version skipped" 'not newer' "$s"
# 4. numeric compare: 6.10.0 > 6.4.0
s="$T/s4"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.10.0 good
expect_ok "numeric version compare (6.10.0 > 6.4.0)" '6.4.0 -> 6.10.0' "$s"
# 5. unclassified file stops
s="$T/s5"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.5.0 extra
expect_fail "unclassified file stops" 'unclassified file src/hsl_ma77_extra.f90' "$s"
# 6. header mismatch stops
s="$T/s6"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.5.0 hdr
expect_fail "interface header mismatch stops" 'interface change' "$s"
# 7. dependency module mismatch stops
s="$T/s7"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.5.0 dep
expect_fail "dependency module mismatch stops" 'unit mod:mod_alpha differs' "$s"
# 8. two coinhsl tarballs
s="$T/s8"; mkdir -p "$s"; mk_coin "$s"; cp "$s/coinhsl-2024.05.15.tar.gz" "$s/coinhsl-2024.05.16.tar.gz"
expect_fail "two base tarballs rejected" 'more than one tarball' "$s"
# 9. unsafe member path
s="$T/s9"; mkdir -p "$s/evil/coinhsl-2024.05.15" "$s/evil/outside"; echo x > "$s/evil/outside/f"
( cd "$s/evil" && tar -czf "$s/coinhsl-2024.05.15.tar.gz" coinhsl-2024.05.15 ../evil/outside/f 2>/dev/null ) || true
expect_fail "unsafe tar member rejected" 'unsafe member path|not a single top-level' "$s"
# 10. ChangeLog disagrees with pin
s="$T/s10"; mkdir -p "$s"; mk_coin "$s"
d="$s/x"; mkdir -p "$d"; tar -xzf "$s/coinhsl-2024.05.15.tar.gz" -C "$d"
sed -i.bak 's/HSL_MA77 v6.3.0 -> v6.4.0/HSL_MA77 v6.3.0 -> v6.4.1/' "$d/coinhsl-2024.05.15/ChangeLog" && rm -f "$d/coinhsl-2024.05.15/ChangeLog.bak"
tar -czf "$s/coinhsl-2024.05.15.tar.gz" -C "$d" coinhsl-2024.05.15; rm -rf "$d"
expect_fail "ChangeLog/pin disagreement stops" "ChangeLog says '6.4.1', pin says 6.4.0" "$s"
# 11. unpinned Coin-HSL release stops
s="$T/s11"; mkdir -p "$s"; mk_coin "$s"
d="$s/x"; mkdir -p "$d"; tar -xzf "$s/coinhsl-2024.05.15.tar.gz" -C "$d"
sed -i.bak "s/2024.05.15'/2030.01.01'/" "$d/coinhsl-2024.05.15/meson.build" && rm -f "$d/coinhsl-2024.05.15/meson.build.bak"
tar -czf "$s/coinhsl-2024.05.15.tar.gz" -C "$d" coinhsl-2024.05.15; rm -rf "$d"
expect_fail "unpinned Coin-HSL release stops" 'has no pin for' "$s"
# 12a. '..' member (GNU tar refuses to create one; python tarfile does not)
s="$T/s12a"; mkdir -p "$s"; mk_coin "$s"
python3 - "$s/coinhsl-2024.05.15.tar.gz" <<'PY'
import sys, tarfile, io
p = sys.argv[1]
with tarfile.open(p, 'r:gz') as src:
    members = [(m, src.extractfile(m).read() if m.isfile() else None) for m in src.getmembers()]
with tarfile.open(p, 'w:gz') as dst:
    for m, data in members:
        dst.addfile(m, io.BytesIO(data) if data is not None else None)
    evil = tarfile.TarInfo('coinhsl-2024.05.15/../../escaped.txt'); evil.size = 1
    dst.addfile(evil, io.BytesIO(b'x'))
PY
expect_fail "'..' member rejected (no pipefail race)" 'unsafe member path' "$s"
# 12b. symlink member refused
s="$T/s12b"; mkdir -p "$s"; mk_coin "$s"
python3 - "$s/coinhsl-2024.05.15.tar.gz" <<'PY'
import sys, tarfile, io
p = sys.argv[1]
with tarfile.open(p, 'r:gz') as src:
    members = [(m, src.extractfile(m).read() if m.isfile() else None) for m in src.getmembers()]
with tarfile.open(p, 'w:gz') as dst:
    for m, data in members:
        dst.addfile(m, io.BytesIO(data) if data is not None else None)
    ln = tarfile.TarInfo('coinhsl-2024.05.15/common/link.f'); ln.type = tarfile.SYMTYPE; ln.linkname = '../../outside.f'
    dst.addfile(ln)
PY
expect_fail "symlink member refused" 'link member pointing outside|contains symlinks' "$s"
# 12b2. hardlink to a target outside the archive, with a blank in the target
s="$T/s12b2"; mkdir -p "$s"; mk_coin "$s"
python3 - "$s/coinhsl-2024.05.15.tar.gz" <<'PY'
import sys, tarfile, io
p = sys.argv[1]
with tarfile.open(p, 'r:gz') as src:
    members = [(m, src.extractfile(m).read() if m.isfile() else None) for m in src.getmembers()]
with tarfile.open(p, 'w:gz') as dst:
    for m, data in members:
        dst.addfile(m, io.BytesIO(data) if data is not None else None)
    ln = tarfile.TarInfo('coinhsl-2024.05.15/common/hard.f'); ln.type = tarfile.LNKTYPE; ln.linkname = '../out side.f'
    dst.addfile(ln)
PY
expect_fail "outside hardlink with blank in target refused" 'link member pointing outside' "$s"
# 12c. dependency file in a form the unit splitter does not parse must stop, not pass
s="$T/s12c"; mkdir -p "$s"; mk_coin "$s"; mk_ma77 "$s" 6.5.0 good
d="$s/x"; mkdir -p "$d"; tar -xzf "$s/hsl_ma77-6.5.0.tar.gz" -C "$d"
printf '      SUBROUTINE DUMMYA(X)\n      X = 1\n      END SUBROUTINE DUMMYA\n' > "$d/hsl_ma77-6.5.0/src/common.f"
tar -czf "$s/hsl_ma77-6.5.0.tar.gz" -C "$d" hsl_ma77-6.5.0; rm -rf "$d"
expect_fail "unparsed F77 unit form stops (coverage)" 'unit headers but only|no Fortran units recognised' "$s"
# 12. target inside the repo refused
s="$T/s12"; mkdir -p "$s"; mk_coin "$s"
if out="$("$ASM" "$s" "$HERE/../../../tmp/hsl-test-target-$RANDOM" 2>&1)"; then bad "in-repo target accepted"; else
    echo "$out" | grep -q 'inside the SCLS work tree' && ok "in-repo target refused" || bad "in-repo target: wrong message"; fi

echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
