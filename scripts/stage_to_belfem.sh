#!/bin/bash
# Stage one flavor's artifacts for belfem.lbl.gov signing and publication.
#
# Written against transfer contract v1.5. The contract is authoritative and lives in
# the publishing host's staging root; it cannot be read back over the upload key
# (forced write-only rsync), so revisions arrive over the AI relay.
#
# THIS SCRIPT ENDS AT "READY UPLOADED, REPORTED". It never signs, never promotes,
# never runs createrepo/reprepro, and never touches repository state. See
# doc/BUILD_EXECUTION.md §5.4 — repository mutation is permanently manual.
#
# Usage:
#   scripts/stage_to_belfem.sh --flavor <f> --column <c> [--stage DIR] [--build] [--upload]
#
#   (no --build/--upload)  select + report only; nothing is written or sent
#   --build                stage locally, write MANIFEST.txt/SHA256SUMS/READY, verify
#   --upload               additionally rsync payload then READY (requires --build)
#
# The split is deliberate: --build produces everything belfem needs to size the drop,
# so total_bytes can be sent for approval before a single byte leaves this host.

set -u -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Connection details live in an UNTRACKED local file, never in the repo. SCLS is
# published under BSD-3-Clause-LBNL: a hardcoded internal hostname and service
# account tell a reader exactly which host to aim at and as whom, which is
# reconnaissance we have no reason to ship. The repo documents the mechanism; the
# endpoint is site configuration. See publish.conf.example.
#
# Nothing secret belongs in publish.conf either — it names a key, it does not
# contain one. The private key stays in ~/.ssh and never goes near this tree.
CONF="$REPO/publish.conf"
if [ ! -f "$CONF" ]; then
    echo "error: $CONF not found." >&2
    echo "Copy publish.conf.example to publish.conf and fill in this site's values." >&2
    echo "It is git-ignored and must stay that way." >&2
    exit 2
fi
# shellcheck disable=SC1090
. "$CONF"
: "${PUBLISH_REMOTE:?publish.conf must set PUBLISH_REMOTE (user@host)}"
: "${PUBLISH_KEY:?publish.conf must set PUBLISH_KEY (path to the upload private key)}"

SSH_OPTS=(-i "$PUBLISH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes
          -o StrictHostKeyChecking=yes)
REMOTE="$PUBLISH_REMOTE"

FLAVOR=""; COLUMN=""; STAGE=""; DO_BUILD=0; DO_UPLOAD=0; USE_DROP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --flavor) FLAVOR="$2"; shift 2 ;;
        --column) COLUMN="$2"; shift 2 ;;
        --stage)  STAGE="$2";  shift 2 ;;
        --drop)   USE_DROP="$2"; shift 2 ;;
        --build)  DO_BUILD=1;  shift ;;
        --upload) DO_UPLOAD=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
# --upload without --drop would restage under a NEW timestamp, so the thing
# uploaded would not be the drop whose total_bytes the publishing host approved.
# Approval is granted against a specific DROP name; honour it.
if [ "$DO_UPLOAD" -eq 1 ] && [ -z "$USE_DROP" ]; then
    echo "error: --upload requires --drop <DROP>, naming the already-staged drop." >&2
    echo "Stage with --build first, get the size approved, then upload THAT drop." >&2
    exit 2
fi
[ -n "$FLAVOR" ] && [ -n "$COLUMN" ] || { echo "usage: $0 --flavor <f> --column <c>" >&2; exit 2; }

case "$COLUMN" in
    R9)   DISTRO=el9      ;;
    R10)  DISTRO=el10     ;;
    AMZN) DISTRO=amzn2023 ;;
    U24)  DISTRO=ubuntu   ;;
    *) echo "unknown column: $COLUMN (expected R9, R10, AMZN or U24)" >&2; exit 2 ;;
esac
[ "$DISTRO" = ubuntu ] && { echo "DEB staging not implemented; this host is RPM" >&2; exit 2; }

