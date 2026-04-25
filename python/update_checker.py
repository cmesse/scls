#!/usr/bin/env python3
"""
SCLS Package Version Update Checker

Checks upstream sources for newer versions of packages in the SCLS stack.
Supports GitHub releases/tags, GNU FTP mirrors, GitLab, and HTML scraping.

Usage:
    python python/update_checker.py all
    python python/update_checker.py cmake
    python python/update_checker.py all --json
    python python/update_checker.py all --verify-downloads
"""

import os
import re
import sys
import json
import yaml
import argparse
import ssl
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UpdateCheckError(Exception):
    """Raised when an update check fails for a specific package."""
    pass


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

# Status constants
UP_TO_DATE = "up_to_date"
UPDATE_AVAILABLE = "update_available"
UPDATE_URL_FAILED = "update_available_but_url_failed"
UNDETERMINED = "undetermined"
SKIP = "skip"
ERROR = "error"


class UpdateResult:
    """Result of checking one package for updates."""

    def __init__(self, name: str, current_version: str,
                 latest_version: Optional[str] = None,
                 status: str = UNDETERMINED,
                 source_type: str = "",
                 download_url: Optional[str] = None,
                 download_ok: Optional[bool] = None,
                 reason: Optional[str] = None,
                 blocked_version: Optional[str] = None):
        self.name = name
        self.current_version = current_version
        self.latest_version = latest_version
        self.status = status
        self.source_type = source_type
        self.download_url = download_url
        self.download_ok = download_ok
        self.reason = reason
        # A higher-major release that exists upstream but is held back by
        # the recipe's update.max_major pin. None when no pin is active or
        # no higher major has been released yet.
        self.blocked_version = blocked_version

    def to_dict(self) -> Dict:
        d = {
            "name": self.name,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "status": self.status,
            "source_type": self.source_type,
        }
        if self.download_url:
            d["download_url"] = self.download_url
        if self.download_ok is not None:
            d["download_ok"] = self.download_ok
        if self.reason:
            d["reason"] = self.reason
        if self.blocked_version:
            d["blocked_version"] = self.blocked_version
        return d


# ---------------------------------------------------------------------------
# YAML loading (raw — preserves %{version} placeholders)
# ---------------------------------------------------------------------------

def load_recipe_raw(package_name: str,
                    recipes_dir: Path = Path("recipes")) -> Dict:
    """Load a recipe YAML without substituting %{version} in URLs."""
    recipe_path = recipes_dir / f"{package_name}.yaml"
    if not recipe_path.exists():
        raise UpdateCheckError(f"Recipe not found: {recipe_path}")
    with open(recipe_path, 'r') as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and 'version' in data:
        data['version'] = str(data['version'])
    # Handle platform-specific versions — prefer linux section when present
    # (mirrors the build system's per-platform merge). The Linux version is
    # treated as the canonical one for update checking.
    if isinstance(data, dict):
        if 'linux' in data and isinstance(data['linux'], dict):
            if 'version' in data['linux']:
                data['version'] = str(data['linux']['version'])
            if 'source' in data['linux']:
                data['source'] = data['linux']['source']
    return data


def load_all_recipe_names(recipes_dir: Path = Path("recipes")) -> List[str]:
    """Return sorted list of all recipe names."""
    names = []
    for p in sorted(recipes_dir.glob('*.yaml')):
        names.append(p.stem)
    return names


# ---------------------------------------------------------------------------
# Version parsing and comparison
# ---------------------------------------------------------------------------

