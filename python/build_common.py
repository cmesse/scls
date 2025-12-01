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


def add_rpath_for_libdirs(ldflags: str, platform: str = 'linux') -> str:
    """
    Add rpath entries for every -L directory in ldflags.

    This ensures that libraries can be found at runtime without
    needing to set LD_LIBRARY_PATH or DYLD_LIBRARY_PATH.

    The rpath is inserted immediately after each -L flag, before any -l flags.
    Example: "-L/opt/scls/lib -lz" becomes "-L/opt/scls/lib -Wl,-rpath,/opt/scls/lib -lz"

    Args:
        ldflags: The linker flags string
        platform: 'linux' or 'macos' (affects rpath syntax)

    Returns:
        ldflags with rpath entries added for each -L path
    """
    if not ldflags:
        return ldflags

    # Collect existing rpaths to avoid duplicates
    existing_rpaths = set()
    for token in ldflags.split():
        if '-rpath' in token:
            # Extract path from -Wl,-rpath,/path or -Wl,-rpath=/path
            if ',' in token:
                parts = token.split(',')
                for part in parts:
                    if part.startswith('/') or part.startswith('='):
                        existing_rpaths.add(part.lstrip('='))
            elif '=' in token:
                existing_rpaths.add(token.split('=')[-1])

    # Process tokens and insert rpath after each -L
    tokens = ldflags.split()
    result_tokens = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith('-L'):
            if token == '-L' and i + 1 < len(tokens):
                # -L /path/to/lib (space separated)
                lib_path = tokens[i + 1]
                result_tokens.append(token)
                result_tokens.append(lib_path)
                if lib_path not in existing_rpaths:
                    result_tokens.append(f'-Wl,-rpath,{lib_path}')
                    existing_rpaths.add(lib_path)
                i += 2
            else:
                # -L/path/to/lib (no space)
                lib_path = token[2:]
                result_tokens.append(token)
                if lib_path not in existing_rpaths:
                    result_tokens.append(f'-Wl,-rpath,{lib_path}')
                    existing_rpaths.add(lib_path)
                i += 1
        else:
            result_tokens.append(token)
            i += 1

    return ' '.join(result_tokens)


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


def get_interface_args(recipe: Dict, flavor: Dict, section: str = 'configure') -> List[str]:
    """
    Get arguments specific to LP64 or ILP64 interface.

    Checks the recipe for 'lp64_args' and 'ilp64_args' keys under the specified
    section and returns the appropriate list based on the flavor's math.interface setting.

    Args:
        recipe: The package recipe dictionary
        flavor: The flavor configuration dictionary
        section: Which section to look in ('configure' or 'build')

    Returns:
        List of arguments for the current interface type
    """
    args = []

    if section not in recipe:
        return args

    section_config = recipe[section]

    # Get interface type from flavor (default to lp64)
    math_config = flavor.get('math', {})
    interface = math_config.get('interface', 'lp64')

    # Get interface-specific args
    if interface == 'ilp64' and 'ilp64_args' in section_config:
        ilp64_args = section_config['ilp64_args']
        if isinstance(ilp64_args, list):
            args.extend(ilp64_args)
        print(f"Adding ILP64 {section} args: {ilp64_args}")
    elif interface == 'lp64' and 'lp64_args' in section_config:
        lp64_args = section_config['lp64_args']
        if isinstance(lp64_args, list):
            args.extend(lp64_args)
        print(f"Adding LP64 {section} args: {lp64_args}")

    return args


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
        # Help CMake find libraries/headers in our prefix (needed for try_run tests)
        f"-DCMAKE_PREFIX_PATH={prefix}",
        f"-DCMAKE_LIBRARY_PATH={prefix}/lib",
        f"-DCMAKE_INCLUDE_PATH={prefix}/include",
        # Pass linker flags so libraries in our prefix are found at link time
        f"-DCMAKE_SHARED_LINKER_FLAGS=-L{prefix}/lib -Wl,-rpath,{prefix}/lib",
        f"-DCMAKE_EXE_LINKER_FLAGS=-L{prefix}/lib -Wl,-rpath,{prefix}/lib",
    ]

    # Get defaults configuration if it exists
    defaults = recipe.get('configure', {}).get('defaults', {})

    # Check if we should add host/cross-compilation flags
    # NOTE: For native builds, do NOT set CMAKE_SYSTEM_NAME or CMAKE_SYSTEM_PROCESSOR
    # as this tells CMake it's cross-compiling and disables try_run() tests.
    # These should only be set for actual cross-compilation scenarios.
    use_host_flags = defaults.get('host_flags', True)
    cross_compile = defaults.get('cross_compile', False)
    if use_host_flags and cross_compile:
        # Only set these for actual cross-compilation
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


