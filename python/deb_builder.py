#!/usr/bin/env python3
"""
DEB builder for Debian/Ubuntu hosts.

Produces monolithic .deb packages that install into /opt/scls/<flavor>/.
Mirrors how rpm_builder treats these as vendor packages: no binary/-dev
split, the stack sits outside the FHS, and runtime dependencies between
SCLS packages are stated explicitly in each recipe's `requires:` list.

Inherits UnixBuilder's download/extract/configure/build/install pipeline
(which already stages installs into a DESTDIR) and overrides install() to
stop at the staged buildroot instead of copying files into the live
prefix. create_deb() then wraps the buildroot with a DEBIAN/control file
and invokes `dpkg-deb --build`.

System-package dependency names come out of the recipe in RHEL form
(e.g. gmp-devel, openssl-devel) and are translated via
packaging/system_packages.yaml. Missing entries in that map are a hard
error so drift surfaces at package time instead of install time.
"""

import os
import sys
import argparse
import shutil
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Tuple

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from build_common import (
    BuildError, load_recipe, load_flavor, load_description,
    clean_libtool_files,
    extract_source,
    write_registry_entry,
    get_package_dependencies,
    read_extra_packages,
    resolve_flavor_key,
    run_command,
    should_build_package,
)
from patch_common import apply_patches, get_all_patches
from unix_builder import UnixBuilder


SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
SYSTEM_PACKAGE_MAP_PATH = PROJECT_ROOT / "packaging" / "system_packages.yaml"

# Build tools that belong in Build-Depends only, not Depends. Matches the
# set rpm_builder uses so recipe `requires:` stays format-agnostic.
BUILD_ONLY_TOOLS = {'cmake', 'autoconf', 'automake', 'libtool', 'pkg-config'}


def load_system_package_map() -> Dict[str, str]:
    """Load the RHEL -> Debian package name map.

    A value of None (YAML ~) means "drop this dep, no Debian equivalent."
    We keep None in the returned dict so callers can distinguish "missing"
    (unknown RHEL name, hard error) from "explicitly dropped."
    """
    if not SYSTEM_PACKAGE_MAP_PATH.exists():
        raise BuildError(
            f"System package map not found: {SYSTEM_PACKAGE_MAP_PATH}. "
            "deb_builder requires packaging/system_packages.yaml."
        )
    with open(SYSTEM_PACKAGE_MAP_PATH) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise BuildError(
            f"{SYSTEM_PACKAGE_MAP_PATH} must be a top-level mapping"
        )
    return data


def detect_architecture() -> str:
    """Return dpkg architecture name for the current host."""
    try:
        out = subprocess.check_output(['dpkg', '--print-architecture'], text=True)
        return out.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback table for CI or non-Debian dev hosts running dry-runs.
        machine = platform.machine()
        return {
            'x86_64': 'amd64',
            'aarch64': 'arm64',
            'armv7l': 'armhf',
        }.get(machine, machine)


