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
DRAWS = []
EVENTS = []
DECODES = []


def timed():
    draw, modal = editor.DEVIL_PAINTER_OT_editor.draw_overlay, editor.DEVIL_PAINTER_OT_editor.modal

    def measured_draw(self):
        start = time.perf_counter()
        try:
            return draw(self)
        finally:
            DRAWS.append((time.perf_counter(), (time.perf_counter() - start) * 1000))

    def measured_modal(self, context, event):
        start = time.perf_counter()
        try:
            return modal(self, context, event)
        finally:
            EVENTS.append((time.perf_counter(), (time.perf_counter() - start) * 1000))
    editor.DEVIL_PAINTER_OT_editor.draw_overlay, editor.DEVIL_PAINTER_OT_editor.modal = measured_draw, measured_modal
    decode = thumbnails.decode

    def measured_decode(source, cached):
        start = time.perf_counter()
        try:
            return decode(source, cached)
        finally:
            DECODES.append((time.perf_counter(), (time.perf_counter() - start) * 1000))
    thumbnails.decode = measured_decode


def summary(rows, since):
    values = sorted(duration for stamp, duration in rows if stamp >= since)
    if not values:
        return dict(count=0, worst=0.0, p95=0.0, mean=0.0)
    return dict(count=len(values), worst=values[-1], p95=values[max(0, int(len(values) * .95) - 1)], mean=sum(values) / len(values))


def described(numbers):
    return f"{numbers['count']} samples, mean {numbers['mean']:.1f} ms, p95 {numbers['p95']:.1f} ms, worst {numbers['worst']:.1f} ms"


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


def scroll_while_loading(window, region, seconds):
    end = time.perf_counter() + seconds
    tick = 0
    streamed = False
    while time.perf_counter() < end:
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
    folder = scratch / 'big_library_perf'
    shutil.rmtree(folder, ignore_errors=True)
    make_library(folder)
    for cache in ('preview_cache', 'thumbnails', 'thumbnail_jobs'):
        shutil.rmtree(library.library_root() / cache, ignore_errors=True)
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    library.set_texture_folder(str(folder))
    timed()
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

    opened = time.perf_counter()
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check(len(shelf.visible('TEXTURES')) >= COUNT, f'the Textures section lists all {COUNT} library textures')
    yield from until(lambda: any(item.label == 'aaa_broken' and item.icon == 'FAILED' for item in tiles()), 'the broken texture tile to say Preview failed')
    full = yield from wait_full(10)
    first_screen = time.perf_counter() - opened
    check(full, f'the first screen of previews fills in {first_screen:.2f} s')
    loading = time.perf_counter()
    streamed = yield from scroll_while_loading(window, region, 8)
    draws, events = summary(DRAWS, opened), summary(EVENTS, loading)
    print('MEASURED 600 TEXTURES DRAW:', described(draws))
    print('MEASURED 600 TEXTURES EVENTS:', described(events))
    check(streamed, 'scrolling reaches tiles whose previews are still streaming in')
    check(summary(DRAWS, loading)['count'] >= 60, f'the UI keeps drawing while previews load ({summary(DRAWS, loading)["count"]} frames in 8 s)')
    check(draws['worst'] < 100 and draws['p95'] < 50, f'no UI stall while 600 previews load: {described(draws)}')
    check(events['worst'] < 100 and events['p95'] < 20, f'scrolling and pointer input stay responsive while previews load: {described(events)}')
    full = yield from wait_full(15)
    check(full, 'every visible tile gets its preview after scrolling stops')

    thumbnails.release()
    editor._active.state.scroll['SHELF'] = 0.0
    reopened = time.perf_counter()
    move(window, *middle)
    yield from settle()
    full = yield from wait_full(5)
    first, repeat = summary(DECODES, opened), summary(DECODES, reopened)
    print('MEASURED DECODE FIRST TIME:', described(first))
    print('MEASURED DECODE FROM CACHE:', described(repeat))
    check(full and repeat['count'] > 0 and repeat['mean'] * 3 < first['mean'],
          f"reopened previews decode from the small cache ({repeat['mean']:.1f} ms each, first time {first['mean']:.1f} ms)")

    rendered = time.perf_counter()
    click(window, region, 'SHELF_TAB.SMART')
    yield from settle()
    end = time.perf_counter() + 40
    while time.perf_counter() < end:
        move(window, *middle)
        current = tiles()
        if current and all(item.preview is not None or item.icon == 'FAILED' for item in current):
            break
        yield from settle()
    smart = summary(EVENTS, rendered)
    smart_draws = summary(DRAWS, rendered)
    print('MEASURED SMART RENDERS EVENTS:', described(smart))
    print('MEASURED SMART RENDERS DRAW:', described(smart_draws))
    check(all(item.preview is not None for item in tiles()), f'smart material previews render in {time.perf_counter() - rendered:.1f} s')
    check(smart['worst'] < 100 and smart_draws['worst'] < 100, f'rendering material previews never stalls the UI: events {described(smart)}')

    click(window, region, 'CLOSE')
    yield from settle()
    devil_painter.unregister()
    shutil.rmtree(folder, ignore_errors=True)
    print('ALL PERF LIBRARY CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'Perf library check')
