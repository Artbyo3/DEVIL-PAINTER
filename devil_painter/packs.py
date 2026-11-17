import hashlib
import json
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import PurePosixPath
import bpy
from .library import PACK_MARKER, packs_folder, rescan

CATALOG_URL = 'https://artbyo3.github.io/DEVIL-PAINTER_Asset_Library/packs.json'
RELEASE_PREFIX = 'https://github.com/Artbyo3/DEVIL-PAINTER_Asset_Library/releases/download/'
REDIRECT_HOSTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}
DATA_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.exr', '.webp', '.svg', '.json'}
CHUNK = 1 << 16
TIMEOUT = 60
MAX_PACK_BYTES = 4 << 30
SHA_PATTERN = re.compile(r'^[0-9a-f]{64}$')
CATALOG_FILE = 'catalog.json'
_state = dict(catalog=None, error='', requests=0)
_jobs = {}


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        target = urllib.parse.urlsplit(url)
        if target.scheme != 'https' or target.hostname not in REDIRECT_HOSTS:
            raise urllib.error.URLError(f'refused redirect to {target.hostname}')
        return super().redirect_request(request, response, code, message, headers, url)


def online():
    return bool(bpy.app.online_access)


def opened(url):
    _state['requests'] += 1
    opener = urllib.request.build_opener(GuardedRedirect())
    return opener.open(urllib.request.Request(url, headers={'User-Agent': 'Devil Painter'}), timeout=TIMEOUT)


def requests():
    return _state['requests']


def slug(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'pack'


def allowed(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip():
        return False
    url, digest = entry.get('downloadUrl'), entry.get('sha256')
    if not isinstance(url, str) or not isinstance(digest, str) or not SHA_PATTERN.match(digest.lower()):
        return False
    parts = urllib.parse.urlsplit(url)
    return url.startswith(RELEASE_PREFIX) and not parts.query and not parts.fragment and '..' not in parts.path and '\\' not in url


def cached():
    path = packs_folder() / CATALOG_FILE
    if _state['catalog'] is None and path.is_file():
        _state['catalog'] = json.loads(path.read_text(encoding='utf-8'))
    return _state['catalog'] or []


def catalog():
    return [entry for entry in cached() if allowed(entry)]


def refresh():
    if not online():
        _state['error'] = 'Online access is off, so packs are unavailable.'
        return _state['error']
    try:
        with opened(CATALOG_URL) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError) as error:
        _state['error'] = f'Could not read the pack catalog: {getattr(error, "reason", error)}.'
        return _state['error']
    entries = [entry for entry in data.get('packs', []) if allowed(entry)] if isinstance(data, dict) else []
    _state['catalog'], _state['error'] = entries, ''
    (packs_folder() / CATALOG_FILE).write_text(json.dumps(entries, indent=1), encoding='utf-8')
    return f'{len(entries)} pack{"s" if len(entries) != 1 else ""} available.'


def folder_of(entry):
    return packs_folder() / slug(entry['name'])


def installed(entry):
    marker = folder_of(entry) / PACK_MARKER
    return marker.is_file() and marker.read_text(encoding='utf-8').strip() == entry['sha256'].lower()


def status(entry):
    job = _jobs.get(entry['name'])
    if job is not None and job['state'] == 'downloading':
        total = job['total'] or 1
        return f'Downloading {min(99, int(job["received"] * 100 / total))}%'
    if job is not None and job['state'] == 'failed':
        return job['message']
    if installed(entry):
        return 'Installed'
    return entry.get('size', '') if online() else 'Unavailable offline'


def busy():
    return any(job['state'] in {'downloading', 'downloaded'} for job in _jobs.values())


def fetch(job, url, path):
    try:
        with opened(url) as response, open(path, 'wb') as target:
            job['total'] = int(response.headers.get('Content-Length') or 0)
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                job['received'] += len(chunk)
                if job['received'] > MAX_PACK_BYTES:
                    raise OSError('the pack is larger than allowed')
                target.write(chunk)
        job['state'] = 'downloaded'
    except (urllib.error.URLError, OSError, ValueError) as error:
        path.unlink(missing_ok=True)
        job.update(state='failed', message=f'Download failed: {getattr(error, "reason", error)}')


def download(entry):
    if not online():
        return 'Online access is off, so packs cannot be downloaded.'
    if not allowed(entry) or entry not in catalog():
        return 'That pack is not in the Devil Painter catalog.'
    if busy():
        return 'Another pack is still downloading.'
    staging = packs_folder() / 'downloads'
    staging.mkdir(exist_ok=True)
    path = staging / (slug(entry['name']) + '.zip')
    job = dict(state='downloading', received=0, total=0, message='', path=path, entry=dict(entry))
    _jobs[entry['name']] = job
    threading.Thread(target=fetch, args=(job, entry['downloadUrl'], path), daemon=True).start()
    return f'Downloading {entry["name"]}.'


def digest(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_members(archive):
    for member in archive.infolist():
        name = PurePosixPath(member.filename.replace('\\', '/'))
        if member.is_dir() or name.is_absolute() or '..' in name.parts or ':' in member.filename:
            continue
        if name.suffix.lower() in DATA_SUFFIXES:
            yield member, name


def unpack(path, target):
    temporary = target.with_name(target.name + '.partial')
    shutil.rmtree(temporary, ignore_errors=True)
    with zipfile.ZipFile(path) as archive:
        for member, name in safe_members(archive):
            parts = name.parts[1:] if len(name.parts) > 1 else name.parts
            destination = temporary.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(destination, 'wb') as written:
                shutil.copyfileobj(source, written)
    shutil.rmtree(target, ignore_errors=True)
    temporary.rename(target)


def finish(job):
    entry, path = job['entry'], job['path']
    if digest(path) != entry['sha256'].lower():
        path.unlink(missing_ok=True)
        job.update(state='failed', message='Refused: the download does not match its checksum', reported=True)
        return f'{entry["name"]} was refused because its checksum does not match. Nothing was installed.'
    target = folder_of(entry)
    try:
        unpack(path, target)
    except (zipfile.BadZipFile, OSError) as error:
        job.update(state='failed', message=f'Could not unpack: {error}', reported=True)
        return f'{entry["name"]} could not be unpacked.'
    finally:
        path.unlink(missing_ok=True)
    (target / PACK_MARKER).write_text(entry['sha256'].lower(), encoding='utf-8')
    job.update(state='installed', message='Installed')
    rescan()
    return f'Installed {entry["name"]}. Its textures and alphas are in the shelf.'


def poll():
    messages = []
    for job in _jobs.values():
        if job['state'] == 'downloaded':
            messages.append(finish(job))
        elif job['state'] == 'failed' and not job.get('reported'):
            job['reported'] = True
            messages.append(f'{job["entry"]["name"]}: {job["message"]}.')
    return messages


def remove(entry):
    shutil.rmtree(folder_of(entry), ignore_errors=True)
    _jobs.pop(entry['name'], None)
    rescan()
    return f'Removed {entry["name"]}.'


def message():
    if not online():
        return 'Online access is off in Preferences > System, so packs are unavailable. Everything else works offline.'
    if _state['error']:
        return _state['error']
    return '' if cached() else 'Click Check for packs to see the free Devil Painter packs.'
