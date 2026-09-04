"""
Improved patching functions for SCLS build system
"""

import os
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from build_common import BuildError, resolve_flavor_key


def normalize_arch(name) -> str:
    """Fold the spellings of one CPU architecture onto a single token.

    Python's platform.machine() reports 'arm64' on macOS and 'aarch64' on
    Linux for the same architecture, and 'x86_64' / 'amd64' likewise, so a
    recipe's arch: key and the host answer must be compared after folding.
    Unknown names pass through lowercased so a typo shows up as a
    never-matching patch rather than a crash.
    """
    n = str(name or '').lower()
    if n in ('arm64', 'aarch64'):
        return 'arm64'
    if n in ('x86_64', 'amd64'):
        return 'x86_64'
    return n


def host_arch() -> str:
    """Normalized architecture of the build host (see normalize_arch)."""
    return normalize_arch(platform.machine())


def get_patches_from_recipe(recipe: Dict, flavor: Dict = None, arch: str = None) -> List[Dict]:
    """
    Extract patch information from recipe - supports multiple formats:
    1. patches: [list] format (simple list of patches)
    2. patches: {all: [...], ilp64: [...], flavor: [...]} format (conditional patches)

    Conditional patches are applied based on:
    - all: always applied
    - ilp64: applied when flavor math.interface == 'ilp64'
    - lp64: applied when flavor math.interface == 'lp64' (or default)
    - <flavor_name>: applied for specific flavor (e.g., macos, debug, mkl)

    Any dict-style entry may additionally carry `arch: <name>` or
    `arch: [<name>, ...]`; the entry is then applied only when the build
    architecture (`arch` argument, default the host's) is in that set. This
    is an orthogonal filter inside a flavor list, not a flavor key: the
    macos flavor covers both Intel and Apple Silicon hosts, and a patch such
    as the aarch64-apple-darwin GCC branch belongs to one of them only.
    """
    patches = []

    if 'patches' not in recipe:
        return patches

    patch_config = recipe['patches']

    # Determine interface type from flavor
    interface = 'lp64'  # default
    flavor_name = ''
    if flavor:
        flavor_name = flavor.get('name', '')
        math_config = flavor.get('math', {})
        interface = math_config.get('interface', 'lp64')

    current_arch = host_arch() if arch is None else normalize_arch(arch)

    def add_patch_entry(patch_entry):
        """Helper to add a patch entry in either string or dict format"""
        if isinstance(patch_entry, str):
            patches.append({
                'file': patch_entry,
                'strip': 1,
                'source': 'recipe_patches'
            })
        elif isinstance(patch_entry, dict):
            if 'arch' in patch_entry:
                # An explicit key must carry a real value: a bare `arch:`
                # (YAML null) is almost certainly a mistake, and silently
                # treating it as "every architecture" would apply a
                # platform-specific patch everywhere.
                wanted = patch_entry['arch']
                if isinstance(wanted, str):
                    wanted = [wanted]
                if (not isinstance(wanted, (list, tuple))
                        or not all(isinstance(a, str) for a in wanted)):
                    raise BuildError(
                        f"Patch {patch_entry.get('file')}: 'arch' must be a "
                        f"string or a list of strings, got {wanted!r}"
                    )
                allowed = {normalize_arch(a) for a in wanted}
                if current_arch not in allowed:
                    print(f"Skipping {patch_entry.get('file')}: arch "
                          f"{sorted(allowed)} does not match build arch {current_arch}")
                    return
            patches.append({
                'file': patch_entry['file'],
                'strip': patch_entry.get('strip', 1),
                'allow_failure': patch_entry.get('allow_failure', False),
                'source': 'recipe_patches'
            })

    # Handle dict format with conditional keys
    if isinstance(patch_config, dict):
        # Apply 'all' patches (always)
        if 'all' in patch_config:
            for patch_entry in patch_config['all']:
                add_patch_entry(patch_entry)

        # Apply interface-specific patches (ilp64 or lp64)
        if interface == 'ilp64' and 'ilp64' in patch_config:
            print(f"Applying ILP64 patches (64-bit integers)")
            for patch_entry in patch_config['ilp64']:
                add_patch_entry(patch_entry)
        elif interface == 'lp64' and 'lp64' in patch_config:
            print(f"Applying LP64 patches (32-bit integers)")
            for patch_entry in patch_config['lp64']:
                add_patch_entry(patch_entry)

        # Apply flavor-specific patches. Use resolve_flavor_key so a recipe
        # with patches: {mkl: [...]} also matches concrete flavors like
        # 'gcc-mkl' / 'gcc-mkl-cuda', mirroring how flavor_args resolves.
        # Filter out the reserved keys (handled above) so resolve_flavor_key
        # can't double-apply them via the hyphen-component fallback.
        reserved = {'all', 'lp64', 'ilp64'}
        flavor_only = {k: v for k, v in patch_config.items() if k not in reserved}
        if flavor and flavor_only:
            flavor_patches = resolve_flavor_key(flavor, flavor_only)
            if flavor_patches:
                print(f"Applying flavor-specific patches for {flavor_name}")
                for patch_entry in flavor_patches:
                    add_patch_entry(patch_entry)

    # Handle simple list format (legacy)
    elif isinstance(patch_config, list):
        for patch_entry in patch_config:
            add_patch_entry(patch_entry)

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


