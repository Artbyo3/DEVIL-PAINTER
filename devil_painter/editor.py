import colorsys
import time
import traceback
from pathlib import Path
import bpy
import numpy
import math
import gpu
from gpu_extras.batch import batch_for_shader
from . import actions, brushes, compositing, exporting, library, painting, projects, sets, shelf, shortcuts, smart, strokes, thumbnails
from .blending import BLEND_MODES, CHANNEL, FOLDER_BLENDS, linear_to_srgb, srgb_to_linear
from .ui_system import ACCENT
from .canvas import Rect
from .document import RESOLUTIONS, active_effect, active_layer, active_tile, find_layer, paint_target, set_channels, slot_value, texture_set
from .effects import FILTERS, MASK_BLENDS
from .procedural import PATTERNS
from .tiles import variant
from .draw import Renderer
from .masks import GENERATORS
from .meshmaps import MESH_MAPS
from .minimal import FX_RANGES, effect_menu, layer_rows, FOV_RANGE, RECENT_COLORS, SHADER_SLIDERS, BRUSH_SLIDERS, BRUSH_TOGGLES, GENERATOR_SLIDERS, MAX_BRUSH_SIZE, REPLACE_TARGET, EFFECT_TARGET, SCALE_RANGE, TILING_RANGE, from_slider, painter_layout
from .shell import MARGIN, clamp_column, clamp_split
from .state import Popover, TextEdit, WorkspaceState

