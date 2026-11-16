import time
import traceback
import bpy
from . import actions, painting
from .canvas import Rect
from .document import texture_set
from .draw import Renderer
from .minimal import MAX_BRUSH_SIZE, painter_layout

TIMER_INTERVAL = .3
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
LAYER_VALUES = {'OPACITY': 'opacity', 'ROUGHNESS': 'roughness', 'METALLIC': 'metallic'}
MOVES = {'MOVE_UP': 1, 'MOVE_DOWN': -1}
CHANNELS = {'USE_COLOR': 'color', 'USE_ROUGHNESS': 'roughness', 'USE_METALLIC': 'metallic'}
_active = None


def close_active():
    if _active is not None:
        _active.cleanup()


class DEVIL_PAINTER_OT_editor(bpy.types.Operator):
    bl_idname = "devil_painter.editor"
    bl_label = "Devil Painter"
    bl_description = "Open the Devil Painter workspace over the 3D viewport"
    _closed = True
    _handle = None
    _timer = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        global _active
        if _active is not None:
            _active.cleanup()
            return {'FINISHED'}
        self._area, self._window, self._scene = context.area, context.window, context.scene
        self._region = next(r for r in context.area.regions if r.type == 'WINDOW')
        self.pointer = (0, 0)
        self.message = ''
        self.toast_text = None
        self.toast_until = 0.0
        self.resolution = 2048
        self.slider = None
        self._closed = False
        data = texture_set(context.view_layer.objects.active)
        if data is not None:
            painting.enter_paint_mode(context, context.view_layer.objects.active)
            painting.update_canvas(context, data)
        self.workspace = self.make_layout()
        self.renderer = Renderer()
        try:
            self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
            self._timer = context.window_manager.event_timer_add(TIMER_INTERVAL, window=context.window)
            context.window_manager.modal_handler_add(self)
        except Exception:
            self.cleanup()
            raise
        _active = self
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def painted(self):
        obj = self._window.view_layer.objects.active
        return obj, texture_set(obj)

    def make_layout(self):
        region, space = self._region, self._area.spaces.active
        left = right = top = bottom = 0
        for r in self._area.regions:
            if r.type == 'TOOLS' and space.show_region_toolbar and r.width > 1:
                left = max(left, r.x + r.width - region.x)
            if r.type == 'UI' and space.show_region_ui and r.width > 1:
                right = max(right, region.x + region.width - r.x)
            if r.type in {'HEADER', 'TOOL_HEADER'} and r.height > 1 and r.y >= region.y + region.height / 2:
                if r.y < region.y + region.height:
                    top = max(top, region.y + region.height - r.y)
            if r.type in {'ASSET_SHELF', 'ASSET_SHELF_HEADER'} and r.height > 1:
                if region.y <= r.y < region.y + region.height / 2:
                    bottom = max(bottom, r.y + r.height - region.y)
        system_scale = getattr(bpy.context.preferences.system, 'ui_scale', 0.0)
        if system_scale <= 0.0:
            system_scale = getattr(bpy.context.preferences.view, 'ui_scale', 1.0)
        scale = max(.5, system_scale)
        self.bounds = Rect(left, bottom, max(1, region.width - left - right), max(1, region.height - top - bottom))
        obj, data = self.painted()
        brush = (painting.brush_value(self._scene, 'size'), painting.brush_value(self._scene, 'strength'),
                 (*painting.brush_value(self._scene, 'color'), 1.0))
        name = obj.name if obj is not None and obj.type == 'MESH' else ''
        return painter_layout(self.bounds, scale, data, name, self.resolution, painting.active_tool(self._scene), brush)

    def draw_overlay(self):
        if self._closed:
            return
        context = bpy.context
        if context.area != self._area or context.region != self._region or context.window != self._window:
            return
        try:
            self.workspace = self.make_layout()
            self.renderer.draw(self)
        except Exception as exc:
            self.message = f"Render error: {exc}"
            traceback.print_exc()

    def modal(self, context, event):
        if self._closed:
            return {'FINISHED'}
        try:
            return self.handle_event(context, event)
        except ReferenceError:
            self.cleanup()
            self.report({'WARNING'}, 'Devil Painter closed because the view or scene it was using is gone. Reopen it from View > Devil Painter.')
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.message = f"Editor error: {exc}"
            return {'RUNNING_MODAL'}

    def handle_event(self, context, event):
        if self._area not in list(self._window.screen.areas) or self._area.type != 'VIEW_3D' or self._window.scene != self._scene:
            self.cleanup()
            return {'FINISHED'}
        if event.type == 'TIMER':
            if time.monotonic() < self.toast_until + TIMER_INTERVAL:
                self._area.tag_redraw()
            return {'PASS_THROUGH'}
        self.workspace = self.make_layout()
        self.pointer = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
        press = event.value == 'PRESS'
        if press and event.ctrl and event.alt and event.type == 'P':
            self.cleanup()
            return {'FINISHED'}
        if self.slider is not None:
            return self.slider_event(context, event)
        over = self.workspace.covers(*self.pointer) or self.workspace.hit(*self.pointer) is not None
        if event.type == 'MOUSEMOVE':
            self._area.tag_redraw()
        if not over or not any(token in event.type for token in POINTER_TOKENS):
            return {'PASS_THROUGH'}
        control = self.workspace.hit(*self.pointer)
        if control is not None and event.type == 'LEFTMOUSE' and event.value in {'PRESS', 'DOUBLE_CLICK'}:
            try:
                result = self.act(context, control, event.value == 'DOUBLE_CLICK')
            except (ValueError, RuntimeError) as failure:
                self.message = str(failure)
                result = None
            self._area.tag_redraw()
            if result is not None:
                return result
        return {'RUNNING_MODAL'}

    def slider_event(self, context, event):
        key, rect = self.slider
        value = max(0.0, min(1.0, (self.pointer[0] - rect.x) / rect.w))
        obj, data = self.painted()
        if event.type == 'MOUSEMOVE':
            self.apply_slider(key, value, obj, data)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.apply_slider(key, value, obj, data)
            self.slider = None
            if key in LAYER_VALUES and data is not None:
                self.message = actions.commit_value(context, obj, data, LAYER_VALUES[key])
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def apply_slider(self, key, value, obj, data):
        if key == 'BRUSH_SIZE':
            painting.set_brush_value(self._scene, 'size', max(1, round(value * MAX_BRUSH_SIZE)))
        elif key == 'BRUSH_STRENGTH':
            painting.set_brush_value(self._scene, 'strength', value)
        elif data is not None:
            actions.set_value(bpy.context, obj, data, LAYER_VALUES[key], value)

    def act(self, context, control, double):
        key = control.key
        obj, data = self.painted()
        if key == 'CLOSE':
            self.cleanup()
            return {'FINISHED'}
        if key.startswith('RES_'):
            self.resolution = int(key.removeprefix('RES_'))
        elif key == 'START':
            self.message = actions.start(context, obj, self.resolution)
        elif control.kind == 'SLIDER':
            self.slider = (key, control.rect)
            self.apply_slider(key, max(0.0, min(1.0, (self.pointer[0] - control.rect.x) / control.rect.w)), obj, data)
        elif key in painting.BRUSH_NAMES:
            painting.activate_tool(context, key)
            self.message = control.label + ' tool.'
        elif key == 'UNDO':
            bpy.ops.ed.undo()
        elif key == 'REDO':
            bpy.ops.ed.redo()
        elif key == 'BRUSH_COLOR':
            bpy.ops.devil_painter.pick_color('INVOKE_DEFAULT', target='BRUSH')
        elif key == 'LAYER_COLOR':
            bpy.ops.devil_painter.pick_color('INVOKE_DEFAULT', target='LAYER')
        elif key == 'EXPORT':
            bpy.ops.devil_painter.export_textures('INVOKE_DEFAULT')
        elif key == 'RENAME' or (double and key.startswith('ROW_')):
            bpy.ops.devil_painter.rename_layer('INVOKE_DEFAULT')
        elif key.startswith('ROW_'):
            self.message = actions.select_layer(context, obj, data, int(key.removeprefix('ROW_')))
        elif key.startswith('EYE_'):
            self.message = actions.toggle_visible(context, obj, data, int(key.removeprefix('EYE_')))
        elif key in {'ADD_PAINT', 'ADD_FILL'}:
            self.message = actions.add_layer(context, obj, data, key.removeprefix('ADD_'))
        elif key == 'DELETE':
            self.message = actions.delete_layer(context, obj, data)
        elif key in MOVES:
            self.message = actions.move_layer(context, obj, data, MOVES[key])
        elif key == 'BLEND':
            self.message = actions.cycle_blend(context, obj, data)
        elif key in CHANNELS:
            self.message = actions.toggle_channel(context, obj, data, CHANNELS[key])
        elif key in {'ADD_MASK_WHITE', 'ADD_MASK_BLACK'}:
            self.message = actions.add_mask(context, obj, data, key == 'ADD_MASK_WHITE')
        elif key == 'REMOVE_MASK':
            self.message = actions.remove_mask(context, obj, data)
        elif key in {'TARGET_LAYER', 'TARGET_MASK'}:
            self.message = actions.set_paint_mask(context, obj, data, key == 'TARGET_MASK')
        return None

    def cleanup(self):
        global _active
        if self._closed:
            return
        self._closed = True
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if self._timer is not None:
            bpy.context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        try:
            self._area.tag_redraw()
        except ReferenceError:
            pass
        if _active is self:
            _active = None

    def cancel(self, context):
        self.cleanup()
