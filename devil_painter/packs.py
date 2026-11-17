import hashlib
import json
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
import bpy
import numpy
from .library import PACK_MARKER, library_root, packs_folder, rescan

CATALOG_URL = 'https://artbyo3.github.io/DEVIL-PAINTER_Asset_Library/packs.json'
PAGES_PREFIX = 'https://artbyo3.github.io/DEVIL-PAINTER_Asset_Library/'
RELEASE_PREFIX = 'https://github.com/Artbyo3/DEVIL-PAINTER_Asset_Library/releases/download/'
REDIRECT_HOSTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}
DATA_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.exr', '.webp', '.svg', '.json'}
KIND_FOLDERS = (('alpha', 'Alphas'), ('material', 'Materials'), ('brush', 'Brushes'), ('generator', 'Generators'), ('texture', 'Textures'))
CHUNK = 1 << 16
TIMEOUT = 60
MAX_PACK_BYTES = 4 << 30
MAX_FILE_BYTES = 64 << 20
MAX_PREVIEW_BYTES = 1 << 20
SHA_PATTERN = re.compile(r'^[0-9a-f]{64}$')
NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
THUMB_PATTERN = re.compile(r'^thumbs/[A-Za-z0-9._-]+/[A-Za-z0-9][A-Za-z0-9._-]*\.webp$')
CATALOG_FILE = 'catalog.json'
_state = dict(catalog=None, error='', requests=0, open='', previews=None)
_jobs = {}
_preview_queue = []
_preview_done = []
_preview_failed = set()
_preview_worker = dict(thread=None)


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
    url, expected = entry.get('downloadUrl'), entry.get('sha256')
    if not isinstance(url, str) or not isinstance(expected, str) or not SHA_PATTERN.match(expected.lower()):
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
    browse()
    return f'{len(entries)} pack{"s" if len(entries) != 1 else ""} available.'


def browse():
    return request_previews([(entry, first_file(entry)) for entry in catalog() if first_file(entry)])


def folder_of(entry):
    return packs_folder() / slug(entry['name'])


def installed(entry):
    marker = folder_of(entry) / PACK_MARKER
    return marker.is_file() and marker.read_text(encoding='utf-8').strip() == entry['sha256'].lower()


def files(entry):
    names = entry.get('files')
    return [name for name in names if isinstance(name, str) and NAME_PATTERN.match(name)] if isinstance(names, list) else []


def release_tag(entry):
    tag = entry.get('releaseTag')
    if isinstance(tag, str) and NAME_PATTERN.match(tag) and entry['downloadUrl'].startswith(RELEASE_PREFIX + tag + '/'):
        return tag
    return ''


def file_url(entry, name):
    tag = release_tag(entry)
    return RELEASE_PREFIX + tag + '/' + name if tag and name in files(entry) else ''


def file_hash(entry, name):
    hashes = entry.get('fileHashes')
    value = hashes.get(name) if isinstance(hashes, dict) else None
    return value.lower() if isinstance(value, str) and SHA_PATTERN.match(value.lower()) else ''


