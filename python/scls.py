#!/usr/bin/env python3
"""
SCLS - Scientific Core Libraries

A unified CLI for building and managing scientific computing packages.
Similar to dnf/apt but for the SCLS build system.

Usage:
    scls build <package>              Build package from source
    scls install <package>            Build (if needed) and install
    scls remove <package> [--force]   Uninstall package
    scls list                         List installed packages
    scls info <package>               Show package information
"""

import os
import sys
import argparse
import shutil
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict

import yaml

# Add the python directory to path for imports
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from build_common import (
    load_recipe, load_flavor, get_registry_entry, get_all_registry_entries,
    check_package_in_registry, get_reverse_dependencies, BuildError
)
from build_order import get_next_unbuilt_package


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_CONFIG = {
    'flavor': 'macos' if platform.system() == 'Darwin' else 'gcc-mkl',
    'package_format': 'auto',
}

CONFIG_PATHS = [
    Path.home() / '.config' / 'scls.yaml',
    Path('/etc/scls.yaml'),
]


def load_config() -> Dict:
    """Load configuration from config file, with defaults."""
    config = DEFAULT_CONFIG.copy()

    for config_path in CONFIG_PATHS:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    user_config = yaml.safe_load(f) or {}
                config.update(user_config)
                break
            except Exception as e:
                print(f"Warning: Could not load config from {config_path}: {e}",
                      file=sys.stderr)

    return config


def detect_package_format() -> str:
    """Auto-detect the appropriate package format for this system."""
    system = platform.system()

    if system == 'Darwin':
        return 'pkg'

    # Linux - check for distro type
    if Path('/etc/redhat-release').exists():
        return 'rpm'
    if Path('/etc/debian_version').exists():
        return 'deb'

    # Check for common package managers
    if shutil_which('dnf') or shutil_which('yum'):
        return 'rpm'
    if shutil_which('apt-get'):
        return 'deb'

    # Default to tar.xz for unknown Linux
    return 'tar.xz'


def shutil_which(cmd: str) -> Optional[str]:
    """Check if a command exists in PATH."""
    import shutil
    return shutil.which(cmd)


def get_package_format(config: Dict) -> str:
    """Get the package format to use, auto-detecting if needed."""
    fmt = config.get('package_format', 'auto')
    if fmt == 'auto':
        return detect_package_format()
    return fmt


# =============================================================================
# "next" package resolution
# =============================================================================

