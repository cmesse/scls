#!/usr/bin/env python3
"""
Unix builder for SCLS packages
Builds directly without creating SPEC files
Supports macOS, Linux, and other Unix-like systems
"""

import os
import sys
import argparse
import platform
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
    add_rpath_for_libdirs,
    get_package_dependencies,
    get_subpackages_for_flavor,
    get_subpackage_dependencies,
    split_files_by_subpackage,
    get_interface_args,
    resolve_flavor_key
)

from patch_common import (
    copy_patches_to_sources,
    apply_patches,
    apply_configure_environment,
    process_env_operations
)

from math_common import ( get_math_link_line, get_math_compile_flags )

class UnixBuilder:
    def __init__(self, package: str, flavor: str = "macos"):
        self.package = package
        self.flavor_name = flavor

        # Load configurations
        self.recipe = load_recipe(package)
        self.flavor = load_flavor(flavor)

        # Detect and validate platform from flavor
        self.platform = self.flavor.get('platform', 'linux')

        # Merge platform-specific recipe sections (linux: or macos:)
        # This allows recipes to have different version/source per platform
        if self.platform in self.recipe:
            platform_section = self.recipe[self.platform]
            # Merge version if specified
            if 'version' in platform_section:
                self.recipe['version'] = platform_section['version']
            # Merge source if specified
            if 'source' in platform_section:
                if 'source' not in self.recipe:
                    self.recipe['source'] = {}
                self.recipe['source'].update(platform_section['source'])

        # Apply flavor-specific overrides (e.g., version, source URL)
        from build_common import apply_flavor_overrides
        self.recipe = apply_flavor_overrides(self.recipe, self.flavor)

        # Validate platform
        supported_platforms = ['macos', 'linux']
        if self.platform not in supported_platforms:
            raise BuildError(f"Platform {self.platform} not supported. Use: {supported_platforms}")

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
        self.specs_dir = self.rpmbuild / "specs"
        self.patch_dir = self.project_root / "patches" / package

        # this is set in run after extracting the package
        self.source_dir = ""

        self.nprocs = os.cpu_count()

        # Platform-specific settings
        if self.platform == 'macos':
            # macOS: get SDK path and Darwin version
            self.sdk = subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
            uname_r = subprocess.check_output(["uname", "-r"], text=True).strip()
            # Detect architecture
            machine = platform.machine()
            if machine == 'arm64':
                self.host = f"aarch64-apple-darwin{uname_r}"
            else:
                self.host = f"x86_64-apple-darwin{uname_r}"
            self.lib_ext = '.dylib'
            self.soname_flag = '-install_name'
        else:
            # Linux and other Unix
            self.sdk = ""  # No SDK needed
            # Use gcc -dumpmachine to get the correct host triplet
            try:
                result = subprocess.run(['gcc', '-dumpmachine'], capture_output=True, text=True)
                self.host = result.stdout.strip()
            except Exception:
                machine = platform.machine()
                self.host = f"{machine}-unknown-linux-gnu"
            self.lib_ext = '.so'
            self.soname_flag = '-soname'

        # Feature flags
        self.openmp = False
        self.mpi = False
        self.cuda = False
        self.math = None  # 'reference', 'mkl', 'openblas', or None

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

            # Add interface-specific arguments (LP64/ILP64)
            args.extend(get_interface_args(self.recipe, self.flavor))

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

            # Get ldflags from flavor
            self.ldflags = self.flavor['flags'].get('ldflags', '').replace('%{prefix}', str(self.prefix))

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, self.platform)
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix, source_dir)

            # Apply platform-specific environment variables
            env = self.apply_platform_env(env)

            # apply special clang hack (macOS only - removes -qversion flag for clang compatibility)
            if self.flavor.get('platform') == 'macos':
                cmd = "for f in $(find . -name configure); do sed -i '' 's/--version -v -V -qversion/--version -v/g' $f; done"
                run_command(['sh', '-c', cmd], source_dir, env, "pre-configure")

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Run platform-specific pre-configure commands
            self.run_platform_pre(source_dir, env)

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
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix, source_dir)

            # Create build directory
            build_dir = source_dir / 'build'
            build_dir.mkdir(exist_ok=True)

            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # Get CMake arguments
            args = get_cmake_args(self.recipe, self.host, self.flavor, self.prefix, self.install_prefix)

            # Add interface-specific arguments (LP64/ILP64)
            args.extend(get_interface_args(self.recipe, self.flavor))

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

            self.ldflags = self.flavor['flags'].get('ldflags', '').replace('%{prefix}', str(self.prefix))

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, self.platform)
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix, source_dir)

            # Apply platform-specific environment variables
            env = self.apply_platform_env(env)

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    # Apply check_args to replace %{sdk} and %{host}
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Run platform-specific pre-configure commands
            self.run_platform_pre(source_dir, env)

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
            # Custom configuration system (like OpenSSL's ./config or PETSc's ./configure)
            if 'configure' in self.recipe and 'install_prefix' in self.recipe['configure']:
                self.install_prefix = self.prefix / self.recipe['configure']['install_prefix']
            else:
                self.install_prefix = self.prefix

            # Check if we should skip setting compiler environment variables
            # (Some packages like PETSc prefer command-line args and warn about env vars)
            skip_compiler_env = self.recipe.get('configure', {}).get('skip_compiler_env', False)

            if not skip_compiler_env:
                # Set compilers in environment
                if self.mpi:
                    env['CC'] = 'mpicc'
                    env['CXX'] = 'mpicxx'
                    env['FC'] = 'mpifort'
                    env['FF'] = 'mpifort'
                    env['F77'] = 'mpifort'
                else:
                    # Use bootstrap compilers if this is a bootstrap package
                    is_bootstrap = self.recipe.get('bootstrap', False)
                    if is_bootstrap and 'bootstrap_compilers' in self.flavor:
                        compilers = self.flavor['bootstrap_compilers']
                    else:
                        compilers = self.flavor.get('compilers', {})
                    env['CC'] = compilers.get('cc', 'gcc')
                    env['CXX'] = compilers.get('cxx', 'g++')
                    env['FC'] = compilers.get('fc', 'gfortran')

            # Get optimization flags (still needed for placeholder substitution)
            self.cflags, self.cxxflags, self.fcflags = get_optimization_flags(
                self.recipe, self.flavor, env.get('CC', 'gcc')
            )

            # Get ldflags from flavor
            self.ldflags = self.flavor['flags'].get('ldflags', '').replace('%{prefix}', str(self.prefix))

            # Add math flags to existing flags
            if self.math:
                self.cflags += f" {self.math_flags}"
                self.cxxflags += f" {self.math_flags}"
                self.fcflags += f" {self.math_flags}"
                self.ldflags += f" {self.math_ldflags}"

            if not skip_compiler_env:
                env['CFLAGS'] = self.cflags
                env['CXXFLAGS'] = self.cxxflags
                env['FFLAGS'] = self.fcflags
                env['FCFLAGS'] = self.fcflags
                env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, self.platform)

            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment (supports +=, -=, etc.)
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix, source_dir)

            # Apply platform-specific environment variables
            env = self.apply_platform_env(env)

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    checked_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', checked_cmd], source_dir, env, "pre-configure")

            # Run platform-specific pre-configure commands
            self.run_platform_pre(source_dir, env)

            # Get custom configure command and arguments
            configure_cmd = self.recipe.get('configure', {}).get('command', './config')
            args = self.recipe.get('configure', {}).get('args', [])

            # Add prefix to args if not already present
            prefix_arg = f"--prefix={self.install_prefix}"
            if not any(arg.startswith('--prefix') for arg in args):
                args.insert(0, prefix_arg)

            # Apply flavor-specific args
            if 'configure' in self.recipe and 'flavor_args' in self.recipe['configure']:
                flavor_specific = resolve_flavor_key(self.flavor, self.recipe['configure']['flavor_args'])
                if flavor_specific:
                    args.extend(flavor_specific)

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

            self.ldflags = self.flavor['flags'].get('ldflags', '').replace('%{prefix}', str(self.prefix))

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, self.platform)
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

            self.ldflags = self.flavor['flags'].get('ldflags', '').replace('%{prefix}', str(self.prefix))

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
            env['LDFLAGS'] = add_rpath_for_libdirs(self.ldflags, self.platform)
            env['PKG_CONFIG_PATH'] = pkg_config_path

            # Apply enhanced configure environment
            env = apply_configure_environment(env, self.recipe, self.flavor, self.prefix, source_dir)

            # *** CALL IT HERE ***
            self.process_custom_makefile(source_dir, env)

        else:
            raise BuildError(f"Unknown configure type: {configure_type}")

        return source_dir

    def check_args(self, cmd):
        if self.platform == 'macos':
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
        cuda_path = self.flavor.get('nvidia', {}).get('cuda_path', '')
        cuda_archs = self.flavor.get('nvidia', {}).get('architectures', '')
        cmd = [s.replace('%{cuda}', cuda_path) for s in cmd]
        cmd = [s.replace('%{cuda_architectures}', cuda_archs) for s in cmd]
        # MKL paths and linker flags
        mklroot = self.flavor.get('math', {}).get('mklroot', '/opt/intel/oneapi/mkl/latest')
        cmd = [s.replace('%{mklroot}', mklroot) for s in cmd]
        # MKL linker flags (simplified - actual flags come from math_common)
        interface = self.flavor.get('math', {}).get('interface', 'lp64')
        if interface == 'ilp64':
            mkl_lp = 'ilp64'
        else:
            mkl_lp = 'lp64'
        mkl_linker = f'-lmkl_intel_{mkl_lp} -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl'
        mkl_mpi_linker = f'-lmkl_scalapack_{mkl_lp} -lmkl_intel_{mkl_lp} -lmkl_gnu_thread -lmkl_core -lmkl_blacs_intelmpi_{mkl_lp} -lgomp -lpthread -lm -ldl'
        cmd = [s.replace('%{mkl_linker_flags}', mkl_linker) for s in cmd]
        cmd = [s.replace('%{mkl_mpi_linker_flags}', mkl_mpi_linker) for s in cmd]
        # Platform (linux or macos)
        cmd = [s.replace('%{platform}', self.platform) for s in cmd]
        # System library paths (zlib, etc.) - check system_libraries setting in flavor
        system_libs = self.flavor.get('system_libraries', {})
        if system_libs.get('zlib', False):
            # Use system zlib
            if self.platform == 'linux':
                cmd = [s.replace('%{zlib_include}', '/usr/include') for s in cmd]
                cmd = [s.replace('%{zlib_lib}', '/usr/lib64/libz.so') for s in cmd]
            else:
                cmd = [s.replace('%{zlib_include}', '/usr/include') for s in cmd]
                cmd = [s.replace('%{zlib_lib}', '/usr/lib/libz.dylib') for s in cmd]
        else:
            # Use our built zlib
            cmd = [s.replace('%{zlib_include}', f'{self.prefix}/include') for s in cmd]
            cmd = [s.replace('%{zlib_lib}', f'{self.prefix}/lib/libz{self.lib_ext}') for s in cmd]
        # Substitute extra source info (e.g., %{gmp_version}, %{gmp_tarball})
        for name, info in self.extra_source_info.items():
            cmd = [s.replace(f'%{{{name}_version}}', info['version']) for s in cmd]
            cmd = [s.replace(f'%{{{name}_tarball}}', info['tarball']) for s in cmd]
        return cmd

    def run_platform_pre(self, source_dir: Path, env: Dict[str, str]) -> None:
        """Run platform-specific pre-configure commands"""
        if 'configure' not in self.recipe:
            return
        platform_pre = self.recipe['configure'].get('platform_pre', {})
        if self.platform in platform_pre:
            for cmd in platform_pre[self.platform]:
                checked_cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', checked_cmd], source_dir, env, f"platform-pre ({self.platform})")

    def apply_platform_env(self, env: Dict[str, str]) -> Dict[str, str]:
        """Apply platform-specific environment variables"""
        if 'configure' not in self.recipe:
            return env
        platform_env = self.recipe['configure'].get('platform_env', {})
        if self.platform in platform_env:
            for key, value in platform_env[self.platform].items():
                # Apply check_args to the value to expand placeholders
                expanded_value = self.check_args([value])[0]
                env[key] = expanded_value
        return env

    def build(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run build step"""
        # Get number of parallel jobs
        jobs = get_parallel_jobs()
        if not self.recipe.get('build', {}).get('parallel', True):
            jobs = 1

        # Run any pre-build commands
        if 'build' in self.recipe and 'pre' in self.recipe['build']:
            for cmd in self.recipe['build']['pre']:
                expanded_cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded_cmd], build_dir, env, "pre-build")

        # Run LP64/ILP64 interface-specific pre-build commands
        if 'build' in self.recipe:
            interface = self.flavor.get('math', {}).get('interface', 'lp64')
            if interface == 'ilp64' and 'ilp64_pre' in self.recipe['build']:
                for cmd in self.recipe['build']['ilp64_pre']:
                    expanded_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', expanded_cmd], build_dir, env, "pre-build (ilp64)")
            elif interface == 'lp64' and 'lp64_pre' in self.recipe['build']:
                for cmd in self.recipe['build']['lp64_pre']:
                    expanded_cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', expanded_cmd], build_dir, env, "pre-build (lp64)")

        # Build command
        make_cmd = ['make', f'-j{jobs}']
        if 'build' in self.recipe and 'args' in self.recipe['build']:
            make_cmd.extend(self.check_args(self.recipe['build']['args']))

        # Add flavor-specific build args
        if 'build' in self.recipe and 'flavor_args' in self.recipe['build']:
            flavor_specific = resolve_flavor_key(self.flavor, self.recipe['build']['flavor_args'])
            if flavor_specific:
                make_cmd.extend(self.check_args(flavor_specific))

        # Add LP64/ILP64 interface-specific build args
        make_cmd.extend(get_interface_args(self.recipe, self.flavor, 'build'))

        run_command(make_cmd, build_dir, env, "build")

        # Run any post-build commands
        if 'build' in self.recipe and 'post' in self.recipe['build']:
            for cmd in self.recipe['build']['post']:
                expanded_cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded_cmd], build_dir, env, "post-build")

    def test(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run test step"""
        if 'test' not in self.recipe:
            print("No tests defined for this package")
            return

        print("\n=== Running tests ===")

        # Add prefix lib directory to library path so test executables
        # can find shared libraries without requiring rpath in test binaries
        # On macOS, use DYLD_FALLBACK_LIBRARY_PATH (not stripped by SIP)
        lib_dir = str(self.prefix / "lib")
        if self.platform == 'macos':
            lib_var = 'DYLD_FALLBACK_LIBRARY_PATH'
        else:
            lib_var = 'LD_LIBRARY_PATH'
        if lib_var in env:
            env[lib_var] = f"{lib_dir}:{env[lib_var]}"
        else:
            env[lib_var] = lib_dir

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
                expanded_cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded_cmd], build_dir, env, "pre-install")

        # special case for Apple zlib - only if the zlib subdirectory exists
        if self.package == 'zlib' and (build_dir / 'zlib').exists():
            build_dir = build_dir / 'zlib'

        print(f"Install build_dir: {build_dir}")  # Debug output
        if not build_dir.exists():
            raise BuildError(f"Build directory does not exist: {build_dir}")

        # Check if recipe defines custom install commands
        if 'install' in self.recipe and 'commands' in self.recipe['install']:
            # Run custom install commands instead of make install
            for cmd in self.recipe['install']['commands']:
                cmd = cmd.replace('%{buildroot}', str(destdir))
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{libext}', self.lib_ext)
                expanded_cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded_cmd], build_dir, env, "install")
        else:
            # Default: make install with DESTDIR
            install_cmd = ['make', 'install', f'DESTDIR={destdir}']
            if 'install' in self.recipe and 'args' in self.recipe['install']:
                args = self.check_args(self.recipe['install']['args'])
                install_cmd.extend(args)
            # Add flavor-specific install args
            if 'install' in self.recipe and 'flavor_args' in self.recipe['install']:
                flavor_specific = resolve_flavor_key(self.flavor, self.recipe['install']['flavor_args'])
                if flavor_specific:
                    install_cmd.extend(self.check_args(flavor_specific))
            run_command(install_cmd, build_dir, env, "install")

        # Run any post-install commands (with DESTDIR)
        # %{prefix} = destdir path (for file operations during staging)
        # %{final_prefix} = actual install prefix (for content that needs final paths, like .pc files)
        if 'install' in self.recipe and 'post' in self.recipe['install']:
            for cmd in self.recipe['install']['post']:
                # Apply install-specific replacements FIRST (before check_args replaces %{prefix})
                cmd = cmd.replace('%{buildroot}', str(destdir))
                cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                # Then apply check_args for %{host}, %{sdk}, %{version}, etc.
                cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', cmd], build_dir, env, "post-install")

        # Run flavor-specific post-install commands
        if 'install' in self.recipe and 'flavor_post' in self.recipe['install']:
            flavor_post = resolve_flavor_key(self.flavor, self.recipe['install']['flavor_post'])
            if flavor_post:
                for cmd in flavor_post:
                    # Apply install-specific replacements FIRST (before check_args replaces %{prefix})
                    cmd = cmd.replace('%{buildroot}', str(destdir))
                    cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                    cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                    # Then apply check_args for %{host}, %{sdk}, %{version}, etc.
                    cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', cmd], build_dir, env, "flavor-post-install")

        # Run platform-specific post-install commands
        if 'install' in self.recipe and 'platform_post' in self.recipe['install']:
            if self.platform in self.recipe['install']['platform_post']:
                for cmd in self.recipe['install']['platform_post'][self.platform]:
                    # Apply install-specific replacements FIRST (before check_args replaces %{prefix})
                    cmd = cmd.replace('%{buildroot}', str(destdir))
                    cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                    cmd = cmd.replace('%{prefix}', str(destdir / str(self.prefix).lstrip('/')))
                    # Then apply check_args for %{host}, %{sdk}, %{version}, etc.
                    cmd = self.check_args([cmd])[0]
                    run_command(['sh', '-c', cmd], build_dir, env, f"platform-post-install ({self.platform})")

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
        else:
            raise BuildError(f"No files found in {src_prefix}")

        # Run any final post-install commands (after files are in final location)
        self.run_final_post_install_commands()

        # Generate RPM-style file list for use in SPEC files
        self.generate_rpm_file_list()

        # Write registry entry for this package
        write_registry_entry(self.prefix, self.recipe, self.flavor_name)

        # Add registry file to installed files list so it gets included in PKG
        registry_file = self.prefix / "share" / "scls" / "registry" / f"{self.recipe['name']}.yaml"
        if registry_file.exists():
            self.installed_files.append(registry_file)

        # Save installed files list for PKG creation (after registry entry is added)
        file_list_path = self.work_dir / "installed_files.txt"
        with open(file_list_path, 'w') as f:
            for file in self.installed_files:
                f.write(f"{file}\n")

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
        """Create macOS PKG file(s) with proper file tracking and subpackage support"""
        # Check if we have the installed files list
        file_list_path = self.work_dir / "installed_files.txt"
        if not file_list_path.exists():
            raise BuildError("No installed files list found. Run 'install' first.")

        # Read installed files
        with open(file_list_path, 'r') as f:
            installed_files = [line.strip() for line in f if line.strip()]

        # Check for subpackages
        subpackages = get_subpackages_for_flavor(self.recipe, self.flavor_name)

        if subpackages:
            # Split files among subpackages
            files_by_subpkg = split_files_by_subpackage(
                installed_files, subpackages, str(self.prefix)
            )

            # Create a PKG for each subpackage
            for subpkg in subpackages:
                subpkg_name = subpkg['name']
                subpkg_files = files_by_subpkg.get(subpkg_name, [])

                if not subpkg_files:
                    print(f"Warning: No files matched for subpackage '{subpkg_name}'")
                    continue

                self._create_single_pkg(
                    pkg_name=subpkg_name,
                    version=self.recipe['version'],
                    files=subpkg_files,
                    identifier=f'gov.lbl.scls.{subpkg_name}'
                )

            # Create main package with remaining files (if any)
            main_files = files_by_subpkg.get('main', [])
            if main_files:
                self._create_single_pkg(
                    pkg_name=self.package,
                    version=self.recipe['version'],
                    files=main_files,
                    identifier=f'gov.lbl.scls.{self.package}'
                )
        else:
            # No subpackages - create single package
            self._create_single_pkg(
                pkg_name=self.package,
                version=self.recipe['version'],
                files=installed_files,
                identifier=f'gov.lbl.scls.{self.package}'
            )

    def _create_single_pkg(self, pkg_name: str, version: str, files: List[str], identifier: str) -> None:
        """Create a single macOS PKG file"""
        pkg_filename = f"scls-{pkg_name}-{version}.pkg"
        pkg_path = self.rpms_dir / pkg_filename

        print(f"\n=== Creating PKG: {pkg_filename} ===")

        # Create a temporary package root
        pkg_root = self.work_dir / f"pkg-root-{pkg_name}"
        if pkg_root.exists():
            shutil.rmtree(pkg_root)
        pkg_root.mkdir(parents=True)

        print(f"Packaging {len(files)} files...")

        for file_path in files:
            # Convert %{prefix} format to actual path
            if file_path.startswith('%{prefix}'):
                src_file = Path(str(self.prefix) + file_path[len('%{prefix}'):])
            else:
                src_file = Path(file_path)

            if src_file.exists():
                # Calculate relative path from root
                rel_path = str(src_file).lstrip('/')
                dest_file = pkg_root / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if src_file.is_symlink():
                    # Preserve symlinks
                    link_target = os.readlink(src_file)
                    if dest_file.exists() or dest_file.is_symlink():
                        dest_file.unlink()
                    dest_file.symlink_to(link_target)
                else:
                    shutil.copy2(src_file, dest_file)

        # Create the package
        cmd = [
            'pkgbuild',
            '--root', str(pkg_root),
            '--identifier', identifier,
            '--version', version,
            '--install-location', '/',
            str(pkg_path)
        ]

        try:
            run_command(cmd, self.work_dir, os.environ, f"create PKG {pkg_name}")
            print(f"Created package: {pkg_path}")

            # Also save the file list for this subpackage
            file_list_dir = self.project_root / "files"
            file_list_dir.mkdir(parents=True, exist_ok=True)
            file_list_path = file_list_dir / f"{pkg_name}.txt"
            with open(file_list_path, 'w') as f:
                for file_path in files:
                    # Convert to %{prefix} format for portability
                    if file_path.startswith(str(self.prefix)):
                        f.write(f"%{{prefix}}{file_path[len(str(self.prefix)):]}\n")
                    elif file_path.startswith('%{prefix}'):
                        f.write(f"{file_path}\n")
                    else:
                        f.write(f"{file_path}\n")
            print(f"Saved file list: {file_list_path}")

        except BuildError as e:
            print(f"Warning: Failed to create PKG {pkg_name}: {e}")
            print("Package is installed but PKG creation failed")

    def install_generated(self) -> None:
        """
        Install a generated package (no source, templates only).

        Processes Jinja2 templates from the templates/ directory and installs
        them to the prefix. Used for packages like scls-environment that don't
        have external source code.
        """
        from jinja2 import Environment, FileSystemLoader

        print("\n=== Installing generated package ===")

        # Setup Jinja2 environment
        templates_dir = self.project_root / "templates"
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
            'scls_version': '1.0',  # TODO: get from somewhere central
        }

        # Track installed files
        self.installed_files = []

        # Process each template in the install section
        templates_config = self.recipe.get('install', {}).get('templates', [])

        for tmpl_config in templates_config:
            src_template = tmpl_config['src']
            dest_path = tmpl_config['dest']
            file_mode = tmpl_config.get('mode', '0644')

            print(f"Processing template: {src_template} -> {dest_path}")

            # Load and render template
            try:
                template = jinja_env.get_template(src_template)
                rendered = template.render(**context)
            except Exception as e:
                raise BuildError(f"Failed to render template {src_template}: {e}")

            # Determine full destination path
            full_dest = self.prefix / dest_path

            # Create parent directories
            full_dest.parent.mkdir(parents=True, exist_ok=True)

            # Write rendered content
            with open(full_dest, 'w') as f:
                f.write(rendered)

            # Set file mode
            os.chmod(full_dest, int(file_mode, 8))

            self.installed_files.append(full_dest)
            print(f"  Installed: {full_dest}")

        print(f"\nInstalled {len(self.installed_files)} files")

        # Write registry entry
        write_registry_entry(self.prefix, self.recipe, self.flavor_name)

        # Add registry file to installed files
        registry_file = self.prefix / "share" / "scls" / "registry" / f"{self.recipe['name']}.yaml"
        if registry_file.exists():
            self.installed_files.append(registry_file)

        # Save installed files list for PKG creation
        self.work_dir.mkdir(parents=True, exist_ok=True)
        file_list_path = self.work_dir / "installed_files.txt"
        with open(file_list_path, 'w') as f:
            for file in self.installed_files:
                f.write(f"{file}\n")

    def is_generated_package(self) -> bool:
        """Check if this is a generated package (no external source)."""
        source = self.recipe.get('source', {})
        return source.get('type') == 'generated'

    def check_dependencies(self) -> None:
        """Check that all required dependencies are installed before building."""
        deps = get_package_dependencies(self.recipe, self.flavor_name)

        if not deps:
            return

        missing = []
        for dep in deps:
            if not check_package_installed(self.prefix, dep):
                missing.append(dep)

        if missing:
            missing_list = ', '.join(missing)
            raise BuildError(
                f"Package '{self.package}' has missing dependencies: {missing_list}\n"
                f"Install them first with: python python/mac_builder.py -p <package> build install"
            )

        print(f"All dependencies satisfied: {', '.join(deps)}")

    def run(self, commands: List[str]) -> None:
        """Run the build process"""
        print(f"\n{'=' * 60}")
        print(f"Building {self.package} {self.recipe['version']} for {self.flavor_name}")
        print(f"{'=' * 60}\n")

        # Check all dependencies before starting
        self.check_dependencies()

        # Handle generated packages (no source, templates only)
        if self.is_generated_package():
            print("Generated package - skipping download/build")
            if 'install' in commands or 'build' in commands:
                self.install_generated()
            if 'pkg' in commands:
                self.create_pkg()
            print(f"\n{'=' * 60}")
            print(f"Successfully completed: {', '.join(commands)}")
            print(f"{'=' * 60}\n")
            return

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
            copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir, self.package, self.flavor)

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
            apply_patches(source_dir, self.recipe, self.package, self.patch_dir, self.flavor)

            # Setup environment
            env = setup_environment(self.flavor, self.prefix, self.source_dir )

            # Configure
            build_dir = self.configure(source_dir, env)

            # Build
            self.build(build_dir, env)
        else:
            # For test/install without build, find the build directory
            # First try: if there's exactly one directory, use it (same logic as extract_source)
            build_dirs = [d for d in self.work_dir.iterdir() if d.is_dir()] if self.work_dir.exists() else []
            if not build_dirs:
                raise BuildError("No build directory found. Run 'build' first.")
            if len(build_dirs) > 1:
                # Multiple dirs: try matching by package name (case-insensitive)
                build_dirs = [d for d in build_dirs if d.name.lower().startswith(self.package.lower())]
            if not build_dirs:
                raise BuildError("No build directory found. Run 'build' first.")
            build_dir = build_dirs[0]
            self.source_dir = build_dir
            if (build_dir / 'build').exists():  # CMake build
                build_dir = build_dir / 'build'
            env = setup_environment(self.flavor, self.prefix, self.source_dir)

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
        context['lib_ext'] = self.lib_ext

        # Index size for packages that support it
        context['index_size'] = self.recipe.get('features', {}).get('index_size', 32)

        # Platform
        context['platform'] = self.platform

        # Compiler family (gnu, intel, etc.)
        cc = compilers.get('cc', 'gcc')
        if 'gcc' in cc or 'g++' in cc:
            context['compiler_family'] = 'gnu'
        elif 'icx' in cc or 'icc' in cc:
            context['compiler_family'] = 'intel'
        else:
            context['compiler_family'] = 'gnu'  # default

        # Version components
        version = str(self.recipe.get('version', '0.0.0'))
        version_parts = version.split('.')
        context['version_major'] = version_parts[0] if len(version_parts) > 0 else '0'
        context['version_minor'] = version_parts[1] if len(version_parts) > 1 else '0'
        context['version_patch'] = version_parts[2] if len(version_parts) > 2 else '0'

        # Archiver
        context['ar'] = 'ar'

        # Optimization level from recipe
        oflags = '-O2'
        if 'configure' in self.recipe and 'optimization' in self.recipe['configure']:
            o_level = self.recipe['configure']['optimization'].get('O_level', 2)
            oflags = f'-O{o_level}'
        context['oflags'] = oflags

        # LP64/ILP64 interface
        math_config = self.flavor.get('math', {})
        context['interface'] = math_config.get('interface', 'lp64')

        # Math provider (mkl, lapack, accelerate)
        math_linalg = math_config.get('linalg', 'reference')
        if math_linalg == 'mkl':
            context['math_provider'] = 'mkl'
            # Use correct LP64/ILP64 MKL library names
            interface = context['interface']
            if interface == 'ilp64':
                mkl_interface = 'ilp64'
            else:
                mkl_interface = 'lp64'
            context['mkl_linker_flags'] = f'-lmkl_intel_{mkl_interface} -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl'
            context['mkl_mpi_linker_flags'] = f'-lmkl_scalapack_{mkl_interface} -lmkl_intel_{mkl_interface} -lmkl_gnu_thread -lmkl_core -lmkl_blacs_openmpi_{mkl_interface} -lgomp -lpthread -lm -ldl'
        else:
            context['math_provider'] = 'lapack'
            context['mkl_linker_flags'] = ''
            context['mkl_mpi_linker_flags'] = ''

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
                # First apply check_args for %{host}, %{sdk}, etc.
                cmd = self.check_args([cmd])[0]
                # Then apply install-specific replacements
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{install_prefix}', str(self.prefix))
                run_command(['sh', '-c', cmd], self.work_dir, env, "final-post-install")

        # Run flavor-specific final post commands
        if 'flavor_final_post' in self.recipe['install'] and flavor_name in self.recipe['install']['flavor_final_post']:
            for cmd in self.recipe['install']['flavor_final_post'][flavor_name]:
                # First apply check_args for %{host}, %{sdk}, etc.
                cmd = self.check_args([cmd])[0]
                # Then apply install-specific replacements
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{install_prefix}', str(self.prefix))
                run_command(['sh', '-c', cmd], self.work_dir, env, "flavor-final-post-install")

    def fix_library_symlinks(self) -> None:
        """Fix library symlinks that may have been created as hard copies"""
        lib_dir = self.prefix / "lib"

        if not lib_dir.exists():
            return

        print("\n=== Fixing library symlinks ===")

        # Find all shared library files based on platform
        if self.platform == 'macos':
            lib_files = list(lib_dir.glob("*.dylib"))
            lib_ext = '.dylib'
            ext_len = 6  # len('.dylib')
        else:
            # Linux: find both .so and .so.* files
            lib_files = list(lib_dir.glob("*.so")) + list(lib_dir.glob("*.so.*"))
            lib_ext = '.so'
            ext_len = 3  # len('.so')

        # Group by base name
        lib_groups = {}
        for lib_file in lib_files:
            # Extract base name - handle both dot and dash separators
            name = lib_file.name

            if self.platform == 'macos':
                if name.endswith('.dylib'):
                    name_without_ext = name[:-ext_len]  # Remove .dylib

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
                else:
                    continue
            else:
                # Linux: libname.so.version or libname.so
                import re
                # Match libname.so or libname.so.version
                so_match = re.match(r'(.+)\.so(?:\.\d+.*)?$', name)
                if so_match:
                    base_name = so_match.group(1)
                else:
                    continue

            if base_name not in lib_groups:
                lib_groups[base_name] = []
            lib_groups[base_name].append(lib_file)

        # Process each group
        for base_name, files in lib_groups.items():
            if len(files) <= 1:
                continue

            # Sort by version specificity (most specific last)
            def version_sort_key(f):
                name = f.name
                if self.platform == 'macos':
                    name = name[:-6]  # Remove .dylib
                    if '-' in name and any(c.isdigit() for c in name.split('-')[-1]):
                        # Dash-separated version: count version components
                        version_part = name.split('-', 1)[1]
                        version_components = len(version_part.split('.'))
                        return (version_components, name)
                    else:
                        # Dot-separated version: count all components
                        return (len(name.split('.')), name)
                else:
                    # Linux: libname.so.1.2.3 - count version parts after .so
                    import re
                    match = re.match(r'(.+\.so)(\..*)?$', name)
                    if match and match.group(2):
                        version_parts = match.group(2).count('.')
                        return (version_parts, name)
                    else:
                        return (0, name)

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


