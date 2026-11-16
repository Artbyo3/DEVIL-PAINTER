import bpy
from bpy.app.handlers import persistent
from .editor import DEVIL_PAINTER_OT_editor, close_active


def launch_menu(self, context):
    self.layout.separator()
    self.layout.operator(DEVIL_PAINTER_OT_editor.bl_idname, text='Devil Painter', icon='BRUSH_DATA')

KEYMAPS = []


@persistent
def on_load(_):
    close_active()


classes = (DEVIL_PAINTER_OT_editor,)
PROPERTIES = ('dp_ui_rect',)


def register():
    Scene = bpy.types.Scene
    Scene.dp_ui_rect = bpy.props.FloatVectorProperty(name='Editor window bounds', size=4, default=(-1, -1, 0, 0))
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(on_load)
    bpy.types.VIEW3D_MT_view.append(launch_menu)
    config = bpy.context.window_manager.keyconfigs.addon
    if config:
        keymap = config.keymaps.new(name='3D View', space_type='VIEW_3D')
        item = keymap.keymap_items.new(DEVIL_PAINTER_OT_editor.bl_idname, 'P', 'PRESS', ctrl=True, alt=True)
        KEYMAPS.append((keymap, item))


def unregister():
    close_active()
    if on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(on_load)
    bpy.types.VIEW3D_MT_view.remove(launch_menu)
    for keymap, item in KEYMAPS:
        keymap.keymap_items.remove(item)
    KEYMAPS.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for name in PROPERTIES:
        delattr(bpy.types.Scene, name)
