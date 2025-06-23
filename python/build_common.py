#!/usr/bin/env python3
"""
Common utilities for SCLS build system
Shared between mac_builder.py and rpm_builder.py
"""

import os
import sys
import yaml
import subprocess
import hashlib
import urllib.request
import tarfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class BuildError(Exception):
    """Custom exception for build errors"""
    pass


def load_yaml(filepath: Path) -> Dict:
    """Load a YAML file"""
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)

    # Force version to be a string if present at top level
    if isinstance(data, dict) and 'version' in data:
        data['version'] = str(data['version'])

    # Also handle version in source URLs
    if isinstance(data, dict) and 'source' in data and 'url' in data['source']:
        # Store original version as string for URL substitution
        if 'version' in data:
            data['source']['url'] = data['source']['url'].replace('%{version}', str(data['version']))

    return data


def load_recipe(package_name: str, recipes_dir: Path = Path("recipes")) -> Dict:
    """Load a package recipe"""
    recipe_path = recipes_dir / f"{package_name}.yaml"
    if not recipe_path.exists():
        raise BuildError(f"Recipe not found: {recipe_path}")

    # load_yaml now handles version conversion
    return load_yaml(recipe_path)


def load_flavor(flavor_name: str, flavors_dir: Path = Path("flavors")) -> Dict:
    """Load a flavor configuration"""
    flavor_path = flavors_dir / f"{flavor_name}.yaml"
    if not flavor_path.exists():
        raise BuildError(f"Flavor not found: {flavor_path}")
    return load_yaml(flavor_path)


def load_description(package_name: str, descriptions_dir: Path = Path("descriptions")) -> str:
    """Load package description"""
    desc_path = descriptions_dir / f"{package_name}.txt"
    if desc_path.exists():
        with open(desc_path, 'r') as f:
            return f.read().strip()
    return ""


def get_optimization_flags(recipe: Dict, flavor: Dict, compiler: str) -> Tuple[str, str, str]:
    """
    Get optimization flags for C, C++, and Fortran
    Combines recipe-specific optimization with flavor flags
    """
    # Get base flags from flavor
    cflags = flavor['flags'].get('cflags', '')
    cxxflags = flavor['flags'].get('cxxflags', '')
    fflags = flavor['flags'].get('fflags', '')

    # Get optimization settings from recipe
    if 'configure' in recipe and 'optimization' in recipe['configure']:
        opt = recipe['configure']['optimization']
        o_level = opt.get('O_level', 2)
        strict_aliasing = opt.get('strict_aliasing', True)

        # Add optimization level
        opt_flag = f"-O{o_level}"
        cflags += f" {opt_flag}"
        cxxflags += f" {opt_flag}"
        fflags += f" {opt_flag}"

        # Handle strict aliasing
        if not strict_aliasing:
            if compiler in ['gcc', 'g++', 'gfortran']:
                alias_flag = "-fno-strict-aliasing"
            elif compiler in ['icx', 'icpx', 'ifx']:
                alias_flag = "-fno-ansi-alias"
            elif compiler in ['clang', 'clang++']:
                alias_flag = "-fno-strict-aliasing"
            else:
                alias_flag = ""

            if alias_flag:
                cflags += f" {alias_flag}"
                cxxflags += f" {alias_flag}"

        # Add any extra flags from recipe (platform-specific)
        platform = flavor.get('platform', 'linux')
        if platform in opt:
            plat_opt = opt[platform]
            if 'cflags' in plat_opt:
                cflags += f" {plat_opt['cflags']}"
            if 'cxxflags' in plat_opt:
                cxxflags += f" {plat_opt['cxxflags']}"
            if 'fcflags' in plat_opt:
                fflags += f" {plat_opt['fcflags']}"

        # special handling for integers
        math_config = flavor.get('math', {})
        interface = math_config.get('interface', 'lp64')
        if interface == 'ilp64':
            fflags += " -fdefault-integer-8"
            cflags += " -DInt=long"
            cxxflags += " -DInt=long"

    return cflags.strip(), cxxflags.strip(), fflags.strip()


def download_source(url: str, dest_dir: Path, package_name: str, version: str) -> Path:
    """Download source tarball if not already present"""
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = url.split('/')[-1]
    dest_path = dest_dir / filename

    if dest_path.exists():
        print(f"Source already downloaded: {dest_path}")
        return dest_path

    print(f"Downloading {url}...")
    try:
        #urllib.request.urlretrieve(url, dest_path)
        cmd = ['curl', '-O', '-L', url]
        run_command(cmd, cwd=dest_dir, env={}, phase="Download source")
        print(f"Downloaded to {dest_path}")
        return dest_path
    except Exception as e:
        raise BuildError(f"Failed to download source: {e}")


