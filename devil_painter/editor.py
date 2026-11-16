import blf
import bpy
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

TITLE = 'Devil Painter'
HINT = 'Esc to close'
MARGIN = 16
BAR_HEIGHT = 40
TEXT_SIZE = 13
SURFACE_COLOR = (0.09, 0.09, 0.1, 0.94)
BAR_COLOR = (0.14, 0.14, 0.16, 1.0)
TITLE_COLOR = (0.93, 0.93, 0.95, 1.0)
HINT_COLOR = (0.6, 0.6, 0.64, 1.0)
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
KEYMAPS = []
_active = None


def close_active():
    if _active is not None:
        _active.cleanup()


def editor_frame(region):
    scale = bpy.context.preferences.system.ui_scale
    margin, bar_height = MARGIN * scale, BAR_HEIGHT * scale
    surface = (margin, margin, max(region.width - 2 * margin, 0), max(region.height - 2 * margin, 0))
    bar = (surface[0], surface[1] + max(surface[3] - bar_height, 0), surface[2], min(bar_height, surface[3]))
    return surface, bar, scale


def contains(rect, x, y):
    return rect[0] <= x <= rect[0] + rect[2] and rect[1] <= y <= rect[1] + rect[3]


def fill(shader, rect, color):
    x, y, w, h = rect
    batch = batch_for_shader(shader, 'TRIS', {'pos': ((x, y), (x + w, y), (x + w, y + h), (x, y + h))}, indices=((0, 1, 2), (0, 2, 3)))
    shader.uniform_float('color', color)
    batch.draw(shader)


def text(value, x, y, size, color):
    blf.size(0, size)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, value)


class DEVIL_PAINTER_OT_editor(bpy.types.Operator):
    bl_idname = 'devil_painter.editor'
    bl_label = 'Devil Painter'
    bl_description = 'Open the Devil Painter editor over the 3D viewport'
    _handle = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        global _active
        if _active is not None:
            _active.cleanup()
            return {'FINISHED'}
        self._area = context.area
        self._region = next(region for region in context.area.regions if region.type == 'WINDOW')
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        _active = self
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if _active is not self:
            return {'FINISHED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self.cleanup()
            return {'FINISHED'}
        if any(token in event.type for token in POINTER_TOKENS) and self.pointer_inside(event):
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def pointer_inside(self, event):
        try:
            region = self._region
            surface = editor_frame(region)[0]
            return contains(surface, event.mouse_x - region.x, event.mouse_y - region.y)
        except ReferenceError:
            self.cleanup()
            return False

    def draw_overlay(self):
        if bpy.context.area != self._area:
            return
        surface, bar, scale = editor_frame(self._region)
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        fill(shader, surface, SURFACE_COLOR)
        fill(shader, bar, BAR_COLOR)
        gpu.state.blend_set('NONE')
        size = TEXT_SIZE * scale
        baseline = bar[1] + (bar[3] - size) / 2
        text(TITLE, bar[0] + MARGIN * scale, baseline, size, TITLE_COLOR)
        blf.size(0, size)
        hint_width = blf.dimensions(0, HINT)[0]
        text(HINT, bar[0] + bar[2] - MARGIN * scale - hint_width, baseline, size, HINT_COLOR)

    def cleanup(self):
        global _active
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if _active is self:
            _active = None
        try:
            self._area.tag_redraw()
        except ReferenceError:
            pass


def launch_menu(self, context):
    self.layout.separator()
    self.layout.operator(DEVIL_PAINTER_OT_editor.bl_idname, text=TITLE, icon='BRUSH_DATA')


@persistent
def on_load(_):
    close_active()


def register():
    bpy.utils.register_class(DEVIL_PAINTER_OT_editor)
    bpy.types.VIEW3D_MT_view.append(launch_menu)
    bpy.app.handlers.load_pre.append(on_load)
    config = bpy.context.window_manager.keyconfigs.addon
    if config:
        keymap = config.keymaps.new(name='3D View', space_type='VIEW_3D')
        item = keymap.keymap_items.new(DEVIL_PAINTER_OT_editor.bl_idname, 'P', 'PRESS', ctrl=True, alt=True)
        KEYMAPS.append((keymap, item))


def unregister():
    close_active()
    for keymap, item in KEYMAPS:
        keymap.keymap_items.remove(item)
    KEYMAPS.clear()
    if on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(on_load)
    bpy.types.VIEW3D_MT_view.remove(launch_menu)
    bpy.utils.unregister_class(DEVIL_PAINTER_OT_editor)
