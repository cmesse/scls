#!/usr/bin/env python3
import os
import glob
import yaml
from collections import defaultdict, deque
import sys
import argparse

from build_common import get_flavor_names

# Sentinel package name for the flavor meta-package (e.g. scls-gcc).
# Appended as the last entry in the build order so that "scls build next"
# creates the meta-RPM once every real package has been built.
FLAVOR_META = '_meta'


def load_yaml_files(directory, flavor=None, flavor_names=None):
    """Load all YAML files from the specified directory and extract package info."""
    if flavor_names is None:
        flavor_names = [flavor] if flavor else []
    packages = []
    for filepath in glob.glob(os.path.join(directory, "*.yaml")):
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict) or 'name' not in data:
                    print(f"Warning: {filepath} does not contain a valid package name, skipping.")
                    continue

                # Check if package should be built for this flavor
                if flavor_names:
                    # Check exclusion first (takes precedence)
                    if 'exclude_flavors' in data and any(n in data['exclude_flavors'] for n in flavor_names):
                        print(f"Skipping {data['name']} - excluded for flavor '{flavor}'", file=sys.stderr)
                        continue
                    # If 'include_flavors' key exists, check if our flavor (or parent) is in the list
                    if 'include_flavors' in data and not any(n in data['include_flavors'] for n in flavor_names):
                        print(f"Skipping {data['name']} - not built for flavor '{flavor}'", file=sys.stderr)
                        continue
                    # If no 'include_flavors' key, package is built for all flavors (default behavior)

                # Get explicit requires from recipe
                requires = data.get('requires', [])

                # Non-bootstrap packages implicitly depend on gcc (except gcc itself)
                is_bootstrap = data.get('bootstrap', False)
                pkg_name = data['name']
                if not is_bootstrap and pkg_name != 'gcc':
                    # Add gcc as implicit dependency
                    if isinstance(requires, list):
                        if 'gcc' not in requires:
                            requires = ['gcc'] + requires
                    elif isinstance(requires, dict):
                        # For flavor-specific requires, add gcc to 'all'
                        if 'all' not in requires:
                            requires['all'] = []
                        if 'gcc' not in requires['all']:
                            requires['all'] = ['gcc'] + requires['all']

                # Packages with math features depend on math libraries
                features = data.get('features', {})
                math_type = features.get('math', None)
                if math_type in ('serial', 'parallel', True):
                    # Convert requires to dict format if needed for flavor-specific math deps
                    if isinstance(requires, list):
                        requires = {'all': requires}
                    elif not isinstance(requires, dict):
                        requires = {'all': []}

                    # Add math library dependencies per flavor.
                    # Parallel math packages additionally depend on scalapack
                    # (MKL provides its own, so mkl/intel/gcc-mkl-cuda are skipped).
                    is_parallel = (math_type == 'parallel')

                    # macos: openblas + lapack (+ scalapack for parallel)
                    if 'macos' not in requires:
                        requires['macos'] = []
                    if 'openblas' not in requires['macos'] and pkg_name != 'openblas':
                        requires['macos'].append('openblas')
                    if 'lapack' not in requires['macos'] and pkg_name != 'lapack':
                        requires['macos'].append('lapack')
                    if is_parallel and pkg_name != 'scalapack' and 'scalapack' not in requires['macos']:
                        requires['macos'].append('scalapack')

                    # debug: blas + lapack + (scalapack for parallel)
                    if 'debug' not in requires:
                        requires['debug'] = []
                    if 'blas' not in requires['debug'] and pkg_name not in ('blas', 'lapack'):
                        requires['debug'].append('blas')
                    if 'lapack' not in requires['debug'] and pkg_name != 'lapack':
                        requires['debug'].append('lapack')
                    if is_parallel and pkg_name != 'scalapack' and 'scalapack' not in requires['debug']:
                        requires['debug'].append('scalapack')

                    # gcc / lbl: openblas (provides BLAS+LAPACK via compat symlinks)
                    #            + scalapack for parallel
                    for openblas_flavor in ('gcc', 'lbl'):
                        if openblas_flavor not in requires:
                            requires[openblas_flavor] = []
                        if pkg_name != 'openblas' and 'openblas' not in requires[openblas_flavor]:
                            requires[openblas_flavor].append('openblas')
                        if is_parallel and pkg_name != 'scalapack' and 'scalapack' not in requires[openblas_flavor]:
                            requires[openblas_flavor].append('scalapack')

                    # mkl / intel / gcc-mkl-cuda: Intel MKL provides BLAS and
                    # LAPACK. ScaLAPACK comes from our own scalapack recipe
                    # built on top of MKL (see math_common.py for rationale),
                    # so parallel math packages need a build edge to it.
                    # We always set an explicit (possibly empty) entry so
                    # that the hyphen-split fallback doesn't silently pick
                    # up the 'gcc: [openblas]' injection above.
                    for mkl_flavor in ('mkl', 'intel', 'gcc-mkl-cuda'):
                        if mkl_flavor not in requires:
                            requires[mkl_flavor] = []
                        if is_parallel and pkg_name != 'scalapack' and 'scalapack' not in requires[mkl_flavor]:
                            requires[mkl_flavor].append('scalapack')

                package = {
                    'name': pkg_name,
                    'requires': requires,
                    'filepath': filepath,
                    'include_flavors': data.get('include_flavors'),  # None means all flavors
                    'bootstrap': is_bootstrap
                }
                packages.append(package)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
    return packages


