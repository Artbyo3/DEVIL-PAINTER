from pathlib import Path
import bpy
from . import library
from .document import project_of, texture_set


class DEVIL_PAINTER_OT_choose_export_folder(bpy.types.Operator):
    bl_idname = 'devil_painter.choose_export_folder'
    bl_label = 'Choose Folder'
    bl_description = 'Pick the folder Devil Painter exports textures to'
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        return texture_set(context.view_layer.objects.active) is not None

    def invoke(self, context, event):
        self.directory = project_of(context.view_layer.objects.active).export_directory
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        project_of(context.view_layer.objects.active).export_directory = self.directory
        return {'FINISHED'}


class DEVIL_PAINTER_OT_choose_texture_folder(bpy.types.Operator):
    bl_idname = 'devil_painter.choose_texture_folder'
    bl_label = 'Choose Texture Folder'
    bl_description = 'Pick the folder of textures the Devil Painter shelf browses'
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        self.directory = library.texture_folder()
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        library.set_texture_folder(self.directory)
        return {'FINISHED'}


class DEVIL_PAINTER_OT_import_textures(bpy.types.Operator):
    bl_idname = 'devil_painter.import_textures'
    bl_label = 'Import Textures'
    bl_description = 'Copy image files into the Devil Painter texture library'
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        count = library.import_textures(Path(self.directory) / item.name for item in self.files)
        self.report({'INFO'}, f'Imported {count} textures into the library.')
        return {'FINISHED'}


CLASSES = (DEVIL_PAINTER_OT_choose_export_folder, DEVIL_PAINTER_OT_choose_texture_folder, DEVIL_PAINTER_OT_import_textures)
