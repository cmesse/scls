#!/usr/bin/env python3
"""
SCLS project validator — checks recipes, flavors, templates, and cross-references
for consistency issues before building.

Usage:
    python python/validate_project.py [--flavor <flavor>] [--verbose]

Without --flavor, validates all flavors. With --flavor, validates only that one.
"""

import os
import sys
import yaml
import argparse
from pathlib import Path
from collections import defaultdict


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def load_yaml(filepath):
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and 'version' in data:
        data['version'] = str(data['version'])
    return data


def load_all_recipes(recipes_dir):
    recipes = {}
    for p in sorted(Path(recipes_dir).glob('*.yaml')):
        try:
            data = load_yaml(p)
            if isinstance(data, dict) and 'name' in data:
                recipes[data['name']] = data
        except Exception as e:
            recipes[p.stem] = {'_error': str(e), 'name': p.stem}
    return recipes


def load_all_flavors(flavors_dir):
    flavors = {}
    for p in sorted(Path(flavors_dir).glob('*.yaml')):
        try:
            data = load_yaml(p)
            if isinstance(data, dict) and 'name' in data:
                flavors[data['name']] = data
        except Exception as e:
            flavors[p.stem] = {'_error': str(e), 'name': p.stem}
    return flavors


# ---------------------------------------------------------------------------
# Flavor resolution (mirrors build_common.get_flavor_names)
# ---------------------------------------------------------------------------

def get_flavor_names(flavor_name, flavors):
    """Return the list of names a flavor matches, including inheritance
    and hyphen-separated components."""
    names = [flavor_name]
    flavor_data = flavors.get(flavor_name, {})
    if 'inherits' in flavor_data:
        names.append(flavor_data['inherits'])
    for part in flavor_name.split('-'):
        if part and part not in names:
            names.append(part)
    return names


def resolve_flavor_key(flavor_names, mapping):
    """Resolve a flavor-specific key from a mapping, trying each name in order."""
    for name in flavor_names:
        if name in mapping:
            return name, mapping[name]
    return None, None


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

