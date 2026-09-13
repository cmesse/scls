# 2026-09-13 — Host toolchain as a runtime dependency of `environment`

## Purpose

On Ubuntu the installed flavor packages did not pull in `build-essential`,
`gfortran` or `doxygen`. Record why, what the same gap looks like on the RPM
side, and how it was closed with a single environment rebuild per flavor.

## Finding

Neither builder emitted any runtime toolchain dependency. `get_rpm_requires`
injected `gcc`/`gcc-c++`/`gcc-gfortran` into `BuildRequires` only, and the deb
builder mirrored that into `Build-Depends`, which a `dpkg-deb`-built binary
never sees. The built `scls-gcc-environment_2026-1_amd64.deb` had no
`Depends:` line at all. With `AutoReqProv: no` as policy, even `libgfortran`
and `libstdc++` were uncaptured. RHEL hosts worked only because the build
hosts already carry the toolchain.

The generated-package spec path in `rpm_builder.generate_generated_spec`
also hard-coded `Release: 1`, ignored `rpm_requires:`, and did not set
`AutoReqProv: no`.

## Change

- `recipes/environment.yaml`: `release: 2`; per-flavor `rpm_requires:`
  (`gcc gcc-c++ gcc-gfortran glibc-devel` for gcc/mkl/debug/gcc-mkl-cuda,
  `make` for all, empty for lbl and intel); `rpm_recommends: [doxygen]`.
- `packaging/system_packages.yaml`: `glibc-devel -> libc6-dev`,
  `doxygen -> doxygen`. Debian's `gcc` only Recommends `libc6-dev`, so it
  must be listed explicitly to reach the build-essential set.
- New `rpm_recommends:` recipe field rendered as `Recommends:` by both
  builders (`get_rpm_recommends`, `get_deb_recommends`), in the spec
  template, the control template, the generated spec, and the deb source
  `debian/control`. Weak because doxygen lives in CRB on RHEL 9/10, which
  is disabled on a fresh host; a hard `Requires` would fail
  `dnf install scls-<flavor>` there.
- Generated spec now honours `release:`, emits `Requires:`/`Recommends:`
  and sets `AutoReqProv: no`.

## Why environment

Every other package carries `Requires(pre)`/`Pre-Depends` on
`scls-<flavor>-environment`, so it is the one package whose dependencies
reach every consumer. Only environment needs rebuilding, once per flavor.

## Gates that ran

- `rpm_builder --spec-only` for environment on gcc, mkl, lbl, intel: Release
  2, expected Requires/Recommends lines, `AutoReqProv: no`.
- `rpm_builder --spec-only` for cmake on gcc: regular template path
  unchanged apart from the empty Recommends block.
- `deb_builder ... build install deb` for environment on gcc on the Ubuntu
  dev host: `Depends: gcc, g++, gfortran, libc6-dev, make`,
  `Recommends: doxygen`, same 29-entry payload as the -1 build.
- `_render_source_control` for environment/gcc: Recommends line present.
- Not run: an actual `rpmbuild` (no RHEL host here) and a `dnf`/`apt`
  install of the new package. Pending the Linux build hosts.

## Open

- RHEL 8 with `gcc_toolset:` would need `gcc-toolset-N-*` names instead;
  the wrapper exports the toolset so `get_rpm_requires` could rewrite them.
  Not done; documented build hosts are el9, el10, amzn2023.
- `intel` flavor: oneAPI compilers remain a documented host prerequisite.
