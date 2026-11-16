import bpy
from bpy.app.handlers import persistent
from . import document, operators
from .editor import DEVIL_PAINTER_OT_editor, close_active


def launch_menu(self, context):
    self.layout.separator()
    self.layout.operator(DEVIL_PAINTER_OT_editor.bl_idname, text='Devil Painter', icon='BRUSH_DATA')

KEYMAPS = []


@persistent
def on_load(_):
    close_active()


@persistent
def on_save(_):
    for obj in bpy.data.objects:
        data = document.texture_set(obj)
        if data is None:
            continue
        for layer in data.layers:
            for image in (layer.image, layer.mask):
                if image is not None and (image.is_dirty or image.packed_file is None):
                    image.pack()


classes = (DEVIL_PAINTER_OT_editor,) + operators.CLASSES


def register():
    document.register()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(on_load)
    bpy.app.handlers.save_pre.append(on_save)
    bpy.types.VIEW3D_MT_view.append(launch_menu)
    config = bpy.context.window_manager.keyconfigs.addon
    if config:
        keymap = config.keymaps.new(name='3D View', space_type='VIEW_3D')
        item = keymap.keymap_items.new(DEVIL_PAINTER_OT_editor.bl_idname, 'P', 'PRESS', ctrl=True, alt=True)
        KEYMAPS.append((keymap, item))


def unregister():
    close_active()
    for handlers, handler in ((bpy.app.handlers.load_pre, on_load), (bpy.app.handlers.save_pre, on_save)):
        if handler in handlers:
            handlers.remove(handler)
    bpy.types.VIEW3D_MT_view.remove(launch_menu)
    for keymap, item in KEYMAPS:
        keymap.keymap_items.remove(item)
    KEYMAPS.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    document.unregister()
