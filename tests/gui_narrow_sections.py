import sys
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, move, press, run_journey, settle, viewport

EXEMPT_KINDS = {'GRIP', 'GHOST'}
EXEMPT_KEYS = {'DROP_LINE', 'DRAG_GHOST'}
NAMES = dict(BAR='workspace bar', STRIP='tool strip', SHELF='asset browser')
OPENERS = dict(BAR=('EXPORT', 'EXPORT'), STRIP=('SYMMETRY', 'SYMMETRY'))
SCOPES = ('SCOPE.ALL', 'SCOPE.BUILTIN', 'SCOPE.MINE')


def workspace():
    return editor._active.workspace


def rect(key):
    return workspace().zones.rects[key]


def strip_of(key):
    side, index = workspace().zones.places[key]
    return side, index, next(found for where, number, found in workspace().zones.strips if where == side and number == index)


def inside(box, area, slack=1.0):
    return box.x >= area.x - slack and box.y >= area.y - slack and box.x + box.w <= area.x + area.w + slack and box.top <= area.top + slack


def visible_part(item):
    box, clip = item.rect, item.clip
    if clip is None:
        return box
    x, y = max(box.x, clip.x), max(box.y, clip.y)
    right, top = min(box.x + box.w, clip.x + clip.w), min(box.top, clip.top)
    if right <= x or top <= y:
        return None
    return type(box)(x, y, right - x, top - y)


def escaped():
    layout = workspace()
    boxes = [found for found, _ in layout.cards] + list(layout.tool_groups) + list(layout.zones.rects.values())
    if layout.popover is not None:
        boxes.append(layout.popover)
    found = []
    for item in layout.controls:
        if item.kind in EXEMPT_KINDS or item.key in EXEMPT_KEYS:
            continue
        part = visible_part(item)
        if part is not None and part.w > 0 and part.h > 0 and not any(inside(part, box) for box in boxes):
            found.append((item.key, item.kind, part))
    return found


def whole(item, area):
    return inside(item.rect, area, .5) and (item.clip is None or inside(item.rect, item.clip, .5))


def row_controls(key):
    zone = rect(key)
    return [item for item in workspace().controls if item.clip == zone and item.kind not in EXEMPT_KINDS and item.rect.w > 0]


def tiles():
    return [item for item in workspace().controls if item.key.startswith('ITEM.')]


