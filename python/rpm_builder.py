#!/usr/bin/env python3
"""
RPM SPEC file generator for SCLS packages
Generates SPEC files from recipes and flavors, then builds RPMs
"""

import os
import sys
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    get_optimization_flags, download_source, should_build_package
)

from patch_common import (
    copy_patches_to_sources,
    get_all_patches
)


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

        # Setup paths - can symlink to ~/rpmbuild on Linux
        self.prefix = Path(self.flavor['prefix'])
        self.project_root = Path(__file__).parent.parent
        self.rpm_base = self.project_root / "rpmbuild"
        self.sources_dir = self.rpm_base / "sources"
        self.specs_dir = self.rpm_base / "specs"
        self.generated_dir = Path("generated") / "specs"

        self.host = "x86_64-redhat-linux"

        # Create directories
        self.generated_dir.mkdir(parents=True, exist_ok=True)
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

    def get_file_list(self) -> list:
        """Generate file list for the package"""
        files = []

        # Headers
        files.extend([
            f"{self.prefix}/include/*.h",
            f"{self.prefix}/include/*.hpp",
        ])

        # Libraries (shared only)
        files.extend([
            f"{self.prefix}/lib/*.so",
            f"{self.prefix}/lib/*.so.*",
        ])

        # pkg-config files
        files.append(f"{self.prefix}/lib/pkgconfig/*.pc")

        # Binaries (if any)
        files.append(f"{self.prefix}/bin/*")

        # Exclude common directories
        files.append(f"%exclude {self.prefix}/share")

        return files

    def generate_spec(self) -> Path:
        """Generate RPM SPEC file from template"""
        # Load template
        template_name = self.recipe.get('template', 'default.spec.j2')
        try:
            template = self.jinja_env.get_template(template_name)
        except:
            template = self.jinja_env.get_template('default.spec.j2')

        # Get optimization flags
        cflags, cxxflags, fflags = get_optimization_flags(
            self.recipe, self.flavor, self.flavor['compilers']['cc']
        )

        # Get requirements
        build_requires, requires = self.get_rpm_requires()

        # Get file list
        files = self.get_file_list()

        # Load description from descriptions directory
        description = load_description(self.package)
        if not description:
            description = self.recipe.get('description', self.recipe.get('summary', ''))

        # For RPM, ensure description is properly formatted (no leading/trailing whitespace per line)
        description_lines = []
        for line in description.split('\n'):
            description_lines.append(line.strip())
        formatted_description = '\n'.join(description_lines).strip()

        # Process configure environment for SPEC file
        configure_env_vars = self.get_configure_env_vars()

        # Prepare template variables
        context = {
            'flavor': self.flavor,
            'recipe': self.recipe,
            'package_name': self.package,
            'scls_name': self.scls_name,
            'version': self.recipe['version'],
            'description': formatted_description,
            'homepage': self.recipe.get('homepage', ''),
            'license': self.recipe.get('license', ''),
            'source_url': self.recipe['source']['url'],
            'build_requires': build_requires,
            'requires': requires,
            'prefix': str(self.prefix),
            'cflags': cflags,
            'cxxflags': cxxflags,
            'fflags': fflags,
            'fcflags': fflags,  # Same as fflags
            'ldflags': self.flavor['flags'].get('ldflags', ''),
            'files': files,
            'changelog_date': datetime.now().strftime('%a %b %d %Y'),
            'parallel_build': self.recipe.get('build', {}).get('parallel', True),
            'configure_type': self.recipe.get('configure', {}).get('type', 'autotools'),
            'configure_args': self.get_configure_args(),
            'cmake_args': self.get_cmake_args() if self.recipe.get('configure', {}).get('type') == 'cmake' else [],
            'configure_env_vars': configure_env_vars,
            'patches': self.get_patches(),
            'test_commands': self.recipe.get('test', {}).get('commands', []),
        }

        # Render template
        spec_content = template.render(**context)

        # Write to generated directory first
        spec_filename = f"{self.scls_name}.spec"
        generated_spec = self.generated_dir / spec_filename
        with open(generated_spec, 'w') as f:
            f.write(spec_content)

        print(f"Generated SPEC file: {generated_spec}")
        return generated_spec

    def get_configure_args(self) -> list:
        """Get configure arguments as a list"""
        args = []

        # Standard arguments
        args.append("--prefix=%{prefix}")

        # Shared libraries only
        args.append("--enable-shared")
        args.append("--disable-static")

        # Recipe-specific arguments
        if 'configure' in self.recipe and 'args' in self.recipe['configure']:
            args.extend(self.recipe['configure']['args'])

        return args

    def get_cmake_args(self) -> list:
        """Get CMake arguments as a list"""
        args = []

        # Standard CMake arguments
        args.append("-DCMAKE_INSTALL_PREFIX=%{prefix}")
        args.append("-DCMAKE_BUILD_TYPE=Release")
        args.append("-DCMAKE_INSTALL_LIBDIR=lib")

        # Recipe-specific arguments
        if 'configure' in self.recipe and 'args' in self.recipe['configure']:
            args.extend(self.recipe['configure']['args'])

        return args

    def get_configure_env_vars(self) -> List[Dict[str, str]]:
        """Get configure environment variables for SPEC file"""
        env_vars = []

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


