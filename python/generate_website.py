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
                'flavors': recipe.get('flavors', []),  # Empty = all flavors
                'exclude_flavors': recipe.get('exclude_flavors', []),
                'features': recipe.get('features', {})
            }
            recipes.append(package_info)
        except Exception as e:
            print(f"Warning: Failed to load {yaml_file}: {e}")

    # Sort by name
    recipes.sort(key=lambda x: x['name'].lower())
    return recipes


def load_all_flavors(flavors_dir, exclude_dev=True):
    """Load all flavor YAML files"""
    flavors = []

    for yaml_file in Path(flavors_dir).glob("*.yaml"):
        try:
            flavor = load_yaml(yaml_file)
            # Skip development flavors if requested
            if exclude_dev and flavor.get('platform') == 'macos':
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

    # Sort flavors in a logical order
    flavor_order = ['gcc', 'debug', 'lbl', 'gcc-mkl', 'intel-mkl', 'gcc-mkl-cuda']
    flavors.sort(key=lambda x: flavor_order.index(x['name']) if x['name'] in flavor_order else 999)

    return flavors


def get_flavor_match_names(flavor_name):
    """Return list of names to match against for a flavor.
    E.g., 'gcc-mkl-cuda' returns ['gcc-mkl-cuda', 'gcc', 'mkl', 'cuda']."""
    names = [flavor_name]
    for part in flavor_name.split('-'):
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
    # If no flavors specified, available for all
    if not package['flavors']:
        return True
    # Otherwise check if any name matches
    return any(n in package['flavors'] for n in names)


def generate_flavor_descriptions(flavors):
    """Generate HTML descriptions for each flavor"""
    descriptions = []

    # Group flavors by category (each flavor goes into exactly one group)
    gcc_flavors = []
    debug_flavors = []
    mkl_flavors = []
    intel_flavors = []
    cuda_flavors = []

    for f in flavors:
        name = f['name']
        if 'cuda' in name:
            cuda_flavors.append(f)
        elif 'debug' in name:
            debug_flavors.append(f)
        elif name.startswith('intel'):
            intel_flavors.append(f)
        elif 'mkl' in name:
            mkl_flavors.append(f)
        else:
            gcc_flavors.append(f)

    if gcc_flavors:
        descriptions.append({
            'title': 'GCC + OpenBLAS',
            'description': 'Default production flavors using the system GCC toolchain and OpenBLAS for linear algebra. Suitable for most scientific computing workloads.',
            'flavors': gcc_flavors
        })

    if debug_flavors:
        descriptions.append({
            'title': 'Debug',
            'description': 'Compiled with -Og -g and linked against reference BLAS/LAPACK. Designed for use with valgrind, address sanitizers, and debuggers. No SIMD optimizations that could confuse analysis tools.',
            'flavors': debug_flavors
        })

    if mkl_flavors:
        descriptions.append({
            'title': 'GCC + Intel MKL',
            'description': 'Uses the system GCC toolchain with Intel Math Kernel Library for optimized BLAS, LAPACK, and ScaLAPACK. Requires Intel oneAPI MKL.',
            'flavors': mkl_flavors
        })

    if intel_flavors:
        descriptions.append({
            'title': 'Intel Compilers + MKL',
            'description': 'Uses Intel oneAPI compilers (icx/icpx/ifx) with Intel MKL. Requires Intel oneAPI Base and HPC Toolkits.',
            'flavors': intel_flavors
        })

    if cuda_flavors:
        descriptions.append({
            'title': 'GPU-accelerated with CUDA',
            'description': 'Adds NVIDIA CUDA support for GPU-accelerated computing. Requires NVIDIA GPU hardware and CUDA toolkit.',
            'flavors': cuda_flavors
        })

    return descriptions


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

    # Prepare context
    context = {
        'packages': packages,
        'flavors': flavors,
        'flavor_groups': generate_flavor_descriptions(flavors),
        'release_version': args.release_version,
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