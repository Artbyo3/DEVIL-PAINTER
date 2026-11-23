import json
import sys
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library
from devil_painter.privacy import MASK, masked_path
from devil_painter.shell import COLUMNS, MAX_SIZE, PANELS, SECTIONS
from tools.workspace import prepare_scratch
from tests.gui_harness import check, finish, move, press, run_journey, settle, type_text, viewport

EXEMPT_KINDS = {'GRIP', 'GHOST'}
NAMES = dict(BAR='workspace bar', STRIP='tool strip', DOCK='tool dock', SHELF='asset browser', SETS='Texture sets panel',
             LAYERS='Layers panel', PROPERTIES='Properties panel', MAPS='Mesh maps panel', HISTORY='History panel')
GROW = dict(TOP=(0, -1), BOTTOM=(0, 1), LEFT=(1, 0), RIGHT=(-1, 0))
EXEMPT_KEYS = {'DROP_LINE', 'DRAG_GHOST'}


def workspace():
    return editor._active.workspace


def control(key):
    return next(item for item in reversed(workspace().controls) if item.key == key)


def has(key):
    return any(item.key == key for item in workspace().controls)


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5):
    press(window, kind, *spot(region, key, fx, fy))


def drag(window, region, key, dx, dy, fx=.5, fy=.5):
    x, y = spot(region, key, fx, fy)
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 9):
        move(window, x + dx * step / 8, y + dy * step / 8)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def inside(rect, box, slack=1.0):
    return rect.x >= box.x - slack and rect.y >= box.y - slack and rect.x + rect.w <= box.x + box.w + slack and rect.top <= box.top + slack


def visible_part(item):
    rect, clip = item.rect, item.clip
    if clip is None:
        return rect
    x, y = max(rect.x, clip.x), max(rect.y, clip.y)
    right, top = min(rect.x + rect.w, clip.x + clip.w), min(rect.top, clip.top)
    if right <= x or top <= y:
        return None
    return type(rect)(x, y, right - x, top - y)


def escaped():
    layout = workspace()
    zones = layout.zones
    boxes = [rect for rect, _ in layout.cards] + list(layout.tool_groups) + list(zones.rects.values())
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


def rect(key):
    return workspace().zones.rects[key]


def strip_of(key):
    side, index = workspace().zones.places[key]
    return side, index, next(found for where, number, found in workspace().zones.strips if where == side and number == index)


def extent(key):
    found = rect(key)
    return found.w * found.h


def grab_point(region, key):
    layout, found = workspace(), rect(key)
    if key in PANELS:
        header = control('PANEL_' + key).rect
        return region.x + header.x + 30, region.y + header.y + header.h / 2
    for step in range(1, int(found.h // 2)):
        for fraction in (.5, .1, .9, .3, .7):
            x, y = found.x + found.w * fraction, found.top - 2 * step
            if layout.hit(x, y) is None and (key == 'DOCK' or layout.covers(x, y)):
                return region.x + x, region.y + y
    raise AssertionError(f'no empty spot to grab the {NAMES[key]}')


def move_section(window, region, key, x, y):
    start = grab_point(region, key)
    move(window, *start)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
    for step in range(1, 9):
        move(window, start[0] + (x - start[0]) * step / 8, start[1] + (y - start[1]) * step / 8)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x), y=int(y))


def resize_section(window, region, key, amount):
    side, index, _ = strip_of(key)
    if has('SIZE.' + key):
        dx, dy = (0, -1) if side in COLUMNS else (1, 0)
        drag(window, region, 'SIZE.' + key, dx * amount, dy * amount)
    else:
        dx, dy = GROW[side]
        drag(window, region, f'STRIP.{side}.{index}', dx * amount, dy * amount)


def stage_point(region, side):
    stage = workspace().zones.stage
    return dict(TOP=(region.x + stage.x + stage.w / 2, region.y + stage.top - 10), BOTTOM=(region.x + stage.x + stage.w / 2, region.y + stage.y + 10),
                LEFT=(region.x + stage.x + 10, region.y + stage.y + stage.h / 2), RIGHT=(region.x + stage.x + stage.w - 10, region.y + stage.y + stage.h / 2))[side]


def snapshot():
    return {key: tuple(round(value, 2) for value in (found.x, found.y, found.w, found.h)) for key, found in workspace().zones.rects.items()}


def saved_workspace(settings_file):
    return json.loads(settings_file.read_text(encoding='utf-8'))['workspace']


