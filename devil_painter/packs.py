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
import imbuf
from .library import PACK_MARKER, library_folder, packs_folder, rescan
from .thumbnails import wait_idle

CATALOG_URL = 'https://artbyo3.github.io/DEVIL-PAINTER_Asset_Library/packs.json'
PAGES_PREFIX = 'https://artbyo3.github.io/DEVIL-PAINTER_Asset_Library/'
RELEASE_PREFIX = 'https://github.com/Artbyo3/DEVIL-PAINTER_Asset_Library/releases/download/'
RELEASE_PATH = urllib.parse.urlsplit(RELEASE_PREFIX).path
RELEASE_REDIRECT_HOSTS = frozenset({'objects.githubusercontent.com', 'release-assets.githubusercontent.com'})
DATA_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.exr', '.webp', '.svg', '.json'}
IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.exr', '.webp'})
KIND_FOLDERS = (('alpha', 'Alphas'), ('material', 'Materials'), ('brush', 'Brushes'), ('generator', 'Generators'), ('texture', 'Textures'))
KIND_SUFFIXES = dict(Alphas=IMAGE_SUFFIXES, Textures=IMAGE_SUFFIXES, Materials=frozenset({'.blend'}), Brushes=frozenset({'.json'}),
                     Generators=frozenset({'.json'}))
CHUNK = 1 << 16
TIMEOUT = 60
MAX_PACK_BYTES = 4 << 30
MAX_FILE_BYTES = 64 << 20
MAX_PREVIEW_BYTES = 1 << 20
MAX_UNPACKED_BYTES = 8 << 30
MAX_PREVIEW_SIDE = 4096
DECODE_ROUNDS = 8
PREVIEW_FETCHERS = 4
SHA_PATTERN = re.compile(r'^[0-9a-f]{64}$')
NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
TAG_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
THUMB_PATTERN = re.compile(r'^thumbs/[A-Za-z0-9._-]+/[A-Za-z0-9][A-Za-z0-9._-]*\.webp$')
CATALOG_FILE = 'catalog.json'
_state = dict(catalog=None, error='', requests=0, open='', previews=None, verified=False, checking=None, fetched=None)
_preview_lock = threading.Lock()
_jobs = {}
_preview_queue = []
_preview_waiting = set()
_preview_failed = set()
_preview_worker = dict(running=0)


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, request, response, code, message, headers, url):
        target = urllib.parse.urlsplit(url)
        if target.scheme != 'https' or target.hostname not in self.hosts or target.username or target.password or target.port not in (None, 443):
            raise urllib.error.URLError(f'refused redirect to {target.hostname}')
        return super().redirect_request(request, response, code, message, headers, url)


def online():
    return bool(bpy.app.online_access)


def redirect_hosts(url):
    if url == CATALOG_URL or (url.startswith(PAGES_PREFIX + 'thumbs/') and THUMB_PATTERN.match(url[len(PAGES_PREFIX):])):
        return frozenset()
    if release_parts(url) is not None:
        return RELEASE_REDIRECT_HOSTS
    return None


def opener_for(url):
    hosts = redirect_hosts(url)
    if hosts is None:
        raise urllib.error.URLError('refused an address outside the Devil Painter library')
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), GuardedRedirect(hosts))


def opened(url):
    opener = opener_for(url)
    _state['requests'] += 1
    return opener.open(urllib.request.Request(url, headers={'User-Agent': 'Devil Painter'}), timeout=TIMEOUT)


def requests():
    return _state['requests']