def _read_deb_package_version(deb_path: Path) -> Tuple[str, str]:
    """Return (Package, Version) from the control metadata of a .deb.

    Returns (None, None) on any failure so the caller can fall back
    to a plain `apt-get install`.
    """
    result = subprocess.run(
        ['dpkg-deb', '-f', str(deb_path), 'Package', 'Version'],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return (None, None)
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, val = line.partition(':')
        if sep and key.strip():
            fields[key.strip()] = val.strip()
    return fields.get('Package'), fields.get('Version')


def _deb_is_already_installed_at_version(name: str, version: str) -> bool:
    """True if package `name` is currently installed with exactly `version`.

    Uses dpkg-query to inspect the local dpkg database. Only an "ii"
    (fully installed) status counts — half-configured/removed-but-not-
    purged states don't; those need a fresh install anyway.
    """
    if not name or not version:
        return False
    result = subprocess.run(
        ['dpkg-query', '-W', '-f', '${db:Status-Abbrev}\t${Version}', name],
        capture_output=True, text=True, check=False,
    )
    # dpkg-query exits 1 when the package isn't known; that's not an error.
    if result.returncode not in (0, 1):
        return False
    parts = result.stdout.split('\t', 1)
    if len(parts) != 2:
        return False
    status, installed_version = parts
    return status.startswith('ii') and installed_version.strip() == version


def _apt_install_deb(deb_path: Path, label: str = "apt-get install") -> None:
    """Install a single .deb, routing to --reinstall when its exact
    Package+Version is already installed.

    Mirrors rpm_builder._dnf_install_rpms's partition-and-dispatch
    semantics: a rebuild of the same version reinstalls (overwrites
    files) rather than hitting apt's "already the newest version"
    no-op; a different version goes through plain install which
    handles upgrade/downgrade naturally.
    """
    deb_arg = str(deb_path) if deb_path.is_absolute() else f"./{deb_path}"
    name, version = _read_deb_package_version(deb_path)
    if _deb_is_already_installed_at_version(name, version):
        print(f"Reinstalling {deb_path} ({name}={version} already installed)")
        cmd = ['sudo', 'apt-get', 'install', '--reinstall', '-y', deb_arg]
    else:
        print(f"Installing {deb_path}")
        cmd = ['sudo', 'apt-get', 'install', '-y', deb_arg]
    run_command(cmd, PROJECT_ROOT, os.environ, label)


class DebBuilder(UnixBuilder):
    def __init__(self, package: str, flavor: str):
        super().__init__(package, flavor)

        if self.platform != 'linux':
            raise BuildError(
                f"deb_builder requires a linux flavor; got platform={self.platform}"
            )

        self.system_package_map = load_system_package_map()
        self.architecture = detect_architecture()
        self.scls_name = f"scls-{self.flavor_name}-{self.package}"
        self.release = str(self.recipe.get('release', '1'))
        self.maintainer = self.recipe.get(
            'maintainer', 'Christian Messe <cmesse@lbl.gov>'
        )

        # Output directory for .deb files. Mirrors rpm_builder's rpmbuild/RPMS
        # but lives under work/ like UnixBuilder's other artifacts.
        self.deb_out_dir = self.rpms_dir  # work/pkgs (from UnixBuilder)

        # Staging dir for the buildroot. Populated by install(); consumed by
        # create_deb(). Kept separate from UnixBuilder's macOS pkg-root so
        # both code paths can coexist on a dual-purpose host.
        self.destdir = self.work_dir / "destdir"

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(PROJECT_ROOT / "templates")),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # -------------------------------------------------------------------
    # Dependency collection (port of rpm_builder.get_rpm_requires, with the
    # system-package names translated to their Debian equivalents at the end)
    # -------------------------------------------------------------------

    def _translate_system_deps(self, names: List[str]) -> List[str]:
        """Apply the RHEL->Debian package name map.

        Names already prefixed with 'scls-' are internal SCLS packages and
        pass through unchanged. Anything else must appear in the map; a
        missing key is a hard error so the map stays complete as recipes
        grow.
        """
        out = []
        for name in names:
            if name.startswith('scls-'):
                out.append(name)
                continue
            if name not in self.system_package_map:
                raise BuildError(
                    f"System package '{name}' has no Debian mapping. "
                    f"Add it to {SYSTEM_PACKAGE_MAP_PATH.relative_to(PROJECT_ROOT)} "
                    f"or mark it null (~) if no Debian equivalent exists."
                )
            deb_name = self.system_package_map[name]
            if deb_name is None:
                continue  # Explicitly dropped.
            out.append(deb_name)
        return out

    def _collect_recipe_system_deps(self) -> Tuple[List[str], List[str]]:
        """Pull rpm_build_requires / rpm_requires out of the recipe."""
        build_requires = []
        requires = []

        def extend_flavor_aware(field, target):
            val = self.recipe.get(field)
            if val is None:
                return
            if isinstance(val, dict):
                flavor_specific = resolve_flavor_key(self.flavor, val)
                if flavor_specific:
                    target.extend(flavor_specific)
                if 'all' in val:
                    target.extend(val['all'])
            elif isinstance(val, list):
                target.extend(val)

        extend_flavor_aware('rpm_build_requires', build_requires)
        extend_flavor_aware('rpm_requires', requires)
        return build_requires, requires

    def _flavor_builds_own_gcc(self) -> bool:
        """True if the `gcc` recipe is in the active flavor's build set.

        When False (e.g. on the `gcc`, `mkl`, `debug`, `intel` flavors whose
        gcc recipe is gated by `include_flavors: [lbl, macos]`), every package
        built for this flavor — bootstrap or not — relies on the host
        toolchain. When True (lbl, macos), non-bootstrap packages pick up
        scls-<flavor>-gcc via the normal `requires:` chain instead.
        """
        try:
            gcc_recipe = load_recipe('gcc')
        except Exception:
            return False
        return should_build_package(gcc_recipe, self.flavor)

    def _collect_auto_system_deps(self) -> List[str]:
        """System build-requires that the builder injects automatically.

        Mirrors rpm_builder's bootstrap-compiler logic and extends it to
        cover the case rpm_builder silently papers over: non-bootstrap
        packages on a Linux flavor whose stack does not include gcc.
        Those packages use the HOST gcc/g++/gfortran at build time and so
        need the same system toolchain deps that bootstrap packages get.
        On RHEL this has been working by ambient state; the Ubuntu path
        doesn't have that luxury.

        Rules, in order of precedence:
          1. Bootstrap package with bootstrap_compilers.cc containing 'gcc'
             → inject gcc/gcc-c++/gcc-gfortran (original behavior).
          2. Bootstrap package with a non-gcc bootstrap cc (e.g. macOS's
             'clang') → inject nothing; platform compiler is sufficient.
          3. Non-bootstrap package on a flavor that does NOT build its own
             gcc (gcc/mkl/debug/intel) → inject gcc/gcc-c++/gcc-gfortran.
             This is the new case.
          4. Non-bootstrap package on a flavor that DOES build its own gcc
             (lbl, macos) → inject nothing; the recipe's own `requires:`
             pulls scls-<flavor>-gcc.
        """
        deps = []
        features = self.recipe.get('features', {})
        is_bootstrap = self.recipe.get('bootstrap', False)

        if is_bootstrap:
            bootstrap = self.flavor.get('bootstrap_compilers', {})
            cc = bootstrap.get('cc', '/usr/bin/gcc')
            if 'gcc' in cc:
                deps.extend(['gcc', 'gcc-c++'])
                if features.get('fortran', False):
                    deps.append('gcc-gfortran')
        elif not self._flavor_builds_own_gcc():
            deps.extend(['gcc', 'gcc-c++'])
            if features.get('fortran', False):
                deps.append('gcc-gfortran')

        deps.extend(['make', 'git'])
        return deps

    def _collect_math_and_mpi_deps(self) -> Tuple[List[str], List[str]]:
        """Math library + MPI deps. Mirrors rpm_builder's logic so both
        builders produce the same dependency graph.
        """
        build_requires = []
        requires = []
        features = self.recipe.get('features', {})
        math_feature = features.get('math', 'none')

        if math_feature in ('serial', 'parallel'):
            linalg = self.flavor.get('math', {}).get('linalg', 'reference')
            if linalg == 'mkl':
                for dep in ('intel-oneapi-mkl', 'intel-oneapi-mkl-devel'):
                    requires.append(dep)
                    build_requires.append(dep)
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)
            elif linalg == 'openblas':
                scls_openblas = f"scls-{self.flavor_name}-openblas"
                requires.append(scls_openblas)
                build_requires.append(scls_openblas)
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)
            elif linalg in ('reference', 'lapack'):
                scls_blas = f"scls-{self.flavor_name}-blas"
                scls_lapack = f"scls-{self.flavor_name}-lapack"
                requires.extend([scls_blas, scls_lapack])
                build_requires.extend([scls_blas, scls_lapack])
                if math_feature == 'parallel':
                    scls_scalapack = f"scls-{self.flavor_name}-scalapack"
                    requires.append(scls_scalapack)
                    build_requires.append(scls_scalapack)

        if features.get('mpi', False):
            scls_mpi = f"scls-{self.flavor_name}-openmpi"
            requires.append(scls_mpi)
            build_requires.append(scls_mpi)

        return build_requires, requires

    def _collect_recipe_scls_deps(self) -> Tuple[List[str], List[str]]:
        """Recipe `requires:` list, transformed to scls-<flavor>-<name>.

        Matches rpm_builder's asymmetric behavior deliberately: for the
        plain-list form, BUILD_ONLY_TOOLS (cmake, autoconf, automake, libtool,
        pkg-config) are build-time only and omitted from runtime Depends. For
        the dict form, every entry goes to BOTH build and runtime. That
        asymmetry looks accidental — a recipe that declares
        `requires: {gcc: [cmake, ...]}` will currently pull cmake into
        runtime deps in both builders — but parity with rpm_builder is what
        existing recipes are written against, so we mirror the quirk rather
        than silently diverging. Fixing it should happen in both builders at
        once, not just here.
        """
        build_requires = []
        requires = []
        recipe_requires = self.recipe.get('requires')
        if recipe_requires is None:
            return build_requires, requires

        def add_unfiltered(names):
            for req in names:
                scls_req = f"scls-{self.flavor_name}-{req}"
                build_requires.append(scls_req)
                requires.append(scls_req)

        def add_list_form(names):
            for req in names:
                scls_req = f"scls-{self.flavor_name}-{req}"
                build_requires.append(scls_req)
                if req not in BUILD_ONLY_TOOLS:
                    requires.append(scls_req)

        if isinstance(recipe_requires, dict):
            flavor_specific = resolve_flavor_key(self.flavor, recipe_requires)
            if flavor_specific:
                add_unfiltered(flavor_specific)
            if 'all' in recipe_requires:
                add_unfiltered(recipe_requires['all'])
        elif isinstance(recipe_requires, list):
            add_list_form(recipe_requires)
        return build_requires, requires

    def get_deb_depends(self) -> Tuple[List[str], List[str]]:
        """Return (Build-Depends, Depends) with all system names translated."""
        br, r = self._collect_recipe_system_deps()
        br.extend(self._collect_auto_system_deps())
        math_br, math_r = self._collect_math_and_mpi_deps()
        br.extend(math_br)
        r.extend(math_r)
        scls_br, scls_r = self._collect_recipe_scls_deps()
        br.extend(scls_br)
        r.extend(scls_r)

        br = self._translate_system_deps(br)
        r = self._translate_system_deps(r)

        # Dedupe preserving order.
        br = list(dict.fromkeys(br))
        r = list(dict.fromkeys(r))
        return br, r

    # -------------------------------------------------------------------
    # Install: override UnixBuilder.install to stage only
    # -------------------------------------------------------------------

    def _generated_install_root(self) -> Path:
        """Stage generated-package files into the destdir buildroot.

        UnixBuilder.run() has a fast path for generated packages (source: none)
        that bypasses install() entirely and calls install_generated(), which
        writes templates/files into _generated_install_root(). Defaulting
        that to the live prefix would mutate /opt/scls/<flavor> during
        the build; we redirect to the destdir buildroot so create_deb()
        can wrap it.

        Critically, self.prefix is NOT rebound — the parent still passes
        str(self.prefix) as the Jinja `prefix` context, so rendered file
        contents (e.g. share/scls/config.yaml) carry the real install prefix,
        not the staging path.
        """
        if self.destdir.exists():
            shutil.rmtree(self.destdir)
        destdir_prefix = self.destdir / str(self.prefix).lstrip('/')
        destdir_prefix.mkdir(parents=True)
        return destdir_prefix

    def install(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Stage the install into self.destdir; do not copy into live prefix.

        Parallels UnixBuilder.install up through the DESTDIR make install
        and pre/post hooks, then stops. We write the registry entry INTO
        the destdir so it ships inside the .deb.
        """
        if self.destdir.exists():
            shutil.rmtree(self.destdir)
        self.destdir.mkdir(parents=True)

        # Pre-install commands
        if 'install' in self.recipe and 'pre' in self.recipe['install']:
            for cmd in self.recipe['install']['pre']:
                expanded = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded], build_dir, env, "pre-install")

        if self.package == 'zlib' and (build_dir / 'zlib').exists():
            build_dir = build_dir / 'zlib'

        if not build_dir.exists():
            raise BuildError(f"Build directory does not exist: {build_dir}")

        # Custom vs default install
        if 'install' in self.recipe and 'commands' in self.recipe['install']:
            for cmd in self.recipe['install']['commands']:
                cmd = cmd.replace('%{buildroot}', str(self.destdir))
                cmd = cmd.replace('%{prefix}', str(self.prefix))
                cmd = cmd.replace('%{libext}', self.lib_ext)
                expanded = self.check_args([cmd])[0]
                run_command(['sh', '-c', expanded], build_dir, env, "install")
        else:
            install_cmd = ['make', 'install', f'DESTDIR={self.destdir}']
            if 'install' in self.recipe:
                if 'args' in self.recipe['install']:
                    install_cmd.extend(self.check_args(self.recipe['install']['args']))
                if 'flavor_args' in self.recipe['install']:
                    flavor_specific = resolve_flavor_key(
                        self.flavor, self.recipe['install']['flavor_args']
                    )
                    if flavor_specific:
                        install_cmd.extend(self.check_args(flavor_specific))
            run_command(install_cmd, build_dir, env, "install")

        # Post-install hooks. Three variants (post / flavor_post / platform_post)
        # all use the same %{...} substitution conventions as UnixBuilder.
        destdir_prefix = self.destdir / str(self.prefix).lstrip('/')

        def run_post(cmds, label):
            for cmd in cmds:
                cmd = cmd.replace('%{buildroot}', str(self.destdir))
                cmd = cmd.replace('%{final_prefix}', str(self.prefix))
                cmd = cmd.replace('%{prefix}', str(destdir_prefix))
                cmd = self.check_args([cmd])[0]
                run_command(['sh', '-c', cmd], build_dir, env, label)

        if 'install' in self.recipe and 'post' in self.recipe['install']:
            run_post(self.recipe['install']['post'], "post-install")
        if 'install' in self.recipe and 'flavor_post' in self.recipe['install']:
            fp = resolve_flavor_key(self.flavor, self.recipe['install']['flavor_post'])
            if fp:
                run_post(fp, "flavor-post-install")
        if 'install' in self.recipe and 'platform_post' in self.recipe['install']:
            pp = self.recipe['install']['platform_post'].get(self.platform)
            if pp:
                run_post(pp, f"platform-post-install ({self.platform})")

        # Drop libtool archives and system-managed info directory.
        clean_libtool_files(destdir_prefix)
        info_dir = destdir_prefix / "share" / "info"
        if info_dir.exists():
            shutil.rmtree(info_dir, ignore_errors=True)

        if not destdir_prefix.exists():
            raise BuildError(f"No files staged under {destdir_prefix}")

        # Write the SCLS registry entry INTO the destdir so it gets packaged
        # alongside the rest of the install tree. write_registry_entry places
        # the file at <prefix>/share/scls/registry/<name>.yaml, so passing
        # destdir_prefix as "prefix" stages it correctly.
        write_registry_entry(destdir_prefix, self.recipe, self.flavor_name)

        print(f"Staged install under {self.destdir}")

    # -------------------------------------------------------------------
    # .deb creation
    # -------------------------------------------------------------------

    def write_control(self) -> None:
        """Render DEBIAN/control into the staged destdir.

        We discard the Build-Depends list returned by get_deb_depends(): this
        is a binary package (dpkg-deb --build output), not a source package,
        so Build-Depends would be dead metadata. get_deb_depends() still
        returns the full tuple so a future source-package path (or tooling
        that wants to pre-check build hosts) can consume it.
        """
        debian_dir = self.destdir / "DEBIAN"
        debian_dir.mkdir(parents=True, exist_ok=True)

        _, depends = self.get_deb_depends()

        description = load_description(self.package) or self.recipe.get(
            'summary', self.package
        )
        summary = self.recipe.get('summary') or description.split('\n', 1)[0]
        # Debian control descriptions: first line is the summary (on the
        # Description: line itself), subsequent lines are indented by one
        # space, with '.' used for blank paragraph separators.
        description_lines = description.strip().splitlines()[1:] if (
            description.strip().startswith(summary)
        ) else description.strip().splitlines()

        template = self.jinja_env.get_template("default.control.j2")
        rendered = template.render(
            scls_name=self.scls_name,
            version=self.recipe['version'],
            release=self.release,
            architecture=self.architecture,
            maintainer=self.maintainer,
            depends=depends,
            homepage=self.recipe.get('homepage', ''),
            summary=summary,
            description_lines=description_lines,
        )
        control_path = debian_dir / "control"
        control_path.write_text(rendered)
        print(f"Wrote {control_path}")

    def create_deb(self) -> Path:
        """Package self.destdir into a .deb via dpkg-deb --build."""
        if not self.destdir.exists():
            raise BuildError(
                f"No staged buildroot at {self.destdir}. Run 'install' first."
            )
        self.write_control()
        self.deb_out_dir.mkdir(parents=True, exist_ok=True)

        deb_filename = (
            f"{self.scls_name}_{self.recipe['version']}-{self.release}"
            f"_{self.architecture}.deb"
        )
        deb_path = self.deb_out_dir / deb_filename

        cmd = [
            'dpkg-deb',
            '--root-owner-group',
            '--build',
            str(self.destdir),
            str(deb_path),
        ]
        run_command(cmd, self.work_dir, os.environ, "dpkg-deb --build")
        print(f"Created {deb_path}")

        # Local registry marker so build-order tracking knows this package is
        # done without needing the .deb to be installed yet. Mirrors what
        # rpm_builder writes under rpmbuild/registry/.
        marker_dir = PROJECT_ROOT / "debbuild" / "registry" / self.flavor_name
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker = marker_dir / f"{self.package}.yaml"
        marker.write_text(
            f"name: {self.package}\nversion: {self.recipe['version']}\n"
        )
        return deb_path

    # -------------------------------------------------------------------
    # Source package (3.0 quilt) — license-compliance analogue of SRPM
    # -------------------------------------------------------------------

    def _render_source_control(self, build_depends: List[str],
                               depends: List[str]) -> str:
        """debian/control in SOURCE format.

        This is a DIFFERENT file from the binary DEBIAN/control: it has a
        Source: stanza at top with Build-Depends (no Architecture), then
        one Package: stanza per binary (we produce exactly one). The
        template in templates/default.control.j2 is binary-only, so we
        render this one inline.
        """
        description = (load_description(self.package)
                       or self.recipe.get('summary', self.package))
        summary = (self.recipe.get('summary')
                   or description.split('\n', 1)[0])
        # Same indentation rule as the binary template: summary goes on
        # Description:, subsequent lines are indented by one space with
        # '.' standing in for blank paragraph separators.
        desc_body = description.strip().splitlines()
        if desc_body and desc_body[0] == summary:
            desc_body = desc_body[1:]

        lines = [
            f"Source: {self.scls_name}",
            "Section: science",
            "Priority: optional",
            f"Maintainer: {self.maintainer}",
            "Standards-Version: 4.6.2",
        ]
        homepage = self.recipe.get('homepage', '')
        if homepage:
            lines.append(f"Homepage: {homepage}")
        if build_depends:
            lines.append(f"Build-Depends: {', '.join(build_depends)}")

        lines.extend([
            "",
            f"Package: {self.scls_name}",
            f"Architecture: {self.architecture}",
        ])
        if depends:
            lines.append(f"Depends: {', '.join(depends)}")
        lines.append(f"Description: {summary}")
        for line in desc_body:
            lines.append(f" {line if line else '.'}")
        lines.append("")  # trailing newline
        return '\n'.join(lines)

    def _read_changelog_entry(self) -> Tuple[str, List[str]]:
        """Return (rfc5322_date, body_lines) for the most recent entry
        in changelogs/<package>.md.

        Reading from the on-disk changelog (rather than `datetime.now`)
        is what makes source-package output reproducible across runs:
        the tarball hashes only change when the committed changelog
        does. Matches rpm_builder.load_changelog's source of truth so
        both builders embed the same timestamp for a given release.

        Creates a skeleton changelog via rpm_builder.ensure_changelog_
        exists if the file is missing — same side effect rpm_builder
        has during its own run, so repeated builds on a fresh checkout
        converge on a committed file.
        """
        from datetime import datetime
        # Auto-create so the first run doesn't fail. The creation uses
        # datetime.now() (not reproducible), but commit the resulting
        # file and subsequent runs are stable. This mirrors rpm_builder
        # on a fresh host.
        from rpm_builder import ensure_changelog_exists
        changelogs_dir = PROJECT_ROOT / 'changelogs'
        ensure_changelog_exists(
            self.package, self.recipe['version'], self.release,
            changelogs_dir=changelogs_dir,
        )

        changelog_path = changelogs_dir / f'{self.package}.md'
        content = changelog_path.read_text()

        # Find the first "## Version <vr> - <date>" block. Bullets until
        # the next version header or EOF form the body.
        version_line = None
        body: List[str] = []
        for line in content.splitlines():
            if version_line is None:
                if line.startswith('## Version'):
                    version_line = line
                continue
            if line.startswith('## Version'):
                break
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            body.append(stripped)

        if version_line is None:
            raise BuildError(
                f"No '## Version ...' entry found in {changelog_path}. "
                f"Source-package build needs a parseable changelog."
            )

        parts = version_line.replace('## Version', '').strip()
        if ' - ' not in parts:
            raise BuildError(
                f"Changelog entry '{version_line}' in {changelog_path} "
                f"is missing the ' - <date>' separator."
            )
        _vr, date_part = parts.split(' - ', 1)
        date_part = date_part.strip()
        try:
            dt = datetime.strptime(date_part, '%a %b %d %Y')
        except ValueError as e:
            raise BuildError(
                f"Could not parse date '{date_part}' in {changelog_path}: "
                f"{e}. Expected format 'Day Mon DD YYYY' (e.g. "
                f"'Fri Apr 24 2026')."
            )
        # Zero-out time so the output is stable; dpkg-parsechangelog
        # requires numeric TZ offset (not 'GMT' or 'UTC').
        rfc_date = dt.strftime('%a, %d %b %Y 00:00:00 +0000')
        return rfc_date, body

    def _render_changelog(self) -> str:
        """debian/changelog in dpkg-parseable format, reproducible.

        Format is strict: the source name must match Source: in control,
        the version must match the rest of the package, the trailer
        line must start with ' -- ' (space-dash-dash-space), and the
        trailer date must be RFC 5322 with a numeric TZ offset.
        """
        date_str, body = self._read_changelog_entry()
        # Normalize bullets: strip any leading '-' or '*' so we can re-
        # emit in Debian changelog style (two-space leading, '* ' prefix).
        if body:
            normalized = []
            for line in body:
                trimmed = line.lstrip('-*').strip()
                if trimmed:
                    normalized.append(f"  * {trimmed}")
            body_text = '\n'.join(normalized) if normalized else "  * SCLS build."
        else:
            body_text = "  * SCLS build."

        return (
            f"{self.scls_name} ({self.recipe['version']}-{self.release}) "
            f"unstable; urgency=medium\n"
            f"\n"
            f"{body_text}\n"
            f"\n"
            f" -- {self.maintainer}  {date_str}\n"
        )

    def _render_copyright(self) -> str:
        """Minimal debian/copyright in DEP-5 format.

        Points the consumer at the upstream LICENSE/COPYING inside the
        orig tarball rather than inlining the full text (which varies
        per package and is already preserved in the shipped source).
        """
        lines = [
            "Format: https://www.debian.org/doc/packaging-manuals/"
            "copyright-format/1.0/",
            f"Upstream-Name: {self.package}",
        ]
        homepage = self.recipe.get('homepage', '')
        if homepage:
            lines.append(f"Source: {homepage}")
        license_name = self.recipe.get('license', 'See upstream')
        lines.extend([
            "",
            "Files: *",
            "Copyright: Upstream — see LICENSE/COPYING in the extracted "
            "source",
            f"License: {license_name}",
            " Full license text is preserved in the upstream source "
            "tarball.",
            "",
            "Files: debian/*",
            "Copyright: 2020-present, The Regents of the University "
            "of California",
            "License: BSD-3-Clause-LBNL",
            " See the SCLS LICENSE file for the full LBNL BSD variant "
            "text.",
            "",
        ])
        return '\n'.join(lines)

    def _render_rules(self) -> str:
        """Minimal debian/rules.

        Required by 3.0 (quilt) for the source package to be valid, but
        not used by SCLS — binary rebuilds go through `scls build`, not
        dpkg-buildpackage. The stub is there so tools like dpkg-source
        -x produce a tree that at least LOOKS buildable.
        """
        return (
            "#!/usr/bin/make -f\n"
            "# SCLS source packages are not rebuilt via dpkg-buildpackage.\n"
            "# Run `scls build <package>` against the SCLS checkout to "
            "produce binaries.\n"
            "%:\n"
            "\tdh $@\n"
        )

    def _detect_tarball_compression(self, tarball: Path) -> str:
        """Return the compression extension ('gz', 'bz2', 'xz') for
        constructing the Debian-standard orig.tar.<ext> filename.
        """
        name = tarball.name.lower()
        if name.endswith('.tar.gz') or name.endswith('.tgz'):
            return 'gz'
        if name.endswith('.tar.bz2') or name.endswith('.tbz2'):
            return 'bz2'
        if name.endswith('.tar.xz') or name.endswith('.txz'):
            return 'xz'
        # Fallback: sniff magic bytes.
        with open(tarball, 'rb') as f:
            head = f.read(6)
        if head[:2] == b'\x1f\x8b':
            return 'gz'
        if head[:3] == b'BZh':
            return 'bz2'
        if head[:6] == b'\xfd7zXZ\x00':
            return 'xz'
        raise BuildError(f"Could not determine compression of {tarball}")

    def _stage_pristine_upstream(self, tarball: Path, dest: Path) -> None:
        """Extract tarball into dest, stripping the single top-level
        directory that upstream tarballs universally ship.

        dpkg-source -b wants the source tree rooted directly in the
        passed directory, not inside a subdirectory. build_common's
        extract_source preserves the upstream top dir, so we extract
        then flatten.
        """
        extracted_top = extract_source(
            tarball, dest, self.package, self.recipe['version']
        )
        if extracted_top.parent != dest:
            raise BuildError(
                f"extract_source returned unexpected path: "
                f"{extracted_top} not under {dest}"
            )
        # Move everything from <dest>/<top>/ up into <dest>/ and remove
        # the now-empty top dir.
        for item in list(extracted_top.iterdir()):
            shutil.move(str(item), str(dest / item.name))
        extracted_top.rmdir()

    def _write_scls_build_info(self, debian_dir: Path) -> None:
        """Bundle the SCLS inputs needed to reproduce the binary into
        debian/scls-build-info/.

        An SRPM carries the fully-rendered SPEC with %build/%install
        baked in — self-contained reproduction info. Our debian/rules
        is a stub (we don't rebuild via dpkg-buildpackage), so without
        this subdirectory the source package would merely point at an
        external SCLS checkout. LICENSE_POLICY.md requires the source
        package to carry enough to reproduce the binary; shipping the
        recipe + flavor + SCLS revision + rendered binary control
        satisfies that.

        Contents:
          recipe.yaml       — this package's recipe (configure/build
                              /install args, patches, tests).
          flavor.yaml       — the active flavor (compilers, opt flags,
                              math library, prefix).
          control-binary    — the DEBIAN/control we would write for the
                              binary .deb (runtime Depends snapshot).
          scls-revision.txt — SCLS git commit at build time, or
                              'unknown' if .git is absent.
          README.md         — pointer to the SCLS project and rebuild
                              instructions.
        """
        info = debian_dir / 'scls-build-info'
        info.mkdir()

        # Recipe and flavor — canonical inputs to the builder.
        recipe_src = PROJECT_ROOT / 'recipes' / f'{self.package}.yaml'
        if recipe_src.exists():
            shutil.copy2(recipe_src, info / 'recipe.yaml')
        flavor_src = PROJECT_ROOT / 'flavors' / f'{self.flavor_name}.yaml'
        if flavor_src.exists():
            shutil.copy2(flavor_src, info / 'flavor.yaml')

        # Rendered binary control. This is what dpkg-deb --build would
        # write for this package today; shipping a snapshot lets a
        # reviewer see the intended runtime deps without rerunning the
        # builder.
        _, depends = self.get_deb_depends()
        description = (load_description(self.package)
                       or self.recipe.get('summary', self.package))
        summary = (self.recipe.get('summary')
                   or description.split('\n', 1)[0])
        desc_body = description.strip().splitlines()
        if desc_body and desc_body[0] == summary:
            desc_body = desc_body[1:]
        control_binary_lines = [
            f"Package: {self.scls_name}",
            f"Version: {self.recipe['version']}-{self.release}",
            "Section: science",
            "Priority: optional",
            f"Architecture: {self.architecture}",
            f"Maintainer: {self.maintainer}",
        ]
        if depends:
            control_binary_lines.append(f"Depends: {', '.join(depends)}")
        homepage = self.recipe.get('homepage', '')
        if homepage:
            control_binary_lines.append(f"Homepage: {homepage}")
        control_binary_lines.append(f"Description: {summary}")
        for line in desc_body:
            control_binary_lines.append(f" {line if line else '.'}")
        control_binary_lines.append("")
        (info / 'control-binary').write_text('\n'.join(control_binary_lines))

        # SCLS revision: capture git HEAD if we're inside a work tree.
        # Failure (no git, detached state, or plumbing error) maps to
        # "unknown" — the source package must build even on hosts with
        # no git installed, though reproducibility degrades.
        revision = 'unknown'
        try:
            result = subprocess.run(
                ['git', '-C', str(PROJECT_ROOT), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                revision = result.stdout.strip()
        except (FileNotFoundError, OSError):
            pass
        (info / 'scls-revision.txt').write_text(revision + '\n')

        (info / 'README.md').write_text(
            f"# SCLS build metadata for {self.scls_name}\n"
            f"\n"
            f"This directory carries the inputs SCLS used to build the\n"
            f"binary `.deb`. It satisfies the source-availability\n"
            f"obligation documented in `LICENSE_POLICY.md` by pairing the\n"
            f"upstream tarball + patches with the recipe/flavor metadata\n"
            f"SCLS would use to reproduce the binary.\n"
            f"\n"
            f"## Files\n"
            f"\n"
            f"- `recipe.yaml` — the SCLS recipe for this package\n"
            f"  (configure/build/install logic, patches, tests).\n"
            f"- `flavor.yaml` — the active SCLS flavor (compilers,\n"
            f"  optimization flags, math library, install prefix).\n"
            f"- `control-binary` — the `DEBIAN/control` snapshot that\n"
            f"  the binary `.deb` carried at the time this source\n"
            f"  package was produced.\n"
            f"- `scls-revision.txt` — the SCLS git commit under which\n"
            f"  this source package was rendered. `unknown` if the\n"
            f"  build host had no git available.\n"
            f"\n"
            f"## Rebuilding\n"
            f"\n"
            f"The `debian/rules` in this source package is a stub. SCLS\n"
            f"packages are rebuilt via the SCLS CLI, not via\n"
            f"`dpkg-buildpackage`:\n"
            f"\n"
            f"    git clone https://github.com/cmesse/scls  # at the pinned revision\n"
            f"    cd scls\n"
            f"    ./scls build {self.package}\n"
        )

    def _write_debian_dir(self, src_dir: Path) -> None:
        """Populate src_dir/debian/ with control, changelog, rules,
        copyright, source/format, scls-build-info/, and patches/ with
        a series file.
        """
        debian = src_dir / 'debian'
        debian.mkdir()

        source_meta = debian / 'source'
        source_meta.mkdir()
        (source_meta / 'format').write_text('3.0 (quilt)\n')

        build_depends, depends = self.get_deb_depends()
        (debian / 'control').write_text(
            self._render_source_control(build_depends, depends)
        )
        (debian / 'changelog').write_text(self._render_changelog())
        (debian / 'copyright').write_text(self._render_copyright())

        rules = debian / 'rules'
        rules.write_text(self._render_rules())
        rules.chmod(0o755)

        # SCLS-specific reproduction metadata (addresses the
        # source-availability gap called out in LICENSE_POLICY.md).
        self._write_scls_build_info(debian)

        # Patches: resolve via patch_common so flavor-specific selection
        # mirrors what the binary build applied. Bundle into
        # debian/patches/ with a series file; dpkg-source -x will re-
        # apply them on extraction.
        patches = get_all_patches(
            self.recipe, self.package, self.patches_root, self.flavor
        )
        if not patches:
            return
        patches_dir = debian / 'patches'
        patches_dir.mkdir()
        series_lines = []
        package_patches_dir = self.patches_root / self.package
        for p in patches:
            patch_file = p['file'] if isinstance(p, dict) else p
            # Honor non-default strip level (quilt series line syntax
            # accepts ' -pN' options). patch_common exposes this via the
            # 'strip' key; default is -p1, so we only annotate otherwise.
            strip = p.get('strip', 1) if isinstance(p, dict) else 1
            src_patch = package_patches_dir / patch_file
            if not src_patch.exists():
                # Hard-fail: producing a .dsc that silently drops a patch
                # the binary build applied would ship broken "source"
                # that can't reconstruct the binary. Matches how the
                # binary apply_patches path treats this.
                raise BuildError(
                    f"Patch {src_patch} referenced by recipe for "
                    f"{self.package} is not on disk. Cannot build a "
                    f"source package that silently omits it."
                )
            shutil.copy2(src_patch, patches_dir / patch_file)
            if strip != 1:
                series_lines.append(f"{patch_file} -p{strip}")
            else:
                series_lines.append(patch_file)
        (patches_dir / 'series').write_text(
            '\n'.join(series_lines) + '\n'
        )

    def create_source_package(self) -> Path:
        """Produce a 3.0 (quilt) source package triplet in work/spkgs/.

        Mirrors rpmbuild -ba's source-RPM output semantically: ships the
        upstream tarball plus our patches plus generated debian/
        metadata, so a downstream consumer can reconstruct the binary
        from scratch. Required for license compliance with copyleft
        dependencies per LICENSE_POLICY.md.

        Output triplet (Debian's canonical source-package shape):
          work/spkgs/<scls-name>_<upstream-version>.orig.tar.<ext>
          work/spkgs/<scls-name>_<version>-<release>.debian.tar.xz
          work/spkgs/<scls-name>_<version>-<release>.dsc

        Limitations in this first pass:
          * Recipes with extra_sources (currently: gcc with in-tree gmp/
            mpfr/mpc) are not supported; we fail loudly rather than
            silently omit the additional tarballs.
          * Generated packages (environment) have no upstream tarball;
            no source package is meaningful, so we skip them.
        """
        # Skip generated packages — they are template-only, nothing to
        # ship as "source" that isn't already in the SCLS repository.
        if self.is_generated_package():
            print(f"Skipping source package for generated recipe "
                  f"{self.package}")
            return None

        if 'extra_sources' in self.recipe:
            raise BuildError(
                f"Source package not yet supported for '{self.package}': "
                f"recipe has extra_sources (multi-tarball packaging is a "
                f"known follow-up)."
            )

        # Locate the already-downloaded upstream tarball.
        source_url = self.recipe['source'].get(
            'source0', self.recipe['source']['url']
        )
        source_url = source_url.replace('%{version}', self.recipe['version'])
        orig_filename = source_url.split('/')[-1]
        orig_path = self.sources_dir / orig_filename
        if not orig_path.exists():
            raise BuildError(
                f"Upstream tarball not found at {orig_path}. Run the "
                f"build phase first so the tarball is downloaded."
            )

        # Staging area: a fresh directory containing both the orig tar
        # (under its Debian-standard name) and the source tree dpkg-
        # source -b will operate on.
        staging = (self.work_dir
                   / f"srcpkg-{self.scls_name}-{self.recipe['version']}")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        src_dir = staging / f"{self.scls_name}-{self.recipe['version']}"
        src_dir.mkdir()

        # Pristine upstream goes directly into src_dir (no top-level dir).
        self._stage_pristine_upstream(orig_path, src_dir)

        # Copy the orig tarball under the Debian-standard name next to
        # the source tree. dpkg-source -b reads it from here.
        orig_ext = self._detect_tarball_compression(orig_path)
        orig_debian_name = (
            f"{self.scls_name}_{self.recipe['version']}.orig.tar.{orig_ext}"
        )
        shutil.copy2(orig_path, staging / orig_debian_name)

        # Overlay debian/ metadata.
        self._write_debian_dir(src_dir)

        # Produce the triplet.
        cmd = ['dpkg-source', '-b', str(src_dir)]
        run_command(cmd, staging, os.environ, "dpkg-source -b")

        # Move outputs into the permanent source-package directory.
        out_dir = PROJECT_ROOT / 'work' / 'spkgs'
        out_dir.mkdir(parents=True, exist_ok=True)
        produced = []
        for pattern in (f"{self.scls_name}_*.dsc",
                        f"{self.scls_name}_*.debian.tar.*",
                        f"{self.scls_name}_*.orig.tar.*"):
            for f in staging.glob(pattern):
                dest = out_dir / f.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(f), str(dest))
                produced.append(dest)

        dsc = next((p for p in produced if p.suffix == '.dsc'), None)
        if dsc is None:
            raise BuildError(
                "dpkg-source -b completed but no .dsc file was produced "
                f"(expected under {staging})."
            )
        print(f"Created source package: {dsc}")
        return dsc

    def install_deb(self) -> None:
        """Install (or reinstall) the most-recently-built .deb via apt-get.

        Mirrors RPMBuilder.install_rpm semantically, including its
        reinstall-when-exact-version-is-already-installed behavior (see
        rpm_builder._partition_rpms_for_install). A rebuild of the same
        version overwrites the installed files instead of apt-get's
        "already the newest version" no-op.
        """
        pattern = f"{self.scls_name}_*_{self.architecture}.deb"
        candidates = sorted(
            self.deb_out_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            raise BuildError(
                f"No built .deb found for {self.scls_name} in {self.deb_out_dir}"
            )
        _apt_install_deb(candidates[0], label="apt-get install")

    def check_system_build_deps(self) -> None:
        """Verify non-SCLS entries in Build-Depends are installed on the host.

        SCLS inter-package deps (scls-<flavor>-<pkg>) are checked separately
        by UnixBuilder.check_dependencies against the prefix registry. This
        method fills the gap for the HOST packages that must be present for
        the build to run at all — autoconf/libtool for autoreconf hooks,
        -dev packages for headers, etc. Without this, missing tools surface
        as opaque mid-build failures (`sh: 1: autoreconf: not found`).

        Skipped silently if dpkg-query isn't available (non-Debian host
        running a dry-run).
        """
        if shutil.which('dpkg-query') is None:
            return

        build_depends, _ = self.get_deb_depends()
        system_deps = [d for d in build_depends if not d.startswith('scls-')]
        if not system_deps:
            return

        missing = []
        for pkg in system_deps:
            result = subprocess.run(
                ['dpkg-query', '-W', '-f', '${db:Status-Abbrev}', pkg],
                capture_output=True, text=True, check=False,
            )
            # Status-Abbrev for fully-installed packages starts with "ii".
            # Anything else (not installed, half-configured, removed-but-
            # -config-present) means the build can't rely on the package.
            if result.returncode != 0 or not result.stdout.startswith('ii'):
                missing.append(pkg)

        if missing:
            raise BuildError(
                f"Missing host packages required to build {self.package}:\n"
                f"  {', '.join(missing)}\n"
                f"Install them with:\n"
                f"  sudo apt-get install -y {' '.join(missing)}"
            )

    # -------------------------------------------------------------------
    # Orchestration
    # -------------------------------------------------------------------

    def test(self, build_dir: Path, env: Dict[str, str]) -> None:
        """Run tests with rpmbuild-parity semantics.

        Three changes over UnixBuilder.test:

        1. Env carries the flavor's CFLAGS/CXXFLAGS/FFLAGS/FCFLAGS/
           LDFLAGS. rpmbuild's %check section exports these explicitly
           (see default.spec.j2:232-237), so tests compile with the same
           arch/optimization flags as the build. setup_environment
           doesn't set them and UnixBuilder.test doesn't either, so the
           DEB path otherwise inherits whatever the parent shell has —
           usually nothing — and templates that depend on arch defines
           (blaze's SIMD specializations being the canonical case, where
           missing __AVX2__ drops SIMDci64::equal into a `= delete`
           branch) fail to compile. Pulled from self.c*flags which were
           populated during super().run([build,install])'s configure
           step and persist on the instance.

        2. Env is augmented with the destdir-staged prefix paths, mirroring
             CPATH=%{buildroot}%{prefix}/include
             LIBRARY_PATH=%{buildroot}%{prefix}/lib
             LD_LIBRARY_PATH=%{buildroot}%{prefix}/lib + %{prefix}/lib
           so a recipe whose test compiles against `-I%{prefix}/include`
           still finds headers that are present only in the staged
           buildroot, not the live prefix. UnixBuilder.test only appends
           self.prefix/lib to LD_LIBRARY_PATH, which is insufficient on a
           first-ever build (live prefix empty).

        3. CWD for test commands is the source root, not build_dir. For
           cmake recipes build_dir is `<source>/build/`; some tests (e.g.
           blaze's `cd blazetest && ./configure`) reference sibling
           directories that don't exist below build/. rpmbuild's %check
           runs from $srcdir, so we match it.
        """
        # (1) Compiler flags from the configured flavor. Skipped for
        # recipes that set configure.skip_compiler_env — same knob
        # rpm_builder's SPEC template honors via `skip_compiler_env`.
        skip_compiler_env = self.recipe.get('configure', {}).get(
            'skip_compiler_env', False
        )
        if not skip_compiler_env:
            if self.cflags:
                env['CFLAGS'] = self.cflags
            if self.cxxflags:
                env['CXXFLAGS'] = self.cxxflags
            if self.fcflags:
                env['FCFLAGS'] = self.fcflags
                env['FFLAGS'] = self.fcflags
            if self.ldflags:
                env['LDFLAGS'] = self.ldflags

        # (2) Destdir-staged include/lib paths.
        if self.destdir.exists():
            destdir_prefix = self.destdir / str(self.prefix).lstrip('/')
            destdir_include = destdir_prefix / 'include'
            destdir_lib = destdir_prefix / 'lib'

            def _prepend(var: str, value: str) -> None:
                existing = env.get(var, '')
                env[var] = f"{value}:{existing}" if existing else value

            if destdir_include.is_dir():
                _prepend('CPATH', str(destdir_include))
            if destdir_lib.is_dir():
                _prepend('LIBRARY_PATH', str(destdir_lib))
                _prepend('LD_LIBRARY_PATH', str(destdir_lib))

        # (3) Source-root CWD for tests. self.source_dir is set during
        # super().run() — either the build-phase branch or the else
        # branch that reconstructs state from disk. Fall back to
        # build_dir if it's somehow unset (shouldn't happen in practice).
        test_cwd = build_dir
        if self.source_dir:
            candidate = Path(self.source_dir)
            if candidate.is_dir():
                test_cwd = candidate

        super().test(test_cwd, env)

    def run(self, commands: List[str]) -> None:
        """Run the build pipeline.

        Supports: build, test, install, deb, source. The usual invocation
        is ['build', 'test', 'install', 'deb', 'source']; 'source' is the
        3.0 (quilt) source-package analogue of rpmbuild's SRPM output.

        Semantics mirror UnixBuilder.run() except:
          * 'install' stages into destdir instead of the live prefix.
          * Tests run AFTER install (matching rpmbuild's %check-after-
            %install ordering), not before. UnixBuilder.run hardcodes
            test-before-install; on the RPM path rpmbuild reorders
            internally, but on the DEB path we have to do it ourselves
            or recipes whose tests need prefix/include fail on a
            first-ever build.
          * 'deb' wraps destdir with a .deb.
          * 'source' produces the 3.0 (quilt) triplet from the upstream
            tarball + patches + generated debian/ metadata.
        """
        # Narrow fast-paths when only packaging steps are requested.
        # Useful when iterating on control/dep translation without
        # rebuilding; both assume their upstream artifacts already exist.
        if commands == ['deb']:
            self.create_deb()
            return
        if commands == ['source']:
            self.create_source_package()
            return

        # Pre-flight: verify host build-deps are installed before we start
        # downloading/extracting. Only relevant when there's actual build
        # work to do, not for standalone packaging/source steps.
        if 'build' in commands:
            self.check_system_build_deps()

        # Hand off the download/extract/configure/build/install sequence to
        # UnixBuilder.run. Our overridden install() turns "install" into a
        # staged buildroot instead of a live-prefix write. Run build +
        # install BEFORE test so the staged destdir exists — see docstring.
        core = [c for c in commands if c in ('build', 'install')]
        if core:
            super().run(core)

        # Test runs separately, against the freshly-staged destdir.
        # super().run(['test']) reconstructs env + build_dir from the
        # filesystem state (see UnixBuilder.run's else branch); our
        # test() override then augments env with destdir paths.
        if 'test' in commands:
            super().run(['test'])

        if 'deb' in commands:
            self.create_deb()

        if 'source' in commands:
            self.create_source_package()


# ---------------------------------------------------------------------------
# Flavor meta-package
# ---------------------------------------------------------------------------

def build_flavor_meta_package(flavor: str) -> Path:
    """Build the flavor meta-package `scls-<flavor>` as a .deb.

    Produces an Architecture: all package whose Depends: pulls in every real
    package in the flavor (plus any extras from flavor.conf). The only payload
    is a registry marker at {prefix}/share/scls/registry/_meta.yaml so
    `scls list` and the install-next resolver both see the meta-package as
    installed once apt pulls it in.

    Parallels rpm_builder.build_flavor_meta_package. We do NOT emit an
    examples meta-package here because deb_builder does not support the
    `subpackages:` recipe section yet; when it does, the examples meta
    follows the same pattern as the RPM path.
    """
    from build_order import get_flavor_package_list, FLAVOR_META

    flavor_config = load_flavor(flavor)
    prefix = Path(flavor_config['prefix'])

    packages = get_flavor_package_list(str(PROJECT_ROOT / 'recipes'), flavor)
    if not packages:
        raise BuildError(f"No packages found for flavor {flavor}")

    # Extras from flavor.conf go first so foundation packages (gcc, binutils)
    # end up at the front of the Depends list, matching rpm_builder.
    for pkg in read_extra_packages(flavor):
        if pkg not in packages:
            packages.insert(0, pkg)

    scls_name = f"scls-{flavor}"
    depends = [f"scls-{flavor}-{pkg}" for pkg in packages]

    # Version: use the environment recipe's version, matching rpm_builder.
    env_recipe = load_recipe('environment')
    version = str(env_recipe.get('version', '1.0'))
    release = '1'
    architecture = 'all'
    description = flavor_config.get(
        'description', f"SCLS {flavor} flavor — complete installation"
    )
    maintainer = flavor_config.get(
        'maintainer', 'Christian Messe <cmesse@lbl.gov>'
    )

    # Stage a dedicated buildroot for the meta-package so it can't clobber a
    # regular per-package destdir that might already exist.
    meta_destdir = PROJECT_ROOT / 'work' / 'build' / f'meta-destdir-{flavor}'
    if meta_destdir.exists():
        shutil.rmtree(meta_destdir)
    destdir_prefix = meta_destdir / str(prefix).lstrip('/')
    registry_dir = destdir_prefix / 'share' / 'scls' / 'registry'
    registry_dir.mkdir(parents=True)

    # Marker file — lets `scls list` and the next-resolver see the meta as
    # installed once apt has pulled it in.
    marker_yaml = (
        f"name: {FLAVOR_META}\n"
        f"version: \"{version}\"\n"
        f"summary: {description}\n"
        f"dependencies: []\n"
    )
    (registry_dir / f"{FLAVOR_META}.yaml").write_text(marker_yaml)

    # DEBIAN/control. Meta-packages are noarch (`Architecture: all`), depend
    # only on other SCLS packages, and carry no Build-Depends (binary deb).
    debian_dir = meta_destdir / 'DEBIAN'
    debian_dir.mkdir(parents=True)
    control_lines = [
        f"Package: {scls_name}",
        f"Version: {version}-{release}",
        "Section: science",
        "Priority: optional",
        f"Architecture: {architecture}",
        f"Maintainer: {maintainer}",
        f"Depends: {', '.join(depends)}",
        f"Description: {description}",
        " This meta-package depends on every package in the SCLS",
        f" {flavor} flavor. Installing it via apt pulls in the complete",
        " scientific computing stack.",
        "",
    ]
    (debian_dir / 'control').write_text('\n'.join(control_lines))

    # Output dir parallels DebBuilder.deb_out_dir (work/pkgs).
    out_dir = PROJECT_ROOT / 'work' / 'pkgs'
    out_dir.mkdir(parents=True, exist_ok=True)
    deb_path = out_dir / f"{scls_name}_{version}-{release}_{architecture}.deb"

    cmd = [
        'dpkg-deb', '--root-owner-group', '--build',
        str(meta_destdir), str(deb_path),
    ]
    run_command(cmd, PROJECT_ROOT, os.environ, f"dpkg-deb --build {scls_name}")
    print(f"Created {deb_path}")

    # Local marker so build_order's install-next resolver can tell the meta
    # has been produced (not the same as being installed).
    marker_dir = PROJECT_ROOT / 'debbuild' / 'registry' / flavor
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{FLAVOR_META}.yaml").write_text(
        f"name: {FLAVOR_META}\nversion: {version}\n"
    )
    return deb_path


def install_flavor_meta_package(flavor: str) -> None:
    """Install the most-recently-built scls-<flavor> meta .deb via apt-get."""
    from build_order import FLAVOR_META  # noqa: F401  (keeps call-site aligned with rpm)
    scls_name = f"scls-{flavor}"
    out_dir = PROJECT_ROOT / 'work' / 'pkgs'
    # Architecture is always 'all' for meta; glob on it explicitly so we
    # don't accidentally pick up a same-named regular package if one ever
    # existed.
    candidates = sorted(
        out_dir.glob(f"{scls_name}_*_all.deb"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not candidates:
        raise BuildError(
            f"No built meta .deb found for {scls_name} in {out_dir}. "
            f"Run `scls build _meta` (or `scls build next` once the stack "
            f"is fully built) first."
        )
    _apt_install_deb(candidates[0], label="apt-get install meta")


def main():
    parser = argparse.ArgumentParser(
        description="Build .deb packages for SCLS on Debian/Ubuntu"
    )
    parser.add_argument('--package', '-p', help="Package name")
    parser.add_argument('--flavor', '-f',
                        help="Flavor (gcc, mkl, debug, ...)")
    parser.add_argument('--install', action='store_true',
                        help="Install the most-recently-built .deb for this package")
    parser.add_argument(
        'commands',
        nargs='*',
        default=[],
        help="Pipeline steps to run, subset of "
             "{build, test, install, deb, source}. "
             "Defaults to 'build test install deb source' when no flags "
             "override it (test is a no-op when the recipe has no test: "
             "section; source produces the 3.0 (quilt) triplet under "
             "work/spkgs/); positional 'install' stages into the destdir "
             "buildroot, --install installs the built .deb",
    )
    args = parser.parse_args()

    if not args.package:
        parser.error("--package/-p is required")
    if not args.flavor:
        parser.error("--flavor/-f is required")
    valid = {'build', 'test', 'install', 'deb', 'source'}
    bad = [c for c in args.commands if c not in valid]
    if bad:
        parser.error(f"invalid command(s): {bad!r}; valid choices are {sorted(valid)}")

    try:
        # Flavor meta-package: no recipe, no source, just a Depends-only .deb
        # that pulls in every real package in the flavor. Mirrors
        # rpm_builder.main's FLAVOR_META special case.
        from build_order import FLAVOR_META
        if args.package == FLAVOR_META:
            if args.install:
                install_flavor_meta_package(args.flavor)
            else:
                build_flavor_meta_package(args.flavor)
            return 0

        builder = DebBuilder(args.package, args.flavor)

        if args.install:
            # --install implies: build the .deb first if it doesn't exist,
            # then install via apt-get. Mirrors rpm_builder --install which
            # installs the last-built RPM. We require a prior build (same as
            # rpm_builder) rather than auto-building.
            builder.install_deb()
        else:
            # No flags: default to the full build/test/install/deb/source
            # pipeline. Mirrors rpm_builder's `rpmbuild -ba` behavior —
            # rpmbuild runs %prep/%build/%check/%install and emits both
            # the binary RPM and the SRPM by default, so our DEB path
            # does the analogous thing: binary .deb + 3.0 (quilt) source
            # package for license compliance.
            commands = args.commands if args.commands else [
                'build', 'test', 'install', 'deb', 'source'
            ]
            builder.run(commands)
    except BuildError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
