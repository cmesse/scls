#!/usr/bin/env python3
"""
SCLS Patch Management Utility
"""

import argparse
import sys
from pathlib import Path
from patch_common import (
    get_all_patches, validate_patches,
    discover_patches_in_directory, infer_patch_level
)
from build_common import load_recipe


def list_patches(package_name: str) -> None:
    """List all patches for a package"""
    try:
        recipe = load_recipe(package_name)
        patches = get_all_patches(recipe, package_name)

        if not patches:
            print(f"No patches found for {package_name}")
            return

        print(f"Patches for {package_name}:")
        for i, patch in enumerate(patches, 1):
            source_indicator = {
                'recipe_patches': '[R]',
                'recipe_patch_legacy': '[L]',
                'auto_discovered': '[A]'
            }.get(patch['source'], '[?]')

            strip_info = f"(-p{patch['strip']})" if patch['strip'] != 1 else ""
            print(f"  {i:2d}. {patch['file']} {strip_info} {source_indicator}")

        print("\nLegend: [R]=Recipe [L]=Legacy [A]=Auto-discovered")

    except Exception as e:
        print(f"Error: {e}")


def show_rpm_spec_patches(package_name: str) -> None:
    """Show how patches will appear in RPM SPEC file"""
    try:
        recipe = load_recipe(package_name)
        patches = get_all_patches(recipe, package_name)

        if not patches:
            print(f"No patches for {package_name} - no patch entries in SPEC")
            return

        print(f"RPM SPEC patch entries for {package_name}:")
        print("\n# Patch declarations:")
        for i, patch in enumerate(patches):
            print(f"Patch{i}:         {patch['file']}")

        print("\n# %prep section:")
        print(f"%setup -q -n {package_name}-{{version}}")
        for i, patch in enumerate(patches):
            if patch['strip'] == 1:
                print(f"%patch{i} -p1")
            else:
                print(f"%patch{i} -p{patch['strip']}")

        print("\n# Changelog entry:")
        print(f"- Applied {len(patches)} patch(es):")
        for patch in patches:
            strip_info = f" (-p{patch['strip']})" if patch['strip'] != 1 else ""
            print(f"  - {patch['file']}{strip_info}")

    except Exception as e:
        print(f"Error: {e}")


def validate_package_patches(package_name: str) -> None:
    """Validate patches for a package"""
    try:
        recipe = load_recipe(package_name)
        is_valid = validate_patches(recipe, package_name)

        if is_valid:
            print(f"All patches for {package_name} are valid")
        else:
            print(f"Some patches for {package_name} have issues")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def analyze_patch(patch_file: Path) -> None:
    """Analyze a patch file and suggest strip level"""
    if not patch_file.exists():
        print(f"Patch file not found: {patch_file}")
        return

    suggested_level = infer_patch_level(patch_file)
    print(f"Patch: {patch_file}")
    print(f"Suggested strip level: -p{suggested_level}")

    # Show first few diff lines for context
    try:
        with open(patch_file, 'r') as f:
            lines = f.readlines()

        print("\nFirst few diff lines:")
        for line in lines[:10]:
            if line.startswith(('---', '+++', '@@')):
                print(f"  {line.rstrip()}")

    except Exception as e:
        print(f"Error reading patch: {e}")


def convert_to_modern_format(package_name: str) -> None:
    """Convert legacy patch format to modern format"""
    try:
        recipe = load_recipe(package_name)
        patches = get_all_patches(recipe, package_name)

        if not patches:
            print(f"No patches found for {package_name}")
            return

        print(f"Modern YAML format for {package_name}:")
        print("\npatches:")

        for patch in patches:
            if patch['strip'] == 1:
                print(f"  - {patch['file']}")
            else:
                print(f"  - file: {patch['file']}")
                print(f"    strip: {patch['strip']}")

        # Show what to remove from recipe
        if 'patch' in recipe:
            print("\n# Remove this legacy 'patch:' section:")
            print("# patch:")
            for cmd in recipe['patch']:
                print(f"#   - \"{cmd}\"")

    except Exception as e:
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description='SCLS Patch Management')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # List patches
    list_parser = subparsers.add_parser('list', help='List patches for a package')
    list_parser.add_argument('package', help='Package name')

    # Show RPM SPEC format
    rpm_parser = subparsers.add_parser('rpm', help='Show RPM SPEC patch format')
    rpm_parser.add_argument('package', help='Package name')

    # Validate patches
    validate_parser = subparsers.add_parser('validate', help='Validate patches for a package')
    validate_parser.add_argument('package', help='Package name')

    # Analyze patch
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a patch file')
    analyze_parser.add_argument('patch_file', type=Path, help='Path to patch file')

    # Convert format
    convert_parser = subparsers.add_parser('convert', help='Convert to modern patch format')
    convert_parser.add_argument('package', help='Package name')

    args = parser.parse_args()

    if args.command == 'list':
        list_patches(args.package)
    elif args.command == 'rpm':
        show_rpm_spec_patches(args.package)
    elif args.command == 'validate':
        validate_package_patches(args.package)
    elif args.command == 'analyze':
        analyze_patch(args.patch_file)
    elif args.command == 'convert':
        convert_to_modern_format(args.package)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()