def grab_point(region, key):
    layout, found = workspace(), rect(key)
    for step in range(1, int(found.h // 2)):
        for fraction in (.5, .1, .9, .3, .7):
            x, y = found.x + found.w * fraction, found.top - 2 * step
            if layout.hit(x, y) is None and layout.covers(x, y):
                return region.x + x, region.y + y
    raise AssertionError(f'no empty spot to grab the {NAMES.get(key, key)}')


def drag_between(window, start, end):
    move(window, *start)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
    for step in range(1, 9):
        move(window, start[0] + (end[0] - start[0]) * step / 8, start[1] + (end[1] - start[1]) * step / 8)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(end[0]), y=int(end[1]))


def move_section(window, region, key, x, y):
    drag_between(window, grab_point(region, key), (x, y))


def move_panel(window, region, key, x, y):
    header = control('PANEL_' + key).rect
    drag_between(window, (region.x + header.x + 30, region.y + header.y + header.h / 2), (x, y))


def drag_grip(window, region, key, x, y):
    found = control(key).rect
    drag_between(window, (region.x + found.x + found.w / 2, region.y + found.y + found.h / 2), (x, y))


def stage_point(region, side):
    stage = workspace().zones.stage
    return dict(BOTTOM=(region.x + stage.x + stage.w / 2, region.y + stage.y + 10),
                LEFT=(region.x + stage.x + 10, region.y + stage.y + stage.h / 2))[side]


def middle_of(region):
    stage = workspace().zones.stage
    return region.x + stage.x + stage.w / 2, region.y + stage.y + stage.h / 2


def wheel(window, region, area, direction):
    x, y = region.x + area.x + area.w / 2, region.y + area.y + area.h / 2
    move(window, x, y)
    window.event_simulate(type=direction, value='PRESS', x=int(x), y=int(y))


def scroll_through(window, region, key, area, seen):
    for _ in range(60):
        seen(area)
        before = editor._active.state.scroll.get(key, 0.0)
        wheel(window, region, area, 'WHEELDOWNMOUSE')
        yield from settle()
        if editor._active.state.scroll.get(key, 0.0) <= before:
            break
    seen(area)


def narrow_row(window, region, key):
    move_section(window, region, key, *stage_point(region, 'BOTTOM'))
    yield from settle()
    check(workspace().zones.places[key][0] == 'BOTTOM', f'the {NAMES[key]} moves into its own bottom row')
    zone = rect(key)
    check(key in workspace().scroll_areas, f'the {NAMES[key]} in a {zone.w:.0f} px bottom row between side columns is narrower than its content and scrolls')
    check(not escaped(), f'nothing in the narrow {NAMES[key]} reaches past the section edge {escaped()}')
    every = {item.key for item in row_controls(key)}
    reached = set()

    def seen(area):
        check(not escaped(), f'scrolling the {NAMES[key]} keeps its content inside the section {escaped()}')
        reached.update(item.key for item in row_controls(key) if whole(item, area))

    yield from scroll_through(window, region, key, zone, seen)
    check(editor._active.state.scroll.get(key, 0.0) > 0 and abs(editor._active.state.scroll[key] - workspace().scroll_areas[key][1]) < 1.0,
          f'the wheel scrolls the {NAMES[key]} to the end of its content')
    check(reached >= every, f'every control of the {NAMES[key]} comes fully into view while scrolling {sorted(every - reached)}')
    opener, kind = OPENERS[key]
    opened = False
    for _ in range(60):
        if not opened and whole(control(opener), zone):
            click(window, region, opener)
            yield from settle()
            opened = editor._active.state.popover is not None and editor._active.state.popover.kind == kind
            check(opened, f'{opener} in the scrolled {NAMES[key]} still opens its card')
            press(window, 'ESC', *middle_of(region))
            yield from settle()
        if editor._active.state.scroll.get(key, 0.0) <= 0:
            break
        wheel(window, region, zone, 'WHEELUPMOUSE')
        yield from settle()
    check(opened, f'{opener} came fully into view while scrolling the {NAMES[key]} back')
    check(editor._active.state.scroll.get(key, 0.0) == 0 and not escaped(), f'the {NAMES[key]} scrolls back to its start')


def journey():
    prepare_scratch()
    settings_file = library.library_root() / library.SETTINGS_FILE
    settings_file.unlink(missing_ok=True)
    library._cache.clear()
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    check(not escaped(), f'nothing spills out of its section in the default layout {escaped()}')

    move_panel(window, region, 'SETS', *stage_point(region, 'LEFT'))
    yield from settle()
    check(workspace().zones.places['SETS'][0] == 'LEFT', 'the Texture sets panel opens a side column on the left')
    grip = control('STRIP.RIGHT.0').rect
    drag_grip(window, region, 'STRIP.RIGHT.0', region.x + 20, region.y + grip.y + grip.h / 2)
    yield from settle()
    yield from narrow_row(window, region, 'BAR')
    yield from narrow_row(window, region, 'STRIP')

    move_section(window, region, 'SHELF', *stage_point(region, 'LEFT'))
    yield from settle()
    check(workspace().zones.places['SHELF'][0] == 'LEFT', 'the asset browser moves into a side column')
    side, index, column = strip_of('SHELF')
    grip = control(f'STRIP.{side}.{index}').rect
    drag_grip(window, region, f'STRIP.{side}.{index}', region.x + column.x + 4, region.y + grip.y + grip.h / 2)
    yield from settle()
    zone = rect('SHELF')
    check(abs(zone.w - 200 * workspace().scale) < 1.0, f'the asset browser column shrinks to its 200 px minimum width ({zone.w:.0f})')
    check(all(whole(control(key), zone) for key in SCOPES), 'the All, Built-in, and Mine chips sit fully inside the asset browser at its minimum width')
    check(not escaped(), f'nothing in the asset browser reaches past its edge at the minimum width {escaped()}')
    check(tiles() and any(whole(item, zone) for item in tiles()), 'at least one whole tile shows in the minimum-width asset browser')

    shelf_zone = rect('SHELF')
    move_panel(window, region, 'HISTORY', region.x + shelf_zone.x + shelf_zone.w / 2, region.y + shelf_zone.y + 12)
    yield from settle()
    check(strip_of('HISTORY')[:2] == strip_of('SHELF')[:2], 'the History panel joins the asset browser column below it')
    zone = rect('SHELF')
    check('SHELF' in workspace().scroll_areas and not escaped(),
          f'a short {zone.h:.0f} px asset browser with wrapped tabs scrolls its header and tiles together without overflow {escaped()}')
    found = []

    def seen(area):
        check(not escaped(), f'scrolling the short asset browser keeps its content inside the section {escaped()}')
        found.extend(item.key for item in tiles() if whole(item, area))

    yield from scroll_through(window, region, 'SHELF', zone, seen)
    check(found, 'scrolling the short asset browser brings a whole tile into view')
    layers = len(cube.devil_painter.sets[0].layers)
    click(window, region, next(item.key for item in tiles() if whole(item, zone)))
    yield from settle()
    check(len(cube.devil_painter.sets[0].layers) == layers + 1, 'clicking the whole tile in view adds it as a fill layer')

    press(window, 'P', *middle_of(region), ctrl=True, alt=True)
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI NARROW SECTION CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI narrow sections test')
