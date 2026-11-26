import bpy
from . import compositing
from .document import active_layer, active_tile, editing_content, paint_target
from .tiles import variant

BRUSH_LIBRARY = 'brushes/essentials_brushes-mesh_texture.blend/Brush/'
TOOLS = (('PAINT', 'Paint', 'Paint Soft', 'B'), ('ERASE', 'Erase', 'Erase Soft', 'E'), ('FILL', 'Fill', 'Fill', 'G'),
         ('BLUR', 'Blur', 'Blur', ''), ('SMEAR', 'Smear', 'Smear', ''), ('CLONE', 'Clone', 'Clone', ''))
BRUSH_NAMES = {key: brush for key, _, brush, _ in TOOLS}
STROKE_TOOLS = {'PAINT', 'FILL'}
BUFFER_TOOLS = {'PAINT', 'FILL', 'ERASE', 'BLUR', 'SMEAR', 'CLONE'}
NATIVE_TYPES = {'PAINT': ('DRAW', 'MIX'), 'FILL': ('FILL', 'MIX'), 'ERASE': ('DRAW', 'ERASE_ALPHA'), 'BLUR': ('SOFTEN', 'MIX'),
                'SMEAR': ('SMEAR', 'MIX'), 'CLONE': ('CLONE', 'MIX')}
DEVIL_PREFIX = 'DP '


def brush_source(holder, name):
    paint = holder.tool_settings.image_paint
    brush = paint.brush
    return paint.unified_paint_settings if brush is None or getattr(brush, 'use_unified_' + name) else brush


def brush_value(holder, name):
    return getattr(brush_source(holder, name), name)


def set_brush_value(holder, name, value):
    setattr(brush_source(holder, name), name, value)


def enter_paint_mode(context, obj):
    if context.view_layer.objects.active is not obj:
        context.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.mode != 'TEXTURE_PAINT':
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    paint = context.tool_settings.image_paint
    paint.mode = 'IMAGE'
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.type = 'MATERIAL'


def devil_brush_name(tool):
    return DEVIL_PREFIX + next(label for key, label, _, _ in TOOLS if key == tool)


def activate_tool(context, tool):
    name = devil_brush_name(tool)
    local = bpy.data.brushes.get((name, None))
    if local is None:
        bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier=BRUSH_LIBRARY + BRUSH_NAMES[tool])
        local = context.tool_settings.image_paint.brush.copy()
        local.name = name
        local.asset_mark()
    bpy.ops.brush.asset_activate(asset_library_type='LOCAL', relative_asset_identifier='Brush/' + local.name)


def active_tool(context):
    brush = context.tool_settings.image_paint.brush
    name = brush.name if brush else ''
    return next((key for key, label, brush_name, _ in TOOLS if name in {brush_name, DEVIL_PREFIX + label}), None)


def uses_stroke_buffer(context, data):
    layer = active_layer(data)
    return (layer is not None and layer.kind == 'PAINT' and editing_content(data) and data.stroke is not None and data.quick_mask is None and not data.bake_paint
            and active_tool(context) in BUFFER_TOOLS)


def set_brush_mode(context, tool, buffered):
    brush = context.tool_settings.image_paint.brush
    if brush is None or brush.library is not None or tool not in NATIVE_TYPES:
        return
    kind, blend = NATIVE_TYPES['PAINT'] if buffered and tool != 'FILL' else NATIVE_TYPES[tool]
    if brush.image_brush_type != kind:
        brush.image_brush_type = kind
    if brush.blend != blend:
        brush.blend = blend


def update_canvas(context, data):
    buffered = uses_stroke_buffer(context, data)
    owner = data.active_uid if buffered else ''
    tool = active_tool(context) or ''
    set_brush_mode(context, tool, buffered)
    if data.stroke_owner != owner or data.stroke_tool != tool or data.material is None:
        data.stroke_owner, data.stroke_tool = owner, tool
        compositing.sync(data)
    context.tool_settings.image_paint.canvas = data.stroke if buffered else variant(data, paint_target(data), active_tile(data))
