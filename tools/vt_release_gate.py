import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GITHUB_API = 'https://api.github.com'
VT_API = 'https://www.virustotal.com/api/v3'
GITHUB_HOSTS = frozenset({'api.github.com', 'uploads.github.com'})
ASSET_HOST_SUFFIX = '.githubusercontent.com'
VT_HOSTS = frozenset({'www.virustotal.com'})
TAG_PATTERN = re.compile(r'^v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:-[A-Za-z0-9]{1,32}(?:\.[A-Za-z0-9]{1,32}){0,3})?$')
REPO_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
OUTPUT_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MAX_UPLOAD_BYTES = 32 << 20
VT_INTERVAL = 15.5
VT_POLLS = 120
VT_RETRIES = 3
RATE_LIMIT_WAIT = 65.0
NOTES_MARK = '## VirusTotal scan'
TEST_SIGNATURE = ''.join(('X5O!P%@AP[4\\PZX54(P^)7CC)7}$', 'EICAR-STANDARD-', 'ANTIVIRUS-TEST-FILE!$H+H*')).encode('ascii')
USER_AGENT = 'Devil-Painter-Release-Scan-Gate'


@dataclass
class Verdict:
    sha256: str
    malicious: int
    suspicious: int
    harmless: int
    undetected: int
    engines: list = field(default_factory=list)
    source: str = ''

    @property
    def clean(self):
        return self.malicious == 0 and self.suspicious == 0

    @property
    def link(self):
        return f'https://www.virustotal.com/gui/file/{self.sha256}'


class GateError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


def checked_url(url, hosts, suffix=''):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443):
        raise GateError(f'refused a non-https or credentialed address for {host or "an unknown host"}')
    if host not in hosts and not (suffix and host.endswith(suffix)):
        raise GateError(f'refused an address outside the allowlist: {host}')
    return url


def valid_tag(tag):
    return bool(TAG_PATTERN.match(tag or ''))


def asset_name(tag):
    return f'devil_painter-{tag[1:]}.zip'


def single_line(value, limit=300):
    return re.sub(r'[\r\n\x00]+', ' ', str(value)).strip()[:limit]


def set_output(name, value):
    if not OUTPUT_NAME.match(name):
        raise GateError(f'unsafe output name {name!r}')
    value = str(value)
    if any(character in value for character in '\r\n\x00'):
        raise GateError(f'unsafe characters in output {name}')
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(f'{name}={value}\n')


def summary(markdown):
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(markdown.rstrip() + '\n\n')
    print(markdown)


def github(url, token, method='GET', body=None, accept='application/vnd.github+json'):
    checked_url(url, GITHUB_HOSTS)
    headers = {'Authorization': f'Bearer {token}', 'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': USER_AGENT}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        raise GateError(f'GitHub {method} {urllib.parse.urlsplit(url).path} failed with {error.code}') from error


def draft_release(repo, token, tag):
    releases = github(f'{GITHUB_API}/repos/{repo}/releases?per_page=100', token)
    drafts = [release for release in releases if release.get('draft') is True]
    if not tag:
        if not drafts:
            raise GateError('there is no draft release to scan')
        drafts.sort(key=lambda release: release.get('created_at', ''), reverse=True)
        tag = drafts[0].get('tag_name', '')
        if not valid_tag(tag):
            raise GateError('the newest draft release has an invalid tag')
    match = next((release for release in releases if release.get('tag_name') == tag), None)
    if match is None:
        raise GateError(f'no release named {tag} exists')
    if match.get('draft') is not True:
        raise GateError(f'release {tag} is already published; the gate only scans drafts')
    return match


def release_asset(release, tag):
    assets = release.get('assets') or []
    expected = asset_name(tag)
    if len(assets) != 1 or assets[0].get('name') != expected:
        raise GateError(f'the draft must carry exactly one asset named {expected}')
    asset = assets[0]
    if not 0 < int(asset.get('size') or 0) <= MAX_UPLOAD_BYTES:
        raise GateError(f'{expected} must be between 1 byte and 32 MB')
    return asset