def extract_source(tarball: Path, work_dir: Path, package_name: str, version: str) -> Path:
    """Extract source tarball and return the extracted directory"""
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {tarball}...")
    with tarfile.open(tarball, 'r:*') as tar:
        tar.extractall(work_dir)

    # Find the extracted directory
    # Usually it's package-version, but we should check
    extracted_dirs = [d for d in work_dir.iterdir() if d.is_dir()]
    if len(extracted_dirs) == 1:
        return extracted_dirs[0]

    # Try common patterns
    for pattern in [f"{package_name}-{version}", f"{package_name}_{version}", package_name]:
        extracted_dir = work_dir / pattern
        if extracted_dir.exists():
            return extracted_dir

    raise BuildError(f"Could not find extracted source directory in {work_dir}")


def copy_patches_to_sources(recipe: Dict, patches_dir: Path, sources_dir: Path) -> None:
    """Copy patches from version-controlled patches/ to sources directory"""
    if 'source' not in recipe:
        return

    package_name = recipe['name']
    package_patches_dir = patches_dir / package_name

    if not package_patches_dir.exists():
        return

    # Copy all patches for this package
    for patch_file in package_patches_dir.glob("*.patch"):
        dest = sources_dir / patch_file.name
        shutil.copy2(patch_file, dest)
        print(f"Copied patch to sources: {patch_file.name}")


