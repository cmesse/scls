#!/usr/bin/env python3
"""
Generate SCLS website from recipe and flavor YAML files
"""

import os
import sys
import yaml
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
import argparse


def load_yaml(filepath):
    """Load a YAML file"""
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)
    # Force version to be string
    if isinstance(data, dict) and 'version' in data:
        data['version'] = str(data['version'])
    return data


def load_all_recipes(recipes_dir):
    """Load all recipe YAML files and return sorted list"""
    recipes = []

    for yaml_file in Path(recipes_dir).glob("*.yaml"):
        try:
            recipe = load_yaml(yaml_file)
            # Extract key information
            package_info = {
                'name': recipe.get('name', ''),
                'version': recipe.get('version', ''),
                'summary': recipe.get('summary', recipe.get('description', '')),
                'homepage': recipe.get('homepage', ''),
                'license': recipe.get('license', ''),
                'include_flavors': recipe.get('include_flavors'),  # None = all flavors
                'exclude_flavors': recipe.get('exclude_flavors', []),
                'features': recipe.get('features', {})
            }
            recipes.append(package_info)
        except Exception as e:
            print(f"Warning: Failed to load {yaml_file}: {e}")

    # Sort by name
    recipes.sort(key=lambda x: x['name'].lower())
    return recipes


PUBLIC_FLAVORS = ('gcc', 'mkl', 'debug')


def load_all_flavors(flavors_dir):
    """Load flavor YAML files for the publicly distributed binary flavors."""
    flavors = []

    for yaml_file in Path(flavors_dir).glob("*.yaml"):
        try:
            flavor = load_yaml(yaml_file)
            if flavor.get('name') not in PUBLIC_FLAVORS:
                continue

            flavor_info = {
                'name': flavor.get('name', ''),
                'description': flavor.get('description', ''),
                'platform': flavor.get('platform', 'linux'),
                'prefix': flavor.get('prefix', ''),
                'math': flavor.get('math', {}),
                'mpi': flavor.get('mpi', '')
            }
            flavors.append(flavor_info)
        except Exception as e:
            print(f"Warning: Failed to load {yaml_file}: {e}")

    flavors.sort(key=lambda x: PUBLIC_FLAVORS.index(x['name']))
    return flavors


def get_flavor_match_names(flavor_name):
    """Return list of names to match against for a flavor.
    Rightmost hyphen components win (most specific first), matching
    build_common.get_flavor_names(). E.g., 'gcc-mkl-cuda' returns
    ['gcc-mkl-cuda', 'cuda', 'mkl', 'gcc']."""
    names = [flavor_name]
    for part in reversed(flavor_name.split('-')):
        if part and part not in names:
            names.append(part)
    return names


def package_available_for_flavor(package, flavor_name):
    """Check if a package is available for a specific flavor"""
    names = get_flavor_match_names(flavor_name)
    # Check exclusion first
    exclude = package.get('exclude_flavors', [])
    if any(n in exclude for n in names):
        return False
    # If no include_flavors specified, available for all
    if package['include_flavors'] is None:
        return True
    # Otherwise check if any name matches (empty list = no flavor matches)
    return any(n in package['include_flavors'] for n in names)


def generate_flavor_descriptions(flavors):
    """Generate display rows for each publicly distributed flavor package."""
    by_name = {f['name']: f for f in flavors}
    descriptions = []

    if 'gcc' in by_name:
        descriptions.append({
            'package': 'scls-gcc',
            'label': 'GCC + OpenBLAS',
            'description': 'Default production stack with GCC, OpenBLAS, OpenMPI, LP64 integers, and <code>x86-64-v3</code> optimization flags.',
        })

    if 'mkl' in by_name:
        descriptions.append({
            'package': 'scls-mkl',
            'label': 'GCC + Intel MKL',
            'description': 'Production stack for sites that use Intel oneAPI MKL for BLAS, LAPACK, and ScaLAPACK while compiling the rest with GCC.',
        })

    if 'debug' in by_name:
        descriptions.append({
            'package': 'scls-debug',
            'label': 'GCC + Reference BLAS/LAPACK',
            'description': 'Diagnostic stack compiled with <code>-Og -g</code> and linked against Netlib reference BLAS/LAPACK for Valgrind, sanitizers, and debuggers.',
        })

    return descriptions


def is_gpl3_license(license_str):
    """Return True if the license string indicates a GPL-3 / LGPL-3 component."""
    if not license_str:
        return False
    s = license_str.upper().replace(' ', '')
    return 'GPL-3' in s or 'GPLV3' in s


def split_packages(packages, flavor_names, gpl3_flavor_name='macos'):
    """Split packages into the main binary-distribution table and the GPL-3 table.

    - main: non-GPL-3 packages available for at least one of the listed flavors.
    - gpl3: GPL-3 / LGPL-3 packages selected by the macOS Unix build flavor.
    """
    main, gpl3 = [], []
    for p in packages:
        if is_gpl3_license(p.get('license', '')):
            if package_available_for_flavor(p, gpl3_flavor_name):
                gpl3.append(p)
            continue
        if any(package_available_for_flavor(p, name) for name in flavor_names):
            main.append(p)
    return main, gpl3


def main():
    parser = argparse.ArgumentParser(description='Generate SCLS website from recipes')
    parser.add_argument('--recipes', default='recipes', help='Directory containing recipe YAML files')
    parser.add_argument('--flavors', default='flavors', help='Directory containing flavor YAML files')
    parser.add_argument('--template', default='web/scls.html.j2', help='Jinja2 template file')
    parser.add_argument('--output', default='scls.html', help='Output HTML file')
    parser.add_argument('--release-version', default='2026', help='SCLS release version')

    args = parser.parse_args()

    # Load data
    print(f"Loading recipes from {args.recipes}...")
    packages = load_all_recipes(args.recipes)
    print(f"Loaded {len(packages)} packages")

    print(f"Loading flavors from {args.flavors}...")
    flavors = load_all_flavors(args.flavors)
    print(f"Loaded {len(flavors)} flavors")

    # Single source of truth for the scls-release / scls-archive-keyring
    # package version: the environment recipe. Both rpm_builder and
    # deb_builder read the same field, so the install URLs on the site
    # match the artifacts produced by `./scls build scls-release`.
    env_recipe = load_yaml(Path(args.recipes) / 'environment.yaml')
    scls_release_pkg_version = str(env_recipe.get('version', '1'))

    # Setup Jinja2
    template_dir = Path(args.template).parent
    template_name = Path(args.template).name

    env = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True
    )

    # Register custom filter
    env.filters['package_available'] = package_available_for_flavor

    # Load template
    try:
        template = env.get_template(template_name)
    except Exception as e:
        print(f"Error loading template: {e}")
        sys.exit(1)

    flavor_names = [f['name'] for f in flavors]
    main_packages, gpl3_packages = split_packages(packages, flavor_names)
    release_year = str(args.release_version).split('.', 1)[0]
    if not release_year.isdigit():
        release_year = datetime.now().strftime('%Y')

    # Prepare context
    context = {
        'packages': main_packages,
        'gpl3_packages': gpl3_packages,
        'flavors': flavors,
        'flavor_groups': generate_flavor_descriptions(flavors),
        'release_version': args.release_version,
        'release_year': release_year,
        'scls_release_pkg_version': scls_release_pkg_version,
        'generation_date': datetime.now().strftime('%B %d, %Y'),
        'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    # Render template
    html_content = template.render(**context)

    # Write output
    with open(args.output, 'w') as f:
        f.write(html_content)

    print(f"Generated {args.output}")


if __name__ == '__main__':
    main()