TIMER_INTERVAL = .3
DOUBLE_CLICK_SECONDS = .4
SCROLL_STEP = 40
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
HIDDEN_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_asset_shelf', 'show_gizmo_navigate')
FLAT_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_ui', 'show_region_asset_shelf')
MOVES = {'MOVE_UP': 1, 'MOVE_DOWN': -1}
EXPORT_MENUS = {'EXPORT_TEMPLATE', 'EXPORT_DEPTH', 'EXPORT_SIZE', 'EXPORT_PADDING'}
HIGHLIGHT_ALPHA = .35
SHADER_RANGES = {key: (field, top) for key, _, field, top in SHADER_SLIDERS}
TOOL_ACTIONS = {'PAINT', 'ERASE', 'FILL', 'BLUR', 'SMEAR', 'CLONE'}
EXPORT_MENU_PREFIXES = ('OUT_SRC.', 'OUT_FORMAT.', 'OUT_DEPTH.')
EXPORT_EDITS = ('SET_TEMPLATE.', 'SET_EXPORT_DEPTH.', 'SET_EXPORT_SIZE.', 'SET_EXPORT_PADDING.', 'OUT_REMOVE.', 'SET_SRC.', 'SET_FORMAT.', 'SET_DEPTH.')
PROJECTION_LABELS = {'UV': 'UV', 'TRIPLANAR': 'Tri-planar'}
BRUSH_RANGES = {key: (field, top, .01 if key == 'BRUSH_FLOW' else 1.0 if key == 'BRUSH_SPACING' else 0.0) for key, _, field, top, _ in BRUSH_SLIDERS}
BRUSH_FLAGS = {key: field for key, _, field in BRUSH_TOGGLES}
GENERATOR_RANGES = {key: (field, top) for key, _, field, top in GENERATOR_SLIDERS}
LAYER_KEYS = ('ROW_', 'FX_', 'EYE_', 'FXEYE_', 'MASKTHUMB_')
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
    flat_area = None
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
        self.modifiers = (False, False)
        self._closed = False
        self.saved_regions = {}
        self.hide_regions()
        obj = context.view_layer.objects.active
        data = texture_set(obj)
        self.stroke_pending = False
        self.flat_area = None
        self.saved_mask = None
        self.setup_cache = None
        self.highlight = None
        self.highlight_cache = (None, None)
        self._view_handle = None
        if data is not None:
            for item in obj.devil_painter.sets:
                actions.prepare(obj, item)
            painting.enter_paint_mode(context, obj)
            self.remember_mask(obj)
            sets.mask_faces(obj, obj.devil_painter)
            painting.update_canvas(context, data)
            brushes.sync(context, data)
        self.renderer = Renderer()
        self.workspace = self.make_layout()
        try:
            self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
            self._view_handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_highlight, (), 'WINDOW', 'POST_VIEW')
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
        directory = (obj.devil_painter.export_directory or default_directory(obj)) if data is not None else ''
        viewport = (space.shading, space.lens, space.region_3d.view_perspective == 'ORTHO')
        return painter_layout(self.bounds, scale, self.state, data, name, painting.active_tool(self.scene), brush, directory, self.setup(obj, data),
                              viewport)

    def setup(self, obj, data):
        if data is not None or obj is None or obj.type != 'MESH':
            return [], False, True
        key = (obj.name, len(obj.data.polygons), len(obj.material_slots), self.state.setup_udim, len(obj.data.uv_layers))
        if self.setup_cache is None or self.setup_cache[0] != key:
            found = sets.has_udim(obj)
            self.setup_cache = (key, (sets.detect(obj, found and self.state.setup_udim), found, bool(obj.data.uv_layers)))
        return self.setup_cache[1]

    def highlight_batch(self, obj, slot):
        mesh = obj.data
        key = (obj.name, slot, len(mesh.polygons), tuple(obj.matrix_world.col[3]))
        if self.highlight_cache[0] != key:
            mesh.calc_loop_triangles()
            count = len(mesh.loop_triangles)
            vertices = numpy.empty(count * 3, dtype=numpy.int32)
            materials = numpy.empty(count, dtype=numpy.int32)
            mesh.loop_triangles.foreach_get('vertices', vertices)
            mesh.loop_triangles.foreach_get('material_index', materials)
            coordinates = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float32)
            mesh.vertices.foreach_get('co', coordinates)
            coordinates = coordinates.reshape(-1, 3)
            matrix = numpy.array(obj.matrix_world, dtype=numpy.float32)
            world = coordinates @ matrix[:3, :3].T + matrix[:3, 3]
            chosen = vertices.reshape(-1, 3)[materials == slot].ravel()
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            self.highlight_cache = (key, (shader, batch_for_shader(shader, 'TRIS', {'pos': world[chosen].tolist()}), int((materials == slot).sum())))
        return self.highlight_cache[1]

    def draw_highlight(self):
        if self._closed or self.highlight is None or bpy.context.area != self._area:
            return
        obj, data = self.painted()
        if data is None:
            return
        project = obj.devil_painter
        if self.highlight >= len(project.sets):
            return
        shader, batch, _ = self.highlight_batch(obj, project.sets[self.highlight].slot)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        shader.bind()
        shader.uniform_float('color', (*ACCENT[:3], HIGHLIGHT_ALPHA))
        batch.draw(shader)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')

    def update_highlight(self, event, control):
        obj, data = self.painted()
        if data is None:
            wanted = None
        elif control is not None and control.key.startswith('SET.'):
            wanted = int(control.key.removeprefix('SET.'))
        elif event.ctrl and event.alt:
            wanted = obj.devil_painter.active_set
        else:
            wanted = None
        if wanted != self.highlight:
            self.highlight = wanted
            self._area.tag_redraw()

    def pick_color(self, context):
        target = self.state.picking
        self.state.picking = ''
        obj, data = self.painted()
        previous = tuple(painting.brush_value(self.scene, 'color'))
        bpy.ops.paint.sample_color(location=(int(self.pointer[0]), int(self.pointer[1])), merged=True, palette=False)
        picked = tuple(painting.brush_value(self.scene, 'color'))
        self.remember_color(picked)
        if target == 'BRUSH':
            return 'Picked the brush color from the model.'
        painting.set_brush_value(self.scene, 'color', previous)
        if target.startswith('fx:'):
            return actions.edit_effect(context, obj, data, target.removeprefix('fx:'), tuple(float(part) for part in srgb_to_linear(numpy.array(picked))), True)
        channel, _, second = target.removeprefix('brush:').partition(':')
        value = tuple(float(part) for part in (srgb_to_linear(numpy.array(picked)) if CHANNEL[channel].srgb else picked))
        if target.startswith('brush:'):
            data.brush_slots[channel].color = value
            compositing.update_values(data)
            return f'Picked the brush {CHANNEL[channel].label.lower()} from the model.'
        actions.set_channel_value(context, obj, data, channel, value, second=bool(second))
        return actions.commit_value(context, obj, data, CHANNEL[channel].label)

    def remember_color(self, display):
        color = tuple(round(float(part), 4) for part in display[:3])
        recent = [item for item in self.state.recent_colors if item != color]
        self.state.recent_colors[:] = [color] + recent[:RECENT_COLORS - 1]

    def run_shortcut(self, context, action):
        obj, data = self.painted()
        if action in TOOL_ACTIONS:
            painting.activate_tool(context, action)
            painting.update_canvas(context, data)
            brushes.sync(context, data)
            return action.title() + ' tool.'
        if action in {'SIZE_DOWN', 'SIZE_UP'}:
            size = painting.brush_value(self.scene, 'size')
            factor = shortcuts.SIZE_STEP if action == 'SIZE_UP' else 1 / shortcuts.SIZE_STEP
            painting.set_brush_value(self.scene, 'size', max(1, min(MAX_BRUSH_SIZE, round(size * factor) + (1 if action == 'SIZE_UP' else -1))))
            return f'Brush size {painting.brush_value(self.scene, "size")} px.'
        if action == 'VIEW2D':
            return self.close_flat(context) if self.flat_space() is not None else self.open_flat(context)
        self.state.shelf_open = not self.state.shelf_open
        return 'Shelf shown.' if self.state.shelf_open else 'Shelf hidden.'

    def key_event(self, context, event):
        obj, data = self.painted()
        if data is None or event.ctrl or event.alt or event.oskey:
            return None
        if self.state.binding:
            action, self.state.binding = self.state.binding, ''
            if event.type == 'ESC':
                shortcuts.bind(action, '')
                self.message = 'Shortcut cleared.'
            elif event.type in shortcuts.BINDABLE and not event.shift:
                shortcuts.bind(action, event.type)
                self.message = f'{action.title()} now uses {shortcuts.key_label(event.type)}.'
            return {'RUNNING_MODAL'}
        action = shortcuts.action_for(event.type) if not event.shift else None
        if action is None:
            return None
        self.message = self.run_shortcut(context, action)
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def restore_mask_snapshot(self, obj):
        if self.saved_mask is not None and len(self.saved_mask[1][1]) != len(obj.data.polygons):
            self.saved_mask = (obj.name, (False, numpy.zeros(len(obj.data.polygons), dtype=bool)))

    def remember_mask(self, obj):
        project = obj.devil_painter
        if not project.mask_backup_set:
            project.mask_backup, project.mask_backup_set = obj.data.use_paint_mask, True
        if self.saved_mask is None:
            self.saved_mask = (obj.name, sets.remember_mask(obj.data))

    def restore_mask(self):
        if self.saved_mask is None:
            return
        obj = bpy.data.objects.get(self.saved_mask[0])
        if obj is not None and obj.type == 'MESH':
            project = obj.devil_painter
            flag = project.mask_backup if project.mask_backup_set else self.saved_mask[1][0]
            sets.restore_mask(obj.data, (flag, self.saved_mask[1][1]))
            project.mask_backup_set = False
        self.saved_mask = None

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
        self.sync_flat()
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
        self.update_highlight(event, control)
        if press and event.type == 'Z' and event.ctrl:
            self.history_step(context, redo=event.shift)
            return {'PASS_THROUGH'}
        if press and not pointer_event and (self.state.popover is None or self.state.popover.kind == 'SHORTCUTS'):
            result = self.key_event(context, event)
            if result is not None:
                return result
        if not over and press and event.type == 'LEFTMOUSE' and self.state.geo_pick:
            self.message = self.pick_geometry(context)
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if press and event.ctrl and event.type in {'C', 'V'} and control is not None and control.key.startswith(LAYER_KEYS):
            self.message = self.clipboard_key(context, event.type == 'V')
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if not over and press and event.type == 'LEFTMOUSE' and self.state.picking:
            self.message = self.pick_color(context)
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if not over or not pointer_event:
            if press and event.type == 'LEFTMOUSE' and not event.alt:
                self.begin_stroke(context)
            return {'PASS_THROUGH'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ROW_'):
            obj, data = self.painted()
            uid = control.key.removeprefix('ROW_')
            if uid not in self.chosen(data):
                self.state.multi.clear()
            actions.select_layer(context, obj, data, uid)
            self.open_layer_menu(control.rect, data)
            return {'RUNNING_MODAL'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ITEM.'):
            item = self.shelf_item(control.key)
            index = control.key.removeprefix('ITEM.')
            if item.user_index >= 0 and item.kind == 'SMART':
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_SMART.{item.user_index}', 'Delete smart material', False),))
            elif item.user_index >= 0:
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
            self.modifiers = (event.ctrl, event.shift)
            try:
                result = self.act(context, control, event.value == 'DOUBLE_CLICK')
            except (ValueError, RuntimeError) as failure:
                self.message = str(failure)
                result = None
            self._area.tag_redraw()
            if result is not None:
                return result
        return {'RUNNING_MODAL'}

    def flat_space(self):
        try:
            if self.flat_area is not None and self.flat_area in list(self._window.screen.areas) and self.flat_area.type == 'IMAGE_EDITOR':
                return self.flat_area.spaces.active
        except ReferenceError:
            pass
        self.flat_area = None
        self.state.view_2d = False
        return None

    def sync_flat(self):
        space = self.flat_space()
        if space is None:
            return
        obj, data = self.painted()
        image = variant(data, paint_target(data), active_tile(data)) if data is not None else None
        if space.image != image:
            space.image = image

    def open_flat(self, context):
        known = {area.as_pointer() for area in self._window.screen.areas}
        with context.temp_override(window=self._window, area=self._area, region=self._region):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=.5)
        area = next(item for item in self._window.screen.areas if item.as_pointer() not in known)
        area.type = 'IMAGE_EDITOR'
        space = area.spaces.active
        space.ui_mode = 'PAINT'
        for name in FLAT_REGIONS:
            if hasattr(space, name):
                setattr(space, name, False)
        space.uv_editor.show_uv = True
        self.flat_area = area
        self.state.view_2d = True
        self.sync_flat()
        return 'The 2D view shows the selected canvas in UV space. Paint on either side.'

    def close_flat(self, context):
        if self.flat_space() is not None:
            with context.temp_override(window=self._window, area=self.flat_area):
                bpy.ops.screen.area_close()
        self.flat_area = None
        self.state.view_2d = False
        return 'Closed the 2D view.'

    def begin_stroke(self, context):
        obj, data = self.painted()
        if data is None or obj.mode != 'TEXTURE_PAINT':
            return
        inside = 0 <= self.pointer[0] < self._region.width and 0 <= self.pointer[1] < self._region.height
        if inside:
            face = sets.face_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
            if face >= 0:
                message = actions.activate(context, obj, obj.devil_painter, *sets.locate(obj, obj.devil_painter, face))
                if message:
                    self.message = message
                    data = texture_set(obj)
        if inside and painting.uses_stroke_buffer(context, data):
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

    def chosen(self, data):
        self.state.multi &= {layer.uid for layer in data.layers}
        return [layer.uid for layer in data.layers if layer.uid in self.state.multi or layer.uid == data.active_uid]

    def clipboard_key(self, context, paste):
        obj, data = self.painted()
        if not paste:
            return self.copy_layers(obj, data)
        return self.paste('PASTE_LAYERS', context, obj)

    def copy_layers(self, obj, data):
        uids = tuple(self.chosen(data))
        self.state.clipboard = (obj.name, obj.devil_painter.active_set, uids)
        return f'Copied {len(uids)} layer{"s" if len(uids) > 1 else ""}.'

    def paste(self, key, context, obj):
        if not self.state.clipboard or self.state.clipboard[0] != obj.name:
            return 'Copy a layer first.'
        _, index, uids = self.state.clipboard
        project = obj.devil_painter
        if index >= len(project.sets) or not any(find_layer(project.sets[index], uid) for uid in uids):
            return 'The copied layers are gone.'
        uids = [uid for uid in uids if find_layer(project.sets[index], uid) is not None]
        if key == 'PASTE_LAYERS':
            return actions.paste_layers(context, obj, project, index, uids)
        if key == 'PASTE_MASK':
            return actions.paste_mask(context, obj, project, index, uids[0])
        return actions.paste_effects(context, obj, project, index, uids[0])

    def pick_geometry(self, context):
        obj, data = self.painted()
        face = sets.face_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
        if face < 0:
            return 'Click on the model to pick faces.'
        return actions.pick_geometry(context, obj, data, face, self.state.geo_pick == 'ISLAND')

    def drop_target(self, prefix):
        return next((control for control in self.workspace.controls if control.kind == 'ROW' and control.key.startswith(prefix)
                     and control.hit(*self.pointer)), None)

    def track_drop(self, key):
        if key.startswith('DRAG_ROW.'):
            target = self.drop_target('ROW_')
            if target is None or target.key == 'ROW_' + key.removeprefix('DRAG_ROW.'):
                self.state.drop = ()
                return
            obj, data = self.painted()
            height = (self.pointer[1] - target.rect.y) / target.rect.h
            folder = find_layer(data, target.key.removeprefix('ROW_')).kind == 'FOLDER'
            mode = ('ABOVE' if height > .66 else 'BELOW' if height < .33 else 'INTO') if folder else 'ABOVE' if height >= .5 else 'BELOW'
            self.state.drop = (target.key, mode)
            return
        uid, effect = key.removeprefix('DRAG_FX.').split('.')
        target = self.drop_target(f'FX_{uid}.')
        self.state.drop = () if target is None or target.key == f'FX_{uid}.{effect}' else (target.key, 'ABOVE')

    def finish_drop(self, context, key):
        drop, self.state.drop = self.state.drop, ()
        if not drop:
            return
        obj, data = self.painted()
        if key.startswith('DRAG_ROW.'):
            self.message = actions.drop_layer(context, obj, data, key.removeprefix('DRAG_ROW.'), drop[0].removeprefix('ROW_'), drop[1])
            return
        uid, effect = key.removeprefix('DRAG_FX.').split('.')
        layer = find_layer(data, uid)
        target = drop[0].split('.')[1]
        index = next(position for position, item in enumerate(layer.effects) if item.uid == target)
        self.message = actions.move_effect(context, obj, data, uid, effect, index)

    def select_row(self, context, obj, data, uid, control, double):
        ctrl, shift = self.modifiers
        if shift and data.active_uid:
            order = [layer.uid for layer, _, effect in layer_rows(data, self.state.collapsed) if effect is None]
            start, end = sorted((order.index(data.active_uid), order.index(uid))) if data.active_uid in order else (order.index(uid),) * 2
            self.state.multi = set(order[start:end + 1])
            data.active_uid = uid
            return f'{len(self.state.multi)} layers selected.'
        if ctrl:
            self.state.multi = set(self.chosen(data)) ^ {uid}
            if uid in self.state.multi:
                data.active_uid = uid
            elif self.state.multi:
                data.active_uid = next(layer.uid for layer in data.layers if layer.uid in self.state.multi)
            return f'{len(self.chosen(data))} layers selected.'
        self.state.multi.clear()
        key = control.key
        now = time.monotonic()
        repeated = self.last_click[0] == key and now - self.last_click[1] < DOUBLE_CLICK_SECONDS
        self.last_click = ('', 0.0) if double or repeated else (key, now)
        message = actions.select_layer(context, obj, data, uid)
        if double or repeated:
            self.begin_text(f'NAME_{uid}', active_layer(data).name)
        else:
            self.state.drag = ('DRAG_ROW.' + uid, control.rect)
        return message

    def open_effect_menu(self, key, control, data):
        effect = active_effect(data)
        if key == 'FX_BLEND':
            items = tuple((f'SET_FXBLEND.{mode}', label, mode == effect.blend) for mode, label in MASK_BLENDS)
        elif key == 'FX_FILTER':
            items = tuple((f'SET_FXFILTER.{item.key}', item.label, item.key == effect.filter) for item in FILTERS
                          if effect.target == 'CONTENT' or not item.color_only)
        elif key == 'FX_SOURCE':
            items = (('SET_FXSOURCE.VALUE', 'Plain value', effect.source == 'VALUE'),
                     ('FX_PICK_TEXTURE', 'Texture from the shelf', effect.source == 'IMAGE')) + tuple(
                (f'SET_FXPATTERN.{item.key}', 'Pattern · ' + item.label, effect.source == 'PATTERN' and effect.pattern == item.key) for item in PATTERNS)
        elif key == 'FX_OTHER':
            items = tuple((f'SET_FXOTHER.{layer.uid}', layer.name, layer.uid == effect.other) for layer in data.layers
                          if layer.uid != data.active_uid and layer.kind != 'INSTANCE') or (('NO_LAYER', 'No other layer', False),)
        else:
            items = tuple((f'SET_FXCHANNEL.{channel.key}', channel.label, channel.key == effect.channel) for channel in set_channels(data))
        self.state.popover = Popover('MENU', control.rect, items=items)

    def effect_act(self, context, obj, data, key, control):
        effect = active_effect(data)
        if key in {'ADD_FX_MASK', 'ADD_FX_CONTENT'}:
            self.state.popover = Popover('MENU', control.rect, items=effect_menu('MASK' if key == 'ADD_FX_MASK' else 'CONTENT'))
        elif key.startswith('NEW_FX.'):
            _, target, kind = key.split('.')
            self.message = actions.add_effect(context, obj, data, kind, target)
        elif key.startswith('FXEYE_'):
            uid, effect_uid = key.removeprefix('FXEYE_').split('.')
            self.message = actions.toggle_effect(context, obj, data, uid, effect_uid)
        elif key.startswith('FX_OPEN_'):
            self.state.collapsed ^= {key}
        elif key == 'FX_ENABLED':
            self.message = actions.toggle_effect(context, obj, data, data.active_uid, effect.uid)
        elif key in {'FX_UP', 'FX_DOWN'}:
            layer = active_layer(data)
            index = next(position for position, item in enumerate(layer.effects) if item.uid == effect.uid)
            self.message = actions.move_effect(context, obj, data, layer.uid, effect.uid, index + (1 if key == 'FX_UP' else -1))
        elif key == 'FX_DELETE':
            self.message = actions.delete_effect(context, obj, data)
        elif key in {'FX_BLEND', 'FX_FILTER', 'FX_SOURCE', 'FX_OTHER', 'FX_CHANNEL'}:
            self.open_effect_menu(key, control, data)
        elif key.startswith('SET_FXPATTERN.'):
            actions.edit_effect(context, obj, data, 'source', 'PATTERN', False)
            self.message = actions.edit_effect(context, obj, data, 'pattern', key.removeprefix('SET_FXPATTERN.'), True)
        elif key == 'FX_PICK_TEXTURE':
            self.state.armed = EFFECT_TARGET
            self.state.shelf_open, self.state.shelf_tab = True, 'TEXTURES'
            self.message = 'Click a texture in the shelf to fill the effect with it.'
        elif key.startswith('FXCOLOR.'):
            self.open_color(control, 'fx:' + key.removeprefix('FXCOLOR.'))
        elif key.startswith(('SET_FXBLEND.', 'SET_FXFILTER.', 'SET_FXSOURCE.', 'SET_FXOTHER.', 'SET_FXCHANNEL.')):
            prefix, value = key.split('.', 1)
            field = {'SET_FXBLEND': 'blend', 'SET_FXFILTER': 'filter', 'SET_FXSOURCE': 'source', 'SET_FXOTHER': 'other', 'SET_FXCHANNEL': 'channel'}[prefix]
            self.message = actions.edit_effect(context, obj, data, field, value, True)
        elif control.kind == 'ROW' and key.startswith('FX_'):
            uid, effect_uid = key.removeprefix('FX_').split('.')
            self.message = actions.select_effect(context, obj, data, uid, effect_uid)
            self.state.drag = (f'DRAG_FX.{uid}.{effect_uid}', control.rect)
        else:
            return False
        return True

    def stack_act(self, context, obj, data, key):
        uids = self.chosen(data)
        project = obj.devil_painter
        if key == 'COPY_LAYERS':
            self.message = self.copy_layers(obj, data)
        elif key in {'PASTE_LAYERS', 'PASTE_MASK', 'PASTE_EFFECTS'}:
            self.message = self.paste(key, context, obj)
        elif key == 'GROUP':
            self.message = actions.group_layers(context, obj, data, uids)
            self.state.multi.clear()
        elif key == 'FLATTEN':
            self.message = actions.flatten_layers(context, obj, project, uids)
            self.state.multi.clear()
            self.restore_mask_snapshot(obj)
        elif key in {'EXPORT_LAYER', 'EXPORT_MASK'}:
            directory = bpy.path.abspath(project.export_directory or default_directory(obj))
            self.message = actions.export_layer(context, obj, project, uids, directory, key == 'EXPORT_MASK')
        elif key.startswith('INSTANCE_INTO.'):
            self.message = actions.instance_into(context, obj, project, int(key.removeprefix('INSTANCE_INTO.')))
        elif key in {'HIDE_SELECTED', 'SHOW_SELECTED'}:
            self.message = actions.set_layers_visible(context, obj, data, uids, key == 'SHOW_SELECTED')
        elif key == 'DELETE_SELECTED':
            self.message = actions.delete_layers(context, obj, data, uids)
            self.state.multi.clear()
        elif key == 'DUPLICATE_SELECTED':
            self.message = actions.duplicate_layers(context, obj, data, uids)
        elif key.startswith('MOVE_SELECTED.'):
            index = int(key.removeprefix('MOVE_SELECTED.'))
            for uid in uids:
                source = project.sets[project.active_set]
                source.active_uid = uid
                self.message = actions.move_to_set(context, obj, project, index)
                project.active_set = project.sets.find(source.name)
            self.state.multi.clear()
            self.restore_mask_snapshot(obj)
        elif key.startswith('SET_FOLDERBLEND.'):
            self.message = actions.set_layer_field(context, obj, data, 'folder_blend', key.removeprefix('SET_FOLDERBLEND.'))
        elif key == 'GEO_MASK':
            self.message = actions.toggle_geometry_mask(context, obj, data)
            self.state.geo_pick = 'FACE' if active_layer(data).geo_mask else ''
        elif key in {'GEO_FACES', 'GEO_ISLANDS'}:
            mode = 'FACE' if key == 'GEO_FACES' else 'ISLAND'
            self.state.geo_pick = '' if self.state.geo_pick == mode else mode
            self.message = 'Click the model to pick ' + ('faces.' if mode == 'FACE' else 'mesh parts.') if self.state.geo_pick else 'Picking stopped.'
        elif key in {'GEO_INVERT', 'GEO_CLEAR'}:
            self.message = actions.edit_geometry(context, obj, data, key.removeprefix('GEO_'))
        else:
            return False
        return True

    def open_layer_menu(self, anchor, data):
        layer = active_layer(data)
        project = data.id_data.devil_painter
        uids = self.chosen(data)
        if len(uids) > 1:
            items = [('GROUP', 'Group into folder', False), ('FLATTEN', 'Flatten', False), ('EXPORT_LAYER', 'Export flattened', False),
                     ('COPY_LAYERS', 'Copy', False), ('DUPLICATE_SELECTED', 'Duplicate', False), ('HIDE_SELECTED', 'Hide', False),
                     ('SHOW_SELECTED', 'Show', False)]
            items += [(f'MOVE_SELECTED.{index}', 'Move to ' + item.name, False) for index, item in enumerate(project.sets) if index != project.active_set]
            items.append(('DELETE_SELECTED', f'Delete {len(uids)} layers', False))
            self.state.popover = Popover('MENU', anchor, items=tuple(items))
            return
        items = [('RENAME', 'Rename', False), ('DUPLICATE', 'Duplicate', False), ('COPY_LAYERS', 'Copy', False)]
        if self.state.clipboard:
            items += [('PASTE_LAYERS', 'Paste layers', False), ('PASTE_MASK', 'Paste mask', False), ('PASTE_EFFECTS', 'Paste effects', False)]
        if layer.kind == 'INSTANCE':
            items += [('MOVE_UP', 'Move up', False), ('MOVE_DOWN', 'Move down', False), ('DELETE', 'Delete', False)]
            self.state.popover = Popover('MENU', anchor, items=tuple(items))
            return
        if layer.kind == 'FOLDER':
            items.append(('FLATTEN', 'Flatten folder', False))
        items.append(('EXPORT_LAYER', 'Export flattened', False))
        if layer.mask is not None or layer.generator != 'NONE' or layer.geo_mask or len(layer.effects):
            items.append(('EXPORT_MASK', 'Export mask', False))
        if layer.kind != 'FOLDER':
            items += [(f'INSTANCE_INTO.{index}', 'Instance into ' + item.name, False) for index, item in enumerate(project.sets) if index != project.active_set]
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
        items.append(('SAVE_SMART', 'Save as smart material', False))
        items += [(f'MOVE_TO_SET.{index}', 'Move to ' + item.name, False) for index, item in enumerate(project.sets) if index != project.active_set]
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
            obj.devil_painter.export_directory = edit.text.strip()
        elif edit.key == 'EXPORT_PATTERN' and data is not None:
            obj.devil_painter.export_pattern = edit.text.strip() or '{mesh}_{set}_{output}'
        elif edit.key.startswith('OUT_NAME.') and data is not None:
            exporting.edit_output(obj.devil_painter.export_template, int(edit.key.removeprefix('OUT_NAME.')), name=edit.text.strip() or 'Output')
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
        elif key in SHADER_RANGES and data is not None:
            field, top = SHADER_RANGES[key]
            actions.set_set_value(context, obj, data, field, x * top, False)
            if release:
                self.message = actions.set_set_value(context, obj, data, field, x * top, True)
        elif key == 'PHYS_SIZE' and data is not None:
            obj.devil_painter.physical_size = max(.01, x * 10)
            compositing.update_values(data)
            if release:
                self.message = actions.set_project_value(context, obj, obj.devil_painter, 'physical_size', max(.01, x * 10))
        elif key in {'ENV_ROTATION', 'ENV_STRENGTH', 'CAMERA_FOV'}:
            space = self._area.spaces.active
            if key == 'ENV_ROTATION':
                space.shading.studiolight_rotate_z = x * 2 * math.pi - math.pi
            elif key == 'ENV_STRENGTH':
                space.shading.studiolight_intensity = x * 2
            else:
                space.lens = FOV_RANGE[0] + x * (FOV_RANGE[1] - FOV_RANGE[0])
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
        elif key.startswith(('DRAG_ROW.', 'DRAG_FX.')):
            self.track_drop(key)
            if release:
                self.finish_drop(context, key)
        elif key.startswith('FX_') and key.removeprefix('FX_') in FX_RANGES and data is not None:
            field = key.removeprefix('FX_')
            top, floor = FX_RANGES[field]
            value = max(floor, x * top)
            actions.edit_effect(context, obj, data, field, value, False)
            if release:
                self.message = actions.edit_effect(context, obj, data, field, value, True)
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
        elif target.startswith('fx:') and data is not None:
            message = actions.edit_effect(context, obj, data, target.removeprefix('fx:'), tuple(float(part) for part in srgb_to_linear(numpy.array(display))), commit)
            self.message = message or self.message
        elif data is not None:
            channel, _, second = target.partition(':')
            value = srgb_to_linear(numpy.array(display)) if CHANNEL[channel].srgb else display
            actions.set_channel_value(context, obj, data, channel, tuple(float(part) for part in value), second=bool(second))
            if commit:
                self.message = actions.commit_value(context, obj, data, CHANNEL[channel].label)
        if commit:
            self.remember_color(display)

    def open_color(self, control, target):
        obj, data = self.painted()
        if target == 'BRUSH':
            display = painting.brush_value(self.scene, 'color')
        elif target.startswith('brush:'):
            channel = target.removeprefix('brush:')
            value = numpy.array(data.brush_slots[channel].color)
            display = linear_to_srgb(value) if CHANNEL[channel].srgb else value
        elif target.startswith('fx:'):
            display = linear_to_srgb(numpy.array(getattr(active_effect(data), target.removeprefix('fx:'))))
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
        if data is not None and control.kind != 'SLIDER' and (self.effect_act(context, obj, data, key, control) or self.stack_act(context, obj, data, key)):
            return None
        if key == 'FOLDER_BLEND':
            current = active_layer(data).folder_blend
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_FOLDERBLEND.{mode}', label, mode == current) for mode, label in FOLDER_BLENDS))
        elif key.startswith('RES.'):
            _, index, size = key.split('.')
            self.state.setup_resolutions[int(index)] = int(size)
        elif key == 'SETUP_UDIM':
            self.state.setup_udim = not self.state.setup_udim
        elif key == 'START':
            rows, found, _ = self.setup(obj, data)
            resolutions = [self.state.setup_resolutions.get(index, 2048) for index in range(max(1, len(rows)))]
            if obj is not None and obj.type == 'MESH':
                self.remember_mask(obj)
            self.message = actions.start(context, obj, resolutions, found and self.state.setup_udim, self.state.setup_template,
                                         self.state.setup_normal_format, self.state.setup_normal_space, self.state.setup_unwrap)
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
        elif key == 'VIEW2D':
            self.message = self.close_flat(context) if self.flat_space() is not None else self.open_flat(context)
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
        elif key == 'SAVE_SMART':
            self.message = f'Saved {smart.save_smart(active_layer(data))} to the smart material shelf.'
        elif key.startswith('DELETE_SMART.'):
            self.message = f'Deleted {smart.remove_smart(int(key.removeprefix("DELETE_SMART.")))}.'
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
            project = obj.devil_painter
            directory = bpy.path.abspath(project.export_directory or default_directory(obj))
            self.state.popover = None
            self.message = actions.export(context, obj, project, directory)
        elif key.startswith('SET.'):
            self.message = actions.activate(context, obj, obj.devil_painter, int(key.removeprefix('SET.')), obj.devil_painter.active_tile)
        elif key.startswith('TILE.'):
            project = obj.devil_painter
            self.message = actions.activate(context, obj, project, project.active_set, int(key.removeprefix('TILE.')))
        elif key.startswith('SETRES.'):
            index = int(key.removeprefix('SETRES.'))
            current = obj.devil_painter.sets[index].resolution
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_SETRES.{index}.{size}', f'{size} px', size == current)
                                                                          for size in RESOLUTIONS))
        elif key.startswith('SET_SETRES.'):
            _, index, size = key.split('.')
            self.message = actions.set_resolution(context, obj, obj.devil_painter.sets[int(index)], int(size))
        elif key in EXPORT_MENUS or key.startswith(EXPORT_MENU_PREFIXES):
            self.open_export_menu(obj.devil_painter, key, control)
        elif key.startswith(EXPORT_EDITS) or key in {'TEMPLATE_DUPLICATE', 'TEMPLATE_DELETE', 'OUT_ADD'}:
            self.message = self.edit_export(obj.devil_painter, key)
        elif key.startswith('OUT_NAME.') or key == 'EXPORT_PATTERN':
            self.begin_text(key, control.text)
        elif key.startswith('EXPORT_SET.'):
            item = obj.devil_painter.sets[int(key.removeprefix('EXPORT_SET.'))]
            item.export = not item.export
        elif key.startswith('BLEND.'):
            channel = key.removeprefix('BLEND.')
            current = active_layer(data).slots[channel].blend
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BLEND.{channel}.{mode}', label, mode == current)
                                                                          for mode, label in BLEND_MODES))
        elif key.startswith('SET_BLEND.'):
            _, channel, mode = key.split('.')
            self.message = actions.set_blend(context, obj, data, channel, mode)
        elif key in {'CHANNELS', 'PROJECT', 'VIEWPORT', 'OPEN_SHORTCUTS'}:
            kind = 'SHORTCUTS' if key == 'OPEN_SHORTCUTS' else key
            same = self.state.popover is not None and self.state.popover.kind == kind
            self.state.popover = None if same else Popover(kind, control.rect)
        elif key.startswith('CHANSET.'):
            channel = key.removeprefix('CHANSET.')
            self.message = actions.set_channel_enabled(context, obj, obj.devil_painter, channel, not data.channels[channel].enabled, self.state.channels_all)
        elif key == 'CHANNELS_ALL':
            self.state.channels_all = not self.state.channels_all
        elif key.startswith(('PNF.', 'PNS.')):
            field = 'normal_format' if key.startswith('PNF.') else 'normal_space'
            self.message = actions.set_project_value(context, obj, obj.devil_painter, field, key.split('.', 1)[1])
        elif key == 'PHYS_USE':
            self.message = actions.set_project_value(context, obj, obj.devil_painter, 'use_physical', not obj.devil_painter.use_physical)
        elif key.startswith('SHADER.'):
            self.message = actions.set_set_value(context, obj, data, 'shader', key.removeprefix('SHADER.'), True)
        elif key == 'REIMPORT':
            bpy.ops.devil_painter.reimport_mesh('INVOKE_DEFAULT')
        elif key == 'REIMPORT_OBJECT':
            meshes = [item.name for item in context.view_layer.objects if item.type == 'MESH' and item != obj]
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'REIMPORT_FROM.{name}', name, False) for name in meshes)
                                         or (('NO_MESH', 'No other mesh in the scene', False),))
        elif key.startswith('REIMPORT_FROM.'):
            source = bpy.data.objects[key.removeprefix('REIMPORT_FROM.')]
            self.message = actions.reimport_mesh(context, obj, obj.devil_painter, source.data.copy())
            self.restore_mask_snapshot(obj)
        elif key == 'ENV':
            lights = [light.name for light in context.preferences.studio_lights if light.type == 'WORLD']
            current = self._area.spaces.active.shading.studio_light
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_ENV.{index}', name.rsplit('.', 1)[0], name == current)
                                                                          for index, name in enumerate(lights)))
        elif key.startswith('SET_ENV.'):
            lights = [light.name for light in context.preferences.studio_lights if light.type == 'WORLD']
            self._area.spaces.active.shading.studio_light = lights[int(key.removeprefix('SET_ENV.'))]
            self.message = 'Environment changed.'
        elif key == 'ENV_BACKGROUND':
            shading = self._area.spaces.active.shading
            shading.studiolight_background_alpha = 0.0 if shading.studiolight_background_alpha > .5 else 1.0
        elif key == 'CAMERA_ORTHO':
            view = self._area.spaces.active.region_3d
            view.view_perspective = 'PERSP' if view.view_perspective == 'ORTHO' else 'ORTHO'
        elif key.startswith('SETEYE.'):
            self.message = actions.toggle_set_visible(context, obj, obj.devil_painter, int(key.removeprefix('SETEYE.')))
        elif key.startswith('MOVE_TO_SET.'):
            self.message = actions.move_to_set(context, obj, obj.devil_painter, int(key.removeprefix('MOVE_TO_SET.')))
            self.restore_mask_snapshot(obj)
        elif key == 'COLOR_PICK':
            self.state.picking = self.state.popover.target
            self.state.popover = None
            self.message = 'Click the model to pick a color.'
        elif key.startswith('RECENT.'):
            red, green, blue = self.state.recent_colors[int(key.removeprefix('RECENT.'))]
            self.state.hsv = colorsys.rgb_to_hsv(red, green, blue)
            self.apply_color(context, commit=True)
        elif key.startswith('BIND.'):
            self.state.binding = key.removeprefix('BIND.')
            self.message = 'Press the new key, or Esc to clear it.'
        elif key == 'SETUP_TEMPLATE':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_SETUP_TEMPLATE.{index}', item['name'], item['name'] == self.state.setup_template)
                                                                          for index, item in enumerate(projects.PROJECT_TEMPLATES)))
        elif key.startswith('SET_SETUP_TEMPLATE.'):
            template = projects.PROJECT_TEMPLATES[int(key.removeprefix('SET_SETUP_TEMPLATE.'))]
            self.state.setup_template, self.state.setup_normal_format = template['name'], template['normal_format']
        elif key.startswith(('SETUP_NF.', 'SETUP_NS.', 'SETUP_UNWRAP.')):
            prefix, value = key.split('.', 1)
            setattr(self.state, {'SETUP_NF': 'setup_normal_format', 'SETUP_NS': 'setup_normal_space', 'SETUP_UNWRAP': 'setup_unwrap'}[prefix], value)
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
            self.message = self.select_row(context, obj, data, key.removeprefix('ROW_'), control, double)
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
        if armed == EFFECT_TARGET and item.kind == 'TEXTURE' and active_effect(data) is not None:
            actions.edit_effect(context, obj, data, 'texture', library.load_image(item.payload, CHANNEL['roughness']), False)
            return actions.edit_effect(context, obj, data, 'source', 'IMAGE', True)
        armed = '' if armed in {REPLACE_TARGET, EFFECT_TARGET} else armed
        target = armed if armed and layer is not None and layer.kind == 'FILL' else ''
        if item.kind == 'SMART':
            return actions.add_smart_material(context, obj, data, item.payload)
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

    def open_export_menu(self, project, key, control):
        template = exporting.find_template(project.export_template)
        if key == 'EXPORT_TEMPLATE':
            items = tuple((f'SET_TEMPLATE.{index}', item['name'], item['name'] == template['name']) for index, item in enumerate(exporting.all_templates()))
        elif key == 'EXPORT_DEPTH':
            items = tuple((f'SET_EXPORT_DEPTH.{depth}', 'From template' if depth == 'TEMPLATE' else depth + '-bit', depth == project.export_depth)
                          for depth in exporting.DEPTHS)
        elif key == 'EXPORT_SIZE':
            items = tuple((f'SET_EXPORT_SIZE.{size}', f'{size} px' if size else 'Texture set size', size == project.export_size) for size in exporting.SIZES)
        elif key == 'EXPORT_PADDING':
            items = tuple((f'SET_EXPORT_PADDING.{padding}', 'Infinite' if padding < 0 else f'{padding} px', padding == project.export_padding)
                          for padding in exporting.PADDINGS)
        elif key.startswith('OUT_SRC.'):
            _, index, slot = key.split('.')
            items = tuple((f'SET_SRC.{index}.{slot}.{source}', label, False) for source, (label, _, _) in exporting.SOURCES.items())
            if slot in {'1', '3'}:
                items += ((f'SET_SRC.{index}.{slot}.none', 'Single channel' if slot == '1' else 'No alpha', False),)
        elif key.startswith('OUT_FORMAT.'):
            index = key.removeprefix('OUT_FORMAT.')
            items = tuple((f'SET_FORMAT.{index}.{name}', label, False) for name, label in exporting.FORMAT_LABELS.items())
        else:
            index = int(key.removeprefix('OUT_DEPTH.'))
            allowed = exporting.FORMATS[template['outputs'][index]['format']][1]
            items = tuple((f'SET_DEPTH.{index}.{depth}', depth + '-bit', False) for depth in allowed)
        self.state.popover = Popover('MENU', control.rect, items=items)

    def edit_export(self, project, key):
        name = project.export_template
        if key.startswith('SET_TEMPLATE.'):
            project.export_template = exporting.all_templates()[int(key.removeprefix('SET_TEMPLATE.'))]['name']
            return f'Exporting with the {project.export_template} template.'
        if key.startswith('SET_EXPORT_DEPTH.'):
            project.export_depth = key.removeprefix('SET_EXPORT_DEPTH.')
            return 'Bit depth set.'
        if key.startswith('SET_EXPORT_SIZE.'):
            project.export_size = int(key.removeprefix('SET_EXPORT_SIZE.'))
            return 'Export size set.'
        if key.startswith('SET_EXPORT_PADDING.'):
            project.export_padding = int(key.removeprefix('SET_EXPORT_PADDING.'))
            return 'Padding set.'
        if key == 'TEMPLATE_DUPLICATE':
            project.export_template = exporting.duplicate_template(name)
            return f'Created the editable {project.export_template} template.'
        if key == 'TEMPLATE_DELETE':
            exporting.delete_template(name)
            project.export_template = exporting.BUILTIN_TEMPLATES[0]['name']
            return f'Deleted the {name} template.'
        if key == 'OUT_ADD':
            exporting.add_output(name)
            return 'Added an output.'
        if key.startswith('OUT_REMOVE.'):
            exporting.remove_output(name, int(key.removeprefix('OUT_REMOVE.')))
            return 'Removed the output.'
        if key.startswith('SET_SRC.'):
            _, index, slot, source = key.split('.', 3)
            exporting.set_source(name, int(index), int(slot), source)
            return 'Channel packing updated.'
        if key.startswith('SET_FORMAT.'):
            _, index, file_format = key.split('.')
            exporting.set_format(name, int(index), file_format)
            return 'Format updated.'
        _, index, depth = key.split('.')
        exporting.edit_output(name, int(index), depth=depth)
        return 'Bit depth updated.'

    def cleanup(self):
        global _active
        if self._closed:
            return
        self._closed = True
        try:
            self.restore_mask()
        except ReferenceError:
            self.saved_mask = None
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        if self._view_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._view_handle, 'WINDOW')
            self._view_handle = None
            self._handle = None
        if self._timer is not None:
            bpy.context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        try:
            space = self._area.spaces.active
            with bpy.context.temp_override(window=self._window, area=self._area):
                for name, value in self.saved_regions.items():
                    if not space.is_property_readonly(name):
                        setattr(space, name, value)
            self._area.tag_redraw()
        except ReferenceError:
            pass
        try:
            self.close_flat(bpy.context)
        except (ReferenceError, RuntimeError):
            self.flat_area = None
        if _active is self:
            _active = None

    def cancel(self, context):
        self.cleanup()
