import time
import traceback
import bpy
from .canvas import Layout, View, Rect
from .draw import Renderer
from .minimal import minimal_layout

TIMER_INTERVAL = .3
_active = None


def close_active():
    if _active is not None:
        _active.cleanup()


class DEVIL_PAINTER_OT_editor(bpy.types.Operator):
    bl_idname = "devil_painter.editor"
    bl_label = "Devil Painter"
    bl_description = "Open the Devil Painter workspace over the 3D scene"
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
        saved = tuple(self._scene.dp_ui_rect)
        self.window_rect = saved if saved[2] > 0 and saved[3] > 0 else None
        self.view = View()
        self.full = True
        self.pan_last = None
        self.pointer = (0, 0)
        self.message = ''
        self.toast_text = None
        self.toast_until = 0.0
        self._closed = False
        self.free_window = self.window_rect
        self.window_drag = None
        self.window_cursor = 'DEFAULT'
        self.canvas_layout = self.make_layout()
        self.fit()
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

    def reveal_3d(self):
        self.full = False
        self.canvas_layout = self.make_layout()
        available = self.canvas_layout.available
        panel = self.canvas_layout.panel
        scale = self.canvas_layout.scale
        if self.free_window:
            self.window_rect = self.free_window
            self.canvas_layout = self.make_layout()
        else:
            width = min(available.w, max(620 * scale, available.w * .45))
            self.set_window(Rect(available.x + available.w - width, panel.y, width, panel.h))
        self.save_window()
        self.fit()
        self.message = '3D viewport revealed on the left. Click Full canvas to return.'

    def window_hit(self):
        if self.full or self.pan_last is not None:
            return None
        panel = self.canvas_layout.panel
        scale = self.canvas_layout.scale
        x, y = self.pointer
        reach = 5 * scale
        if not (panel.x - reach <= x <= panel.x + panel.w + reach and panel.y - reach <= y <= panel.y + panel.h + reach):
            return None
        edges = ''.join(mark for mark, near in (('L', abs(x - panel.x) <= reach), ('R', abs(x - panel.x - panel.w) <= reach),
                                                ('B', abs(y - panel.y) <= reach), ('T', abs(y - panel.y - panel.h) <= reach)) if near)
        if edges:
            return edges
        if y > panel.y + panel.h - 34 * scale and self.canvas_layout.button(x, y) is None:
            return 'MOVE'
        return None

    def window_event(self, event):
        press = event.value == 'PRESS'
        drag = self.window_drag
        if drag:
            if event.type == 'MOUSEMOVE':
                self.drag_window(drag)
            elif press and event.type in {'ESC', 'RIGHTMOUSE'}:
                self.set_window(drag['rect'])
                self.window_drag = None
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.window_drag = None
                self.save_window()
                self.free_window = self.window_rect
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        hit = self.window_hit()
        if press and event.type == 'LEFTMOUSE' and hit:
            self.window_drag = dict(hit=hit, pointer=self.pointer, rect=self.canvas_layout.panel)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            cursor = 'DEFAULT' if not hit else 'SCROLL_XY' if hit == 'MOVE' or len(hit) > 1 else 'MOVE_X' if hit in {'L', 'R'} else 'MOVE_Y'
            if cursor != self.window_cursor:
                self._window.cursor_set(cursor)
                self.window_cursor = cursor
        return None

    def drag_window(self, drag):
        rect = drag['rect']
        dx = self.pointer[0] - drag['pointer'][0]
        dy = self.pointer[1] - drag['pointer'][1]
        hit = drag['hit']
        least = 420 * self.canvas_layout.scale
        if hit == 'MOVE':
            self.set_window(Rect(rect.x + dx, rect.y + dy, rect.w, rect.h))
            return
        x, y, w, h = rect.x, rect.y, rect.w, rect.h
        if 'L' in hit:
            shift = min(dx, w - least)
            x, w = x + shift, w - shift
        if 'R' in hit:
            w = max(least, w + dx)
        if 'B' in hit:
            shift = min(dy, h - least)
            y, h = y + shift, h - shift
        if 'T' in hit:
            h = max(least, h + dy)
        self.set_window(Rect(x, y, w, h))

    def set_window(self, rect):
        s = self.canvas_layout.scale
        self.window_rect = tuple(value / s for value in (rect.x, rect.y, rect.w, rect.h))
        self.canvas_layout = self.make_layout()

    def save_window(self):
        if not self.full:
            p = self.canvas_layout.panel
            s = self.canvas_layout.scale
            self.window_rect = (p.x / s, p.y / s, p.w / s, p.h / s)
        if self.window_rect is not None:
            self._scene.dp_ui_rect = self.window_rect

    def restore_canvas(self):
        self.free_window = self.window_rect
        self.full = True
        self.window_rect = None
        self.canvas_layout = self.make_layout()
        self.save_window()
        self.fit()
        self.message = 'Full canvas restored.'

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
        position = tuple(v * scale for v in self.window_rect) if self.window_rect else None
        layout = Layout(region.width, region.height, scale, self.full, max(0, left), max(0, right), top, bottom,
                        position=position)
        minimal_layout(layout)
        return layout

    def fit(self):
        self.view.fit(self.canvas_layout.canvas)

    def draw_overlay(self):
        if self._closed:
            return
        context = bpy.context
        if context.area != self._area or context.region != self._region or context.window != self._window:
            return
        try:
            self.canvas_layout = self.make_layout()
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
        self.canvas_layout = self.make_layout()
        self.pointer = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
        layout = self.canvas_layout
        panel = layout.panel.contains(*self.pointer)
        canvas = layout.canvas.contains(*self.pointer)
        press = event.value == 'PRESS'
        if event.type == 'TIMER':
            if time.monotonic() < self.toast_until + TIMER_INTERVAL:
                self._area.tag_redraw()
            return {'PASS_THROUGH'}
        if press and event.ctrl and event.alt and event.type == 'P':
            self.cleanup()
            return {'FINISHED'}
        window_result = self.window_event(event)
        if window_result is not None:
            return window_result
        if self.pan_last is not None:
            if event.type == 'MOUSEMOVE':
                self.view.pan(self.pointer[0] - self.pan_last[0], self.pointer[1] - self.pan_last[1])
                self.pan_last = self.pointer
            elif event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
                self.pan_last = None
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if panel or press:
            self._area.tag_redraw()
        if not panel:
            return {'PASS_THROUGH'}
        if press and event.ctrl and event.type == 'S':
            return {'PASS_THROUGH'}
        button = layout.button(*self.pointer)
        if button and press and event.type == 'LEFTMOUSE':
            if button == 'CLOSE':
                self.cleanup()
                return {'FINISHED'}
            if button == 'SHOW_3D':
                self.reveal_3d()
            elif button == 'RESTORE_CANVAS':
                self.restore_canvas()
            return {'RUNNING_MODAL'}
        if canvas and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            self.view.zoom_at(self.pointer, layout.canvas, 1.15 if event.type == 'WHEELUPMOUSE' else 1 / 1.15)
        elif canvas and event.type == 'MIDDLEMOUSE' and press:
            self.pan_last = self.pointer
        return {'RUNNING_MODAL'}

    def cleanup(self):
        global _active
        if self._closed:
            return
        self.save_window()
        self._closed = True
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if self._timer is not None:
            bpy.context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        try:
            if self.window_cursor != 'DEFAULT':
                self._window.cursor_set('DEFAULT')
            self._area.tag_redraw()
        except ReferenceError:
            pass
        if _active is self:
            _active = None

    def cancel(self, context):
        self.cleanup()