def collect_declared_patch_files(patch_config) -> set:
    """Collect every patch filename explicitly mentioned in a patches block."""
    declared = set()

    def collect_entries(entries):
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, str):
                declared.add(entry)
            elif isinstance(entry, dict) and 'file' in entry:
                declared.add(entry['file'])

    if isinstance(patch_config, dict):
        for entries in patch_config.values():
            collect_entries(entries)
    elif isinstance(patch_config, list):
        collect_entries(patch_config)

    return declared


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


def get_all_patches(recipe: Dict, package_name: str, patches_dir: Path = Path("patches"), flavor: Dict = None, arch: str = None) -> List[Dict]:
    """
    Get all patches for a package, with smart auto-discovery
    Priority: recipe-specified patches first, then auto-discovered

    `arch` is forwarded to get_patches_from_recipe (None = build host).
    """
    patches = []

    # First, get patches specified in recipe (if any)
    recipe_patches = get_patches_from_recipe(recipe, flavor, arch)
    patches.extend(recipe_patches)

    patch_config = recipe.get('patches')
    patch_config_present = 'patches' in recipe

    # If no patches block is present, auto-discover all patches for legacy
    # recipes. Once a recipe declares patches explicitly, an empty resolved
    # list means "no patches for this flavor", not "discover everything".
    if not patch_config_present:
        print(f"No patches specified in recipe, auto-discovering patches for {package_name}...")
        discovered_patches = discover_patches_in_directory(package_name, patches_dir)
        patches.extend(discovered_patches)
    else:
        # If recipe has patches, only auto-discover additional ones not mentioned
        # anywhere in the recipe (including flavor/interface-specific sections)
        discovered_patches = discover_patches_in_directory(package_name, patches_dir)

        # Collect ALL patch filenames from the recipe, not just the resolved ones
        all_recipe_patch_files = collect_declared_patch_files(patch_config)
        # Also include the already-resolved patches
        all_recipe_patch_files.update(p['file'] for p in recipe_patches)

        additional_patches = [p for p in discovered_patches if p['file'] not in all_recipe_patch_files]
        if additional_patches:
            extras = ', '.join(p['file'] for p in additional_patches)
            raise BuildError(
                f"patches/{package_name}/ contains files not declared in the "
                f"recipe: {extras}. Either declare them in the recipe's "
                f"patches: section or remove them from the directory. "
                f"Silent auto-discovery is disabled to prevent stray files "
                f"from changing the build output."
            )

    return patches


def copy_patches_to_sources(recipe: Dict, patches_dir: Path, sources_dir: Path, package_name: str, flavor: Dict = None) -> None:
    """
    Enhanced version that copies all relevant patches to sources directory
    """
    if 'source' not in recipe:
        return

    patches = get_all_patches(recipe, package_name, patches_dir, flavor)

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


