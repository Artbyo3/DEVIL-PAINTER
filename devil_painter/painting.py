import bpy
from .document import paint_target

BRUSH_LIBRARY = 'brushes/essentials_brushes-mesh_texture.blend/Brush/'
TOOLS = (('PAINT', 'Paint', 'Paint Soft', 'B'), ('ERASE', 'Erase', 'Erase Soft', 'E'), ('FILL', 'Fill', 'Fill', 'G'),
         ('BLUR', 'Blur', 'Blur', ''), ('SMEAR', 'Smear', 'Smear', ''), ('CLONE', 'Clone', 'Clone', ''))
BRUSH_NAMES = {key: brush for key, _, brush, _ in TOOLS}


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


def activate_tool(context, tool):
    bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier=BRUSH_LIBRARY + BRUSH_NAMES[tool])


def active_tool(context):
    brush = context.tool_settings.image_paint.brush
    name = brush.name if brush else ''
    return next((key for key, _, brush_name, _ in TOOLS if name == brush_name), None)


def update_canvas(context, data):
    context.tool_settings.image_paint.canvas = paint_target(data)
