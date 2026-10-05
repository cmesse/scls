# Bugs — `extra_packages:` ignored by unix/deb builders; NEVER_SHIP misses subpackages

**Found:** 2026-09-30, while planning the HSL work (the packaged-recipe plan, since removed; see
`devlog/dl20261003_libhsl_private_build.md`). Read-only
finding. Both items touch `python/` or `scripts/`, so fixing them needs Christian's approval and
the review gate in `doc/AI_COLLABORATION_PROTOCOL.md`.

## B1 — `extra_packages:` only works for RPM builds

**Symptom.** A recipe excluded by its own `include_flavors:` / `exclude_flavors:` (e.g.
`include_flavors: []` on `suitesparse` or `zlib`) can be opted in through `extra_packages:` in
`flavor.conf` on RHEL-family hosts, but not on Ubuntu (deb_builder) or macOS / plain Unix
(unix_builder). There the build aborts with `Package <pkg> not built for <flavor>`.

**Cause.**
- `python/rpm_builder.py:383-395` checks `read_extra_packages(flavor)` before raising. If the
  package is listed, it prints a note and builds anyway.
- `python/unix_builder.py:91-92` calls `should_build_package` and raises unconditionally. It has
  no `extra_packages` check.
- `DebBuilder` subclasses `UnixBuilder` (`python/deb_builder.py:253-254`), so it inherits the
  missing check.
- The meta-package builders *do* read `extra_packages` on both paths
  (`rpm_builder.py:2491-2500`, `deb_builder.py:1958-1966`). On a .deb host that is
  inconsistent: the meta-package would Depend on a package the builder refuses to build.

**Docs that claim otherwise.** CLAUDE.md ("`include_flavors: []` … must be opted in via
`extra_packages:`") and `flavor.conf` describe the override as general. On non-RPM hosts it
isn't.

**Fix sketch.** Port the `is_extra` branch from `rpm_builder.py:383-395` into
`unix_builder.py:91-92`, sharing the message text. Better still, move the check into one helper
in `build_common.py` that all three builders call, so it cannot drift again.

**Blast radius.** Behaviour changes only for packages listed in `extra_packages:` on a
non-RPM host. Today those fail; after the fix they build. No spec or .deb output changes for
any other recipe.

- [ ] Confirm on a .deb host: add `zlib` to `extra_packages:`, run `./scls build zlib`, and expect the `not built for` error
- [ ] Approval
- [ ] Implement the shared helper; call it from rpm_builder and unix_builder
- [ ] Re-run the confirm step and expect a successful build with the "not officially supported" note
- [ ] Changelog/devlog entry

## B2 — staging exclusion matches the binary short name only

**Symptom.** `NEVER_SHIP_REASON` in `scripts/stage_to_belfem.sh:170-183` and
`scripts/deb_drop_select.py:52-55,133-135` is keyed on the binary package name with
`scls-<flavor>-` stripped. A subpackage of an excluded recipe has a different short name
(e.g. `scls-<f>-suitesparse-devel` → `suitesparse-devel`), so it misses the table. It also has a
valid SRPM / `.dsc`, so it would be staged.

**Today's exposure.** None known: suitesparse produces no subpackages. This is latent.

**Fix sketch.** Also check the source package name: the `SOURCERPM` tag on RPM, the `.dsc`
`Source:` field on DEB. Exclude the binary when *either* name is in the table.

- [ ] Approval
- [ ] Implement in both scripts
- [ ] Dry-run `stage_to_belfem.sh` against a host with a fake subpackage, or a unit test for `deb_drop_select.py`
