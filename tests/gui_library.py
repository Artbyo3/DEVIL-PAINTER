import shutil
import sys
import time
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, shelf, thumbnails
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, finish, move, press, run_journey, settle, until, viewport

COUNT = 600
SIZE = 1024


def tiles():
    return [item for item in editor._active.workspace.controls if item.key.startswith('ITEM.')]


def make_library(folder):
    folder.mkdir(parents=True, exist_ok=True)
    rng = numpy.random.default_rng(7)
    for variant in range(4):
        image = bpy.data.images.new(f'seed{variant}', SIZE, SIZE, alpha=True)
        image.pixels.foreach_set(rng.random(SIZE * SIZE * 4, dtype=numpy.float32))
        image.filepath_raw, image.file_format = str(folder / f'cloth_{variant:04d}.png'), 'PNG'
        image.save()
        bpy.data.images.remove(image)
    for index in range(4, COUNT):
        shutil.copyfile(folder / f'cloth_{index % 4:04d}.png', folder / f'cloth_{index:04d}.png')
    (folder / 'aaa_broken.png').write_bytes(b'not an image')


def scroll_while_loading(window, region):
    tick = 0
    streamed = False
    while tick < 120 and editor._active.state.scroll.get('SHELF', 0.0) <= 1000:
        tick += 1
        current = tiles()
        streamed = streamed or any(item.preview is None for item in current)
        viewport_rect = editor._active.workspace.scroll_areas['SHELF'][0]
        x, y = region.x + viewport_rect.x + viewport_rect.w / 2 + tick % 5, region.y + viewport_rect.y + viewport_rect.h / 2
        move(window, x, y)
        if tick % 3 == 0:
            window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
        yield from settle()
    return streamed


def wait_full(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        current = tiles()
        if current and all(item.preview is not None or item.icon == 'FAILED' for item in current):
            return True
        yield from settle()
    return False


def journey():
    scratch = prepare_scratch()
    folder = scratch / 'big_library'
    shutil.rmtree(folder, ignore_errors=True)
    make_library(folder)
    for cache in ('preview_cache', 'thumbnails', 'thumbnail_jobs'):
        shutil.rmtree(library.library_root() / cache, ignore_errors=True)
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    library.set_texture_folder(str(folder))
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = bpy.data.objects['Cube'].devil_painter.sets[0]

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check(len(shelf.visible('TEXTURES')) >= COUNT, f'the Textures section lists all {COUNT} library textures')
    yield from until(lambda: any(item.label == 'aaa_broken' and item.icon == 'FAILED' for item in tiles()), 'the broken texture tile to say Preview failed')
    broken = next((item for item in tiles() if item.label == 'aaa_broken'), None)
    check(broken is not None and broken.preview is None and broken.icon == 'FAILED', 'a texture whose preview cannot be decoded says Preview failed on its tile')
    check(thumbnails.waiting() and any(item.preview is None for item in tiles()), 'previews are still loading in the background when the section opens')
    layers = len(data.layers)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    check(len(data.layers) == layers + 1 and thumbnails.waiting(), 'a button click is handled at once while previews stream in')
    full = yield from wait_full(60)
    check(full, 'the first screen of previews fills')
    streamed = yield from scroll_while_loading(window, region)
    check(streamed, 'scrolling reaches tiles whose previews are still streaming in')
    check(editor._active.state.scroll.get('SHELF', 0.0) > 1000, 'the 600-texture section scrolls smoothly far down the list')
    full = yield from wait_full(60)
    check(full, 'every visible tile gets its preview after scrolling stops')
    cached = list((library.library_root() / 'preview_cache').glob('*.png'))
    check(len(cached) >= len(tiles()), f'decoded previews are cached on disk ({len(cached)} small previews)')

    thumbnails.release()
    editor._active.state.scroll['SHELF'] = 0.0
    move(window, *middle)
    yield from settle()
    full = yield from wait_full(60)
    check(full, 'reopened previews load from the small cache')

    click(window, region, 'SHELF_TAB.SMART')
    yield from settle()
    end = time.perf_counter() + 60
    while time.perf_counter() < end:
        move(window, *middle)
        current = tiles()
        if current and all(item.preview is not None or item.icon == 'FAILED' for item in current):
            break
        yield from settle()
    check(all(item.preview is not None for item in tiles()), 'smart material previews render')
    check(thumbnails._state['processes'], 'material previews render in background Blender processes')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter') and not thumbnails.rendering(), 'Devil Painter unregisters and stops its preview renderers')
    shutil.rmtree(folder, ignore_errors=True)
    print('ALL GUI LIBRARY CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI library test')