def parse_version(version_str: str) -> Tuple:
    """Parse a version string into a tuple for comparison.

    Handles: 3.24.5, 2025.05.28, 4.9, 0.29.2, 1.14.6
    Splits on dots and converts numeric parts to ints.
    Each element is wrapped as (type_flag, value) so that ints and strings
    are always comparable: numeric parts sort after non-numeric.
    """
    parts = []
    for part in re.split(r'[._-]', version_str):
        if not part:
            continue
        try:
            parts.append((0, int(part)))
        except ValueError:
            parts.append((1, part))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Return True if latest version is newer than current."""
    return parse_version(latest) > parse_version(current)


def is_prerelease(tag_name: str) -> bool:
    """Check if a tag looks like a pre-release or non-standard release."""
    lower = tag_name.lower()
    return bool(re.search(
        r'(alpha|beta|rc\d|dev|pre|snapshot|nightly|canary|branch|amzn|'
        r'ubuntu|debian|fedora|suse)',
        lower))


def major_of(version: str) -> Optional[int]:
    """Return the integer major version (first numeric component), or None.

    Used by max_major filtering — recipes can pin to their current major to
    avoid being prompted to take an API-breaking upstream bump.
    """
    parts = parse_version(version)
    if not parts:
        return None
    flag, val = parts[0]
    return val if flag == 0 else None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str, headers: Optional[Dict[str, str]] = None,
              timeout: int = 30) -> Tuple[str, Dict[str, str]]:
    """Fetch URL content. Returns (body_text, response_headers).

    Uses curl as the primary method (handles SSL certificates reliably
    across platforms), with urllib as fallback.
    """
    # Build curl command
    cmd = ['curl', '-sL', '--max-time', str(timeout)]
    cmd += ['-D', '-']  # dump headers to stdout
    cmd += ['-H', 'User-Agent: SCLS-Update-Checker/1.0']
    if headers:
        for k, v in headers.items():
            cmd += ['-H', f'{k}: {v}']
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True,
                                timeout=timeout + 5)
        if result.returncode != 0:
            raise UpdateCheckError(
                f"curl failed for {url}: "
                f"{result.stderr.decode('utf-8', errors='replace').strip()}")
        # Split headers and body (separated by blank line after last header block)
        output = result.stdout.decode('utf-8', errors='replace')
        # curl -D - puts headers before body, separated by \r\n\r\n
        # With redirects (-L), there may be multiple header blocks
        parts = re.split(r'\r?\n\r?\n', output)
        if len(parts) >= 2:
            # Last header block is the final response headers
            # Find where headers end — look for the last HTTP/ status line
            body_start = 0
            for i, part in enumerate(parts):
                if part.startswith('HTTP/'):
                    body_start = i + 1
                else:
                    break
            resp_headers_text = parts[body_start - 1] if body_start > 0 \
                else parts[0]
            body = '\n'.join(parts[body_start:]) if body_start < len(parts) \
                else ''
        else:
            resp_headers_text = ''
            body = output

        # Parse response headers
        resp_headers = {}
        for line in resp_headers_text.splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                resp_headers[k.strip().lower()] = v.strip()

        # Check for HTTP errors in the header
        status_match = re.search(r'HTTP/[\d.]+ (\d+)', resp_headers_text)
        if status_match:
            status = int(status_match.group(1))
            if status >= 400:
                raise UpdateCheckError(
                    f"HTTP {status} fetching {url}")

        return body, resp_headers
    except subprocess.TimeoutExpired:
        raise UpdateCheckError(f"Timeout fetching {url}")
    except FileNotFoundError:
        # curl not available, fall back to urllib
        return _fetch_url_urllib(url, headers, timeout)


def _fetch_url_urllib(url: str, headers: Optional[Dict[str, str]] = None,
                      timeout: int = 30) -> Tuple[str, Dict[str, str]]:
    """Fallback URL fetcher using urllib."""
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'SCLS-Update-Checker/1.0')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        # Try default SSL context first, fall back to unverified
        try:
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except ssl.SSLCertVerificationError:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        body = resp.read().decode('utf-8', errors='replace')
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        return body, resp_headers
    except urllib.error.HTTPError as e:
        raise UpdateCheckError(
            f"HTTP {e.code} fetching {url}: {e.reason}")
    except urllib.error.URLError as e:
        raise UpdateCheckError(f"URL error fetching {url}: {e.reason}")
    except Exception as e:
        raise UpdateCheckError(f"Error fetching {url}: {e}")


def head_url(url: str, timeout: int = 15) -> int:
    """Check if a URL is reachable, return HTTP status code.

    Tries HEAD first for speed. If HEAD fails or returns a non-success code
    (some mirrors like SourceForge reject HEAD), falls back to a ranged GET
    that only fetches the first byte. Returns 0 on total failure.
    """
    # Try HEAD first (fast path)
    try:
        result = subprocess.run(
            ['curl', '-sI', '-o', '/dev/null', '-w', '%{http_code}',
             '-L', '--max-time', str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5)
        if result.stdout.strip():
            status = int(result.stdout.strip())
            if 200 <= status < 400:
                return status
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Fall back to ranged GET (first byte only — cheap even for large files)
    try:
        result = subprocess.run(
            ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
             '-L', '-r', '0-0', '--max-time', str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5)
        if result.stdout.strip():
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return 0


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _github_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Build headers for GitHub API requests."""
    h = {'Accept': 'application/vnd.github.v3+json'}
    if token:
        h['Authorization'] = f'token {token}'
    return h