def create_default_template():
    """Create a default SPEC template if it doesn't exist"""
    template_dir = Path("templates")
    template_dir.mkdir(exist_ok=True)

    default_template = template_dir / "default.spec.j2"
    if not default_template.exists():
        template_content = '''#######################################################################
# SCLS {{ flavor.name }} - {{ package_name }}                        #
#######################################################################

%define prefix {{ prefix }}
%define scls_name {{ scls_name }}

Name:           %{scls_name}
Version:        {{ version }}
Release:        1%{?dist}
Summary:        {{ description | truncate(70) }}

License:        {{ license }}
URL:            {{ homepage }}
Source0:        {{ source_url }}
{% for patch in patches %}
Patch{{ patch.number }}:         {{ patch.file }}
{% endfor %}

# Build requirements
{% for req in build_requires %}
BuildRequires:  {{ req }}
{% endfor %}

# Runtime requirements
{% for req in requires %}
Requires:       {{ req }}
{% endfor %}

%description
{{ description }}

%prep
%setup -q -n {{ package_name }}-{{ version }}
{% for patch in patches %}
{% if patch.strip == 1 %}
%patch{{ patch.number }} -p1
{% else %}
%patch{{ patch.number }} -p{{ patch.strip }}
{% endif %}
{% endfor %}

%build
# Setup environment
export CC={{ flavor.compilers.cc }}
export CXX={{ flavor.compilers.cxx }}
export FC={{ flavor.compilers.fc }}
export F77={{ flavor.compilers.fc }}
export CFLAGS="{{ cflags }}"
export CXXFLAGS="{{ cxxflags }}"
export FFLAGS="{{ fflags }}"
export FCFLAGS="{{ fcflags }}"
export LDFLAGS="{{ ldflags }}"

# Configure-specific environment variables
{% for env_var in configure_env_vars %}
{% if '+=' in env_var.value %}
export {{ env_var.name }}="${{{ env_var.name }}:-} {{ env_var.value.replace('+=', '').strip() }}"
{% elif '-=' in env_var.value %}
# Remove operation for {{ env_var.name }} (manual implementation needed)
export {{ env_var.name }}="${{{ env_var.name }}}"
{% else %}
export {{ env_var.name }}="{{ env_var.value }}"
{% endif %}
{% endfor %}

{% if configure_type == 'autotools' %}
%configure \\
{% for arg in configure_args %}
    {{ arg }}{% if not loop.last %} \\{% endif %}
{% endfor %}

{% if parallel_build %}
%make_build
{% else %}
make
{% endif %}

{% elif configure_type == 'cmake' %}
%cmake \\
{% for arg in cmake_args %}
    {{ arg }}{% if not loop.last %} \\{% endif %}
{% endfor %}

%cmake_build

{% elif configure_type == 'custom' %}
# Custom configuration system
{% if recipe.configure.command is defined %}
{{ recipe.configure.command }} \\
{% else %}
./config \\
{% endif %}
{% for arg in configure_args %}
    {{ arg }}{% if not loop.last %} \\{% endif %}
{% endfor %}

{% if parallel_build %}
make -j%{?_smp_mflags}
{% else %}
make
{% endif %}

{% elif configure_type == 'none' %}
# No configure step - direct build
{% if parallel_build %}
make -j%{?_smp_mflags} PREFIX=%{prefix}
{% else %}
make PREFIX=%{prefix}
{% endif %}

{% endif %}

%check
{% if test_commands %}
{% for cmd in test_commands %}
{{ cmd }}
{% endfor %}
{% endif %}

%install
{% if configure_type == 'autotools' %}
%make_install
{% elif configure_type == 'cmake' %}
%cmake_install
{% else %}
make install DESTDIR=%{buildroot}
{% endif %}

# Remove libtool archives
find %{buildroot} -name '*.la' -delete

%files
{% for file in files %}
{{ file }}
{% endfor %}

%changelog
* {{ changelog_date }} SCLS Build System <scls@lbl.gov> - {{ version }}-1
- Initial package for {{ flavor.name }} flavor
{% if patches %}
- Applied {{ patches|length }} patch(es):
{% for patch in patches %}
  - {{ patch.file }}{% if patch.strip != 1 %} (-p{{ patch.strip }}){% endif %}
{% endfor %}
{% endif %}
'''
        with open(default_template, 'w') as f:
            f.write(template_content)
        print(f"Created default template: {default_template}")


def main():
    parser = argparse.ArgumentParser(description='Generate RPM SPEC files for SCLS packages')
    parser.add_argument('--package', '-p', required=True, help='Package name')
    parser.add_argument('--flavor', '-f', required=True, help='Flavor name')
    parser.add_argument('--spec-only', action='store_true',
                        help='Only generate SPEC file, do not build RPM')

    args = parser.parse_args()

    # Ensure default template exists
    create_default_template()

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