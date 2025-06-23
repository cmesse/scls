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
    get_configure_args, get_cmake_args
)
from patch_common import (
    copy_patches_to_sources,
    get_all_patches
)

from math_common import (
    get_math_link_line,
    get_math_compile_flags,
    get_cuda_path,
    nv_hpc_compiler_path,
    get_nv_gpu_targets )


def load_changelog(package_name: str, logs_dir: Path = Path("logs")) -> str:
    """Load package changelog from logs directory"""
    changelog_path = logs_dir / f"{package_name}.md"
    if changelog_path.exists():
        with open(changelog_path, 'r') as f:
            content = f.read().strip()

        # Convert Markdown to basic RPM changelog format
        # This is a simple conversion - could be enhanced
        changelog_lines = []
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('##'):  # Version headers
                # Convert "## Version 1.2.3 - 2024-01-15" to RPM format
                changelog_lines.append(line.replace('##', '*').strip())
            elif line.startswith('-'):  # Bullet points
                changelog_lines.append(line)
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

        # Validate platform
        if self.flavor.get('platform') != 'linux':
            raise BuildError(f"Flavor {flavor} is not for Linux")

        # Check if package should be built
        if not should_build_package(self.recipe, self.flavor):
            raise BuildError(f"Package {package} not built for {flavor}")

        # Setup paths
        self.prefix = Path(self.flavor['prefix'])
        self.project_root = Path(__file__).parent.parent
        self.rpm_base = self.project_root / "rpmbuild"  # DO NOT CHANGE!!!
        self.sources_dir = self.rpm_base / "SOURCES" # DO NOT CHANGE!!!
        self.specs_dir = self.rpm_base / "SPECS" # DO NOT CHANGE!!!

        self.host = "x86_64-redhat-linux"
        self.nprocs = os.cpu_count()

        # flags to be filled later
        self.cflags = ""
        self.cxxflags = ""
        self.fcflags = ""
        self.ldflags = ""

        self.math_flags = ""
        self.math_ldflags = ""

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

        # Create directories
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        for d in [self.sources_dir, self.specs_dir]:
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
        """Get pre and post configure commands from recipe"""
        pre_commands = []
        post_commands = []

        if 'configure' in self.recipe:
            if 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    pre_commands.append(cmd)

            if 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    post_commands.append(cmd)

        return pre_commands, post_commands

    def check_args(self, cmd):
        cmd = [s.replace('%{prefix}', str(self.prefix)) for s in cmd]
        cmd = [s.replace('%{install_prefix}', str(self.install_prefix)) for s in cmd]
        cmd = [s.replace('%{host}', self.host) for s in cmd]
        cmd = [s.replace('%{nprocs}', str(self.nprocs)) for s in cmd]
        cmd = [s.replace('%{cuda}', str(self.cuda_path)) for s in cmd]
        cmd = [s.replace('%{mklroot}', str( self.mkl_root)) for s in cmd]
        return cmd

    def get_install_pre_post_commands(self) -> tuple[list, list]:
        """Get pre and post install commands from recipe"""
        pre_commands = []
        post_commands = []

        if 'install' in self.recipe:
            if 'pre' in self.recipe['install']:
                for cmd in self.recipe['install']['pre']:
                    pre_commands.append(cmd)

            if 'post' in self.recipe['install']:
                for cmd in self.recipe['install']['post']:
                    post_commands.append(cmd)

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
        args = ["--prefix=%{prefix}"]

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
            flavor_name = self.flavor.get('name', '')
            if flavor_name in self.recipe['configure']['flavor_args']:
                for arg in self.recipe['configure']['flavor_args'][flavor_name]:
                    args.append(arg)

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

    def generate_spec(self) -> Path:
        """Generate RPM SPEC file from template"""
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

        # Load changelog from logs directory
        changelog = load_changelog(self.package)

        # Process configure environment for SPEC file
        configure_env_vars = self.get_configure_env_vars()

        # Get parallel make command
        make_command = self.get_parallel_make_flags()

        # Get configure type
        configure_type = self.recipe.get('configure', {}).get('type', 'autotools')

        # Get direct configure command (instead of %configure)
        direct_configure_command = self.get_direct_configure_command()

        # Get pre/post commands
        configure_pre_commands, configure_post_commands = self.get_configure_pre_post_commands()
        install_pre_commands, install_post_commands = self.get_install_pre_post_commands()

        # Get Intel OneAPI setup
        intel_oneapi_setup = self.get_intel_oneapi_setup()

        # Get cmake args if needed
        cmake_args = []
        if configure_type == 'cmake':
            cmake_args = self.get_cmake_args_with_paths()

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
            'cflags': self.cflags,
            'cxxflags': self.cxxflags,
            'fflags': self.fclags,
            'fcflags': self.fcfags,
            'ldflags': self.flavor['flags'].get('ldflags', ''),
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
            'cmake_args': cmake_args,
            'configure_env_vars': configure_env_vars,
            'patches': self.get_patches(),
            'test_commands': self.get_test_commands(),
            'pre_build_setup': intel_oneapi_setup,  # UPDATED: Intel OneAPI setup
            'cuda': self.cuda_path,
            'nv_hpc_compilers' : self.nv_hpc_compilers,
            'nv_gpu_target' : self.nv_gpu_target,
            'nprocs': "$(nproc)",
            'mkl_root': self.mkl_root,
            'self.math_flags': self.math_flags,
            'math_ldflags': self.math_ldflags,
            'features': self.recipe.get('features', {}),
            'path_setup': self.get_path_setup()
        }

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
            processed_args.append(arg)

        return processed_args

    def get_rpm_requires(self) -> tuple[list, list]:
        """Get RPM BuildRequires and Requires from recipe and flavor-specific settings"""
        build_requires = []
        requires = []

        # Get flavor-specific RPM requirements from recipe
        flavor_name = self.flavor_name

        # Add flavor-specific build requirements
        if 'rpm_build_requires' in self.recipe:
            if isinstance(self.recipe['rpm_build_requires'], dict):
                # Flavor-specific format
                if flavor_name in self.recipe['rpm_build_requires']:
                    build_requires.extend(self.recipe['rpm_build_requires'][flavor_name])
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
                if flavor_name in self.recipe['rpm_requires']:
                    requires.extend(self.recipe['rpm_requires'][flavor_name])
                # Also add 'all' flavors requirements if present
                if 'all' in self.recipe['rpm_requires']:
                    requires.extend(self.recipe['rpm_requires']['all'])
            elif isinstance(self.recipe['rpm_requires'], list):
                # Simple list format (applies to all flavors)
                requires.extend(self.recipe['rpm_requires'])

        # Compiler requirements based on features
        features = self.recipe.get('features', {})

        # Add compiler requirements based on flavor
        compiler_cc = self.flavor['compilers']['cc']
        if compiler_cc == 'gcc':
            build_requires.append('gcc')
            build_requires.append('gcc-c++')
            if features.get('fortran', False):
                build_requires.append('gfortran')
        elif compiler_cc == 'icx':
            # Intel compilers - could be added later
            pass

        # Standard build tools
        build_requires.extend(['make', 'git'])

        # Add recipe-specific requirements (our own packages) - with flavor support
        if 'requires' in self.recipe:
            recipe_requires = self.recipe['requires']

            # Handle flavor-sensitive requires
            if isinstance(recipe_requires, dict):
                # Flavor-specific format
                if flavor_name in recipe_requires:
                    for req in recipe_requires[flavor_name]:
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

        env_vars.append({'name': 'PKG_CONFIG_PATH', 'value': "%{prefix}/lib/pkgconfig:/usr/lib/pkgconfig"})

        if 'configure' not in self.recipe or 'env' not in self.recipe['configure']:
            return env_vars

        env_config = self.recipe['configure']['env']

        # Handle both dict and list formats
        if isinstance(env_config, dict):
            for var, val in env_config.items():
                # Replace %{prefix} with RPM macro
                val = str(val).replace('%{prefix}', '%{prefix}')
                env_vars.append({'name': var, 'value': val})
        elif isinstance(env_config, list):
            for env_item in env_config:
                if isinstance(env_item, dict):
                    for var, val in env_item.items():
                        val = str(val).replace('%{prefix}', '%{prefix}')
                        env_vars.append({'name': var, 'value': val})

        return env_vars

    def get_patches(self) -> list:
        """Get list of patches for SPEC file generation"""
        patches = get_all_patches(self.recipe, self.package)

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
        source_url = self.recipe['source']['url'].replace('%{version}', self.recipe['version'])
        download_source(
            source_url, self.sources_dir,
            self.package, self.recipe['version']
        )

        # Copy patches using improved patching system
        copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir, self.package)

    def build_rpm(self, spec_file: Path) -> None:
        """Run rpmbuild to create the RPM"""
        # Copy spec to rpmbuild/SPECS
        dest_spec = self.specs_dir / spec_file.name
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
        """Generate file list for the package using actual installed files"""
        # Check if we have tracked files from a previous build
        file_list_path = self.project_root / "files" / "{:s}.txt".format(self.package)

        if file_list_path.exists():
            print(f"Using tracked files from: {file_list_path}")
            with open(file_list_path, 'r') as f:
                files = [line.strip() for line in f if line.strip()]

            # Convert absolute paths to RPM file list format
            rpm_files = []
            for file_path in files:
                if file_path.startswith(str(self.prefix)):
                    # Remove the prefix to get relative path, then add back as RPM macro
                    rel_path = file_path[len(str(self.prefix)):]
                    if rel_path.startswith('/'):
                        rel_path = rel_path[1:]
                    rpm_files.append(f"%{{prefix}}/{rel_path}")
                else:
                    # File outside our prefix - use as-is
                    rpm_files.append(file_path)
            return rpm_files
        else:
            print("No tracked files found")
            # return empty list
            return []

    def run(self) -> None:
        """Run the complete build process"""
        print(f"\n{'=' * 60}")
        print(f"Building {self.package} {self.recipe['version']} for {self.flavor_name}")
        print(f"{'=' * 60}\n")

        # Setup rpmbuild directory
        self.setup_rpmbuild()

        # Download sources
        self.download_sources()

        # Generate SPEC file
        spec_file = self.generate_spec()

        # Build RPM
        self.build_rpm(spec_file)

        print(f"\n{'=' * 60}")
        print("Build completed successfully!")
        print(f"{'=' * 60}\n")


def create_example_changelog():
    """Create an example changelog file"""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    example_changelog = logs_dir / "example.md"
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


def main():
    parser = argparse.ArgumentParser(description='Generate RPM SPEC files for SCLS packages')
    parser.add_argument('--package', '-p', required=True, help='Package name')
    parser.add_argument('--flavor', '-f', required=True, help='Flavor name')
    parser.add_argument('--spec-only', action='store_true',
                        help='Only generate SPEC file, do not build RPM')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    try:
        builder = RPMBuilder(args.package, args.flavor)

        if args.spec_only:
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