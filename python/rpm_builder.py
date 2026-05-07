#!/usr/bin/env python3
"""
Enhanced RPM builder with release tags, proper parallel builds, and changelog logs
FIXED: Direct configure call instead of %configure macro to avoid unwanted arguments
"""

import copy
import os
import sys
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from typing import Dict, List

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, detect_source_directory,
    should_build_package,
    get_configure_args, get_cmake_args,
    check_package_installed,
    get_package_dependencies,
    add_rpath_for_libdirs,
    get_all_registry_entries,
    get_subpackages_for_flavor,
    get_subpackage_dependencies,
    get_interface_args,
    read_extra_packages,
    resolve_flavor_key,
    apply_flavor_overrides,
    resolve_gcc_runtime_lib,
)
from patch_common import (
    copy_patches_to_sources,
    get_all_patches,
    apply_patches,
    validate_patches,
    process_env_operations,
    apply_configure_environment
)

from math_common import (
    get_math_link_line,
    get_math_compile_flags,
    get_mkl_serial_link_line,
    get_mkl_mpi_link_line,
    get_cuda_path,
    nv_hpc_compiler_path,
    get_nv_gpu_targets )


def ensure_changelog_exists(package_name: str, version: str, release: str = "1",
                            changelogs_dir: Path = Path("changelogs")) -> None:
    """
    Ensure changelog file exists for package. Creates it if missing,
    and adds a new version entry if the current version is not present.

    Args:
        package_name: Name of the package
        version: Current package version
        release: Release number (default "1")
        changelogs_dir: Directory containing changelog files
    """
    changelogs_dir.mkdir(exist_ok=True)
    changelog_path = changelogs_dir / f"{package_name}.md"

    # Get current date in changelog format
    date_str = datetime.now().strftime('%a %b %d %Y')
    version_release = f"{version}-{release}"

    if not changelog_path.exists():
        # Create new changelog file
        content = f"""# {package_name.capitalize()} Changelog

## Version {version_release} - {date_str}
- Initial SCLS package for {package_name} {version}
"""
        with open(changelog_path, 'w') as f:
            f.write(content)
        print(f"Created changelog: {changelog_path}")
    else:
        # Check if current version already exists
        with open(changelog_path, 'r') as f:
            content = f.read()

        # Look for this version in the changelog
        # Match both "Version X.Y.Z" and "Version X.Y.Z-R" formats
        version_pattern = f"## Version {version}"
        if version_pattern not in content:
            # Add new version entry at the top (after the title)
            lines = content.split('\n')
            new_content_lines = []
            title_found = False
            version_added = False

            for line in lines:
                new_content_lines.append(line)
                # Insert new version after the title line
                if line.startswith('# ') and not title_found:
                    title_found = True
                    new_content_lines.append('')
                    new_content_lines.append(f"## Version {version_release} - {date_str}")
                    new_content_lines.append(f"- Updated to version {version}")
                    version_added = True

            # If no title was found, prepend the new version
            if not version_added:
                new_content_lines = [
                    f"# {package_name.capitalize()} Changelog",
                    '',
                    f"## Version {version_release} - {date_str}",
                    f"- Updated to version {version}",
                    ''
                ] + lines

            with open(changelog_path, 'w') as f:
                f.write('\n'.join(new_content_lines))
            print(f"Updated changelog with version {version}: {changelog_path}")
        else:
            print(f"Changelog up-to-date for {package_name} {version}")


def load_changelog(package_name: str, changelogs_dir: Path = Path("changelogs")) -> str:
    """Load package changelog from changelogs directory and convert to RPM format"""
    changelog_path = changelogs_dir / f"{package_name}.md"
    if changelog_path.exists():
        with open(changelog_path, 'r') as f:
            content = f.read().strip()

        # Convert Markdown to RPM changelog format
        changelog_lines = []
        current_author = "Christian Messe <cmesse@lbl.gov>"  # Default author

        for line in content.split('\n'):
            line = line.strip()

            # Skip empty lines and main title
            if not line or line.startswith('# '):
                continue

            if line.startswith('## Version'):  # Version headers
                # Extract version and date from "## Version X.Y.Z-R - Day Mon DD YYYY"
                parts = line.replace('## Version', '').strip()
                if ' - ' in parts:
                    version_part, date_part = parts.split(' - ', 1)
                    # Format as RPM changelog entry
                    changelog_lines.append(f"* {date_part} {current_author} - {version_part}")
                else:
                    changelog_lines.append(f"* {parts} {current_author}")

            elif line.startswith('-'):  # Bullet points
                # Keep existing bullet points
                changelog_lines.append(line)

            elif line.startswith('Author:'):  # Handle author lines if present
                current_author = line.replace('Author:', '').strip()

            elif line and not line.startswith('#'):  # Regular text
                changelog_lines.append(f"- {line}")

        return '\n'.join(changelog_lines)

    return ""


def _partition_rpms_for_install(rpm_files):
    """Split RPM files into (to_install, to_reinstall).

    An RPM goes to `to_reinstall` only when its exact NVRA is already
    installed — otherwise a plain `dnf install` will upgrade/downgrade as
    needed. This lets `scls install` pick up rebuilds of the same version
    instead of hitting the usual 'nothing to do' no-op.
    """
    to_install = []
    to_reinstall = []
    for rpm in rpm_files:
        rpm = Path(rpm)
        qp = subprocess.run(
            ['rpm', '-qp', '--queryformat',
             '%{NAME}\t%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}',
             str(rpm)],
            capture_output=True, text=True
        )
        if qp.returncode != 0 or '\t' not in qp.stdout:
            to_install.append(rpm)
            continue
        name, nvra = qp.stdout.strip().split('\t', 1)
        q = subprocess.run(
            ['rpm', '-q', '--queryformat',
             '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', name],
            capture_output=True, text=True
        )
        if q.returncode == 0 and q.stdout.strip() == nvra:
            to_reinstall.append(rpm)
        else:
            to_install.append(rpm)
    return to_install, to_reinstall


def _dnf_install_rpms(rpm_files):
    """Install or reinstall the given RPM files via dnf.

    RPMs whose exact NVRA is already installed are passed to
    `dnf reinstall`; the rest go to `dnf install`.
    """
    to_install, to_reinstall = _partition_rpms_for_install(rpm_files)
    if to_reinstall:
        cmd = ['sudo', 'dnf', 'reinstall', '-y'] + [str(r) for r in to_reinstall]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise BuildError(
                f"RPM reinstallation failed with return code {result.returncode}")
    if to_install:
        cmd = ['sudo', 'dnf', 'install', '-y'] + [str(r) for r in to_install]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise BuildError(
                f"RPM installation failed with return code {result.returncode}")


