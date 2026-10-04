#!/usr/bin/env python3
"""Select one flavor's .debs and source packages for a belfem drop.

Called by scripts/stage_to_belfem.sh for the Ubuntu columns; the RPM columns do the
same job in shell. Emits one tab-separated record per line on stdout:

    bin      <path to .deb>          <name_version_arch>
    src      <path to .dsc>          <name_version_source>
    srcfile  <path to .orig/.debian> -
    excluded <line for MANIFEST excluded:>
    already  <line for MANIFEST already_published:>
    nosrc    <line for MANIFEST no_source:>
    replace  <line for MANIFEST replace_published:>

Optional arguments 7 and 8 name a file of binary package names and a reason. A
listed package whose published filename exists with DIFFERENT bytes ships as a
same-version replacement instead of going under already_published:, together
with its complete source package if that differs from the published one too.
Replacing a published version needs Christian's explicit override of contract
v1.2 (first granted 2026-09-29 for the --no-as-needed relink).

The published state comes from the repo's signed indexes (Packages.gz, Sources.gz),
which the caller has already verified against InRelease. Membership is decided by
pool filename: reprepro keys its pool on it, so a file whose name is already
published can never be shipped again, whatever its bytes (contract v1.2).

Binaries map to sources through the .dsc Binary: field, never by name. Our .debs
carry no Source: field, and subpackages (blas/cblas/lapacke from lapack, the
*-examples from their parents) share one source package.
"""
import gzip
import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

# Same rule as NEVER_SHIP_REASON in stage_to_belfem.sh: licence first, mechanism second.
# The ONLY packages that may ship without a source package: SCLS's own generated
# packaging, with no upstream code (Christian, 2026-09-28; doc/LICENSE_POLICY.md).
# The list is closed. Anything else without a .dsc stays excluded, and the
# publishing host's verifier rejects a no_source: entry outside this list.
NO_SOURCE_REASON = ('SCLS-generated packaging, no upstream source; '
                    'source in the SCLS repository')


