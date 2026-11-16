bl_info = {
    "name": "Devil Painter",
    "author": "Artbyo3",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > View > Devil Painter; Ctrl+Alt+P",
    "description": "Layer-based texture painting inside Blender",
    "category": "Paint",
}


def register():
    from . import editor
    editor.register()


def unregister():
    from . import editor
    editor.unregister()
