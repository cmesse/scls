#!/usr/bin/env python3
"""
Enhanced RPM builder with release tags, proper parallel builds, and changelog logs
FIXED: Direct configure call instead of %configure macro to avoid unwanted arguments
"""

import os
import sys
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Dict, List

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, should_build_package,
    get_configure_args, get_cmake_args,
    check_package_installed,
    get_package_dependencies,
    add_rpath_for_libdirs,
    get_all_registry_entries,
    get_subpackages_for_flavor,
    get_subpackage_dependencies,
    get_interface_args,
    resolve_flavor_key
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


class RPMBuilder:
    def __init__(self, package: str, flavor: str):
        self.package = package
        self.flavor_name = flavor

        # Load configurations
        self.recipe = load_recipe(package)
        self.flavor = load_flavor(flavor)

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

        # Validate platform
        if self.flavor.get('platform') != 'linux':
            raise BuildError(f"Flavor {flavor} is not for Linux")

        # Check if package should be built
        if not should_build_package(self.recipe, self.flavor):
            raise BuildError(f"Package {package} not built for {flavor}")

        # Check if this is a bootstrap package (needs system compilers before our GCC is built)
        self.is_bootstrap = self.recipe.get('bootstrap', False)
        if self.is_bootstrap and 'bootstrap_compilers' in self.flavor:
            print(f"Using bootstrap compilers (bootstrap package)")
            # Override compilers with bootstrap compilers for this build
            self.flavor['compilers'] = self.flavor['bootstrap_compilers'].copy()

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
                comp = self.flavor['compilers']
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


        # MKL paths if needed
        if 'mkl' in self.flavor_name:
            self.mkl_root = '/opt/intel/oneapi/mkl/latest'
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
        """Get test commands with parallel make substitution if appropriate"""
        if 'test' not in self.recipe:
            return []

        test_config = self.recipe['test']
        commands = test_config.get('commands', [])

        # Check if parallel testing is enabled (default: True)
        parallel_tests = test_config.get('parallel', True)

        # Process commands
        processed_commands = []
        for cmd in commands:
            if parallel_tests and cmd.strip().startswith('make '):
                # Replace "make " with "make %{?_smp_mflags} "
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
                    pre_commands.append(cmd)

            # Flavor-specific pre commands
            flavor_pre = resolve_flavor_key(self.flavor, self.recipe['configure'].get('flavor_pre', {}))
            if flavor_pre:
                for cmd in flavor_pre:
                    pre_commands.append(cmd)

            # Platform-specific pre commands (linux for RPM builder)
            if 'platform_pre' in self.recipe['configure'] and self.platform in self.recipe['configure']['platform_pre']:
                for cmd in self.recipe['configure']['platform_pre'][self.platform]:
                    pre_commands.append(self.check_args([cmd])[0])

            # General post commands
            if 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    post_commands.append(cmd)

            # Flavor-specific post commands
            flavor_post = resolve_flavor_key(self.flavor, self.recipe['configure'].get('flavor_post', {}))
            if flavor_post:
                for cmd in flavor_post:
                    post_commands.append(cmd)

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
        # MKL paths and linker flags
        cmd = [s.replace('%{mklroot}', str(self.mkl_root)) for s in cmd]
        interface = self.flavor.get('math', {}).get('interface', 'lp64')
        if interface == 'ilp64':
            mkl_lp = 'ilp64'
        else:
            mkl_lp = 'lp64'
        mkl_linker = f'-lmkl_intel_{mkl_lp} -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl'
        mkl_mpi_linker = f'-lmkl_scalapack_{mkl_lp} -lmkl_intel_{mkl_lp} -lmkl_gnu_thread -lmkl_core -lmkl_blacs_intelmpi_{mkl_lp} -lgomp -lpthread -lm -ldl'
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
                    pre_commands.append(self.check_args([cmd])[0])

            # Flavor-specific pre commands
            flavor_pre = resolve_flavor_key(self.flavor, self.recipe['install'].get('flavor_pre', {}))
            if flavor_pre:
                for cmd in flavor_pre:
                    pre_commands.append(self.check_args([cmd])[0])

            # General post commands
            if 'post' in self.recipe['install']:
                for cmd in self.recipe['install']['post']:
                    # Apply check_args for %{host}, %{prefix}, etc.
                    post_commands.append(self.check_args([cmd])[0])

            # Flavor-specific post commands
            flavor_post = resolve_flavor_key(self.flavor, self.recipe['install'].get('flavor_post', {}))
            if flavor_post:
                for cmd in flavor_post:
                    post_commands.append(self.check_args([cmd])[0])

            # Platform-specific post commands (linux for RPM builder)
            if 'platform_post' in self.recipe['install'] and self.platform in self.recipe['install']['platform_post']:
                for cmd in self.recipe['install']['platform_post'][self.platform]:
                    post_commands.append(self.check_args([cmd])[0])

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
        """Get Intel OneAPI setup commands for MKL flavors"""
        setup_commands = []

        # Add Intel OneAPI setup for MKL flavors
        if 'mkl' in self.flavor_name:
            setup_commands.append("source /opt/intel/oneapi/setvars.sh intel64")

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