class RPMBuilder:
    def __init__(self, package: str, flavor: str):
        self.package = package
        self.flavor_name = flavor

        # Load configurations. Deepcopy both so platform/flavor/MPI overrides
        # below don't mutate cached recipe/flavor dicts that other builders
        # (or future load_recipe caching) might share.
        self.recipe = copy.deepcopy(load_recipe(package))
        self.flavor = copy.deepcopy(load_flavor(flavor))

        # Platform is always linux for RPM builder
        self.platform = 'linux'

        # Merge platform-specific recipe sections (linux:)
        # This allows recipes to have different version/source per platform
        if 'linux' in self.recipe:
            platform_section = self.recipe['linux']
            # Merge version if specified
            if 'version' in platform_section:
                self.recipe['version'] = platform_section['version']
            # Merge source if specified
            if 'source' in platform_section:
                if 'source' not in self.recipe:
                    self.recipe['source'] = {}
                self.recipe['source'].update(platform_section['source'])

        # Apply flavor-specific overrides (e.g. lbl pinning openmpi to 4.1.6).
        # Must run after the platform merge so platform-level fields are in
        # place, and before downstream code reads recipe['version'] or the
        # source URL. Mirrors unix_builder.__init__.
        self.recipe = apply_flavor_overrides(self.recipe, self.flavor)

        # Validate platform
        if self.flavor.get('platform') != 'linux':
            raise BuildError(f"Flavor {flavor} is not for Linux")

        # Check if the package is in flavor.conf's extra_packages list. Such
        # packages are foundation packages whose recipe's flavors: allowlist
        # would normally exclude them, but the host needs them anyway (e.g.
        # building gcc/binutils for the gcc flavor on RHEL 8). Listing them in
        # extra_packages is the only supported override path — there is no
        # CLI flag, since the flavor.conf entry is trackable per-host.
        is_extra = package in read_extra_packages(flavor)

        # Check if package should be built
        if not should_build_package(self.recipe, self.flavor):
            if is_extra:
                print(f"Note: {package} is not officially supported for "
                      f"flavor {flavor}; building anyway because it is "
                      f"listed in flavor.conf's extra_packages.")
            else:
                raise BuildError(
                    f"Package {package} not built for {flavor}. "
                    f"To override, add it to extra_packages: in flavor.conf."
                )

        # Check if this is a bootstrap package (needs system compilers before our GCC is built)
        self.is_bootstrap = self.recipe.get('bootstrap', False)
        if self.is_bootstrap and 'bootstrap_compilers' in self.flavor:
            print(f"Using bootstrap compilers (bootstrap package)")
            # If a Red Hat gcc-toolset is active (set by the wrapper sourcing
            # /opt/rh/gcc-toolset-N/enable), rewrite the flavor's hardcoded
            # /usr/bin/gcc bootstrap_compilers to point at the toolset's
            # binaries directly. Otherwise SPEC files would still emit
            # `export CC=/usr/bin/gcc`, defeating the purpose of the toolset.
            toolset = os.environ.get('SCLS_GCC_TOOLSET', '').strip()
            bootstrap = self.flavor['bootstrap_compilers'].copy()
            if toolset:
                ts_bin = f"/opt/rh/gcc-toolset-{toolset}/root/usr/bin"
                for key, default_basename in (('cc', 'gcc'), ('cxx', 'g++'),
                                              ('fc', 'gfortran')):
                    val = bootstrap.get(key, '')
                    # Replace any /usr/bin/<x> with the toolset path. Also
                    # handle bare names (e.g. 'gcc') by prepending ts_bin.
                    if val.startswith('/usr/bin/'):
                        bootstrap[key] = val.replace('/usr/bin/', ts_bin + '/', 1)
                    elif '/' not in val:
                        bootstrap[key] = f"{ts_bin}/{val}"
                print(f"  using gcc-toolset-{toolset} at {ts_bin}")
            # Override compilers with bootstrap compilers for this build
            self.flavor['compilers'] = bootstrap

        # Setup paths
        self.prefix = Path(self.flavor['prefix'])
        self.project_root = Path(__file__).parent.parent
        self.rpm_base = self.project_root / "rpmbuild"  # DO NOT CHANGE!!!
        self.sources_dir = self.rpm_base / "SOURCES" # DO NOT CHANGE!!!
        self.specs_dir = self.rpm_base / "SPECS" # DO NOT CHANGE!!!

        # Determine host triple based on architecture
        import platform as platform_mod
        machine = platform_mod.machine()
        if machine == 'aarch64':
            self.host = "aarch64-redhat-linux"
        else:
            self.host = "x86_64-redhat-linux"
        self.nprocs = os.cpu_count()
        self.lib_ext = '.so'  # Linux always uses .so

        # flags to be filled later
        self.cflags = ""
        self.cxxflags = ""
        self.fcflags = ""
        self.ldflags = ""

        self.math_flags = ""
        self.math_ldflags = ""

        # Extra source info for recipe references (populated during download_sources)
        self.extra_source_info = {}

        # Source directory (set during spec generation for %{srcdir} placeholder)
        self.source_dir = ""

        # Set install prefix
        if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
            configure_config = self.recipe['configure']
            self.install_prefix = self.prefix / configure_config['install_prefix']
        else:
            self.install_prefix = self.prefix

        # check for MPI
        self.mpi = False
        features = self.recipe.get('features', {})
        if 'mpi' in features:
            if features['mpi'] == True:
                self.mpi = True

                # override compilers with mpi wrappers
                # Copy first so we don't permanently mutate the flavor dict
                comp = dict(self.flavor['compilers'])
                comp['cc'] = 'mpicc'
                comp['cxx'] = 'mpicxx'
                comp['fc'] = 'mpifort'
                comp['f77'] = 'mpifort'
                comp['f90'] = 'mpifort'
                self.flavor['compilers'] = comp
                
        if 'nvidia' in self.flavor :
            self.cuda = True
            self.cuda_path = get_cuda_path(self.flavor)
            self.nv_gpu_target = get_nv_gpu_targets( self.flavor )
            self.nv_hpc_compilers = nv_hpc_compiler_path( self.flavor )
        else:
            self.cuda = False
            self.cuda_path = ''
            self.nv_gpu_target = ''
            self.nv_hpc_compilers = ''


        # MKL paths if needed. Prefer the MKLROOT env var (set by sourcing
        # /opt/intel/oneapi/setvars.sh or the equivalent module load) and
        # fall back to the standard oneAPI install location.
        if 'mkl' in self.flavor_name:
            self.mkl_root = os.environ.get('MKLROOT', '/opt/intel/oneapi/mkl/latest')
        else:
            self.mkl_root = None

        # Create directories (skip if symlink exists)
        for d in [self.sources_dir, self.specs_dir]:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)

        # Setup Jinja2
        self.jinja_env = Environment(
            loader=FileSystemLoader('templates'),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # SPEC name
        self.scls_name = f"scls-{self.flavor_name}-{self.package}"

    def get_release_string(self) -> str:
        """Get release string from recipe or default"""
        return str(self.recipe.get('release', '1'))

    def get_parallel_make_flags(self) -> str:
        """Get appropriate make flags for parallel builds"""
        if self.recipe.get('build', {}).get('parallel', True):
            return 'make %{?_smp_mflags}'
        else:
            return 'make'

    def get_test_commands(self) -> List[str]:
        """Get test commands with parallel make substitution if appropriate.

        If test.inherit_build_args is true, build args are appended to make
        invocations so that packages like OpenBLAS which expect consistent
        flags across make targets work correctly.
        """
        if 'test' not in self.recipe:
            return []

        test_config = self.recipe['test']
        commands = test_config.get('commands', [])

        # Check if parallel testing is enabled (default: True)
        parallel_tests = test_config.get('parallel', True)

        # If inherit_build_args, collect the build args string
        inherit_args = test_config.get('inherit_build_args', False)
        build_args_str = ''
        if inherit_args:
            build_args_str = ' '.join(self.get_build_args())

        # Process commands
        processed_commands = []
        for cmd in commands:
            # Expand recipe placeholders (%{prefix}, %{srcdir}, etc.)
            cmd = self.check_args([cmd])[0]
            if cmd.strip().startswith('make '):
                if inherit_args and build_args_str:
                    # Insert build args after "make "
                    cmd = cmd.replace('make ', f'make {build_args_str} ', 1)
                if parallel_tests:
                    cmd = cmd.replace('make ', 'make %{?_smp_mflags} ', 1)
            processed_commands.append(cmd)

        return processed_commands

    def get_configure_pre_post_commands(self) -> tuple[list, list]:
        """Get pre and post configure commands from recipe, including flavor-specific and platform-specific ones"""
        pre_commands = []
        post_commands = []
        flavor_name = self.flavor.get('name', '')

        if 'configure' in self.recipe:
            # General pre commands
            if 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    pre_commands.append(self.check_args([cmd])[0])

            # Flavor-specific pre commands
            flavor_pre = resolve_flavor_key(self.flavor, self.recipe['configure'].get('flavor_pre', {}))
            if flavor_pre:
                for cmd in flavor_pre:
                    pre_commands.append(self.check_args([cmd])[0])

            # Platform-specific pre commands (linux for RPM builder)
            if 'platform_pre' in self.recipe['configure'] and self.platform in self.recipe['configure']['platform_pre']:
                for cmd in self.recipe['configure']['platform_pre'][self.platform]:
                    pre_commands.append(self.check_args([cmd])[0])

            # General post commands
            if 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    post_commands.append(self.check_args([cmd])[0])

            # Flavor-specific post commands
            flavor_post = resolve_flavor_key(self.flavor, self.recipe['configure'].get('flavor_post', {}))
            if flavor_post:
                for cmd in flavor_post:
                    post_commands.append(self.check_args([cmd])[0])

        return pre_commands, post_commands

    def get_platform_env_vars(self) -> List[Dict[str, str]]:
        """Get platform-specific environment variables for SPEC file"""
        env_vars = []

        if 'configure' not in self.recipe:
            return env_vars

        platform_env = self.recipe['configure'].get('platform_env', {})
        if self.platform in platform_env:
            for var, val in platform_env[self.platform].items():
                # Apply check_args to expand placeholders
                expanded_val = self.check_args([str(val)])[0]
                # Handle += append syntax
                if expanded_val.startswith('+='):
                    env_vars.append({'name': var, 'value': expanded_val[2:], 'operation': 'append'})
                else:
                    env_vars.append({'name': var, 'value': expanded_val, 'operation': 'set'})

        return env_vars

    def check_args(self, cmd):
        cmd = [s.replace('%{prefix}', str(self.prefix)) for s in cmd]
        cmd = [s.replace('%{install_prefix}', str(self.install_prefix)) for s in cmd]
        cmd = [s.replace('%{host}', self.host) for s in cmd]
        cmd = [s.replace('%{nprocs}', str(self.nprocs)) for s in cmd]
        cmd = [s.replace('%{srcdir}', str(self.source_dir)) for s in cmd]
        cmd = [s.replace('%{cflags}', str(self.cflags)) for s in cmd]
        cmd = [s.replace('%{cxxflags}', str(self.cxxflags)) for s in cmd]
        cmd = [s.replace('%{fcflags}', str(self.fcflags)) for s in cmd]
        cmd = [s.replace('%{ldflags}', str(self.ldflags)) for s in cmd]
        cmd = [s.replace('%{math_flags}', str(self.math_flags)) for s in cmd]
        cmd = [s.replace('%{math_ldflags}', str(self.math_ldflags)) for s in cmd]
        cmd = [s.replace('%{sources}', str(self.sources_dir)) for s in cmd]
        cmd = [s.replace('%{version}', str(self.recipe['version'])) for s in cmd]
        cmd = [s.replace('%{name}', str(self.recipe['name'])) for s in cmd]
        # Compilers (from flavor, with bootstrap fallback)
        is_bootstrap = self.recipe.get('bootstrap', False)
        if is_bootstrap and 'bootstrap_compilers' in self.flavor:
            compilers = self.flavor['bootstrap_compilers']
        else:
            compilers = self.flavor.get('compilers', {})
        cmd = [s.replace('%{cc}', compilers.get('cc', 'gcc')) for s in cmd]
        cmd = [s.replace('%{cxx}', compilers.get('cxx', 'g++')) for s in cmd]
        cmd = [s.replace('%{fc}', compilers.get('fc', 'gfortran')) for s in cmd]
        # MPI compiler wrappers
        cmd = [s.replace('%{mpicc}', 'mpicc') for s in cmd]
        cmd = [s.replace('%{mpicxx}', 'mpicxx') for s in cmd]
        cmd = [s.replace('%{mpifort}', 'mpifort') for s in cmd]
        # Library extension
        cmd = [s.replace('%{libext}', self.lib_ext) for s in cmd]
        # CUDA paths and architectures
        cmd = [s.replace('%{cuda}', str(self.cuda_path)) for s in cmd]
        cuda_archs = self.flavor.get('nvidia', {}).get('architectures', '')
        cmd = [s.replace('%{cuda_architectures}', cuda_archs) for s in cmd]
        # MKL paths and linker flags (canonical definitions in math_common)
        cmd = [s.replace('%{mklroot}', str(self.mkl_root)) for s in cmd]
        mkl_linker = get_mkl_serial_link_line(self.flavor)
        mkl_mpi_linker = get_mkl_mpi_link_line(self.flavor)
        mkl_mpi_linker = mkl_mpi_linker.replace('%{prefix}', str(self.prefix))
        cmd = [s.replace('%{mkl_linker_flags}', mkl_linker) for s in cmd]
        cmd = [s.replace('%{mkl_mpi_linker_flags}', mkl_mpi_linker) for s in cmd]
        # Platform
        cmd = [s.replace('%{platform}', self.platform) for s in cmd]
        # System library paths (zlib, etc.) - check system_libraries setting in flavor
        system_libs = self.flavor.get('system_libraries', {})
        if system_libs.get('zlib', False):
            # Use system zlib (Linux)
            cmd = [s.replace('%{zlib_include}', '/usr/include') for s in cmd]
            cmd = [s.replace('%{zlib_lib}', '/usr/lib64/libz.so') for s in cmd]
        else:
            # Use our built zlib
            cmd = [s.replace('%{zlib_include}', f'{self.prefix}/include') for s in cmd]
            cmd = [s.replace('%{zlib_lib}', f'{self.prefix}/lib/libz.so') for s in cmd]
        # libgomp: ask the active gcc, so the path tracks system gcc,
        # gcc-toolset/devtoolset, and the SCLS-built gcc under `lbl`.
        if any('%{libgomp}' in s for s in cmd):
            libgomp = resolve_gcc_runtime_lib('libgomp.so.1', self.prefix)
            cmd = [s.replace('%{libgomp}', libgomp) for s in cmd]
        # Substitute extra source info (e.g., %{gmp_version}, %{gmp_tarball})
        for name, info in self.extra_source_info.items():
            cmd = [s.replace(f'%{{{name}_version}}', info['version']) for s in cmd]
            cmd = [s.replace(f'%{{{name}_tarball}}', info['tarball']) for s in cmd]
        return cmd

    def get_install_pre_post_commands(self) -> tuple[list, list]:
        """Get pre and post install commands from recipe, including flavor-specific and platform-specific ones"""
        pre_commands = []
        post_commands = []
        flavor_name = self.flavor.get('name', '')

        if 'install' in self.recipe:
            # General pre commands
            if 'pre' in self.recipe['install']:
                for cmd in self.recipe['install']['pre']:
                    # Apply check_args for %{host}, %{prefix}, etc.
                    # Rewrite prefix to BUILDROOT for RPM %install section
                    expanded = self.check_args([cmd])[0]
                    expanded = expanded.replace(str(self.prefix), '%{buildroot}%{prefix}')
                    pre_commands.append(expanded)

            # Flavor-specific pre commands
            flavor_pre = resolve_flavor_key(self.flavor, self.recipe['install'].get('flavor_pre', {}))
            if flavor_pre:
                for cmd in flavor_pre:
                    expanded = self.check_args([cmd])[0]
                    expanded = expanded.replace(str(self.prefix), '%{buildroot}%{prefix}')
                    pre_commands.append(expanded)

            # General post commands
            if 'post' in self.recipe['install']:
                for cmd in self.recipe['install']['post']:
                    # Apply check_args for %{host}, %{prefix}, etc.
                    # Rewrite prefix to BUILDROOT for RPM %install section
                    expanded = self.check_args([cmd])[0]
                    expanded = expanded.replace(str(self.prefix), '%{buildroot}%{prefix}')
                    post_commands.append(expanded)

            # Flavor-specific post commands
            flavor_post = resolve_flavor_key(self.flavor, self.recipe['install'].get('flavor_post', {}))
            if flavor_post:
                for cmd in flavor_post:
                    expanded = self.check_args([cmd])[0]
                    expanded = expanded.replace(str(self.prefix), '%{buildroot}%{prefix}')
                    post_commands.append(expanded)

            # Platform-specific post commands (linux for RPM builder)
            if 'platform_post' in self.recipe['install'] and self.platform in self.recipe['install']['platform_post']:
                for cmd in self.recipe['install']['platform_post'][self.platform]:
                    expanded = self.check_args([cmd])[0]
                    expanded = expanded.replace(str(self.prefix), '%{buildroot}%{prefix}')
                    post_commands.append(expanded)

        return pre_commands, post_commands

    def get_install_commands(self) -> list:
        """Get custom install commands from recipe (replaces default make install)"""
        commands = []
        if 'install' in self.recipe and 'commands' in self.recipe['install']:
            for cmd in self.recipe['install']['commands']:
                # Apply check_args for %{host}, %{prefix}, etc.
                commands.append(self.check_args([cmd])[0])
        return commands

    def get_build_pre_post_commands(self) -> tuple[list, list]:
        """Get pre and post build commands from recipe, including LP64/ILP64 specific ones"""
        pre_commands = []
        post_commands = []

        if 'build' in self.recipe:
            # General pre commands
            if 'pre' in self.recipe['build']:
                for cmd in self.recipe['build']['pre']:
                    pre_commands.append(self.check_args([cmd])[0])

            # LP64/ILP64 interface-specific pre commands
            interface = self.flavor.get('math', {}).get('interface', 'lp64')
            if interface == 'ilp64' and 'ilp64_pre' in self.recipe['build']:
                for cmd in self.recipe['build']['ilp64_pre']:
                    pre_commands.append(self.check_args([cmd])[0])
            elif interface == 'lp64' and 'lp64_pre' in self.recipe['build']:
                for cmd in self.recipe['build']['lp64_pre']:
                    pre_commands.append(self.check_args([cmd])[0])

            # General post commands
            if 'post' in self.recipe['build']:
                for cmd in self.recipe['build']['post']:
                    post_commands.append(self.check_args([cmd])[0])

        return pre_commands, post_commands

    def get_intel_oneapi_setup(self) -> list:
        """Get Intel OneAPI setup commands for MKL flavors.

        We avoid sourcing /opt/intel/oneapi/setvars.sh because:
        - it pollutes the build environment with dozens of unrelated vars
        - it doesn't exist on minimal Intel installs (only mkl shipped)
        - we already know MKLROOT statically, so the explicit export is enough
        """
        setup_commands = []

        if 'mkl' in self.flavor_name and self.mkl_root:
            setup_commands.append(f"export MKLROOT={self.mkl_root}")
            # Make MKL .so files discoverable at runtime during %build/%check.
            # Our binaries link against -lmkl_* but their embedded rpath only
            # points into our prefix, so the loader needs LD_LIBRARY_PATH for
            # any test executable run from the build tree.
            setup_commands.append(
                f"export LD_LIBRARY_PATH={self.mkl_root}/lib/intel64${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
            )
            # LIBRARY_PATH and CPATH are read by gcc during try_compile in
            # fresh subprocesses (e.g. cmake's BLAS finder), where our -L/-I
            # flags don't reach. Without these, projects like blaspp/lapackpp
            # report "BLAS library not found" even though MKL is installed.
            setup_commands.append(
                f"export LIBRARY_PATH={self.mkl_root}/lib/intel64${{LIBRARY_PATH:+:$LIBRARY_PATH}}"
            )
            setup_commands.append(
                f"export CPATH={self.mkl_root}/include${{CPATH:+:$CPATH}}"
            )

        # Add any flavor-specific pre-build setup
        if 'pre_build_setup' in self.flavor:
            setup_commands.extend(self.flavor['pre_build_setup'])

        return setup_commands

    def get_configure_args_for_rpm(self) -> List[str]:
        """Get configure arguments for RPM SPEC file, preserving RPM macros"""
        # Determine compilers based on MPI feature
        features = self.recipe.get('features', {})
        use_mpi = features.get('mpi', False)

        if use_mpi:
            # Use MPI compiler wrappers (env vars set in SPEC template)
            cc = 'mpicc'
            cxx = 'mpicxx'
            fc = 'mpifort'
        else:
            # Use compilers from flavor
            compilers = self.flavor.get('compilers', {})
            cc = compilers.get('cc', 'gcc')
            cxx = compilers.get('cxx', 'g++')
            fc = compilers.get('fc', 'gfortran')

        args = [
            "--prefix=%{prefix}",
            # Explicitly set compilers to avoid configure picking up system defaults
            f"CC={cc}",
            f"CXX={cxx}",
            f"FC={fc}",
            f"F77={fc}",
        ]

        # Get defaults configuration if it exists
        defaults = self.recipe.get('configure', {}).get('defaults', {})

        # Always check the value of 'shared' - default to True if not specified
        use_shared = defaults.get('shared', True)
        if use_shared:
            args.extend(["--enable-shared", "--disable-static"])

        # Same logic for host_flags
        use_host_flags = defaults.get('host_flags', True)
        if use_host_flags:
            args.extend([
                f"--host={self.host}",
                f"--build={self.host}",
                f"--target={self.host}"
            ])

        # Add recipe-specific configure args with RPM macro preservation
        if 'configure' in self.recipe and 'args' in self.recipe['configure']:
            for arg in self.recipe['configure']['args']:
                args.append(arg)

        # Add flavor-specific args from recipe
        if 'configure' in self.recipe and 'flavor_args' in self.recipe['configure']:
            flavor_specific = resolve_flavor_key(self.flavor, self.recipe['configure']['flavor_args'])
            if flavor_specific:
                args.extend(flavor_specific)

        # Add interface-specific arguments (LP64/ILP64)
        args.extend(get_interface_args(self.recipe, self.flavor))

        return args

    def get_custom_configure_args(self) -> List[str]:
        """Get configure arguments for custom configure type (e.g., PETSc, SLEPc, OpenSSL)"""
        args = []

        # Add prefix first
        args.append(f"--prefix=%{{prefix}}")

        # Get recipe-specific configure args
        if 'configure' in self.recipe and 'args' in self.recipe['configure']:
            for arg in self.recipe['configure']['args']:
                args.append(arg)

        # Add flavor-specific args from recipe
        if 'configure' in self.recipe and 'flavor_args' in self.recipe['configure']:
            flavor_specific = resolve_flavor_key(self.flavor, self.recipe['configure']['flavor_args'])
            if flavor_specific:
                args.extend(flavor_specific)

        # Add interface-specific arguments (LP64/ILP64)
        args.extend(get_interface_args(self.recipe, self.flavor))

        # Process placeholders
        args = self.check_args(args)

        return args

    def get_direct_configure_command(self) -> str:
        """
        Get direct configure command instead of using %configure macro
        This avoids the unwanted RPM default arguments
        """
        configure_type = self.recipe.get('configure', {}).get('type', 'autotools')

        if configure_type != 'autotools':
            return ""  # Only applies to autotools

        # Get our custom configure arguments with RPM macros preserved
        args = self.get_configure_args_for_rpm()

        # Build the direct configure command
        cmd_parts = ['./configure']
        cmd_parts.extend(args)

        # Format for SPEC file (with proper line continuation)
        if len(cmd_parts) == 1:
            return cmd_parts[0]

        # Multi-line format with backslash continuation
        lines = [cmd_parts[0] + ' \\']
        for arg in cmd_parts[1:-1]:
            lines.append(f'    {arg} \\')
        lines.append(f'    {cmd_parts[-1]}')  # Last line without backslash

        return '\n'.join(lines)

    def get_path_setup(self) -> str:
        """Get PATH setup to ensure SCLS binaries are found first"""
        if self.cuda :
            return f"export PATH=%{{prefix}}/bin:%{{nv_hpc_compiler}}/bin:$PATH"
        else :
            return f"export PATH=%{{prefix}}/bin:$PATH"

    def resolve_extra_sources(self) -> None:
        """Resolve extra source info from recipe references without downloading.
        This populates self.extra_source_info for use in spec generation."""
        if 'extra_sources' in self.recipe:
            for extra in self.recipe['extra_sources']:
                if 'recipe' in extra:
                    ref_recipe = load_recipe(extra['recipe'])
                    ref_version = ref_recipe['version']
                    ref_url = ref_recipe['source'].get('source0', ref_recipe['source']['url'])
                    ref_url = ref_url.replace('%{version}', ref_version)
                    extra_name = extra['recipe']
                    tarball_name = ref_url.split('/')[-1]
                    self.extra_source_info[extra_name] = {
                        'version': ref_version,
                        'tarball': tarball_name,
                        'url': ref_url
                    }

    def _render_custom_makefile(self) -> str:
        """Render a Jinja2 Makefile.inc template for custom_makefile packages (e.g. MUMPS)."""
        template_name = self.recipe.get('configure', {}).get('template')
        if not template_name:
            raise BuildError("custom_makefile type requires 'template' field in configure section")

        template = self.jinja_env.get_template(template_name)

        # Build context mirroring unix_builder.get_makefile_context
        compilers = self.flavor.get('compilers', {})
        cc = compilers.get('cc', 'gcc')

        # Optimization flags
        cflags, cxxflags, fcflags = get_optimization_flags(
            self.recipe, self.flavor, cc
        )

        oflags = '-O2'
        if 'configure' in self.recipe and 'optimization' in self.recipe['configure']:
            o_level = self.recipe['configure']['optimization'].get('O_level', 2)
            oflags = f'-O{o_level}'

        math_config = self.flavor.get('math', {})
        math_linalg = math_config.get('linalg', 'reference')
        interface = math_config.get('interface', 'lp64')

        # Version components
        version = str(self.recipe.get('version', '0.0.0'))
        version_parts = version.split('.')

        context = {
            'recipe': self.recipe,
            'flavor': self.flavor,
            'package_name': self.package,
            'version': version,
            'version_major': version_parts[0] if len(version_parts) > 0 else '0',
            'version_minor': version_parts[1] if len(version_parts) > 1 else '0',
            'version_patch': version_parts[2] if len(version_parts) > 2 else '0',
            'features': self.recipe.get('features', {}),
            'prefix': str(self.prefix),
            'install_prefix': str(self.install_prefix),
            'cc': cc,
            'cxx': compilers.get('cxx', 'g++'),
            'fc': compilers.get('fc', 'gfortran'),
            'cflags': cflags,
            'cxxflags': cxxflags,
            'fcflags': fcflags,
            # Expand %{prefix} etc. since the rendered Makefile.inc is escaped (%% → %)
            # before being written, so RPM macros would not be expanded otherwise.
            'ldflags': add_rpath_for_libdirs(self.check_args([self.flavor['flags'].get('ldflags', '')])[0], 'linux'),
            'oflags': oflags,
            'ar': 'ar',
            'interface': interface,
            'shared_libs': True,
            'lib_ext': self.lib_ext,
            'platform': 'linux',
            'host': self.host,
            'nprocs': str(self.nprocs),
            'index_size': self.recipe.get('features', {}).get('index_size', 32),
        }

        # MPI compilers
        if self.mpi:
            context.update({
                'mpicc': 'mpicc',
                'mpicxx': 'mpicxx',
                'mpifort': 'mpifort',
            })

        # Compiler family — detect from the flavor name / compiler binary.
        # Note: 'icc' is a substring of 'mpicc', so check flavor name instead.
        if 'intel' in self.flavor_name:
            context['compiler_family'] = 'intel'
        else:
            context['compiler_family'] = 'gnu'

        # Math libraries
        if math_linalg == 'mkl':
            context['math_provider'] = 'mkl'
            context['mkl_linker_flags'] = get_mkl_serial_link_line(self.flavor)
            mkl_mpi = get_mkl_mpi_link_line(self.flavor)
            context['mkl_mpi_linker_flags'] = mkl_mpi.replace('%{prefix}', str(self.prefix))
        else:
            context['math_provider'] = 'lapack'
            context['mkl_linker_flags'] = ''
            context['mkl_mpi_linker_flags'] = ''
            # OpenBLAS bundles both BLAS and LAPACK in a single library;
            # reference (lapack/blas) keeps them split. Avoid duplicates so
            # the link line lists each implementation only once.
            if math_linalg == 'openblas':
                context['blas_libs'] = '-lopenblas'
                context['lapack_libs'] = ''
            else:
                context['blas_libs'] = '-lblas'
                context['lapack_libs'] = '-llapack'
            if self.recipe.get('features', {}).get('math') == 'parallel':
                context['scalapack_libs'] = '-lscalapack'
                context['math_libs'] = f"-lscalapack {context['lapack_libs']} {context['blas_libs']}".strip()
            else:
                context['scalapack_libs'] = ''
                context['math_libs'] = f"{context['lapack_libs']} {context['blas_libs']}".strip()

        # OpenMP
        if self.recipe.get('features', {}).get('openmp', False):
            context['openmp_flag'] = '-fopenmp'
            context['openmp_libs'] = '-lgomp'
        else:
            context['openmp_flag'] = ''
            context['openmp_libs'] = ''

        return template.render(**context)

    def is_generated_package(self) -> bool:
        """Check if this is a generated package (no external source)."""
        source = self.recipe.get('source', {})
        return source.get('type') == 'generated'

    def generate_generated_spec(self) -> Path:
        """
        Generate RPM SPEC file for a generated package (no source, templates only).

        This creates a SPEC file that processes Jinja2 templates and installs
        them to the prefix. Used for packages like scls-environment.
        """
        spec_file = self.specs_dir / f"scls-{self.flavor_name}-{self.package}.spec"

        # Get templates config from recipe
        templates_config = self.recipe.get('install', {}).get('templates', [])

        # Build the %install section commands
        install_commands = [
            f"mkdir -p %{{buildroot}}%{{prefix}}/share/scls/registry",
            # lib is a symlink to lib64 (Linux From Scratch convention)
            f"mkdir -p %{{buildroot}}%{{prefix}}/lib64",
            f"ln -sf lib64 %{{buildroot}}%{{prefix}}/lib",
        ]

        # For each template, we need to include the rendered content in the SPEC
        # We'll use the jinja_env to render them now and embed the content
        from jinja2 import Environment, FileSystemLoader

        templates_dir = Path(__file__).parent.parent / "templates"
        jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Build template context
        context = {
            'flavor': self.flavor,
            'prefix': str(self.prefix),
            'package': self.package,
            'version': self.recipe['version'],
            'build_date': datetime.now().strftime('%Y-%m-%d'),
            'scls_version': '1.0',
        }

        files_list = []

        for tmpl_config in templates_config:
            src_template = tmpl_config['src']
            dest_path = tmpl_config['dest']
            file_mode = tmpl_config.get('mode', '0644')

            # Render the template
            try:
                template = jinja_env.get_template(src_template)
                rendered = template.render(**context)
            except Exception as e:
                raise BuildError(f"Failed to render template {src_template}: {e}")

            # Create install command using cat with heredoc
            full_dest = f"%{{buildroot}}%{{prefix}}/{dest_path}"
            parent_dir = str(Path(dest_path).parent)
            if parent_dir != '.':
                install_commands.append(f"mkdir -p %{{buildroot}}%{{prefix}}/{parent_dir}")

            # Escape any % characters in the content (RPM macro issue)
            escaped_content = rendered.replace('%', '%%')

            install_commands.append(f"cat > {full_dest} << 'SCLS_EOF'")
            install_commands.append(escaped_content)
            install_commands.append("SCLS_EOF")
            install_commands.append(f"chmod {file_mode} {full_dest}")

            files_list.append(f"%{{prefix}}/{dest_path}")

        # Copy plain files (no template rendering)
        files_config = self.recipe.get('install', {}).get('files', [])
        repo_root = Path(__file__).parent.parent

        for file_config in files_config:
            src_path = repo_root / file_config['src']
            dest_path = file_config['dest']
            file_mode = file_config.get('mode', '0644')

            if not src_path.exists():
                print(f"  Warning: source file not found: {src_path}")
                continue

            with open(src_path, 'r') as f:
                content = f.read()

            full_dest = f"%{{buildroot}}%{{prefix}}/{dest_path}"
            parent_dir = str(Path(dest_path).parent)
            if parent_dir != '.':
                install_commands.append(f"mkdir -p %{{buildroot}}%{{prefix}}/{parent_dir}")

            escaped_content = content.replace('%', '%%')
            install_commands.append(f"cat > {full_dest} << 'SCLS_EOF'")
            install_commands.append(escaped_content)
            install_commands.append("SCLS_EOF")
            install_commands.append(f"chmod {file_mode} {full_dest}")

            files_list.append(f"%{{prefix}}/{dest_path}")

        # Add lib/lib64 symlink (x86_64 only)
        files_list.append(f"%dir %{{prefix}}/lib64")
        files_list.append(f"%{{prefix}}/lib")

        # Add registry file
        files_list.append(f"%{{prefix}}/share/scls/registry/{self.package}.yaml")

        # Generate the SPEC file content
        spec_content = f"""# Generated SPEC file for scls-{self.flavor_name}-{self.package}
# This is a generated package - no external source

%define package_name {self.package}
%define package_version {self.recipe['version']}
%define scls_flavor {self.flavor_name}
%define prefix {self.prefix}

Name:           scls-%{{scls_flavor}}-%{{package_name}}
Version:        %{{package_version}}
Release:        1%{{?dist}}
Summary:        {self.recipe.get('summary', 'SCLS environment package')}
License:        {self.recipe.get('license', 'BSD-3-Clause')}
BuildArch:      noarch

# Pull in basic build tools so they are available for the rest of the stack
BuildRequires:  autoconf
BuildRequires:  automake
BuildRequires:  m4
BuildRequires:  make
BuildRequires:  libtool

%description
{self.recipe.get('summary', 'SCLS environment setup and activation scripts.')}

%install
{chr(10).join(install_commands)}

# Create registry entry
mkdir -p %{{buildroot}}%{{prefix}}/share/scls/registry
cat > %{{buildroot}}%{{prefix}}/share/scls/registry/{self.package}.yaml << 'SCLS_EOF'
name: {self.package}
version: "{self.recipe['version']}"
license: {self.recipe.get('license', '')}
summary: {self.recipe.get('summary', '')}
dependencies: []
cflags: ""
ldflags: ""
features:
  fortran: false
  openmp: false
  mpi: false
  math: false
has_pc_file: false
SCLS_EOF

%postun
# When the environment package is fully removed ($1 = 0, not an upgrade),
# clean up the entire flavor prefix tree.  The environment package is the
# base of the stack — if it is gone, nothing else under this prefix can
# function, so removing the tree avoids leaving stale directories behind.
#
# Defensive guards: only clean up paths under /opt/scls, and only if the
# environment marker is actually present. Anything else is a misconfigured
# prefix that we refuse to touch — refusing rather than silently rm -rf'ing
# protects users who customized their prefix to e.g. /opt or $HOME.
if [ "$1" -eq 0 ]; then
    case "%{{prefix}}" in
        /opt/scls/*|/opt/scls)
            if [ -f "%{{prefix}}/share/scls/registry/environment.yaml" ]; then
                rm -rf -- "%{{prefix}}" 2>/dev/null || true
            fi
            ;;
        *)
            echo "scls-environment %postun: refusing to remove non-SCLS prefix: %{{prefix}}" >&2
            ;;
    esac
fi

%files
{chr(10).join(files_list)}

%changelog
* {datetime.now().strftime('%a %b %d %Y')} SCLS Builder <scls@lbl.gov> - {self.recipe['version']}-1
- Initial package
"""

        # Write the SPEC file
        with open(spec_file, 'w') as f:
            f.write(spec_content)

        print(f"Generated SPEC file: {spec_file}")
        return spec_file

    def _resolve_source_directory(self) -> str:
        """Resolve the top-level source directory name for the spec file.

        Priority:
        1. Explicit source.directory in the recipe (manual override)
        2. Auto-detect by peeking inside the downloaded tarball
        3. Fall back to {name}-{version}
        """
        version = self.recipe['version']

        # 1. Explicit override in recipe
        explicit = self.recipe.get('source', {}).get('directory')
        if explicit:
            return explicit.replace('%{version}', version)

        # 2. Auto-detect from tarball
        source_url = self.recipe['source'].get('source0', self.recipe['source']['url'])
        source_url = source_url.replace('%{version}', version)
        tarball_name = source_url.split('/')[-1]
        tarball_path = self.sources_dir / tarball_name
        if tarball_path.exists():
            detected = detect_source_directory(tarball_path)
            if detected:
                if detected != f"{self.package}-{version}":
                    print(f"Auto-detected source directory: {detected}")
                return detected

        # 3. Default convention
        return f"{self.package}-{version}"

    def generate_spec(self) -> Path:
        """Generate RPM SPEC file from template"""
        # Set source_dir for %{srcdir} placeholder - in RPM context, commands run from source dir
        # so we use $PWD to reference the current (source) directory
        self.source_dir = "$PWD"

        # Resolve extra sources if not already done (for spec-only mode)
        if not self.extra_source_info:
            self.resolve_extra_sources()

        # Load template
        template_name = self.recipe.get('template', 'default.spec.j2')
        try:
            template = self.jinja_env.get_template(template_name)
        except TemplateNotFound:
            if template_name != 'default.spec.j2':
                print(f"Warning: Template '{template_name}' not found, using default.spec.j2")
            template = self.jinja_env.get_template('default.spec.j2')

        # Get optimization flags. Use self.fcflags as the single source of
        # truth for Fortran flags; the SPEC template still emits both
        # FFLAGS and FCFLAGS, fed from the same value via the context
        # dict below.
        self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
            self.recipe, self.flavor, self.flavor['compilers']['cc']
        )

        # Get math flags if math features are enabled
        features = self.recipe.get('features', {})
        if features.get('math') :
            self.math_flags = get_math_compile_flags(self.flavor, self.recipe)
            self.math_ldflags = get_math_link_line(self.flavor, self.recipe)

            # Replace %{mklroot} with actual path
            if self.mkl_root:
                self.math_flags = self.math_flags.replace('%{mklroot}', self.mkl_root)
                self.math_ldflags = self.math_ldflags.replace('%{mklroot}', self.mkl_root)

            # Add math flags to existing flags
            if self.math_flags :
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"

        # For the mkl flavor, every package may need MKL headers (e.g. C++
        # bindings, headers that #include <mkl.h> transitively), regardless
        # of whether the recipe sets `features.math`. Inject the MKL flags
        # unconditionally so they always reach CFLAGS/CXXFLAGS/FFLAGS.
        #
        # Per Intel's link-line advisor, GNU/GCC builds against MKL need:
        #   LP64  (32-bit BLAS ints): -m64 -I$MKLROOT/include
        #   ILP64 (64-bit BLAS ints): -DMKL_ILP64 -m64 -I$MKLROOT/include
        # The -DMKL_ILP64 macro toggles MKL's MKL_INT typedef from int to
        # long long; without it, headers and libs would disagree on widths.
        if 'mkl' in self.flavor_name and self.mkl_root:
            interface = self.flavor.get('math', {}).get('interface', 'lp64')
            mkl_flag_parts = ['-m64', f'-I{self.mkl_root}/include']
            if interface == 'ilp64':
                mkl_flag_parts.insert(0, '-DMKL_ILP64')
            mkl_flags = ' '.join(mkl_flag_parts)
            for flag in mkl_flag_parts:
                if flag not in self.cflags:
                    self.cflags += f" {flag}"
                if flag not in self.cxxflags:
                    self.cxxflags += f" {flag}"
                if flag not in self.fcflags:
                    self.fcflags += f" {flag}"

        # Get requirements
        build_requires, requires, pre_requires = self.get_rpm_requires()

        # Get file list
        files = self.get_file_list()

        # Exclude paths claimed by subpackages from the main %files section.
        # get_file_list collapses share/<pkg>/ into a single entry, which would
        # otherwise conflict with subpackage %files claiming share/<pkg>/examples.
        subpkg_specs = self.get_subpackages_for_spec()
        for subpkg in subpkg_specs:
            for pattern in subpkg.get('files', []):
                files.append(f"%exclude %{{prefix}}/{pattern}")

        # Load description and changelog
        description = load_description(self.package)
        if not description:
            description = self.recipe.get('description', self.recipe.get('summary', ''))

        # Format description for RPM
        description_lines = []
        for line in description.split('\n'):
            description_lines.append(line.strip())
        formatted_description = '\n'.join(description_lines).strip()

        # Ensure changelog exists and is up-to-date, then load it
        ensure_changelog_exists(self.package, self.recipe['version'], self.get_release_string())
        changelog = load_changelog(self.package)

        # Process configure environment for SPEC file
        configure_env_vars = self.get_configure_env_vars()

        # Add platform-specific environment variables
        platform_env_vars = self.get_platform_env_vars()
        configure_env_vars.extend(platform_env_vars)

        # Get parallel make command
        make_command = self.get_parallel_make_flags()

        # Get configure type
        configure_type = self.recipe.get('configure', {}).get('type', 'autotools')

        # Get direct configure command (instead of %configure)
        direct_configure_command = self.get_direct_configure_command()

        # Get pre/post commands
        configure_pre_commands, configure_post_commands = self.get_configure_pre_post_commands()
        install_pre_commands, install_post_commands = self.get_install_pre_post_commands()
        install_commands = self.get_install_commands()
        build_pre_commands, build_post_commands = self.get_build_pre_post_commands()

        # Handle custom_makefile: render the Makefile.inc template and inject it
        # as a pre-build heredoc, then treat as 'none' (plain make)
        if configure_type == 'custom_makefile':
            makefile_content = self._render_custom_makefile()
            # Escape RPM macros in the rendered content
            escaped = makefile_content.replace('%', '%%')
            makefile_heredoc = f"cat > Makefile.inc << 'SCLS_MAKEFILE_EOF'\n{escaped}\nSCLS_MAKEFILE_EOF"
            build_pre_commands.insert(0, makefile_heredoc)
            configure_type = 'none'

        # Get Intel OneAPI setup
        intel_oneapi_setup = self.get_intel_oneapi_setup()

        # Set ldflags so get_cmake_args_with_paths() and downstream
        # check_args calls see them. self.fcflags is already populated by
        # the math/MKL injection above; no resync needed.
        self.ldflags = add_rpath_for_libdirs(self.flavor['flags'].get('ldflags', ''), 'linux')

        # Get cmake args if needed
        cmake_args = []
        if configure_type == 'cmake':
            cmake_args = self.get_cmake_args_with_paths()

        # Get custom configure args if needed (for custom configure type like PETSc, SLEPc)
        configure_args = []
        if configure_type == 'custom':
            configure_args = self.get_custom_configure_args()

        # Get build args for make-based builds
        build_args = self.get_build_args()

        # Get install args
        install_args = self.get_install_args()

        # Compute registry cflags/ldflags using the same precedence as
        # build_common.write_registry_entry: recipe override (if any) > the
        # generic -I/-L defaults. The pkg-config layer runs in %post and may
        # override these at install time. Keeping the %{prefix} macro literal
        # lets RPM expand it at spec-parse time, so the on-disk YAML still
        # ends up with the absolute prefix path — matching what
        # build_common emits for the DEB/unix paths.
        recipe_registry = self.recipe.get('registry', {}) or {}
        registry_cflags = recipe_registry.get(
            'cflags', '-I%{prefix}/include'
        )
        registry_ldflags = recipe_registry.get(
            'ldflags', '-L%{prefix}/lib -Wl,-rpath,%{prefix}/lib'
        )

        # Prepare template variables
        context = {
            'flavor': self.flavor,
            'recipe': self.recipe,
            'package_name': self.package,
            'scls_name': self.scls_name,
            'version': self.recipe['version'],
            'source_directory': self._resolve_source_directory(),
            'release': self.get_release_string(),
            'description': formatted_description,
            'changelog': changelog,
            'homepage': self.recipe.get('homepage', ''),
            'license': self.recipe.get('license', ''),
            'summary': self.recipe.get('summary', ''),
            'source_url': self.recipe['source'].get(
                'source0', self.recipe['source']['url']
            ).replace('%{version}', self.recipe['version']),
            'build_requires': build_requires,
            'requires': requires,
            'pre_requires': pre_requires,
            'prefix': str(self.prefix),
            'sources': str(self.sources_dir),  # For extra sources (e.g., gmp/mpfr/mpc for GCC)
            'cflags': self.cflags,
            'cxxflags': self.cxxflags,
            'fflags': self.fcflags,
            'fcflags': self.fcflags,
            'ldflags': add_rpath_for_libdirs(self.flavor['flags'].get('ldflags', ''), 'linux'),
            'files': files,
            'changelog_date': datetime.now().strftime('%a %b %d %Y'),
            'parallel_build': self.recipe.get('build', {}).get('parallel', True),
            'make_command': make_command,
            'configure_type': configure_type,
            'direct_configure_command': direct_configure_command,  # NEW: Direct configure
            'configure_pre_commands': configure_pre_commands,  # NEW: Pre-configure commands
            'configure_post_commands': configure_post_commands,  # NEW: Post-configure commands
            'install_pre_commands': install_pre_commands,  # NEW: Pre-install commands
            'install_post_commands': install_post_commands,  # NEW: Post-install commands
            'install_commands': install_commands,  # NEW: Custom install commands (replaces make install)
            'build_pre_commands': build_pre_commands,  # NEW: Pre-build commands
            'build_post_commands': build_post_commands,  # NEW: Post-build commands
            'cmake_args': cmake_args,
            'configure_args': configure_args,  # For custom configure type (PETSc, SLEPc, OpenSSL)
            'build_args': build_args,  # For make-based builds (configure.type: none)
            'install_args': install_args,  # For install phase (e.g., PETSC_DIR)
            'configure_env_vars': configure_env_vars,
            'patches': self.get_patches(),
            'test_commands': self.get_test_commands(),
            'test_post_commands': self.check_args(self.recipe.get('test', {}).get('post', [])),
            'test_sources': self.recipe.get('test', {}).get('sources', []),
            'pre_build_setup': intel_oneapi_setup,  # UPDATED: Intel OneAPI setup
            'cuda': self.cuda_path,
            'cuda_architectures': self.flavor.get('nvidia', {}).get('architectures', ''),
            'nv_hpc_compilers' : self.nv_hpc_compilers,
            'nv_gpu_target' : self.nv_gpu_target,
            'nprocs': "$(nproc)",
            'mkl_root': self.mkl_root,
            'self.math_flags': self.math_flags,
            'math_ldflags': self.math_ldflags,
            'features': self.recipe.get('features', {}),
            'rpm_files_auto': self.recipe.get('rpm_files_auto', False),
            'skip_compiler_env': self.recipe.get('configure', {}).get('skip_compiler_env', False),
            'path_setup': self.get_path_setup(),
            'library_symlink_fixes': self.get_library_symlink_fixes(),
            'extra_source_info': self.extra_source_info,  # For recipe-referenced sources
            'package_dependencies': get_package_dependencies(self.recipe, self.flavor),
            'subpackages': self.get_subpackages_for_spec(),
            'registry_cflags': registry_cflags,
            'registry_ldflags': registry_ldflags,
        }

        # Add extra source info as individual variables (e.g., gmp_version, gmp_tarball)
        for name, info in self.extra_source_info.items():
            context[f'{name}_version'] = info['version']
            context[f'{name}_tarball'] = info['tarball']

        # Render template
        spec_content = template.render(**context)

        # Write to generated directory first
        spec_filename = f"{self.scls_name}.spec"
        generated_spec = self.specs_dir / spec_filename

        # Remove any existing file/directory with same name
        if generated_spec.exists():
            if generated_spec.is_dir():
                import shutil
                shutil.rmtree(generated_spec)
            else:
                generated_spec.unlink()

        with open(generated_spec, 'w') as f:
            f.write(spec_content)

        print(f"Generated SPEC file: {generated_spec}")
        return generated_spec

    def get_cmake_args_with_paths(self) -> List[str]:
        """Get CMake arguments with proper path substitutions"""
        args = get_cmake_args(self.recipe, self.host, self.flavor, self.prefix, self.install_prefix)

        # Add interface-specific arguments (LP64/ILP64)
        args.extend(get_interface_args(self.recipe, self.flavor))

        # MKL link-line placeholders. Non-MKL flavors never reference these
        # macros (gcc/debug recipes prescribe -lopenblas / -llapack directly),
        # so computing them unconditionally is safe.
        mkl_linker = get_mkl_serial_link_line(self.flavor)
        mkl_mpi_linker = get_mkl_mpi_link_line(self.flavor).replace(
            '%{prefix}', str(self.prefix))

        # Process arguments for MKL and CUDA paths
        processed_args = []
        for arg in args:
            # Replace CUDA path variables
            if '%{cuda}' in arg:
                arg = arg.replace('%{cuda}', self.cuda_path)
            # Replace MKL path variables
            if '%{mklroot}' in arg:
                arg = arg.replace('%{mklroot}', self.mkl_root)

            arg = arg.replace('%{cflags}', self.cflags)
            arg = arg.replace('%{cxxflags}', self.cxxflags)
            arg = arg.replace('%{fcflags}', self.fcflags)
            arg = arg.replace('%{ldflags}', self.ldflags)
            arg = arg.replace('%{math_flags}', self.math_flags)
            arg = arg.replace('%{math_ldflags}', self.math_ldflags)
            arg = arg.replace('%{mkl_linker_flags}', mkl_linker)
            arg = arg.replace('%{mkl_mpi_linker_flags}', mkl_mpi_linker)
            # Replace CUDA architectures
            cuda_archs = self.flavor.get('nvidia', {}).get('architectures', '')
            arg = arg.replace('%{cuda_architectures}', cuda_archs)
            arg = arg.replace('%{libext}', self.lib_ext)
            processed_args.append(arg)

        return processed_args

    def get_build_args(self) -> List[str]:
        """Get build arguments for make-based builds (configure.type: none)"""
        args = []

        # Add recipe build args
        if 'build' in self.recipe and 'args' in self.recipe['build']:
            args.extend(self.check_args(self.recipe['build']['args']))

        # Add flavor-specific build args
        if 'build' in self.recipe and 'flavor_args' in self.recipe['build']:
            flavor_specific = resolve_flavor_key(self.flavor, self.recipe['build']['flavor_args'])
            if flavor_specific:
                args.extend(self.check_args(flavor_specific))

        # Add LP64/ILP64 interface-specific build args
        args.extend(get_interface_args(self.recipe, self.flavor, 'build'))

        return args

    def get_install_args(self) -> List[str]:
        """Get install arguments for make install"""
        args = []

        # Add recipe install args
        if 'install' in self.recipe and 'args' in self.recipe['install']:
            args.extend(self.check_args(self.recipe['install']['args']))

        # Add flavor-specific install args
        if 'install' in self.recipe and 'flavor_args' in self.recipe['install']:
            flavor_specific = resolve_flavor_key(self.flavor, self.recipe['install']['flavor_args'])
            if flavor_specific:
                args.extend(self.check_args(flavor_specific))

        # Add LP64/ILP64 interface-specific install args
        args.extend(get_interface_args(self.recipe, self.flavor, 'install'))

        return args

    def get_rpm_requires(self) -> tuple[list, list, list]:
        """Get RPM BuildRequires, Requires, and Requires(pre) from recipe and
        flavor-specific settings.

        The pre_requires list emits `Requires(pre):` lines, used to force
        transaction ordering: every non-environment package gets a pre-dep
        on scls-<flavor>-environment so that environment's %pre scriptlet
        (and the lib -> lib64 symlink layout) is guaranteed to be in place
        before any other package's payload extracts files into %{prefix}/lib.
        Without this, dnf is free to schedule environment last, and the
        first package to install creates %{prefix}/lib as a real directory
        — which then conflicts with environment's lib symlink and breaks
        the whole transaction.
        """
        build_requires = []
        requires = []
        pre_requires = []

        # Get flavor-specific RPM requirements from recipe
        flavor_name = self.flavor_name

        # GCC dependency is handled via recipe requires section (like macOS)
        # No automatic injection - if a package needs gcc, it should list it in requires

        # Add flavor-specific build requirements
        if 'rpm_build_requires' in self.recipe:
            if isinstance(self.recipe['rpm_build_requires'], dict):
                # Flavor-specific format
                flavor_specific = resolve_flavor_key(self.flavor, self.recipe['rpm_build_requires'])
                if flavor_specific:
                    build_requires.extend(flavor_specific)
                # Also add 'all' flavors requirements if present
                if 'all' in self.recipe['rpm_build_requires']:
                    build_requires.extend(self.recipe['rpm_build_requires']['all'])
            elif isinstance(self.recipe['rpm_build_requires'], list):
                # Simple list format (applies to all flavors)
                build_requires.extend(self.recipe['rpm_build_requires'])

        # Add flavor-specific runtime requirements
        if 'rpm_requires' in self.recipe:
            if isinstance(self.recipe['rpm_requires'], dict):
                # Flavor-specific format
                flavor_specific = resolve_flavor_key(self.flavor, self.recipe['rpm_requires'])
                if flavor_specific:
                    requires.extend(flavor_specific)
                # Also add 'all' flavors requirements if present
                if 'all' in self.recipe['rpm_requires']:
                    requires.extend(self.recipe['rpm_requires']['all'])
            elif isinstance(self.recipe['rpm_requires'], list):
                # Simple list format (applies to all flavors)
                requires.extend(self.recipe['rpm_requires'])

        # Compiler requirements based on features
        features = self.recipe.get('features', {})

        # Bootstrap packages need system compilers
        if self.is_bootstrap:
            compiler_cc = self.flavor.get('bootstrap_compilers', {}).get('cc', '/usr/bin/gcc')
            if 'gcc' in compiler_cc:
                build_requires.append('gcc')
                build_requires.append('gcc-c++')
                if features.get('fortran', False):
                    build_requires.append('gcc-gfortran')

        # Standard build tools
        build_requires.extend(['make', 'git'])

        # Add recipe-specific requirements (our own packages) - with flavor support
        if 'requires' in self.recipe:
            recipe_requires = self.recipe['requires']

            # Build tools that are only needed at build time, not runtime.
            # Apply this filter to both the dict and list forms — most
            # recipes declare cmake under `requires: {all: [cmake, ...]}`
            # and we don't want to pull cmake into every package's runtime
            # closure.
            build_only_tools = {'cmake', 'autoconf', 'automake', 'libtool', 'pkg-config'}

            def _add_recipe_reqs(names):
                for req in names:
                    scls_req = f"scls-{self.flavor_name}-{req}"
                    build_requires.append(scls_req)
                    if req not in build_only_tools:
                        requires.append(scls_req)

            if isinstance(recipe_requires, dict):
                flavor_specific = resolve_flavor_key(self.flavor, recipe_requires)
                if flavor_specific:
                    _add_recipe_reqs(flavor_specific)
                if 'all' in recipe_requires:
                    _add_recipe_reqs(recipe_requires['all'])
            elif isinstance(recipe_requires, list):
                _add_recipe_reqs(recipe_requires)

        # Math library requirements based on flavor.
        # The flavor file expresses the math provider via `math.linalg`
        # ('mkl', 'openblas', 'lapack'/'reference', ...).
        math_feature = features.get('math', 'none')
        if math_feature in ['serial', 'parallel']:
            math_config = self.flavor.get('math', {})
            linalg = math_config.get('linalg', 'reference')
            if linalg == 'mkl':
                # Intel oneAPI MKL: both packages are required at runtime
                # (the -devel package owns the unversioned .so symlinks
                # against which our binaries are linked).
                requires.extend(['intel-oneapi-mkl', 'intel-oneapi-mkl-devel'])
                build_requires.extend(['intel-oneapi-mkl', 'intel-oneapi-mkl-devel'])
                # ScaLAPACK: we ship our own reference build layered on
                # MKL BLAS/LAPACK (see math_common.py for rationale).
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)
            elif linalg == 'openblas':
                # OpenBLAS provides BLAS+LAPACK via compat symlinks
                # (liblapack.so -> libopenblas.so). ScaLAPACK is a separate
                # recipe on OpenBLAS flavors.
                scls_openblas = f"scls-{self.flavor_name}-openblas"
                requires.append(scls_openblas)
                build_requires.append(scls_openblas)
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)
            elif linalg in ('reference', 'lapack'):
                # Reference BLAS/LAPACK — provided by the SCLS `lapack` recipe
                # (which produces scls-<flavor>-blas / scls-<flavor>-lapack
                # subpackages). Don't pull system blas-devel/lapack-devel.
                scls_blas = f"scls-{self.flavor_name}-blas"
                scls_lapack = f"scls-{self.flavor_name}-lapack"
                requires.extend([scls_blas, scls_lapack])
                build_requires.extend([scls_blas, scls_lapack])
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)

        # MPI requirements — use our own SCLS-built MPI, not the system package
        if features.get('mpi', False):
            scls_mpi = f"scls-{self.flavor_name}-openmpi"
            requires.append(scls_mpi)
            build_requires.append(scls_mpi)

        # Every non-environment package must have the environment package
        # installed first within the same dnf transaction (see method docstring).
        if self.package != 'environment':
            env_pkg = f"scls-{self.flavor_name}-environment"
            pre_requires.append(env_pkg)
            # Also emit a plain Requires so the steady-state dependency graph
            # records the relationship (Requires(pre) alone is a scriptlet
            # ordering hint and is not always reflected in `rpm -qR`).
            requires.append(env_pkg)

        # Remove duplicates while preserving order
        build_requires = list(dict.fromkeys(build_requires))
        requires = list(dict.fromkeys(requires))
        pre_requires = list(dict.fromkeys(pre_requires))

        return build_requires, requires, pre_requires

    def get_configure_env_vars(self) -> List[Dict[str, str]]:
        """Get configure environment variables for SPEC file"""
        env_vars = []

        env_vars.append({'name': 'PKG_CONFIG_PATH', 'value': "%{prefix}/lib/pkgconfig:/usr/lib/pkgconfig", 'operation': 'set'})

        if 'configure' not in self.recipe or 'env' not in self.recipe['configure']:
            return env_vars

        env_config = self.recipe['configure']['env']

        def process_env_value(var, val):
            """Process env value, handling += append syntax"""
            val = str(val)
            # Handle += append syntax: "+=-std=gnu17" means append to existing value
            if val.startswith('+='):
                append_val = val[2:]  # Remove the += prefix
                return {'name': var, 'value': append_val, 'operation': 'append'}
            else:
                # Replace %{prefix} with RPM macro
                val = val.replace('%{prefix}', '%{prefix}')
                # Replace %{srcdir} with $PWD (RPM %build runs from source dir)
                val = val.replace('%{srcdir}', '$PWD')
                return {'name': var, 'value': val, 'operation': 'set'}

        # Handle both dict and list formats
        if isinstance(env_config, dict):
            for var, val in env_config.items():
                env_vars.append(process_env_value(var, val))
        elif isinstance(env_config, list):
            for env_item in env_config:
                if isinstance(env_item, dict):
                    for var, val in env_item.items():
                        env_vars.append(process_env_value(var, val))

        return env_vars

    def get_patches(self) -> list:
        """Get list of patches for SPEC file generation"""
        patches = get_all_patches(self.recipe, self.package, flavor=self.flavor)

        # Convert to RPM SPEC format
        rpm_patches = []
        for i, patch in enumerate(patches):
            rpm_patches.append({
                'number': i,
                'file': patch['file'],
                'strip': patch['strip'],
                'source': patch['source']
            })

        return rpm_patches

    def setup_rpmbuild(self) -> None:
        """Ensure rpmbuild directory structure exists"""
        for subdir in ['BUILD', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS']:
            (self.rpm_base / subdir).mkdir(parents=True, exist_ok=True)

    def download_sources(self) -> None:
        """Download source tarball and copy patches to rpmbuild/SOURCES"""
        # Prefer source0 (direct tarball URL) over url (homepage/base URL)
        source_url = self.recipe['source'].get('source0', self.recipe['source']['url'])
        source_url = source_url.replace('%{version}', self.recipe['version'])
        download_source(
            source_url, self.sources_dir,
            self.package, self.recipe['version']
        )

        # Download extra sources (e.g., gmp, mpfr, mpc for GCC)
        # Supports both direct URLs and recipe references (single source of truth)
        if 'extra_sources' in self.recipe:
            for extra in self.recipe['extra_sources']:
                if 'recipe' in extra:
                    # Load version and URL from referenced recipe
                    ref_recipe = load_recipe(extra['recipe'])
                    ref_version = ref_recipe['version']
                    ref_url = ref_recipe['source'].get('source0', ref_recipe['source']['url'])
                    ref_url = ref_url.replace('%{version}', ref_version)
                    extra_name = extra['recipe']
                    # Store for later substitution in SPEC template
                    tarball_name = ref_url.split('/')[-1]
                    self.extra_source_info[extra_name] = {
                        'version': ref_version,
                        'tarball': tarball_name,
                        'url': ref_url
                    }
                    print(f"Downloading extra source from recipe {extra_name}: {ref_url}")
                    download_source(ref_url, self.sources_dir, extra_name, ref_version)
                else:
                    # Direct URL (legacy support)
                    extra_url = extra['url']
                    print(f"Downloading extra source: {extra_url}")
                    download_source(
                        extra_url, self.sources_dir,
                        extra.get('extract_to', 'extra'), '0'
                    )

        # Download test sources (e.g. matrix data for STRUMPACK tests)
        for tsrc in self.recipe.get('test', {}).get('sources', []):
            download_source(tsrc['url'], self.sources_dir, self.package, 'test')

        # Copy patches using improved patching system
        copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir, self.package, self.flavor)

    def build_rpm(self, spec_file: Path) -> None:
        """Run rpmbuild to create the RPM"""
        # Copy spec to rpmbuild/SPECS (if not already there)
        dest_spec = self.specs_dir / spec_file.name
        if spec_file.resolve() != dest_spec.resolve():
            shutil.copy2(spec_file, dest_spec)

        # Run rpmbuild with explicit topdir so it uses our local rpmbuild/ tree
        cmd = ['rpmbuild', '--define', f'_topdir {self.rpm_base}', '-ba', str(dest_spec)]

        print(f"\n=== Running rpmbuild ===")
        print(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd)
            if result.returncode != 0:
                raise BuildError(f"rpmbuild failed with return code {result.returncode}")

            print("\nRPM build successful!")

            # Find the generated RPMs
            rpm_files = list((self.rpm_base / "RPMS").rglob("*.rpm"))
            srpm_files = list((self.rpm_base / "SRPMS").glob("*.rpm"))

            print("\nGenerated packages:")
            for rpm in rpm_files + srpm_files:
                print(f"  {rpm}")

        except FileNotFoundError:
            raise BuildError("rpmbuild command not found. Please install rpm-build package.")

    def get_file_list(self) -> list:
        """
        Generate file list for the package using tracked files.

        Reads from files/{package}.txt (generated by mac_builder) and converts
        to RPM-compatible format:
        - Converts .dylib to .so* patterns
        - Replaces platform triplets (x86_64-apple-darwin*) with wildcards
        - Collapses package-specific directories into directory patterns
        - Handles files with spaces

        Returns a list ready for the SPEC %files section.
        """
        import re
        file_list_path = self.project_root / "files" / f"{self.package}.txt"

        if not file_list_path.exists():
            print(f"Warning: No tracked files found at {file_list_path}")
            print("SPEC file will have empty %files section - build may fail")
            return [f"%{{prefix}}/share/scls/registry/{self.package}.yaml"]

        print(f"Using tracked files from: {file_list_path}")
        with open(file_list_path, 'r') as f:
            files = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        # Platform triplet pattern (e.g., x86_64-apple-darwin24.6.0, x86_64-redhat-linux, aarch64-unknown-linux-gnu)
        platform_triplet_pattern = re.compile(r'(x86_64|aarch64|arm64)-(apple-darwin[\d.]+|redhat-linux|unknown-linux-gnu|pc-linux-gnu)')

        # Directories that are package-specific and safe to collapse
        # (i.e., entirely owned by this package)
        # Note: we check these as prefixes, handling versioned dirs specially
        package_specific_prefixes = [
            'lib/cmake/',        # CMake config directories
            'doc/',              # Documentation
            'share/doc/',        # Alternative doc location
        ]

        # Version pattern for package-specific share directories (e.g., share/cmake-4.2/)
        package_share_pattern = re.compile(
            rf'^share/{re.escape(self.package)}(-[\d.]+)?/'
        )

        # Shared directories where we must list individual files
        shared_dirs = {'bin', 'lib', 'include', 'etc', 'libexec',
                       'share/man', 'share/info', 'share/aclocal',
                       'share/pkgconfig', 'lib/pkgconfig',
                       'share/bash-completion', 'share/emacs', 'share/vim'}

        # Track directories we've seen for collapsing
        seen_dirs = {}  # dir_path -> list of files

        rpm_files = []
        skipped_macos = []
        has_dash_versioned_dylibs = set()  # bases like 'lib/libfoo' that have libfoo-N.M.dylib
        dylib_bases = []  # bases processed from unversioned .dylib entries

        # Get flavor short name from prefix (e.g., /opt/scls/gcc -> gcc)
        # This is used to strip duplicate flavor prefixes from macOS file lists
        flavor_short_name = self.prefix.name  # Last component of prefix path
        # Also get the base compiler name (e.g., gcc-debug -> gcc, intel-mkl -> intel)
        flavor_base_name = flavor_short_name.split('-')[0] if '-' in flavor_short_name else None

        for file_path in files:
            # Normalize to %{prefix} format
            if file_path.startswith('%{prefix}'):
                rel_path = file_path[len('%{prefix}/'):]
            elif file_path.startswith(str(self.prefix)):
                rel_path = file_path[len(str(self.prefix)):]
                if rel_path.startswith('/'):
                    rel_path = rel_path[1:]
            else:
                rel_path = file_path

            # Strip flavor prefix if present (avoids double prefix like /opt/scls/gcc/gcc/...)
            # This can happen when macOS file lists are recorded relative to /opt/scls
            # but contain gcc/ subdirectories that would duplicate the Linux prefix
            # Check both full flavor name (gcc-debug) and base compiler name (gcc)
            if rel_path.startswith(f'{flavor_short_name}/'):
                rel_path = rel_path[len(flavor_short_name) + 1:]
            elif flavor_base_name and rel_path.startswith(f'{flavor_base_name}/'):
                rel_path = rel_path[len(flavor_base_name) + 1:]

            # Skip macOS-specific files
            if '.dSYM' in rel_path or rel_path.endswith('.plist'):
                skipped_macos.append(rel_path)
                continue

            # Skip info pages (depend on texinfo and are not needed in the stack)
            if rel_path.startswith('share/info/'):
                continue

            # Convert .dylib to .so* pattern
            if '.dylib' in rel_path:
                # Track versioned-dash dylibs (e.g., libfoo-2.1.7.dylib)
                # so the unversioned entry knows to emit a dash-glob pattern
                if re.search(r'-[\d.]+\.dylib$', rel_path):
                    has_dash_versioned_dylibs.add(re.sub(r'-[\d.]+\.dylib$', '', rel_path))
                    continue
                # Skip dot-versioned dylibs (e.g., libfoo.5.dylib)
                if re.search(r'\.[\d.]+\.dylib$', rel_path):
                    continue
                # libfoo.dylib -> libfoo.so*
                base = re.sub(r'\.dylib$', '', rel_path)
                rpm_files.append(f"%{{prefix}}/{base}.so*")
                dylib_bases.append(base)
                continue

            # Replace platform triplets with wildcard
            if platform_triplet_pattern.search(rel_path):
                rel_path = platform_triplet_pattern.sub('*', rel_path)

            # Check if this belongs to a package-specific directory
            is_package_specific = False
            pkg_dir = None

            # Check standard package-specific prefixes
            for prefix in package_specific_prefixes:
                if rel_path.startswith(prefix):
                    parts = rel_path.split('/')
                    if prefix == 'lib/cmake/':
                        pkg_dir = '/'.join(parts[:3])  # lib/cmake/PkgName
                    else:
                        # doc/pkgname/... or share/doc/pkgname/...
                        pkg_dir = '/'.join(parts[:2]) if prefix == 'doc/' else '/'.join(parts[:3])
                    is_package_specific = True
                    break

            # Check for versioned share directories (e.g., share/cmake-4.2/)
            if not is_package_specific:
                match = package_share_pattern.match(rel_path)
                if match:
                    parts = rel_path.split('/')
                    pkg_dir = '/'.join(parts[:2])  # share/cmake-4.2
                    is_package_specific = True

            if is_package_specific and pkg_dir:
                if pkg_dir not in seen_dirs:
                    seen_dirs[pkg_dir] = []
                seen_dirs[pkg_dir].append(rel_path)

            if not is_package_specific:
                final_path = f"%{{prefix}}/{rel_path}"
                # Quote paths with spaces
                if ' ' in final_path and not final_path.startswith('"'):
                    final_path = f'"{final_path}"'
                rpm_files.append(final_path)

        # Add libfoo-*.so* only for libraries that actually have dash-versioned dylibs
        for base in dylib_bases:
            if base in has_dash_versioned_dylibs:
                rpm_files.append(f"%{{prefix}}/{base}-*.so*")

        # Add collapsed directories
        # In RPM, listing a directory path (without %dir) includes it recursively
        for pkg_dir in sorted(seen_dirs.keys()):
            rpm_files.append(f"%{{prefix}}/{pkg_dir}")

        if skipped_macos:
            print(f"  Skipped {len(skipped_macos)} macOS-specific files")

        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in rpm_files:
            # Normalize for dedup (handle .so* patterns)
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        # Add the registry file (if not already present from the file list)
        registry_entry = f"%{{prefix}}/share/scls/registry/{self.package}.yaml"
        if registry_entry not in seen:
            unique_files.append(registry_entry)

        return unique_files

    def run(self) -> None:
        """Run the complete build process"""
        print(f"\n{'=' * 60}")
        print(f"Building {self.package} {self.recipe['version']} for {self.flavor_name}")
        print(f"{'=' * 60}\n")

        # Warn about GPL-3 licensed packages (project targets BSD-3 compatibility)
        pkg_license = self.recipe.get('license', '')
        if 'GPL-3' in pkg_license:
            print(f"WARNING: {self.package} is licensed under {pkg_license}")
            print("         GPL-3 libraries must NOT be distributed as part of this stack.")
            print("         Building locally for development use only.\n")

        # Setup rpmbuild directory
        self.setup_rpmbuild()

        # Handle generated packages differently
        if self.is_generated_package():
            print("Generated package - skipping source download")
            # Generate SPEC file for generated package
            spec_file = self.generate_generated_spec()
        else:
            # Download sources
            self.download_sources()
            # Generate SPEC file
            spec_file = self.generate_spec()

        # Build RPM
        self.build_rpm(spec_file)

        # Write a local registry entry so build-order tracking knows this package
        # is done. The real registry entry is inside the RPM and gets installed
        # to the prefix when the RPM is installed.
        local_registry = self.project_root / "rpmbuild" / "registry" / self.flavor_name
        local_registry.mkdir(parents=True, exist_ok=True)
        marker = local_registry / f"{self.package}.yaml"
        marker.write_text(f"name: {self.package}\nversion: {self.recipe['version']}\n")

        print(f"\n{'=' * 60}")
        print("Build completed successfully!")
        print(f"{'=' * 60}\n")

    def install_rpm(self) -> None:
        """Install the most recently built RPMs for this package, including subpackages."""
        # Collect RPMs for the main package
        rpm_files = set(
            (self.rpm_base / "RPMS").rglob(f"{self.scls_name}-[0-9]*.rpm")
        )
        # Also collect RPMs for subpackages
        for subpkg in self.get_subpackages_for_spec():
            rpm_files.update(
                (self.rpm_base / "RPMS").rglob(f"{subpkg['rpm_name']}-[0-9]*.rpm")
            )
        # Sort by modification time (newest first)
        rpm_files = sorted(rpm_files, key=lambda p: p.stat().st_mtime, reverse=True)

        if not rpm_files:
            raise BuildError(f"No built RPMs found for {self.scls_name} in {self.rpm_base / 'RPMS'}")

        print(f"\nInstalling RPMs:")
        for rpm in rpm_files:
            print(f"  {rpm}")

        _dnf_install_rpms(rpm_files)

    def get_library_symlink_fixes(self) -> List[str]:
        """Get shell commands to fix library symlinks in RPM %post section"""
        return [
            "# Fix library symlinks created as hard copies",
            "if [ -d %{prefix}/lib ]; then",
            "  cd %{prefix}/lib",
            "  for lib in *.so.*; do",
            "    if [ -f \"$lib\" ]; then",
            "      base=\"${lib%%.*}.so\"",
            "      if [ -f \"$base\" ] && [ ! -L \"$base\" ]; then",
            "        # Check if they're hard links (same inode)",
            "        if [ \"$(stat -c %i \"$lib\")\" = \"$(stat -c %i \"$base\")\" ]; then",
            "          echo \"Converting hard copy to symlink: $base -> $lib\"",
            "          rm -f \"$base\"",
            "          ln -s \"$lib\" \"$base\"",
            "        fi",
            "      fi",
            "    fi",
            "  done",
            "  # Update library cache",
            "  /sbin/ldconfig %{prefix}/lib 2>/dev/null || true",
            "fi"
        ]

    def get_subpackages_for_spec(self) -> List[Dict]:
        """
        Get subpackage definitions formatted for the SPEC template.

        Returns:
            List of subpackage dicts with name, summary, requires, and files
        """
        subpackages = get_subpackages_for_flavor(self.recipe, self.flavor)

        if not subpackages:
            return []

        spec_subpackages = []
        for subpkg in subpackages:
            subpkg_name = subpkg['name']

            # Get dependencies for this subpackage
            deps = get_subpackage_dependencies(subpkg, self.flavor)

            # Convert dependency names to SCLS RPM package names
            rpm_requires = []
            for dep in deps:
                # Check if it's one of our subpackages
                is_subpkg = any(s['name'] == dep for s in subpackages)
                if is_subpkg:
                    rpm_requires.append(f"scls-{self.flavor_name}-{dep}")
                else:
                    # External dependency
                    rpm_requires.append(f"scls-{self.flavor_name}-{dep}")

            # Get file patterns for this subpackage
            file_patterns = subpkg.get('files', [])

            rpm_name = f"scls-{self.flavor_name}-{subpkg_name}"

            # Skip subpackages that would collide with the main package name
            if rpm_name == self.scls_name:
                continue

            # Subpackages install files into %{prefix} just like the main
            # package, so they need the same pre-dep on environment to avoid
            # creating %{prefix}/lib as a real directory before environment
            # has had a chance to lay down the lib -> lib64 symlink.
            env_pkg = f"scls-{self.flavor_name}-environment"
            sub_pre_requires = [env_pkg]
            sub_requires = list(rpm_requires)
            if env_pkg not in sub_requires:
                sub_requires.append(env_pkg)

            spec_subpackages.append({
                'name': subpkg_name,
                'rpm_name': rpm_name,
                'summary': subpkg.get('summary', f'{subpkg_name} subpackage'),
                'description': subpkg.get('description', subpkg.get('summary', '')),
                'requires': sub_requires,
                'pre_requires': sub_pre_requires,
                'files': file_patterns
            })

        return spec_subpackages