def normalize_dependencies(requires, flavor=None, flavor_names=None):
    """
    Normalize the requires field to a simple list based on flavor.

    Handles formats:
    - Simple list: ['pkg1', 'pkg2']
    - Flavor dict: {'all': ['pkg1'], 'macos': ['pkg2']}
    """
    if flavor_names is None:
        flavor_names = [flavor] if flavor else []
    if isinstance(requires, list):
        # Simple list format - applies to all flavors
        return requires
    elif isinstance(requires, dict):
        # Flavor-specific format
        deps = []

        # First add 'all' dependencies if present
        if 'all' in requires:
            deps.extend(requires['all'])

        # Then add flavor-specific dependencies (with inheritance fallback)
        for name in flavor_names:
            if name in requires:
                deps.extend(requires[name])
                break

        # Remove duplicates while preserving order
        seen = set()
        unique_deps = []
        for dep in deps:
            if dep not in seen:
                seen.add(dep)
                unique_deps.append(dep)

        return unique_deps
    else:
        return []


def get_effective_dependencies(package, flavor=None, flavor_names=None):
    """Get the effective list of dependencies for a package given a flavor."""
    return normalize_dependencies(package['requires'], flavor, flavor_names)


def build_dependency_graph(packages, flavor=None, flavor_names=None):
    """Build a dependency graph from the package list."""
    graph = defaultdict(set)
    in_degree = defaultdict(int)
    all_nodes = set()

    # First, collect all package names that are actually being built
    available_packages = {pkg['name'] for pkg in packages}

    # Build the graph
    for pkg in packages:
        pkg_name = pkg['name']
        all_nodes.add(pkg_name)

        # Get effective dependencies for this flavor
        effective_deps = get_effective_dependencies(pkg, flavor, flavor_names)

        for dep in effective_deps:
            if dep in available_packages:
                # Only add edges for dependencies that are in our build set
                graph[dep].add(pkg_name)
                in_degree[pkg_name] += 1
            else:
                print(
                    f"Info: Dependency '{dep}' for package '{pkg_name}' not in build set for flavor '{flavor or 'all'}'",
                    file=sys.stderr)

    # Ensure all packages have an entry in in_degree (even if 0)
    for pkg in packages:
        if pkg['name'] not in in_degree:
            in_degree[pkg['name']] = 0

    return graph, in_degree, all_nodes


def topological_sort(graph, in_degree, nodes):
    """Perform topological sort and assign ranks to nodes."""
    ranks = {}
    in_degree_copy = in_degree.copy()  # Don't modify the original

    # Find all nodes with no dependencies
    queue = deque([node for node in nodes if in_degree_copy[node] == 0])

    # Assign rank 0 to nodes with no dependencies
    for node in queue:
        ranks[node] = 0

    # Process nodes in topological order
    processed = 0
    while queue:
        node = queue.popleft()
        processed += 1

        # Process all nodes that depend on this one
        for neighbor in graph[node]:
            in_degree_copy[neighbor] -= 1

            # Update rank of the neighbor
            if neighbor not in ranks:
                ranks[neighbor] = 0
            ranks[neighbor] = max(ranks[neighbor], ranks[node] + 1)

            # If all dependencies are satisfied, add to queue
            if in_degree_copy[neighbor] == 0:
                queue.append(neighbor)

    # Check for cycles
    if processed != len(nodes):
        unprocessed = [node for node in nodes if node not in ranks or in_degree_copy[node] > 0]
        raise ValueError(f"Cycle detected! Unprocessed packages: {unprocessed}")

    return ranks


def get_build_order(ranks):
    """Generate build order grouped by rank, sorted alphabetically within each rank."""
    if not ranks:
        return []

    max_rank = max(ranks.values())
    build_order = []

    for rank in range(max_rank + 1):
        nodes_at_rank = sorted([node for node, node_rank in ranks.items() if node_rank == rank])
        build_order.extend((rank, node) for node in nodes_at_rank)

    return build_order


