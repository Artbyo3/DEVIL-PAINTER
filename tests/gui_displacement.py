import sys
from pathlib import Path
import bpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import compositing, editor
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, drag_slider, finish, has, press, run_journey, settle, viewport


def material_output(data):
    return next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')


def journey():
    prepare_scratch()
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

    tree_nodes = data.material.node_tree.nodes
    check(not data.height_displacement and data.material.displacement_method == 'BUMP', 'height displacement starts off in bump-only mode')
    check('shader.bump' in tree_nodes and 'shader.displacement' not in tree_nodes and not material_output(data).inputs['Displacement'].is_linked,
          'default material routes height to bump only')
    check(compositing.DISPLACEMENT_MODIFIER not in cube.modifiers, 'no preview subdivision modifier is present while displacement is off')

    click(window, region, 'PROJECT')
    yield from settle()
    check(has('HEIGHT_DISP') and not control('HEIGHT_DISP').active and not has('DISP_SCALE') and not has('DISP_SUBDIV'),
          'Project card shows the Height displacement toggle without its sliders while off')

    click(window, region, 'HEIGHT_DISP')
    yield from settle()
    tree_nodes = data.material.node_tree.nodes
    output = material_output(data)
    check(data.height_displacement and control('HEIGHT_DISP').active and has('DISP_SCALE') and has('DISP_SUBDIV'),
          'enabling Height displacement reveals Scale and Subdivision controls')
    check(data.material.displacement_method == 'BOTH' and 'shader.bump' not in tree_nodes and 'shader.displacement' in tree_nodes,
          'Height displacement switches the material to displacement + bump and drops the duplicate bump node')
    check(output.inputs['Displacement'].is_linked and output.inputs['Displacement'].links[0].from_node.name == 'shader.displacement',
          'Material Output Displacement links from the height displacement node')
    disp_node = tree_nodes['shader.displacement']
    check(abs(disp_node.inputs['Midlevel'].default_value - compositing.DISPLACEMENT_MIDLEVEL) < 1e-5
          and abs(disp_node.inputs['Scale'].default_value - data.displacement_scale * data.bump_strength) < 1e-5,
          'displacement node uses the 0.5 midlevel and texture-set displacement scale')
    modifier = cube.modifiers.get(compositing.DISPLACEMENT_MODIFIER)
    check(modifier is not None and modifier.type == 'SUBSURF' and modifier.subdivision_type == 'SIMPLE'
          and modifier.levels == data.displacement_subdivision and modifier.render_levels == 0
          and modifier.show_viewport and not modifier.show_render,
          'enabling Height displacement adds a viewport-only Simple subdivision modifier for tessellation preview')

    drag_slider(window, region, 'DISP_SCALE', .6)
    yield from settle()
    check(abs(data.displacement_scale - .3) < .05
          and abs(data.material.node_tree.nodes['shader.displacement'].inputs['Scale'].default_value - data.displacement_scale * data.bump_strength) < 1e-5,
          'dragging Scale updates the displacement node scale live')

    drag_slider(window, region, 'DISP_SUBDIV', .5)
    yield from settle()
    check(data.displacement_subdivision == 3 and cube.modifiers[compositing.DISPLACEMENT_MODIFIER].levels == 3,
          'dragging Subdivision updates the viewport tessellation level')

    drag_slider(window, region, 'DISP_SUBDIV', .02)
    yield from settle()
    check(data.displacement_subdivision == 0 and compositing.DISPLACEMENT_MODIFIER not in cube.modifiers and data.material.displacement_method == 'BOTH',
          'setting Subdivision to 0 removes the preview modifier while keeping shader displacement active')

    drag_slider(window, region, 'DISP_SUBDIV', 2 / 6)
    yield from settle()
    check(data.displacement_subdivision == 2 and cube.modifiers[compositing.DISPLACEMENT_MODIFIER].levels == 2,
          'raising Subdivision restores the preview modifier at the requested level')

    drag_slider(window, region, 'BUMP_STRENGTH', .5)
    yield from settle()
    check(abs(data.material.node_tree.nodes['shader.displacement'].inputs['Scale'].default_value - data.displacement_scale * data.bump_strength) < 1e-4,
          'Height strength scales the height displacement preview')
    drag_slider(window, region, 'BUMP_STRENGTH', .98)
    yield from settle()

    press(window, 'ESC', *middle)
    yield from settle()
    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.height')
    yield from settle()
    check(not material_output(data).inputs['Displacement'].is_linked, 'soloing a channel disconnects displacement in the viewport')
    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.')
    yield from settle()
    check(material_output(data).inputs['Displacement'].is_linked, 'returning to Material view restores displacement')

    click(window, region, 'CHANNELS')
    yield from settle()
    click(window, region, 'CHANSET.height')
    yield from settle()
    check(data.material.displacement_method == 'BUMP' and compositing.DISPLACEMENT_MODIFIER not in cube.modifiers
          and not material_output(data).inputs['Displacement'].is_linked,
          'disabling the height channel pauses displacement and removes the preview modifier')
    click(window, region, 'CHANSET.height')
    yield from settle()
    check(data.material.displacement_method == 'BOTH' and compositing.DISPLACEMENT_MODIFIER in cube.modifiers
          and material_output(data).inputs['Displacement'].is_linked,
          're-enabling the height channel restores displacement and tessellation')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'HEIGHT_DISP')
    yield from settle()
    tree_nodes = data.material.node_tree.nodes
    check(not data.height_displacement and not has('DISP_SCALE') and not has('DISP_SUBDIV'),
          'toggling Height displacement off hides its sliders')
    check(data.material.displacement_method == 'BUMP' and 'shader.bump' in tree_nodes and 'shader.displacement' not in tree_nodes
          and not material_output(data).inputs['Displacement'].is_linked and compositing.DISPLACEMENT_MODIFIER not in cube.modifiers,
          'toggling Height displacement off restores bump-only shading and removes the preview modifier')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI DISPLACEMENT CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI height displacement test')