def create_example_changelog():
    """Create an example changelog file"""
    changelogs_dir = Path("changelogs")
    changelogs_dir.mkdir(exist_ok=True)

    example_changelog = changelogs_dir / "example.md"
    if not example_changelog.exists():
        changelog_content = '''# Package Changelog

## Version 1.2.3 - Wed Jan 15 2025
- Updated to upstream version 1.2.3
- Fixed compilation issues on ARM64
- Added support for new feature X

## Version 1.2.2 - Mon Jan 10 2025  
- Security patch for CVE-2024-12345
- Performance improvements in core algorithms
- Updated documentation

## Version 1.2.1 - Fri Jan 05 2025
- Initial SCLS package
- Built with GCC optimization flags
- Added comprehensive test suite
'''
        with open(example_changelog, 'w') as f:
            f.write(changelog_content)
        print(f"Created example changelog: {example_changelog}")


def list_installed_packages(flavor_name: str) -> None:
    """List all installed packages from the registry."""
    from build_order import FLAVOR_META

    try:
        flavor = load_flavor(flavor_name)
        prefix = Path(flavor['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor_name}': {e}", file=sys.stderr)
        sys.exit(1)

    entries = get_all_registry_entries(prefix)

    if not entries:
        print(f"No packages installed in {prefix}")
        return

    # Hide internal packages from the listing
    hidden = {'environment', FLAVOR_META}

    # Banner
    description = flavor.get('description', '')
    print("")
    print("     \u259C")
    print(f" \u259B\u2598\u259B\u2598\u2590 \u259B\u2598    Scientific Core Library Stack 2026 [{flavor_name}]")
    print(f" \u2584\u258C\u2599\u2596\u2590\u2596\u2584\u258C    {description}")
    print("")
    print(f"{'Package':<25}{'Version':<17}{'License'}")
    print(f"{'-------':<25}{'-------':<17}{'-------'}")

    count = 0
    for name in sorted(entries.keys()):
        if name in hidden:
            continue
        entry = entries[name]
        version = entry.get('version', '?')
        pkg_license = entry.get('license', '')
        print(f"{name:<25}{version:<17}{pkg_license}")
        count += 1

    print(f"\n{count} packages installed.")


def build_flavor_meta_package(flavor: str, spec_only: bool = False) -> None:
    """Build the flavor meta-package (e.g. scls-gcc) that depends on all
    packages in the flavor.  Installing it via dnf pulls in the entire stack.
    """
    from build_order import get_flavor_package_list, FLAVOR_META

    flavor_config = load_flavor(flavor)
    prefix = Path(flavor_config['prefix'])
    project_root = Path(__file__).parent.parent
    recipes_dir = project_root / 'recipes'
    rpm_base = project_root / 'rpmbuild'
    specs_dir = rpm_base / 'SPECS'
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Collect all real packages for this flavor
    packages = get_flavor_package_list(str(recipes_dir), flavor)
    if not packages:
        raise BuildError(f"No packages found for flavor {flavor}")

    # Add any host-extra packages (e.g. gcc/binutils on RHEL 8) so they
    # become Requires of the meta package and get installed alongside the
    # rest of the stack.
    extra = read_extra_packages(flavor)
    for pkg in extra:
        if pkg not in packages:
            packages.insert(0, pkg)  # foundation packages first

    scls_name = f"scls-{flavor}"
    requires = [f"scls-{flavor}-{pkg}" for pkg in packages]

    description = flavor_config.get('description',
                                    f'SCLS {flavor} flavor — complete installation')

    # Use the environment recipe version as the meta-package version
    env_recipe = load_recipe('environment')
    version = env_recipe.get('version', '1.0')

    changelog_date = datetime.now().strftime('%a %b %d %Y')

    spec_content = f"""\
# Flavor meta-package for {scls_name}
# Installing this RPM pulls in every package in the {flavor} flavor.

Name:           {scls_name}
Version:        {version}
Release:        1%{{?dist}}
Summary:        {description}
License:        BSD-3-Clause-LBNL
BuildArch:      noarch

# All packages in the flavor
{"".join(f"Requires:       {r}{chr(10)}" for r in requires)}
AutoReqProv:    no

%description
{description}

This is a meta-package that depends on every package in the SCLS {flavor}
flavor. Installing it will pull in the complete scientific computing stack.

%install
mkdir -p %{{buildroot}}{prefix}/share/scls/registry
cat > %{{buildroot}}{prefix}/share/scls/registry/{FLAVOR_META}.yaml << 'SCLS_EOF'
name: {FLAVOR_META}
version: "{version}"
summary: {description}
dependencies: []
SCLS_EOF

%files
{prefix}/share/scls/registry/{FLAVOR_META}.yaml

%changelog
* {changelog_date} SCLS Builder <scls@lbl.gov> - {version}-1
- Flavor meta-package for {flavor}
"""

    spec_file = specs_dir / f"{scls_name}.spec"
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    print(f"Generated SPEC file: {spec_file}")

    # Also generate/build the examples meta-package if any recipe defines an
    # *-examples subpackage.
    build_examples_meta_package(flavor, packages, version, changelog_date,
                                spec_only=spec_only)

    if spec_only:
        return

    # Build the RPM
    cmd = ['rpmbuild', '--define', f'_topdir {rpm_base}', '-ba', str(spec_file)]
    print(f"\n=== Building flavor meta-package {scls_name} ===")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise BuildError(f"rpmbuild failed with return code {result.returncode}")

    print(f"\nFlavor meta-package {scls_name} built successfully!")

    # Write local registry marker
    local_registry = project_root / 'rpmbuild' / 'registry' / flavor
    local_registry.mkdir(parents=True, exist_ok=True)
    marker = local_registry / f"{FLAVOR_META}.yaml"
    marker.write_text(f"name: {FLAVOR_META}\nversion: {version}\n")


def _discover_example_subpackages(recipes_dir: Path, packages: list, flavor: str) -> list:
    """Return the list of *-examples subpackage names defined by recipes in
    the given package set for the given flavor."""
    from build_common import get_subpackages_for_flavor
    example_subpkgs = []
    for pkg in packages:
        recipe_path = recipes_dir / f"{pkg}.yaml"
        if not recipe_path.exists():
            continue
        try:
            recipe = load_recipe(pkg)
        except Exception:
            continue
        for subpkg in get_subpackages_for_flavor(recipe, flavor):
            name = subpkg.get('name', '')
            if name.endswith('-examples'):
                example_subpkgs.append(name)
    return example_subpkgs


def build_examples_meta_package(flavor: str, packages: list, version: str,
                                changelog_date: str, spec_only: bool = False) -> None:
    """Build scls-<flavor>-examples — a meta-package that Requires every
    *-examples subpackage discovered across the flavor's recipes.  Skipped
    silently when no example subpackages are defined."""
    project_root = Path(__file__).parent.parent
    recipes_dir = project_root / 'recipes'
    rpm_base = project_root / 'rpmbuild'
    specs_dir = rpm_base / 'SPECS'

    example_subpkgs = _discover_example_subpackages(recipes_dir, packages, flavor)
    if not example_subpkgs:
        return

    scls_name = f"scls-{flavor}-examples"
    requires = [f"scls-{flavor}-{name}" for name in example_subpkgs]
    summary = f"Example programs for the SCLS {flavor} flavor"

    spec_content = f"""\
# Examples meta-package for {scls_name}
# Installing this RPM pulls in every *-examples subpackage in the {flavor} flavor.

Name:           {scls_name}
Version:        {version}
Release:        1%{{?dist}}
Summary:        {summary}
License:        BSD-3-Clause-LBNL
BuildArch:      noarch

{"".join(f"Requires:       {r}{chr(10)}" for r in requires)}
AutoReqProv:    no

%description
{summary}.

This meta-package pulls in the example programs shipped by packages in the
SCLS {flavor} flavor (e.g. PETSc, SLEPc, SUNDIALS). It is optional — install it
only if you want the upstream example sources on disk.

%files

%changelog
* {changelog_date} SCLS Builder <scls@lbl.gov> - {version}-1
- Examples meta-package for {flavor}
"""

    spec_file = specs_dir / f"{scls_name}.spec"
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    print(f"Generated SPEC file: {spec_file}")

    if spec_only:
        return

    cmd = ['rpmbuild', '--define', f'_topdir {rpm_base}', '-ba', str(spec_file)]
    print(f"\n=== Building examples meta-package {scls_name} ===")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise BuildError(f"rpmbuild failed with return code {result.returncode}")

    print(f"\nExamples meta-package {scls_name} built successfully!")


# ---------------------------------------------------------------------------
# scls-release: format-aware static-config package, parallels FLAVOR_META.
# Ships /etc/yum.repos.d/scls.repo and /etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS.
# Same one-off pattern: no recipe, no source, generated inline.
# ---------------------------------------------------------------------------

SCLS_RELEASE = 'scls-release'


def _detect_scls_repo_dir() -> str:
    """Resolve @SCLS_REPO_DIR@ to bake into scls.repo at build time.

    On RHEL-family hosts the .repo file uses 'el$releasever_major' verbatim
    (a literal string that dnf expands at install time, so a single RPM
    works on EL 9 and EL 10). On AL2023 and other dnf hosts whose dist tag
    does not share the EL repo layout, the dist tag is baked in directly.
    """
    import re
    try:
        result = subprocess.run(
            ['rpm', '--eval', '%{dist}'],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise BuildError(f"Cannot determine RPM dist tag: {e}")
    dist = result.stdout.strip().lstrip('.')
    if not dist:
        raise BuildError("rpm --eval %{dist} returned an empty string")
    if re.match(r'^el\d+', dist):
        return 'el$releasever_major'
    return dist


def build_scls_release_package(spec_only: bool = False) -> None:
    """Build the scls-release RPM (and SRPM).

    No recipe of its own, no flavor — the only on-disk inputs are the
    .repo template (templates/scls.repo, with @SCLS_REPO_DIR@ substituted)
    and the GPG key (RPM-GPG-KEY-SCLS at the repo root). Both are the
    single sources of truth shared with deb_builder's
    scls-archive-keyring path. The package version tracks the
    environment recipe (the canonical "SCLS release year"), matching the
    flavor meta-package, so a stack-year bump auto-bumps scls-release.
    Use Release: > 1 to respin scls-release inside the same year (e.g.
    a fix to scls.repo) without bumping the year.
    """
    project_root = Path(__file__).parent.parent
    rpm_base = project_root / 'rpmbuild'
    sources_dir = rpm_base / 'SOURCES'
    specs_dir = rpm_base / 'SPECS'
    for sub in ('BUILD', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
        (rpm_base / sub).mkdir(parents=True, exist_ok=True)

    repo_template = project_root / 'templates' / 'scls.repo'
    if not repo_template.exists():
        raise BuildError(f"Repo template not found: {repo_template}")
    key_src = project_root / 'RPM-GPG-KEY-SCLS'
    if not key_src.exists():
        raise BuildError(f"GPG key not found: {key_src}")

    repo_dir = _detect_scls_repo_dir()
    rendered = repo_template.read_text().replace('@SCLS_REPO_DIR@', repo_dir)
    (sources_dir / 'scls.repo').write_text(rendered)
    shutil.copy2(key_src, sources_dir / 'RPM-GPG-KEY-SCLS')

    env_recipe = load_recipe('environment')
    version = str(env_recipe.get('version', '1'))
    release = '1'

    changelog_date = datetime.now().strftime('%a %b %d %Y')
    spec_content = f"""\
Name:           {SCLS_RELEASE}
Version:        {version}
Release:        {release}%{{?dist}}
Summary:        SCLS repository configuration and GPG key

License:        BSD-3-Clause-LBNL
URL:            https://belfem.lbl.gov/scls

Source0:        scls.repo
Source1:        RPM-GPG-KEY-SCLS

BuildArch:      noarch

%description
This package provides the repository configuration and GPG key for the
Scientific Core Library Stack (SCLS).

%install
install -Dpm 644 %{{SOURCE0}} %{{buildroot}}/etc/yum.repos.d/scls.repo
install -Dpm 644 %{{SOURCE1}} %{{buildroot}}/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS

%files
/etc/yum.repos.d/scls.repo
/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS

%changelog
* {changelog_date} SCLS Builder <scls@lbl.gov> - {version}-{release}
- SCLS repository configuration and GPG key.
"""
    spec_file = specs_dir / f'{SCLS_RELEASE}.spec'
    spec_file.write_text(spec_content)
    print(f"Generated SPEC file: {spec_file} (SCLS_REPO_DIR={repo_dir})")

    if spec_only:
        return

    cmd = ['rpmbuild', '--define', f'_topdir {rpm_base}', '-ba', str(spec_file)]
    print(f"\n=== Building {SCLS_RELEASE} ===")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise BuildError(f"rpmbuild failed with return code {result.returncode}")
    print(f"\n{SCLS_RELEASE} built successfully!")


def main():
    parser = argparse.ArgumentParser(description='Generate RPM SPEC files for SCLS packages')
    parser.add_argument('--package', '-p', help='Package name')
    parser.add_argument('--flavor', '-f', help='Flavor name')
    parser.add_argument('--spec-only', action='store_true',
                        help='Only generate SPEC file, do not build RPM')
    parser.add_argument('--install', action='store_true',
                        help='Install the last built RPM for this package')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List installed packages')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    # Handle --list flag
    if args.list:
        if not args.flavor:
            parser.error("--flavor/-f is required when using --list")
        list_installed_packages(args.flavor)
        return

    # Require package and flavor for build commands
    if not args.package:
        parser.error("--package/-p is required when not using --list")
    # scls-release is flavor-independent; --flavor isn't required for it.
    if not args.flavor and args.package != SCLS_RELEASE:
        parser.error("--flavor/-f is required when not using --list")

    try:
        # scls-release: no recipe, no flavor. Generated inline; the .rpm
        # ships the system repo config and GPG key.
        if args.package == SCLS_RELEASE:
            build_scls_release_package(spec_only=args.spec_only)
            return

        # Flavor meta-package (_meta) is handled separately — no recipe needed
        from build_order import FLAVOR_META
        if args.package == FLAVOR_META:
            if args.install:
                # Install the meta-package RPM
                rpm_base = Path(__file__).parent.parent / 'rpmbuild'
                scls_name = f"scls-{args.flavor}"
                rpm_files = sorted(
                    (rpm_base / "RPMS").rglob(f"{scls_name}*.rpm"),
                    key=lambda p: p.stat().st_mtime, reverse=True
                )
                if not rpm_files:
                    raise BuildError(f"No built RPMs found for {scls_name}")
                _dnf_install_rpms(rpm_files)
            else:
                build_flavor_meta_package(args.flavor, spec_only=args.spec_only)
            return

        builder = RPMBuilder(args.package, args.flavor)

        if args.spec_only:
            # Use appropriate spec generator based on package type
            if builder.is_generated_package():
                spec_file = builder.generate_generated_spec()
            else:
                spec_file = builder.generate_spec()
            print(f"\nSPEC file generated: {spec_file}")
            print("To build RPM, run:")
            print(f"  rpmbuild -ba {builder.specs_dir}/{spec_file.name}")
        elif args.install:
            builder.install_rpm()
        else:
            builder.run()

    except BuildError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBuild interrupted by user", file=sys.stderr)
        sys.exit(130)




if __name__ == '__main__':
    main()