DROP="${USE_DROP:-${COLUMN}-${FLAVOR}-$(date -u +%Y%m%dT%H%MZ)}"
STAGE="${STAGE:-$REPO/work/staging}"
# Always absolute. The linkage gate extracts each RPM after cd'ing into a scratch
# dir, so a relative --stage silently yields "no ELF objects found" (R10, 2026-09-25).
STAGE=$(realpath -m -- "$STAGE") || { echo "error: cannot resolve --stage $STAGE" >&2; exit 2; }
DROPDIR="$STAGE/$DROP"
DIST=$(rpm --eval '%{dist}')

echo "drop:   $DROP"
echo "distro: $DISTRO"
echo "stage:  $DROPDIR"
echo

# ---------------------------------------------------------------- selection ---
# Only NEVRAs matching the current recipes ship. The RPMS tree accumulates
# superseded artifacts across campaigns, and belfem must never be asked to sign one.
# Binaries map to their source package via the SOURCERPM tag, never by name:
# subpackages (blas/cblas/lapacke from lapack, *-examples from petsc/slepc/sundials)
# share a parent SRPM and a name-based guess reports them as missing sources.

declare -a PAYLOAD_BIN=() PAYLOAD_SRC=() EXCLUDED=() ALREADY=()

recipe_nevr() {
    python3 -c "import yaml,sys;r=yaml.safe_load(open('$REPO/recipes/$1.yaml'));print(f\"{r['version']}-{r.get('release',1)}\")" 2>/dev/null
}

# The published NEVRA list comes FROM the publishing host, read out of its RPM
# headers. Membership in it decides payload vs already_published, so the decision
# rests on what the repo actually holds rather than on what this host's tracker
# believes changed. Without it every current NEVRA would be treated as new, which
# is safe but wastes upload and scarce remote free space on files that cannot be
# promoted (contract v1.2: a NEVRA already published is never promoted, because
# replacing a signed file with an unsigned one breaks clients holding cached
# metadata).
PUBLISHED_LIST="${PUBLISH_PUBLISHED_LIST:-$REPO/work/publish/published-$DISTRO.txt}"
if [ -f "$PUBLISHED_LIST" ]; then
    echo "published list: $PUBLISHED_LIST ($(grep -c . "$PUBLISHED_LIST") NEVRAs)"
else
    echo "WARNING: no published list at $PUBLISHED_LIST — every current NEVRA will" >&2
    echo "         be treated as new. Ask the publishing host for its NEVRA list." >&2
    PUBLISHED_LIST=/dev/null
fi

is_published() { grep -qxF "$1" "$PUBLISHED_LIST" 2>/dev/null; }
# NOTE: do NOT write the arch as ${2:-%{ARCH}}. The `}` inside %{ARCH} closes the
# parameter expansion early, so with $2 set the format ends up as "...src}", which
# rpm rejects and returns EMPTY. With $2 unset it happens to work, which is how the
# bug hides: binaries resolve correctly while every source package yields an empty
# NEVRA, matches nothing in the published list, and is shipped as if it were new.
nevra() {
    local arch_fmt='%{ARCH}'
    [ -n "${2:-}" ] && arch_fmt="$2"
    rpm -qp --qf "%{NAME}-%|EPOCH?{%{EPOCH}}:{0}|:%{VERSION}-%{RELEASE}.${arch_fmt}" "$1" 2>/dev/null
}

# NEVER_SHIP: packages that must not leave this host as binaries, whatever else is
# true of them. Each carries its OWN governing reason, because the next entry will
# not be excluded for suitesparse's reason and a shared string would quietly
# misattribute it.
#
# The reason states the rule first and the mechanism second. "no SRPM in the tree"
# and "include_flavors: []" are consequences, not the rule: opt a package in via
# extra_packages: for one local build and an SRPM appears, but it must still never
# ship. The manifest travels with packages the publishing host signs, so it is the
# durable record of why something was withheld and must name the governing reason.
declare -A NEVER_SHIP_REASON=(
    [suitesparse]="licence — GPL-2 linkable, not shipped as a binary (doc/LICENSE_POLICY.md); recipe carries include_flavors: [] so it is never built by default"
)

