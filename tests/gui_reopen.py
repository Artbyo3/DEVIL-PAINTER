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
from devil_painter.editor import HIDDEN_REGIONS
from tools.workspace import prepare_scratch
from tests.gui_harness import settle, until

TIMEOUT = 600
STARTED = time.time()
TOGGLES = dict(fullscreen=dict(ctrl=True, alt=True), maximize=dict(ctrl=True))


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def finish(code):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def view(window):
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return area, region


def middle(window):
    area, _ = view(window)
    return area.x + area.width / 2, area.y + area.height / 2


def press(window, kind, **modifiers):
    x, y = middle(window)
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
    window.event_simulate(type=kind, value='PRESS', x=int(x), y=int(y), **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=int(x), y=int(y), **modifiers)


def wiggle(window):
    x, y = middle(window)
    for step in range(6):
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x + step * 5), y=int(y))


def regions(window):
    space = view(window)[0].spaces.active
    return {name: getattr(space, name) for name in HIDDEN_REGIONS if hasattr(space, name) and not space.is_property_readonly(name)}


def regions_shown(window):
    return all(regions(window).values())


def open_now(window):
    return editor._active is not None and [op.bl_idname for op in window.modal_operators].count('DEVIL_PAINTER_OT_editor') == 1


def closed_now(window):
    return editor._active is None and 'DEVIL_PAINTER_OT_editor' not in [op.bl_idname for op in window.modal_operators]


def given_back(window):
    yield from until(lambda: window.screen.show_fullscreen or not editor._pending_regions, 'Devil Painter to give back the regions it hid before the screen toggle')


def opens(window, where):
    yield from given_back(window)
    press(window, 'P', ctrl=True, alt=True)
    yield from until(lambda: open_now(window) and not any(regions(window).values()), 'Blender to finish hiding its regions')
    check(open_now(window) and editor._active.workspace is not None and not regions_shown(window),
          f'Ctrl+Alt+P opens Devil Painter {where} and hides the Blender regions')


def fails_once(window, where, patch):
    yield from opens(window, f'before the {where} fault')
    cls = editor.DEVIL_PAINTER_OT_editor
    original = getattr(cls, patch)
    calls = []

    def broken(self, *args):
        calls.append(time.monotonic())
        raise KeyError('probe fault')

    setattr(cls, patch, broken)
    try:
        for _ in range(10):
            wiggle(window)
            yield from settle()
    finally:
        setattr(cls, patch, original)
    check(closed_now(window) and regions_shown(window), f'an unexpected {where} error closes Devil Painter through its normal cleanup and gives back the regions')
    check(len(calls) == 1, f'the failing {where} code runs once instead of on every frame or event ({len(calls)} calls)')
    yield from opens(window, f'again after the {where} fault')
    press(window, 'P', ctrl=True, alt=True)
    yield from settle()
    check(closed_now(window), f'Devil Painter closes normally after the {where} fault')


def damaged_settings(window):
    path = library.library_root() / library.SETTINGS_FILE
    damaged = path.with_name(path.name + '.damaged')
    damaged.unlink(missing_ok=True)
    truncated = '{"texture_folder": "", "materials": [{"name": "Half'
    path.write_text(truncated, encoding='utf-8')
    library._cache.pop('settings', None)
    yield from opens(window, 'with a truncated settings file')
    message = editor._active.message
    check('settings' in message.lower() and damaged.name in message, f'Devil Painter says the settings were damaged and where the old file went: {message!r}')
    check(damaged.read_text(encoding='utf-8') == truncated, 'the damaged settings file is set aside untouched')
    press(window, 'P', ctrl=True, alt=True)
    yield from settle()
    check(closed_now(window), 'Ctrl+Alt+P closes it')
    check(not path.exists(), 'the damaged file no longer sits where the settings are read')
    library.save_settings()
    saved = json.loads(path.read_text(encoding='utf-8'))
    check(isinstance(saved, dict) and saved['materials'] == [], 'the next save writes a complete settings file with defaults')
    check(not list(path.parent.glob(path.name + '.*.tmp')), 'no temporary settings file is left behind')
    library._cache.pop('settings', None)
    yield from opens(window, 'after the settings were repaired')
    check(editor._active.message == '', 'the damaged-settings notice is shown only once')
    press(window, 'P', ctrl=True, alt=True)
    yield from settle()
    check(closed_now(window), 'Ctrl+Alt+P closes it again')


def journey():
    prepare_scratch()
    devil_painter.register()
    yield from settle()
    window = bpy.context.window_manager.windows[0]
    normal = window.screen.name
    check(regions_shown(window), 'the Blender regions start visible')

    for cycle in range(2):
        yield from opens(window, f'(normal cycle {cycle + 1})')
        press(window, 'P', ctrl=True, alt=True)
        yield from settle()
        check(closed_now(window) and regions_shown(window), 'Ctrl+Alt+P closes it, leaves no stale editor and restores the regions')

    for mode, modifiers in TOGGLES.items():
        press(window, 'SPACE', **modifiers)
        yield from settle()
        toggled = window.screen.name
        press(window, 'SPACE', **modifiers)
        yield from settle()
        check(toggled != normal and window.screen.name == normal and regions_shown(window), f'without Devil Painter, {mode} toggles on and back')

        yield from opens(window, f'before {mode}')
        press(window, 'SPACE', **modifiers)
        yield from settle()
        wiggle(window)
        yield from settle()
        check(window.screen.name != normal, f'the {mode} toggle replaces the screen')
        yield from given_back(window)
        check(closed_now(window) and regions_shown(window),
              f'hiding all UI with {mode} closes Devil Painter completely and gives back every region it hid {regions(window)}')

        yield from opens(window, f'inside {mode}')
        press(window, 'P', ctrl=True, alt=True)
        yield from settle()
        yield from given_back(window)
        check(closed_now(window) and regions_shown(window), f'it closes again inside {mode} and gives the regions back {regions(window)}')
        yield from opens(window, f'inside {mode} a second time')

        press(window, 'SPACE', **modifiers)
        yield from settle()
        wiggle(window)
        yield from settle()
        check(window.screen.name == normal, f'the {mode} toggle returns to the normal screen')
        check(open_now(window) is False, 'the editor opened inside the toggled screen ends when that screen goes away')
        yield from given_back(window)
        check(closed_now(window) and regions_shown(window),
              f'leaving {mode} with Devil Painter open closes it completely and restores the regions')

        yield from opens(window, f'after leaving {mode}')
        press(window, 'SPACE', **modifiers)
        yield from settle()
        press(window, 'SPACE', **modifiers)
        yield from settle()
        wiggle(window)
        yield from settle()
        yield from given_back(window)
        check(window.screen.name == normal and closed_now(window) and regions_shown(window),
              f'toggling {mode} on and off quickly leaves no stale editor and the regions visible')
        yield from opens(window, f'after the quick {mode} round trip')
        _, region = view(window)
        close = next(item for item in reversed(editor._active.workspace.controls) if item.key == 'CLOSE').rect
        x, y = region.x + close.x + close.w / 2, region.y + close.y + close.h / 2
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
        window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
        window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x), y=int(y))
        yield from settle()
        yield from given_back(window)
        check(closed_now(window) and regions_shown(window), 'the close button still closes it cleanly')

    yield from damaged_settings(window)
    yield from fails_once(window, 'layout', 'make_layout')
    yield from fails_once(window, 'event', 'handle_event')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI REOPEN CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI reopen test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
