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
        urllib.request.urlretrieve(url, dest_path)
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

    # Start the bash script with stdout piped for real-time reading
    process = subprocess.Popen(cmd,cwd=cwd,env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Read and print stdout line by line as it’s produced
    for line in process.stdout:
        print(line.strip())  # strip() removes trailing newlines

    # Optionally, handle stderr if your script produces error output
    for line in process.stderr:
        print(line.strip())

    # Wait for the script to finish (optional, if you need the exit code)
    process.wait()


def setup_environment(flavor: Dict, prefix: Path, recipe: Dict = None) -> Dict[str, str]:
    """Setup build environment variables"""
    env = os.environ.copy()

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

    # Add recipe-specific environment variables for configure
    if recipe and 'configure' in recipe and 'env' in recipe['configure']:
        for key, value in recipe['configure']['env'].items():
            # Replace %{prefix} with actual prefix
            value = str(value).replace('%{prefix}', str(prefix))
            env[key] = value
            print(f"Setting {key}={value}")

    return env


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


def get_configure_args(recipe: Dict, flavor: Dict, prefix: Path) -> List[str]:
    """Get configure arguments for autotools packages"""
    args = [f"--prefix={prefix}"]

    # Add flavor-specific configure args from flavor definition
    if 'configure' in flavor['flags']:
        args.extend(flavor['flags']['configure'].split())

    # Add recipe-specific configure args
    if 'configure' in recipe and 'args' in recipe['configure']:
        for arg in recipe['configure']['args']:
            # Substitute variables
            arg = arg.replace('%{prefix}', str(prefix))
            args.append(arg)

    # Add flavor-specific args from recipe
    if 'configure' in recipe and 'flavor_args' in recipe['configure']:
        flavor_name = flavor.get('name', '')
        if flavor_name in recipe['configure']['flavor_args']:
            args.extend(recipe['configure']['flavor_args'][flavor_name])

    return args


def get_cmake_args(recipe: Dict, flavor: Dict, prefix: Path) -> List[str]:
    """Get CMake arguments"""
    args = [
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_LIBDIR=lib",
    ]

    # Add recipe-specific cmake args
    if 'configure' in recipe and 'args' in recipe['configure']:
        for arg in recipe['configure']['args']:
            arg = arg.replace('%{prefix}', str(prefix))
            args.append(arg)

    # Add flavor-specific args from recipe
    if 'configure' in recipe and 'flavor_args' in recipe['configure']:
        flavor_name = flavor.get('name', '')
        if flavor_name in recipe['configure']['flavor_args']:
            args.extend(recipe['configure']['flavor_args'][flavor_name])

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