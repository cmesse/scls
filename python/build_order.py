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


def filter_dependencies_by_flavor(packages, flavor=None):
    """Filter dependencies to only include packages that are built for the given flavor."""
    if not flavor:
        return packages

    # Get list of package names that are built for this flavor
    available_packages = {pkg['name'] for pkg in packages}

    # Filter dependencies
    for pkg in packages:
        original_deps = pkg['requires'].copy()
        pkg['requires'] = [dep for dep in pkg['requires'] if dep in available_packages]

        # Report filtered dependencies
        filtered_deps = set(original_deps) - set(pkg['requires'])
        if filtered_deps:
            print(f"Info: {pkg['name']} dependencies filtered for flavor '{flavor}': {', '.join(filtered_deps)}")

    return packages


def build_dependency_graph(packages):
    """Build a dependency graph from the package list."""
    graph = defaultdict(set)
    in_degree = defaultdict(int)
    all_nodes = set()

    # Collect all package names
    for pkg in packages:
        all_nodes.add(pkg['name'])

    # Build the graph and in-degree counts
    for pkg in packages:
        for dep in pkg['requires']:
            if dep not in all_nodes:
                print(f"Warning: Dependency '{dep}' for package '{pkg['name']}' not found in available packages.")
            else:
                graph[dep].add(pkg['name'])
                in_degree[pkg['name']] += 1
        all_nodes.add(pkg['name'])

    return graph, in_degree, all_nodes


def topological_sort(graph, in_degree, nodes):
    """Perform topological sort and assign ranks to nodes."""
    ranks = {node: -1 for node in nodes}
    queue = deque(sorted(node for node in nodes if in_degree[node] == 0))

    # Assign rank 0 to nodes with no dependencies
    for node in queue:
        ranks[node] = 0

    # Process nodes in topological order
    while queue:
        node = queue.popleft()
        for neighbor in sorted(graph[node]):
            in_degree[neighbor] -= 1
            ranks[neighbor] = max(ranks[neighbor], ranks[node] + 1)
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Check for cycles or unresolved nodes
    unresolved = [node for node in nodes if in_degree[node] > 0]
    if unresolved:
        raise ValueError(f"Cycle or unresolved dependencies detected for packages: {unresolved}")

    # Assign ranks to isolated nodes
    max_rank = max(ranks.values()) if ranks else -1
    for node in nodes:
        if ranks[node] == -1:
            max_rank += 1
            ranks[node] = max_rank

    return ranks


def get_build_order(ranks):
    """Generate build order grouped by rank, sorted alphabetically."""
    max_rank = max(ranks.values())
    build_order = []
    for rank in range(max_rank + 1):
        nodes_at_rank = [node for node, node_rank in ranks.items() if node_rank == rank]
        build_order.extend((rank, node) for node in sorted(nodes_at_rank))
    return build_order


def validate_build_order(build_order, dependencies):
    """Validate that dependencies are built before dependent packages."""
    ranks = {pkg: rank for rank, pkg in build_order}
    for dependent, dependency in dependencies:
        if ranks[dependent] <= ranks[dependency]:
            raise ValueError(
                f"Invalid build order: '{dependent}' depends on '{dependency}' but is built before or at the same time.")


def build_order(directory, flavor=None):
    """Main function to generate build order from YAML files."""
    # Load YAML files with flavor filtering
    packages = load_yaml_files(directory, flavor)
    if not packages:
        print(f"No valid YAML files found in the directory{' for flavor ' + flavor if flavor else ''}.")
        return

    # Filter dependencies based on flavor
    packages = filter_dependencies_by_flavor(packages, flavor)

    # Build dependency graph
    graph, in_degree, nodes = build_dependency_graph(packages)

    # Extract explicit dependencies for validation
    dependencies = []
    for pkg in packages:
        for dep in pkg['requires']:
            if dep in nodes:
                dependencies.append((pkg['name'], dep))

    try:
        # Perform topological sort
        ranks = topological_sort(graph, in_degree, nodes)

        # Get build order
        build_order_list = get_build_order(ranks)

        # Validate the build order
        validate_build_order(build_order_list, dependencies)

        # Print the build order
        current_rank = -1
        print(f"\nBuild Order{' for flavor: ' + flavor if flavor else ' (all packages)'}:")
        for rank, package in build_order_list:
            if rank != current_rank:
                current_rank = rank
                print(f"--- Group {rank + 1} ---")
            print(package)

        print(f"\nTotal packages: {len(nodes)}")

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Generate build order for SCLS packages')
    parser.add_argument('directory', help='Directory containing recipe YAML files')
    parser.add_argument('--flavor', '-f', help='Filter packages by flavor (e.g., macos, gcc-debug)')

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a valid directory.")
        sys.exit(1)

    build_order(args.directory, args.flavor)


if __name__ == "__main__":
    main()