def kind_folder(entry, name):
    tags = entry.get('fileTags', {}).get(name, []) if isinstance(entry.get('fileTags'), dict) else []
    words = [tag.lower() for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
    folder = next((folder for kind, folder in KIND_FOLDERS if kind in words), '')
    return folder or ('Alphas' if 'alpha' in entry['name'].lower() else 'Textures')


def file_path(entry, name):
    return folder_of(entry) / kind_folder(entry, name) / name


def key_of(entry, name=''):
    return entry['name'] + ('/' + name if name else '')


def job_status(key):
    job = _jobs.get(key)
    if job is None:
        return ''
    if job['state'] == 'downloading':
        return f'Downloading {min(99, int(job["received"] * 100 / (job["total"] or 1)))}%'
    return job['message'] if job['state'] == 'failed' else ''


def status(entry):
    running = job_status(key_of(entry))
    if running:
        return running
    if installed(entry):
        return 'Installed'
    return entry.get('size', '') if online() else 'Unavailable offline'


def file_status(entry, name):
    running = job_status(key_of(entry, name))
    if running:
        return running
    if file_path(entry, name).is_file():
        return 'Installed'
    return '' if online() else 'Offline'


def busy():
    return any(job['state'] in {'downloading', 'downloaded'} for job in _jobs.values())


def fetch(job, url, path, limit):
    try:
        with opened(url) as response, open(path, 'wb') as target:
            job['total'] = int(response.headers.get('Content-Length') or 0)
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                job['received'] += len(chunk)
                if job['received'] > limit:
                    raise OSError('the download is larger than allowed')
                target.write(chunk)
        job['state'] = 'downloaded'
    except (urllib.error.URLError, OSError, ValueError) as error:
        path.unlink(missing_ok=True)
        job.update(state='failed', message=f'Download failed: {getattr(error, "reason", error)}')


def start(key, entry, url, path, expected, limit, name=''):
    job = dict(state='downloading', received=0, total=0, message='', path=path, entry=dict(entry), name=name, sha=expected)
    _jobs[key] = job
    threading.Thread(target=fetch, args=(job, url, path, limit), daemon=True).start()


def staging():
    folder = packs_folder() / 'downloads'
    folder.mkdir(exist_ok=True)
    return folder


def download(entry):
    if not online():
        return 'Online access is off, so packs cannot be downloaded.'
    if not allowed(entry) or entry not in catalog():
        return 'That pack is not in the Devil Painter catalog.'
    if busy():
        return 'Another download is still running.'
    start(key_of(entry), entry, entry['downloadUrl'], staging() / (slug(entry['name']) + '.zip'), entry['sha256'].lower(), MAX_PACK_BYTES)
    return f'Downloading {entry["name"]}.'


def download_file(entry, name):
    if not online():
        return 'Online access is off, so files cannot be downloaded.'
    if not allowed(entry) or entry not in catalog() or name not in files(entry):
        return 'That file is not in the Devil Painter catalog.'
    url, expected = file_url(entry, name), file_hash(entry, name)
    if not url:
        return f'{name} has no download address in its pack.'
    if not expected:
        return f'Refused {name}: the catalog has no checksum for it. Download the whole pack instead.'
    if busy():
        return 'Another download is still running.'
    start(key_of(entry, name), entry, url, staging() / (slug(entry['name']) + '__' + name), expected, MAX_FILE_BYTES, name)
    return f'Downloading {name}.'


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
    entry, path, name = job['entry'], job['path'], job['name']
    label = name or entry['name']
    if digest(path) != job['sha']:
        path.unlink(missing_ok=True)
        job.update(state='failed', message='Refused: the download does not match its checksum', reported=True)
        return f'{label} was refused because its checksum does not match. Nothing was installed.'
    if name:
        target = file_path(entry, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        job.update(state='installed', message='Installed')
        rescan()
        return f'Installed {name} from {entry["name"]}. It is in the shelf.'
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
    return f'Installed {entry["name"]}. Its assets are in the shelf.'


def preview_folder():
    folder = library_root() / 'pack_previews'
    folder.mkdir(exist_ok=True)
    return folder


def thumb_url(entry, name):
    thumbs = entry.get('thumbs')
    relative = thumbs.get(name) if isinstance(thumbs, dict) else None
    tag = release_tag(entry)
    if not isinstance(relative, str) or not THUMB_PATTERN.match(relative) or not tag or not relative.startswith(f'thumbs/{tag}/'):
        return ''
    return PAGES_PREFIX + relative


def first_file(entry):
    return next((name for name in files(entry) if thumb_url(entry, name)), '')


def preview_file(entry, name):
    return preview_folder() / release_tag(entry) / (Path(name).stem + '.png')


def ready_previews():
    if _state['previews'] is None:
        _state['previews'] = {str(path) for path in preview_folder().rglob('*.png')}
    return _state['previews']


def preview(entry, name):
    if not online() or not name:
        return ''
    path = str(preview_file(entry, name))
    return path if path in ready_previews() else ''


def fetch_previews():
    while _preview_queue:
        if not online():
            _preview_queue.clear()
            break
        url, webp = _preview_queue.pop(0)
        try:
            with opened(url) as response:
                data = response.read(MAX_PREVIEW_BYTES + 1)
            if len(data) > MAX_PREVIEW_BYTES:
                raise OSError('preview too large')
            webp.parent.mkdir(parents=True, exist_ok=True)
            webp.write_bytes(data)
            _preview_done.append(webp)
        except (urllib.error.URLError, OSError, ValueError) as error:
            _preview_failed.add(str(webp))
    _preview_worker['thread'] = None


def request_previews(pairs):
    if not online():
        return 0
    queued = 0
    for entry, name in pairs:
        url, target = thumb_url(entry, name), preview_file(entry, name)
        webp = target.with_suffix('.webp')
        if not url or str(target) in ready_previews() or str(webp) in _preview_failed or any(item[1] == webp for item in _preview_queue):
            continue
        _preview_queue.append((url, webp))
        queued += 1
    if _preview_queue and _preview_worker['thread'] is None:
        _preview_worker['thread'] = threading.Thread(target=fetch_previews, daemon=True)
        _preview_worker['thread'].start()
    return queued


def convert_previews():
    while _preview_done:
        webp = _preview_done.pop(0)
        target = webp.with_suffix('.png')
        made = []
        try:
            source = bpy.data.images.load(str(webp))
            made.append(source)
            width, height = source.size
            if not width or not height:
                raise RuntimeError('empty preview')
            values = numpy.empty(width * height * 4, dtype=numpy.float32)
            source.pixels.foreach_get(values)
            copy = bpy.data.images.new(target.stem, width, height, alpha=True)
            made.append(copy)
            copy.pixels.foreach_set(values)
            copy.filepath_raw, copy.file_format = str(target), 'PNG'
            copy.save()
            ready_previews().add(str(target))
        except RuntimeError:
            _preview_failed.add(str(webp))
        finally:
            for image in made:
                bpy.data.images.remove(image)
            webp.unlink(missing_ok=True)


def poll():
    messages = []
    convert_previews()
    for job in _jobs.values():
        if job['state'] == 'downloaded':
            messages.append(finish(job))
        elif job['state'] == 'failed' and not job.get('reported'):
            job['reported'] = True
            messages.append(f'{job["name"] or job["entry"]["name"]}: {job["message"]}.')
    return messages


def active():
    return busy() or bool(_preview_queue) or _preview_worker['thread'] is not None or bool(_preview_done)


def open_pack(entry):
    _state['open'] = entry['name'] if entry is not None else ''
    if entry is not None:
        request_previews([(entry, name) for name in files(entry)])


def open_entry():
    return next((entry for entry in catalog() if entry['name'] == _state['open']), None)


def remove(entry):
    shutil.rmtree(folder_of(entry), ignore_errors=True)
    for key in [key for key in _jobs if key == entry['name'] or key.startswith(entry['name'] + '/')]:
        _jobs.pop(key)
    rescan()
    return f'Removed {entry["name"]}.'


def message():
    if not online():
        return 'Online access is off in Preferences > System, so packs are unavailable. Everything else works offline.'
    if _state['error']:
        return _state['error']
    return '' if cached() else 'Click Check for packs to see the free Devil Painter packs.'
