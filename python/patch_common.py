"""
Improved patching functions for SCLS build system
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional


def get_patches_from_recipe(recipe: Dict) -> List[Dict]:
    """
    Extract patch information from recipe - simplified approach:
    1. patches: [list] format (recommended - auto-discover files)
    2. Legacy patch commands (still supported)
    """
    patches = []

    #  Simple patches list
    if 'patches' in recipe:
        for patch_entry in recipe['patches']:
            if isinstance(patch_entry, str):
                # Simple filename - default to -p1
                patches.append({
                    'file': patch_entry,
                    'strip': 1,
                    'source': 'recipe_patches'
                })
            elif isinstance(patch_entry, dict):
                # Detailed patch specification with optional strip level
                patches.append({
                    'file': patch_entry['file'],
                    'strip': patch_entry.get('strip', 1),  # Default to -p1
                    'source': 'recipe_patches'
                })
    return patches


def discover_patches_in_directory(package_name: str, patches_dir: Path = Path("patches")) -> List[Dict]:
    """
    Automatically discover all patches for a package in the patches directory
    """
    package_patches_dir = patches_dir / package_name
    patches = []

    if not package_patches_dir.exists():
        return patches

    # Find all .patch files, sorted by name
    patch_files = sorted(package_patches_dir.glob("*.patch"))

    for patch_file in patch_files:
        # Try to infer patch level from filename or content
        patch_level = infer_patch_level(patch_file)

        patches.append({
            'file': patch_file.name,
            'strip': patch_level,
            'source': 'auto_discovered',
            'full_path': patch_file
        })

    return patches


def infer_patch_level(patch_file: Path) -> int:
    """
    Try to infer the appropriate -p level for a patch by examining its content
    """
    try:
        with open(patch_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Look for diff headers to determine directory structure
        for line in lines:
            if line.startswith('---') or line.startswith('+++'):
                # Count path components
                parts = line.split()
                if len(parts) >= 2:
                    path = parts[1]
                    # Remove common prefixes like a/ b/ or timestamps
                    if path.startswith(('a/', 'b/')):
                        return 1
                    elif '/' in path:
                        # Count directory levels
                        return min(path.count('/'), 3)  # Cap at -p3

        # Default to -p1 if we can't determine
        return 1

    except Exception:
        return 1


def get_all_patches(recipe: Dict, package_name: str, patches_dir: Path = Path("patches")) -> List[Dict]:
    """
    Get all patches for a package, with smart auto-discovery
    Priority: recipe-specified patches first, then auto-discovered
    """
    patches = []

    # First, get patches specified in recipe (if any)
    recipe_patches = get_patches_from_recipe(recipe)
    patches.extend(recipe_patches)

    # If no patches specified in recipe, auto-discover all patches
    if not recipe_patches:
        print(f"No patches specified in recipe, auto-discovering patches for {package_name}...")
        discovered_patches = discover_patches_in_directory(package_name, patches_dir)
        patches.extend(discovered_patches)
    else:
        # If recipe has patches, only auto-discover additional ones not already specified
        discovered_patches = discover_patches_in_directory(package_name, patches_dir)
        recipe_patch_files = {p['file'] for p in recipe_patches}

        additional_patches = [p for p in discovered_patches if p['file'] not in recipe_patch_files]
        if additional_patches:
            print(f"Found {len(additional_patches)} additional patches not specified in recipe:")
            for patch in additional_patches:
                print(f"  - {patch['file']} (-p{patch['strip']})")
            patches.extend(additional_patches)

    return patches


def copy_patches_to_sources(recipe: Dict, patches_dir: Path, sources_dir: Path, package_name: str) -> None:
    """
    Enhanced version that copies all relevant patches to sources directory
    """
    if 'source' not in recipe:
        return

    patches = get_all_patches(recipe, package_name, patches_dir)

    if not patches:
        print(f"No patches found for {package_name}")
        return

    package_patches_dir = patches_dir / package_name

    for patch in patches:
        if 'full_path' in patch:
            # Auto-discovered patch
            src_path = patch['full_path']
        else:
            # Recipe-specified patch
            src_path = package_patches_dir / patch['file']

        if src_path.exists():
            dest = sources_dir / patch['file']
            shutil.copy2(src_path, dest)
            print(f"Copied patch to sources: {patch['file']} (strip level: {patch['strip']})")
        else:
            print(f"Warning: Patch file not found: {src_path}")


def apply_patches(source_dir: Path, recipe: Dict, package_name: str, patches_dir: Path = Path("patches")) -> None:
    """
    Enhanced patch application with better error handling and logging
    """
    patches = get_all_patches(recipe, package_name, patches_dir)

    if not patches:
        print(f"No patches to apply for {package_name}")
        return

    print(f"\n=== Applying {len(patches)} patches ===")

    for i, patch in enumerate(patches, 1):
        patch_file = patch['file']
        strip_level = patch['strip']
        patch_source = patch['source']

        print(f"[{i}/{len(patches)}] Applying {patch_file} (-p{strip_level}) [{patch_source}]")

        # Look for patch file in current directory (copied by copy_patches_to_sources)
        patch_path = patches_dir / patch_file

        if not patch_path.exists():
            print(f"  ERROR: Patch file not found: {patch_file}")
            print(f"    Expected at: {patch_path}")
            continue

        print(f"  Using patch from: {patch_path}")

        # Apply patch with absolute path
        cmd = ["patch", f"-p{strip_level}", "-i", str(patch_path)]

        try:
            result = subprocess.run(
                cmd,
                cwd=source_dir,
                capture_output=True,
                text=True,
                timeout=60  # Timeout after 60 seconds
            )

            if result.returncode == 0:
                print(f"  SUCCESS: {patch_file} applied successfully")
                if result.stdout.strip():
                    # Show patched files
                    patched_files = [line.split()[1] for line in result.stdout.split('\n')
                                     if line.startswith('patching file')]
                    if patched_files:
                        print(f"    Patched files: {', '.join(patched_files[:3])}" +
                              (f" and {len(patched_files) - 3} more" if len(patched_files) > 3 else ""))
            else:
                print(f"  WARNING: Patch {patch_file} failed to apply")
                print(f"    Return code: {result.returncode}")
                if result.stderr:
                    print(f"    Error: {result.stderr.strip()}")
                if result.stdout:
                    print(f"    Output: {result.stdout.strip()}")
                # Don't fail the build for patch failures - just warn

        except subprocess.TimeoutExpired:
            print(f"  ERROR: Patch {patch_file} timed out")
        except Exception as e:
            print(f"  ERROR: Failed to apply patch {patch_file}: {e}")


def validate_patches(recipe: Dict, package_name: str, patches_dir: Path = Path("patches")) -> bool:
    """
    Validate that all specified patches exist and are readable
    """
    patches = get_all_patches(recipe, package_name, patches_dir)
    all_valid = True

    print(f"\n=== Validating patches for {package_name} ===")

    for patch in patches:
        if 'full_path' in patch:
            patch_path = patch['full_path']
        else:
            patch_path = patches_dir / package_name / patch['file']

        if not patch_path.exists():
            print(f"  ERROR: Patch not found: {patch['file']}")
            all_valid = False
        elif not patch_path.is_file():
            print(f"  ERROR: Not a file: {patch['file']}")
            all_valid = False
        else:
            print(f"  OK: {patch['file']} (-p{patch['strip']})")

    return all_valid


def process_env_operations(env: Dict[str, str], env_ops: Dict[str, str]) -> Dict[str, str]:
    """
    Process environment variable operations like +=, -=, =

    Args:
        env: Current environment dictionary
        env_ops: Dictionary of environment operations from recipe

    Returns:
        Updated environment dictionary
    """
    for key, value in env_ops.items():
        if '+=' in value:
            # Append operation: VAR += "value"
            append_value = value.replace('+=', '').strip()
            if key in env:
                env[key] = f"{env[key]} {append_value}"
            else:
                env[key] = append_value
        elif '-=' in value:
            # Remove operation: VAR -= "value"
            remove_value = value.replace('-=', '').strip()
            if key in env:
                env[key] = env[key].replace(remove_value, '').strip()
                # Clean up multiple spaces
                env[key] = ' '.join(env[key].split())
        elif '=' in value and not value.startswith('='):
            # Assignment operation: VAR = "value" (but not starting with =)
            env[key] = value
        else:
            # Direct assignment (no operator)
            env[key] = value

    return env


def apply_configure_environment(env: Dict[str, str], recipe: Dict, flavor: Dict, prefix: Path) -> Dict[str, str]:
    """
    Apply configure-specific environment variables from recipe
    Supports operations like +=, -=, and =
    """
    if 'configure' not in recipe:
        return env

    configure_config = recipe['configure']
    flavor_name = flavor.get('name', '')

    # Apply general configure environment
    if 'env' in configure_config:
        env_config = configure_config['env']

        # Handle list format: [{"VAR": "value"}, {"VAR2": "value2"}]
        if isinstance(env_config, list):
            for env_item in env_config:
                if isinstance(env_item, dict):
                    # Process variable substitution
                    processed_env = {}
                    for var, val in env_item.items():
                        val = str(val).replace('%{prefix}', str(prefix))
                        processed_env[var] = val
                    env = process_env_operations(env, processed_env)
        # Handle dict format: {"VAR": "value", "VAR2": "value2"}
        elif isinstance(env_config, dict):
            # Process variable substitution
            processed_env = {}
            for var, val in env_config.items():
                val = str(val).replace('%{prefix}', str(prefix))
                processed_env[var] = val
            env = process_env_operations(env, processed_env)

    # Apply flavor-specific configure environment
    if 'flavor_env' in configure_config and flavor_name in configure_config['flavor_env']:
        flavor_env = configure_config['flavor_env'][flavor_name]

        # Process variable substitution
        processed_env = {}
        for var, val in flavor_env.items():
            val = str(val).replace('%{prefix}', str(prefix))
            processed_env[var] = val
        env = process_env_operations(env, processed_env)

    return env