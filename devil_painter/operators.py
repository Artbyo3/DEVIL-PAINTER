import bpy
from . import actions, compositing
from .document import active_layer, texture_set
from .painting import brush_value, set_brush_value


def painted_object(context):
    obj = context.view_layer.objects.active
    return obj, texture_set(obj)


class DEVIL_PAINTER_OT_export_textures(bpy.types.Operator):
    bl_idname = 'devil_painter.export_textures'
    bl_label = 'Export Textures'
    bl_description = 'Write the Base Color, Roughness and Metallic textures as PNG files'
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        return painted_object(context)[1] is not None

    def invoke(self, context, event):
        if not self.directory:
            self.directory = bpy.path.abspath('//textures/') if bpy.data.filepath else ''
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj, data = painted_object(context)
        try:
            self.report({'INFO'}, actions.export(context, obj, data, bpy.path.abspath(self.directory)))
        except (OSError, ValueError, RuntimeError) as failure:
            self.report({'ERROR'}, str(failure))
            return {'CANCELLED'}
        return {'FINISHED'}


class DEVIL_PAINTER_OT_pick_color(bpy.types.Operator):
    bl_idname = 'devil_painter.pick_color'
    bl_label = 'Color'
    bl_description = 'Choose the brush or fill color'
    bl_options = {'REGISTER', 'UNDO'}
    target: bpy.props.EnumProperty(items=(('BRUSH', 'Brush', ''), ('LAYER', 'Layer', '')))
    brush_color: bpy.props.FloatVectorProperty(subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0)
    layer_color: bpy.props.FloatVectorProperty(subtype='COLOR', size=3, min=0.0, max=1.0)

    @classmethod
    def poll(cls, context):
        return painted_object(context)[1] is not None

    def invoke(self, context, event):
        obj, data = painted_object(context)
        if self.target == 'BRUSH':
            self.brush_color = brush_value(context, 'color')
        else:
            self.layer_color = active_layer(data).color
        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        prop = 'brush_color' if self.target == 'BRUSH' else 'layer_color'
        self.layout.template_color_picker(self, prop, value_slider=True)
        self.layout.prop(self, prop, text='')

    def execute(self, context):
        obj, data = painted_object(context)
        if self.target == 'BRUSH':
            set_brush_value(context, 'color', self.brush_color)
        else:
            active_layer(data).color = self.layer_color
            compositing.update_values(data)
        return {'FINISHED'}


class DEVIL_PAINTER_OT_rename_layer(bpy.types.Operator):
    bl_idname = 'devil_painter.rename_layer'
    bl_label = 'Rename Layer'
    bl_options = {'REGISTER', 'UNDO'}
    name: bpy.props.StringProperty(name='Name')

    @classmethod
    def poll(cls, context):
        data = painted_object(context)[1]
        return data is not None and active_layer(data) is not None

    def invoke(self, context, event):
        self.name = active_layer(painted_object(context)[1]).name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        active_layer(painted_object(context)[1]).name = self.name.strip() or 'Layer'
        return {'FINISHED'}


CLASSES = (DEVIL_PAINTER_OT_export_textures, DEVIL_PAINTER_OT_pick_color, DEVIL_PAINTER_OT_rename_layer)