# Patch functions moved to patch_common.py to avoid duplication

def setup_environment(flavor: Dict, prefix: Path, srcdir: Path, recipe: Dict = None) -> Dict[str, str]:
    """Setup build environment variables"""
    env = os.environ.copy()

    flavor_name = flavor.get('name', '')

    # Check if this is a bootstrap package (needs system compilers before GCC is built)
    is_bootstrap = recipe.get('bootstrap', False) if recipe else False

    # Compiler setup - use bootstrap compilers if available and package is bootstrap
    if is_bootstrap and 'bootstrap_compilers' in flavor:
        compilers = flavor['bootstrap_compilers']
        print(f"Using bootstrap compilers (bootstrap package)")
    else:
        compilers = flavor.get('compilers', {})

    env['CC'] = compilers.get('cc', 'gcc')
    env['CXX'] = compilers.get('cxx', 'g++')
    # Fortran compiler - bootstrap packages typically don't need Fortran,
    # but fall back to gfortran from default compilers if needed
    env['FC'] = compilers.get('fc', flavor.get('compilers', {}).get('fc', 'gfortran'))
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


def check_package_installed(prefix: Path, package_name: str) -> bool:
    """
    Check if a package is installed by looking for its registry entry.

    Falls back to pkg-config if registry entry doesn't exist.

    Args:
        prefix: The installation prefix (e.g., /opt/scls)
        package_name: Name of the package to check

    Returns:
        True if package is found in registry or via pkg-config
    """
    # First check the registry
    registry_file = prefix / "share" / "scls" / "registry" / f"{package_name}.yaml"
    if registry_file.exists():
        return True

    # Fall back to pkg-config for packages not yet using registry
    pkgconfig_dir = prefix / "lib" / "pkgconfig"
    env = os.environ.copy()
    env['PKG_CONFIG_PATH'] = str(pkgconfig_dir)

    try:
        result = subprocess.run(
            ['pkg-config', '--exists', package_name],
            env=env,
            capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        # pkg-config not installed, fall back to checking .pc file directly
        pc_file = pkgconfig_dir / f"{package_name}.pc"
        return pc_file.exists()


def get_package_version(prefix: Path, package_name: str) -> Optional[str]:
    """
    Get the version of an installed package using pkg-config.

    Args:
        prefix: The installation prefix
        package_name: Name of the package

    Returns:
        Version string or None if not found
    """
    pkgconfig_dir = prefix / "lib" / "pkgconfig"
    env = os.environ.copy()
    env['PKG_CONFIG_PATH'] = str(pkgconfig_dir)

    try:
        result = subprocess.run(
            ['pkg-config', '--modversion', package_name],
            env=env,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def get_package_libs(prefix: Path, package_name: str) -> Optional[str]:
    """
    Get the link flags for a package using pkg-config.

    Args:
        prefix: The installation prefix
        package_name: Name of the package

    Returns:
        Link flags string or None if not found
    """
    pkgconfig_dir = prefix / "lib" / "pkgconfig"
    env = os.environ.copy()
    env['PKG_CONFIG_PATH'] = str(pkgconfig_dir)

    try:
        result = subprocess.run(
            ['pkg-config', '--libs', package_name],
            env=env,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def get_package_cflags(prefix: Path, package_name: str) -> Optional[str]:
    """
    Get the compiler flags for a package using pkg-config.

    Args:
        prefix: The installation prefix
        package_name: Name of the package

    Returns:
        Compiler flags string or None if not found
    """
    pkgconfig_dir = prefix / "lib" / "pkgconfig"
    env = os.environ.copy()
    env['PKG_CONFIG_PATH'] = str(pkgconfig_dir)

    try:
        result = subprocess.run(
            ['pkg-config', '--cflags', package_name],
            env=env,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


# =============================================================================
# SCLS Registry Functions
# =============================================================================

def get_package_dependencies(recipe: Dict, flavor_name: str = None) -> List[str]:
    """
    Get the list of dependencies for a package, including implicit gcc dependency.

    Args:
        recipe: The package recipe
        flavor_name: Optional flavor name for flavor-specific dependencies

    Returns:
        List of dependency package names
    """
    deps = []

    # Non-bootstrap packages implicitly depend on gcc
    is_bootstrap = recipe.get('bootstrap', False)
    if not is_bootstrap and recipe.get('name') != 'gcc':
        deps.append('gcc')

    # Get explicit requires from recipe
    requires = recipe.get('requires', [])

    if isinstance(requires, list):
        deps.extend(requires)
    elif isinstance(requires, dict):
        # Add 'all' dependencies
        if 'all' in requires:
            deps.extend(requires['all'])
        # Add flavor-specific dependencies
        if flavor_name and flavor_name in requires:
            deps.extend(requires[flavor_name])

    # Remove duplicates while preserving order
    seen = set()
    unique_deps = []
    for dep in deps:
        if dep not in seen:
            seen.add(dep)
            unique_deps.append(dep)

    return unique_deps


def parse_pc_file(pc_file: Path, prefix: Path) -> tuple[Optional[str], Optional[str]]:
    """
    Parse a .pc file directly to extract Cflags and Libs.

    This is used as a fallback when pkg-config is not available.

    Args:
        pc_file: Path to the .pc file
        prefix: Installation prefix for variable substitution

    Returns:
        Tuple of (cflags, ldflags) or (None, None) if parsing fails
    """
    if not pc_file.exists():
        return None, None

    try:
        # Read and parse the .pc file
        variables = {
            'prefix': str(prefix),
            'exec_prefix': str(prefix),
            'libdir': str(prefix / 'lib'),
            'includedir': str(prefix / 'include'),
            'sharedlibdir': str(prefix / 'lib'),
        }

        cflags = None
        ldflags = None

        with open(pc_file, 'r') as f:
            for line in f:
                line = line.strip()

                # Parse variable definitions
                if '=' in line and not line.startswith(('Libs', 'Cflags', 'Requires', 'Name', 'Description', 'Version')):
                    key, value = line.split('=', 1)
                    # Substitute variables in value
                    for var, val in variables.items():
                        value = value.replace(f'${{{var}}}', val)
                    variables[key.strip()] = value.strip()

                # Parse Cflags
                elif line.startswith('Cflags:'):
                    cflags = line[7:].strip()
                    # Substitute variables
                    for var, val in variables.items():
                        cflags = cflags.replace(f'${{{var}}}', val)

                # Parse Libs (not Libs.private)
                elif line.startswith('Libs:') and not line.startswith('Libs.private:'):
                    ldflags = line[5:].strip()
                    # Substitute variables
                    for var, val in variables.items():
                        ldflags = ldflags.replace(f'${{{var}}}', val)

        return cflags, ldflags

    except Exception as e:
        print(f"Warning: Could not parse {pc_file}: {e}")
        return None, None


def write_registry_entry(prefix: Path, recipe: Dict, flavor_name: str = None) -> None:
    """
    Write a registry entry for an installed package.

    Registry files are stored in {prefix}/share/scls/registry/{package}.yaml
    and contain package metadata, dependencies, and build flags.

    This function is designed to NEVER fail - it will always write at least
    a minimal registry entry with name and version.

    Args:
        prefix: The installation prefix
        recipe: The package recipe
        flavor_name: Optional flavor name for flavor-specific settings
    """
    # Extract essential info first - these should never fail
    package_name = recipe.get('name', 'unknown')
    version = str(recipe.get('version', '0.0.0'))

    # Create registry directory
    registry_dir = prefix / "share" / "scls" / "registry"
    try:
        registry_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"ERROR: Failed to create registry directory {registry_dir}: {e}")
        return

    registry_file = registry_dir / f"{package_name}.yaml"

    # Start with minimal entry that we'll enhance
    registry_entry = {
        'name': package_name,
        'version': version,
        'dependencies': [],
        'cflags': '',
        'ldflags': '',
        'features': {
            'fortran': False,
            'openmp': False,
            'mpi': False,
            'math': False
        },
        'has_pc_file': False
    }

    # Try to get dependencies
    try:
        registry_entry['dependencies'] = get_package_dependencies(recipe, flavor_name)
    except Exception as e:
        print(f"Warning: Failed to get dependencies for {package_name}: {e}")

    # Try to get flags from pkg-config
    pc_cflags = None
    pc_ldflags = None
    has_pc_file = False

    try:
        pc_cflags = get_package_cflags(prefix, package_name)
        pc_ldflags = get_package_libs(prefix, package_name)

        # If pkg-config failed, try parsing .pc file directly
        pkgconfig_dir = prefix / "lib" / "pkgconfig"
        pc_file = pkgconfig_dir / f"{package_name}.pc"

        if pc_cflags is None and pc_ldflags is None and pc_file.exists():
            pc_cflags, pc_ldflags = parse_pc_file(pc_file, prefix)
            if pc_cflags is not None or pc_ldflags is not None:
                has_pc_file = True
                print(f"Registry: Parsed .pc file directly for {package_name}")
        elif pc_cflags is not None or pc_ldflags is not None:
            has_pc_file = True
    except Exception as e:
        print(f"Warning: Failed to get pkg-config flags for {package_name}: {e}")

    # Default flags based on prefix
    default_cflags = f"-I{prefix}/include"
    default_ldflags = f"-L{prefix}/lib -Wl,-rpath,{prefix}/lib"

    # Check if this is a library
    is_library = False
    try:
        lib_dir = prefix / "lib"
        if lib_dir.exists():
            for pattern in [f"lib{package_name}.so*", f"lib{package_name}.dylib",
                          f"lib{package_name}.*.dylib", f"lib{package_name}.a"]:
                if list(lib_dir.glob(pattern)):
                    is_library = True
                    break
        if pc_ldflags:
            is_library = True
    except Exception as e:
        print(f"Warning: Failed to check library status for {package_name}: {e}")

    # Determine final flags
    try:
        features = recipe.get('features', {})
        registry_entry['features'] = {
            'fortran': features.get('fortran', False),
            'openmp': features.get('openmp', False),
            'mpi': features.get('mpi', False),
            'math': features.get('math', False)
        }
    except Exception as e:
        print(f"Warning: Failed to get features for {package_name}: {e}")

    # Set cflags
    if pc_cflags is not None:
        registry_entry['cflags'] = pc_cflags
    elif is_library:
        registry_entry['cflags'] = default_cflags

    # Set ldflags
    if pc_ldflags is not None:
        registry_entry['ldflags'] = pc_ldflags
    elif is_library:
        registry_entry['ldflags'] = default_ldflags

    # Add rpath for every -L directory
    try:
        if registry_entry['ldflags']:
            registry_entry['ldflags'] = add_rpath_for_libdirs(registry_entry['ldflags'])
    except Exception as e:
        print(f"Warning: Failed to add rpath for {package_name}: {e}")

    registry_entry['has_pc_file'] = has_pc_file

    # Log what we did
    if has_pc_file:
        print(f"Registry: Using flags from .pc file for {package_name}")
    elif is_library:
        print(f"Registry: No .pc file for {package_name}, using default flags")
    else:
        print(f"Registry: {package_name} is a tool (no library flags needed)")

    # Write the registry file - this is critical and must not fail silently
    try:
        with open(registry_file, 'w') as f:
            yaml.dump(registry_entry, f, default_flow_style=False, sort_keys=False)
        print(f"Registry entry written: {registry_file}")
    except Exception as e:
        print(f"ERROR: Failed to write registry file {registry_file}: {e}")
        # Try one more time with absolute minimal entry
        try:
            minimal_entry = {'name': package_name, 'version': version}
            with open(registry_file, 'w') as f:
                yaml.dump(minimal_entry, f)
            print(f"Registry: Wrote minimal entry for {package_name}")
        except Exception as e2:
            print(f"CRITICAL: Cannot write registry entry for {package_name}: {e2}")


def check_package_in_registry(prefix: Path, package_name: str) -> bool:
    """
    Check if a package is installed by looking for its registry entry.

    Args:
        prefix: The installation prefix
        package_name: Name of the package to check

    Returns:
        True if package has a registry entry
    """
    registry_file = prefix / "share" / "scls" / "registry" / f"{package_name}.yaml"
    return registry_file.exists()


def get_registry_entry(prefix: Path, package_name: str) -> Optional[Dict]:
    """
    Get the registry entry for a package.

    Args:
        prefix: The installation prefix
        package_name: Name of the package

    Returns:
        Registry entry dict or None if not found
    """
    registry_file = prefix / "share" / "scls" / "registry" / f"{package_name}.yaml"

    if not registry_file.exists():
        return None

    try:
        with open(registry_file, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Could not read registry entry for {package_name}: {e}")
        return None


def get_all_registry_entries(prefix: Path) -> Dict[str, Dict]:
    """
    Get all installed packages from the registry.

    Returns:
        Dict mapping package names to their registry entries
    """
    registry_dir = prefix / "share" / "scls" / "registry"
    packages = {}

    if not registry_dir.exists():
        return packages

    for registry_file in registry_dir.glob("*.yaml"):
        try:
            with open(registry_file, 'r') as f:
                entry = yaml.safe_load(f)
            if entry and 'name' in entry:
                packages[entry['name']] = entry
        except Exception:
            pass

    return packages


# =============================================================================
# Subpackage Functions
# =============================================================================

def get_subpackages_for_flavor(recipe: Dict, flavor_name: str) -> List[Dict]:
    """
    Get the list of subpackages that should be built for a given flavor.

    Args:
        recipe: The package recipe
        flavor_name: The flavor being built

    Returns:
        List of subpackage definitions that apply to this flavor
    """
    if 'subpackages' not in recipe:
        return []

    subpackages = []
    for subpkg_name, subpkg_config in recipe['subpackages'].items():
        # Check if this subpackage should be built for this flavor
        allowed_flavors = subpkg_config.get('flavors', None)

        if allowed_flavors is None:
            # No restriction - build for all flavors
            subpackages.append({
                'name': subpkg_name,
                **subpkg_config
            })
        elif flavor_name in allowed_flavors:
            # Flavor is in the allowed list
            subpackages.append({
                'name': subpkg_name,
                **subpkg_config
            })

    return subpackages


def get_subpackage_dependencies(subpkg_config: Dict, flavor_name: str) -> List[str]:
    """
    Get the dependencies for a subpackage.

    Args:
        subpkg_config: The subpackage configuration
        flavor_name: The flavor being built

    Returns:
        List of dependency package names
    """
    deps = []
    requires = subpkg_config.get('requires', [])

    if isinstance(requires, list):
        deps.extend(requires)
    elif isinstance(requires, dict):
        # Add 'all' dependencies
        if 'all' in requires:
            deps.extend(requires['all'])
        # Add flavor-specific dependencies
        if flavor_name in requires:
            deps.extend(requires[flavor_name])

    return deps


def match_files_to_subpackage(all_files: List[str], file_patterns: List[str], prefix: str) -> List[str]:
    """
    Match installed files to a subpackage based on glob patterns.

    Args:
        all_files: List of all installed files (with %{prefix} or absolute paths)
        file_patterns: List of glob patterns for this subpackage (e.g., ['lib/libblas.*', 'include/cblas*.h'])
        prefix: The installation prefix

    Returns:
        List of files that match the patterns
    """
    import fnmatch

    matched = []
    for file_path in all_files:
        # Normalize path: remove prefix to get relative path
        if file_path.startswith('%{prefix}'):
            rel_path = file_path[len('%{prefix}/'):]
        elif file_path.startswith(prefix):
            rel_path = file_path[len(prefix):].lstrip('/')
        else:
            rel_path = file_path

        # Check against each pattern
        for pattern in file_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                matched.append(file_path)
                break

    return matched


def split_files_by_subpackage(all_files: List[str], subpackages: List[Dict], prefix: str) -> Dict[str, List[str]]:
    """
    Split a list of installed files among subpackages.

    Args:
        all_files: List of all installed files
        subpackages: List of subpackage definitions with 'files' patterns
        prefix: The installation prefix

    Returns:
        Dict mapping subpackage names to their file lists.
        Files not matching any subpackage go to 'main'.
    """
    result = {'main': []}
    assigned_files = set()

    for subpkg in subpackages:
        subpkg_name = subpkg['name']
        file_patterns = subpkg.get('files', [])

        if not file_patterns:
            result[subpkg_name] = []
            continue

        matched = match_files_to_subpackage(all_files, file_patterns, prefix)
        result[subpkg_name] = matched
        assigned_files.update(matched)

    # Remaining files go to main package
    result['main'] = [f for f in all_files if f not in assigned_files]

    return result