def _rpm_installed_scls_packages(flavor: str) -> set:
    """Return the set of recipe names whose scls-<flavor>-<name> RPM is installed.

    Used to recover from partial installs where the RPM is registered with
    rpm but the {prefix}/share/scls/registry/<name>.yaml marker file is
    missing on disk (e.g., after a manual delete or interrupted install).
    Returns an empty set if rpm is unavailable or the query fails.
    """
    if shutil.which('rpm') is None:
        return set()
    try:
        result = subprocess.run(
            ['rpm', '-qa', '--queryformat', '%{NAME}\n', f'scls-{flavor}-*'],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()

    prefix = f'scls-{flavor}-'
    return {
        line[len(prefix):]
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    }


def resolve_next_package(flavor: str) -> Optional[str]:
    """Resolve 'next' to the next unbuilt package in build order."""
    try:
        flavor_config = load_flavor(flavor)
        prefix = Path(flavor_config['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor}': {e}", file=sys.stderr)
        return None

    recipes_dir = str(SCRIPT_DIR.parent / 'recipes')

    # Cross-check rpm against the on-disk registry. A package whose RPM is
    # installed but whose registry marker file is missing would otherwise
    # cause "install next" to loop on it forever.
    rpm_installed = _rpm_installed_scls_packages(flavor)
    registry_dir = prefix / 'share' / 'scls' / 'registry'
    missing_registry = {
        name for name in rpm_installed
        if not (registry_dir / f'{name}.yaml').exists()
    }
    if missing_registry:
        names = ', '.join(sorted(missing_registry))
        print(
            f"Warning: RPM installed but registry marker missing for: {names}.",
            file=sys.stderr,
        )
        print(
            f"  Treating as installed. To restore the marker file, run: "
            f"sudo dnf reinstall scls-{flavor}-<name>",
            file=sys.stderr,
        )

    pkg = get_next_unbuilt_package(
        recipes_dir, flavor, prefix, extra_installed=rpm_installed
    )
    if pkg is None:
        print("All packages are already installed.")
    return pkg


# =============================================================================
# Command Implementations
# =============================================================================

def cmd_build(args, config: Dict) -> int:
    """Build a package from source."""
    package = args.package
    flavor = args.flavor or config['flavor']
    pkg_format = get_package_format(config)

    if package == 'next':
        package = resolve_next_package(flavor)
        if package is None:
            return 0
        print(f"Next package to build: {package}")

    print(f"Building {package} with flavor '{flavor}' (format: {pkg_format})")

    try:
        # Check if recipe exists
        recipe = load_recipe(package)
    except Exception as e:
        print(f"Error: Could not load recipe for '{package}': {e}", file=sys.stderr)
        return 1

    # Dispatch to appropriate builder
    if pkg_format == 'rpm':
        return _build_rpm(package, flavor)
    else:
        # pkg, deb, tar.xz all use unix_builder for the build step
        return _build_unix(package, flavor, pkg_format)


def _build_rpm(package: str, flavor: str) -> int:
    """Build using rpm_builder."""
    cmd = [sys.executable, str(SCRIPT_DIR / 'rpm_builder.py'),
           '--package', package, '--flavor', flavor]
    result = subprocess.run(cmd)
    return result.returncode


def _build_unix(package: str, flavor: str, pkg_format: str) -> int:
    """Build using unix_builder."""
    # Determine which commands to run based on format
    commands = ['build', 'install']
    if pkg_format == 'pkg':
        commands.append('pkg')

    cmd = [sys.executable, str(SCRIPT_DIR / 'unix_builder.py'),
           '--package', package, '--flavor', flavor] + commands
    result = subprocess.run(cmd)
    return result.returncode


def cmd_install(args, config: Dict) -> int:
    """Build (if needed) and install a package."""
    package = args.package
    flavor = args.flavor or config['flavor']
    pkg_format = get_package_format(config)

    if package == 'next':
        package = resolve_next_package(flavor)
        if package is None:
            return 0
        print(f"Next package to install: {package}")
        args.package = package

    print(f"Installing {package} (flavor: {flavor}, format: {pkg_format})")

    try:
        flavor_config = load_flavor(flavor)
        prefix = Path(flavor_config['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor}': {e}", file=sys.stderr)
        return 1

    try:
        recipe = load_recipe(package)
        new_version = recipe.get('version', 'unknown')
    except Exception as e:
        print(f"Error: Could not load recipe for '{package}': {e}", file=sys.stderr)
        return 1

    # Check if already installed
    existing = get_registry_entry(prefix, package)
    if existing:
        old_version = existing.get('version', 'unknown')
        if old_version == new_version and not args.force:
            print(f"{package} {new_version} is already installed. Use --force to reinstall.")
            return 0
        print(f"Upgrading {package} from {old_version} to {new_version}")

    # Dispatch based on package format
    if pkg_format == 'rpm':
        return _install_rpm(package, flavor, prefix, existing is not None)
    elif pkg_format == 'deb':
        return _install_deb(package, flavor, prefix, existing is not None)
    elif pkg_format == 'pkg':
        return _install_pkg(package, flavor, prefix, existing is not None)
    else:  # tar.xz or direct
        return _install_direct(package, flavor, prefix, existing is not None)


def _install_rpm(package: str, flavor: str, prefix: Path, upgrade: bool) -> int:
    """Install via RPM/dnf."""
    # First build the RPM
    ret = _build_rpm(package, flavor)
    if ret != 0:
        return ret

    # Find the built RPM (RPMs are named scls-{flavor}-{package}-*.rpm)
    rpm_dir = Path('rpmbuild/RPMS')
    scls_name = f'scls-{flavor}-{package}'
    rpms = sorted(
        rpm_dir.rglob(f'{scls_name}-[0-9]*.rpm'),
        key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not rpms:
        print(f"Error: No RPM found for {scls_name} in {rpm_dir}", file=sys.stderr)
        return 1

    rpm_file = rpms[0]
    print(f"Installing {rpm_file}")

    # Use dnf or yum
    pkg_manager = 'dnf' if shutil_which('dnf') else 'yum'
    cmd = ['sudo', pkg_manager, 'install', '-y', str(rpm_file)]
    result = subprocess.run(cmd)
    return result.returncode


def _install_deb(package: str, flavor: str, prefix: Path, upgrade: bool) -> int:
    """Install via DEB/apt-get."""
    # First build (we'd need a deb_builder, for now use unix and create tarball)
    ret = _build_unix(package, flavor, 'deb')
    if ret != 0:
        return ret

    # Find the built DEB (would need deb_builder to create this)
    deb_dir = Path('work/packages')
    debs = list(deb_dir.glob(f'{package}*.deb'))
    if not debs:
        print(f"Note: DEB builder not yet implemented, falling back to direct install")
        return _install_direct(package, flavor, prefix, upgrade)

    deb_file = debs[0]
    print(f"Installing {deb_file}")

    cmd = ['sudo', 'apt-get', 'install', '-y', str(deb_file)]
    result = subprocess.run(cmd)
    return result.returncode


def _install_pkg(package: str, flavor: str, prefix: Path, upgrade: bool) -> int:
    """Install via macOS PKG."""
    # Remove old version if upgrading
    if upgrade:
        print(f"Removing old version of {package}...")
        ret = _remove_direct(package, flavor, prefix, force=True)
        if ret != 0:
            print("Warning: Could not remove old version, continuing anyway...")

    # Build the package (includes pkg creation)
    ret = _build_unix(package, flavor, 'pkg')
    if ret != 0:
        return ret

    # Find the built PKG
    pkg_dir = Path('work/packages')
    pkgs = list(pkg_dir.glob(f'{package}*.pkg'))
    if not pkgs:
        print(f"Error: No PKG found for {package}", file=sys.stderr)
        return 1

    pkg_file = pkgs[0]
    print(f"Installing {pkg_file}")

    cmd = ['sudo', 'installer', '-pkg', str(pkg_file), '-target', '/']
    result = subprocess.run(cmd)
    return result.returncode


def _install_direct(package: str, flavor: str, prefix: Path, upgrade: bool) -> int:
    """Direct install using unix_builder (for tar.xz or fallback)."""
    # Remove old version if upgrading
    if upgrade:
        print(f"Removing old version of {package}...")
        ret = _remove_direct(package, flavor, prefix, force=True)
        if ret != 0:
            print("Warning: Could not remove old version, continuing anyway...")

    # Build and install
    cmd = [sys.executable, str(SCRIPT_DIR / 'unix_builder.py'),
           '--package', package, '--flavor', flavor, 'build', 'install']
    result = subprocess.run(cmd)
    return result.returncode


def cmd_remove(args, config: Dict) -> int:
    """Remove/uninstall a package."""
    package = args.package
    flavor = args.flavor or config['flavor']
    pkg_format = get_package_format(config)

    try:
        flavor_config = load_flavor(flavor)
        prefix = Path(flavor_config['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor}': {e}", file=sys.stderr)
        return 1

    # Check if installed
    if not check_package_in_registry(prefix, package):
        print(f"Package '{package}' is not installed")
        return 1

    # Dispatch based on package format
    if pkg_format == 'rpm':
        return _remove_rpm(package, flavor, args.force)
    elif pkg_format == 'deb':
        return _remove_deb(package, flavor, args.force)
    else:  # pkg, tar.xz, direct
        return _remove_direct(package, flavor, prefix, args.force, args.with_deps,
                              args.dry_run)


def _remove_rpm(package: str, flavor: str, force: bool) -> int:
    """Remove via RPM/dnf."""
    pkg_manager = 'dnf' if shutil_which('dnf') else 'yum'
    cmd = ['sudo', pkg_manager, 'remove', '-y', f'scls-{flavor}-{package}']
    result = subprocess.run(cmd)
    return result.returncode


def _remove_deb(package: str, flavor: str, force: bool) -> int:
    """Remove via DEB/apt-get."""
    cmd = ['sudo', 'apt-get', 'remove', '-y', f'scls-{flavor}-{package}']
    result = subprocess.run(cmd)
    return result.returncode


def _remove_direct(package: str, flavor: str, prefix: Path,
                   force: bool = False, with_deps: bool = False,
                   dry_run: bool = False) -> int:
    """Remove using our uninstall functionality."""
    cmd = [sys.executable, str(SCRIPT_DIR / 'unix_builder.py'),
           '--package', package, '--flavor', flavor, '--uninstall']

    if force:
        cmd.append('--force')
    if with_deps:
        cmd.append('--with-deps')
    if dry_run:
        cmd.append('--dry-run')

    result = subprocess.run(cmd)
    return result.returncode


def cmd_list(args, config: Dict) -> int:
    """List installed packages."""
    flavor = args.flavor or config['flavor']

    try:
        flavor_config = load_flavor(flavor)
        prefix = Path(flavor_config['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor}': {e}", file=sys.stderr)
        return 1

    entries = get_all_registry_entries(prefix)

    if not entries:
        print(f"No packages installed in {prefix}")
        return 0

    print(f"\nInstalled packages in {prefix}:")
    print(f"{'Package':<20} {'Version':<15} {'Dependencies'}")
    print("-" * 70)

    for name in sorted(entries.keys()):
        entry = entries[name]
        version = entry.get('version', '?')
        deps = ', '.join(entry.get('dependencies', [])) or '-'
        # Truncate deps if too long
        if len(deps) > 30:
            deps = deps[:27] + '...'
        print(f"{name:<20} {version:<15} {deps}")

    print(f"\nTotal: {len(entries)} package(s)")
    return 0


def cmd_info(args, config: Dict) -> int:
    """Show information about a package."""
    package = args.package
    flavor = args.flavor or config['flavor']

    try:
        flavor_config = load_flavor(flavor)
        prefix = Path(flavor_config['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor}': {e}", file=sys.stderr)
        return 1

    # Try to load recipe
    try:
        recipe = load_recipe(package)
    except Exception:
        recipe = None

    # Check registry
    entry = get_registry_entry(prefix, package)

    if not recipe and not entry:
        print(f"Package '{package}' not found (no recipe and not installed)")
        return 1

    print(f"\n{'='*60}")
    print(f"Package: {package}")
    print(f"{'='*60}")

    if recipe:
        print(f"\nRecipe Information:")
        print(f"  Version:     {recipe.get('version', 'unknown')}")
        print(f"  License:     {recipe.get('license', 'unknown')}")
        print(f"  Homepage:    {recipe.get('homepage', 'N/A')}")
        if recipe.get('description'):
            print(f"  Description: {recipe['description'][:60]}...")

    if entry:
        print(f"\nInstalled:")
        print(f"  Version:      {entry.get('version', 'unknown')}")
        print(f"  Dependencies: {', '.join(entry.get('dependencies', [])) or 'none'}")

        # Show reverse dependencies
        reverse_deps = get_reverse_dependencies(prefix, package)
        if reverse_deps:
            print(f"  Required by:  {', '.join(reverse_deps)}")

        # Show features
        features = []
        if entry.get('features', {}).get('mpi'):
            features.append('MPI')
        if entry.get('features', {}).get('openmp'):
            features.append('OpenMP')
        if entry.get('features', {}).get('fortran'):
            features.append('Fortran')
        if features:
            print(f"  Features:     {', '.join(features)}")
    else:
        print(f"\nStatus: Not installed")

    return 0


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='SCLS - Scientific Core Libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  scls build openblas          Build OpenBLAS from source
  scls build next              Build next unbuilt package in dependency order
  scls install next            Build and install next unbuilt package
  scls install petsc           Build and install PETSc
  scls install petsc -f        Force reinstall PETSc
  scls remove slepc            Uninstall SLEPc
  scls remove zlib -f          Force remove even if dependents exist
  scls remove zlib -n          Dry-run (show what would be removed)
  scls list                    Show all installed packages
  scls info petsc              Show PETSc information

Configuration:
  Config file: ~/.config/scls.yaml

  Example config:
    flavor: macos
    package_format: auto    # auto, pkg, rpm, deb, tar.xz
""")

    parser.add_argument('--flavor', '-F',
                        help='Override flavor from config')
    parser.add_argument('--version', '-V', action='store_true',
                        help='Show version')

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # build command
    build_parser = subparsers.add_parser('build', help='Build package from source')
    build_parser.add_argument('package', help='Package name')

    # install command
    install_parser = subparsers.add_parser('install', help='Build (if needed) and install')
    install_parser.add_argument('package', help='Package name')
    install_parser.add_argument('--force', '-f', action='store_true',
                                help='Reinstall even if same version exists')

    # remove command
    remove_parser = subparsers.add_parser('remove', help='Uninstall package')
    remove_parser.add_argument('package', help='Package name')
    remove_parser.add_argument('--force', '-f', action='store_true',
                               help='Remove even if other packages depend on it')
    remove_parser.add_argument('--with-deps', action='store_true',
                               help='Also remove dependencies not needed by others')
    remove_parser.add_argument('--dry-run', '-n', action='store_true',
                               help='Show what would be removed without actually removing')

    # list command
    subparsers.add_parser('list', help='List installed packages')

    # info command
    info_parser = subparsers.add_parser('info', help='Show package information')
    info_parser.add_argument('package', help='Package name')

    args = parser.parse_args()

    if args.version:
        print("SCLS version 1.0.0")
        return 0

    if not args.command:
        parser.print_help()
        return 1

    # Load configuration
    config = load_config()

    # Dispatch to command handler
    commands = {
        'build': cmd_build,
        'install': cmd_install,
        'remove': cmd_remove,
        'list': cmd_list,
        'info': cmd_info,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args, config)
        except KeyboardInterrupt:
            print("\nInterrupted by user", file=sys.stderr)
            return 130
        except BuildError as e:
            print(f"\nError: {e}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