def extract_github_info(raw_url: str) -> Optional[Dict]:
    """Extract GitHub owner/repo and tag pattern from a raw source URL.

    Returns dict with keys: owner, repo, tag_prefix, tag_suffix, use_releases
    or None if URL is not a GitHub URL or can't be parsed.
    """
    if 'github.com' not in raw_url:
        return None

    # Extract owner/repo
    m = re.search(r'github\.com/([^/]+)/([^/]+)', raw_url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)

    # Check if %{version} is present (commit-pinned URLs won't have it)
    if '%{version}' not in raw_url:
        return None

    # Determine if it's a release or archive/tag URL
    use_releases = '/releases/download/' in raw_url

    # Extract the tag pattern containing %{version}
    tag_prefix = ""
    tag_suffix = ""

    if use_releases:
        # Pattern: /releases/download/{TAG}/filename
        m = re.search(r'/releases/download/([^/]*?)%\{version\}([^/]*?)/',
                       raw_url)
        if m:
            tag_prefix = m.group(1)
            tag_suffix = m.group(2)
    else:
        # Pattern: /archive/refs/tags/{TAG}.tar or /archive/{TAG}/
        m = re.search(
            r'/(?:archive/refs/tags/|archive/)([^%]*?)%\{version\}([^./]*)',
            raw_url)
        if m:
            tag_prefix = m.group(1)
            tag_suffix = m.group(2)

    return {
        'owner': owner,
        'repo': repo,
        'tag_prefix': tag_prefix,
        'tag_suffix': tag_suffix,
        'use_releases': use_releases,
    }


def extract_gnu_ftp_info(raw_url: str) -> Optional[Dict]:
    """Extract GNU FTP directory path from a raw source URL.

    Returns dict with keys: ftp_path, filename_pattern
    or None if not a GNU FTP URL.
    """
    if 'ftp.gnu.org' not in raw_url:
        return None

    # Extract the directory path
    # Patterns: /gnu/<pkg>/ or /pub/gnu/<pkg>/
    m = re.search(r'(ftp\.gnu\.org)(/(?:gnu|pub/gnu)/[^/]+/)', raw_url)
    if not m:
        return None
    ftp_path = m.group(2)

    # Extract filename pattern from the URL
    # Replace %{version} with a regex capture group
    filename = raw_url.rsplit('/', 1)[-1]
    filename_re = re.escape(filename).replace(
        re.escape('%{version}'), r'(\d+[\d.]*\d+)')
    # Also match different archive extensions
    filename_re = re.sub(r'\\\.tar\\\.[a-z]+$', r'\\.tar\\.[a-z]+',
                         filename_re)

    return {
        'ftp_path': ftp_path,
        'filename_pattern': filename_re,
    }


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def check_github_release_latest(owner: str, repo: str,
                                tag_prefix: str = "v",
                                tag_suffix: str = "",
                                version_transform: Optional[str] = None,
                                max_major: Optional[int] = None,
                                token: Optional[str] = None
                                ) -> Tuple[str, Optional[str]]:
    """Check GitHub /releases/latest endpoint — a single API call.

    GitHub's `/releases/latest` returns the most recent non-draft,
    non-prerelease release, filtered server-side. Much cheaper than fetching
    all tags: 1 request per package instead of up to 5.

    Returns (latest_within_max_major, blocked_higher_major_or_None). When
    max_major is set and /releases/latest exceeds it, this falls back to a
    tag scan to find the highest within-constraint version, and reports the
    higher upstream version separately.
    """
    headers = _github_headers(token)
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        body, _ = fetch_url(url, headers=headers)
    except UpdateCheckError as e:
        if '403' in str(e) and not token:
            raise UpdateCheckError(
                "GitHub API rate-limited (set GITHUB_TOKEN for higher limit)")
        raise
    release = json.loads(body)
    if not isinstance(release, dict) or 'tag_name' not in release:
        msg = release.get('message', 'Unexpected response') \
            if isinstance(release, dict) else 'Unexpected response'
        raise UpdateCheckError(
            f"GitHub releases API for {owner}/{repo}: {msg}")
    tag_name = release['tag_name']
    ver = tag_name
    if tag_prefix and ver.startswith(tag_prefix):
        ver = ver[len(tag_prefix):]
    if tag_suffix and ver.endswith(tag_suffix):
        ver = ver[:-len(tag_suffix)]
    if version_transform == 'dots_to_dashes':
        ver = ver.replace('-', '.')
    if not ver or not re.match(r'\d', ver):
        raise UpdateCheckError(
            f"Could not extract version from tag {tag_name!r} for "
            f"{owner}/{repo} (prefix={tag_prefix!r}, suffix={tag_suffix!r})")

    if max_major is not None:
        ver_major = major_of(ver)
        if ver_major is not None and ver_major > max_major:
            # /releases/latest is past our pin — scan tags for the highest
            # within-constraint version and report the latest as blocked.
            constrained, _ = check_github_tags(
                owner, repo,
                tag_prefix=tag_prefix, tag_suffix=tag_suffix,
                version_transform=version_transform,
                max_major=max_major, token=token,
            )
            return constrained, ver
    return ver, None