%description
{self.recipe.get('summary', 'SCLS environment setup and activation scripts.')}

%install
{chr(10).join(install_commands)}

# Create registry entry
mkdir -p %{{buildroot}}%{{prefix}}/share/scls/registry
cat > %{{buildroot}}%{{prefix}}/share/scls/registry/{self.package}.yaml << 'SCLS_EOF'
name: {self.package}
version: "{self.recipe['version']}"
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
        except:
            template = self.jinja_env.get_template('default.spec.j2')

        # Get optimization flags
        self.cflags, self.cxxflags, self.fflags = get_optimization_flags(
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
                self.fflags += f" {self.math_flags}"

        # Get requirements
        build_requires, requires = self.get_rpm_requires()

        # Get file list
        files = self.get_file_list()

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

        # Get Intel OneAPI setup
        intel_oneapi_setup = self.get_intel_oneapi_setup()

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

        # Prepare template variables
        context = {
            'flavor': self.flavor,
            'recipe': self.recipe,
            'package_name': self.package,
            'scls_name': self.scls_name,
            'version': self.recipe['version'],
            'release': self.get_release_string(),
            'description': formatted_description,
            'changelog': changelog,
            'homepage': self.recipe.get('homepage', ''),
            'license': self.recipe.get('license', ''),
            'source_url': self.recipe['source']['url'],
            'build_requires': build_requires,
            'requires': requires,
            'prefix': str(self.prefix),
            'sources': str(self.sources_dir),  # For extra sources (e.g., gmp/mpfr/mpc for GCC)
            'cflags': self.cflags,
            'cxxflags': self.cxxflags,
            'fflags': self.fflags,
            'fcflags': self.fflags,
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
            'skip_compiler_env': self.recipe.get('configure', {}).get('skip_compiler_env', False),
            'path_setup': self.get_path_setup(),
            'library_symlink_fixes': self.get_library_symlink_fixes(),
            'extra_source_info': self.extra_source_info,  # For recipe-referenced sources
            'package_dependencies': get_package_dependencies(self.recipe, self.flavor_name),
            'subpackages': self.get_subpackages_for_spec()
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

        # Process arguments for MKL and CUDA paths
        processed_args = []
        for arg in args:
            # Replace CUDA path variables
            if '%{cuda}' in arg:
                arg = arg.replace('%{cuda}', self.cuda_path)
            # Replace MKL path variables
            if '%{mklroot}' in arg:
                arg = arg.replace('%{mklroot}', self.mklroot)

            arg = arg.replace('%{cflags}', self.cflags)
            arg = arg.replace('%{cxxflags}', self.cxxflags)
            arg = arg.replace('%{fcflags}', self.fcflags)
            arg = arg.replace('%{ldflags}', self.ldflags)
            arg = arg.replace('%{math_flags}', self.math_flags)
            arg = arg.replace('%{math_ldflags}', self.math_ldflags)
            # Replace CUDA architectures
            cuda_archs = self.flavor.get('nvidia', {}).get('architectures', '')
            arg = arg.replace('%{cuda_architectures}', cuda_archs)
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

    def get_rpm_requires(self) -> tuple[list, list]:
        """Get RPM BuildRequires and Requires from recipe and flavor-specific settings"""
        build_requires = []
        requires = []

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

            # Handle flavor-sensitive requires
            if isinstance(recipe_requires, dict):
                # Flavor-specific format
                flavor_specific = resolve_flavor_key(self.flavor, recipe_requires)
                if flavor_specific:
                    for req in flavor_specific:
                        scls_req = f"scls-{self.flavor_name}-{req}"
                        build_requires.append(scls_req)
                        requires.append(scls_req)
                # Also add 'all' flavors requirements if present
                if 'all' in recipe_requires:
                    for req in recipe_requires['all']:
                        scls_req = f"scls-{self.flavor_name}-{req}"
                        build_requires.append(scls_req)
                        requires.append(scls_req)
            elif isinstance(recipe_requires, list):
                # Simple list format (applies to all flavors)
                for req in recipe_requires:
                    # For packages we build, add scls- prefix
                    if req in ['cmake', 'autoconf', 'automake', 'libtool', 'pkg-config']:
                        build_requires.append(req)  # Use system versions for build tools
                    else:
                        scls_req = f"scls-{self.flavor_name}-{req}"
                        build_requires.append(scls_req)
                        requires.append(scls_req)

        # Math library requirements based on flavor
        math_feature = features.get('math', 'none')
        if math_feature in ['serial', 'parallel']:
            math_config = self.flavor.get('math', {})
            if math_config.get('type') == 'mkl':
                # Intel MKL requirements
                if 'gcc-mkl' in flavor_name or 'intel-mkl' in flavor_name:
                    requires.append('intel-mkl')
                    build_requires.append('intel-mkl-devel')
            elif math_config.get('type') == 'reference':
                # Reference BLAS/LAPACK
                requires.extend(['blas', 'lapack'])
                build_requires.extend(['blas-devel', 'lapack-devel'])
                if math_feature == 'parallel':
                    requires.append('scalapack')
                    build_requires.append('scalapack-devel')

        # MPI requirements
        if features.get('mpi', False):
            mpi_impl = self.flavor.get('mpi', 'openmpi')
            if mpi_impl == 'openmpi':
                requires.extend(['openmpi', 'openmpi-devel'])
                build_requires.extend(['openmpi-devel'])

        # Remove duplicates while preserving order
        build_requires = list(dict.fromkeys(build_requires))
        requires = list(dict.fromkeys(requires))

        return build_requires, requires

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

        # Copy patches using improved patching system
        copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir, self.package)

    def build_rpm(self, spec_file: Path) -> None:
        """Run rpmbuild to create the RPM"""
        # Copy spec to rpmbuild/SPECS (if not already there)
        dest_spec = self.specs_dir / spec_file.name
        if spec_file.resolve() != dest_spec.resolve():
            shutil.copy2(spec_file, dest_spec)

        # Run rpmbuild
        cmd = ['rpmbuild', '-ba', str(dest_spec)]

        print(f"\n=== Running rpmbuild ===")
        print(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print("rpmbuild failed!")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                raise BuildError(f"rpmbuild failed with return code {result.returncode}")

            print(result.stdout)
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

        # Platform triplet pattern (e.g., x86_64-apple-darwin24.6.0, aarch64-apple-darwin23.0.0)
        platform_triplet_pattern = re.compile(r'(x86_64|aarch64|arm64)-apple-darwin[\d.]+')

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

            # Convert .dylib to .so* pattern
            if '.dylib' in rel_path:
                # libfoo.1.2.3.dylib -> libfoo.so*
                # libfoo.dylib -> libfoo.so*
                rel_path = re.sub(r'\.[\d.]*\.dylib$', '.so*', rel_path)
                rel_path = re.sub(r'\.dylib$', '.so*', rel_path)

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

        # Add the registry file
        unique_files.append(f"%{{prefix}}/share/scls/registry/{self.package}.yaml")

        return unique_files

    def run(self) -> None:
        """Run the complete build process"""
        print(f"\n{'=' * 60}")
        print(f"Building {self.package} {self.recipe['version']} for {self.flavor_name}")
        print(f"{'=' * 60}\n")

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

        print(f"\n{'=' * 60}")
        print("Build completed successfully!")
        print(f"{'=' * 60}\n")

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
        subpackages = get_subpackages_for_flavor(self.recipe, self.flavor_name)

        if not subpackages:
            return []

        spec_subpackages = []
        for subpkg in subpackages:
            subpkg_name = subpkg['name']

            # Get dependencies for this subpackage
            deps = get_subpackage_dependencies(subpkg, self.flavor_name)

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

            spec_subpackages.append({
                'name': subpkg_name,
                'rpm_name': f"scls-{self.flavor_name}-{subpkg_name}",
                'summary': subpkg.get('summary', f'{subpkg_name} subpackage'),
                'description': subpkg.get('description', subpkg.get('summary', '')),
                'requires': rpm_requires,
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

    print(f"\nInstalled packages in {prefix}:")
    print(f"{'Package':<20} {'Version':<12} {'Has .pc':<8} {'Dependencies'}")
    print("-" * 80)

    for name in sorted(entries.keys()):
        entry = entries[name]
        version = entry.get('version', '?')
        has_pc = 'yes' if entry.get('has_pc_file', False) else 'no'
        deps = ', '.join(entry.get('dependencies', [])) or '-'
        print(f"{name:<20} {version:<12} {has_pc:<8} {deps}")

    print(f"\nTotal: {len(entries)} package(s)")


def main():
    parser = argparse.ArgumentParser(description='Generate RPM SPEC files for SCLS packages')
    parser.add_argument('--package', '-p', help='Package name')
    parser.add_argument('--flavor', '-f', help='Flavor name')
    parser.add_argument('--spec-only', action='store_true',
                        help='Only generate SPEC file, do not build RPM')
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
    if not args.flavor:
        parser.error("--flavor/-f is required when not using --list")

    try:
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