class Validator:
    def __init__(self, recipes_dir='recipes', flavors_dir='flavors',
                 patches_dir='patches', templates_dir='templates',
                 files_dir='files'):
        self.recipes_dir = Path(recipes_dir)
        self.flavors_dir = Path(flavors_dir)
        self.patches_dir = Path(patches_dir)
        self.templates_dir = Path(templates_dir)
        self.files_dir = Path(files_dir)

        self.recipes = load_all_recipes(recipes_dir)
        self.flavors = load_all_flavors(flavors_dir)
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    # --- Recipe structure ---

    def check_recipe_structure(self):
        """Validate required fields and types in each recipe."""

        for name, recipe in self.recipes.items():
            if '_error' in recipe:
                self.error(f"recipe/{name}: failed to parse YAML: {recipe['_error']}")
                continue

            # name is always required
            if 'name' not in recipe:
                self.error(f"recipe/{name}: missing required field 'name'")

            # version can be top-level or inside a platform section (e.g. linux:, macos:)
            has_version = 'version' in recipe
            for plat in ('linux', 'macos'):
                plat_section = recipe.get(plat, {})
                if isinstance(plat_section, dict) and 'version' in plat_section:
                    has_version = True
            if not has_version:
                self.error(f"recipe/{name}: no version (not top-level or platform-specific)")

            # summary or description should be present
            if 'summary' not in recipe and 'description' not in recipe:
                self.warn(f"recipe/{name}: no 'summary' or 'description'")

            # Source can be top-level or platform-specific
            source = recipe.get('source', {})
            source_type = source.get('type', '')
            has_source = 'url' in source
            for plat in ('linux', 'macos'):
                plat_section = recipe.get(plat, {})
                if isinstance(plat_section, dict) and 'source' in plat_section:
                    plat_source = plat_section['source']
                    if isinstance(plat_source, dict) and 'url' in plat_source:
                        has_source = True
            if source_type != 'generated' and not has_source:
                if name != 'environment':
                    self.error(f"recipe/{name}: no source.url found "
                               f"(not top-level or platform-specific)")

            # Configure type validation
            configure = recipe.get('configure', {})
            ctype = configure.get('type', 'autotools')
            valid_types = ('autotools', 'cmake', 'custom', 'none', 'custom_makefile')
            if ctype not in valid_types:
                self.error(f"recipe/{name}: unknown configure.type '{ctype}' "
                           f"(valid: {', '.join(valid_types)})")

            # custom_makefile requires template field
            if ctype == 'custom_makefile' and 'template' not in configure:
                self.error(f"recipe/{name}: configure.type 'custom_makefile' "
                           f"requires a 'template' field")

            # Check that referenced template exists
            if ctype == 'custom_makefile' and 'template' in configure:
                tmpl_path = self.templates_dir / configure['template']
                if not tmpl_path.exists():
                    self.error(f"recipe/{name}: template '{configure['template']}' "
                               f"not found at {tmpl_path}")

            # test.sources validation
            test_sources = recipe.get('test', {}).get('sources', [])
            for i, tsrc in enumerate(test_sources):
                if not isinstance(tsrc, dict) or 'url' not in tsrc:
                    self.error(f"recipe/{name}: test.sources[{i}] must be a dict with 'url'")

    # --- Flavor structure ---

    def check_flavor_structure(self):
        """Validate required fields in each flavor."""
        required_fields = ['name', 'platform', 'prefix']

        for name, flavor in self.flavors.items():
            if '_error' in flavor:
                self.error(f"flavor/{name}: failed to parse YAML: {flavor['_error']}")
                continue

            for field in required_fields:
                if field not in flavor:
                    self.error(f"flavor/{name}: missing required field '{field}'")

            # Check inheritance target exists
            if 'inherits' in flavor:
                parent = flavor['inherits']
                if parent not in self.flavors:
                    self.error(f"flavor/{name}: inherits from '{parent}' "
                               f"but no flavors/{parent}.yaml found")

            # Platform validation
            platform = flavor.get('platform', '')
            if platform not in ('linux', 'macos'):
                self.error(f"flavor/{name}: unknown platform '{platform}'")

            # Compilers should be present
            if 'compilers' not in flavor and 'inherits' not in flavor:
                self.warn(f"flavor/{name}: no 'compilers' section and no inheritance")

    # --- Cross-reference: flavor selectors in recipes ---

    def check_flavor_selectors(self):
        """Check that flavor selectors used in recipes are resolvable."""
        # Collect all known flavor match names
        all_match_names = set()
        for fname in self.flavors:
            for n in get_flavor_names(fname, self.flavors):
                all_match_names.add(n)

        for name, recipe in self.recipes.items():
            if '_error' in recipe:
                continue

            # Check include_flavors: allowlist
            for f in recipe.get('include_flavors', []):
                if f not in all_match_names:
                    self.warn(f"recipe/{name}: include_flavors entry '{f}' does not match "
                              f"any known flavor or component")

            # Check exclude_flavors
            for f in recipe.get('exclude_flavors', []):
                if f not in all_match_names:
                    self.warn(f"recipe/{name}: exclude_flavors entry '{f}' does not "
                              f"match any known flavor or component")

            # Check flavor-keyed dicts in requires, flavor_args, etc.
            self._check_flavor_dict_keys(name, recipe.get('requires', {}), 'requires')

            configure = recipe.get('configure', {})
            self._check_flavor_dict_keys(name, configure.get('flavor_args', {}), 'configure.flavor_args')
            self._check_flavor_dict_keys(name, configure.get('flavor_pre', {}), 'configure.flavor_pre')
            self._check_flavor_dict_keys(name, configure.get('flavor_post', {}), 'configure.flavor_post')
            self._check_flavor_dict_keys(name, configure.get('lp64_flavor_args', {}), 'configure.lp64_flavor_args')
            self._check_flavor_dict_keys(name, configure.get('ilp64_flavor_args', {}), 'configure.ilp64_flavor_args')
            # Note: configure.env keys are environment variable names, not flavor selectors

            # Build section flavor keys
            build = recipe.get('build', {})
            self._check_flavor_dict_keys(name, build.get('flavor_args', {}), 'build.flavor_args')

            # Install section flavor keys
            install = recipe.get('install', {})
            self._check_flavor_dict_keys(name, install.get('flavor_post', {}), 'install.flavor_post')

            # Subpackage flavor refs
            subpackages = recipe.get('subpackages', [])
            if isinstance(subpackages, list):
                for subpkg in subpackages:
                    if isinstance(subpkg, dict):
                        for f in subpkg.get('include_flavors', []):
                            if f not in all_match_names:
                                self.warn(f"recipe/{name}: subpackage "
                                          f"'{subpkg.get('name', '?')}' "
                                          f"include_flavors entry '{f}' unknown")
            elif isinstance(subpackages, dict):
                for sname, subpkg in subpackages.items():
                    if isinstance(subpkg, dict):
                        for f in subpkg.get('include_flavors', []):
                            if f not in all_match_names:
                                self.warn(f"recipe/{name}: subpackage '{sname}' "
                                          f"include_flavors entry '{f}' unknown")

    def _check_flavor_dict_keys(self, recipe_name, mapping, field_name):
        """Check that keys in a flavor-keyed dict are resolvable."""
        if not isinstance(mapping, dict):
            return

        all_match_names = set()
        for fname in self.flavors:
            for n in get_flavor_names(fname, self.flavors):
                all_match_names.add(n)
        # 'all' is a special key
        all_match_names.add('all')

        for key in mapping:
            if key not in all_match_names:
                self.warn(f"recipe/{recipe_name}: {field_name} key '{key}' does not "
                          f"match any known flavor or component")

    # --- Cross-reference: dependencies ---

    def check_dependencies(self, flavor_name=None):
        """Check that recipe dependencies refer to existing recipes."""
        flavors_to_check = [flavor_name] if flavor_name else list(self.flavors.keys())

        for fname in flavors_to_check:
            if fname not in self.flavors:
                self.error(f"Unknown flavor '{fname}'")
                continue

            fnames = get_flavor_names(fname, self.flavors)

            for rname, recipe in self.recipes.items():
                if '_error' in recipe:
                    continue

                # Check if package builds for this flavor
                if not self._builds_for_flavor(recipe, fnames):
                    continue

                # Gather dependencies
                requires = recipe.get('requires', {})
                deps = []
                if isinstance(requires, list):
                    deps = requires
                elif isinstance(requires, dict):
                    if 'all' in requires:
                        deps.extend(requires['all'])
                    _, flavor_deps = resolve_flavor_key(fnames, requires)
                    if flavor_deps:
                        deps.extend(flavor_deps)

                # Verify each dependency exists and builds for this flavor
                for dep in deps:
                    if dep not in self.recipes and dep not in self._all_subpackage_names():
                        self.error(f"recipe/{rname} [{fname}]: dependency '{dep}' "
                                   f"has no recipe or subpackage")
                    elif dep in self.recipes:
                        dep_recipe = self.recipes[dep]
                        if '_error' not in dep_recipe and not self._builds_for_flavor(dep_recipe, fnames):
                            self.warn(f"recipe/{rname} [{fname}]: dependency '{dep}' "
                                      f"is not built for flavor '{fname}'")

    def _all_subpackage_names(self):
        """Collect all subpackage names across all recipes."""
        if hasattr(self, '_subpkg_cache'):
            return self._subpkg_cache
        names = set()
        for recipe in self.recipes.values():
            subpackages = recipe.get('subpackages', [])
            if isinstance(subpackages, list):
                for s in subpackages:
                    if isinstance(s, dict) and 'name' in s:
                        names.add(s['name'])
            elif isinstance(subpackages, dict):
                names.update(subpackages.keys())
        self._subpkg_cache = names
        return names

    def _builds_for_flavor(self, recipe, flavor_names):
        """Check if a recipe builds for the given flavor names."""
        # Check exclusion
        excludes = recipe.get('exclude_flavors', [])
        if any(n in excludes for n in flavor_names):
            return False
        # Check inclusion
        includes = recipe.get('include_flavors')
        if includes is None:
            return True
        return any(n in includes for n in flavor_names)

    # --- Patches ---

    def check_patches(self):
        """Verify that referenced patches exist on disk."""
        for name, recipe in self.recipes.items():
            if '_error' in recipe:
                continue

            patches = recipe.get('patches', {})
            if not patches:
                continue

            # Collect all patch entries regardless of format
            patch_entries = []
            if isinstance(patches, dict):
                # Dict format: {all: [...], gcc: [...], ...}
                for key, patch_list in patches.items():
                    if isinstance(patch_list, list):
                        patch_entries.extend(patch_list)
            elif isinstance(patches, list):
                # List format: [file1, file2, ...]
                patch_entries = patches

            for patch_entry in patch_entries:
                if isinstance(patch_entry, str):
                    patch_file = patch_entry
                elif isinstance(patch_entry, dict) and 'file' in patch_entry:
                    patch_file = patch_entry['file']
                else:
                    continue

                patch_path = self.patches_dir / name / patch_file
                if not patch_path.exists():
                    self.error(f"recipe/{name}: patch '{patch_file}' not found "
                               f"at {patch_path}")

    # --- Subpackage consistency ---

    def check_subpackages(self):
        """Check subpackage definitions for consistency."""
        for name, recipe in self.recipes.items():
            if '_error' in recipe:
                continue

            subpackages = recipe.get('subpackages', [])
            if not subpackages:
                continue

            if isinstance(subpackages, list):
                # List format (e.g., petsc)
                subpkg_names = set()
                for subpkg in subpackages:
                    if not isinstance(subpkg, dict):
                        self.error(f"recipe/{name}: subpackage entry is not a dict")
                        continue
                    sname = subpkg.get('name', '')
                    if not sname:
                        self.error(f"recipe/{name}: subpackage missing 'name'")
                        continue
                    if sname in subpkg_names:
                        self.error(f"recipe/{name}: duplicate subpackage name '{sname}'")
                    subpkg_names.add(sname)
                    if 'files' not in subpkg and 'summary' not in subpkg:
                        self.warn(f"recipe/{name}: subpackage '{sname}' has no "
                                  f"'files' or 'summary'")

            elif isinstance(subpackages, dict):
                # Dict format (e.g., lapack)
                for sname, subpkg in subpackages.items():
                    if not isinstance(subpkg, dict):
                        continue
                    if 'files' not in subpkg:
                        self.warn(f"recipe/{name}: subpackage '{sname}' has no 'files'")

    # --- Tracked file lists ---

    def check_file_lists(self):
        """Warn about packages that don't use rpm_files_auto and have no tracked file list."""
        for name, recipe in self.recipes.items():
            if '_error' in recipe:
                continue

            # Generated packages don't need file lists
            if recipe.get('source', {}).get('type') == 'generated':
                continue

            # Auto-file-list packages don't need tracked files
            if recipe.get('rpm_files_auto', False):
                continue

            file_list = self.files_dir / f"{name}.txt"
            if not file_list.exists():
                self.warn(f"recipe/{name}: no tracked file list at {file_list} "
                          f"and rpm_files_auto is not set")

    # --- Build order sanity ---

    def check_build_order(self, flavor_name=None):
        """Check that the build order can be computed without cycles."""
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            from build_order import get_ordered_package_list
        except ImportError:
            self.warn("Could not import build_order module, skipping build order check")
            return

        flavors_to_check = [flavor_name] if flavor_name else list(self.flavors.keys())

        for fname in flavors_to_check:
            if fname not in self.flavors:
                continue
            import io
            old_stderr = sys.stderr
            try:
                # Suppress stderr from build_order
                sys.stderr = io.StringIO()
                ordered = get_ordered_package_list(str(self.recipes_dir), fname)

                if not ordered:
                    self.warn(f"flavor/{fname}: build order is empty")
                elif len(ordered) < 3:
                    self.warn(f"flavor/{fname}: build order has only "
                              f"{len(ordered)} packages")
            except Exception as e:
                self.error(f"flavor/{fname}: build order computation failed: {e}")
            finally:
                sys.stderr = old_stderr

    # --- Run all checks ---

    def validate(self, flavor_name=None, verbose=False):
        """Run all validation checks."""
        self.check_recipe_structure()
        self.check_flavor_structure()
        self.check_flavor_selectors()
        self.check_patches()
        self.check_subpackages()
        self.check_file_lists()
        self.check_dependencies(flavor_name)
        self.check_build_order(flavor_name)

        return self.errors, self.warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Validate SCLS recipes, flavors, and cross-references')
    parser.add_argument('--flavor', '-f', help='Validate only this flavor')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show warnings in addition to errors')
    parser.add_argument('--recipes', default='recipes',
                        help='Path to recipes directory')
    parser.add_argument('--flavors', default='flavors',
                        help='Path to flavors directory')
    args = parser.parse_args()

    v = Validator(recipes_dir=args.recipes, flavors_dir=args.flavors)
    errors, warnings = v.validate(flavor_name=args.flavor, verbose=args.verbose)

    # Print results
    if warnings and args.verbose:
        print(f"\n--- Warnings ({len(warnings)}) ---")
        for w in warnings:
            print(f"  W: {w}")

    if errors:
        print(f"\n--- Errors ({len(errors)}) ---")
        for e in errors:
            print(f"  E: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Recipes: {len(v.recipes)}  Flavors: {len(v.flavors)}")
    print(f"Errors:  {len(errors)}  Warnings: {len(warnings)}")
    if not errors:
        print("Validation passed.")
    else:
        print("Validation FAILED.")
    print(f"{'='*60}")

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