def check_github_tags(owner: str, repo: str,
                      tag_prefix: str = "v",
                      tag_suffix: str = "",
                      version_transform: Optional[str] = None,
                      exclude_pattern: Optional[str] = None,
                      max_major: Optional[int] = None,
                      token: Optional[str] = None,
                      max_pages: int = 3) -> Tuple[str, Optional[str]]:
    """Check GitHub tags API for latest version.

    Fetches tags with pagination (up to max_pages * 100 tags), filters by
    prefix/suffix, extracts versions, and returns the highest stable version.
    Pagination is necessary for repos like CMake or OpenSSL that have >100
    tags, where the newest release may be on the first page but related
    stable tags for comparison may be further back.

    Returns (latest_within_max_major, blocked_higher_major_or_None).
    """
    headers = _github_headers(token)
    versions = []
    all_tag_names = []

    for page in range(1, max_pages + 1):
        url = (f"https://api.github.com/repos/{owner}/{repo}/tags"
               f"?per_page=100&page={page}")
        try:
            body, resp_headers = fetch_url(url, headers=headers)
        except UpdateCheckError as e:
            if '403' in str(e) and not token:
                raise UpdateCheckError(
                    "GitHub API rate-limited "
                    "(set GITHUB_TOKEN for higher limit)")
            raise
        tags = json.loads(body)

        if not isinstance(tags, list):
            msg = tags.get('message', 'Unknown error') \
                if isinstance(tags, dict) else 'Unexpected response'
            raise UpdateCheckError(
                f"GitHub API error for {owner}/{repo}: {msg}")

        if not tags:
            break  # No more tags

        all_tag_names.extend(t['name'] for t in tags)

        for tag in tags:
            name = tag['name']
            if tag_prefix and not name.startswith(tag_prefix):
                continue
            if tag_suffix and not name.endswith(tag_suffix):
                continue
            ver = name[len(tag_prefix):]
            if tag_suffix:
                ver = ver[:-len(tag_suffix)]
            if not ver:
                continue
            if version_transform == 'dots_to_dashes':
                ver = ver.replace('-', '.')
            if is_prerelease(name) or is_prerelease(ver):
                continue
            if exclude_pattern and re.search(exclude_pattern, ver):
                continue
            if not re.match(r'\d', ver):
                continue
            versions.append(ver)

        # Stop paginating once we got fewer than a full page
        if len(tags) < 100:
            break

    if not versions:
        raise UpdateCheckError(
            f"No matching tags found for {owner}/{repo} "
            f"(prefix={tag_prefix!r}, suffix={tag_suffix!r})")

    # Sort by parsed version and return highest
    versions.sort(key=parse_version, reverse=True)
    unconstrained_latest = versions[0]
    if max_major is None:
        return unconstrained_latest, None

    constrained = [v for v in versions
                   if (m := major_of(v)) is not None and m <= max_major]
    if not constrained:
        raise UpdateCheckError(
            f"No tags within max_major={max_major} for {owner}/{repo}")
    unc_major = major_of(unconstrained_latest)
    blocked = unconstrained_latest if (
        unc_major is not None and unc_major > max_major) else None
    return constrained[0], blocked


def check_gnu_ftp(ftp_path: str,
                  filename_pattern: str,
                  dir_pattern: Optional[str] = None,
                  max_major: Optional[int] = None
                  ) -> Tuple[str, Optional[str]]:
    """Check GNU FTP directory listing for latest version.

    For most packages, scans the flat directory listing.
    For GCC-style packages with subdirectories, uses dir_pattern to scan
    subdirectory names first.

    Returns (latest_within_max_major, blocked_higher_major_or_None).
    """
    base_url = f"https://ftp.gnu.org{ftp_path}"

    if dir_pattern:
        # Scan subdirectories (e.g., gcc-X.Y.Z/)
        body, _ = fetch_url(base_url)
        versions = re.findall(dir_pattern, body)
    else:
        # Scan filenames in flat directory
        body, _ = fetch_url(base_url)
        versions = re.findall(filename_pattern, body)

    if not versions:
        raise UpdateCheckError(
            f"No versions found at {base_url} "
            f"(pattern={filename_pattern!r})")

    # Deduplicate and sort
    versions = list(set(versions))
    versions.sort(key=parse_version, reverse=True)
    unconstrained_latest = versions[0]
    if max_major is None:
        return unconstrained_latest, None
    constrained = [v for v in versions
                   if (m := major_of(v)) is not None and m <= max_major]
    if not constrained:
        raise UpdateCheckError(
            f"No versions within max_major={max_major} at "
            f"https://ftp.gnu.org{ftp_path}")
    unc_major = major_of(unconstrained_latest)
    blocked = unconstrained_latest if (
        unc_major is not None and unc_major > max_major) else None
    return constrained[0], blocked


