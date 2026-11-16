import colorsys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from . import actions, compositing, painting
from .blending import BLEND_MODES, linear_to_srgb, srgb_to_linear
from .canvas import Rect
from .document import active_layer, texture_set
from .draw import Renderer
from .minimal import MAX_BRUSH_SIZE, painter_layout
from .shell import MARGIN, clamp_column, clamp_split
from .state import Popover, TextEdit, WorkspaceState

TIMER_INTERVAL = .3
DOUBLE_CLICK_SECONDS = .4
SCROLL_STEP = 40
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
HIDDEN_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_asset_shelf', 'show_gizmo_navigate')
LAYER_VALUES = {'OPACITY': 'opacity', 'ROUGHNESS': 'roughness', 'METALLIC': 'metallic'}
MOVES = {'MOVE_UP': 1, 'MOVE_DOWN': -1}
CHANNELS = {'USE_COLOR': 'color', 'USE_ROUGHNESS': 'roughness', 'USE_METALLIC': 'metallic'}
_active = None


def close_active():
    if _active is not None:
        _active.cleanup()


def default_directory(obj):
    if bpy.data.filepath:
        return bpy.path.abspath('//textures')
    return str(Path.home() / 'Devil Painter Textures' / bpy.path.clean_name(obj.name))


def parse_hex(text):
    digits = text.strip().lstrip('#')
    if len(digits) != 6:
        raise ValueError('Type six hex digits, like #C83A4F.')
    return tuple(int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4))


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
        self.state = WorkspaceState()
        self.last_click = ('', 0.0)
        self._closed = False
        self.saved_regions = {}
        self.hide_regions()
        obj = context.view_layer.objects.active
        data = texture_set(obj)
        if data is not None:
            painting.enter_paint_mode(context, obj)
            painting.update_canvas(context, data)
        self.renderer = Renderer()
        self.workspace = self.make_layout()
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

    def hide_regions(self):
        space = self._area.spaces.active
        for name in HIDDEN_REGIONS:
            if not hasattr(space, name) or space.is_property_readonly(name):
                continue
            self.saved_regions.setdefault(name, getattr(space, name))
            setattr(space, name, True)
            setattr(space, name, False)

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
        directory = (data.export_directory or default_directory(obj)) if data is not None else ''
        return painter_layout(self.bounds, scale, self.state, data, name, painting.active_tool(self._scene), brush, directory)

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
        pointer_event = any(token in event.type for token in POINTER_TOKENS)
        if press and event.ctrl and event.alt and event.type == 'P':
            self.cleanup()
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            self._area.tag_redraw()
        if self.state.text is not None:
            result = self.text_event(context, event, pointer_event)
            if result is not None:
                return result
        if self.state.drag is not None:
            return self.drag_event(context, event)
        layout = self.workspace
        control = layout.hit(*self.pointer)
        over = layout.covers(*self.pointer) or control is not None
        if self.state.popover is not None:
            inside = layout.popover is not None and layout.popover.contains(*self.pointer)
            if press and event.type == 'ESC':
                self.state.popover = None
                return {'RUNNING_MODAL'}
            if press and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and not inside:
                self.state.popover = None
                self._area.tag_redraw()
                if not over:
                    return {'PASS_THROUGH'}
                if event.type == 'LEFTMOUSE':
                    return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and over:
            key = layout.scroll_area(*self.pointer)
            if key is not None:
                step = SCROLL_STEP * layout.scale * (-1 if event.type == 'WHEELUPMOUSE' else 1)
                self.state.scroll[key] = self.state.scroll.get(key, 0.0) + step
                self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if not over or not pointer_event:
            return {'PASS_THROUGH'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ROW_'):
            obj, data = self.painted()
            actions.select_layer(context, obj, data, int(control.key.removeprefix('ROW_')))
            self.open_layer_menu(control.rect, data)
            return {'RUNNING_MODAL'}
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

    def open_layer_menu(self, anchor, data):
        layer = active_layer(data)
        items = [('RENAME', 'Rename', False), ('DUPLICATE', 'Duplicate', False)]
        if layer.mask is None:
            items += [('ADD_MASK_WHITE', 'Add white mask', False), ('ADD_MASK_BLACK', 'Add black mask', False)]
        else:
            items.append(('REMOVE_MASK', 'Remove mask', False))
        items += [('MOVE_UP', 'Move up', False), ('MOVE_DOWN', 'Move down', False), ('DELETE', 'Delete', False)]
        self.state.popover = Popover('MENU', anchor, items=tuple(items))

    def begin_text(self, key, text):
        self.state.text = TextEdit(key, text, len(text))

    def commit_text(self, context):
        edit = self.state.text
        self.state.text = None
        obj, data = self.painted()
        if edit.key.startswith('NAME_') and data is not None:
            self.message = actions.rename_layer(context, obj, data, int(edit.key.removeprefix('NAME_')), edit.text)
        elif edit.key == 'COLOR_HEX':
            red, green, blue = parse_hex(edit.text)
            self.state.hsv = colorsys.rgb_to_hsv(red, green, blue)
            self.apply_color(context, commit=True)
        elif edit.key == 'EXPORT_DIR' and data is not None:
            data.export_directory = edit.text.strip()

    def text_event(self, context, event, pointer_event):
        edit = self.state.text
        if pointer_event:
            if event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'}:
                control = self.workspace.hit(*self.pointer)
                owner = control is not None and (control.key == edit.key or control.key == 'ROW_' + edit.key.removeprefix('NAME_'))
                if not owner:
                    self.finish_text(context)
                    return None
                return {'RUNNING_MODAL'}
            return None
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type in {'RET', 'NUMPAD_ENTER'}:
            self.finish_text(context)
        elif event.type == 'ESC':
            self.state.text = None
        elif event.type == 'BACK_SPACE' and edit.cursor > 0:
            edit.text = edit.text[:edit.cursor - 1] + edit.text[edit.cursor:]
            edit.cursor -= 1
        elif event.type == 'DEL':
            edit.text = edit.text[:edit.cursor] + edit.text[edit.cursor + 1:]
        elif event.type == 'LEFT_ARROW':
            edit.cursor = max(0, edit.cursor - 1)
        elif event.type == 'RIGHT_ARROW':
            edit.cursor = min(len(edit.text), edit.cursor + 1)
        elif event.type == 'HOME':
            edit.cursor = 0
        elif event.type == 'END':
            edit.cursor = len(edit.text)
        elif event.ctrl and event.type == 'V':
            pasted = context.window_manager.clipboard.replace('\n', ' ')
            edit.text = edit.text[:edit.cursor] + pasted + edit.text[edit.cursor:]
            edit.cursor += len(pasted)
        elif event.unicode and event.unicode.isprintable() and not event.ctrl:
            edit.text = edit.text[:edit.cursor] + event.unicode + edit.text[edit.cursor:]
            edit.cursor += len(event.unicode)
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish_text(self, context):
        try:
            self.commit_text(context)
        except ValueError as failure:
            self.message = str(failure)

    def drag_event(self, context, event):
        key, rect = self.state.drag
        x = max(0.0, min(1.0, (self.pointer[0] - rect.x) / rect.w))
        y = max(0.0, min(1.0, (self.pointer[1] - rect.y) / rect.h))
        release = event.type == 'LEFTMOUSE' and event.value == 'RELEASE'
        if event.type == 'MOUSEMOVE' or release:
            self.apply_drag(context, key, x, y, release)
        if release:
            self.state.drag = None
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def apply_drag(self, context, key, x, y, release):
        obj, data = self.painted()
        if key == 'COLUMN_EDGE':
            self.state.column_width = clamp_column((self.bounds.x + self.bounds.w - MARGIN * self.workspace.scale - self.pointer[0]) / self.workspace.scale)
        elif key == 'SPLITTER':
            top, room = self.workspace.splitter
            self.state.split = clamp_split((top - self.pointer[1]) / room) if room > 0 else self.state.split
        elif key == 'BRUSH_SIZE':
            painting.set_brush_value(self._scene, 'size', max(1, round(x * MAX_BRUSH_SIZE)))
        elif key == 'BRUSH_STRENGTH':
            painting.set_brush_value(self._scene, 'strength', x)
        elif key in LAYER_VALUES and data is not None:
            actions.set_value(context, obj, data, LAYER_VALUES[key], x)
            if release:
                self.message = actions.commit_value(context, obj, data, LAYER_VALUES[key])
        elif key == 'COLOR_SV':
            self.state.hsv = (self.state.hsv[0], x, y)
            self.apply_color(context, release)
        elif key == 'COLOR_HUE':
            self.state.hsv = (x, self.state.hsv[1], self.state.hsv[2])
            self.apply_color(context, release)

    def apply_color(self, context, commit):
        display = colorsys.hsv_to_rgb(*self.state.hsv)
        obj, data = self.painted()
        if self.state.popover.target == 'BRUSH':
            painting.set_brush_value(self._scene, 'color', display)
        elif data is not None:
            active_layer(data).color = tuple(float(value) for value in srgb_to_linear(numpy.array(display)))
            compositing.update_values(data)
            if commit:
                self.message = actions.commit_value(context, obj, data, 'color')

    def open_color(self, control, target):
        obj, data = self.painted()
        if target == 'BRUSH':
            display = painting.brush_value(self._scene, 'color')
        else:
            display = linear_to_srgb(numpy.array(active_layer(data).color))
        self.state.hsv = colorsys.rgb_to_hsv(*(float(value) for value in display))
        self.state.popover = Popover('COLOR', control.rect, target=target)

    def act(self, context, control, double):
        key = control.key
        obj, data = self.painted()
        if self.state.popover is not None and self.state.popover.kind == 'MENU' and control.kind == 'MENUITEM':
            self.state.popover = None
        if key == 'CLOSE':
            self.cleanup()
            return {'FINISHED'}
        if key.startswith('RES_'):
            self.state.resolution = int(key.removeprefix('RES_'))
        elif key == 'START':
            self.message = actions.start(context, obj, self.state.resolution)
            self.hide_regions()
        elif key.startswith('PANEL_'):
            self.state.collapsed ^= {key.removeprefix('PANEL_')}
        elif control.kind in {'SLIDER', 'SV', 'HUE', 'GRIP'}:
            self.state.drag = (key, control.rect)
            x = max(0.0, min(1.0, (self.pointer[0] - control.rect.x) / control.rect.w))
            y = max(0.0, min(1.0, (self.pointer[1] - control.rect.y) / control.rect.h))
            self.apply_drag(context, key, x, y, False)
        elif key in painting.BRUSH_NAMES:
            painting.activate_tool(context, key)
            self.message = control.label + ' tool.'
        elif key == 'UNDO':
            bpy.ops.ed.undo()
        elif key == 'REDO':
            bpy.ops.ed.redo()
        elif key == 'BRUSH_COLOR':
            self.open_color(control, 'BRUSH')
        elif key == 'LAYER_COLOR':
            self.open_color(control, 'LAYER')
        elif key == 'COLOR_HEX':
            self.begin_text(key, control.text)
        elif key == 'EXPORT':
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'EXPORT' else Popover('EXPORT', control.rect)
        elif key == 'EXPORT_DIR':
            self.begin_text(key, control.text)
        elif key == 'BROWSE':
            bpy.ops.devil_painter.choose_export_folder('INVOKE_DEFAULT')
        elif key == 'EXPORT_RUN':
            directory = bpy.path.abspath(data.export_directory or default_directory(obj))
            self.message = actions.export(context, obj, data, directory)
            self.state.popover = None
        elif key == 'BLEND':
            layer = active_layer(data)
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BLEND_{mode}', label, mode == layer.blend) for mode, label in BLEND_MODES))
        elif key.startswith('SET_BLEND_'):
            self.message = actions.set_blend(context, obj, data, key.removeprefix('SET_BLEND_'))
        elif key == 'RENAME':
            self.begin_text(f'NAME_{data.active}', active_layer(data).name)
        elif key == 'DUPLICATE':
            self.message = actions.duplicate_layer(context, obj, data)
        elif key.startswith('ROW_'):
            index = int(key.removeprefix('ROW_'))
            now = time.monotonic()
            repeated = self.last_click[0] == key and now - self.last_click[1] < DOUBLE_CLICK_SECONDS
            self.last_click = ('', 0.0) if double or repeated else (key, now)
            self.message = actions.select_layer(context, obj, data, index)
            if double or repeated:
                self.begin_text(f'NAME_{index}', data.layers[index].name)
        elif key.startswith('EYE_'):
            self.message = actions.toggle_visible(context, obj, data, int(key.removeprefix('EYE_')))
        elif key in {'ADD_PAINT', 'ADD_FILL'}:
            self.message = actions.add_layer(context, obj, data, key.removeprefix('ADD_'))
        elif key == 'DELETE':
            self.message = actions.delete_layer(context, obj, data)
        elif key in MOVES:
            self.message = actions.move_layer(context, obj, data, MOVES[key])
        elif key in CHANNELS:
            self.message = actions.toggle_channel(context, obj, data, CHANNELS[key])
        elif key in {'ADD_MASK_WHITE', 'ADD_MASK_BLACK'}:
            self.message = actions.add_mask(context, obj, data, key == 'ADD_MASK_WHITE')
        elif key == 'REMOVE_MASK':
            self.message = actions.remove_mask(context, obj, data)
        elif key.startswith('MASKTHUMB_'):
            self.message = actions.select_layer(context, obj, data, int(key.removeprefix('MASKTHUMB_')), mask=True)
        elif key in {'SELECT_LAYER', 'SELECT_MASK'}:
            self.message = actions.set_paint_mask(context, obj, data, key == 'SELECT_MASK')
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
            space = self._area.spaces.active
            for name, value in self.saved_regions.items():
                if not space.is_property_readonly(name):
                    setattr(space, name, value)
            self._area.tag_redraw()
        except ReferenceError:
            pass
        if _active is self:
            _active = None

    def cancel(self, context):
        self.cleanup()
