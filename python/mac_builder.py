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


from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, extract_source,
    run_command, setup_environment,
    get_configure_args, get_cmake_args, get_parallel_jobs,
    clean_libtool_files,
    should_build_package,
    check_package_installed,
    write_registry_entry,
    add_rpath_for_libdirs
)

from patch_common import (
    copy_patches_to_sources,
    apply_patches,
    apply_configure_environment,
    process_env_operations
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

        # Extra source info for recipe references (populated during build)
        self.extra_source_info = {}

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, 'macos')
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            from patch_common import apply_configure_environment

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
            from patch_common import apply_configure_environment

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, 'macos')
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            from patch_common import apply_configure_environment
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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, 'macos')
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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, 'macos')
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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, 'macos')
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
        cmd = [s.replace('%{sdk}', self.sdk) for s in cmd]
        cmd = [s.replace('%{host}', self.host) for s in cmd]
        cmd = [s.replace('%{nprocs}', str(self.nprocs)) for s in cmd]
        cmd = [s.replace('%{srcdir}', str(self.source_dir)) for s in cmd]
        cmd = [s.replace('%{cflags}', str(self.cflags)) for s in cmd]
        cmd = [s.replace('%{cxxflags}', str(self.cxxflags)) for s in cmd]
        cmd = [s.replace('%{fcflags}', str(self.fcflags)) for s in cmd]
        cmd = [s.replace('%{ldflags}', str(self.fcflags)) for s in cmd]
        cmd = [s.replace('%{math_flags}', str(self.math_flags)) for s in cmd]
        cmd = [s.replace('%{math_ldflags}', str(self.math_ldflags)) for s in cmd]
        cmd = [s.replace('%{sources}', str(self.sources_dir)) for s in cmd]
        cmd = [s.replace('%{version}', str(self.recipe['version'])) for s in cmd]
        cmd = [s.replace('%{name}', str(self.recipe['name'])) for s in cmd]
        # Substitute extra source info (e.g., %{gmp_version}, %{gmp_tarball})
        for name, info in self.extra_source_info.items():
            cmd = [s.replace(f'%{{{name}_version}}', info['version']) for s in cmd]
            cmd = [s.replace(f'%{{{name}_tarball}}', info['tarball']) for s in cmd]
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

        # special case for Apple zlib - only if the zlib subdirectory exists
        if self.package == 'zlib' and (build_dir / 'zlib').exists():
            build_dir = build_dir / 'zlib'

        print(f"Install build_dir: {build_dir}")  # Debug output
        if not build_dir.exists():
            raise BuildError(f"Build directory does not exist: {build_dir}")

        run_command(install_cmd, build_dir, env, "install")

        # Run any post-install commands (with DESTDIR)
        # %{prefix} = destdir path (for file operations during staging)
        # %{final_prefix} = actual install prefix (for content that needs final paths, like .pc files)
        if 'install' in self.recipe and 'post' in self.recipe['install']:
            for cmd in self.recipe['install']['post']:
                cmd = cmd.replace('%{buildroot}', str(destdir))
                cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                cmd = cmd.replace('%{version}', str(self.recipe['version']))
                cmd = cmd.replace('%{name}', str(self.recipe['name']))
                run_command(['sh', '-c', cmd], build_dir, env, "post-install")

        # Run flavor-specific post-install commands
        if 'install' in self.recipe and 'flavor_post' in self.recipe['install']:
            flavor_name = self.flavor.get('name', 'macos')
            if flavor_name in self.recipe['install']['flavor_post']:
                for cmd in self.recipe['install']['flavor_post'][flavor_name]:
                    cmd = cmd.replace('%{buildroot}', str(destdir))
                    cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                    cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                    cmd = cmd.replace('%{version}', str(self.recipe['version']))
                    cmd = cmd.replace('%{name}', str(self.recipe['name']))
                    run_command(['sh', '-c', cmd], build_dir, env, "flavor-post-install")

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

        # Fix library symlinks after installation
        self.fix_library_symlinks()

        # Run any final post-install commands (after files are in final location)
        self.run_final_post_install_commands()

        # Generate RPM-style file list for use in SPEC files
        self.generate_rpm_file_list()

        # Write registry entry for this package
        write_registry_entry(self.prefix, self.recipe, self.flavor_name)

    def generate_rpm_file_list(self) -> None:
        """
        Generate an RPM-style file list from installed files.

        Converts absolute paths to %{prefix}-relative paths and applies
        wildcards for versioned libraries (e.g., libfoo.so.1.2.3 -> libfoo.so.*)

        Output is saved to files/{package}.txt
        """
        if not hasattr(self, 'installed_files') or not self.installed_files:
            print("No installed files to generate RPM file list from")
            return

        files_dir = Path("files")
        files_dir.mkdir(parents=True, exist_ok=True)

        prefix_str = str(self.prefix)

        # Group files by type for smarter wildcard handling
        rpm_files = set()  # Use set to avoid duplicates
        dirs_with_files = set()  # Track directories that contain files

        for file_path in self.installed_files:
            file_str = str(file_path)

            # Convert to %{prefix}-relative path
            if file_str.startswith(prefix_str):
                rel_path = file_str[len(prefix_str):]
                rpm_path = f"%{{prefix}}{rel_path}"
            else:
                rpm_path = file_str
                rel_path = file_str

            # Track parent directories for potential directory entries
            parent = str(Path(rel_path).parent)
            if parent and parent != '/':
                dirs_with_files.add(parent)

            # Apply wildcards for versioned shared libraries
            # Linux: libfoo.so.1.2.3 -> libfoo.so.*
            # macOS: libfoo.1.2.3.dylib -> libfoo.*.dylib (handled differently)
            import re

            # Match versioned .so files (e.g., libgmp.so.10.5.0)
            so_match = re.match(r'(.+\.so)\.\d+.*$', rpm_path)
            if so_match:
                rpm_files.add(f"{so_match.group(1)}")
                rpm_files.add(f"{so_match.group(1)}.*")
                continue

            # Match versioned .dylib files - convert to .so pattern for Linux
            # macOS format: libfoo.1.2.3.dylib -> Linux: libfoo.so.1.2.3
            dylib_match = re.match(r'(.+)\.(\d+(?:\.\d+)*)\.dylib$', rpm_path)
            if dylib_match:
                base = dylib_match.group(1)
                # Add both the base .so and wildcard version
                rpm_files.add(f"{base}.so")
                rpm_files.add(f"{base}.so.*")
                continue

            # Plain .dylib -> .so for Linux (unversioned symlink)
            if rpm_path.endswith('.dylib'):
                rpm_files.add(rpm_path.replace('.dylib', '.so'))
                continue

            # Skip macOS-specific files that won't exist on Linux
            if '.dSYM' in rpm_path:
                continue

            rpm_files.add(rpm_path)

        # Add directory entries for doc/share directories
        for dir_path in dirs_with_files:
            if '/share/doc/' in dir_path or '/share/man/' in dir_path or '/share/info/' in dir_path:
                rpm_files.add(f"%{{prefix}}{dir_path}")

        # Sort and write to file
        rpm_file_list = sorted(rpm_files)

        output_file = files_dir / f"{self.package}.txt"
        with open(output_file, 'w') as f:
            for rpm_file in rpm_file_list:
                f.write(f"{rpm_file}\n")

        print(f"RPM file list written: {output_file} ({len(rpm_file_list)} entries)")

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

        # Check dependencies: non-bootstrap packages require GCC to be installed
        is_bootstrap = self.recipe.get('bootstrap', False)
        if not is_bootstrap and self.package != 'gcc':
            if not check_package_installed(self.prefix, 'gcc'):
                raise BuildError(
                    f"Package '{self.package}' requires GCC but it is not installed.\n"
                    f"Build GCC first: python python/mac_builder.py -p gcc build install"
                )
            print(f"GCC dependency satisfied (via pkg-config)")

        # Clean work directory if it exists
        if self.work_dir.exists() and 'build' in commands:
            print(f"Cleaning existing work directory: {self.work_dir}")
            shutil.rmtree(self.work_dir)

        # Download source
        if 'build' in commands:
            # Prefer source0 (direct tarball URL) over url (homepage/base URL)
            source_url = self.recipe['source'].get('source0', self.recipe['source']['url'])
            source_url = source_url.replace('%{version}', self.recipe['version'])
            tarball = download_source(
                source_url, self.sources_dir,
                self.package, self.recipe['version']
            )

            # Download extra sources (e.g., gmp, mpfr, mpc for GCC)
            # Supports both direct URLs and recipe references (single source of truth)
            self.extra_source_info = {}  # Store info for placeholder substitution
            if 'extra_sources' in self.recipe:
                for extra in self.recipe['extra_sources']:
                    if 'recipe' in extra:
                        # Load version and URL from referenced recipe
                        ref_recipe = load_recipe(extra['recipe'])
                        ref_version = ref_recipe['version']
                        ref_url = ref_recipe['source'].get('source0', ref_recipe['source']['url'])
                        ref_url = ref_url.replace('%{version}', ref_version)
                        extra_name = extra['recipe']
                        # Store for later substitution in commands
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

        # Add compiler information (use bootstrap compilers if bootstrap package)
        is_bootstrap = self.recipe.get('bootstrap', False)
        if is_bootstrap and 'bootstrap_compilers' in self.flavor:
            compilers = self.flavor['bootstrap_compilers']
        else:
            compilers = self.flavor.get('compilers', {})
        context.update({
            'cc': compilers.get('cc', 'gcc'),
            'cxx': compilers.get('cxx', 'g++'),
            'fc': compilers.get('fc', self.flavor.get('compilers', {}).get('fc', 'gfortran')),
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

    def run_final_post_install_commands(self):
        """Run final post-install commands after files are in their final location"""
        if 'install' not in self.recipe:
            return
            
        env = setup_environment(self.flavor, self.prefix, self.source_dir, self.recipe)
        flavor_name = self.flavor.get('name', 'macos')
        
        # Run general final post commands
        if 'final_post' in self.recipe['install']:
            for cmd in self.recipe['install']['final_post']:
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{install_prefix}', str(self.prefix))  # For zlib, these are the same
                run_command(['sh', '-c', cmd], self.work_dir, env, "final-post-install")
        
        # Run flavor-specific final post commands
        if 'flavor_final_post' in self.recipe['install'] and flavor_name in self.recipe['install']['flavor_final_post']:
            for cmd in self.recipe['install']['flavor_final_post'][flavor_name]:
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{install_prefix}', str(self.prefix))  # For zlib, these are the same
                run_command(['sh', '-c', cmd], self.work_dir, env, "flavor-final-post-install")

    def fix_library_symlinks(self) -> None:
        """Fix library symlinks that may have been created as hard copies"""
        lib_dir = self.prefix / "lib"

        if not lib_dir.exists():
            return

        print("\n=== Fixing library symlinks ===")

        # Find all .dylib files
        dylib_files = list(lib_dir.glob("*.dylib"))

        # Group by base name
        lib_groups = {}
        for dylib in dylib_files:
            # Extract base name - handle both dot and dash separators
            name = dylib.name
            if name.endswith('.dylib'):
                name_without_ext = name[:-6]  # Remove .dylib

                # Handle different versioning patterns:
                # 1. libname.version.dylib (e.g., libgmp.4.dylib)
                # 2. libname-version.dylib (e.g., libevent_core-2.1.7.dylib)

                if '-' in name_without_ext:
                    # Check if this looks like libname-version
                    parts = name_without_ext.split('-')
                    # If the part after the dash starts with a digit, it's likely a version
                    if len(parts) >= 2 and parts[1] and parts[1][0].isdigit():
                        base_name = parts[0]  # Everything before first dash
                    else:
                        base_name = name_without_ext  # No version detected
                else:
                    # Standard dot-separated versioning
                    parts = name_without_ext.split('.')
                    base_name = parts[0]  # Everything before first dot

                if base_name not in lib_groups:
                    lib_groups[base_name] = []
                lib_groups[base_name].append(dylib)

        # Process each group
        for base_name, files in lib_groups.items():
            if len(files) <= 1:
                continue

            # Sort by version specificity (most specific last)
            # For dash-separated versions, we need a smarter sort
            def version_sort_key(f):
                name = f.name[:-6]  # Remove .dylib
                if '-' in name and any(c.isdigit() for c in name.split('-')[-1]):
                    # Dash-separated version: count version components
                    version_part = name.split('-', 1)[1]
                    version_components = len(version_part.split('.'))
                    return (version_components, name)
                else:
                    # Dot-separated version: count all components
                    return (len(name.split('.')), name)

            files.sort(key=version_sort_key)

            # The most version-specific file should be the target
            target_file = files[-1]
            potential_links = files[:-1]

            print(f"Processing {base_name}: target={target_file.name}")

            # All less-specific versions should be symlinks to the most specific
            for candidate in potential_links:
                should_be_symlink = True
                current_state = "unknown"

                if candidate.is_symlink():
                    # Already a symlink, check if correct
                    try:
                        if candidate.resolve() == target_file:
                            print(f"  {candidate.name} -> {target_file.name} (already correct)")
                            continue
                        else:
                            current_state = "incorrect symlink"
                    except (OSError, FileNotFoundError):
                        current_state = "broken symlink"

                    # Remove incorrect/broken symlink
                    print(f"  Removing {current_state}: {candidate.name}")
                    candidate.unlink()
                else:
                    # It's a regular file - check if it's identical to target
                    target_stat = target_file.stat()
                    candidate_stat = candidate.stat()

                    if (candidate_stat.st_ino == target_stat.st_ino and
                            candidate_stat.st_dev == target_stat.st_dev):
                        current_state = "hard copy"
                        print(f"  Converting {current_state} to symlink: {candidate.name}")
                        candidate.unlink()
                    else:
                        # Check if the files have identical content
                        if candidate_stat.st_size == target_stat.st_size:
                            # Quick size check first, then content if needed
                            try:
                                with open(candidate, 'rb') as f1, open(target_file, 'rb') as f2:
                                    # Read in chunks to handle large files
                                    chunk_size = 8192
                                    while True:
                                        chunk1 = f1.read(chunk_size)
                                        chunk2 = f2.read(chunk_size)
                                        if chunk1 != chunk2:
                                            should_be_symlink = False
                                            break
                                        if not chunk1:  # EOF
                                            break

                                    if should_be_symlink:
                                        current_state = "identical copy"
                                        print(f"  Converting {current_state} to symlink: {candidate.name}")
                                        candidate.unlink()
                                    else:
                                        current_state = "different content"
                            except OSError:
                                should_be_symlink = False
                                current_state = "cannot compare"
                        else:
                            should_be_symlink = False
                            current_state = "different size"

                    if not should_be_symlink:
                        print(f"  Keeping separate file ({current_state}): {candidate.name}")
                        continue

                # Create symlink
                try:
                    candidate.symlink_to(target_file.name)
                    print(f"  Created symlink: {candidate.name} -> {target_file.name}")
                except OSError as e:
                    print(f"  Error creating symlink: {e}")

def list_installed_packages(flavor_name: str = 'macos') -> None:
    """List all installed packages from the registry."""
    from build_common import load_flavor, get_all_registry_entries

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
    parser = argparse.ArgumentParser(description='Build SCLS packages for macOS')
    parser.add_argument('--package', '-p', help='Package name')
    parser.add_argument('--flavor', '-f', default='macos', help='Flavor name (default: macos)')
    parser.add_argument('--list', '-l', action='store_true', help='List installed packages')
    parser.add_argument('commands', nargs='*',
                        help='Commands to run (build, test, install, pkg)')

    args = parser.parse_args()

    # Handle --list flag
    if args.list:
        list_installed_packages(args.flavor)
        return

    # Require package name for build commands
    if not args.package:
        parser.error("--package/-p is required when not using --list")

    if not args.commands:
        parser.error("At least one command (build, test, install, pkg) is required")

    # Validate commands
    valid_commands = {'build', 'test', 'install', 'pkg'}
    for cmd in args.commands:
        if cmd not in valid_commands:
            parser.error(f"invalid command: {cmd} (choose from build, test, install, pkg)")

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