def check_html_regex(url: str, pattern: str) -> str:
    """Scrape an HTML page for version using a regex pattern.

    The pattern should contain a named group (?P<version>...) or a
    capture group that extracts the version string.
    """
    body, _ = fetch_url(url)
    matches = re.findall(pattern, body)
    if not matches:
        raise UpdateCheckError(
            f"Pattern {pattern!r} did not match anything at {url}")

    # Deduplicate and sort
    versions = list(set(matches))
    versions.sort(key=parse_version, reverse=True)
    return versions[0]


def check_github_commit(owner: str, repo: str,
                        branch: Optional[str] = None,
                        token: Optional[str] = None) -> str:
    """Check the latest commit SHA on a GitHub branch.

    Returns the short (12-char) SHA of the latest commit. Used for packages
    that are pinned to a commit hash rather than a tagged release.

    When branch is None, tries "HEAD" (GitHub API resolves this to the
    default branch server-side — 1 request instead of 2).
    """
    headers = _github_headers(token)
    # "HEAD" is a valid ref on the commits endpoint that resolves to the
    # repo's default branch, saving a round trip to discover it.
    ref = branch or 'HEAD'
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    try:
        body, _ = fetch_url(url, headers=headers)
    except UpdateCheckError as e:
        if '403' in str(e) and not token:
            raise UpdateCheckError(
                "GitHub API rate-limited (set GITHUB_TOKEN for higher limit)")
        raise
    commit = json.loads(body)
    sha = commit.get('sha')
    if not sha:
        raise UpdateCheckError(f"No sha in commit response for {owner}/{repo}")
    return sha[:12]


def check_gitlab(instance: str, repo: str,
                 tag_prefix: str = "v",
                 tag_suffix: str = "") -> str:
    """Check GitLab tags API for latest version."""
    # URL-encode the repo path
    encoded = repo.replace('/', '%2F')
    url = (f"{instance}/api/v4/projects/{encoded}"
           f"/repository/tags?per_page=100")
    body, _ = fetch_url(url)
    tags = json.loads(body)

    if not isinstance(tags, list):
        raise UpdateCheckError(f"GitLab API error for {repo}: {body[:200]}")

    versions = []
    for tag in tags:
        name = tag['name']
        if tag_prefix and not name.startswith(tag_prefix):
            continue
        if tag_suffix and not name.endswith(tag_suffix):
            continue
        ver = name[len(tag_prefix):]
        if tag_suffix:
            ver = ver[:-len(tag_suffix)]
        if not ver or not re.match(r'\d', ver):
            continue
        if is_prerelease(name):
            continue
        versions.append(ver)

    if not versions:
        raise UpdateCheckError(
            f"No matching tags found on {instance} for {repo}")

    versions.sort(key=parse_version, reverse=True)
    return versions[0]


# ---------------------------------------------------------------------------
# Strategy resolution
# ---------------------------------------------------------------------------

def resolve_strategy(recipe: Dict) -> Tuple[str, Dict]:
    """Determine the update checking strategy for a package.

    Returns (strategy_name, config_dict).

    Priority:
    1. If 'update.strategy' is explicit, use it as-is.
    2. Otherwise auto-detect from source URL (GitHub, GNU FTP) and merge any
       user-supplied keys from 'update:' (e.g. max_major) into the config.
    3. Return ('undetermined', ...) when neither path applies.
    """
    user_update = recipe.get('update') or {}
    if not isinstance(user_update, dict):
        user_update = {}

    # 1. Explicit strategy: user fully owns the config.
    if 'strategy' in user_update:
        return user_update['strategy'], dict(user_update)

    # 2. Auto-detect from source URL, then layer user keys on top so
    # constraints like max_major work without forcing a full update block.
    # The build system (unix_builder.py, rpm_builder.py) prefers source0 over
    # url when both are present, treating url as a project page in that case.
    # Mirror that priority here so auto-detection targets the real tarball.
    source = recipe.get('source', {})
    if isinstance(source, dict):
        url = source.get('source0') or source.get('url', '')
    else:
        return 'undetermined', {'reason': 'No source URL', **user_update}

    if not url or source.get('type') == 'generated':
        return 'undetermined', {'reason': 'No external source', **user_update}

    # Try GitHub
    gh = extract_github_info(url)
    if gh:
        strategy = 'github_release' if gh['use_releases'] else 'github_tag'
        config = {
            'repo': f"{gh['owner']}/{gh['repo']}",
            'tag_prefix': gh['tag_prefix'],
            'tag_suffix': gh['tag_suffix'],
        }
        config.update(user_update)
        return strategy, config

    # Try GNU FTP
    gnu = extract_gnu_ftp_info(url)
    if gnu:
        config = dict(gnu)
        config.update(user_update)
        return 'gnu_ftp', config

    return 'undetermined', {'reason': 'No updater strategy configured',
                            **user_update}


