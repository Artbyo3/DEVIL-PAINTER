import math
import sys
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import autosave, editor, library, painting
from devil_painter.document import active_effect, active_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, close_cards, control, drag_slider, finish, press, reveal, run_journey, settle, shelf_index, spot, viewport


def send_characters(window, text, x, y):
    for character in text:
        if character == '.':
            window.event_simulate(type='NUMPAD_PERIOD', value='PRESS', x=int(x), y=int(y))
        else:
            window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)


def type_number(window, region, key, text, commit='RET', shift=False):
    click(window, region, key)
    yield from settle()
    edit = editor._active.state.text
    check(edit is not None and edit.numeric and edit.key == key and edit.selected, f'clicking {key} opens selected numeric entry')
    check(control(key).caret >= 0 and control(key).selected, f'{key} renders in active numeric edit state')
    x, y = spot(region, key)
    send_characters(window, text, x, y)
    window.event_simulate(type=commit, value='PRESS', x=int(x), y=int(y), shift=shift)
    yield from settle()


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
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

    yield from type_number(window, region, 'BRUSH_SIZE', '77')
    check(painting.brush_value(bpy.context.scene, 'size') == 77 and control('BRUSH_SIZE').text == '77 px',
          'typing into Size sets brush size and syncs the slider text')
    yield from type_number(window, region, 'BRUSH_SIZE', '9999')
    check(painting.brush_value(bpy.context.scene, 'size') == 500, 'typing above max clamps brush size to the slider max')
    yield from type_number(window, region, 'BRUSH_SIZE', '0')
    check(painting.brush_value(bpy.context.scene, 'size') == 1, 'typing below min clamps brush size to the slider min')
    yield from type_number(window, region, 'BRUSH_SIZE', '123', commit='ESC')
    check(editor._active.state.text is None and painting.brush_value(bpy.context.scene, 'size') == 1,
          'pressing Esc cancels typed entry and preserves the original brush size')
    drag_slider(window, region, 'BRUSH_SIZE', .2)
    yield from settle()
    dragged_size = painting.brush_value(bpy.context.scene, 'size')
    click(window, region, 'BRUSH_SIZE')
    yield from settle()
    check(editor._active.state.text is not None and editor._active.state.text.text == str(dragged_size),
          'clicking after dragging shows the dragged value in the numeric field')
    press(window, 'ESC', *middle)
    yield from settle()

    yield from type_number(window, region, 'BRUSH_STRENGTH', '35')
    check(abs(data.brush_opacity - .35) < 1e-4 and control('BRUSH_STRENGTH').text == '35%',
          'typing percentage into Opacity sets brush opacity')
    yield from type_number(window, region, 'BRUSHVAL.roughness', '.25')
    check(abs(data.brush_slots['roughness'].value - .25) < 1e-4 and control('BRUSHVAL.roughness').text == '0.25',
          'leading-decimal entry works on channel sliders')

    click(window, region, 'BRUSH_CARD')
    yield from settle()
    yield from type_number(window, region, 'BRUSH_FLOW', '40', commit='TAB')
    check(abs(data.brush_flow - .4) < 1e-4, 'Tab commits Flow')
    check(editor._active.state.text is not None and editor._active.state.text.key == 'BRUSH_SPACING',
          'Tab advances numeric focus to Spacing')
    x, y = spot(region, 'BRUSH_SPACING')
    send_characters(window, '25', x, y)
    window.event_simulate(type='TAB', value='PRESS', x=int(x), y=int(y), shift=True)
    yield from settle()
    check(abs(data.brush_spacing - 25.0) < 1e-4 and editor._active.state.text is not None and editor._active.state.text.key == 'BRUSH_FLOW',
          'Shift+Tab commits Spacing and moves focus back to Flow')
    press(window, 'ESC', *middle)
    yield from settle()
    check(editor._active.state.text is None and editor._active.state.popover is not None,
          'Esc cancels text editing without closing the open popover')
    yield from type_number(window, region, 'BRUSH_ANGLE', '135')
    check(abs(data.brush_angle - 135.0) < 1e-4, 'typing into Brush Angle commits degrees')
    click(window, region, 'SIZE_SPACE.WORLD')
    yield from settle()
    yield from close_cards(window, middle)
    yield from type_number(window, region, 'BRUSH_SIZE', '.35')
    check(abs(data.brush_world_size - .35) < 1e-4, 'typing a decimal sets world-space brush size')
    click(window, region, 'BRUSH_CARD')
    yield from settle()
    click(window, region, 'SIZE_SPACE.SCREEN')
    yield from settle()
    yield from close_cards(window, middle)

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer = active_layer(data)
    yield from reveal(window, region, 'OPACITY')
    yield from type_number(window, region, 'OPACITY', '60')
    check(abs(layer.opacity - .6) < 1e-4 and control('OPACITY').text == '60%', 'typing sets layer opacity')
    yield from reveal(window, region, 'VALUE.roughness')
    yield from type_number(window, region, 'VALUE.roughness', '0.37')
    check(abs(layer.slots['roughness'].value - .37) < 1e-4, 'typing sets fill channel roughness')
    yield from type_number(window, region, 'CHOPACITY.roughness', '75')
    check(abs(layer.slots['roughness'].opacity - .75) < 1e-4, 'typing sets per-channel opacity')

    yield from reveal(window, region, 'SOURCE.roughness')
    click(window, region, 'SOURCE.roughness')
    yield from settle()
    click(window, region, 'PICK_PATTERN.roughness')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Noise")}')
    yield from settle()
    yield from reveal(window, region, 'TILING')
    yield from type_number(window, region, 'TILING', '4.5')
    check(abs(layer.tiling - 4.5) < 1e-4, 'typing sets Tiling')
    yield from reveal(window, region, 'UV_OFFSET_X')
    yield from type_number(window, region, 'UV_OFFSET_X', '0.25', commit='TAB')
    check(abs(layer.uv_offset[0] - .25) < 1e-4 and editor._active.state.text is not None and editor._active.state.text.key == 'UV_OFFSET_Y',
          'Tab commits Offset X and moves to Offset Y')
    x, y = spot(region, 'UV_OFFSET_Y')
    send_characters(window, '.75', x, y)
    window.event_simulate(type='NUMPAD_ENTER', value='PRESS', x=int(x), y=int(y))
    yield from settle()
    check(abs(layer.uv_offset[1] - .75) < 1e-4, 'Numpad Enter commits Offset Y')
    yield from reveal(window, region, 'UV_SPIN')
    yield from type_number(window, region, 'UV_SPIN', '90')
    check(abs(math.degrees(layer.uv_rotation) - 90.0) < 1e-3, 'typing sets UV Spin')
    yield from reveal(window, region, 'SCALE.roughness')
    yield from type_number(window, region, 'SCALE.roughness', '12.5')
    check(abs(layer.slots['roughness'].scale - 12.5) < 1e-4, 'typing sets pattern scale')

    yield from reveal(window, region, 'ADD_FX_MASK')
    click(window, region, 'ADD_FX_MASK')
    yield from settle()
    click(window, region, 'NEW_FX.MASK.LEVELS')
    yield from settle()
    effect = active_effect(data)
    yield from reveal(window, region, 'FX_opacity')
    yield from type_number(window, region, 'FX_opacity', '80')
    check(abs(effect.opacity - .8) < 1e-4, 'typing sets effect opacity')
    yield from reveal(window, region, 'FX_gamma')
    yield from type_number(window, region, 'FX_gamma', '1.8')
    check(abs(effect.gamma - 1.8) < 1e-4, 'typing sets Levels gamma')

    yield from reveal(window, region, 'ADD_FX_MASK')
    click(window, region, 'ADD_FX_MASK')
    yield from settle()
    click(window, region, 'NEW_FX.MASK.GENERATOR')
    yield from settle()
    click(window, region, 'GENERATOR')
    yield from settle()
    click(window, region, 'SET_GENERATOR.NOISE')
    yield from settle()
    gen = active_effect(data)
    yield from reveal(window, region, 'GEN_SCALE')
    yield from type_number(window, region, 'GEN_SCALE', '45')
    check(abs(gen.gen_scale - 45.0) < 1e-4, 'typing sets generator scale')

    click(window, region, 'SYMMETRY')
    yield from settle()
    yield from type_number(window, region, 'RADIAL', '6')
    check(data.brush_radial == 6, 'typing sets radial copies')
    yield from type_number(window, region, 'RADIAL', '99')
    check(data.brush_radial == 16, 'radial copies clamp to slider max')
    yield from close_cards(window, middle)

    click(window, region, 'STENCIL_CARD')
    yield from settle()
    click(window, region, 'STENCIL_TEXT')
    yield from settle()
    x, y = spot(region, 'STENCIL_TEXT')
    send_characters(window, 'DP', x, y)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))
    yield from settle()
    yield from type_number(window, region, 'STENCIL_SCALE', '1.25')
    yield from type_number(window, region, 'STENCIL_ANGLE', '45')
    yield from type_number(window, region, 'STENCIL_X', '.3')
    yield from type_number(window, region, 'STENCIL_Y', '.7')
    check(abs(data.stencil_scale - 1.25) < 1e-4 and abs(data.stencil_angle - 45.0) < 1e-4
          and abs(data.stencil_x - .3) < 1e-4 and abs(data.stencil_y - .7) < 1e-4,
          'typing sets every stencil numeric field')
    yield from close_cards(window, middle)

    click(window, region, 'BAKE')
    yield from settle()
    yield from type_number(window, region, 'BAKE_SAMPLES', '32')
    yield from type_number(window, region, 'BAKE_EXTRUSION', '15.5')
    yield from type_number(window, region, 'BAKE_AO_DISTANCE', '50')
    yield from type_number(window, region, 'BAKE_AO_SPREAD', '90')
    check(data.bake_samples == 32 and abs(data.bake_extrusion - .155) < 1e-4
          and abs(data.bake_ao_distance - .5) < 1e-4 and abs(data.bake_ao_spread - 90.0) < 1e-4,
          'typing sets bake card numeric fields')
    yield from close_cards(window, middle)

    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'HEIGHT_DISP')
    yield from settle()
    yield from type_number(window, region, 'PHYS_SIZE', '2.5')
    yield from type_number(window, region, 'NORMAL_STRENGTH', '1.4')
    yield from type_number(window, region, 'DISP_SCALE', '0.25')
    yield from type_number(window, region, 'DISP_SUBDIV', '4')
    yield from type_number(window, region, 'AUTOSAVE_MINUTES', '10')
    check(abs(cube.devil_painter.physical_size - 2.5) < 1e-4 and abs(data.normal_strength - 1.4) < 1e-4
          and abs(data.displacement_scale - .25) < 1e-4 and data.displacement_subdivision == 4 and autosave.minutes() == 10,
          'typing sets project card numeric fields')
    yield from close_cards(window, middle)

    click(window, region, 'VIEWPORT')
    yield from settle()
    shading = area.spaces.active.shading
    view = bpy.context.scene.view_settings
    yield from type_number(window, region, 'ENV_ROTATION', '-90')
    yield from type_number(window, region, 'ENV_STRENGTH', '1.5')
    yield from type_number(window, region, 'CAMERA_FOV', '35')
    yield from type_number(window, region, 'CM_EXPOSURE', '-1.25')
    yield from type_number(window, region, 'CM_GAMMA', '1.4')
    yield from type_number(window, region, 'PREVIEW_SAMPLES', '64')
    check(abs(math.degrees(shading.studiolight_rotate_z) + 90.0) < 1e-3 and abs(shading.studiolight_intensity - 1.5) < 1e-4
          and abs(area.spaces.active.lens - 35.0) < 1e-4 and abs(view.exposure + 1.25) < 1e-4
          and abs(view.gamma - 1.4) < 1e-4 and bpy.context.scene.cycles.preview_samples == 64,
          'typing sets viewport card numeric fields')
    yield from type_number(window, region, 'CM_GAMMA', 'notanumber')
    check(abs(view.gamma - 1.4) < 1e-4, 'invalid numeric input keeps the previous value')
    yield from close_cards(window, middle)

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    print('ALL GUI NUMERIC FIELD CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI numeric fields test')