def apply_patches(source_dir: Path, recipe: Dict, package_name: str, patches_dir: Path = Path("patches"), flavor: Dict = None) -> None:
    """
    Enhanced patch application with better error handling and logging
    """
    patches = get_all_patches(recipe, package_name, patches_dir, flavor)

    if not patches:
        print(f"No patches to apply for {package_name}")
        return

    print(f"\n=== Applying {len(patches)} patches ===")

    for i, patch in enumerate(patches, 1):
        patch_file = patch['file']
        strip_level = patch['strip']
        patch_source = patch['source']

        print(f"[{i}/{len(patches)}] Applying {patch_file} (-p{strip_level}) [{patch_source}]")

        # Resolve patch location: auto-discovered patches carry an absolute
        # full_path; recipe-specified patches live under <patches_dir>/<package>/.
        patch_path = patch.get('full_path') or (patches_dir / package_name / patch_file)

        # Check if this patch is allowed to fail (opt-in via recipe)
        allow_failure = patch.get('allow_failure', False)

        if not patch_path.exists():
            msg = f"Patch file not found: {patch_file} (expected at: {patch_path})"
            if allow_failure:
                print(f"  WARNING: {msg}")
                continue
            raise BuildError(msg)

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
                msg = f"Patch {patch_file} failed to apply (return code {result.returncode})"
                if result.stderr:
                    msg += f"\n    Error: {result.stderr.strip()}"
                if result.stdout:
                    msg += f"\n    Output: {result.stdout.strip()}"
                if allow_failure:
                    print(f"  WARNING: {msg}")
                else:
                    raise BuildError(msg)

        except subprocess.TimeoutExpired:
            msg = f"Patch {patch_file} timed out"
            if allow_failure:
                print(f"  WARNING: {msg}")
            else:
                raise BuildError(msg)
        except BuildError:
            raise
        except Exception as e:
            msg = f"Failed to apply patch {patch_file}: {e}"
            if allow_failure:
                print(f"  WARNING: {msg}")
            else:
                raise BuildError(msg)


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


def apply_configure_environment(
    env: Dict[str, str],
    recipe: Dict,
    flavor: Dict,
    prefix: Path,
    srcdir: Path = None,
    sdk: str = '',
) -> Dict[str, str]:
    """
    Apply configure-specific environment variables from recipe
    Supports operations like +=, -=, and =
    """
    if 'configure' not in recipe:
        return env

    configure_config = recipe['configure']
    flavor_name = flavor.get('name', '')

    def expand_env_value(val):
        val = str(val).replace('%{prefix}', str(prefix))
        val = val.replace('%{sdk}', sdk)
        if srcdir:
            val = val.replace('%{srcdir}', str(srcdir))
        return val

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
                        processed_env[var] = expand_env_value(val)
                    env = process_env_operations(env, processed_env)
        # Handle dict format: {"VAR": "value", "VAR2": "value2"}
        elif isinstance(env_config, dict):
            # Process variable substitution
            processed_env = {}
            for var, val in env_config.items():
                processed_env[var] = expand_env_value(val)
            env = process_env_operations(env, processed_env)

    # Apply flavor-specific configure environment. Use resolve_flavor_key
    # so 'mkl:' / 'gcc:' keys also match hyphenated flavors like
    # 'gcc-mkl-cuda', matching the rest of the flavor_args lookup paths.
    flavor_env = None
    if 'flavor_env' in configure_config:
        flavor_env = resolve_flavor_key(flavor, configure_config['flavor_env'])
    if flavor_env:
        # Handle both dict and list formats for flavor_env
        if isinstance(flavor_env, dict):
            # Dictionary format: {"VAR": "value"}
            processed_env = {}
            for var, val in flavor_env.items():
                processed_env[var] = expand_env_value(val)
            env = process_env_operations(env, processed_env)
        elif isinstance(flavor_env, list):
            # List format: [{"VAR": "value"}, {"VAR2": "value2"}]
            for env_item in flavor_env:
                if isinstance(env_item, dict):
                    processed_env = {}
                    for var, val in env_item.items():
                        processed_env[var] = expand_env_value(val)
                    env = process_env_operations(env, processed_env)

    return env