def predict_download_url(recipe: Dict, new_version: str) -> Optional[str]:
    """Predict the download URL for a new version by substituting into
    the recipe's URL template. Prefers source0 over url (matches build system)."""
    source = recipe.get('source', {})
    if not isinstance(source, dict):
        return None
    url_template = source.get('source0') or source.get('url', '')
    if '%{version}' not in url_template:
        return None
    return url_template.replace('%{version}', new_version)


# ---------------------------------------------------------------------------
# Package checking
# ---------------------------------------------------------------------------

def check_package(package_name: str,
                  recipes_dir: Path = Path("recipes"),
                  verify_download: bool = False,
                  github_token: Optional[str] = None,
                  verbose: bool = False) -> UpdateResult:
    """Check a single package for updates."""
    try:
        recipe = load_recipe_raw(package_name, recipes_dir)
    except UpdateCheckError as e:
        return UpdateResult(package_name, "?", status=ERROR, reason=str(e))

    current = str(recipe.get('version', '?'))
    strategy, config = resolve_strategy(recipe)

    # Allow update config to override what we compare against — useful when
    # the recipe's version field doesn't match upstream's tag scheme
    # (e.g. Apple's zlib where tag=zlib-100 but version=1.2.12).
    if isinstance(config, dict) and 'current' in config:
        current = str(config['current'])

    if verbose:
        print(f"  {package_name}: strategy={strategy}", file=sys.stderr)

    # Handle skip
    if strategy == 'skip':
        reason = config.get('reason', 'Skipped')
        return UpdateResult(package_name, current, status=SKIP,
                            source_type='skip', reason=reason)

    # Handle undetermined
    if strategy == 'undetermined':
        reason = config.get('reason', 'No updater strategy configured')
        return UpdateResult(package_name, current, status=UNDETERMINED,
                            source_type='', reason=reason)

    # Discover latest version
    latest = None
    blocked_higher = None
    source_type = strategy
    max_major = config.get('max_major') if isinstance(config, dict) else None
    try:
        if strategy in ('github_release', 'github_tag'):
            repo = config.get('repo', '')
            if '/' in repo:
                owner, repo_name = repo.split('/', 1)
            else:
                # Should not happen if resolve_strategy works correctly
                raise UpdateCheckError("No repo configured")
            if strategy == 'github_release':
                # Use /releases/latest — 1 API call, server-side filtering
                # of drafts and prereleases.
                try:
                    latest, blocked_higher = check_github_release_latest(
                        owner, repo_name,
                        tag_prefix=config.get('tag_prefix', 'v'),
                        tag_suffix=config.get('tag_suffix', ''),
                        version_transform=config.get('version_transform'),
                        max_major=max_major,
                        token=github_token,
                    )
                except UpdateCheckError as e:
                    # Some repos (e.g. libevent, openssl) publish releases but
                    # /releases/latest returns 404 when no release is flagged
                    # "latest". Fall back to scanning tags.
                    if '404' in str(e):
                        latest, blocked_higher = check_github_tags(
                            owner, repo_name,
                            tag_prefix=config.get('tag_prefix', 'v'),
                            tag_suffix=config.get('tag_suffix', ''),
                            version_transform=config.get('version_transform'),
                            exclude_pattern=config.get('exclude_pattern'),
                            max_major=max_major,
                            token=github_token,
                        )
                    else:
                        raise
            else:
                latest, blocked_higher = check_github_tags(
                    owner, repo_name,
                    tag_prefix=config.get('tag_prefix', 'v'),
                    tag_suffix=config.get('tag_suffix', ''),
                    version_transform=config.get('version_transform'),
                    exclude_pattern=config.get('exclude_pattern'),
                    max_major=max_major,
                    token=github_token,
                )
        elif strategy == 'gnu_ftp':
            latest, blocked_higher = check_gnu_ftp(
                config['ftp_path'],
                config.get('filename_pattern', ''),
                dir_pattern=config.get('dir_pattern'),
                max_major=max_major,
            )
        elif strategy == 'html_regex':
            latest = check_html_regex(
                config['url'],
                config['pattern'],
            )
        elif strategy == 'gitlab':
            latest = check_gitlab(
                config.get('instance', 'https://gitlab.com'),
                config['repo'],
                tag_prefix=config.get('tag_prefix', 'v'),
                tag_suffix=config.get('tag_suffix', ''),
            )
        elif strategy == 'github_commit':
            repo = config.get('repo', '')
            if '/' not in repo:
                raise UpdateCheckError("No repo configured")
            owner, repo_name = repo.split('/', 1)
            latest_sha = check_github_commit(
                owner, repo_name,
                branch=config.get('branch'),
                token=github_token,
            )
            # Extract current pinned hash from the source URL.
            # Prefer source0 over url (matches build system and other strategies).
            source_block = recipe.get('source', {}) or {}
            source_url = source_block.get('source0') or source_block.get('url', '')
            m = re.search(r'/archive/([a-f0-9]{7,40})\.tar\.', source_url)
            current_sha = m.group(1)[:12] if m else '?'
            # Commits don't have version ordering — just compare equality
            if latest_sha == current_sha or \
                    latest_sha.startswith(current_sha) or \
                    current_sha.startswith(latest_sha):
                return UpdateResult(package_name, current_sha,
                                    latest_version=latest_sha,
                                    status=UP_TO_DATE,
                                    source_type=source_type)
            return UpdateResult(package_name, current_sha,
                                latest_version=latest_sha,
                                status=UPDATE_AVAILABLE,
                                source_type=source_type,
                                reason="Upstream has newer commits on "
                                       f"{config.get('branch') or 'default branch'}")
        else:
            return UpdateResult(package_name, current, status=UNDETERMINED,
                                source_type=strategy,
                                reason=f"Unknown strategy: {strategy}")
    except UpdateCheckError as e:
        return UpdateResult(package_name, current, status=ERROR,
                            source_type=source_type, reason=str(e))

    if not latest:
        return UpdateResult(package_name, current, status=UNDETERMINED,
                            source_type=source_type,
                            reason="Provider returned no version")

    # Compare versions
    if not is_newer(latest, current):
        return UpdateResult(package_name, current,
                            latest_version=latest,
                            status=UP_TO_DATE,
                            source_type=source_type,
                            blocked_version=blocked_higher)

    # Update available — optionally verify download URL
    download_url = predict_download_url(recipe, latest)
    download_ok = None

    if verify_download and download_url:
        status_code = head_url(download_url)
        download_ok = 200 <= status_code < 400
        if not download_ok:
            return UpdateResult(package_name, current,
                                latest_version=latest,
                                status=UPDATE_URL_FAILED,
                                source_type=source_type,
                                download_url=download_url,
                                download_ok=False,
                                reason=f"HTTP {status_code}",
                                blocked_version=blocked_higher)

    return UpdateResult(package_name, current,
                        latest_version=latest,
                        status=UPDATE_AVAILABLE,
                        source_type=source_type,
                        download_url=download_url,
                        download_ok=download_ok,
                        blocked_version=blocked_higher)


