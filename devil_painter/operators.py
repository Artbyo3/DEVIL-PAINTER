import bpy
from .document import texture_set


class DEVIL_PAINTER_OT_choose_export_folder(bpy.types.Operator):
    bl_idname = 'devil_painter.choose_export_folder'
    bl_label = 'Choose Folder'
    bl_description = 'Pick the folder Devil Painter exports textures to'
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        return texture_set(context.view_layer.objects.active) is not None

    def invoke(self, context, event):
        self.directory = texture_set(context.view_layer.objects.active).export_directory
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        texture_set(context.view_layer.objects.active).export_directory = self.directory
        return {'FINISHED'}


CLASSES = (DEVIL_PAINTER_OT_choose_export_folder,)
