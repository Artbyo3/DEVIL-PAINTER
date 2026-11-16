import colorsys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from . import actions, brushes, compositing, library, painting, shelf, strokes, thumbnails
from .blending import BLEND_MODES, CHANNEL, CHANNELS, linear_to_srgb, srgb_to_linear
from .canvas import Rect
from .document import active_layer, set_channels, slot_value, texture_set
from .draw import Renderer
from .masks import GENERATORS
from .meshmaps import MESH_MAPS
from .minimal import BRUSH_SLIDERS, BRUSH_TOGGLES, GENERATOR_SLIDERS, MAX_BRUSH_SIZE, REPLACE_TARGET, SCALE_RANGE, TILING_RANGE, from_slider, painter_layout
from .shell import MARGIN, clamp_column, clamp_split
from .state import Popover, TextEdit, WorkspaceState

TIMER_INTERVAL = .3
DOUBLE_CLICK_SECONDS = .4
SCROLL_STEP = 40
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
HIDDEN_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_asset_shelf', 'show_gizmo_navigate')
MOVES = {'MOVE_UP': 1, 'MOVE_DOWN': -1}
PROJECTION_LABELS = {'UV': 'UV', 'TRIPLANAR': 'Tri-planar'}
BRUSH_RANGES = {key: (field, top, .01 if key == 'BRUSH_FLOW' else 1.0 if key == 'BRUSH_SPACING' else 0.0) for key, _, field, top, _ in BRUSH_SLIDERS}
BRUSH_FLAGS = {key: field for key, _, field in BRUSH_TOGGLES}
GENERATOR_RANGES = {key: (field, top) for key, _, field, top in GENERATOR_SLIDERS}
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
        self._area, self._window = context.area, context.window
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
        self.stroke_pending = False
        if data is not None:
            actions.prepare(obj, data)
            painting.enter_paint_mode(context, obj)
            painting.update_canvas(context, data)
            brushes.sync(context, data)
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

    @property
    def scene(self):
        return self._window.scene

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
        brush = (painting.brush_value(self.scene, 'size'), (*painting.brush_value(self.scene, 'color'), 1.0))
        name = obj.name if obj is not None and obj.type == 'MESH' else ''
        directory = (data.export_directory or default_directory(obj)) if data is not None else ''
        return painter_layout(self.bounds, scale, self.state, data, name, painting.active_tool(self.scene), brush, directory)

    def draw_overlay(self):
        if self._closed:
            return
        context = bpy.context
        if context.area != self._area or context.region != self._region or context.window != self._window:
            return
        try:
            thumbnails.begin_frame()
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
        if self._area not in list(self._window.screen.areas) or self._area.type != 'VIEW_3D':
            self.cleanup()
            return {'FINISHED'}
        if event.type in {'TIMER', 'MOUSEMOVE'} and self.stroke_pending:
            self.finish_stroke(context)
        if event.type == 'TIMER':
            if thumbnails.waiting():
                thumbnails.render_next()
                self._area.tag_redraw()
            elif time.monotonic() < self.toast_until + TIMER_INTERVAL:
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
                    if event.type == 'LEFTMOUSE':
                        self.begin_stroke(context)
                    return {'PASS_THROUGH'}
                if event.type == 'LEFTMOUSE':
                    return {'RUNNING_MODAL'}
        if press and event.type == 'ESC' and self.state.armed:
            self.state.armed = ''
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and over:
            key = layout.scroll_area(*self.pointer)
            if key is not None:
                step = SCROLL_STEP * layout.scale * (-1 if event.type == 'WHEELUPMOUSE' else 1)
                self.state.scroll[key] = self.state.scroll.get(key, 0.0) + step
                self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if press and event.type == 'Z' and event.ctrl:
            self.history_step(context, redo=event.shift)
            return {'PASS_THROUGH'}
        if not over or not pointer_event:
            if press and event.type == 'LEFTMOUSE' and not event.alt:
                self.begin_stroke(context)
            return {'PASS_THROUGH'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ROW_'):
            obj, data = self.painted()
            actions.select_layer(context, obj, data, control.key.removeprefix('ROW_'))
            self.open_layer_menu(control.rect, data)
            return {'RUNNING_MODAL'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ITEM.'):
            item = self.shelf_item(control.key)
            index = control.key.removeprefix('ITEM.')
            if item.user_index >= 0:
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_MATERIAL.{item.user_index}', 'Delete material', False),))
            elif item.kind == 'TEXTURE':
                obj, data = self.painted()
                layer = active_layer(data) if data is not None else None
                items = [(f'TEXTURE_FILL.{index}', 'New fill layer', False), (f'USE_ALPHA.{index}', 'Use as brush alpha', False)]
                if layer is not None and layer.kind == 'FILL':
                    items += [(f'ASSIGN_TEXTURE.{channel.key}.{index}', f'Use for {channel.label.lower()}', False) for channel in set_channels(data)]
                if item.managed:
                    items.append((f'REMOVE_TEXTURE.{index}', 'Remove from library', False))
                self.state.popover = Popover('MENU', control.rect, items=tuple(items))
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

    def begin_stroke(self, context):
        obj, data = self.painted()
        if data is None or obj.mode != 'TEXTURE_PAINT':
            return
        if painting.uses_stroke_buffer(context, data):
            self.stroke_pending = True
        else:
            strokes.record(None)

    def finish_stroke(self, context):
        if any(operator.bl_idname.startswith('PAINT_OT') for operator in self._window.modal_operators):
            return
        self.stroke_pending = False
        obj, data = self.painted()
        if data is not None and strokes.merge(obj, data):
            self._area.tag_redraw()

    def history_step(self, context, redo):
        self.state.popover = None
        if redo:
            strokes.redo()
            self.stroke_pending = True
        else:
            strokes.undo()

    def open_layer_menu(self, anchor, data):
        layer = active_layer(data)
        items = [('RENAME', 'Rename', False), ('DUPLICATE', 'Duplicate', False)]
        if layer.mask is None:
            items += [('ADD_MASK_WHITE', 'Add white mask', False), ('ADD_MASK_BLACK', 'Add black mask', False)]
        else:
            items.append(('REMOVE_MASK', 'Remove mask', False))
        if layer.kind == 'FILL':
            items += [('REPLACE_MATERIAL', 'Replace material', False), ('SAVE_MATERIAL', 'Save as material', False)]
        if actions.folder_below(data, layer) is not None:
            items.append(('MOVE_INTO', 'Move into folder below', False))
        if layer.parent:
            items.append(('MOVE_OUT', 'Move out of folder', False))
        items += [('MOVE_UP', 'Move up', False), ('MOVE_DOWN', 'Move down', False), ('DELETE', 'Delete', False)]
        self.state.popover = Popover('MENU', anchor, items=tuple(items))

    def begin_text(self, key, text):
        self.state.text = TextEdit(key, text, len(text))

    def commit_text(self, context):
        edit = self.state.text
        self.state.text = None
        obj, data = self.painted()
        if edit.key.startswith('NAME_') and data is not None:
            self.message = actions.rename_layer(context, obj, data, edit.key.removeprefix('NAME_'), edit.text)
        elif edit.key == 'COLOR_HEX':
            red, green, blue = parse_hex(edit.text)
            self.state.hsv = colorsys.rgb_to_hsv(red, green, blue)
            self.apply_color(context, commit=True)
        elif edit.key == 'EXPORT_DIR' and data is not None:
            data.export_directory = edit.text.strip()
        elif edit.key == 'TEXTURE_DIR':
            library.set_texture_folder(edit.text)

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
            painting.set_brush_value(self.scene, 'size', max(1, round(x * MAX_BRUSH_SIZE)))
        elif key == 'BRUSH_STRENGTH' and data is not None:
            data.brush_opacity = x
            self.brush_changed(context, data)
        elif key in BRUSH_RANGES and data is not None:
            setattr(data, BRUSH_RANGES[key][0], max(BRUSH_RANGES[key][2], x * BRUSH_RANGES[key][1]))
            self.brush_changed(context, data)
        elif key in GENERATOR_RANGES and data is not None:
            field, top = GENERATOR_RANGES[key]
            actions.set_generator_value(context, obj, data, field, max(.5, x * top) if key == 'GEN_SCALE' else x * top)
            if release:
                self.message = actions.commit_value(context, obj, data, 'Generator')
        elif key == 'BAKE_SAMPLES' and data is not None:
            data.bake_samples = max(1, round(x * 128))
        elif key.startswith('BRUSHVAL.') and data is not None:
            data.brush_slots[key.removeprefix('BRUSHVAL.')].value = x
            self.brush_changed(context, data)
        elif key == 'OPACITY' and data is not None:
            actions.set_opacity(context, obj, data, x)
            if release:
                self.message = actions.commit_value(context, obj, data, 'Opacity')
        elif key.startswith(('VALUE.', 'VALUEB.')) and data is not None:
            kind, channel = key.split('.')
            actions.set_channel_value(context, obj, data, channel, (x,), second=kind == 'VALUEB')
            if release:
                self.message = actions.commit_value(context, obj, data, CHANNEL[channel].label)
        elif key.startswith('CHOPACITY.') and data is not None:
            channel = key.removeprefix('CHOPACITY.')
            actions.set_slot_field(context, obj, data, channel, 'opacity', x)
            if release:
                self.message = actions.commit_value(context, obj, data, f'{CHANNEL[channel].label} opacity')
        elif key.startswith(('SCALE.', 'DETAIL.', 'CONTRAST.')) and data is not None:
            kind, channel = key.split('.')
            value = {'SCALE': from_slider(x, SCALE_RANGE), 'DETAIL': x, 'CONTRAST': x * .98}[kind]
            actions.set_slot_field(context, obj, data, channel, kind.lower(), value)
            if release:
                self.message = actions.commit_value(context, obj, data, f'{CHANNEL[channel].label} {kind.lower()}')
        elif key == 'TILING' and data is not None:
            actions.set_tiling(context, obj, data, from_slider(x, TILING_RANGE))
            if release:
                self.message = actions.commit_value(context, obj, data, 'Tiling')
        elif key == 'COLOR_SV':
            self.state.hsv = (self.state.hsv[0], x, y)
            self.apply_color(context, release)
        elif key == 'COLOR_HUE':
            self.state.hsv = (x, self.state.hsv[1], self.state.hsv[2])
            self.apply_color(context, release)

    def brush_changed(self, context, data):
        data.brush_preset = 'Custom'
        brushes.sync(context, data)
        compositing.sync(data)

    def apply_color(self, context, commit):
        display = colorsys.hsv_to_rgb(*self.state.hsv)
        obj, data = self.painted()
        target = self.state.popover.target
        if target == 'BRUSH':
            painting.set_brush_value(self.scene, 'color', display)
        elif target.startswith('brush:') and data is not None:
            channel = target.removeprefix('brush:')
            value = srgb_to_linear(numpy.array(display)) if CHANNEL[channel].srgb else display
            data.brush_slots[channel].color = tuple(float(part) for part in value)
            compositing.update_values(data)
        elif data is not None:
            channel, _, second = target.partition(':')
            value = srgb_to_linear(numpy.array(display)) if CHANNEL[channel].srgb else display
            actions.set_channel_value(context, obj, data, channel, tuple(float(part) for part in value), second=bool(second))
            if commit:
                self.message = actions.commit_value(context, obj, data, CHANNEL[channel].label)

    def open_color(self, control, target):
        obj, data = self.painted()
        if target == 'BRUSH':
            display = painting.brush_value(self.scene, 'color')
        elif target.startswith('brush:'):
            channel = target.removeprefix('brush:')
            value = numpy.array(data.brush_slots[channel].color)
            display = linear_to_srgb(value) if CHANNEL[channel].srgb else value
        else:
            channel, _, second = target.partition(':')
            value = numpy.array(slot_value(active_layer(data).slots[channel], bool(second)))
            display = linear_to_srgb(value) if CHANNEL[channel].srgb else value
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
            painting.update_canvas(context, data)
            brushes.sync(context, data)
            self.message = control.label + ' tool.'
        elif key == 'UNDO':
            self.history_step(context, redo=False)
            bpy.ops.ed.undo()
        elif key == 'REDO':
            self.history_step(context, redo=True)
            bpy.ops.ed.redo()
        elif key == 'GENERATOR':
            current = active_layer(data).generator
            self.state.popover = Popover('MENU', control.rect, items=(('SET_GENERATOR.NONE', 'None', current == 'NONE'),) + tuple(
                (f'SET_GENERATOR.{item.key}', item.label, current == item.key) for item in GENERATORS))
        elif key.startswith('SET_GENERATOR.'):
            self.message = actions.set_generator(context, obj, data, dict(generator=key.removeprefix('SET_GENERATOR.')))
        elif key == 'GEN_INVERT':
            self.message = actions.set_generator(context, obj, data, dict(gen_invert=not active_layer(data).gen_invert))
        elif key in {'BAKE', 'OPEN_BAKE'}:
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'BAKE' else Popover('BAKE', control.rect)
        elif key.startswith('BAKEMAP.'):
            self.state.bake_keys ^= {key.removeprefix('BAKEMAP.')}
        elif key == 'BAKE_SOURCE':
            meshes = [item.name for item in context.view_layer.objects if item.type == 'MESH' and item != obj]
            self.state.popover = Popover('MENU', control.rect, items=(('SET_SOURCE.', 'None', data.bake_source is None),) + tuple(
                (f'SET_SOURCE.{name}', name, data.bake_source is not None and data.bake_source.name == name) for name in meshes))
        elif key.startswith('SET_SOURCE.'):
            self.message = actions.set_bake_source(context, obj, data, key.removeprefix('SET_SOURCE.'))
        elif key == 'BAKE_RUN':
            self.state.popover = None
            self.message = actions.bake_mesh_maps(context, obj, data, [item.key for item in MESH_MAPS if item.key in self.state.bake_keys])
        elif key.startswith('MAP.'):
            self.message = actions.set_solo(context, obj, data, 'map:' + key.removeprefix('MAP.'))
        elif key == 'BRUSH_CARD':
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'BRUSH' else Popover('BRUSH', control.rect)
        elif key in BRUSH_FLAGS:
            setattr(data, BRUSH_FLAGS[key], not getattr(data, BRUSH_FLAGS[key]))
            self.brush_changed(context, data)
        elif key.startswith('BRUSHUSE.'):
            slot = data.brush_slots[key.removeprefix('BRUSHUSE.')]
            slot.enabled = not slot.enabled
            self.brush_changed(context, data)
        elif key.startswith('BRUSHSW.'):
            self.open_color(control, 'brush:' + key.removeprefix('BRUSHSW.'))
        elif key == 'BRUSH_ALPHA':
            self.state.shelf_open, self.state.shelf_tab = True, 'ALPHAS'
        elif key.startswith('USE_ALPHA.'):
            data.brush_alpha = bpy.data.images.load(str(self.shelf_item('ITEM.' + key.removeprefix('USE_ALPHA.')).payload), check_existing=True)
            self.brush_changed(context, data)
            self.message = 'The texture is now the brush alpha.'
        elif key == 'BRUSH_COLOR':
            self.open_color(control, 'BRUSH')
        elif key.startswith('SWATCH.'):
            self.open_color(control, key.removeprefix('SWATCH.'))
        elif key.startswith('SWATCHB.'):
            self.open_color(control, key.removeprefix('SWATCHB.') + ':b')
        elif key.startswith('SOURCE.'):
            channel = key.removeprefix('SOURCE.')
            source = active_layer(data).slots[channel].source
            self.state.popover = Popover('MENU', control.rect, items=((f'USE_VALUE.{channel}', 'Plain value', source == 'VALUE'),
                                                                      (f'PICK_TEXTURE.{channel}', 'Texture from the shelf', source == 'IMAGE'),
                                                                      (f'PICK_PATTERN.{channel}', 'Pattern from the shelf', source == 'PATTERN')))
        elif key.startswith('USE_VALUE.'):
            self.message = actions.use_value(context, obj, data, key.removeprefix('USE_VALUE.'))
        elif key.startswith(('PICK_TEXTURE.', 'PICK_PATTERN.')):
            kind, channel = key.split('.')
            self.state.armed = channel
            self.state.shelf_open = True
            self.state.shelf_tab = 'TEXTURES' if kind == 'PICK_TEXTURE' else 'PATTERNS'
            self.message = f'Click a {"texture" if kind == "PICK_TEXTURE" else "pattern"} in the shelf for {CHANNEL[channel].label.lower()}.'
        elif key == 'CANCEL_ARM':
            self.state.armed = ''
        elif key.startswith('SHELF_TAB.'):
            self.state.shelf_tab = key.removeprefix('SHELF_TAB.')
            self.state.shelf_open = True
            self.state.scroll['SHELF'] = 0.0
            library.rescan()
        elif key == 'SHELF_TOGGLE':
            self.state.shelf_open = not self.state.shelf_open
        elif key == 'TEXTURE_DIR':
            self.begin_text(key, control.text)
        elif key == 'TEXTURE_BROWSE':
            bpy.ops.devil_painter.choose_texture_folder('INVOKE_DEFAULT')
        elif key.startswith('ITEM.'):
            self.message = self.use_shelf_item(context, obj, data, self.shelf_item(key))
        elif key == 'TEXTURE_IMPORT':
            bpy.ops.devil_painter.import_textures('INVOKE_DEFAULT')
        elif key.startswith('TEXTURE_FILL.'):
            self.message = actions.add_material(context, obj, data, shelf.texture_definition(self.shelf_item('ITEM.' + key.removeprefix('TEXTURE_FILL.')).payload))
        elif key.startswith('ASSIGN_TEXTURE.'):
            _, channel, index = key.split('.')
            path = self.shelf_item('ITEM.' + index).payload
            self.message = actions.assign_image(context, obj, data, channel, library.load_image(path, CHANNEL[channel]))
        elif key.startswith('REMOVE_TEXTURE.'):
            self.message = f'Removed {library.remove_texture(self.shelf_item("ITEM." + key.removeprefix("REMOVE_TEXTURE.")).payload)} from the library.'
        elif key.startswith('DELETE_MATERIAL.'):
            self.message = f'Deleted {library.remove_user_material(int(key.removeprefix("DELETE_MATERIAL.")))}.'
        elif key == 'SAVE_MATERIAL':
            self.message = f'Saved {library.add_user_material(library.capture(active_layer(data)))} to the material shelf.'
        elif key == 'PROJECTION':
            current = active_layer(data).projection
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_PROJECTION.{mode}', label, mode == current)
                                                                          for mode, label in PROJECTION_LABELS.items()))
        elif key.startswith('SET_PROJECTION.'):
            self.message = actions.set_projection(context, obj, data, key.removeprefix('SET_PROJECTION.'))
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
        elif key.startswith('BLEND.'):
            channel = key.removeprefix('BLEND.')
            current = active_layer(data).slots[channel].blend
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BLEND.{channel}.{mode}', label, mode == current)
                                                                          for mode, label in BLEND_MODES))
        elif key.startswith('SET_BLEND.'):
            _, channel, mode = key.split('.')
            self.message = actions.set_blend(context, obj, data, channel, mode)
        elif key == 'CHANNELS':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_CHANNEL.{channel.key}', channel.label, data.channels[channel.key].enabled)
                                                                          for channel in CHANNELS if channel.key != 'base_color'))
        elif key.startswith('SET_CHANNEL.'):
            self.message = actions.toggle_set_channel(context, obj, data, key.removeprefix('SET_CHANNEL.'))
        elif key == 'VIEW':
            items = [('SOLO.', 'Material', not data.solo)] + [(f'SOLO.{channel.key}', channel.label, data.solo == channel.key)
                                                             for channel in set_channels(data)]
            items += [(f'SOLO.map:{item.key}', item.label + ' map', data.solo == 'map:' + item.key) for item in MESH_MAPS
                      if item.key in data.maps and data.maps[item.key].image is not None]
            self.state.popover = Popover('MENU', control.rect, items=tuple(items))
        elif key.startswith('SOLO.'):
            self.message = actions.set_solo(context, obj, data, key.removeprefix('SOLO.'))
        elif key == 'RENAME':
            self.begin_text(f'NAME_{data.active_uid}', active_layer(data).name)
        elif key == 'DUPLICATE':
            self.message = actions.duplicate_layer(context, obj, data)
        elif key.startswith('ROW_'):
            uid = key.removeprefix('ROW_')
            now = time.monotonic()
            repeated = self.last_click[0] == key and now - self.last_click[1] < DOUBLE_CLICK_SECONDS
            self.last_click = ('', 0.0) if double or repeated else (key, now)
            self.message = actions.select_layer(context, obj, data, uid)
            if double or repeated:
                self.begin_text(f'NAME_{uid}', active_layer(data).name)
        elif key.startswith('EYE_'):
            self.message = actions.toggle_visible(context, obj, data, key.removeprefix('EYE_'))
        elif key.startswith('FOLD_'):
            self.state.collapsed ^= {key}
        elif key == 'MOVE_INTO':
            self.message = actions.move_into_folder(context, obj, data)
        elif key == 'MOVE_OUT':
            self.message = actions.move_out_of_folder(context, obj, data)
        elif key == 'REPLACE_MATERIAL':
            self.state.armed = REPLACE_TARGET
            self.state.shelf_open, self.state.shelf_tab = True, 'MATERIALS'
            self.message = 'Click a material in the shelf to put into ' + active_layer(data).name + '.'
        elif key == 'RESET_MATERIAL':
            self.message = actions.reset_material(context, obj, data)
        elif key in {'ADD_PAINT', 'ADD_FILL', 'ADD_FOLDER'}:
            self.message = actions.add_layer(context, obj, data, key.removeprefix('ADD_'))
        elif key == 'DELETE':
            self.message = actions.delete_layer(context, obj, data)
        elif key in MOVES:
            self.message = actions.move_layer(context, obj, data, MOVES[key])
        elif key.startswith('USE.'):
            self.message = actions.toggle_slot(context, obj, data, key.removeprefix('USE.'))
        elif key in {'ADD_MASK_WHITE', 'ADD_MASK_BLACK'}:
            self.message = actions.add_mask(context, obj, data, key == 'ADD_MASK_WHITE')
        elif key == 'REMOVE_MASK':
            self.message = actions.remove_mask(context, obj, data)
        elif key.startswith('MASKTHUMB_'):
            self.message = actions.select_layer(context, obj, data, key.removeprefix('MASKTHUMB_'), mask=True)
        elif key in {'SELECT_LAYER', 'SELECT_MASK'}:
            self.message = actions.set_target(context, obj, data, 'MASK' if key == 'SELECT_MASK' else 'CONTENT')
        return None

    def shelf_item(self, key):
        return shelf.items(self.state.shelf_tab)[int(key.removeprefix('ITEM.'))]

    def use_shelf_item(self, context, obj, data, item):
        armed = self.state.armed
        self.state.armed = ''
        layer = active_layer(data)
        if armed == REPLACE_TARGET and item.kind == 'MATERIAL' and layer is not None and layer.kind == 'FILL':
            return actions.replace_material(context, obj, data, item.payload)
        armed = '' if armed == REPLACE_TARGET else armed
        target = armed if armed and layer is not None and layer.kind == 'FILL' else ''
        if item.kind == 'MASK':
            if layer is None:
                return 'Select a layer to mask.'
            return actions.set_generator(context, obj, data, {key: value for key, value in item.payload.items() if key != 'name'})
        if item.kind == 'BRUSH':
            brushes.apply_preset(context, data, item.payload)
            compositing.sync(data)
            return f'{item.label} brush.'
        if item.kind == 'ALPHA':
            data.brush_alpha = brushes.load_alpha(item.payload) if item.payload else None
            brushes.sync(context, data)
            return f'Brush alpha: {item.label}.'
        if item.kind == 'TEXTURE' and target:
            return actions.assign_image(context, obj, data, target, library.load_image(item.payload, CHANNEL[target]))
        if item.kind == 'PATTERN' and target:
            return actions.assign_pattern(context, obj, data, target, item.payload)
        if item.kind == 'TEXTURE':
            return actions.add_material(context, obj, data, shelf.texture_definition(item.payload))
        if item.kind == 'PATTERN':
            return actions.add_material(context, obj, data, shelf.pattern_definition(item.payload))
        return actions.add_material(context, obj, data, item.payload)

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