def validate_build_order(build_order, packages, flavor=None, flavor_names=None):
    """Validate that dependencies are built before dependent packages."""
    # Create a position map
    position = {pkg: idx for idx, (rank, pkg) in enumerate(build_order)}

    # Create a package lookup
    pkg_lookup = {pkg['name']: pkg for pkg in packages}

    errors = []
    for rank, pkg_name in build_order:
        if pkg_name not in pkg_lookup:
            continue

        pkg = pkg_lookup[pkg_name]
        deps = get_effective_dependencies(pkg, flavor, flavor_names)

        for dep in deps:
            if dep in position:  # Only check dependencies that are being built
                if position[dep] >= position[pkg_name]:
                    errors.append(f"Package '{pkg_name}' depends on '{dep}' but is scheduled before it")

    if errors:
        raise ValueError("Build order validation failed:\n  " + "\n  ".join(errors))


def analyze_dependencies(packages, flavor=None, flavor_names=None):
    """Analyze and report dependency statistics."""
    stats = {
        'total_packages': len(packages),
        'packages_with_deps': 0,
        'total_dependencies': 0,
        'max_dependencies': 0,
        'most_depended_on': defaultdict(int)
    }

    available_packages = {pkg['name'] for pkg in packages}

    for pkg in packages:
        deps = get_effective_dependencies(pkg, flavor, flavor_names)
        available_deps = [d for d in deps if d in available_packages]

        if available_deps:
            stats['packages_with_deps'] += 1
            stats['total_dependencies'] += len(available_deps)
            stats['max_dependencies'] = max(stats['max_dependencies'], len(available_deps))

            for dep in available_deps:
                stats['most_depended_on'][dep] += 1

    return stats


def get_ordered_package_list(directory, flavor=None):
    """Return a flat list of package names in build order for the given flavor.

    Returns:
        List of package name strings in dependency-safe build order.
    """
    flavor_names = get_flavor_names(flavor) if flavor else []
    packages = load_yaml_files(directory, flavor, flavor_names)
    if not packages:
        return []

    graph, in_degree, nodes = build_dependency_graph(packages, flavor, flavor_names)
    ranks = topological_sort(graph, in_degree, nodes)

    # Force 'environment' to build before everything else (Group 0)
    if 'environment' in ranks:
        offset = ranks['environment']
        if offset == 0:
            for pkg in ranks:
                if pkg != 'environment':
                    ranks[pkg] += 1
        else:
            ranks['environment'] = 0

    order = get_build_order(ranks)
    ordered = [name for _rank, name in order]

    # Append the flavor meta-package as the very last entry so it depends
    # on everything and gets built only after all real packages are done.
    if flavor:
        ordered.append(FLAVOR_META)

    return ordered


def get_next_unbuilt_package(directory, flavor, prefix, extra_installed=None):
    """Find the next package in build order that is not yet installed.

    Args:
        directory: Path to the recipes directory.
        flavor: Flavor name string.
        prefix: Installation prefix (Path) where the registry lives.
        extra_installed: Optional set of package names to additionally treat
            as installed (e.g. packages reported by ``rpm -q`` whose registry
            marker file is missing on disk). Used to recover from partial
            installs where the RPM is registered but the registry file was
            deleted.

    Returns:
        Package name string, or None if all packages are installed.
    """
    from pathlib import Path as _Path

    ordered = get_ordered_package_list(directory, flavor)
    if not ordered:
        return None

    extra_installed = extra_installed or set()

    # Check registry for each package in order
    # Look in both the installed prefix registry and the local RPM build registry
    registry_dir = _Path(prefix) / 'share' / 'scls' / 'registry'
    local_registry_dir = _Path(directory).parent / 'rpmbuild' / 'registry' / flavor
    for pkg_name in ordered:
        installed = (registry_dir / f'{pkg_name}.yaml').exists()
        built = (local_registry_dir / f'{pkg_name}.yaml').exists()
        if not installed and not built and pkg_name not in extra_installed:
            return pkg_name

    return None


def get_flavor_package_list(directory, flavor):
    """Return the list of real package names (excluding _meta) for a flavor.

    This is used by the meta-package builder to determine which packages
    should be listed as Requires.
    """
    ordered = get_ordered_package_list(directory, flavor)
    return [p for p in ordered if p != FLAVOR_META]