while read -r n v r a; do
    [ -z "${n:-}" ] && continue
    short="${n#scls-${FLAVOR}-}"
    [ "$short" = "$n" ] && short="${n#scls-}"        # the bare meta-package
    # Licence exclusion first: it must hold regardless of whether an artifact or an
    # SRPM exists, so it is checked before anything that could `continue` past it.
    if [ -n "${NEVER_SHIP_REASON[$short]:-}" ]; then
        EXCLUDED+=("$n-$v-$r.$a  reason: ${NEVER_SHIP_REASON[$short]}")
        continue
    fi

    f="$REPO/rpmbuild/RPMS/$a/$n-$v-$r.$a.rpm"
    if [ ! -f "$f" ]; then
        # Installed on this host but no local artifact — pruned, or built on another
        # host. Never skip silently: an unreported omission reaches belfem as a drop
        # that is quietly missing a package, with nothing to say why.
        EXCLUDED+=("$n-$v-$r.$a  reason: installed but no binary RPM in rpmbuild/RPMS/$a")
        continue
    fi

    bin_nevra=$(nevra "$f")
    src=$(rpm -qp --qf '%{SOURCERPM}' "$f" 2>/dev/null)
    srcpath="$REPO/rpmbuild/SRPMS/$src"

    if is_published "$bin_nevra"; then
        # Already in the repo. Report it with digests so the publishing host can
        # confirm this builder is byte-identical, but never ship the bytes.
        d=$(rpm -qp --qf '%{SHA256HEADER} %{PAYLOADDIGEST}' "$f" 2>/dev/null)
        ALREADY+=("$bin_nevra  SHA256HEADER=${d% *} PAYLOADDIGEST=${d#* }")
    elif [ -n "$src" ] && [ -f "$srcpath" ]; then
        PAYLOAD_BIN+=("$f")
    else
        # A binary with no shippable source cannot go out: doc/LICENSE_POLICY.md makes
        # the SRPM how SCLS meets its source-availability obligation.
        EXCLUDED+=("$bin_nevra  reason: no SRPM in tree for SOURCERPM ${src:-unknown}")
        continue
    fi

    # The source package is decided on its own merits: a binary can be new while
    # its SRPM is already published (a rebuild at a new release from unchanged
    # sources), and shipping a duplicate SRPM would be refused and waste space.
    if [ -n "$src" ] && [ -f "$srcpath" ]; then
        src_nevra=$(nevra "$srcpath" "src")
        if is_published "$src_nevra"; then
            d=$(rpm -qp --qf '%{SHA256HEADER} %{PAYLOADDIGEST}' "$srcpath" 2>/dev/null)
            case " ${ALREADY[*]:-} " in *"$src_nevra "*) ;;
                *) ALREADY+=("$src_nevra  SHA256HEADER=${d% *} PAYLOADDIGEST=${d#* }") ;; esac
        else
            case " ${PAYLOAD_SRC[*]:-} " in *" $srcpath "*) ;;
                *) PAYLOAD_SRC+=("$srcpath") ;; esac
        fi
    fi
done < <(rpm -qa --qf '%{NAME} %{VERSION} %{RELEASE} %{ARCH}\n' "scls-$FLAVOR-*" "scls-$FLAVOR" 2>/dev/null | sort -u)

# Drop anything whose installed NEVRA no longer matches its recipe.
declare -a KEEP=()
for f in "${PAYLOAD_BIN[@]}"; do
    base=$(basename "$f"); short="${base#scls-${FLAVOR}-}"; short="${short%%-[0-9]*}"
    if [ -f "$REPO/recipes/$short.yaml" ]; then
        want=$(recipe_nevr "$short")
        have=$(rpm -qp --qf '%{VERSION}-%{RELEASE}' "$f" 2>/dev/null | sed "s/${DIST}\$//")
        [ -n "$want" ] && [ "$want" != "$have" ] && {
            EXCLUDED+=("$base  reason: installed $have does not match recipe $want"); continue; }
    fi
    KEEP+=("$f")
done
PAYLOAD_BIN=("${KEEP[@]}")

TOTAL=0; COUNT=0
for f in "${PAYLOAD_BIN[@]}" "${PAYLOAD_SRC[@]}"; do
    TOTAL=$((TOTAL + $(stat -c %s "$f"))); COUNT=$((COUNT + 1))
done

