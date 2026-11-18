bl_info = {
    "name": "Devil Painter", "author": "Artbyo3", "version": (0, 2, 1),
    "blender": (5, 2, 0), "location": "View3D > View > Devil Painter; Ctrl+Alt+P",
    "description": "Layer-based texture painting inside Blender", "category": "Paint",
}

def other_installed_copy():
    import sys
    import bpy
    registered = getattr(bpy.types, 'DEVIL_PAINTER_OT_editor', None)
    owner = registered.__module__.rpartition('.')[0] if registered is not None else __package__
    if owner == __package__:
        return None
    return getattr(sys.modules.get(owner), '__file__', None) or owner

def register():
    other = other_installed_copy()
    if other is not None:
        raise RuntimeError('Devil Painter is already enabled from ' + str(other) + '. Two installed copies break the editor. Disable or remove one copy in Preferences > Get Extensions, then restart Blender.')
    from . import ui
    ui.register()

def unregister():
    if other_installed_copy() is not None:
        return
    from . import ui
    ui.unregister()
