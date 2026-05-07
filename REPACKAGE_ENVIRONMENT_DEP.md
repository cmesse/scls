# Repackage existing RPMs/DEBs to inject the environment dependency

## Why

`scls-<flavor>-environment` owns the `lib -> lib64` symlink under each
flavor's prefix. Until the dependency change shipped in this branch
(`Requires(pre): scls-<flavor>-environment` on every other package /
`Pre-Depends:` on the deb side), dnf or dpkg could schedule environment
last in a transaction. Any other scls-* package then created
`%{prefix}/lib/` as a real directory before environment got a chance to
lay down the symlink, and environment failed with:

```
error: unpacking of archive failed on file /opt/scls/<flavor>/lib;...:
  cpio: File from package already exists as a directory in system
error: scls-<flavor>-environment-...noarch: install failed
```

The dependency change applies to **future builds**. To avoid a full ~1
week stack rebuild, `tools/repackage_add_environment_dep.py` rewrites the
metadata of already-built `.rpm` / `.deb` artifacts in place: payload and
scriptlets are preserved, only the dependency list and Release/Version are
bumped.

This document is the per-VM playbook. Runs on each build host (el10, el9,
amzn2023, and any deb host); the consumer-host instructions at the end
apply to every machine that already has scls-* installed.

---

## Per build host (el10 / el9 / amzn2023)

### 1. Pull the dependency-injection change
```sh
cd /home/mockbuild/scls           # adjust to your checkout
git pull
```

This brings in:
- `python/rpm_builder.py` and `python/deb_builder.py` — auto-inject the env dep on new builds
- `templates/default.spec.j2` and `templates/default.control.j2` — render `Requires(pre):` / `Pre-Depends:` lines
- `tools/repackage_add_environment_dep.py` — the repackager itself

### 2. Install rpmrebuild

`rpmrebuild` lives in EPEL on all RHEL-family distros and is the only
external tool the script needs.

| Distro       | Command |
|--------------|---------|
| RHEL 10 / Rocky 10 / AlmaLinux 10 | `sudo dnf install -y epel-release && sudo dnf install -y rpmrebuild` |
| RHEL 9 / Rocky 9  / AlmaLinux 9   | `sudo dnf install -y epel-release && sudo dnf install -y rpmrebuild` |
| Amazon Linux 2023 | `sudo dnf install -y rpmrebuild` *(EPEL not needed — rpmrebuild is in the default Amazon Linux repos. If `dnf info rpmrebuild` reports "No matching packages", enable EPEL: `sudo dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm`)* |

For deb hosts, `dpkg-deb` is already present; no extra install needed.

### 3. Run the repackager

```sh
# RPM hosts (preferred — patched files have identical names to originals
# so they replace the un-patched RPMs in place when copied to the repo):
python tools/repackage_add_environment_dep.py rpm \
    --input  rpmbuild/RPMS \
    --output patched/RPMS \
    --release-suffix ''

# DEB hosts (analogous):
python tools/repackage_add_environment_dep.py deb \
    --input  work/pkgs \
    --output patched/debs \
    --version-suffix ''
```

If you'd rather keep patched and un-patched copies side-by-side (e.g. for
A/B testing or to roll back without re-extracting from rpmbuild/RPMS),
omit the suffix flag — the script defaults to `.scls2` / `+scls2` so the
patched artifacts get distinct names. With distinct names, dnf treats the
patched RPM as a newer version; with identical names, it's a same-NEVRA
replacement and consumer hosts must run `dnf clean metadata` before the
new metadata is fetched.

Expected runtime: about 10s per RPM (rpmbuild reconstructs the cpio
payload). For ~130 RPMs this is ~20 min. The script is single-threaded.

What you'll see:
```
  OK    scls-mkl-cmake-4.3.2-1.el10.x86_64.rpm -> scls-mkl-cmake-4.3.2-1.el10.scls2.x86_64.rpm
  SKIP  scls-mkl-environment-2026-1.el10.noarch.rpm: this IS the environment package
  SKIP  scls-release-2026-1.el10.noarch.rpm: not a flavored scls-* package
  ...
```

The 3 `scls-<flavor>-environment` RPMs and `scls-release` are correctly
skipped — they don't need the dep, and their metadata is unchanged.

### 4. Verify a sample patched RPM

```sh
# Check both flag types are present (0 = Requires, 512 = Requires(pre)):
rpm -qp --queryformat '[%{REQUIREFLAGS} %{REQUIRENAME}\n]' \
    patched/RPMS/x86_64/scls-mkl-cmake-*.x86_64.rpm | grep environment
# Expect:
#   0   scls-mkl-environment
#   512 scls-mkl-environment

# Confirm the NEVRA matches the original (with --release-suffix '') or
# carries the chosen suffix:
rpm -qp --queryformat '%{NAME}-%{VERSION}-%{RELEASE}\n' \
    patched/RPMS/x86_64/scls-mkl-cmake-*.x86_64.rpm
# With --release-suffix '': scls-mkl-cmake-4.3.2-1.el10
# With default suffix:      scls-mkl-cmake-4.3.2-1.el10.scls2
```

### 5. Publish the patched RPMs

Drop the patched RPMs (and the existing un-patched env RPMs) into the
distro's repo directory, then regenerate metadata:

```sh
# Example layout — adjust to your actual repo path:
REPO=/var/www/scls/el10           # or el9, amzn2023, etc.

cp -v patched/RPMS/noarch/*.rpm   "$REPO/noarch/"
cp -v patched/RPMS/x86_64/*.rpm   "$REPO/x86_64/"
# Existing env RPMs are unchanged — copy them too if not already present:
cp -v rpmbuild/RPMS/noarch/scls-*-environment-*.noarch.rpm "$REPO/noarch/"
cp -v rpmbuild/RPMS/noarch/scls-release-*.noarch.rpm       "$REPO/noarch/"

createrepo_c "$REPO"
# Re-sign the repodata if you sign it:
# gpg --detach-sign --armor "$REPO/repodata/repomd.xml"
```

For deb hosts: regenerate `Packages` / `Packages.gz` via your usual
reprepro / `dpkg-scanpackages` pipeline, then re-sign `Release`/`InRelease`.

---

## Per consumer host (every machine with scls-* installed)

After the patched repo is published, each consumer host needs a clean
reinstall to pick up the new metadata and lay down a correct prefix:

```sh
sudo dnf clean metadata
sudo dnf remove 'scls-*'          # removes everything except scls-release
sudo dnf install scls-<flavor>    # e.g. scls-gcc, scls-mkl, scls-debug
```

The first install transaction will now sequence
`scls-<flavor>-environment` first (because every other package
`Requires(pre)` it), so `%{prefix}/lib -> lib64` is in place before any
other package extracts files into `lib/`. The transaction completes
without the `cpio: File from package already exists as a directory` error.

Debian/Ubuntu equivalent:
```sh
sudo apt-get update
sudo apt-get remove 'scls-*'
sudo apt-get install scls-<flavor>
```

---

## Idempotency

The repackager is safe to re-run. The Requires filter strips any prior
copies of `Requires(pre): scls-<flavor>-environment` and `Requires:
scls-<flavor>-environment` before re-prepending fresh ones, so a re-run
over already-patched RPMs does not stack duplicate Requires.

If you used a non-empty release suffix (e.g. the `.scls2` default), it is
appended each time, so re-running with the same suffix produces
`1.el10.scls2.scls2`. Either pass `--release-suffix ''` (recommended for
in-place replacement) or bump to `--release-suffix .scls3` on subsequent
runs.
