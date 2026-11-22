import json
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, packs
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, keys, move, pixels, press, run_journey, settle, viewport


CONNECTIONS = []
_connect = socket.socket.connect


def counted_connect(self, address):
    CONNECTIONS.append(address)
    return _connect(self, address)


socket.socket.connect = counted_connect


def labels():
    return {control(key).label: key for key in keys('ITEM.')}


TEXTURE_PACK = 'Cloth Textures Vol. 1'
ALPHA_PACK = 'Alphas Vol. 1'


def pack_tile(name=TEXTURE_PACK):
    return next((key for key in keys('ITEM.') if control(key).label.startswith(name + ' ')), None)


def entry_named(name):
    return next(item for item in packs.catalog() if item['name'] == name)


def set_online(enabled):
    bpy.context.preferences.system.use_online_access = enabled
    return bool(bpy.app.online_access) == enabled


def wait_for(condition, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        yield from settle()
    return condition()


def drag(window, x, y, dx, dy, count=8):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, count + 1):
        move(window, x + dx * step / count, y + dy * step / count)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def file_tile(stem):
    return next((key for key in keys('ITEM.') if control(key).label == stem or control(key).label.startswith(stem + ' ')), None)


def redirect_allowed(source, target):
    guard = next(handler for handler in packs.opener_for(source).handlers if isinstance(handler, packs.GuardedRedirect))
    try:
        return guard.redirect_request(urllib.request.Request(source), None, 302, 'Found', {}, target) is not None
    except urllib.error.URLError:
        return False


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    shutil.rmtree(library.library_root() / 'packs', ignore_errors=True)
    library._cache.clear()
    packs._state.update(catalog=None, error='')
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    check(set_online(False), 'online access is turned off in the preferences')
    before = len(CONNECTIONS)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = cube.devil_painter.sets[0]
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    check('Online access is off' in control('PACKS_INFO').label and not keys('ITEM.'), 'offline, the packs tab says packs are unavailable')
    click(window, region, 'PACKS_REFRESH')
    yield from settle()
    check('Online access is off' in editor._active.message, 'Check for packs refuses to go online')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    click(window, region, labels()['Steel'])
    yield from settle()
    click(window, region, 'ADD_PAINT')
    yield from settle()
    offline_uid = active_layer(data).uid
    rect = region.x + region.width * .45, region.y + region.height * .5
    drag(window, *rect, 30, 10)
    yield from settle()
    check(active_layer(data).uid == offline_uid and (pixels(find_layer(data, offline_uid).image)[:, 3] > .5).sum() > 0
          and any(layer.name == 'Steel' for layer in data.layers), 'offline, fill layers and painting keep working')
    check(len(CONNECTIONS) == before and packs.requests() == 0, 'offline, the add-on makes zero network attempts')

    check(set_online(True), 'online access is turned on in the preferences')
    os.environ['HTTPS_PROXY'] = os.environ['HTTP_PROXY'] = 'http://127.0.0.1:9'
    forged = dict(name=TEXTURE_PACK, description='', size='1 KB', releaseTag='cloth-textures-vol1-v1.0.0', sha256='f' * 64,
                  downloadUrl=packs.RELEASE_PREFIX + 'cloth-textures-vol1-v1.0.0/Cloth_Textures_Vol1.zip', files=[], tags=[])
    (library.library_root() / 'packs').mkdir(parents=True, exist_ok=True)
    (library.library_root() / 'packs' / packs.CATALOG_FILE).write_text(json.dumps([forged]), encoding='utf-8')
    packs._state.update(catalog=None, verified=False)
    requested = packs.requests()
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    check(pack_tile() is not None, 'a catalog saved on disk by an earlier session still fills in the packs list')
    click(window, region, pack_tile())
    yield from settle()
    click(window, region, 'PACK_DOWNLOAD')
    yield from settle()
    check('Check for packs first' in editor._active.message and not packs._jobs and packs.requests() == requested,
          f'downloads from the saved catalog stay off until the catalog is confirmed online ({editor._active.message})')
    click(window, region, 'PACK_BACK')
    yield from settle()
    real_catalog = packs.CATALOG_URL
    packs.CATALOG_URL = packs.PAGES_PREFIX + 'missing-catalog.json'
    click(window, region, 'PACKS_REFRESH')
    yield from settle()
    check(editor._active.message == 'Checking for packs.' and packs.active(), 'Check for packs reads the catalog in the background without holding up the UI')
    refused = yield from wait_for(lambda: 'Downloads stay off' in editor._active.message, 20)
    packs.CATALOG_URL = real_catalog
    check(refused and 'Check for packs first' in packs.download(forged) and not packs._jobs,
          f'a failed Check for packs keeps downloads off and says so ({editor._active.message})')
    click(window, region, 'PACKS_REFRESH')
    yield from settle()
    shown = yield from wait_for(lambda: pack_tile() is not None and pack_tile(ALPHA_PACK) is not None, 20)
    check(shown and packs.requests() >= 1, f'Check for packs reads the real catalog and lists the packs ({editor._active.message})')
    entry = entry_named(TEXTURE_PACK)
    check(all(packs.allowed(item) for item in packs.catalog()) and all('thumbs' in item and 'fileHashes' in item for item in packs.catalog()),
          'every catalog entry is allowed and the extra catalog fields are read')
    check(entry['downloadUrl'].startswith(packs.RELEASE_PREFIX) and len(entry['sha256']) == 64, 'the catalog entry points at the asset library releases with a SHA-256')
    check(not packs.allowed(dict(entry, downloadUrl='https://example.com/pack.zip')) and not packs.allowed(dict(entry, sha256='')),
          'entries from another host or without a checksum are not allowed')
    check(not packs.thumb_url(dict(entry, thumbs={'boucle-tweed-01.png': 'https://example.com/x.webp'}), 'boucle-tweed-01.png')
          and not packs.file_url(entry, '../evil.png'), 'previews and files outside the library addresses are refused')
    check(packs._state['verified'], 'a successful Check for packs confirms the catalog for this session')
    check(all(item['sha256'] != forged['sha256'] for item in packs.catalog()), 'the confirmed catalog replaces the saved one, so the forged entry is gone')
    handlers = [handler for url in (packs.CATALOG_URL, entry['downloadUrl']) for handler in packs.opener_for(url).handlers]
    check(urllib.request.getproxies().get('https') and not any(isinstance(handler, urllib.request.ProxyHandler) and handler.proxies for handler in handlers)
          and packs.requests() > requested, 'library traffic ignores the dead proxy set in the environment and still reaches the catalog')
    tag = entry['releaseTag']
    hidden = [packs.RELEASE_PREFIX + tag + '/%2e%2e/%2e%2e/Evil/Repo/pack.zip', packs.RELEASE_PREFIX + tag + '/%252e%252e/pack.zip',
              packs.RELEASE_PREFIX + tag + '/.%2E/pack.zip', packs.RELEASE_PREFIX + '%2e%2e%2f%2e%2e%2fEvil/pack.zip',
              packs.RELEASE_PREFIX + tag + '/%25252e%25252e/pack.zip']
    check(not any(packs.allowed(dict(entry, downloadUrl=url)) for url in hidden), 'download addresses hiding .. behind percent-encoding are refused')
    foreign = ['https://github.com/Evil/Repo/releases/download/' + tag + '/Cloth_Textures_Vol1.zip', packs.RELEASE_PREFIX + 'other-tag/Cloth_Textures_Vol1.zip',
               'https://github.com/Artbyo3/DEVIL-PAINTER_Asset_Library.evil/releases/download/' + tag + '/pack.zip',
               'https://github.com:8443/Artbyo3/DEVIL-PAINTER_Asset_Library/releases/download/' + tag + '/pack.zip']
    check(not any(packs.allowed(dict(entry, downloadUrl=url)) for url in foreign) and not packs.allowed(dict(entry, releaseTag='../' + tag)),
          'foreign repositories, other ports, and download tags that differ from the release tag are refused')
    before_requests = packs.requests()
    try:
        packs.opened('https://github.com/Evil/Repo/releases/download/' + tag + '/pack.zip')
        refused_open = False
    except urllib.error.URLError:
        refused_open = True
    check(refused_open and packs.requests() == before_requests, 'an address outside the library is refused before any request is made')
    thumb = packs.thumb_url(entry, 'boucle-tweed-01.png')
    check(not redirect_allowed(packs.CATALOG_URL, 'https://evil.example/packs.json') and not redirect_allowed(packs.CATALOG_URL, entry['downloadUrl'])
          and not redirect_allowed(thumb, 'https://evil.example/boucle.webp'), 'the catalog and preview host may not redirect anywhere')
    check(redirect_allowed(entry['downloadUrl'], 'https://release-assets.githubusercontent.com/asset')
          and redirect_allowed(entry['downloadUrl'], 'https://objects.githubusercontent.com/asset')
          and not redirect_allowed(entry['downloadUrl'], 'https://github.com/Evil/Repo/releases/download/' + tag + '/pack.zip')
          and not redirect_allowed(entry['downloadUrl'], 'https://evil.example/pack.zip')
          and not redirect_allowed(entry['downloadUrl'], 'http://objects.githubusercontent.com/asset'),
          'release downloads redirect only to GitHub release storage over https')
    staging = library.library_root() / 'packs' / 'downloads'
    entry['files'].append('evil-shirt.blend')
    entry['fileHashes']['evil-shirt.blend'] = 'a' * 64
    entry['fileTags']['evil-shirt.blend'] = ['texture']
    refusal = packs.download_file(entry, 'evil-shirt.blend')
    check('does not match' in refusal and packs.key_of(entry, 'evil-shirt.blend') not in packs._jobs and not packs.file_path(entry, 'evil-shirt.blend').exists(),
          f'a texture entry offering a .blend file is refused before anything is downloaded ({refusal})')
    staging.mkdir(parents=True, exist_ok=True)
    smuggled = staging / 'smuggled.blend'
    smuggled.write_bytes(b'BLENDER-v504')
    note = packs.finish(dict(entry=entry, path=smuggled, name='evil-shirt.blend', sha=packs.digest(smuggled), state='downloaded'))
    check('refused' in note and not smuggled.exists() and not packs.file_path(entry, 'evil-shirt.blend').exists(),
          'a downloaded file whose type does not match its kind is deleted, never installed')
    entry['fileTags']['evil-shirt.blend'] = ['material']
    check(packs.kind_matches(entry, 'evil-shirt.blend') and packs.file_path(entry, 'evil-shirt.blend').parent.name == 'Materials'
          and not packs.kind_matches(dict(entry, fileTags={'boucle-tweed-01.png': ['material']}), 'boucle-tweed-01.png'),
          'material .blend files belong only in Materials, and a material entry may not deliver an image')
    entry['files'].remove('evil-shirt.blend')
    del entry['fileHashes']['evil-shirt.blend']
    del entry['fileTags']['evil-shirt.blend']
    huge = packs.preview_folder() / tag / 'huge-test.webp'
    huge.parent.mkdir(parents=True, exist_ok=True)
    huge.write_bytes(b'RIFF' + (22).to_bytes(4, 'little') + b'WEBP' + b'VP8X' + (10).to_bytes(4, 'little') + bytes(4)
                     + (4999).to_bytes(3, 'little') + (4999).to_bytes(3, 'little'))
    images = len(bpy.data.images)
    loads = []
    real_load = packs.imbuf.load
    packs.imbuf.load = lambda path: loads.append(path) or real_load(path)
    converted = packs.convert_preview(huge)
    packs.imbuf.load = real_load
    check(not converted and not loads and len(bpy.data.images) == images and not huge.exists() and not huge.with_suffix('.png').exists(),
          'a preview claiming 5000 x 5000 pixels is refused from its header, before anything decodes or allocates it')
    second = entry_named('Cloth Textures Vol. 2')
    probe = packs.files(second)[7]
    second['thumbHashes'] = {probe: 'f' * 64}
    packs.request_previews([(second, probe)])
    settled = yield from wait_for(lambda: not packs.active(), 30)
    probe_preview = packs.preview_file(second, probe)
    check(settled and str(probe_preview.with_suffix('.webp')) in packs._preview_failed and not probe_preview.exists(),
          'a preview that does not match its thumbHashes checksum is refused')
    del second['thumbHashes']
    bomb = staging / 'bomb.zip'
    with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('Bomb/Textures/flat.png', bytes(1 << 16))
    limit, packs.MAX_UNPACKED_BYTES = packs.MAX_UNPACKED_BYTES, 4096
    target = library.library_root() / 'packs' / 'Bomb_Test'
    try:
        packs.unpack(bomb, target)
        exploded = True
    except OSError:
        exploded = False
    finally:
        packs.MAX_UNPACKED_BYTES = limit
        bomb.unlink(missing_ok=True)
    check(not exploded and not target.exists() and not target.with_name(target.name + '.partial').exists(),
          'a pack that unpacks past the size cap is refused and leaves nothing behind')
    listed = packs._state['catalog']
    twin = dict(entry, name=TEXTURE_PACK.replace(' ', '-'))
    packs._state['catalog'] = listed + [twin]
    check(packs.folder_of(twin) != packs.folder_of(entry) and packs.folder_of(entry).name.startswith('Cloth_Textures_Vol_1_'),
          'two packs whose names slug to the same folder get separate folders')
    packs._state['catalog'] = listed
    folder = packs.folder_of(entry)
    previewed = yield from wait_for(lambda: move(window, *middle) or (pack_tile() is not None and control(pack_tile()).preview is not None), 40)
    check(previewed and not folder.exists(), 'pack previews from the library site appear before anything is downloaded')
    click(window, region, pack_tile())
    yield from settle()
    check(file_tile('boucle-tweed-01') is not None and has('PACK_DOWNLOAD') and has('PACK_BACK'), 'opening the pack lists its files next to the whole-pack download')
    files_shown = yield from wait_for(lambda: move(window, *middle) or sum(1 for key in keys('ITEM.') if control(key).preview is not None) >= 6, 60)
    check(files_shown and not folder.exists(), 'file previews appear before any file is downloaded')
    cached = list((library.library_root() / 'pack_previews' / entry['releaseTag']).glob('*.png'))
    check(len(cached) >= 6 and not any(path.with_suffix('.webp').exists() for path in cached), 'previews are converted to PNG and cached on disk')
    hashes = dict(entry['fileHashes'])
    target = packs.file_path(entry, 'boucle-tweed-01.png')
    entry['fileHashes']['boucle-tweed-01.png'] = 'f' * 64
    click(window, region, file_tile('boucle-tweed-01'))
    yield from settle()
    refused = yield from wait_for(lambda: 'refused' in editor._active.message, 120)
    check(refused and not target.exists() and not any(staging.glob('*')), 'a single file whose checksum does not match is refused and deleted')
    del entry['fileHashes']['boucle-tweed-02.png']
    click(window, region, file_tile('boucle-tweed-02'))
    yield from settle()
    check('no checksum' in editor._active.message and not packs.file_path(entry, 'boucle-tweed-02.png').exists(), 'a file without a checksum is refused before downloading')
    entry['fileHashes'].clear()
    entry['fileHashes'].update(hashes)
    packs._jobs.clear()
    click(window, region, file_tile('boucle-tweed-01'))
    yield from settle()
    single = yield from wait_for(lambda: target.is_file(), 120)
    check(single and packs.digest(target) == hashes['boucle-tweed-01.png'] and target.parent.name == 'Textures' and not packs.installed(entry),
          'one texture downloads alone, passes its checksum, and lands in the pack Textures folder')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check('boucle-tweed-01' in labels() and 'boucle-tweed-02' not in labels(), 'the single file appears in the shelf on its own')
    click(window, region, labels()['boucle-tweed-01'])
    yield from settle()
    fabric = active_layer(data)
    check(fabric.slots['base_color'].source == 'IMAGE' and fabric.slots['base_color'].image.name.startswith('boucle-tweed-01')
          and any(node.type == 'TEX_IMAGE' and node.image == fabric.slots['base_color'].image for node in data.material.node_tree.nodes),
          'the single downloaded texture paints the model as a fill layer')
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    real = entry['sha256']
    entry['sha256'] = 'f' * 64
    click(window, region, 'PACK_DOWNLOAD')
    yield from settle()
    check('Downloading' in editor._active.message, 'Download whole pack starts the download')
    refused = yield from wait_for(lambda: 'refused' in editor._active.message, 240)
    check(refused and not packs.installed(entry) and not any(staging.glob('*.zip')), 'a pack whose checksum does not match is refused and deleted, nothing is installed')
    entry['sha256'] = real
    packs._jobs.clear()
    click(window, region, 'PACK_DOWNLOAD')
    yield from settle()
    installed = yield from wait_for(lambda: packs.installed(entry), 240)
    check(installed and 'Installed' in editor._active.message, 'the real pack downloads, passes its checksum, and installs')
    check(len(list((folder / 'Textures').glob('*.png'))) == 164 and not any(staging.glob('*.zip')), 'the pack unpacks its 164 textures into the library')
    click(window, region, 'PACK_BACK')
    yield from settle()
    move(window, *middle)
    yield from settle()
    check(control(pack_tile()).label.endswith('Installed'), 'the shelf marks the pack as installed')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    names = labels()
    check('boucle-tweed-02' in names and sum(1 for name in names if name.startswith(('boucle', 'corduroy', 'denim', 'silk'))) > 20,
          'the pack textures appear in the shelf')
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    alphas_entry = entry_named(ALPHA_PACK)
    click(window, region, pack_tile(ALPHA_PACK))
    yield from settle()
    click(window, region, 'PACK_DOWNLOAD')
    yield from settle()
    done = yield from wait_for(lambda: packs.installed(alphas_entry), 120)
    check(done and len(list((packs.folder_of(alphas_entry) / 'Alphas').glob('*.png'))) == 115, 'the alphas pack downloads, passes its checksum, and installs 115 alphas')
    click(window, region, 'PACK_BACK')
    yield from settle()
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check('belt-buckle-01' not in labels(), 'alphas from a pack do not show up as textures')
    click(window, region, 'SHELF_TAB.ALPHAS')
    yield from settle()
    names = labels()
    check('belt-buckle-01' in names, 'the pack alphas appear in the alphas shelf')
    click(window, region, names['belt-buckle-01'])
    yield from settle()
    check(data.brush_alpha is not None and data.brush_alpha.name.startswith('belt-buckle-01'), 'a pack alpha becomes the brush alpha')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    stitched_uid = active_layer(data).uid
    drag(window, *rect, 40, 0)
    yield from settle()
    check((pixels(find_layer(data, stitched_uid).image)[:, 3] > .05).sum() > 0, 'painting with the pack alpha lays down paint')

    os.environ.pop('HTTPS_PROXY', None)
    os.environ.pop('HTTP_PROXY', None)
    check(set_online(False), 'online access is turned off again')
    settled = yield from wait_for(lambda: not packs.active(), 30)
    check(settled, 'turning online access off stops queued preview fetches')
    before, requested = len(CONNECTIONS), packs.requests()
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    check(pack_tile() is not None and control(pack_tile()).label.endswith('Installed') and control(pack_tile()).preview is None,
          'offline, the installed pack is still listed with a placeholder preview')
    click(window, region, pack_tile())
    yield from settle()
    check(file_tile('boucle-tweed-03') is not None and all(control(key).preview is None for key in keys('ITEM.')), 'offline, file tiles show placeholders')
    click(window, region, 'PACK_BACK')
    yield from settle()
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, labels()['boucle-tweed-03'])
    yield from settle()
    check(active_layer(data).slots['base_color'].source == 'IMAGE', 'offline, installed pack textures keep working')
    click(window, region, 'SHELF_TAB.PACKS')
    yield from settle()
    click(window, region, pack_tile(), kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, next(key for key in keys('REMOVE_PACK.')))
    yield from settle()
    check(not folder.exists() and not packs.installed(entry), 'a pack can be removed')
    check(len(CONNECTIONS) == before and packs.requests() == requested, 'offline, browsing, previews, and removal make zero network attempts')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PACK CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI pack test')