echo "payload:           ${#PAYLOAD_BIN[@]} binaries + ${#PAYLOAD_SRC[@]} srpms = $COUNT files"
echo "total_bytes:       $TOTAL"
echo "excluded:          ${#EXCLUDED[@]}"
echo "already_published: ${#ALREADY[@]}"
echo
if [ "$DO_BUILD" -eq 0 ] && [ "$DO_UPLOAD" -eq 0 ]; then
    echo "(selection only — pass --build to stage)"; exit 0
fi

# Uploading a previously staged drop: do NOT restage. Re-running the selection
# could produce different bytes than the ones whose size was approved, and a
# drop is immutable once READY is sent.
if [ "$DO_BUILD" -eq 0 ]; then
    [ -d "$DROPDIR" ] || { echo "error: $DROPDIR does not exist — stage it first." >&2; exit 2; }
    [ -f "$STAGE/READY" ] || { echo "error: $STAGE/READY missing — stage it first." >&2; exit 2; }
    echo "re-using staged drop (no restage)"
    ( cd "$DROPDIR" && sha256sum -c --quiet SHA256SUMS ) \
        || { echo "STAGED DROP FAILED ITS OWN SHA256SUMS — refusing to upload" >&2; exit 1; }
    READY_SHA=$(sha256sum "$DROPDIR/SHA256SUMS" | cut -d' ' -f1)
    [ "$READY_SHA" = "$(cat "$STAGE/READY")" ] \
        || { echo "READY does not match SHA256SUMS — refusing to upload" >&2; exit 1; }
    COUNT=$(grep -c . "$DROPDIR/SHA256SUMS")
    TOTAL=$(awk '/^total_bytes:/{print $2}' "$DROPDIR/MANIFEST.txt")
    echo "verified: file_count=$COUNT total_bytes=$TOTAL sha256(SHA256SUMS)=$READY_SHA"
fi

# ------------------------------------------------------------------ staging ---
if [ "$DO_BUILD" -eq 1 ]; then
rm -rf "$DROPDIR"
mkdir -p "$DROPDIR/$DISTRO/x86_64" "$DROPDIR/$DISTRO/source"
# noarch goes in x86_64/ — contract §2. There is no noarch/ directory and none will
# be added; the live repo keeps noarch in el9/x86_64/Packages and update_repo only
# handles x86_64 and source.
for f in "${PAYLOAD_BIN[@]}"; do ln "$f" "$DROPDIR/$DISTRO/x86_64/" 2>/dev/null || cp "$f" "$DROPDIR/$DISTRO/x86_64/"; done
for f in "${PAYLOAD_SRC[@]}"; do ln "$f" "$DROPDIR/$DISTRO/source/" 2>/dev/null || cp "$f" "$DROPDIR/$DISTRO/source/"; done

{
    echo "drop: $DROP"
    # hostname -f is "localhost" on these VMs, which tells the publishing host
    # nothing about which builder produced the drop. publish.conf may override.
    echo "host: ${PUBLISH_HOST_LABEL:-$(hostname -f 2>/dev/null || hostname)}"
    echo "column: $COLUMN"
    echo "flavor: $FLAVOR"
    echo "distro: $DISTRO"
    echo "git_head: $(git -C "$REPO" rev-parse HEAD)"
    echo "created_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "file_count: $COUNT"
    echo "total_bytes: $TOTAL"
    echo
    # Binaries carry their real %{ARCH}; source packages are emitted as .src
    # EXPLICITLY. rpm reports the BUILD arch for a .src.rpm (x86_64, not src), so
    # querying %{ARCH} makes a binary and its source render as byte-identical
    # lines and the manifest silently loses the distinction — 76 lines, 43 of
    # them duplicates, with nothing to say which entry is the source.
    {
        for f in "${PAYLOAD_BIN[@]}"; do
            rpm -qp --qf '%{NAME}-%|EPOCH?{%{EPOCH}}:{0}|:%{VERSION}-%{RELEASE}.%{ARCH}\n' "$f" 2>/dev/null
        done
        for f in "${PAYLOAD_SRC[@]}"; do
            rpm -qp --qf '%{NAME}-%|EPOCH?{%{EPOCH}}:{0}|:%{VERSION}-%{RELEASE}.src\n' "$f" 2>/dev/null
        done
    } | sort
    if [ "${#EXCLUDED[@]}" -gt 0 ]; then
        echo; echo "excluded:"; printf '%s\n' "${EXCLUDED[@]}"
    fi
    if [ "${#ALREADY[@]}" -gt 0 ]; then
        echo; echo "already_published:"; printf '%s\n' "${ALREADY[@]}"
    fi
} > "$DROPDIR/MANIFEST.txt"

