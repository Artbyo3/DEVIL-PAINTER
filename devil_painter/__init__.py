import bpy

bl_info = {
    "name": "Devil Painter",
    "author": "Artbyo3",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Devil Painter",
    "description": "Layer-based texture painting inside Blender",
    "category": "Paint",
}


class DEVIL_PAINTER_PT_main(bpy.types.Panel):
    bl_label = "Devil Painter"
    bl_idname = "DEVIL_PAINTER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Devil Painter"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Devil Painter")


CLASSES = (DEVIL_PAINTER_PT_main,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
