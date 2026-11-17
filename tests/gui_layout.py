import json
import os
import sys
import time
import traceback
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library
from devil_painter.minimal import HEADER
from devil_painter.privacy import MASK, masked_path
from devil_painter.shell import MAX_COLUMN, MIN_COLUMN, MIN_PANEL, PANELS
from tools.workspace import prepare_scratch

TIMEOUT = 600
STARTED = time.time()
EXEMPT_KINDS = {'GRIP'}
EXEMPT_KEYS = {'DROP_LINE', 'DRAG_GHOST'}


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


def type_text(window, text, x, y):
    for _ in range(200):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


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
    boxes = [rect for rect, _ in layout.cards] + list(layout.tool_groups) + [zones.bar, zones.strip, zones.dock, zones.shelf]
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


def column_fits():
    column = workspace().zones.column
    return all(inside(card, column) for card in workspace().panels.values())


def journey():
    scratch = prepare_scratch()
    settings_file = library.library_root() / library.SETTINGS_FILE
    settings_file.unlink(missing_ok=True)
    library._cache.clear()
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.6
    click(window, region, 'RES.0.1024')
    yield 0.2
    click(window, region, 'START')
    yield 2.0
    data = cube.devil_painter.sets[0]
    check(not escaped(), f'nothing spills out of its shell in the default layout {escaped()}')

    layers = workspace().panels['LAYERS']
    sizes = set()
    for _ in range(24):
        click(window, region, 'ADD_PAINT')
        yield 0.15
        sizes.add((round(workspace().panels['LAYERS'].h, 3), round(workspace().panels['LAYERS'].y, 3)))
    check(len(data.layers) >= 25 and sizes == {(round(layers.h, 3), round(layers.y, 3))},
          f'adding 24 layers leaves the Layers shell at exactly the same size {sizes} {layers}')
    check('LAYERS' in workspace().scroll_areas, 'the layer rows scroll inside the fixed Layers shell')
    check(not escaped(), f'a long layer stack stays inside its shell {escaped()}')

    shown = [key for key in workspace().panels]
    check(shown == [key for key in PANELS if key in shown] and len(shown) == 4, f'the column shows its four sections in the default order {shown}')
    before = workspace().panels['LAYERS'].h
    drag(window, region, 'PANEL_EDGE.LAYERS', 0, -70)
    yield 0.5
    grown = workspace().panels['LAYERS'].h
    check(grown > before + 40, f'dragging the Layers bottom border makes the section taller {before} {grown}')
    drag(window, region, 'PANEL_EDGE.LAYERS', 0, 40)
    yield 0.5
    check(abs(workspace().panels['LAYERS'].h - (grown - 40)) < 6, 'dragging the border back up makes it shorter')
    saved = json.loads(settings_file.read_text(encoding='utf-8'))['column']
    check(abs(saved['heights']['LAYERS'] * workspace().scale - (workspace().panels['LAYERS'].h - HEADER * workspace().scale)) < 1, 'the new size is saved to the library settings')

    sets_top = workspace().panels['SETS'].top
    drag(window, region, 'PANEL_MAPS', 0, sets_top + 12 - control('PANEL_MAPS').rect.y, fx=.3, fy=0.0)
    yield 0.5
    order = list(workspace().panels)
    check(order[0] == 'MAPS' and abs(workspace().panels['MAPS'].top - sets_top) < 1, f'dragging the Mesh maps header to the top moves the section there {order}')
    drag(window, region, 'PANEL_SETS', 0, workspace().panels['PROPERTIES'].y + 6 - control('PANEL_SETS').rect.y, fx=.3)
    yield 0.5
    order = list(workspace().panels)
    check(order == ['MAPS', 'LAYERS', 'PROPERTIES', 'SETS'], f'dragging Texture sets below Properties rearranges the column {order}')
    check(not escaped() and column_fits(), f'the rearranged column has no overflow {escaped()}')
    check(json.loads(settings_file.read_text(encoding='utf-8'))['column']['order'] == order, 'the new order is saved')

    for key in list(workspace().panels):
        drag(window, region, 'PANEL_EDGE.' + key, 0, 2000)
        yield 0.3
    smallest = {key: round(card.h - HEADER * workspace().scale, 2) for key, card in workspace().panels.items()}
    check(all(abs(value - MIN_PANEL * workspace().scale) < 1.5 for value in smallest.values()), f'every section shrinks to its safe minimum {smallest}')
    drag(window, region, 'COLUMN_EDGE', 3000, 0)
    yield 0.5
    check(abs(workspace().zones.column.w - MIN_COLUMN * workspace().scale) < 1, 'the column narrows to its minimum width')
    check(not escaped() and column_fits(), f'at minimum sizes nothing overflows {escaped()}')
    click(window, region, 'EXPORT')
    yield 0.4
    check(not escaped(), f'the export card fits at minimum sizes {escaped()}')
    press(window, 'ESC', *middle)
    yield 0.3

    drag(window, region, 'PANEL_EDGE.LAYERS', 0, -4000)
    yield 0.5
    check(column_fits() and not escaped(), f'a section dragged far past the column bottom stays inside the column {escaped()}')
    drag(window, region, 'COLUMN_EDGE', -3000, 0)
    yield 0.5
    check(workspace().zones.column.w <= MAX_COLUMN * workspace().scale + 1 and not escaped(), 'the column widens only to its maximum width')
    click(window, region, 'PANEL_SETS')
    yield 0.4
    check('SETS' in editor._active.state.collapsed, 'clicking a header without dragging still collapses the section')

    layout_before = {key: (round(card.x, 2), round(card.y, 2), round(card.w, 2), round(card.h, 2)) for key, card in workspace().panels.items()}
    saved_before = json.loads(settings_file.read_text(encoding='utf-8'))['column']
    click(window, region, 'CLOSE')
    yield 0.6
    devil_painter.unregister()
    library._cache.clear()
    yield 0.3
    devil_painter.register()
    yield 0.5
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 1.0
    layout_after = {key: (round(card.x, 2), round(card.y, 2), round(card.w, 2), round(card.h, 2)) for key, card in workspace().panels.items()}
    check(layout_after == layout_before and list(layout_after) == list(layout_before),
          f'after a restart the column comes back exactly as the user left it {layout_before} {layout_after}')
    check(json.loads(settings_file.read_text(encoding='utf-8'))['column'] == saved_before and 'SETS' in editor._active.state.collapsed,
          'order, sizes, width, and collapsed sections persist in the library settings')

    drag(window, region, 'COLUMN_EDGE', 3000, 0)
    yield 0.4
    texture_dir = scratch / 'Private Textures'
    texture_dir.mkdir(exist_ok=True)
    library.set_texture_folder(str(texture_dir))
    (scratch / 'Private Library').mkdir(exist_ok=True)
    check(library.add_library(str(scratch / 'Private Library')), 'a private library folder is added')
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield 0.5
    field = control('TEXTURE_DIR').text
    check(field.startswith(MASK) and field == masked_path(str(texture_dir)) and 'Users' not in field and str(scratch) not in field,
          f'the texture folder field shows the path masked by default ({field})')
    click(window, region, 'TEXTURE_DIR')
    yield 0.3
    check(editor._active.state.text is not None and editor._active.state.text.text == str(texture_dir), 'clicking the field reveals the full path to edit')
    press(window, 'ESC', *middle)
    yield 0.3
    check(control('TEXTURE_DIR').text.startswith(MASK), 'the field is masked again after editing')
    click(window, region, 'LIBRARIES')
    yield 0.4
    label = control('LIBRARY.0').label
    check(label.startswith(MASK) and 'Users' not in label, f'library folders are masked by default ({label})')
    click(window, region, 'LIBRARY.0')
    yield 0.3
    check(control('LIBRARY.0').label == str(scratch / 'Private Library'), 'clicking a library folder reveals its full path')
    click(window, region, 'LIBRARY.0')
    yield 0.3
    check(control('LIBRARY.0').label.startswith(MASK), 'clicking it again masks it')
    press(window, 'ESC', *middle)
    yield 0.3
    export_dir = scratch / 'Private Export'
    cube.devil_painter.export_directory = str(export_dir)
    click(window, region, 'EXPORT')
    yield 0.4
    check(control('EXPORT_DIR').text == masked_path(str(export_dir)) and 'Users' not in control('EXPORT_DIR').text, 'the export folder is masked by default')
    click(window, region, 'EXPORT_DIR')
    yield 0.3
    check(editor._active.state.text.text == str(export_dir), 'clicking the export folder reveals it')
    press(window, 'ESC', *middle)
    yield 0.3
    click(window, region, 'BRIDGE_COMMAND')
    yield 0.2
    command = f'"{scratch / "Apps" / "viewer.exe"}" {{files}}'
    type_text(window, command, *spot(region, 'BRIDGE_COMMAND'))
    yield 0.3
    move(window, *spot(region, 'EXPORT_RUN'))
    yield 0.3
    shown_command = control('BRIDGE_COMMAND').text
    check(shown_command.endswith('{files}') and MASK in shown_command and 'Users' not in shown_command, f'the send-to-app command masks its path ({shown_command})')
    press(window, 'ESC', *middle)
    yield 0.3
    editor._active.message = f'Exported 3 textures to {export_dir}.'
    move(window, *middle)
    yield 0.4
    toast = editor._active.toast_rect
    check(toast is not None and not editor._active.toast_revealed, 'a message with a path shows as a masked toast')
    press(window, 'LEFTMOUSE', region.x + toast.x + toast.w / 2, region.y + toast.y + toast.h / 2)
    yield 0.3
    check(editor._active.toast_revealed, 'clicking the toast reveals the full path')

    click(window, region, 'CLOSE')
    yield 0.6
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI LAYOUT CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI layout test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
