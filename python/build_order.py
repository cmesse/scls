#!/usr/bin/env python3
import os
import glob
import yaml
from collections import defaultdict, deque
import sys
import argparse


def load_yaml_files(directory, flavor=None):
    """Load all YAML files from the specified directory and extract package info."""
    packages = []
    for filepath in glob.glob(os.path.join(directory, "*.yaml")):
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict) or 'name' not in data:
                    print(f"Warning: {filepath} does not contain a valid package name, skipping.")
                    continue

                # Check if package should be built for this flavor
                if flavor:
                    # If 'flavors' key exists, check if our flavor is in the list
                    if 'flavors' in data and flavor not in data['flavors']:
                        print(f"Skipping {data['name']} - not built for flavor '{flavor}'")
                        continue
                    # If no 'flavors' key, package is built for all flavors (default behavior)

                package = {
                    'name': data['name'],
                    'requires': data.get('requires', []),
                    'filepath': filepath,
                    'flavors': data.get('flavors', [])  # Empty list means all flavors
                }
                packages.append(package)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
    return packages


def normalize_dependencies(requires, flavor=None):
    """
    Normalize the requires field to a simple list based on flavor.

    Handles formats:
    - Simple list: ['pkg1', 'pkg2']
    - Flavor dict: {'all': ['pkg1'], 'macos': ['pkg2']}
    """
    if isinstance(requires, list):
        # Simple list format - applies to all flavors
        return requires
    elif isinstance(requires, dict):
        # Flavor-specific format
        deps = []

        # First add 'all' dependencies if present
        if 'all' in requires:
            deps.extend(requires['all'])

        # Then add flavor-specific dependencies if we have a flavor
        if flavor and flavor in requires:
            deps.extend(requires[flavor])

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


def get_effective_dependencies(package, flavor=None):
    """Get the effective list of dependencies for a package given a flavor."""
    return normalize_dependencies(package['requires'], flavor)


def build_dependency_graph(packages, flavor=None):
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
        effective_deps = get_effective_dependencies(pkg, flavor)

        for dep in effective_deps:
            if dep in available_packages:
                # Only add edges for dependencies that are in our build set
                graph[dep].add(pkg_name)
                in_degree[pkg_name] += 1
            else:
                print(
                    f"Info: Dependency '{dep}' for package '{pkg_name}' not in build set for flavor '{flavor or 'all'}'")

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


def validate_build_order(build_order, packages, flavor=None):
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
        deps = get_effective_dependencies(pkg, flavor)

        for dep in deps:
            if dep in position:  # Only check dependencies that are being built
                if position[dep] >= position[pkg_name]:
                    errors.append(f"Package '{pkg_name}' depends on '{dep}' but is scheduled before it")

    if errors:
        raise ValueError("Build order validation failed:\n  " + "\n  ".join(errors))


def analyze_dependencies(packages, flavor=None):
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
        deps = get_effective_dependencies(pkg, flavor)
        available_deps = [d for d in deps if d in available_packages]

        if available_deps:
            stats['packages_with_deps'] += 1
            stats['total_dependencies'] += len(available_deps)
            stats['max_dependencies'] = max(stats['max_dependencies'], len(available_deps))

            for dep in available_deps:
                stats['most_depended_on'][dep] += 1

    return stats


def build_order(directory, flavor=None, show_stats=False):
    """Main function to generate build order from YAML files."""
    # Load YAML files with flavor filtering
    packages = load_yaml_files(directory, flavor)
    if not packages:
        print(f"No valid YAML files found in the directory{' for flavor ' + flavor if flavor else ''}.")
        return

    print(f"\nLoaded {len(packages)} packages{' for flavor: ' + flavor if flavor else ' (all flavors)'}")

    # Build dependency graph with proper flavor handling
    graph, in_degree, nodes = build_dependency_graph(packages, flavor)

    try:
        # Perform topological sort
        ranks = topological_sort(graph, in_degree, nodes)

        # Get build order
        build_order_list = get_build_order(ranks)

        # Validate the build order
        validate_build_order(build_order_list, packages, flavor)

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
                deps = get_effective_dependencies(pkg_obj, flavor)
                available_deps = [d for d in deps if d in nodes]
                if available_deps:
                    print(f"{package} -> {', '.join(available_deps)}")
                else:
                    print(f"{package}")
            else:
                print(f"{package}")

        print(f"\nTotal packages: {len(nodes)}")
        print(f"Build groups: {max(ranks.values()) + 1}")

        # Show statistics if requested
        if show_stats:
            stats = analyze_dependencies(packages, flavor)
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