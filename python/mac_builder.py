#!/usr/bin/env python3
"""
macOS builder for SCLS packages
Builds directly without creating SPEC files
"""

import os
import sys
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from numpy.f2py.auxfuncs import throw_error

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, extract_source,
    run_command, setup_environment,
    get_configure_args, get_cmake_args, get_parallel_jobs,
    clean_libtool_files,
    should_build_package
)

from patch_common import (
    copy_patches_to_sources,
    apply_patches
)

from math_common import ( get_math_link_line, get_math_compile_flags )

class MacOSBuilder:
    def __init__(self, package: str, flavor: str = "macos"):
        self.package = package
        self.flavor_name = flavor

        # Load configurations
        self.recipe = load_recipe(package)
        self.flavor = load_flavor(flavor)

        # Validate platform
        if self.flavor.get('platform') != 'macos':
            raise BuildError(f"Flavor {flavor} is not for macOS")

        # Check if package should be built
        if not should_build_package(self.recipe, self.flavor):
            raise BuildError(f"Package {package} not built for {flavor}")

        # Setup paths - mirror rpmbuild structure
        self.prefix = Path(self.flavor['prefix'])
        self.install_prefix = None
        self.project_root = Path(__file__).parent.parent  # Go up from python/ to project root
        self.rpmbuild = self.project_root / "work"
        self.sources_dir = self.rpmbuild / "sources"
        self.build_dir = self.rpmbuild / "build"
        self.work_dir = self.build_dir
        self.rpms_dir = self.rpmbuild / "pkgs"
        self.srpms_dir = self.rpmbuild / "spkgs"
        self.specs_dir = self.rpmbuild / "specs" # actually not needed on mac
        self.patch_dir = self.project_root / "patches" / package

        # this is set in run after extracting the package
        self.source_dir = ""

        self.nprocs = os.cpu_count()

        # get the sdk
        self.sdk = subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],text=True).strip()

        self.host = "x86_64-apple-darwin" + subprocess.check_output(
            ["uname", "-r"],text=True).strip()

        # Feature flags
        self.openmp = False
        self.mpi = False
        self.cuda = False  # Not used on macOS but kept for consistency
        self.math = None  # 'reference', 'accelerate', or None

        # flags to be filled later
        self.cflags = ""
        self.cxxflags = ""
        self.fcflags = ""
        self.ldflags = ""

        self.math_flags = ""
        self.math_ldflags = ""

        # Create directories
        for d in [self.sources_dir, self.build_dir, self.rpms_dir, self.srpms_dir, self.specs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def update_config_scripts(self, source_dir: Path) -> None:
        """Update config.guess and config.sub for macOS compatibility"""
        # Look for existing config.guess/config.sub
        for name in ['config.guess', 'config.sub']:
            # Common locations
            for subdir in ['.', 'build-aux', 'config']:
                config_file = source_dir / subdir / name
                if config_file.exists():
                    print(f"Found {name} at {config_file}")
                    # For now, we'll rely on the package's version
                    # In the future, we could replace with our custom script
                    if name == 'config.guess':
                        # Make sure it's executable
                        config_file.chmod(0o755)

    def configure(self, source_dir: Path, env: Dict[str, str]) -> None:
        """Run configure step"""
        self.math_flags
        configure_type = self.recipe.get('configure', {}).get('type', 'autotools')

        pkg_config_path = str(self.prefix / 'lib/pkgconfig') + ':' + "/opt/X11/lib/pkgconfig:/usr/lib/pkgconfig"

        # check for MPI
        features = self.recipe.get('features', {})
        self.openmp = features.get('openmp', False)
        self.mpi = features.get('mpi', False)
        self.math = features.get('math', None)

        # Add math flags if math features are enabled
        if self.math :
            self.math_flags = get_math_compile_flags(self.flavor, self.recipe)
            self.math_ldflags = get_math_link_line(self.flavor, self.recipe)

            # Replace %{mklroot} with actual path (not applicable on macOS, but for consistency)
            mklroot = getattr(self, 'mklroot', '/opt/intel/oneapi/mkl/latest')
            self.math_ldflags = self.math_ldflags.replace('%{mklroot}', mklroot)

        if configure_type == 'autotools':
            # Update config scripts
            self.update_config_scripts(source_dir)

            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # Get configure arguments
            args = get_configure_args(self.recipe, self.host, self.flavor, self.prefix, self.install_prefix )

            # override compilers
            if self.mpi:
                env['CC'] = 'mpicc'
                env['CXX'] = 'mpicxx'
                env['FC'] = 'mpifort'
                env['FF'] = 'mpifort'
                env['F77'] = 'mpifort'

            # Get optimization flags
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )

            ldflags = self.flavor['flags'].get('ldflags', '')

            # Add math flags to existing flags
            if self.math:
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            env['CFLAGS'] = self.cflags
            env['CXXFLAGS'] = self.cxxflags
            env['FFLAGS'] = self.fcflags
            env['FCFLAGS'] = self.fcflags
            env['LDFLAGS'] = self.ldflags
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            from build_common import apply_configure_environment

            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix)

            # apply special clang hack
            cmd = "for f in $(find . -name configure); do sed -i '' 's/--version -v -V -qversion/--version -v/g' $f; done"
            run_command(['sh', '-c', cmd], source_dir, env, "pre-configure")

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Run configure
            cmd = self.check_args(['./configure'] + args)
            run_command(cmd, source_dir, env, "configure")

            # Run any post-configure commands
            if 'configure' in self.recipe and 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "post-configure")

        elif configure_type == 'cmake':

            # Apply enhanced configure environment (supports +=, -=, etc.)
            from build_common import apply_configure_environment

            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix)

            # Create build directory
            build_dir = source_dir / 'build'
            build_dir.mkdir(exist_ok=True)

            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # Get CMake arguments
            args = get_cmake_args(self.recipe, self.host, self.flavor, self.prefix, self.install_prefix)

            # override compilers
            if self.mpi:
                env['CC'] = 'mpicc'
                env['CXX'] = 'mpicxx'
                env['FC'] = 'mpifort'
                env['FF'] = 'mpifort'
                env['F77'] = 'mpifort'

            # Get optimization flags
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )

            self.ldflags = self.flavor['flags'].get('ldflags', '')

            # Add math flags to existing flags
            if self.math :
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            env['CFLAGS'] = self.cflags
            env['CXXFLAGS'] = self.cxxflags
            env['FFLAGS'] = self.fcflags
            env['FCFLAGS'] = self.fcflags
            env['LDFLAGS'] = self.ldflags
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            from build_common import apply_configure_environment
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix)

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Run CMake
            cmd = self.check_args(['cmake', '..'] + args)
            run_command(cmd, build_dir, env, "cmake configure")

            # Run any post-configure commands
            if 'configure' in self.recipe and 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "post-configure")


            # Update source_dir to build_dir for subsequent steps
            return build_dir

        elif configure_type == 'custom':
            # Custom configuration system (like OpenSSL's ./config)
            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix
                
            # override compilers
            if self.mpi:
                env['CC'] = 'mpicc'
                env['CXX'] = 'mpicxx'
                env['FC'] = 'mpifort'
                env['FF'] = 'mpifort'
                env['F77'] = 'mpifort'

            # Get optimization flags
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )

            ldflags = self.flavor['flags'].get('ldflags', '')

            # Add math flags to existing flags
            if self.math:
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            env['CFLAGS'] = self.cflags
            env['CXXFLAGS'] = self.cxxflags
            env['FFLAGS'] = self.fcflags
            env['FCFLAGS'] = self.fcflags
            env['LDFLAGS'] = self.ldflags
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Get custom configure command and arguments
            configure_cmd = self.recipe.get('configure', {}).get('command', './config')
            args = self.recipe.get('configure', {}).get('args', [])

            # Add prefix to args if not already present
            prefix_arg = f"--prefix={self.install_prefix}"
            if not any(arg.startswith('--prefix') for arg in args):
                args.insert(0, prefix_arg)

            # Apply flavor-specific args
            if 'configure' in self.recipe and 'flavor_args' in self.recipe['configure']:
                flavor_name = self.flavor.get('name', '')
                if flavor_name in self.recipe['configure']['flavor_args']:
                    args.extend(self.recipe['configure']['flavor_args'][flavor_name])

            # Run custom configure command
            cmd = self.check_args([configure_cmd] + args)
            run_command(cmd, source_dir, env, "custom configure")

            # Run any post-configure commands
            if 'configure' in self.recipe and 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "post-configure")

        elif configure_type == 'none':
            # No configuration step needed (e.g., simple Makefiles)
            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # override compilers
            if self.mpi:
                env['CC'] = 'mpicc'
                env['CXX'] = 'mpicxx'
                env['FC'] = 'mpifort'
                env['FF'] = 'mpifort'
                env['F77'] = 'mpifort'

            # Get optimization flags
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )

            self.ldflags = self.flavor['flags'].get('ldflags', '')

            # Add math flags to existing flags
            if self.math:
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            env['CFLAGS'] = self.cflags
            env['CXXFLAGS'] = self.cxxflags
            env['FFLAGS'] = self.fcflags
            env['FCFLAGS'] = self.fcflags
            env['LDFLAGS'] = self.ldflags
            env['PKG_CONFIG_PATH'] = pkg_config_path

            print("Skipping configure step (type: none)")

        elif configure_type == 'custom_makefile':
            # Set install_prefix
            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # Get optimization flags and set environment
            cflags, cxxflags, fcflags = get_optimization_flags(self.recipe, self.flavor, env['CC'])

            # override compilers
            if self.mpi:
                env['CC'] = 'mpicc'
                env['CXX'] = 'mpicxx'
                env['FC'] = 'mpifort'
                env['FF'] = 'mpifort'
                env['F77'] = 'mpifort'

            # Get optimization flags
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )

            self.ldflags = self.flavor['flags'].get('ldflags', '')

            # Add math flags to existing flags
            if self.math:
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            env['CFLAGS'] = self.cflags
            env['CXXFLAGS'] = self.cxxflags
            env['FFLAGS'] = self.fcflags
            env['FCFLAGS'] = self.fcflags
            env['LDFLAGS'] = self.ldflags
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix)

            # *** CALL IT HERE ***
            self.process_custom_makefile(source_dir, env)

        else:
            raise BuildError(f"Unknown configure type: {configure_type}")

        return source_dir

    def check_args(self, cmd):
        cmd = [s.replace('sed -i', 'gsed -i') for s in cmd]
        cmd = [s.replace('%{prefix}', str(self.prefix)) for s in cmd]
        cmd = [s.replace('%{install_prefix}', str(self.install_prefix)) for s in cmd]
        cmd =  [ s.replace('%{sdk}', self.sdk) for s in cmd ]
        cmd = [s.replace('%{host}', self.host) for s in cmd]
        cmd = [s.replace('%{nprocs}', str(self.nprocs)) for s in cmd]
        cmd = [s.replace('%{srcdir}', str(self.source_dir)) for s in cmd]
        cmd = [s.replace('%{cflags}', str(self.cflags)) for s in cmd]
        cmd = [s.replace('%{cxxflags}', str(self.cxxflags)) for s in cmd]
        cmd = [s.replace('%{fcflags}', str(self.fcflags)) for s in cmd]
        cmd = [s.replace('%{ldflags}', str(self.fcflags)) for s in cmd]
        return cmd

    def build(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run build step"""
        # Get number of parallel jobs
        jobs = get_parallel_jobs()
        if not self.recipe.get('build', {}).get('parallel', True):
            jobs = 1

        # Run any pre-build commands
        if 'build' in self.recipe and 'pre' in self.recipe['build']:
            for cmd in self.recipe['build']['pre']:
                run_command(cmd.split(), build_dir, env, "pre-build")

        # Build command
        make_cmd = ['make', f'-j{jobs}']
        if 'build' in self.recipe and 'args' in self.recipe['build']:
            make_cmd.extend(self.recipe['build']['args'])

        run_command(make_cmd, build_dir, env, "build")

        # Run any post-build commands
        if 'build' in self.recipe and 'post' in self.recipe['build']:
            for cmd in self.recipe['build']['post']:
                run_command(cmd.split(), build_dir, env, "post-build")

    def test(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run test step"""
        if 'test' not in self.recipe:
            print("No tests defined for this package")
            return

        print("\n=== Running tests ===")

        # Run any pre-test commands
        if 'pre' in self.recipe['test']:
            for cmd in self.recipe['test']['pre']:
                run_command(cmd.split(), build_dir, env, "pre-test")

        # Run test commands
        if 'commands' in self.recipe['test']:
            for cmd in self.recipe['test']['commands']:
                # Handle shell features like pipes and redirects
                run_command(['sh', '-c', cmd], build_dir, env, "test")

        # Run any post-test commands
        if 'post' in self.recipe['test']:
            for cmd in self.recipe['test']['post']:
                run_command(['sh', '-c', cmd], build_dir, env, "post-test")

    def install(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run install step and track installed files"""
        # Create a temporary DESTDIR for installation
        destdir = self.work_dir / "destdir"
        if destdir.exists():
            shutil.rmtree(destdir)
        destdir.mkdir(parents=True)

        # Run any pre-install commands
        if 'install' in self.recipe and 'pre' in self.recipe['install']:
            for cmd in self.recipe['install']['pre']:
                run_command(cmd.split(), build_dir, env, "pre-install")

        # Install command with DESTDIR
        install_cmd = ['make', 'install', f'DESTDIR={destdir}']
        if 'install' in self.recipe and 'args' in self.recipe['install']:
            install_cmd.extend(self.recipe['install']['args'])

        # special case for Apple zlib
        if self.package == 'zlib':
            build_dir = build_dir / 'zlib'

        run_command(install_cmd, build_dir, env, "install")

        # Run any post-install commands (with DESTDIR)
        if 'install' in self.recipe and 'post' in self.recipe['install']:
            for cmd in self.recipe['install']['post']:
                cmd = cmd.replace('%{buildroot}', str(destdir))
                cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                run_command(['sh', '-c', cmd], build_dir, env, "post-install")

        # Clean up .la files in destdir
        clean_libtool_files(destdir / str(self.prefix).lstrip('/'))

        # Now copy from destdir to actual prefix
        # This gives us control over what gets installed
        src_prefix = destdir / str(self.prefix).lstrip('/')
        if src_prefix.exists():
            print(f"\nInstalling files from {src_prefix} to {self.prefix}")

            # Track installed files
            self.installed_files = []

            for src_path in src_prefix.rglob('*'):
                if src_path.is_file():
                    rel_path = src_path.relative_to(src_prefix)
                    dest_path = self.prefix / rel_path

                    # Create parent directory if needed
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    # Copy file
                    shutil.copy2(src_path, dest_path)
                    self.installed_files.append(dest_path)

            print(f"Installed {len(self.installed_files)} files")

            # Save installed files list for PKG creation
            file_list_path = self.work_dir / "installed_files.txt"
            with open(file_list_path, 'w') as f:
                for file in self.installed_files:
                    f.write(f"{file}\n")
        else:
            raise BuildError(f"No files found in {src_prefix}")

    def create_pkg(self) -> None:
        """Create a macOS PKG file with proper file tracking"""
        pkg_name = f"scls-{self.package}-{self.recipe['version']}.pkg"
        pkg_path = self.rpms_dir / pkg_name  # PKGs go in rpms dir for consistency

        print(f"\n=== Creating PKG: {pkg_name} ===")

        # Check if we have the installed files list
        file_list_path = self.work_dir / "installed_files.txt"
        if not file_list_path.exists():
            raise BuildError("No installed files list found. Run 'install' first.")

        # Create a temporary package root
        pkg_root = self.work_dir / "pkg-root"
        if pkg_root.exists():
            shutil.rmtree(pkg_root)
        pkg_root.mkdir(parents=True)

        # Read installed files and copy to package root
        with open(file_list_path, 'r') as f:
            installed_files = [Path(line.strip()) for line in f]

        print(f"Packaging {len(installed_files)} files...")

        for src_file in installed_files:
            if src_file.exists():
                # Calculate relative path from root
                if str(src_file).startswith('/'):
                    rel_path = str(src_file).lstrip('/')
                else:
                    rel_path = src_file

                dest_file = pkg_root / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)

        # Create the package
        cmd = [
            'pkgbuild',
            '--root', str(pkg_root),
            '--identifier', f'gov.lbl.scls.{self.package}',
            '--version', self.recipe['version'],
            '--install-location', '/',
            str(pkg_path)
        ]

        try:
            run_command(cmd, self.work_dir, os.environ, "create PKG")
            print(f"Created package: {pkg_path}")
        except BuildError as e:
            print(f"Warning: Failed to create PKG: {e}")
            print("Package is installed but PKG creation failed")

    def run(self, commands: List[str]) -> None:
        """Run the build process"""
        print(f"\n{'=' * 60}")
        print(f"Building {self.package} {self.recipe['version']} for {self.flavor_name}")
        print(f"{'=' * 60}\n")

        # Clean work directory if it exists
        if self.work_dir.exists() and 'build' in commands:
            print(f"Cleaning existing work directory: {self.work_dir}")
            shutil.rmtree(self.work_dir)

        # Download source
        if 'build' in commands:
            source_url = self.recipe['source']['url'].replace('%{version}', self.recipe['version'])
            tarball = download_source(
                source_url, self.sources_dir,
                self.package, self.recipe['version']
            )

            # Copy patches to sources directory
            copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir, self.package)

            # Extract source
            source_dir = extract_source(
                tarball, self.work_dir,
                self.package, self.recipe['version']
            )

            # remember source directory
            self.source_dir = source_dir

            # special case for Apple zlib
            if self.package == 'zlib':
                source_dir = source_dir / 'zlib'

            # Apply patches
            apply_patches(source_dir, self.recipe, self.package, self.patch_dir)

            # Setup environment
            env = setup_environment(self.flavor, self.prefix, self.source_dir )

            # Configure
            build_dir = self.configure(source_dir, env)

            # Build
            self.build(build_dir, env)
        else:
            # For test/install without build, find the build directory
            build_dirs = list(self.work_dir.glob(f"{self.package}-*"))
            if not build_dirs:
                raise BuildError("No build directory found. Run 'build' first.")
            build_dir = build_dirs[0]
            if (build_dir / 'build').exists():  # CMake build
                build_dir = build_dir / 'build'
            env = setup_environment(self.flavor, self.prefix, self.recipe)

        # Test
        if 'test' in commands:
            self.test(build_dir, env)

        # Install
        if 'install' in commands:
            self.install(build_dir, env)

        # Create PKG (optional)
        if 'pkg' in commands:
            self.create_pkg()

        print(f"\n{'=' * 60}")
        print(f"Successfully completed: {', '.join(commands)}")
        print(f"{'=' * 60}\n")

    def process_custom_makefile(self, source_dir: Path, env: Dict[str, str]) -> None:
        """Process custom makefile template if needed"""
        if self.recipe.get('configure', {}).get('type') != 'custom_makefile':
            return

        template_name = self.recipe.get('configure', {}).get('template')
        if not template_name:
            raise BuildError("custom_makefile type requires 'template' field in configure section")

        # Setup Jinja2 environment for templates
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        jinja_env = Environment(
            loader=FileSystemLoader('templates'),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Load the makefile template
        try:
            makefile_template = jinja_env.get_template(template_name)
        except Exception as e:
            raise BuildError(f"Failed to load makefile template '{template_name}': {e}")

        # Calculate additional variables for makefile generation
        makefile_context = self.get_makefile_context(env)

        # Render the makefile
        try:
            rendered_makefile = makefile_template.render(**makefile_context)

            # Write the makefile to the source directory
            makefile_path = source_dir / "Makefile.inc"
            with open(makefile_path, 'w') as f:
                f.write(rendered_makefile)

            print(f"Generated custom Makefile: {makefile_path}")

        except Exception as e:
            raise BuildError(f"Failed to render makefile template '{template_name}': {e}")

    def get_makefile_context(self, env: Dict[str, str]) -> Dict:
        """Get context variables for custom makefile templates"""
        context = {
            'recipe': self.recipe,
            'flavor': self.flavor,
            'package_name': self.package,
            'version': self.recipe['version'],
            'features': self.recipe.get('features', {}),
            'prefix': str(self.prefix),
            'install_prefix': str(self.install_prefix)
        }

        # Add compiler information
        compilers = self.flavor.get('compilers', {})
        context.update({
            'cc': compilers.get('cc', 'clang'),
            'cxx': compilers.get('cxx', 'clang++'),
            'fc': compilers.get('fc', 'gfortran'),
        })

        # Add MPI compilers if MPI is enabled
        if self.mpi:
            context.update({
                'mpicc': 'mpicc',
                'mpicxx': 'mpicxx',
                'mpifort': 'mpifort',
            })

        # Add optimization flags
        cflags, cxxflags, fcflags = get_optimization_flags(
            self.recipe, self.flavor, env['CC']
        )
        context.update({
            'cflags': cflags,
            'cxxflags': cxxflags,
            'fcflags': fcflags,
            'fcflags': fcflags,
            'ldflags': env['LDFLAGS'],
        })

        # Add macOS-specific variables
        context.update({
            'sdk': self.sdk,
            'host': self.host,
            'nprocs': str(self.nprocs),
        })

        # Math library configuration - all or nothing approach
        math_config = self.flavor.get('math', {})
        if math_config.get('linalg') == 'accelerate':
            # Use Accelerate for everything
            context['use_accelerate'] = True
            context['blas_libs'] = '-framework Accelerate'
            context['lapack_libs'] = '-framework Accelerate'
            if self.math == 'parallel':
                # ScaLAPACK built against Accelerate
                context['scalapack_libs'] = '-lscalapack -framework Accelerate'
            context['math_libs'] = '-framework Accelerate'
        else:
            # Use reference implementation for everything
            context['use_accelerate'] = False
            context['blas_libs'] = '-lblas'
            context['lapack_libs'] = '-llapack'
            if self.math == 'parallel':
                context['scalapack_libs'] = '-lscalapack -llapack -lblas'
                context['math_libs'] = '-lscalapack -llapack -lblas'
            else:
                context['math_libs'] = '-llapack -lblas'

        # OpenMP configuration - simple since we use symlinks
        if self.openmp:
            context['openmp_flag'] = '-fopenmp'
            context['openmp_libs'] = '-lgomp'
        else:
            context['openmp_flag'] = ''
            context['openmp_libs'] = ''

        # Library type
        context['shared_libs'] = True
        context['lib_ext'] = '.dylib'

        # Index size for packages that support it
        context['index_size'] = self.recipe.get('features', {}).get('index_size', 32)

        return context

def main():
    parser = argparse.ArgumentParser(description='Build SCLS packages for macOS')
    parser.add_argument('--package', '-p', required=True, help='Package name')
    parser.add_argument('--flavor', '-f', default='macos', help='Flavor name (default: macos)')
    parser.add_argument('commands', nargs='+',
                        choices=['build', 'test', 'install', 'pkg'],
                        help='Commands to run')

    args = parser.parse_args()

    try:
        builder = MacOSBuilder(args.package, args.flavor)
        builder.run(args.commands)
    except BuildError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBuild interrupted by user", file=sys.stderr)
        sys.exit(130)


if __name__ == '__main__':
    main()