def check_all(recipes_dir: Path = Path("recipes"),
              verify_download: bool = False,
              github_token: Optional[str] = None,
              verbose: bool = False) -> List[UpdateResult]:
    """Check all packages for updates, alphabetically."""
    names = load_all_recipe_names(recipes_dir)
    results = []
    for name in names:
        if verbose:
            print(f"Checking {name}...", file=sys.stderr)
        result = check_package(name, recipes_dir, verify_download,
                               github_token, verbose)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_report(results: List[UpdateResult]) -> str:
    """Format results as a human-readable sectioned report."""
    updates = [r for r in results if r.status == UPDATE_AVAILABLE]
    url_failed = [r for r in results if r.status == UPDATE_URL_FAILED]
    up_to_date = [r for r in results if r.status == UP_TO_DATE]
    blocked = [r for r in up_to_date if r.blocked_version]
    up_to_date_clean = [r for r in up_to_date if not r.blocked_version]
    skipped = [r for r in results if r.status == SKIP]
    undetermined = [r for r in results if r.status == UNDETERMINED]
    errors = [r for r in results if r.status == ERROR]

    lines = []
    lines.append("SCLS Package Update Check")
    lines.append("=" * 50)
    lines.append("")

    # Updates available
    if updates:
        lines.append(f"Updates available ({len(updates)}):")
        for r in updates:
            dl = ""
            if r.download_ok is True:
                dl = "  [download verified]"
            blocked_note = ""
            if r.blocked_version:
                blocked_note = f"  [major {r.blocked_version} blocked by pin]"
            lines.append(f"  {r.name:<20s} {r.current_version:>12s}"
                         f"  ->  {r.latest_version:<12s}"
                         f"  ({r.source_type}){dl}{blocked_note}")
        lines.append("")

    # URL verification failures
    if url_failed:
        lines.append(f"Update found but download URL failed ({len(url_failed)}):")
        for r in url_failed:
            lines.append(f"  {r.name:<20s} {r.current_version:>12s}"
                         f"  ->  {r.latest_version:<12s}"
                         f"  ({r.source_type})")
            if r.download_url:
                lines.append(f"    URL: {r.download_url}")
            if r.reason:
                lines.append(f"    {r.reason}")
        lines.append("")

    # Major version blocked by max_major pin (no in-range update available)
    if blocked:
        lines.append(f"Major version blocked by pin ({len(blocked)}):")
        for r in blocked:
            lines.append(f"  {r.name:<20s} {r.current_version:>12s}"
                         f"  ->  {r.blocked_version:<12s}"
                         f"  (held back by max_major)")
        lines.append("")

    # Up to date
    if up_to_date_clean:
        lines.append(f"Up to date ({len(up_to_date_clean)}):")
        # Compact format — multiple per line
        items = [f"{r.name} {r.current_version}" for r in up_to_date_clean]
        line = "  "
        for item in items:
            if len(line) + len(item) + 2 > 78:
                lines.append(line.rstrip(", "))
                line = "  "
            line += item + ", "
        if line.strip():
            lines.append(line.rstrip(", "))
        lines.append("")

    # Skipped
    if skipped:
        lines.append(f"Skipped ({len(skipped)}):")
        for r in skipped:
            reason = r.reason or "skipped"
            lines.append(f"  {r.name:<20s} ({reason})")
        lines.append("")

    # Undetermined
    if undetermined:
        lines.append(f"Could not determine ({len(undetermined)}):")
        for r in undetermined:
            reason = r.reason or "unknown"
            lines.append(f"  {r.name:<20s} ({reason})")
        lines.append("")

    # Errors
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for r in errors:
            reason = r.reason or "unknown error"
            lines.append(f"  {r.name:<20s} ({reason})")
        lines.append("")

    # Summary
    total = len(results)
    summary_parts = [
        f"{total} packages",
        f"{len(updates)} updates",
    ]
    if url_failed:
        summary_parts.append(f"{len(url_failed)} url-failed")
    if blocked:
        summary_parts.append(f"{len(blocked)} major-blocked")
    summary_parts += [
        f"{len(up_to_date_clean)} up-to-date",
        f"{len(skipped)} skipped",
        f"{len(undetermined)} undetermined",
        f"{len(errors)} errors",
    ]
    lines.append("Summary: " + ", ".join(summary_parts))

    return '\n'.join(lines)


