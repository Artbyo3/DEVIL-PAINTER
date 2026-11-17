import os
import shutil
import socket
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, packs
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch

TIMEOUT = 600
STARTED = time.time()


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def finish(code):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def viewport():
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return window, area, region


def move(window, x, y):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def press(window, kind, x, y, **modifiers):
    move(window, x, y)
    window.event_simulate(type=kind, value='PRESS', x=int(x), y=int(y), **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=int(x), y=int(y), **modifiers)


def control(key):
    return next(item for item in reversed(editor._active.workspace.controls) if item.key == key)


def has(key):
    return any(item.key == key for item in editor._active.workspace.controls)


def keys(prefix):
    return [item.key for item in editor._active.workspace.controls if item.key.startswith(prefix)]


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5, **modifiers):
    press(window, kind, *spot(region, key, fx, fy), **modifiers)


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)


CONNECTIONS = []
_connect = socket.socket.connect


def counted_connect(self, address):
    CONNECTIONS.append(address)
    return _connect(self, address)


socket.socket.connect = counted_connect


def labels():
    return {control(key).label: key for key in keys('ITEM.')}


def pack_tile():
    return next((key for key in keys('ITEM.') if control(key).label.startswith('Cloth & Apparel Vol. 1')), None)


def set_online(enabled):
    bpy.context.preferences.system.use_online_access = enabled
    return bool(bpy.app.online_access) == enabled


def wait_for(condition, seconds):
    for _ in range(int(seconds / .5)):
        if condition():
            return True
        yield 0.5
    return condition()


