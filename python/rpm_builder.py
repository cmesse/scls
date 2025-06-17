#!/usr/bin/env python3
"""
macOS builder for SCLS packages
Builds directly without creating SPEC files
"""

import os
import sys
import argparse
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, extract_source,
    apply_patches, run_command, setup_environment,
    get_configure_args, get_cmake_args, get_parallel_jobs,
    clean_libtool_files, copy_patches_to_sources,
    should_build_package
)


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
        self.project_root = Path(__file__).parent.parent  # Go up from python/ to project root
        self.rpmbuild = self.project_root / "rpmbuild"
        self.sources_dir = self.rpmbuild / "sources"
        self.build_dir = self.rpmbuild / "build"
        self.work_dir = self.build_dir / f"{package}-{self.recipe['version']}-{flavor}"
        self.rpms_dir = self.rpmbuild / "rpms"
        self.srpms_dir = self.rpmbuild / "srpms"
        self.specs_dir = self.rpmbuild / "specs"

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
        configure_type = self.recipe.get('configure', {}).get('type', 'autotools')

        if configure_type == 'autotools':
            # Update config scripts
            self.update_config_scripts(source_dir)

            # Get configure arguments
            args = get_configure_args(self.recipe, self.flavor, self.prefix)

            # Get optimization flags
            cflags, cxxflags, fflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )
            env['CFLAGS'] = cflags
            env['CXXFLAGS'] = cxxflags
            env['FFLAGS'] = fflags
            env['FCFLAGS'] = fflags
            env['LDFLAGS'] = self.flavor['flags'].get('ldflags', '')

            # Run any pre-configure commands
            if 'configure' in self.recipe and 'pre' in self.recipe['configure']:
                for cmd in self.recipe['configure']['pre']:
                    run_command(cmd.split(), source_dir, env, "pre-configure")

            # Run configure
            cmd = ['./configure'] + args
            run_command(cmd, source_dir, env, "configure")

            # Run any post-configure commands
            if 'configure' in self.recipe and 'post' in self.recipe['configure']:
                for cmd in self.recipe['configure']['post']:
                    run_command(cmd.split(), source_dir, env, "post-configure")

        elif configure_type == 'cmake':
            # Create build directory
            build_dir = source_dir / 'build'
            build_dir.mkdir(exist_ok=True)

            # Get CMake arguments
            args = get_cmake_args(self.recipe, self.flavor, self.prefix)

            # Get optimization flags
            cflags, cxxflags, fflags = get_optimization_flags(
                self.recipe, self.flavor, env['CC']
            )
            env['CFLAGS'] = cflags
            env['CXXFLAGS'] = cxxflags
            env['FFLAGS'] = fflags
            env['LDFLAGS'] = self.flavor['flags'].get('ldflags', '')

            # Run CMake
            cmd = ['cmake', '..'] + args
            run_command(cmd, build_dir, env, "cmake configure", self.verbose)

            # Update source_dir to build_dir for subsequent steps
            return build_dir

        else:
            raise BuildError(f"Unknown configure type: {configure_type}")

        return source_dir

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
            copy_patches_to_sources(self.recipe, Path("patches"), self.sources_dir)

            # Extract source
            source_dir = extract_source(
                tarball, self.work_dir,
                self.package, self.recipe['version']
            )

            # Apply patches
            apply_patches(source_dir, self.recipe)

            # Setup environment
            env = setup_environment(self.flavor, self.prefix)

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