def journey():
    scratch = prepare_scratch()
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
    data = cube.devil_painter.sets[0]
    check(not escaped(), f'nothing spills out of its shell in the default layout {escaped()}')

    layers = rect('LAYERS')
    sizes = set()
    for _ in range(24):
        click(window, region, 'ADD_PAINT')
        yield from settle()
        sizes.add((round(rect('LAYERS').h, 3), round(rect('LAYERS').y, 3)))
    check(len(data.layers) >= 25 and sizes == {(round(layers.h, 3), round(layers.y, 3))},
          f'adding 24 layers leaves the Layers shell at exactly the same size {sizes} {layers}')
    check('LAYERS' in workspace().scroll_areas, 'the layer rows scroll inside the fixed Layers shell')
    check(not escaped(), f'a long layer stack stays inside its shell {escaped()}')
    column = editor._active.state.strips['RIGHT'][0]['items']
    check(column == list(PANELS), f'the right column holds the {len(PANELS)} panels in the default order {column}')

    before = rect('LAYERS').h
    drag(window, region, 'SIZE.LAYERS', 0, -70)
    yield from settle()
    grown = rect('LAYERS').h
    check(grown > before + 40, f'dragging the Layers bottom border makes the section taller {before} {grown}')
    drag(window, region, 'SIZE.LAYERS', 0, 40)
    yield from settle()
    check(rect('LAYERS').h < grown - 30, 'dragging the border back up makes it shorter')
    check(abs(saved_workspace(settings_file)['heights']['LAYERS'] - editor._active.state.section_heights['LAYERS']) < .01, 'the new size is saved to the library settings')

    sets = rect('SETS')
    move_section(window, region, 'MAPS', region.x + sets.x + sets.w / 2, region.y + sets.y + sets.h * .8)
    yield from settle()
    column = editor._active.state.strips['RIGHT'][0]['items']
    check(column[0] == 'MAPS' and not escaped(), f'dragging the Mesh maps title onto the top of the column moves it there {column}')
    click(window, region, 'PANEL_SETS', fx=.15)
    yield from settle()
    check('SETS' in editor._active.state.collapsed, 'clicking a panel title without dragging still collapses it')
    click(window, region, 'PANEL_SETS', fx=.15)
    yield from settle()

    inventory = {key: set() for key in SECTIONS}
    for key in SECTIONS:
        resize_section(window, region, key, -60)
        yield from settle()
        low = extent(key)
        resize_section(window, region, key, 60)
        yield from settle()
        high = extent(key)
        resize_section(window, region, key, -60)
        yield from settle()
        check(high > low and extent(key) < high and not escaped(), f'the {NAMES[key]} grows and shrinks by its border ({low:.0f} < {high:.0f} > {extent(key):.0f}) {escaped()}')
        inventory[key].add('resized')
    for key in ('BAR', 'STRIP'):
        for target in ('BOTTOM', 'TOP'):
            move_section(window, region, key, *stage_point(region, target))
            yield from settle()
            check(workspace().zones.places[key][0] == target and not escaped(),
                  f'dragging the {NAMES[key]} to the {target.lower()} edge of the viewport moves it there {escaped()}')
        inventory[key].add('rearranged')
    right = strip_of('LAYERS')[2]
    move_section(window, region, 'PROPERTIES', region.x + right.x + right.w - 8, region.y + right.y + right.h / 2)
    yield from settle()
    check(len(editor._active.state.strips['RIGHT']) == 2 and editor._active.state.strips['RIGHT'][0]['items'] == ['PROPERTIES'] and not escaped(),
          f'dropping Properties on the outer edge of the column splits it into its own column {editor._active.state.strips["RIGHT"]} {escaped()}')
    targets = dict(SHELF='LEFT', SETS='LEFT', LAYERS='LEFT', PROPERTIES='RIGHT', MAPS='RIGHT', HISTORY='RIGHT')
    for key in targets:
        before = strip_of(key)[0]
        move_section(window, region, key, *stage_point(region, targets[key]))
        yield from settle()
        side = workspace().zones.places[key][0]
        check(side == targets[key] and not escaped() and not has('SECTION_GHOST'),
              f'dragging the {NAMES[key]} to the {targets[key].lower()} edge of the viewport moves it there (from {before.lower()}) {escaped()}')
        inventory[key].add('rearranged')
    check(all(inventory[key] == ({'resized'} if key == 'DOCK' else {'rearranged', 'resized'}) for key in SECTIONS),
          'inventory: ' + '; '.join(f'{NAMES[key]} {sorted(inventory[key])}' for key in SECTIONS))
    stage = workspace().zones.stage
    check(stage.w > 0 and stage.h > 0 and not any(found.x < stage.x + stage.w and stage.x < found.x + found.w and found.y < stage.top and stage.y < found.top
                                                   for found in workspace().zones.rects.values()),
          'with every section moved, the free viewport stays clear of all of them')

    for key in SECTIONS:
        if key != 'SHELF':
            resize_section(window, region, key, -5000)
            yield from settle()
    check(not escaped(), f'at minimum sizes nothing overflows {escaped()}')
    click(window, region, 'EXPORT')
    yield from settle()
    check(not escaped(), f'the export card fits at minimum sizes {escaped()}')
    press(window, 'ESC', *middle)
    yield from settle()
    resize_section(window, region, 'LAYERS', 5000)
    yield from settle()
    side, index, _ = strip_of('LAYERS')
    bounds = editor._active.bounds
    check(not escaped() and editor._active.state.strips[side][index]['size'] <= MAX_SIZE
          and all(found.x >= bounds.x and found.y >= bounds.y and found.x + found.w <= bounds.x + bounds.w and found.top <= bounds.top
                  for found in workspace().zones.rects.values()),
          f'a section dragged far past its limit stays within its safe maximum and inside the workspace {escaped()}')
    check(saved_workspace(settings_file)['strips'] == editor._active.state.strips, 'the arrangement is saved')

    zones_before = snapshot()
    saved_before = saved_workspace(settings_file)
    click(window, region, 'CLOSE')
    yield from settle()
    devil_painter.unregister()
    library._cache.clear()
    yield from settle()
    devil_painter.register()
    yield from settle()
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(snapshot() == zones_before and saved_workspace(settings_file) == saved_before,
          f'after a restart every section is back exactly where and how big the user left it {zones_before} {snapshot()}')
    check(not escaped(), f'the restored arrangement has no overflow {escaped()}')

    x, y = grab_point(region, 'BAR')
    press(window, 'RIGHTMOUSE', x, y)
    yield from settle()
    click(window, region, 'RESET_LAYOUT')
    yield from settle()
    check(editor._active.state.strips['RIGHT'][0]['items'] == list(PANELS) and workspace().zones.places['SHELF'][0] == 'BOTTOM'
          and workspace().zones.places['DOCK'][0] == 'LEFT' and not escaped(), 'Reset layout from the right-click menu brings back the default arrangement')
    texture_dir = scratch / 'Private Textures'
    texture_dir.mkdir(exist_ok=True)
    library.set_texture_folder(str(texture_dir))
    (scratch / 'Private Library').mkdir(exist_ok=True)
    check(library.add_library(str(scratch / 'Private Library')), 'a private library folder is added')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    field = control('TEXTURE_DIR').text
    check(field.startswith(MASK) and field == masked_path(str(texture_dir)) and 'Users' not in field and str(scratch) not in field,
          f'the texture folder field shows the path masked by default ({field})')
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    check(editor._active.state.text is not None and editor._active.state.text.text == str(texture_dir), 'clicking the field reveals the full path to edit')
    press(window, 'ESC', *middle)
    yield from settle()
    check(control('TEXTURE_DIR').text.startswith(MASK), 'the field is masked again after editing')
    click(window, region, 'LIBRARIES')
    yield from settle()
    label = control('LIBRARY.0').label
    check(label.startswith(MASK) and 'Users' not in label, f'library folders are masked by default ({label})')
    click(window, region, 'LIBRARY.0')
    yield from settle()
    check(control('LIBRARY.0').label == str(scratch / 'Private Library'), 'clicking a library folder reveals its full path')
    click(window, region, 'LIBRARY.0')
    yield from settle()
    check(control('LIBRARY.0').label.startswith(MASK), 'clicking it again masks it')
    press(window, 'ESC', *middle)
    yield from settle()
    export_dir = scratch / 'Private Export'
    cube.devil_painter.export_directory = str(export_dir)
    click(window, region, 'EXPORT')
    yield from settle()
    check(control('EXPORT_DIR').text == masked_path(str(export_dir)) and 'Users' not in control('EXPORT_DIR').text, 'the export folder is masked by default')
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    check(editor._active.state.text.text == str(export_dir), 'clicking the export folder reveals it')
    press(window, 'ESC', *middle)
    yield from settle()
    click(window, region, 'BRIDGE_COMMAND')
    yield from settle()
    command = f'"{scratch / "Apps" / "viewer.exe"}" {{files}}'
    type_text(window, command, *spot(region, 'BRIDGE_COMMAND'))
    yield from settle()
    move(window, *spot(region, 'EXPORT_RUN'))
    yield from settle()
    shown_command = control('BRIDGE_COMMAND').text
    check(shown_command.endswith('{files}') and MASK in shown_command and 'Users' not in shown_command, f'the send-to-app command masks its path ({shown_command})')
    press(window, 'ESC', *middle)
    yield from settle()
    editor._active.message = f'Exported 3 textures to {export_dir}.'
    move(window, *middle)
    yield from settle()
    toast = editor._active.toast_rect
    check(toast is not None and not editor._active.toast_revealed, 'a message with a path shows as a masked toast')
    press(window, 'LEFTMOUSE', region.x + toast.x + toast.w / 2, region.y + toast.y + toast.h / 2)
    yield from settle()
    check(editor._active.toast_revealed, 'clicking the toast reveals the full path')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI LAYOUT CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI layout test')