def drag(window, x, y, dx, dy, count=8):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, count + 1):
        move(window, x + dx * step / count, y + dy * step / count)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    shutil.rmtree(library.library_root() / 'packs', ignore_errors=True)
    library._cache.clear()
    packs._state.update(catalog=None, error='')
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    check(set_online(False), 'online access is turned off in the preferences')
    before = len(CONNECTIONS)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.6
    click(window, region, 'RES.0.1024')
    yield 0.2
    click(window, region, 'START')
    yield 2.0
    data = cube.devil_painter.sets[0]
    click(window, region, 'SHELF_TAB.PACKS')
    yield 0.5
    check('Online access is off' in control('PACKS_INFO').label and not keys('ITEM.'), 'offline, the packs tab says packs are unavailable')
    click(window, region, 'PACKS_REFRESH')
    yield 0.5
    check('Online access is off' in editor._active.message, 'Check for packs refuses to go online')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield 0.4
    click(window, region, labels()['Steel'])
    yield 0.8
    click(window, region, 'ADD_PAINT')
    yield 0.8
    offline_uid = active_layer(data).uid
    rect = region.x + region.width * .45, region.y + region.height * .5
    drag(window, *rect, 30, 10)
    yield 1.2
    check(active_layer(data).uid == offline_uid and (pixels(find_layer(data, offline_uid).image)[:, 3] > .5).sum() > 0
          and any(layer.name == 'Steel' for layer in data.layers), 'offline, fill layers and painting keep working')
    check(len(CONNECTIONS) == before and packs.requests() == 0, 'offline, the add-on makes zero network attempts')

    check(set_online(True), 'online access is turned on in the preferences')
    click(window, region, 'SHELF_TAB.PACKS')
    yield 0.4
    click(window, region, 'PACKS_REFRESH')
    yield 0.5
    shown = yield from wait_for(lambda: pack_tile() is not None, 20)
    check(shown and packs.requests() == 1, 'Check for packs reads the real catalog and lists Cloth & Apparel Vol. 1')
    entry = packs.catalog()[0]
    check(entry['downloadUrl'].startswith(packs.RELEASE_PREFIX) and len(entry['sha256']) == 64, 'the catalog entry points at the asset library releases with a SHA-256')
    check(not packs.allowed(dict(entry, downloadUrl='https://example.com/pack.zip')) and not packs.allowed(dict(entry, sha256='')),
          'entries from another host or without a checksum are not allowed')
    real = entry['sha256']
    entry['sha256'] = 'f' * 64
    click(window, region, pack_tile())
    yield 0.5
    check('Downloading' in editor._active.message, 'clicking the pack starts the download')
    refused = yield from wait_for(lambda: 'refused' in editor._active.message, 240)
    folder = packs.folder_of(entry)
    staging = library.library_root() / 'packs' / 'downloads'
    check(refused and not folder.exists() and not any(staging.glob('*.zip')), f'a pack whose checksum does not match is refused and deleted, nothing is installed {editor._active.message} {[(k, v["state"], v["message"], v["received"]) for k, v in packs._jobs.items()]}')
    move(window, *middle)
    yield 0.3
    check('Refused' in control(pack_tile()).label, 'the shelf shows the refused download')
    entry['sha256'] = real
    packs._jobs.clear()
    click(window, region, pack_tile())
    yield 0.5
    installed = yield from wait_for(lambda: packs.installed(entry), 240)
    check(installed and 'Installed' in editor._active.message, 'the real pack downloads, passes its checksum, and installs')
    check(len(list((folder / 'Textures').glob('*.png'))) == 164 and len(list((folder / 'Alphas').glob('*.png'))) == 16 and not any(staging.glob('*.zip')),
          'the pack unpacks its 164 textures and 16 alphas into the library')
    move(window, *middle)
    yield 0.3
    check(control(pack_tile()).label.endswith('Installed'), 'the shelf marks the pack as installed')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield 0.6
    names = labels()
    check('boucle-tweed-01' in names and sum(1 for name in names if name.startswith(('boucle', 'corduroy', 'denim', 'silk'))) > 20,
          'the pack textures appear in the shelf')
    click(window, region, names['boucle-tweed-01'])
    yield 1.0
    fabric = active_layer(data)
    check(fabric.slots['base_color'].source == 'IMAGE' and fabric.slots['base_color'].image.name.startswith('boucle-tweed-01')
          and any(node.type == 'TEX_IMAGE' and node.image == fabric.slots['base_color'].image for node in data.material.node_tree.nodes),
          'a pack texture becomes a fill layer on the model')
    click(window, region, 'SHELF_TAB.ALPHAS')
    yield 0.6
    names = labels()
    check('blanket-stitch-seam' in names, 'the pack alphas appear in the alphas shelf')
    click(window, region, names['blanket-stitch-seam'])
    yield 0.4
    check(data.brush_alpha is not None and data.brush_alpha.name.startswith('blanket-stitch-seam'), 'a pack alpha becomes the brush alpha')
    click(window, region, 'ADD_PAINT')
    yield 0.8
    stitched_uid = active_layer(data).uid
    drag(window, *rect, 40, 0)
    yield 1.2
    check((pixels(find_layer(data, stitched_uid).image)[:, 3] > .05).sum() > 0, 'painting with the pack alpha lays down paint')

    check(set_online(False), 'online access is turned off again')
    before = len(CONNECTIONS)
    click(window, region, 'SHELF_TAB.PACKS')
    yield 0.5
    check(pack_tile() is not None and control(pack_tile()).label.endswith('Installed'), 'offline, the installed pack is still listed')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield 0.4
    click(window, region, labels()['denim-twill-01'] if 'denim-twill-01' in labels() else labels()['boucle-tweed-02'])
    yield 1.0
    check(active_layer(data).slots['base_color'].source == 'IMAGE' and len(CONNECTIONS) == before, 'offline, installed pack textures keep working with no network')
    click(window, region, 'SHELF_TAB.PACKS')
    yield 0.4
    click(window, region, pack_tile(), kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, next(key for key in keys('REMOVE_PACK.')))
    yield 0.6
    check(not folder.exists() and not packs.installed(entry), 'a pack can be removed')
    check(len(CONNECTIONS) == before, 'removing a pack offline stays offline')

    click(window, region, 'CLOSE')
    yield 0.6
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PACK CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI pack test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