def download(asset, token, folder):
    url = checked_url(asset['url'], GITHUB_HOSTS)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/octet-stream',
                                                   'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': USER_AGENT})
    try:
        with opener.open(request, timeout=120) as response:
            data = response.read(MAX_UPLOAD_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise GateError(f'downloading the asset failed with {error.code}') from error
        location = checked_url(error.headers.get('Location', ''), GITHUB_HOSTS, ASSET_HOST_SUFFIX)
        plain = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with plain.open(urllib.request.Request(location, headers={'User-Agent': USER_AGENT}), timeout=120) as response:
            data = response.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES or len(data) != int(asset['size']):
        raise GateError('the downloaded asset does not match its listed size')
    path = Path(folder) / asset['name']
    path.write_bytes(data)
    return path


def sha256_of(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def verdict_from(sha256, stats, results, source):
    engines = sorted(f'{name}: {detail.get("result") or detail.get("category")}' for name, detail in (results or {}).items()
                     if isinstance(detail, dict) and detail.get('category') in ('malicious', 'suspicious'))
    return Verdict(sha256, int(stats.get('malicious', 0)), int(stats.get('suspicious', 0)), int(stats.get('harmless', 0)),
                   int(stats.get('undetected', 0)), engines, source)


class VirusTotal:
    def __init__(self, key):
        self.key = key
        self.last = 0.0

    def pace(self):
        wait = VT_INTERVAL - (time.monotonic() - self.last)
        if self.last and wait > 0:
            time.sleep(wait)

    def call(self, url, method='GET', data=None, content_type=None):
        checked_url(url, VT_HOSTS)
        for attempt in range(VT_RETRIES + 1):
            self.pace()
            headers = {'x-apikey': self.key, 'Accept': 'application/json', 'User-Agent': USER_AGENT}
            if content_type:
                headers['Content-Type'] = content_type
            self.last = time.monotonic()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            try:
                with opener.open(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=180) as response:
                    payload = response.read()
                    return response.status, json.loads(payload) if payload else {}
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return 404, {}
                if error.code == 429 and attempt < VT_RETRIES:
                    time.sleep(RATE_LIMIT_WAIT)
                    continue
                raise GateError(f'VirusTotal {method} {urllib.parse.urlsplit(url).path} failed with {error.code}') from error
        raise GateError('VirusTotal kept rate-limiting the gate')

    def scan(self, path, sha256):
        status, payload = self.call(f'{VT_API}/files/{sha256}')
        attributes = payload.get('data', {}).get('attributes', {}) if status == 200 else {}
        if attributes.get('last_analysis_stats') and attributes.get('last_analysis_results'):
            return verdict_from(sha256, attributes['last_analysis_stats'], attributes['last_analysis_results'], 'hash lookup')
        boundary = f'devil-painter-{uuid.uuid4().hex}'
        body = b''.join((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode('ascii'),
                         b'Content-Type: application/zip\r\n\r\n', path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode('ascii')))
        _, upload = self.call(f'{VT_API}/files', 'POST', body, f'multipart/form-data; boundary={boundary}')
        analysis = upload.get('data', {}).get('id', '')
        if not re.match(r'^[A-Za-z0-9=_-]{8,200}$', analysis):
            raise GateError('VirusTotal returned no analysis id for the upload')
        for _ in range(VT_POLLS):
            _, result = self.call(f'{VT_API}/analyses/{analysis}')
            attributes = result.get('data', {}).get('attributes', {})
            if attributes.get('status') == 'completed':
                return verdict_from(sha256, attributes.get('stats', {}), attributes.get('results', {}), 'upload')
        raise GateError('the VirusTotal analysis did not finish in time')


def contains_test_signature(data):
    if TEST_SIGNATURE in data:
        return True
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return any(TEST_SIGNATURE in archive.read(member) for member in archive.infolist() if member.file_size <= MAX_UPLOAD_BYTES)
    except zipfile.BadZipFile:
        return False


class SimulatedVirusTotal:
    def scan(self, path, sha256):
        if contains_test_signature(path.read_bytes()):
            return Verdict(sha256, 1, 0, 0, 0, ['Simulated: EICAR test signature'], 'simulated')
        return Verdict(sha256, 0, 0, 0, 1, [], 'simulated')


def verdict_table(name, verdict, simulate):
    rows = [f'| {name} | `{verdict.sha256}` | {verdict.malicious} | {verdict.suspicious} | {verdict.harmless} | {verdict.undetected} | '
            f'{"clean" if verdict.clean else "FLAGGED"} |']
    lines = ['## Release scan gate' + (' (SIMULATED - no real VirusTotal call)' if simulate else ''), '',
             '| File | SHA-256 | Malicious | Suspicious | Harmless | Undetected | Result |', '|---|---|---|---|---|---|---|', *rows]
    if verdict.engines:
        lines += ['', '**Flagged by:** ' + ', '.join(single_line(engine, 120) for engine in verdict.engines[:40])]
    if not simulate:
        lines += ['', f'Report: {verdict.link}']
    return '\n'.join(lines)


def scan_record(name, verdict, when):
    total = verdict.malicious + verdict.suspicious + verdict.harmless + verdict.undetected
    return '\n'.join((NOTES_MARK, '', f'- File: `{name}`', f'- SHA-256: `{verdict.sha256}`',
                      f'- Result: {verdict.malicious} malicious, {verdict.suspicious} suspicious, {verdict.harmless} harmless, '
                      f'{verdict.undetected} undetected ({total} engines), scanned {when} by the release scan gate',
                      f'- Report: {verdict.link}'))


def notes_with_record(notes, record):
    notes = (notes or '').rstrip()
    if NOTES_MARK in notes:
        notes = notes[:notes.index(NOTES_MARK)].rstrip()
    return f'{notes}\n\n{record}\n' if notes else f'{record}\n'


def publish(repo, token, release, asset, sha256, verdict):
    fresh = github(f'{GITHUB_API}/repos/{repo}/releases/{int(release["id"])}', token)
    current = fresh.get('assets') or []
    if fresh.get('draft') is not True or len(current) != 1 or current[0].get('id') != asset['id'] or current[0].get('size') != asset['size'] \
            or current[0].get('updated_at') != asset.get('updated_at') or fresh.get('tag_name') != release.get('tag_name'):
        raise GateError('the draft changed while it was being scanned; it stays a draft')
    listed = (current[0].get('digest') or '').removeprefix('sha256:')
    if listed and listed != sha256:
        raise GateError('the asset digest GitHub reports does not match the scanned file; it stays a draft')
    when = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    body = notes_with_record(fresh.get('body'), scan_record(asset['name'], verdict, when))
    published = github(f'{GITHUB_API}/repos/{repo}/releases/{int(release["id"])}', token, 'PATCH', dict(body=body, draft=False))
    if published.get('draft') is not False:
        raise GateError('GitHub did not publish the release')
    return published.get('html_url', '')


def run():
    simulate = os.environ.get('SIMULATE', 'false').strip().lower() == 'true'
    key = os.environ.get('VT_API_KEY', '')
    token = os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('REPOSITORY', '')
    tag = os.environ.get('RELEASE_TAG', '').strip()
    set_output('clean', 'false')
    set_output('published', 'false')
    if not simulate and not key:
        raise GateError('the VIRUS_TOTAL_TOKEN secret is not set; add it under Settings > Secrets and variables > Actions. The release stays a draft')
    if not token or not REPO_PATTERN.match(repo):
        raise GateError('the GitHub token or repository name is missing')
    if tag and not valid_tag(tag):
        raise GateError('release_tag must look like v1.2.3 or v1.2.3-label')
    release = draft_release(repo, token, tag)
    tag = release['tag_name']
    set_output('release_tag', tag)
    asset = release_asset(release, tag)
    with tempfile.TemporaryDirectory() as folder:
        path = download(asset, token, folder)
        sha256 = sha256_of(path)
        client = SimulatedVirusTotal() if simulate else VirusTotal(key)
        verdict = client.scan(path, sha256)
    summary(verdict_table(asset['name'], verdict, simulate))
    set_output('sha256', sha256)
    if not verdict.clean:
        summary(f'**Blocked:** {asset["name"]} was flagged ({verdict.malicious} malicious, {verdict.suspicious} suspicious). Release {tag} stays a draft.')
        return 1
    set_output('clean', 'true')
    if simulate:
        summary(f'**Simulated pass:** {asset["name"]} is clean in simulate mode. Simulate never publishes, so release {tag} stays a draft and its notes are unchanged.')
        return 0
    url = publish(repo, token, release, asset, sha256, verdict)
    set_output('published', 'true')
    summary(f'**Published:** {asset["name"]} is clean ({verdict.malicious} malicious, {verdict.suspicious} suspicious). Release {tag} is public: {url}')
    return 0


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ['--validate-tag']:
        tag = os.environ.get('RELEASE_TAG', '')
        if tag and not valid_tag(tag):
            print('ERROR: release_tag must look like v1.2.3 or v1.2.3-label.')
            return 1
        return 0
    try:
        return run()
    except GateError as error:
        summary(f'**Release scan gate stopped:** {single_line(error)}. Nothing was published.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