def get_next_uninstalled_package(directory, flavor, prefix):
    """Find the next package that has been built but not yet installed.

    Checks for packages that have a local RPM build registry marker
    but no installed registry entry at the prefix.

    Args:
        directory: Path to the recipes directory.
        flavor: Flavor name string.
        prefix: Installation prefix (Path) where the registry lives.

    Returns:
        Package name string, or None if all built packages are installed.
    """
    from pathlib import Path as _Path

    ordered = get_ordered_package_list(directory, flavor)
    if not ordered:
        return None

    registry_dir = _Path(prefix) / 'share' / 'scls' / 'registry'
    local_registry_dir = _Path(directory).parent / 'rpmbuild' / 'registry' / flavor
    for pkg_name in ordered:
        installed = (registry_dir / f'{pkg_name}.yaml').exists()
        built = (local_registry_dir / f'{pkg_name}.yaml').exists()
        if built and not installed:
            return pkg_name

    return None


def build_order(directory, flavor=None, show_stats=False):
    """Main function to generate build order from YAML files."""
    # Resolve flavor names (with inheritance)
    flavor_names = get_flavor_names(flavor) if flavor else []

    # Load YAML files with flavor filtering
    packages = load_yaml_files(directory, flavor, flavor_names)
    if not packages:
        print(f"No valid YAML files found in the directory{' for flavor ' + flavor if flavor else ''}.")
        return

    print(f"\nLoaded {len(packages)} packages{' for flavor: ' + flavor if flavor else ' (all flavors)'}")

    # Build dependency graph with proper flavor handling
    graph, in_degree, nodes = build_dependency_graph(packages, flavor, flavor_names)

    try:
        # Perform topological sort
        ranks = topological_sort(graph, in_degree, nodes)

        # Force 'environment' to build before everything else (Group 0)
        if 'environment' in ranks:
            offset = ranks['environment']
            if offset == 0:
                # Already rank 0, shift all other rank-0 packages up by 1
                for pkg in ranks:
                    if pkg != 'environment':
                        ranks[pkg] += 1
            else:
                # Move environment to rank 0 (others are already above)
                ranks['environment'] = 0

        # Get build order
        build_order_list = get_build_order(ranks)

        # Validate the build order
        validate_build_order(build_order_list, packages, flavor, flavor_names)

        # Print the build order
        print(f"\nBuild Order{' for flavor: ' + flavor if flavor else ' (all packages)'}:")
        current_rank = -1
        for rank, package in build_order_list:
            if rank != current_rank:
                current_rank = rank
                print(f"\n--- Group {rank + 1} (Rank {rank}) ---")

            # Show dependencies for this package
            pkg_obj = next((p for p in packages if p['name'] == package), None)
            if pkg_obj:
                deps = get_effective_dependencies(pkg_obj, flavor, flavor_names)
                available_deps = [d for d in deps if d in nodes]
                if available_deps:
                    print(f"{package} -> {', '.join(available_deps)}")
                else:
                    print(f"{package}")
            else:
                print(f"{package}")

        # Show flavor meta-package as the final entry
        if flavor:
            max_group = max(ranks.values()) + 1
            print(f"\n--- Group {max_group + 1} (final) ---")
            print(f"scls-{flavor} (flavor meta-package)")

        print(f"\nTotal packages: {len(nodes)}" +
              (f" + 1 meta-package" if flavor else ""))
        print(f"Build groups: {max(ranks.values()) + 1}" +
              (f" + 1 (meta)" if flavor else ""))

        # Show statistics if requested
        if show_stats:
            stats = analyze_dependencies(packages, flavor, flavor_names)
            print("\nDependency Statistics:")
            print(f"  Packages with dependencies: {stats['packages_with_deps']}/{stats['total_packages']}")
            print(f"  Total dependency edges: {stats['total_dependencies']}")
            print(f"  Max dependencies per package: {stats['max_dependencies']}")
            if stats['most_depended_on']:
                print("\n  Most depended-on packages:")
                for pkg, count in sorted(stats['most_depended_on'].items(),
                                         key=lambda x: x[1], reverse=True)[:5]:
                    print(f"    {pkg}: {count} packages depend on it")

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Generate build order for SCLS packages')
    parser.add_argument('directory', help='Directory containing recipe YAML files')
    parser.add_argument('--flavor', '-f', help='Filter packages by flavor (e.g., macos, gcc-debug)')
    parser.add_argument('--stats', '-s', action='store_true', help='Show dependency statistics')
    parser.add_argument('--debug', '-d', action='store_true', help='Show debug information')

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a valid directory.")
        sys.exit(1)

    # Enable debug output if requested
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    build_order(args.directory, args.flavor, args.stats)


if __name__ == "__main__":
    main()