def slug(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'pack'


def decoded(text):
    for _ in range(DECODE_ROUNDS):
        plain = urllib.parse.unquote(text)
        if plain == text:
            return text
        text = plain
    return None


def safe_segment(segment, pattern):
    return bool(pattern.match(segment)) and '..' not in segment


def release_parts(url):
    if not isinstance(url, str) or '\\' in url:
        return None
    parts = urllib.parse.urlsplit(url)
    path = decoded(parts.path)
    if (parts.scheme != 'https' or parts.netloc != 'github.com' or parts.query or parts.fragment or path is None or '\\' in path
            or '..' in path or not path.startswith(RELEASE_PATH)):
        return None
    segments = path[len(RELEASE_PATH):].split('/')
    if len(segments) != 2 or not safe_segment(segments[0], TAG_PATTERN) or not safe_segment(segments[1], NAME_PATTERN):
        return None
    if url != RELEASE_PREFIX + segments[0] + '/' + segments[1]:
        return None
    return segments[0], segments[1]


def allowed(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip():
        return False
    expected, tag = entry.get('sha256'), entry.get('releaseTag')
    if not isinstance(expected, str) or not SHA_PATTERN.match(expected.lower()):
        return False
    parts = release_parts(entry.get('downloadUrl'))
    return parts is not None and isinstance(tag, str) and safe_segment(tag, TAG_PATTERN) and parts[0] == tag


def cached():
    path = packs_folder() / CATALOG_FILE
    if _state['catalog'] is None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            loaded = []
        _state['catalog'] = loaded if isinstance(loaded, list) else []
    return _state['catalog'] or []


def catalog():
    entries = cached()
    if _state.get('checked') is not entries:
        _state['checked'], _state['allowed'] = entries, [entry for entry in entries if allowed(entry)]
    return _state['allowed']


def refresh():
    _state['verified'] = False
    if not online():
        _state['error'] = 'Online access is off, so packs are unavailable.'
        return _state['error']
    if _state['checking'] is None:
        _state['checking'] = threading.Thread(target=fetch_catalog, args=(CATALOG_URL,), daemon=True)
        _state['checking'].start()
    return 'Checking for packs.'


def fetch_catalog(url):
    try:
        with opened(url) as response:
            _state['fetched'] = ('data', json.loads(response.read().decode('utf-8')))
    except (urllib.error.URLError, OSError, ValueError) as error:
        _state['fetched'] = ('error', getattr(error, 'reason', error))


def finish_refresh():
    outcome, value = _state['fetched']
    _state['fetched'], _state['checking'] = None, None
    if outcome == 'error' or not online():
        _state['error'] = f'Could not read the pack catalog: {value if outcome == "error" else "online access is off"}. Downloads stay off until Check for packs succeeds.'
        return _state['error']
    listed = value.get('packs', []) if isinstance(value, dict) else []
    entries = [entry for entry in listed if allowed(entry)] if isinstance(listed, list) else []
    _state['catalog'], _state['error'], _state['verified'] = entries, '', True
    (packs_folder() / CATALOG_FILE).write_text(json.dumps(entries, indent=1), encoding='utf-8')
    browse()
    return f'{len(entries)} pack{"s" if len(entries) != 1 else ""} available.'


def browse():
    return request_previews([(entry, first_file(entry)) for entry in catalog() if first_file(entry)])


def folder_name(entry):
    name = slug(entry['name'])
    if any(other['name'] != entry['name'] and slug(other['name']) == name for other in catalog()):
        name += '_' + hashlib.sha256(entry['name'].encode('utf-8')).hexdigest()[:8]
    return name


def folder_of(entry):
    return packs_folder() / folder_name(entry)


def installed(entry):
    marker = folder_of(entry) / PACK_MARKER
    return marker.is_file() and marker.read_text(encoding='utf-8').strip() == entry['sha256'].lower()


def files(entry):
    names = entry.get('files')
    return [name for name in names if isinstance(name, str) and NAME_PATTERN.match(name)] if isinstance(names, list) else []


def release_tag(entry):
    return entry['releaseTag'] if any(item is entry for item in catalog()) or allowed(entry) else ''


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


def kind_matches(entry, name):
    return Path(name).suffix.lower() in KIND_SUFFIXES[kind_folder(entry, name)]


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


def unverified():
    return '' if _state['verified'] else 'Click Check for packs first: downloads stay off until the catalog is confirmed online.'


def download(entry):
    if not online():
        return 'Online access is off, so packs cannot be downloaded.'
    if unverified():
        return unverified()
    if not allowed(entry) or entry not in catalog():
        return 'That pack is not in the Devil Painter catalog.'
    if busy():
        return 'Another download is still running.'
    start(key_of(entry), entry, entry['downloadUrl'], staging() / (folder_name(entry) + '.zip'), entry['sha256'].lower(), MAX_PACK_BYTES)
    return f'Downloading {entry["name"]}.'


def download_file(entry, name):
    if not online():
        return 'Online access is off, so files cannot be downloaded.'
    if unverified():
        return unverified()
    if not allowed(entry) or entry not in catalog() or name not in files(entry):
        return 'That file is not in the Devil Painter catalog.'
    if not kind_matches(entry, name):
        return f'Refused {name}: its file type does not match the {kind_folder(entry, name).lower()} the catalog lists it as.'
    url, expected = file_url(entry, name), file_hash(entry, name)
    if not url:
        return f'{name} has no download address in its pack.'
    if not expected:
        return f'Refused {name}: the catalog has no checksum for it. Download the whole pack instead.'
    if busy():
        return 'Another download is still running.'
    start(key_of(entry, name), entry, url, staging() / (folder_name(entry) + '__' + name), expected, MAX_FILE_BYTES, name)
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
    try:
        with zipfile.ZipFile(path) as archive:
            members = list(safe_members(archive))
            if sum(member.file_size for member, _ in members) > MAX_UNPACKED_BYTES:
                raise OSError('the pack unpacks to more than allowed')
            written_bytes = 0
            for member, name in members:
                parts = name.parts[1:] if len(name.parts) > 1 else name.parts
                destination = temporary.joinpath(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(destination, 'wb') as written:
                    for chunk in iter(lambda: source.read(CHUNK), b''):
                        written_bytes += len(chunk)
                        if written_bytes > MAX_UNPACKED_BYTES:
                            raise OSError('the pack unpacks to more than allowed')
                        written.write(chunk)
    except (zipfile.BadZipFile, OSError):
        shutil.rmtree(temporary, ignore_errors=True)
        raise
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
        if not kind_matches(entry, name):
            path.unlink(missing_ok=True)
            job.update(state='failed', message='Refused: the file type does not match its kind', reported=True)
            return f'{name} was refused because its file type does not match its kind. Nothing was installed.'
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
    return library_folder('pack_previews')


def thumb_url(entry, name):
    thumbs = entry.get('thumbs')
    relative = thumbs.get(name) if isinstance(thumbs, dict) else None
    tag = release_tag(entry)
    if not isinstance(relative, str) or not THUMB_PATTERN.match(relative) or not tag or not relative.startswith(f'thumbs/{tag}/'):
        return ''
    return PAGES_PREFIX + relative


def thumb_hash(entry, name):
    hashes = entry.get('thumbHashes')
    value = hashes.get(name) if isinstance(hashes, dict) else None
    return value.lower() if isinstance(value, str) and SHA_PATTERN.match(value.lower()) else ''


def webp_size(header):
    if len(header) < 30 or header[:4] != b'RIFF' or header[8:12] != b'WEBP':
        return None
    chunk = header[12:16]
    if chunk == b'VP8X':
        return 1 + int.from_bytes(header[24:27], 'little'), 1 + int.from_bytes(header[27:30], 'little')
    if chunk == b'VP8 ' and header[23:26] == bytes((0x9D, 0x01, 0x2A)):
        return int.from_bytes(header[26:28], 'little') & 0x3FFF, int.from_bytes(header[28:30], 'little') & 0x3FFF
    if chunk == b'VP8L' and header[20] == 0x2F:
        bits = int.from_bytes(header[21:25], 'little')
        return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
    return None


def preview_dimensions_ok(path):
    with open(path, 'rb') as source:
        size = webp_size(source.read(30))
    return size is not None and 0 < size[0] <= MAX_PREVIEW_SIDE and 0 < size[1] <= MAX_PREVIEW_SIDE


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
    while True:
        with _preview_lock:
            if not _preview_queue or not online():
                if not online():
                    _preview_queue.clear()
                    _preview_waiting.clear()
                _preview_worker['running'] -= 1
                return
            url, webp, expected = _preview_queue.pop(0)
            _preview_waiting.discard(str(webp))
        try:
            with opened(url) as response:
                data = response.read(MAX_PREVIEW_BYTES + 1)
            if len(data) > MAX_PREVIEW_BYTES:
                raise OSError('preview too large')
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise OSError('preview does not match its checksum')
            webp.parent.mkdir(parents=True, exist_ok=True)
            webp.write_bytes(data)
            converted = convert_preview(webp)
        except (urllib.error.URLError, OSError, ValueError):
            converted = False
        with _preview_lock:
            if converted:
                ready_previews().add(str(webp.with_suffix('.png')))
            else:
                _preview_failed.add(str(webp))


def request_previews(pairs):
    if not online():
        return 0
    queued = 0
    with _preview_lock:
        for entry, name in pairs:
            url, target = thumb_url(entry, name), preview_file(entry, name)
            webp = target.with_suffix('.webp')
            if not url or str(target) in ready_previews() or str(webp) in _preview_failed or str(webp) in _preview_waiting:
                continue
            _preview_queue.append((url, webp, thumb_hash(entry, name)))
            _preview_waiting.add(str(webp))
            queued += 1
        while _preview_queue and _preview_worker['running'] < min(PREVIEW_FETCHERS, len(_preview_queue)):
            _preview_worker['running'] += 1
            threading.Thread(target=fetch_previews, daemon=True).start()
    return queued


def focus_previews(pairs):
    wanted = {str(preview_file(entry, name).with_suffix('.webp')) for entry, name in pairs if name}
    with _preview_lock:
        if not wanted & _preview_waiting or all(str(item[1]) in wanted for item in _preview_queue[:len(wanted & _preview_waiting)]):
            return
        _preview_queue.sort(key=lambda item: str(item[1]) not in wanted)


def convert_preview(webp):
    try:
        if not preview_dimensions_ok(webp):
            return False
        wait_idle()
        buffer = imbuf.load(str(webp))
        width, height = buffer.size
        if not width or not height:
            return False
        buffer.file_type = 'PNG'
        imbuf.write(buffer, filepath=str(webp.with_suffix('.png')))
        buffer.free()
        return True
    except (OSError, ValueError, RuntimeError):
        return False
    finally:
        webp.unlink(missing_ok=True)


def poll():
    messages = [finish_refresh()] if _state['fetched'] is not None else []
    for job in _jobs.values():
        if job['state'] == 'downloaded':
            messages.append(finish(job))
        elif job['state'] == 'failed' and not job.get('reported'):
            job['reported'] = True
            messages.append(f'{job["name"] or job["entry"]["name"]}: {job["message"]}.')
    return messages


def active():
    with _preview_lock:
        return (busy() or bool(_preview_queue) or _preview_worker['running'] > 0 or _state['checking'] is not None
                or _state['fetched'] is not None)


def preview_failed(entry, name):
    return bool(name) and str(preview_file(entry, name).with_suffix('.webp')) in _preview_failed


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
    if not cached():
        return 'Click Check for packs to see the free Devil Painter packs.'
    return unverified()