def keyring_release():
    """This host's scls-archive-keyring release, from deb_builder's table."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'python'))
    from deb_builder import KEYRING_RELEASE_BY_CODENAME, _apt_repo_for_host
    return KEYRING_RELEASE_BY_CODENAME[_apt_repo_for_host()[1]]


def no_source_names(flavor):
    return {'scls-archive-keyring', f'scls-{flavor}', f'scls-{flavor}-environment'}


NEVER_SHIP_REASON = {
    'suitesparse': 'licence — GPL-2 linkable, not shipped as a binary (doc/LICENSE_POLICY.md); '
                   'recipe carries include_flavors: [] so it is never built by default',
}


def stanzas(text):
    """Split a deb822 file into dicts; continuation lines are kept as a list."""
    out, cur, key = [], {}, None
    for line in text.splitlines():
        if not line.strip():
            if cur:
                out.append(cur)
            cur, key = {}, None
        elif line[0] in ' \t' and key:
            cur.setdefault(key + '+', []).append(line.strip())
        elif ':' in line:
            key, _, val = line.partition(':')
            cur[key] = val.strip()
    if cur:
        out.append(cur)
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def checksums(st):
    """Checksums-Sha256 of a .dsc or Sources stanza -> {filename: sha256}."""
    return {p.split()[2]: p.split()[0] for p in st.get('Checksums-Sha256+', [])}


def main():
    repo, flavor, pkgs, spkgs, packages_gz, sources_gz = sys.argv[1:7]
    repo, pkgs, spkgs = Path(repo), Path(pkgs), Path(spkgs)
    replace, replace_reason = set(), ''
    if len(sys.argv) > 8:
        replace = {l.split('#')[0].strip() for l in open(sys.argv[7])} - {''}
        replace_reason = sys.argv[8]

    pub_deb = {}                       # pool filename -> sha256
    for st in stanzas(gzip.open(packages_gz, 'rt').read()):
        pub_deb[Path(st['Filename']).name] = st['SHA256']
    pub_src = set()                    # (source, version)
    pub_srcfile = {}                   # pool filename -> sha256
    for st in stanzas(gzip.open(sources_gz, 'rt').read()):
        pub_src.add((st['Package'], st['Version']))
        pub_srcfile.update(checksums(st))

    by_binary = {}                     # (binary, version) -> (dsc path, stanza)
    for dsc in sorted(spkgs.glob('*.dsc')):
        # Older .dsc files are clearsigned; skip the armor header, stop at the signature.
        text = dsc.read_text().split('-----BEGIN PGP SIGNATURE-----')[0]
        st = next((x for x in stanzas(text) if 'Source' in x and 'Version' in x), None)
        if st is None:
            continue
        for b in st.get('Binary', '').split(','):
            by_binary[(b.strip(), st['Version'])] = (dsc, st)

    installed = subprocess.run(
        ['dpkg-query', '-W', '-f', '${Package} ${Version} ${Architecture}\n',
         f'scls-{flavor}', f'scls-{flavor}-*', 'scls-archive-keyring'],
        capture_output=True, text=True).stdout.split('\n')

    shipped_src = set()
    for line in sorted(filter(None, installed)):
        name, ver, arch = line.split()
        nva = f'{name}_{ver}_{arch}'
        # The keyring belongs to no flavor: it rides in whichever drop reaches a
        # repo first and is already_published in every later one.
        generated = name in no_source_names(flavor)
        short = None if name in ('scls-archive-keyring', f'scls-{flavor}') \
            else name[len(f'scls-{flavor}-'):]
        recipe = short.replace('-', '_') if short else None

        # Licence exclusion first: it holds whether or not an artifact exists.
        if recipe in NEVER_SHIP_REASON:
            print(f'excluded\t{nva}  reason: {NEVER_SHIP_REASON[recipe]}')
            continue

        deb = pkgs / f'{nva}.deb'
        if not deb.is_file():
            print(f'excluded\t{nva}  reason: installed but no .deb in {pkgs.name}/')
            continue

        # Generated packages have no recipe of their own, but their versions still
        # follow one: environment is version-release of recipes/environment.yaml,
        # the metas are its version with its meta_release (default 1), and the
        # keyring its version with deb_builder's per-codename release.
        # Checked here because they skip the source-package path.
        if generated:
            env = yaml.safe_load((repo / 'recipes' / 'environment.yaml').read_text())
            if name == f'scls-{flavor}-environment':
                want = f"{env['version']}-{env.get('release', 1)}"
            elif name == 'scls-archive-keyring':
                want = f"{env['version']}-{keyring_release()}"
            else:
                want = f"{env['version']}-{env.get('meta_release', 1)}"
            if want != ver:
                print(f'excluded\t{nva}  reason: installed {ver} does not match expected {want}')
                continue

        local = sha256(deb)
        replacing = (deb.name in pub_deb and name in replace and not generated
                     and pub_deb[deb.name] != local)
        if deb.name in pub_deb and not replacing:
            note = '' if pub_deb[deb.name] == local else \
                '  (local rebuild differs; published copy stands, contract v1.2)'
            print(f'already\t{nva}  SHA256={local}{note}')
            hit = by_binary.get((name, ver))
            if hit and (hit[1]['Source'], ver) in pub_src and (hit[1]['Source'], ver) not in shipped_src:
                shipped_src.add((hit[1]['Source'], ver))
                print(f'already\t{hit[1]["Source"]}_{ver}_source  SHA256={sha256(hit[0])}')
            continue

        if generated:
            print(f'bin\t{deb}\t{nva}')
            print(f'nosrc\t{nva}  reason: {NO_SOURCE_REASON}')
            continue

        hit = by_binary.get((name, ver))
        if not hit:
            print(f'excluded\t{nva}  reason: no source package in {spkgs.name}/ lists it at {ver} '
                  f'(source availability, doc/LICENSE_POLICY.md)')
            continue
        dsc, st = hit

        # The recipe is the source package's, not the binary's: blas comes from lapack.
        src_short = st['Source'][len(f'scls-{flavor}-'):]
        rfile = repo / 'recipes' / f"{src_short.replace('-', '_')}.yaml"
        if rfile.is_file():
            r = yaml.safe_load(rfile.read_text())
            want = f"{r['version']}-{r.get('release', 1)}"
            if want != ver:
                print(f'excluded\t{nva}  reason: built {ver} does not match recipe {want}')
                continue

        srcid = (st['Source'], st['Version'])
        nvs = f'{st["Source"]}_{st["Version"]}_source'
        # A replaced binary's source is replaced too only if its bytes changed; the
        # publishing host drops the old pool files first, so it must ship complete.
        src_replacing = (replacing and srcid in pub_src
                         and pub_srcfile.get(dsc.name) != sha256(dsc))
        if replacing:
            print(f'replace\t{nva}  reason: {replace_reason}')
        if srcid in pub_src and not src_replacing:
            if srcid not in shipped_src:
                shipped_src.add(srcid)
                print(f'already\t{nvs}  SHA256={sha256(dsc)}')
            print(f'bin\t{deb}\t{nva}')
            continue

        files = checksums(st)
        bad = [f for f, h in files.items()
               if not (spkgs / f).is_file() or sha256(spkgs / f) != h]
        # A pool filename that is already published with other bytes would be refused
        # by reprepro; an identical one is harmless and ships with its .dsc.
        clash = [] if src_replacing else \
            [f for f, h in files.items() if f in pub_srcfile and pub_srcfile[f] != h]
        if bad or clash:
            why = (f'source file missing or fails .dsc checksum: {", ".join(bad)}' if bad else
                   f'source file already published with other bytes: {", ".join(clash)}')
            print(f'excluded\t{nva}  reason: {why}')
            continue

        print(f'bin\t{deb}\t{nva}')
        if srcid not in shipped_src:
            shipped_src.add(srcid)
            if src_replacing:
                print(f'replace\t{nvs}  reason: {replace_reason}')
            print(f'src\t{dsc}\t{nvs}')
            for f in sorted(files):
                print(f'srcfile\t{spkgs / f}\t-')


if __name__ == '__main__':
    main()