def apply_patches(source_dir: Path, recipe: Dict, patches_dir: Path = Path("patches")) -> None:
    """Apply patches if specified in recipe"""
    if 'patch' not in recipe:
        return

    package_name = recipe['name']
    package_patches_dir = patches_dir / package_name

    for patch_cmd in recipe['patch']:
        # Parse patch command (e.g., "-p1 < fix-apple-m1.patch")
        parts = patch_cmd.strip().split()
        patch_level = "-p1"  # default
        patch_file = None

        for i, part in enumerate(parts):
            if part.startswith("-p"):
                patch_level = part
            elif part == "<" and i + 1 < len(parts):
                patch_file = parts[i + 1]

        if not patch_file:
            print(f"Warning: Could not parse patch command: {patch_cmd}")
            continue

        patch_path = package_patches_dir / patch_file
        if not patch_path.exists():
            print(f"Warning: Patch file not found: {patch_path}")
            continue

        print(f"Applying patch: {patch_file}")
        cmd = ["patch", patch_level, "-i", str(patch_path)]
        result = subprocess.run(cmd, cwd=source_dir, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Warning: Patch failed: {result.stderr}")


def run_command(cmd: List[str], cwd: Path, env: Dict[str, str], phase: str) -> None:
    """Run a command with proper error handling"""
    print(f"\n=== Running {phase} ===")
    print(f"Command: {' '.join(cmd)}")
    print(f"Directory: {cwd}")

    # Start the process
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    # Read output line by line
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            print(line.rstrip())

    # Get the return code
    returncode = process.poll()

    if returncode != 0:
        raise BuildError(f"{phase} failed with return code {returncode}")


def should_build_package(recipe: Dict, flavor: Dict) -> bool:
    """
    Check if a package should be built for a given flavor.
    If no 'flavors' list in recipe, build for all flavors.
    If 'flavors' list exists, only build if flavor is in the list.
    """
    flavor_name = flavor.get('name', '')

    # No flavors specified = build for all
    if 'flavors' not in recipe:
        return True

    # Check if current flavor is in the allowed list
    return flavor_name in recipe['flavors']


def get_configure_args(recipe: Dict, host: str, flavor: Dict, prefix: Path, install_prefix: Path) -> List[str]:
    """Get configure arguments for autotools packages"""
    args = [f"--prefix={install_prefix}"]

    # Get defaults configuration if it exists
    defaults = recipe.get('configure', {}).get('defaults', {})

    # Always check the value of 'shared' - default to True if not specified
    # This means: if 'defaults' doesn't exist, use True
    #            if 'defaults' exists but 'shared' is not in it, use True
    #            if 'defaults' exists and 'shared' is in it, use its value
    use_shared = defaults.get('shared', True)

    if use_shared:
        args.extend(["--enable-shared", "--disable-static"])

    # Same logic for host_flags
    use_host_flags = defaults.get('host_flags', True)
    if use_host_flags:
        args.extend([
            f"--host={host}",
            f"--build={host}",
            f"--target={host}"
        ])

    # Add flavor-specific configure args from flavor definition
    if 'configure' in flavor.get('flags', {}):
        args.extend(flavor['flags']['configure'].split())

    # Add recipe-specific configure args
    if 'configure' in recipe and 'args' in recipe['configure']:
        for arg in recipe['configure']['args']:
            # Substitute variables
            arg = arg.replace('%{prefix}', str(prefix))
            arg = arg.replace('%{install_prefix}', str(install_prefix))
            args.append(arg)

    # Add flavor-specific args from recipe
    if 'configure' in recipe and 'flavor_args' in recipe['configure']:
        flavor_name = flavor.get('name', '')
        if flavor_name in recipe['configure']['flavor_args']:
            for arg in recipe['configure']['flavor_args'][flavor_name]:
                # Substitute variables in flavor args too
                arg = arg.replace('%{prefix}', str(prefix))
                arg = arg.replace('%{install_prefix}', str(install_prefix))
                args.append(arg)

    return args


def get_cmake_args(recipe: Dict, host: str, flavor: Dict, prefix: Path, install_prefix: Path) -> List[str]:
    """Get CMake arguments"""
    args = [
        f"-DCMAKE_INSTALL_PREFIX={install_prefix}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_LIBDIR=lib",
    ]

    # Get defaults configuration if it exists
    defaults = recipe.get('configure', {}).get('defaults', {})

    # Check if we should add host/cross-compilation flags
    use_host_flags = defaults.get('host_flags', True)
    if use_host_flags:
        # For CMake, we can set the system name based on the host triple
        if 'darwin' in host:
            args.append("-DCMAKE_SYSTEM_NAME=Darwin")
        elif 'linux' in host:
            args.append("-DCMAKE_SYSTEM_NAME=Linux")

        # Add processor based on host triple
        if host.startswith('x86_64'):
            args.append("-DCMAKE_SYSTEM_PROCESSOR=x86_64")
        elif host.startswith('aarch64'):
            args.append("-DCMAKE_SYSTEM_PROCESSOR=aarch64")
        elif host.startswith('arm'):
            args.append("-DCMAKE_SYSTEM_PROCESSOR=arm")

    # Handle shared/static libraries
    use_shared = defaults.get('shared', True)
    if use_shared:
        args.append("-DBUILD_SHARED_LIBS=ON")
    else:
        args.append("-DBUILD_SHARED_LIBS=OFF")

    # Add recipe-specific cmake args
    if 'configure' in recipe and 'args' in recipe['configure']:
        for arg in recipe['configure']['args']:
            # Substitute variables
            arg = arg.replace('%{prefix}', str(prefix))
            arg = arg.replace('%{install_prefix}', str(install_prefix))
            args.append(arg)

    # Add flavor-specific args from recipe
    if 'configure' in recipe and 'flavor_args' in recipe['configure']:
        flavor_name = flavor.get('name', '')
        if flavor_name in recipe['configure']['flavor_args']:
            for arg in recipe['configure']['flavor_args'][flavor_name]:
                # Substitute variables in flavor args too
                arg = arg.replace('%{prefix}', str(prefix))
                arg = arg.replace('%{install_prefix}', str(install_prefix))
                args.append(arg)

    return args


def get_parallel_jobs() -> int:
    """Get number of parallel build jobs"""
    try:
        import multiprocessing
        return min(multiprocessing.cpu_count(), 64)
    except:
        return 4


def clean_libtool_files(prefix: Path) -> None:
    """Remove .la files from installation"""
    for la_file in prefix.rglob("*.la"):
        print(f"Removing {la_file}")
        la_file.unlink()


def get_patches_from_recipe(recipe: Dict) -> List[Dict]:
    """
    Extract patch information from recipe - simplified approach:
    1. patches: [list] format (recommended - auto-discover files)
    2. Legacy patch commands (still supported)
    """
    patches = []

    # Method 1: Simple patches list (recommended)
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

    # Method 2: Legacy patch commands (for backward compatibility)
    elif 'patch' in recipe:
        for patch_cmd in recipe['patch']:
            # Parse patch command (e.g., "-p1 < fix-apple-m1.patch")
            parts = patch_cmd.strip().split()
            patch_level = 1  # default
            patch_file = None

            for i, part in enumerate(parts):
                if part.startswith("-p"):
                    try:
                        patch_level = int(part[2:])
                    except ValueError:
                        patch_level = 1
                elif part == "<" and i + 1 < len(parts):
                    patch_file = parts[i + 1]
                elif part.endswith('.patch') and not patch_file:
                    patch_file = part

            if patch_file:
                patches.append({
                    'file': patch_file,
                    'strip': patch_level,
                    'source': 'recipe_patch_legacy'
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
        patch_path = source_dir.parent / "sources" / patch_file
        if not patch_path.exists():
            # Try in patches directory
            patch_path = patches_dir / package_name / patch_file

        if not patch_path.exists():
            print(f"  ERROR: Patch file not found: {patch_file}")
            continue

        # Apply patch
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


# Updated function signatures for compatibility
def copy_patches_to_sources_compat(recipe: Dict, patches_dir: Path, sources_dir: Path) -> None:
    """Compatibility wrapper for existing code"""
    package_name = recipe.get('name', '')
    if package_name:
        copy_patches_to_sources(recipe, patches_dir, sources_dir, package_name)


def apply_patches_compat(source_dir: Path, recipe: Dict, patches_dir: Path = Path("patches")) -> None:
    """Compatibility wrapper for existing code"""
    package_name = recipe.get('name', '')
    if package_name:
        apply_patches(source_dir, recipe, package_name, patches_dir)


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
        value_str = str(value).strip()

        if '+=' in value_str:
            # Append operation: VAR += "value"
            append_value = value_str.replace('+=', '').strip()
            if key in env:
                # Add space between existing and new value
                env[key] = f"{env[key]} {append_value}"
            else:
                env[key] = append_value
        elif '-=' in value_str:
            # Remove operation: VAR -= "value"
            remove_value = value_str.replace('-=', '').strip()
            if key in env:
                env[key] = env[key].replace(remove_value, '').strip()
                # Clean up multiple spaces
                env[key] = ' '.join(env[key].split())
        else:
            # Direct assignment (= or no operator)
            env[key] = value_str

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

def setup_environment(flavor: Dict, prefix: Path, srcdir: Path, recipe: Dict = None) -> Dict[str, str]:
    """Setup build environment variables"""
    env = os.environ.copy()

    flavor_name = flavor.get('name', '')

    # Compiler setup
    compilers = flavor.get('compilers', {})
    env['CC'] = compilers.get('cc', 'gcc')
    env['CXX'] = compilers.get('cxx', 'g++')
    env['FC'] = compilers.get('fc', 'gfortran')
    env['F77'] = env['FC']
    env['FF'] = env['FC']

    # Path setup - PREPEND to ensure our binaries are found first
    env['PATH'] = f"{prefix}/bin:{env.get('PATH', '')}"
    env['PKG_CONFIG_PATH'] = f"{prefix}/lib/pkgconfig:{env.get('PKG_CONFIG_PATH', '')}"

    # Library path setup
    if flavor['platform'] == 'macos':
        env['DYLD_LIBRARY_PATH'] = f"{prefix}/lib:{env.get('DYLD_LIBRARY_PATH', '')}"
    else:
        env['LD_LIBRARY_PATH'] = f"{prefix}/lib:{env.get('LD_LIBRARY_PATH', '')}"

    # Add recipe-specific environment variables (legacy support - FIXED)
    if recipe and 'configure' in recipe and 'env' in recipe['configure']:
        env_config = recipe['configure']['env']

        # Handle both dict and list formats
        if isinstance(env_config, dict):
            # Dictionary format: {"VAR": "value"}
            for key, value in env_config.items():
                value = str(value).replace('%{prefix}', str(prefix))
                value = str(value).replace('%{srcdir}', str(srcdir))
                env[key] = value
                print(f"Setting {key}={value}")
        elif isinstance(env_config, list):
            # List format: [{"VAR": "value"}, {"VAR2": "value2"}]
            for env_item in env_config:
                if isinstance(env_item, dict):
                    for key, value in env_item.items():
                        value = str(value).replace('%{prefix}', str(prefix))
                        value = str(value).replace('%{srcdir}', str(srcdir))
                        env[key] = value
                        print(f"Setting {key}={value}")

        # Handle flavor-specific environment
        if 'flavor_env' in recipe['configure']:
            if flavor_name in recipe['configure']['flavor_env']:
                for key, value in recipe['configure']['flavor_env'][flavor_name].items():
                    value = str(value).replace('%{prefix}', str(prefix))
                    value = str(value).replace('%{srcdir}', str(srcdir))
                    env[key] = value
                    print(f"Setting {key}={value}")
    return env