import os
import sys
import time
import traceback
import bpy

NAME = os.environ.get('DP_PACKAGE', 'bl_ext.user_default.devil_painter')
SECTION_WAIT = float(os.environ.get('DP_SECTION_WAIT', '20'))
SCROLLS = int(os.environ.get('DP_SCROLLS', '12'))
FIRST_LIMIT = float(os.environ.get('DP_FIRST_LIMIT', '0'))
FRAME_LIMIT = float(os.environ.get('DP_FRAME_LIMIT', '0'))
DRAWS, EVENTS = [], []
RESULTS = []


def out(*values):
    print(*values, flush=True)


def finish(code):
    sys.stdout.flush()
    os._exit(code)


def numbers(rows, since, until):
    values = sorted(duration for stamp, duration in rows if since <= stamp <= until)
    if not values:
        return dict(count=0, mean=0.0, p95=0.0, worst=0.0)
    return dict(count=len(values), mean=sum(values) / len(values), p95=values[max(0, int(len(values) * .95) - 1)], worst=values[-1])


def text(row):
    return f"n={row['count']} mean={row['mean']:.1f} p95={row['p95']:.1f} worst={row['worst']:.1f}"


def journey():
    modules = {name: sys.modules[NAME + '.' + name] for name in ('editor', 'shelf', 'packs', 'library')}
    editor, shelf, packs = modules['editor'], modules['shelf'], modules['packs']
    out('REAL build', sys.modules[NAME].__file__, 'online', bpy.app.online_access, 'textures folder set', bool(modules['library'].texture_folder()))
    cls = editor.DEVIL_PAINTER_OT_editor
    draw, modal = cls.draw_overlay, cls.modal

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
    cls.draw_overlay, cls.modal = measured_draw, measured_modal
    window = bpy.context.window_manager.windows[0]
    area = max((area for area in window.screen.areas if area.type == 'VIEW_3D'), key=lambda area: area.width * area.height)
    region = next(region for region in area.regions if region.type == 'WINDOW')
    mesh = next((obj for obj in bpy.data.objects if obj.type == 'MESH'), None)
    if mesh is None:
        bpy.ops.mesh.primitive_cube_add()
        mesh = bpy.context.active_object
    bpy.context.view_layer.objects.active = mesh
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    def move(x, y):
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))

    def controls():
        return editor._active.workspace.controls

    def control(key):
        return next((item for item in reversed(controls()) if item.key == key), None)

    def click(key):
        rect = control(key).rect
        x, y = region.x + rect.x + rect.w / 2, region.y + rect.y + rect.h / 2
        move(x, y)
        window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
        window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x), y=int(y))

    def tiles():
        return [item for item in controls() if item.key.startswith('ITEM.')]

    def settled(tab):
        expected = [item.label for item in shelf.visible(tab)]
        return editor._active.state.shelf_tab == tab and all(any(item.label.startswith(label) for label in expected[:200]) for item in tiles()[:3])

    def wait_previews(started, limit):
        first = full = None
        end = started + limit
        while time.perf_counter() < end:
            current = tiles()
            done = sum(1 for item in current if item.preview is not None or item.icon == 'FAILED')
            if first is None and done:
                first = time.perf_counter() - started
            if current and done == len(current):
                full = time.perf_counter() - started
                break
            yield 0.05
        return first, full

    move(*middle)
    window.event_simulate(type='P', value='PRESS', x=int(middle[0]), y=int(middle[1]), ctrl=True, alt=True)
    yield 1.0
    if control('START') is not None:
        click('START')
        yield 3.0
    if not editor._active.state.shelf_open:
        click('SHELF_TOGGLE')
        yield 0.5

    wanted = [name for name in os.environ.get('DP_SECTIONS', '').split(',') if name]
    sections = [tab for tab, _ in shelf.TABS if not wanted or tab in wanted]
    for tab in sections:
        if control('SHELF_TAB.' + tab) is None:
            out('MISSING SECTION', tab)
            continue
        started = time.perf_counter()
        click('SHELF_TAB.' + tab)
        move(*middle)
        for _ in range(200):
            yield 0.01
            if settled(tab):
                break
        if tab == 'PACKS':
            click('PACKS_REFRESH')
            move(*middle)
            for _ in range(400):
                yield 0.05
                if packs.catalog() and packs._state.get('verified') and tiles():
                    break
            yield from wait_previews(time.perf_counter(), 10)
            tile = next((item.key for item in tiles() if item.label.startswith('Cloth Textures Vol. 1')), None)
            if tile is not None:
                started = time.perf_counter()
                click(tile)
                move(*middle)
                for _ in range(200):
                    yield 0.01
                    if len(tiles()) > 3:
                        break
        opened = time.perf_counter()
        first, full = yield from wait_previews(started, SECTION_WAIT)
        loaded = time.perf_counter()
        scrolled = 0.0
        if 'SHELF' in editor._active.workspace.scroll_areas:
            view = editor._active.workspace.scroll_areas['SHELF'][0]
            x, y = region.x + view.x + view.w / 2, region.y + view.y + view.h / 2
            for step in range(SCROLLS):
                move(x + step % 3, y)
                window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
                yield 0.08
            scrolled = editor._active.state.scroll.get('SHELF', 0.0)
            move(*middle)
        after_first, after_full = yield from wait_previews(time.perf_counter(), SECTION_WAIT)
        until = time.perf_counter()
        current = tiles()
        failed = sum(1 for item in current if item.icon == 'FAILED')
        row = dict(section=tab, items=len(shelf.visible(tab)) if tab != 'PACKS' else len(tiles()), first=first, full=full, after_scroll=after_full,
                   draw=numbers(DRAWS, started, until), events=numbers(EVENTS, started, until), loading_draw=numbers(DRAWS, started, loaded),
                   scrolled=scrolled, failed=failed, blank=sum(1 for item in current if item.preview is None and item.icon != 'FAILED'))
        RESULTS.append(row)
        out(f"SECTION {tab}: items={row['items']} first_preview={first if first is None else round(first, 2)}s visible_done={full if full is None else round(full, 2)}s "
            f"after_scroll={after_full if after_full is None else round(after_full, 2)}s scrolled={scrolled:.0f}px failed={failed} blank={row['blank']} "
            f"draw[{text(row['draw'])}] events[{text(row['events'])}]")

    if wanted and 'LAYERS' not in wanted:
        click('CLOSE')
        yield 0.5
        finish(0)
    started = time.perf_counter()
    click('SHELF_TAB.MATERIALS')
    yield 0.5
    material = next((item.key for item in tiles()), None)
    for _ in range(int(os.environ.get('DP_LAYERS', '40'))):
        click(material)
        yield 0.05
    move(*middle)
    yield 1.0
    layers_open = time.perf_counter()
    if 'LAYERS' in editor._active.workspace.scroll_areas:
        view = editor._active.workspace.scroll_areas['LAYERS'][0]
        x, y = region.x + view.x + view.w / 2, region.y + view.y + view.h / 2
        for step in range(SCROLLS):
            move(x + step % 3, y)
            window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
            yield 0.08
    until = time.perf_counter()
    layer_count = len(editor._active.painted()[1].layers)
    out(f"SECTION LAYERS: layers={layer_count} adding draw[{text(numbers(DRAWS, started, layers_open))}] adding events[{text(numbers(EVENTS, started, layers_open))}] "
        f"scroll draw[{text(numbers(DRAWS, layers_open, until))}] scroll events[{text(numbers(EVENTS, layers_open, until))}]")
    click('CLOSE')
    yield 0.5
    problems = [row['section'] for row in RESULTS if FIRST_LIMIT and (row['first'] is None or row['first'] > FIRST_LIMIT)]
    problems += [row['section'] for row in RESULTS if row['blank'] > (1 if row['section'] == 'ALPHAS' else 0)]
    problems += [row['section'] for row in RESULTS if FRAME_LIMIT and (row['draw']['p95'] > FRAME_LIMIT or row['events']['p95'] > FRAME_LIMIT)]
    out('REAL SECTIONS', 'PASSED' if not problems else 'FAILED ' + ', '.join(sorted(set(problems))))
    finish(0 if not problems else 1)


steps = None


def advance():
    global steps
    try:
        if steps is None:
            steps = journey()
        return next(steps)
    except StopIteration:
        finish(0)
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(advance, first_interval=3.0, persistent=True)