def format_json(results: List[UpdateResult]) -> str:
    """Format results as JSON."""
    updates = [r for r in results if r.status == UPDATE_AVAILABLE]
    url_failed = [r for r in results if r.status == UPDATE_URL_FAILED]
    up_to_date = [r for r in results if r.status == UP_TO_DATE]
    blocked = [r for r in up_to_date if r.blocked_version]
    skipped = [r for r in results if r.status == SKIP]
    undetermined = [r for r in results if r.status == UNDETERMINED]
    errors = [r for r in results if r.status == ERROR]

    data = {
        "packages": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "updates": len(updates),
            "url_failed": len(url_failed),
            "up_to_date": len(up_to_date),
            "major_blocked": len(blocked),
            "skipped": len(skipped),
            "undetermined": len(undetermined),
            "errors": len(errors),
        }
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='SCLS Package Version Update Checker')
    parser.add_argument(
        'package', nargs='?', default='all',
        help='Package name to check, or "all" (default: all)')
    parser.add_argument(
        '--json', action='store_true', dest='json_output',
        help='Output in JSON format')
    parser.add_argument(
        '--verify-downloads', action='store_true',
        help='Verify that predicted download URLs are reachable (slower)')
    parser.add_argument(
        '--github-token', default=None,
        help='GitHub API token (or set GITHUB_TOKEN env var)')
    parser.add_argument(
        '--recipes-dir', default='recipes',
        help='Path to recipes directory (default: recipes)')
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show progress on stderr')

    args = parser.parse_args()
    recipes_dir = Path(args.recipes_dir)
    token = args.github_token or os.environ.get('GITHUB_TOKEN')

    if args.package == 'all':
        results = check_all(recipes_dir, args.verify_downloads, token,
                            args.verbose)
    else:
        result = check_package(args.package, recipes_dir,
                               args.verify_downloads, token, args.verbose)
        results = [result]

    if args.json_output:
        print(format_json(results))
    else:
        print(format_report(results))

    # Exit with non-zero if there were errors
    errors = [r for r in results if r.status == ERROR]
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