( cd "$DROPDIR" && find "$DISTRO" -type f 2>/dev/null | sort | xargs sha256sum ) > "$DROPDIR/SHA256SUMS"
( cd "$DROPDIR" && sha256sum -c --quiet SHA256SUMS ) || { echo "LOCAL SHA256SUMS VERIFY FAILED" >&2; exit 1; }
echo "local sha256sum -c: OK"

# Math/threading uniformity gate. This runs BEFORE READY exists, so a violation
# leaves a drop that physically cannot be uploaded (--upload refuses without a
# matching READY) rather than a warning someone scrolls past.
#
# It exists because on 2026-09-25 belfem rejected R9-mkl-20260925T0946Z over a
# defect that every check up to that point had passed: libscalapack linked
# libmkl_sequential while the flavor's other 256 MKL references linked
# libmkl_gnu_thread, putting two MKL threading layers in one process. Nothing
# here could see it — AutoReqProv: no keeps DT_NEEDED out of RPM metadata, and
# the per-package checks all passed because each object is well-formed alone and
# only wrong in company. The rule is per-flavor, so the gate has to be too.
echo "checking math/threading uniformity..."
if ! "$REPO/scripts/check_mkl_linkage.sh" --flavor "$FLAVOR" --dir "$DROPDIR/$DISTRO/x86_64"; then
    echo >&2
    echo "LINKAGE GATE FAILED — READY not written, so this drop cannot be uploaded." >&2
    echo "Fix the recipes, rebuild the offending packages, and stage a new drop." >&2
    exit 1
fi
echo

# READY is built OUTSIDE the drop directory so the payload rsync cannot carry it up
# by accident. Sending READY early would mark an incomplete drop consumable.
READY_SHA=$(sha256sum "$DROPDIR/SHA256SUMS" | cut -d' ' -f1)
echo "$READY_SHA" > "$STAGE/READY"
echo "sha256(SHA256SUMS): $READY_SHA"
echo
fi   # end staging

[ "$DO_UPLOAD" -eq 1 ] || { echo "(staged only — send total_bytes=$TOTAL to belfem and await OK)"; exit 0; }

# ------------------------------------------------------------------ upload ----
# Flags are contract v1.5 §B verbatim. -p is NOT optional: without it rsync silently
# ignores --chmod and applies the source mode masked by the remote umask, so the drop
# arrives 2755/644 and cannot be moved or deleted by group scls without root.
# Forbidden here: --inplace, --partial, --append, --delete*, --remove-source-files,
# -a (would try to set owner/group), -z (RPMs are already compressed).
echo "uploading payload..."
rsync -rt -p --chmod=D2775,F664 -e "ssh ${SSH_OPTS[*]}" "$DROPDIR/" "$REMOTE:$DROP/"
rc=$?
if [ $rc -ne 0 ]; then
    echo "PAYLOAD UPLOAD FAILED rc=$rc — READY NOT SENT." >&2
    echo "Retrying the same DROP is safe while READY is unsent. rc 23/24 = partial." >&2
    echo "rc 12 = tried to read/list, or a path contained '..'. rc 255 host key = STOP." >&2
    exit $rc
fi
echo "payload uploaded rc=0"

echo "uploading READY..."
rsync -rt -p --chmod=D2775,F664 -e "ssh ${SSH_OPTS[*]}" "$STAGE/READY" "$REMOTE:$DROP/READY"
rc=$?
[ $rc -eq 0 ] || { echo "READY UPLOAD FAILED rc=$rc" >&2; exit $rc; }

echo
echo "=== report this to belfem over the relay ==="
echo "drop: $DROP"
echo "file_count: $COUNT"
echo "total_bytes: $TOTAL"
echo "sha256(SHA256SUMS): $READY_SHA"
echo "excluded: ${#EXCLUDED[@]}   already_published: ${#ALREADY[@]}"
echo
echo "Drop is now immutable. A correction needs a new timestamp."
echo "This host cannot list, verify or delete anything on belfem — that is belfem's job."
