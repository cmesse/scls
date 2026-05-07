#!/usr/bin/env python3
"""Repackage already-built scls-<flavor>-* RPMs and DEBs to inject a hard
ordering dependency on scls-<flavor>-environment, without recompiling.

Why this exists
---------------
The environment package owns the Linux From Scratch `lib -> lib64` symlink
under each flavor's prefix. If dnf or dpkg sequences any other scls-* package
before environment in a transaction, that package will create %{prefix}/lib
as a real directory (because no symlink exists yet), and environment then
fails to install with "File from package already exists as a directory in
system" (RPM) or the equivalent on the dpkg side.

The long-term fix is to have every non-environment package declare
`Requires(pre): scls-<flavor>-environment` on RPM and
`Pre-Depends: scls-<flavor>-environment` on DEB, so package managers are
forced to unpack environment first. New builds get this automatically from
rpm_builder/deb_builder, but the binary artifacts already produced from
prior builds carry the old metadata. Recompiling everything is ~1 week of
build time on a stack this big, so this script rewrites the metadata of
existing artifacts in place: payload and scriptlets are preserved, only
the dependency list and Release/Version are bumped.

Usage
-----
    tools/repackage_add_environment_dep.py rpm \\
        --input rpmbuild/RPMS \\
        --output patched/RPMS

    tools/repackage_add_environment_dep.py deb \\
        --input work/pkgs \\
        --output patched/debs

Requires `rpmrebuild` (dnf install rpmrebuild from EPEL) for RPM mode.
DEB mode only needs `dpkg-deb`, already present on Debian-family hosts.

After repackaging, rebuild the repo metadata (createrepo_c for RPM,
dpkg-scanpackages or apt-ftparchive for DEB) and re-sign the repo so the
new artifacts are picked up.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# -----------------------------------------------------------------------
# Common helpers
# -----------------------------------------------------------------------

def parse_scls_name(pkg_name: str) -> tuple[str | None, str | None]:
    """Split a Debian/RPM package name like scls-gcc-cmake into (flavor, base).

    Returns (None, None) for non-flavored scls-* packages (scls-release) or
    anything that doesn't match the scls-<flavor>(-<base>)? shape.

    Edge cases:
      scls-gcc-environment        → ('gcc', 'environment')
      scls-gcc-mkl-cuda-cmake     → ('gcc-mkl-cuda', 'cmake')   (multi-word flavor)
      scls-gcc                    → ('gcc', None)               (flavor meta-package)
      scls-release                → (None, None)                (repo config, skip)

    The multi-word flavor case is handled by checking each candidate split
    against the on-disk flavors/ directory.
    """
    if not pkg_name.startswith('scls-'):
        return (None, None)
    rest = pkg_name[len('scls-'):]
    # scls-release is a repo-config package, not flavor-scoped.
    if rest == 'release':
        return (None, None)

    flavors_dir = Path(__file__).resolve().parent.parent / 'flavors'
    known_flavors: set[str] = set()
    if flavors_dir.is_dir():
        known_flavors = {p.stem for p in flavors_dir.glob('*.yaml')}

    # Try the longest flavor prefix first so multi-segment flavor names
    # like gcc-mkl-cuda are matched before their gcc/gcc-mkl prefixes.
    for fl in sorted(known_flavors, key=len, reverse=True):
        if rest == fl:
            return (fl, None)
        if rest.startswith(fl + '-'):
            return (fl, rest[len(fl) + 1:])

    # Fallback: split on first '-'. Only used if flavors/ is unreadable.
    parts = rest.split('-', 1)
    if len(parts) == 1:
        return (parts[0], None)
    return (parts[0], parts[1])


# -----------------------------------------------------------------------
# RPM mode
# -----------------------------------------------------------------------

def _rpm_query(rpm_path: Path, fmt: str) -> str:
    return subprocess.check_output(
        ['rpm', '-qp', '--qf', fmt, str(rpm_path)],
        stderr=subprocess.DEVNULL,
    ).decode().strip()


def repackage_rpm(rpm_path: Path, output_dir: Path,
                  release_suffix: str) -> Path | None:
    """Rewrite one RPM's metadata to add Requires(pre)/Requires on env.

    Skips environment itself, scls-release, and any package whose name
    does not match the scls-<flavor>-... shape.
    """
    name = _rpm_query(rpm_path, '%{NAME}')
    version = _rpm_query(rpm_path, '%{VERSION}')
    release = _rpm_query(rpm_path, '%{RELEASE}')
    arch = _rpm_query(rpm_path, '%{ARCH}')

    flavor, base = parse_scls_name(name)
    if flavor is None:
        print(f"  SKIP  {rpm_path.name}: not a flavored scls-* package")
        return None
    if base == 'environment':
        print(f"  SKIP  {rpm_path.name}: this IS the environment package")
        return None

    env_pkg = f"scls-{flavor}-environment"
    new_release = release + release_suffix

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)

        # Filter scripts that rpmrebuild calls to mutate sections of the spec.
        # Each filter reads the original section on stdin and writes the
        # replacement on stdout. Keep them idempotent so re-running the tool
        # over already-patched RPMs does not stack up duplicate Requires.
        req_filter = tdp / 'req_filter.sh'
        # env_pkg is plain alphanumerics + '-' so it needs no regex escaping.
        # grep -E: parens are special; use \(pre\) for literal parens.
        req_filter.write_text(
            "#!/bin/bash\n"
            "# Drop any prior copies of our injected lines, then prepend fresh ones.\n"
            "grep -vE "
            f"'^(Requires\\(pre\\)|Requires):[[:space:]]+{env_pkg}[[:space:]]*$' "
            "> /tmp/scls_repack_req.$$\n"
            f"echo 'Requires(pre): {env_pkg}'\n"
            f"echo 'Requires: {env_pkg}'\n"
            "cat /tmp/scls_repack_req.$$\n"
            "rm -f /tmp/scls_repack_req.$$\n"
        )
        req_filter.chmod(0o755)

        preamble_filter = tdp / 'preamble_filter.sh'
        preamble_filter.write_text(
            "#!/bin/bash\n"
            f"sed -E 's/^(Release:[[:space:]]+).*$/\\1{new_release}/'\n"
        )
        preamble_filter.chmod(0o755)

        # rpmrebuild writes RPMS/<arch>/<NVRA>.rpm under -d <output>.
        # Note: -p (use package file, not rpmdb) is a boolean; the .rpm
        # path is a positional argument that must come after all options.
        cmd = [
            'rpmrebuild',
            '-p',
            '--notest-install',
            f'--change-spec-requires={req_filter}',
            f'--change-spec-preamble={preamble_filter}',
            '--directory', str(output_dir),
            '--batch',
            str(rpm_path),
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"  FAIL  {rpm_path.name}: rpmrebuild exited {e.returncode}")
            return None

    out_path = output_dir / arch / f"{name}-{version}-{new_release}.{arch}.rpm"
    if out_path.exists():
        print(f"  OK    {rpm_path.name} -> {out_path.name}")
        return out_path
    # Not at the predicted path — surface where it landed so the user can find it.
    candidates = list(output_dir.rglob(f"{name}-*.rpm"))
    print(f"  WARN  {rpm_path.name}: expected {out_path}, found: "
          f"{', '.join(str(p) for p in candidates) or '(none)'}")
    return candidates[0] if candidates else None


# -----------------------------------------------------------------------
# DEB mode
# -----------------------------------------------------------------------

def _control_get(text: str, field: str) -> str | None:
    m = re.search(rf'(?m)^{field}:\s*(.*)$', text)
    return m.group(1).strip() if m else None


def _control_replace(text: str, field: str, new_value: str) -> str:
    return re.sub(rf'(?m)^{field}:.*$', f'{field}: {new_value}', text, count=1)


def _control_extend_csv(text: str, field: str, value: str) -> str:
    """Append `value` to the comma-separated list in `field` if not already
    present. Inserts the field (before Description:) if absent.
    """
    existing = _control_get(text, field)
    if existing is None:
        # Insert the new field above Description.
        return re.sub(
            r'(?m)^(Description:)',
            f'{field}: {value}\n\\1',
            text,
            count=1,
        )
    items = [s.strip() for s in existing.split(',') if s.strip()]
    if value in items:
        return text
    items.append(value)
    return _control_replace(text, field, ', '.join(items))


def repackage_deb(deb_path: Path, output_dir: Path,
                  version_suffix: str) -> Path | None:
    pkg = subprocess.check_output(
        ['dpkg-deb', '-f', str(deb_path), 'Package']).decode().strip()
    ver = subprocess.check_output(
        ['dpkg-deb', '-f', str(deb_path), 'Version']).decode().strip()
    arch = subprocess.check_output(
        ['dpkg-deb', '-f', str(deb_path), 'Architecture']).decode().strip()

    flavor, base = parse_scls_name(pkg)
    if flavor is None:
        print(f"  SKIP  {deb_path.name}: not a flavored scls-* package")
        return None
    if base == 'environment':
        print(f"  SKIP  {deb_path.name}: this IS the environment package")
        return None

    env_pkg = f"scls-{flavor}-environment"
    new_ver = ver + version_suffix

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / 'work'
        subprocess.run(['dpkg-deb', '-R', str(deb_path), str(work)], check=True)

        control = work / 'DEBIAN' / 'control'
        text = control.read_text()
        text = _control_replace(text, 'Version', new_ver)
        text = _control_extend_csv(text, 'Pre-Depends', env_pkg)
        text = _control_extend_csv(text, 'Depends', env_pkg)
        control.write_text(text)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{pkg}_{new_ver}_{arch}.deb"
        subprocess.run(
            ['dpkg-deb', '--root-owner-group', '--build', str(work), str(out_path)],
            check=True,
        )
        print(f"  OK    {deb_path.name} -> {out_path.name}")
        return out_path


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest='mode', required=True)

    rpm_p = sub.add_parser('rpm', help='Repackage RPMs (uses rpmrebuild)')
    rpm_p.add_argument('--input', required=True, type=Path,
                       help='Directory tree containing .rpm files (recursive)')
    rpm_p.add_argument('--output', required=True, type=Path,
                       help='Where rpmrebuild should drop the patched RPMs')
    rpm_p.add_argument('--release-suffix', default='.scls2',
                       help='Appended to RPM Release to distinguish patched '
                            'artifacts (default: .scls2)')

    deb_p = sub.add_parser('deb', help='Repackage DEBs (uses dpkg-deb)')
    deb_p.add_argument('--input', required=True, type=Path,
                       help='Directory tree containing .deb files (recursive)')
    deb_p.add_argument('--output', required=True, type=Path,
                       help='Where to write patched .debs')
    deb_p.add_argument('--version-suffix', default='+scls2',
                       help='Appended to deb Version (default: +scls2)')

    args = ap.parse_args()

    if args.mode == 'rpm':
        if not shutil.which('rpmrebuild'):
            sys.exit("rpmrebuild not found. Install with: sudo dnf install rpmrebuild")
        if not args.input.is_dir():
            sys.exit(f"--input not a directory: {args.input}")
        args.output.mkdir(parents=True, exist_ok=True)
        rpms = sorted(args.input.rglob('*.rpm'))
        if not rpms:
            sys.exit(f"No .rpm files under {args.input}")
        print(f"Repackaging {len(rpms)} RPM(s) from {args.input} into {args.output}")
        for rpm in rpms:
            repackage_rpm(rpm, args.output, args.release_suffix)

    elif args.mode == 'deb':
        if not shutil.which('dpkg-deb'):
            sys.exit("dpkg-deb not found")
        if not args.input.is_dir():
            sys.exit(f"--input not a directory: {args.input}")
        args.output.mkdir(parents=True, exist_ok=True)
        debs = sorted(args.input.rglob('*.deb'))
        if not debs:
            sys.exit(f"No .deb files under {args.input}")
        print(f"Repackaging {len(debs)} DEB(s) from {args.input} into {args.output}")
        for deb in debs:
            repackage_deb(deb, args.output, args.version_suffix)

    return 0


if __name__ == '__main__':
    sys.exit(main())
