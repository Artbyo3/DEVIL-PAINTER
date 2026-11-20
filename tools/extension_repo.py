import json
import os
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
from tools.vt_release_gate import GITHUB_API, REPO_PATTERN, GateError, asset_name, download, github, sha256_of, single_line, valid_tag

PACKAGE_ID = 'devil_painter'
MANIFEST_NAME = 'blender_manifest.toml'
REQUIRED_FIELDS = ('schema_version', 'id', 'name', 'tagline', 'version', 'type', 'maintainer', 'license', 'blender_version_min')
OPTIONAL_FIELDS = ('blender_version_max', 'website', 'copyright', 'permissions', 'tags', 'platforms')
UNSUPPORTED_FIELDS = ('wheels', 'asset_library')


def version_key(entry):
    return tuple(int(part) for part in entry['version'].split('-')[0].split('+')[0].split('.'))


def package_entry(path, archive_url):
    with zipfile.ZipFile(path) as archive:
        if MANIFEST_NAME not in archive.NameToInfo:
            raise GateError(f'{path.name} has no {MANIFEST_NAME} at its root')
        manifest = tomllib.loads(archive.read(MANIFEST_NAME).decode('utf-8'))
    missing = [name for name in REQUIRED_FIELDS if manifest.get(name) is None]
    if missing:
        raise GateError(f'{path.name} manifest is missing {", ".join(missing)}')
    unsupported = [name for name in UNSUPPORTED_FIELDS if name in manifest]
    if unsupported:
        raise GateError(f'{path.name} uses {", ".join(unsupported)}, which this index tool does not list')
    entry = {name: manifest[name] for name in REQUIRED_FIELDS + OPTIONAL_FIELDS if manifest.get(name) is not None}
    entry['archive_url'] = archive_url
    entry['archive_size'] = path.stat().st_size
    entry['archive_hash'] = f'sha256:{sha256_of(path)}'
    return entry


def repository_index(packages):
    entries = [package_entry(path, url) for path, url in packages]
    return dict(version='v1', blocklist=[], assetlib_auth_method='PER_LIBRARY', data=[max(entries, key=version_key)])


def write_repository(folder, index):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'index.json').write_bytes(json.dumps(index, indent=2).encode('utf-8'))


def published_releases(repo, token):
    releases, page = [], 1
    while True:
        batch = github(f'{GITHUB_API}/repos/{repo}/releases?per_page=100&page={page}', token)
        releases += [release for release in batch if release.get('draft') is False and release.get('prerelease') is False]
        if len(batch) < 100:
            return releases
        page += 1


def release_asset(repo, release):
    tag = release.get('tag_name', '')
    if not valid_tag(tag):
        raise GateError(f'published release {single_line(tag, 60)!r} has no valid version tag')
    name = asset_name(tag)
    asset = next((item for item in release.get('assets') or [] if item.get('name') == name), None)
    if asset is None:
        raise GateError(f'published release {tag} has no {name} asset')
    expected = f'https://github.com/{repo}/releases/download/{tag}/{name}'
    if asset.get('browser_download_url') != expected:
        raise GateError(f'the {name} download address is not {expected}')
    return asset, expected


def release_packages(repo, token, folder):
    packages = []
    for release in published_releases(repo, token):
        asset, url = release_asset(repo, release)
        path = download(asset, token, folder)
        listed = (asset.get('digest') or '').removeprefix('sha256:')
        if listed and listed != sha256_of(path):
            raise GateError(f'{asset["name"]} does not match the SHA-256 GitHub lists for it')
        packages.append((path, url))
    if not packages:
        raise GateError('there is no published release to list')
    return packages


def run(output):
    token = os.environ.get('GH_TOKEN', '')
    repo = os.environ.get('REPOSITORY', '')
    if not token or not REPO_PATTERN.match(repo):
        raise GateError('the GitHub token or repository name is missing')
    with tempfile.TemporaryDirectory() as folder:
        index = repository_index(release_packages(repo, token, folder))
    for entry in index['data']:
        if entry['id'] != PACKAGE_ID or not entry['archive_url'].endswith(f'/v{entry["version"]}/{asset_name("v" + entry["version"])}'):
            raise GateError(f'the archive at {entry["archive_url"]} carries {entry["id"]} {entry["version"]}, not its release version')
    write_repository(Path(output), index)
    for entry in index['data']:
        print(f'{entry["version"]} {entry["archive_hash"]} {entry["archive_size"]} {entry["archive_url"]}')
    return 0


def main():
    if len(sys.argv) != 2:
        print('usage: python tools/extension_repo.py OUTPUT_FOLDER')
        return 2
    try:
        return run(sys.argv[1])
    except GateError as error:
        print(f'ERROR: extension repository not built: {single_line(error)}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
