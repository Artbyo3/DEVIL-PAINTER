import bpy
from . import compositing
from .document import active_layer, active_tile, paint_target
from .tiles import variant

BRUSH_LIBRARY = 'brushes/essentials_brushes-mesh_texture.blend/Brush/'
TOOLS = (('PAINT', 'Paint', 'Paint Soft', 'B'), ('ERASE', 'Erase', 'Erase Soft', 'E'), ('FILL', 'Fill', 'Fill', 'G'),
         ('BLUR', 'Blur', 'Blur', ''), ('SMEAR', 'Smear', 'Smear', ''), ('CLONE', 'Clone', 'Clone', ''))
BRUSH_NAMES = {key: brush for key, _, brush, _ in TOOLS}
STROKE_TOOLS = {'PAINT', 'FILL'}
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
    return (layer is not None and layer.kind == 'PAINT' and data.target == 'CONTENT' and data.stroke is not None and data.quick_mask is None
            and active_tool(context) in STROKE_TOOLS)


def update_canvas(context, data):
    buffered = uses_stroke_buffer(context, data)
    owner = data.active_uid if buffered else ''
    if data.stroke_owner != owner:
        data.stroke_owner = owner
        compositing.sync(data)
    context.tool_settings.image_paint.canvas = data.stroke if buffered else variant(data, paint_target(data), active_tile(data))