def uninstall_package_cli(
    package_name: str,
    flavor_name: str = 'macos',
    with_dependencies: bool = False,
    uninstall_dependents: bool = False,
    dry_run: bool = False,
    force: bool = False
) -> None:
    """
    Uninstall a package from the command line.

    Args:
        package_name: Name of the package to uninstall
        flavor_name: Flavor to get prefix from
        with_dependencies: Also uninstall dependencies (if not needed by others)
        uninstall_dependents: First uninstall packages that depend on this one
        dry_run: Only show what would be done
        force: Uninstall even if other packages depend on this one
    """
    from build_common import (
        load_flavor, uninstall_package, get_reverse_dependencies,
        check_package_in_registry
    )

    try:
        flavor = load_flavor(flavor_name)
        prefix = Path(flavor['prefix'])
    except Exception as e:
        print(f"Error loading flavor '{flavor_name}': {e}", file=sys.stderr)
        sys.exit(1)

    # Check if package is installed
    if not check_package_in_registry(prefix, package_name):
        print(f"Package '{package_name}' is not installed")
        sys.exit(1)

    # Handle --uninstall-dependents: first uninstall packages that depend on this one
    if uninstall_dependents:
        reverse_deps = get_reverse_dependencies(prefix, package_name)
        if reverse_deps:
            print(f"Uninstalling packages that depend on '{package_name}' first:")
            for dep in reverse_deps:
                print(f"\n--- Uninstalling dependent: {dep} ---")
                # Recursively uninstall dependents
                uninstall_package_cli(
                    dep, flavor_name,
                    with_dependencies=False,
                    uninstall_dependents=True,
                    dry_run=dry_run,
                    force=force
                )

    # Now uninstall the target package
    success, uninstalled = uninstall_package(
        prefix, package_name,
        with_dependencies=with_dependencies,
        dry_run=dry_run,
        force=force
    )

    if success:
        if dry_run:
            print(f"\n[DRY RUN] Would uninstall: {', '.join(uninstalled)}")
        else:
            print(f"\nSuccessfully uninstalled: {', '.join(uninstalled)}")
    else:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Build SCLS packages for Unix-like systems (macOS, Linux)')
    parser.add_argument('--package', '-p', help='Package name')
    parser.add_argument('--flavor', '-f', default='macos', help='Flavor name (default: macos)')
    parser.add_argument('--list', '-l', action='store_true', help='List installed packages')
    parser.add_argument('--uninstall', '-u', action='store_true',
                        help='Uninstall the specified package')
    parser.add_argument('--with-deps', action='store_true',
                        help='Also uninstall dependencies (only those not needed by other packages)')
    parser.add_argument('--uninstall-dependents', action='store_true',
                        help='Also uninstall packages that depend on this package')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Show what would be uninstalled without actually removing files')
    parser.add_argument('--force', action='store_true',
                        help='Force uninstall even if other packages depend on this one')
    parser.add_argument('commands', nargs='*',
                        help='Commands to run (build, test, install, pkg)')

    args = parser.parse_args()

    # Handle --list flag
    if args.list:
        list_installed_packages(args.flavor)
        return

    # Handle --uninstall flag
    if args.uninstall:
        if not args.package:
            parser.error("--package/-p is required for --uninstall")
        uninstall_package_cli(
            args.package,
            args.flavor,
            with_dependencies=args.with_deps,
            uninstall_dependents=args.uninstall_dependents,
            dry_run=args.dry_run,
            force=args.force
        )
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
        builder = UnixBuilder(args.package, args.flavor)
        builder.run(args.commands)
    except BuildError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBuild interrupted by user", file=sys.stderr)
        sys.exit(130)


if __name__ == '__main__':
    main()

