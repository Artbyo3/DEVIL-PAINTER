import colorsys
import itertools
import time
import traceback
from pathlib import Path
import PyOpenColorIO
import bpy
import numpy
import math
import gpu
from gpu_extras.batch import batch_for_shader
from . import actions, autosave, bakejob, baking, bridge, brushes, caches, compositing, dynamics, history, packs, tiles, exporting, library, meshmaps, painting, polyfill, post, projection, vectors, projects, sets, shelf, shortcuts, smart, strokes, thumbnails
from .blending import BLEND_MODES, CHANNEL, FOLDER_BLENDS, linear_to_srgb, srgb_to_linear
from .ui_system import ACCENT
from .canvas import Rect
from .document import (BAKE_ANTIALIAS_LABELS, BAKE_CURVATURE_LABELS, BAKE_ID_LABELS, BAKE_RESOLUTIONS, CHANNEL_DEPTHS, DISPLACEMENT_SCALE_MAX, DISPLACEMENT_SUBDIVISION_MAX, DYNAMICS, PROJECTIONS, PROJECTORS, RESOLUTIONS, STROKE_METHODS, TEXTURE_SAMPLING, active_effect, active_layer, active_tile, bake_map_settings, find_layer,
                       editing_mask, map_extrusion, map_samples, paint_target, set_channels, slot_value, texture_set, uses_coordinates)
from .effects import FILL_PROJECTIONS, LEVEL_COMPONENTS, MASK_BLENDS, LevelsView, mask_effects
from .filters import FILTER, FILTERS, GROUPS
from .post import POST_SLIDERS
from .compositing import PIN_CORNERS
from .procedural import PATTERNS
from .tiles import FIRST_TILE, variant
from bpy_extras import view3d_utils
from mathutils import Euler, Matrix, Vector
from .draw import TOAST_SECONDS, Renderer
from .privacy import masked
from .masks import BREAKUPS, GENERATORS
from .polyfill import POLY_NOUN
from .meshmaps import MESH_MAPS
from .minimal import MENU_HEADING, SAMPLE_TOP, EXPOSURE_RANGE, GAMMA_RANGE, PROJECTOR_RANGE, NORMAL_SLIDERS, STENCIL_SLIDERS, FX_RANGES, effect_menu, layer_rows, FOV_RANGE, RECENT_COLORS, SHADER_SLIDERS, BRUSH_SLIDERS, BRUSH_TOGGLES, BREAKUP_DETAIL, GENERATOR_SLIDERS, MAX_BRUSH_SIZE, MAX_WORLD_SIZE, REPLACE_TARGET, EFFECT_TARGET, SCALE_RANGE, TILING_RANGE, from_slider, painter_layout
from .shell import COLUMNS, HEADER, HEIGHTS, PANELS, ROWS_ONLY, SECTIONS, SIDES, WIDTHS, clamp_length, clamp_strip, default_strips, flexible, place, resize_run
from .state import Popover, TextEdit, WorkspaceState, format_number, parse_number

TIMER_INTERVAL = .3
GESTURE_TOOLS = {'ERASE', 'BLUR', 'SMEAR', 'CLONE'}
LINE_TOOLS = painting.BUFFER_TOOLS - {'FILL'}
DRAG_START = 8
SLIDER_DRAG_START = 4
NUMERIC_KEYS = {**{name: str(index) for index, name in enumerate(('ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'))},
                **{f'NUMPAD_{index}': str(index) for index in range(10)},
                'PERIOD': '.', 'NUMPAD_PERIOD': '.', 'MINUS': '-', 'NUMPAD_MINUS': '-', 'PLUS': '+', 'NUMPAD_PLUS': '+'}
ENV_ROTATE_PIXELS = 720.0
AUTOSAVE_DEFAULT = 5
POST_RANGES = {key: (field, top) for key, _, field, top in POST_SLIDERS}
ONTO_KINDS = {'MASK', 'GENERATOR', 'FILTER'}
LAYER_KINDS = {'MATERIAL', 'SMART', 'TEXTURE', 'PATTERN'}


def choices(scene, field):
    config = PyOpenColorIO.GetCurrentConfig()
    if field == 'view_transform':
        return list(config.getViews(scene.display_settings.display_device)) or [scene.view_settings.view_transform]
    names = list(config.getLookNames())
    prefix = scene.view_settings.view_transform.split(' - ', 1)[0] + ' - '
    scoped = [name for name in names if name.startswith(prefix)]
    return ['None'] + (scoped or [name for name in names if ' - ' not in name])
STROKE_LABEL = {key: label for key, label, _ in STROKE_METHODS}
NORMAL_KEYS = {key for key, _, _, _ in NORMAL_SLIDERS}
DRAG_FIELDS = {key: (field, top) for key, _, field, top in (*NORMAL_SLIDERS, *STENCIL_SLIDERS)}
DOUBLE_CLICK_SECONDS = .4
SCROLL_STEP = 40
POINTER_TOKENS = ('MOUSE', 'TRACKPAD', 'NDOF', 'PEN', 'ERASER')
HIDDEN_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_asset_shelf', 'show_gizmo_navigate')
FLAT_REGIONS = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_region_ui', 'show_region_asset_shelf')
MOVES = {'MOVE_UP': 1, 'MOVE_DOWN': -1}
EXPORT_MENUS = {'EXPORT_TEMPLATE', 'EXPORT_DEPTH', 'EXPORT_SIZE', 'EXPORT_PADDING', 'EXPORT_PADDING_STYLE'}
HIGHLIGHT_ALPHA = .35
SHADER_RANGES = {key: (field, top) for key, _, field, top in SHADER_SLIDERS}
TOOL_ACTIONS = {'PAINT', 'ERASE', 'FILL', 'BLUR', 'SMEAR', 'CLONE'}
EXPORT_MENU_PREFIXES = ('OUT_SRC.', 'OUT_FORMAT.', 'OUT_DEPTH.')
EXPORT_EDITS = ('SET_TEMPLATE.', 'SET_EXPORT_DEPTH.', 'SET_EXPORT_SIZE.', 'SET_EXPORT_PADDING.', 'SET_EXPORT_PADDING_STYLE.', 'OUT_REMOVE.', 'SET_SRC.', 'SET_FORMAT.', 'SET_DEPTH.')
PROJECTION_LABELS = {key: label for key, label, _ in PROJECTIONS}
CIRCLE_STEPS = 32
BRUSH_RANGES = {key: (field, top, .01 if key == 'BRUSH_FLOW' else 1.0 if key == 'BRUSH_SPACING' else 0.0) for key, _, field, top, _ in BRUSH_SLIDERS}
BRUSH_FLAGS = {key: field for key, _, field in BRUSH_TOGGLES}
GENERATOR_RANGES = {**{key: (field, top) for key, _, field, top in GENERATOR_SLIDERS + (BREAKUP_DETAIL,)},
                    **{term.slider: (term.weight, 1.0) for generator in GENERATORS for term in generator.terms}}
BAKE_OBJECTS = {'BAKE_SOURCE': ('bake_source', 'SET_SOURCE.'), 'BAKE_CAGE': ('bake_cage', 'SET_CAGE.')}
AUTO_BAKE_DELAY = 1.0
LAYER_KEYS = ('ROW_', 'FX_', 'EYE_', 'FXEYE_', 'MASKTHUMB_')
_active = None
_pending_regions = []


def give_back_regions(space, saved):
    for name, value in saved.items():
        if not space.is_property_readonly(name) and not getattr(space, name):
            setattr(space, name, value)


def found_window(address):
    return next((window for window in bpy.context.window_manager.windows if window.as_pointer() == address), None)


def found_space(window, address):
    return next((space for area in window.screen.areas for space in area.spaces if space.as_pointer() == address), None)


def regions_after_full_screen():
    for pending in list(_pending_regions):
        window_address, space_address, saved = pending
        window = found_window(window_address)
        if window is not None and window.screen.show_fullscreen:
            continue
        space = None if window is None else found_space(window, space_address)
        if space is not None:
            give_back_regions(space, saved)
            for area in window.screen.areas:
                area.tag_redraw()
        _pending_regions.remove(pending)
    return .1 if _pending_regions else None


def close_active():
    if _active is not None:
        _active.cleanup()


def sync_history(redo):
    if _active is None or _active._closed:
        return
    if history.sync_external(redo):
        _active.after_history(bpy.context)


def accepts_drop(context):
    return (_active is not None and not _active._closed and context.area is not None
            and context.region is not None and context.region.type == 'WINDOW'
            and context.area in {_active._area, _active.flat_area})


def notify(message):
    if _active is None or _active._closed:
        return
    _active.message = message
    _active.toast_text = None
    if _active._area in list(_active._window.screen.areas):
        _active._area.tag_redraw()


def default_directory(obj):
    if bpy.data.filepath:
        return bpy.path.abspath('//textures')
    return str(Path.home() / 'Devil Painter Textures' / bpy.path.clean_name(obj.name))


def parse_hex(text):
    digits = text.strip().lstrip('#')
    if len(digits) != 6:
        raise ValueError('Type six hex digits, like #C83A4F.')
    return tuple(int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4))


def wrap_angle(angle):
    return (angle + math.pi) % math.tau - math.pi


def parse_world_size(scene, text):
    raw = text.strip()
    if not raw:
        raise ValueError('Type a number.')
    units = scene.unit_settings
    try:
        length = bpy.utils.units.to_value(units.system, 'LENGTH', raw)
        if not math.isfinite(length):
            raise ValueError
        value = length / (units.scale_length or 1.0)
    except ValueError:
        value = parse_number(raw, .001, MAX_WORLD_SIZE, units=('m',))
    return max(.001, min(MAX_WORLD_SIZE, float(value)))


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
        self._window_address = context.window.as_pointer()
        self._region = next(r for r in context.area.regions if r.type == 'WINDOW')
        self.pointer = (0, 0)
        self.message = ''
        self.toast_text = None
        self.toast_until = 0.0
        self.toast_rect = None
        self.toast_revealed = False
        self.view_key = None
        self.state = WorkspaceState()
        self.load_column()
        self.message = library.settings_notice()
        self.last_click = ('', 0.0)
        self.modifiers = (False, False, False)
        self._closed = False
        self.failure = None
        self.saved_regions = {}
        self.hide_regions()
        obj = context.view_layer.objects.active
        data = texture_set(obj)
        self.stroke_pending = False
        self.direct_stroke = None
        self.stroke_label_pending = ''
        self.stencil_pending = False
        self.stencil_region = (0, 0)
        self.line_anchor = None
        self.below_pending, self.below_since = (), 0.0
        self.drag_origin = (0.0, 0.0)
        self.drag_moved = False
        self.engine_before = ''
        self.world_pixels = (0, 0)
        self.fonts = []
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
        self._space_address = space.as_pointer()
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
        viewport = (space.shading, space.lens, space.region_3d.view_perspective == 'ORTHO', self.scene.view_settings,
                    obj.devil_painter if data is not None else None, self.scene.cycles)
        self.state.gizmo = self.gizmo_geometry(obj, data, space.region_3d)
        if data is not None and self.state.popover is not None and self.state.popover.kind == 'BAKE':
            self.state.bake_found = meshmaps.bake_sources(bpy.context, obj, data)
        self.state.baking = bakejob.status()
        return painter_layout(self.bounds, scale, self.state, data, name, painting.active_tool(self.scene), brush, directory, self.setup(obj, data),
                              viewport)

    def auto_bake(self, context):
        obj, data = self.painted()
        if data is None or not data.bake_auto or obj.mode != 'TEXTURE_PAINT' or self.stroke_pending or bakejob.running():
            return
        current = meshmaps.signature(context, obj, data)
        if current == data.bake_signature:
            self.state.bake_pending = ''
        elif current != self.state.bake_pending:
            self.state.bake_pending, self.state.bake_since = current, time.monotonic()
        elif time.monotonic() - self.state.bake_since >= AUTO_BAKE_DELAY:
            self.state.bake_pending = ''
            message = actions.rebake(context, obj, data)
            if message:
                self.message = message
                self._area.tag_redraw()

    def poll_bake(self, context):
        finished = bakejob.poll()
        if finished is not None:
            job, _ = finished
            self.message = actions.land_bake(context, *finished)
            if not job.rebake and self.state.popover is not None and self.state.popover.kind == 'BAKE':
                self.state.popover = None
        if finished is not None or bakejob.running():
            self._area.tag_redraw()

    def refresh_below(self, context):
        obj, data = self.painted()
        if (data is None or obj.mode != 'TEXTURE_PAINT' or self.stroke_pending or self.state.drag is not None
                or any(operator.bl_idname.startswith('PAINT_OT') for operator in self._window.modal_operators)):
            return
        stale = tuple(stamp for _, stamp in baking.stale_below(obj.devil_painter))
        if stale != self.below_pending:
            self.below_pending, self.below_since = stale, time.monotonic()
            return
        if not stale or time.monotonic() - self.below_since < AUTO_BAKE_DELAY:
            return
        self.below_pending = ()
        if baking.refresh_below(context, obj, obj.devil_painter):
            painting.enter_paint_mode(context, obj)
            sets.mask_faces(obj, obj.devil_painter)
            painting.update_canvas(context, data)
            self._area.tag_redraw()

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
        if target.startswith(('id:', 'idadd:')):
            face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
            if face < 0:
                return 'Click on the model to pick an ID color.'
            mode, effect_uid = target.split(':', 1)
            return actions.pick_id_color(context, obj, data, effect_uid, face, location, mode == 'idadd')
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
            if data is not None and brushes.world_sized(data):
                data.brush_world_size = data.brush_world_size * factor
                return f'Brush size {brushes.world_size_text(data.brush_world_size)}.'
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
        if self._closed or self.failure is not None:
            return
        context = bpy.context
        if context.area != self._area or context.region != self._region or context.window != self._window:
            return
        try:
            with thumbnails.foreground():
                thumbnails.begin_frame()
                self.workspace = self.make_layout()
                self.renderer.draw(self)
        except Exception as failure:
            traceback.print_exception(failure)
            self.failure = failure
            self._area.tag_redraw()

    def fail(self, failure):
        self.cleanup()
        self.report({'WARNING'}, f'Devil Painter closed after an internal error ({type(failure).__name__}: {failure}). Your work is kept; reopen it with Ctrl+Alt+P.')
        return {'CANCELLED'}

    def modal(self, context, event):
        if self._closed:
            return {'FINISHED'}
        if self.failure is not None:
            return self.fail(self.failure)
        try:
            with thumbnails.foreground():
                return self.handle_event(context, event)
        except ReferenceError:
            self.cleanup()
            self.report({'WARNING'}, 'Devil Painter closed because the view or scene it was using is gone. Reopen it from View > Devil Painter.')
            return {'CANCELLED'}
        except Exception as failure:
            traceback.print_exception(failure)
            return self.fail(failure)

    def handle_event(self, context, event):
        if self._area not in list(self._window.screen.areas) or self._area.type != 'VIEW_3D':
            self.cleanup()
            return {'FINISHED'}
        if event.type in {'TIMER', 'MOUSEMOVE'} and self.stroke_pending:
            self.finish_stroke(context)
        if self.stencil_pending and not self.stencil_moving():
            self.finish_stencil(context)
        if event.type == 'TIMER':
            self.poll_bake(context)
            self.auto_bake(context)
            self.refresh_below(context)
            self.follow_view()
            for note in packs.poll() + [autosave.failure_notice()]:
                if note:
                    self.message = note
                    self._area.tag_redraw()
            if packs.active():
                self._area.tag_redraw()
            if thumbnails.waiting():
                thumbnails.dispatch()
                self._area.tag_redraw()
            elif time.monotonic() < self.toast_until + TIMER_INTERVAL:
                self._area.tag_redraw()
            return {'PASS_THROUGH'}
        if event.type == 'EVT_DROP':
            return {'PASS_THROUGH'}
        self.sync_flat()
        self.sync_stencil_resize(context)
        self.drop_stale_anchor()
        self.workspace = self.make_layout()
        self.pointer = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
        press = event.value == 'PRESS'
        pointer_event = any(token in event.type for token in POINTER_TOKENS)
        if self.state.gesture is not None:
            return self.gesture_event(context, event)
        if press and event.type == 'LEFTMOUSE' and not event.alt and self.state.popover is None                 and not (self.workspace.covers(*self.pointer) or self.workspace.hit(*self.pointer)):
            if event.shift and not event.ctrl and self.draws_lines():
                return self.shift_line(context, event)
            if self.wants_gesture(context):
                return self.start_gesture(context, event)
        if press and event.ctrl and event.alt and event.type == 'P':
            self.cleanup()
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            self._area.tag_redraw()
            self.track_world_size()
        if self.state.text is not None:
            result = self.text_event(context, event, pointer_event)
            if result is not None:
                return result
        if self.state.drag is not None:
            return self.drag_event(context, event)
        if (press and event.type == 'LEFTMOUSE' and self.toast_rect is not None and self.toast_rect.contains(*self.pointer) and masked(self.message) != self.message
                and not self.workspace.covers(*self.pointer) and self.workspace.hit(*self.pointer) is None):
            self.toast_revealed = not self.toast_revealed
            self.toast_until = time.monotonic() + TOAST_SECONDS
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        layout = self.workspace
        control = layout.hit(*self.pointer)
        over = layout.covers(*self.pointer) or control is not None
        if press and event.type == 'RIGHTMOUSE' and not over:
            if self.wants_env_rotate(context, event):
                self.state.popover = None
                return self.start_env_rotate()
            self.stencil_pending = True
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
                        self.native_stroke(context, event)
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
        if press and event.type == 'Z' and event.ctrl and not event.alt:
            self.message = self.history_step(context, redo=event.shift)
            return {'RUNNING_MODAL'}
        if press and not pointer_event and (self.state.popover is None or self.state.popover.kind == 'SHORTCUTS'):
            result = self.key_event(context, event)
            if result is not None:
                return result
        if press and self.state.path_mode and event.type in {'RET', 'NUMPAD_ENTER', 'BACK_SPACE'} and self.state.text is None:
            self.message = self.apply_path(context) if event.type != 'BACK_SPACE' else self.drop_point()
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if not over and press and event.type == 'LEFTMOUSE' and self.state.path_mode and not self.state.picking:
            self.state.path_points.append(self.pointer)
            self.message = f'{len(self.state.path_points)} path points. Press Enter to paint.'
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if not over and press and event.type == 'LEFTMOUSE' and self.state.poly_mode and not self.state.picking:
            self.message = self.fill_polygons(context)
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
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
                self.native_stroke(context, event)
            return {'PASS_THROUGH'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ROW_'):
            obj, data = self.painted()
            uid = control.key.removeprefix('ROW_')
            if uid not in self.chosen(data):
                self.state.multi.clear()
            actions.select_layer(context, obj, data, uid)
            self.open_layer_menu(control.rect, data)
            return {'RUNNING_MODAL'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('SEARCH.'):
            self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_SEARCH.{control.key.removeprefix("SEARCH.")}', 'Delete saved search', False),))
            return {'RUNNING_MODAL'}
        if control is not None and press and event.type == 'RIGHTMOUSE' and control.key.startswith('ITEM.'):
            item = self.shelf_item(control.key)
            index = control.key.removeprefix('ITEM.')
            if item.user_index >= 0 and item.kind == 'MASK':
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_SMART_MASK.{item.user_index}', 'Delete smart mask', False),))
            elif item.kind == 'PACK':
                self.state.popover = Popover('MENU', control.rect, items=((f'REMOVE_PACK.{index}', 'Remove pack', False),))
            elif item.kind == 'PACKFILE':
                self.state.popover = Popover('MENU', control.rect, items=((f'PACK_FILE.{index}', 'Download this file', False),))
            elif item.kind == 'BRUSH' and item.user_index >= 0:
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_BRUSH.{item.user_index}', 'Delete brush preset', False),))
            elif item.kind == 'MATERIAL':
                items = ((f'PAINT_MATERIAL.{index}', 'Paint with this material', False),)
                if item.user_index >= 0:
                    items += ((f'DELETE_MATERIAL.{item.user_index}', 'Delete material', False),)
                self.state.popover = Popover('MENU', control.rect, items=items)
            elif item.user_index >= 0 and item.kind == 'SMART':
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_SMART.{item.user_index}', 'Delete smart material', False),))
            elif item.user_index >= 0:
                self.state.popover = Popover('MENU', control.rect, items=((f'DELETE_MATERIAL.{item.user_index}', 'Delete material', False),))
            elif item.kind == 'TEXTURE':
                obj, data = self.painted()
                layer = active_layer(data) if data is not None else None
                items = [(f'TEXTURE_FILL.{index}', 'New fill layer', False), (f'USE_ALPHA.{index}', 'Use as brush alpha', False),
                         (f'USE_STENCIL.{index}', 'Use as stencil', False)]
                if layer is not None and layer.kind == 'FILL':
                    items += [(f'ASSIGN_TEXTURE.{channel.key}.{index}', f'Use for {channel.label.lower()}', False) for channel in set_channels(data)]
                if item.managed:
                    items.append((f'REMOVE_TEXTURE.{index}', 'Remove from library', False))
                self.state.popover = Popover('MENU', control.rect, items=tuple(items))
            return {'RUNNING_MODAL'}
        if control is not None and event.type == 'LEFTMOUSE' and event.value in {'PRESS', 'DOUBLE_CLICK'}:
            self.modifiers = (event.ctrl, event.shift, event.alt)
            try:
                result = self.act(context, control, event.value == 'DOUBLE_CLICK')
            except (ValueError, RuntimeError) as failure:
                self.message = str(failure)
                result = None
            self._area.tag_redraw()
            if result is not None:
                return result
        elif control is None and press and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and not event.alt:
            name = next((key for key, rect in layout.zones.rects.items() if rect.contains(*self.pointer) and layout.covers(*self.pointer)), None)
            if name is not None and event.type == 'LEFTMOUSE':
                self.grab_section(name)
            elif name is not None:
                self.state.popover = Popover('MENU', Rect(self.pointer[0], self.pointer[1], 1, 1), items=(('RESET_LAYOUT', 'Reset layout', False),))
        return {'RUNNING_MODAL'}

    def grab_section(self, name):
        self.state.drag = ('GRAB_SECTION.' + name, self.workspace.zones.rects[name])
        self.drag_origin = self.pointer

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

    def projector_matrix(self, obj, layer):
        local = Matrix.Translation(layer.proj_offset) @ Euler(layer.proj_rotation).to_matrix().to_4x4() @ Matrix.Scale(layer.proj_size, 4)
        return obj.matrix_world @ local

    def gizmo_geometry(self, obj, data, view):
        layer = active_layer(data) if data is not None else None
        if layer is None or layer.kind != 'FILL' or layer.projection not in PROJECTORS or data.target != 'CONTENT' or not uses_coordinates(layer):
            return ()
        matrix = self.projector_matrix(obj, layer)
        rings = [[(math.cos(angle), math.sin(angle), height) for angle in (step * math.tau / CIRCLE_STEPS for step in range(CIRCLE_STEPS + 1))]
                 for height in ((0.0,) if layer.projection == 'SPHERICAL' else (-1.0, 1.0))]
        if layer.projection == 'SPHERICAL':
            rings += [[(math.cos(angle), 0.0, math.sin(angle)) for angle in (step * math.tau / CIRCLE_STEPS for step in range(CIRCLE_STEPS + 1))],
                      [(0.0, math.cos(angle), math.sin(angle)) for angle in (step * math.tau / CIRCLE_STEPS for step in range(CIRCLE_STEPS + 1))]]
        if layer.projection == 'PLANAR':
            rings = [[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (-1, -1, 0)], [(0, 0, 0), (0, 0, 1)]]
        if layer.projection == 'CYLINDRICAL':
            rings += [[(side, 0, -1), (side, 0, 1)] for side in (-1, 1)] + [[(0, side, -1), (0, side, 1)] for side in (-1, 1)]
        def screen(point):
            spot = view3d_utils.location_3d_to_region_2d(self._region, view, matrix @ Vector(point))
            return None if spot is None else (spot.x, spot.y)
        segments = []
        for ring in rings:
            spots = [screen(point) for point in ring]
            segments += [point for first, second in zip(spots, spots[1:]) if first and second for point in (first, second)]
        center, corner = screen((0, 0, 0)), screen((1, 0, 0))
        if center is None or corner is None:
            return ()
        pins = ()
        if layer.projection == 'PLANAR':
            spots = [screen(((cx + layer.proj_warp[index * 2]) * 2 - 1, (cy + layer.proj_warp[index * 2 + 1]) * 2 - 1, 0))
                     for index, (cx, cy) in enumerate(PIN_CORNERS)]
            pins = tuple(spot for spot in spots if spot is not None)
        return tuple(segments), center, corner, pins

    def drag_gizmo(self, context, key, release):
        obj, data = self.painted()
        layer = active_layer(data)
        view = self._area.spaces.active.region_3d
        matrix = self.projector_matrix(obj, layer)
        center = matrix @ Vector((0.0, 0.0, 0.0))
        point = view3d_utils.region_2d_to_location_3d(self._region, view, self.pointer, center)
        local = obj.matrix_world.inverted() @ point
        if key.startswith('GIZMO_PIN.'):
            index = int(key.removeprefix('GIZMO_PIN.'))
            inside = matrix.inverted() @ point
            warp = list(layer.proj_warp)
            warp[index * 2], warp[index * 2 + 1] = (inside.x + 1) / 2 - PIN_CORNERS[index][0], (inside.y + 1) / 2 - PIN_CORNERS[index][1]
            values = dict(proj_warp=tuple(warp))
        elif key == 'GIZMO_MOVE':
            values = dict(proj_offset=tuple(local))
        else:
            values = dict(proj_size=max(.01, (local - Vector(layer.proj_offset)).length))
        self.message = actions.set_projector(context, obj, data, values, release) or self.message

    def drop_point(self):
        if self.state.path_points:
            self.state.path_points.pop()
        return f'{len(self.state.path_points)} path points.'

    def apply_path(self, context):
        obj, data = self.painted()
        points = list(self.state.path_points)
        if len(points) < (3 if self.state.path_mode == 'FILLED' else 2):
            return 'Click more points on the model first.'
        self.state.path_points = []
        painting.update_canvas(context, data)
        if self.state.path_mode == 'RIBBON':
            self.run_gesture(context, [(point, 1.0) for point in dynamics.spline(points)], shaped=False)
            return 'Painted the ribbon along the path.'
        width, height = self._region.width, self._region.height
        pixels = numpy.zeros((height, width, 4), dtype=numpy.float32)
        color = linear_to_srgb(numpy.array(painting.brush_value(self.scene, 'color'), dtype=numpy.float32))
        pixels[vectors.fill([points], width, height)] = (*color, 1.0)
        return projection.project(context, self._window, self._area, self._region, obj, data, painting.uses_stroke_buffer(context, data),
                                  pixels, 'the filled path')

    def snap_projector(self, context, obj, data):
        layer = active_layer(data)
        center = view3d_utils.location_3d_to_region_2d(self._region, self._area.spaces.active.region_3d,
                                                       self.projector_matrix(obj, layer) @ Vector((0.0, 0.0, 0.0)))
        face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, tuple(center) if center else self.pointer)
        if face < 0:
            return 'Move the projector over the model first.'
        rotation = sets.surface_mesh(obj).polygons[face].normal.to_track_quat('Z', 'Y').to_euler()
        return actions.set_projector(context, obj, data, dict(proj_offset=tuple(location), proj_rotation=tuple(rotation)), True)

    def toggle_path_traced(self, context):
        shading = self._area.spaces.active.shading
        if shading.type == 'RENDERED':
            shading.type = 'MATERIAL'
            self.scene.render.engine = self.engine_before or self.scene.render.engine
            self.engine_before = ''
            return 'Back to the material preview.'
        self.engine_before = self.scene.render.engine
        self.scene.render.engine = 'CYCLES'
        self.scene.cycles.use_preview_denoising = True
        shading.type = 'RENDERED'
        return 'Path-traced preview with Cycles.'

    def brushing(self):
        obj, data = self.painted()
        return not (data is None or obj.mode != 'TEXTURE_PAINT' or self.state.poly_mode or self.state.path_mode or self.state.picking or self.state.geo_pick)

    def draws_lines(self):
        return self.brushing() and painting.active_tool(self.scene) in LINE_TOOLS

    def wants_gesture(self, context):
        if not self.brushing():
            return False
        obj, data = self.painted()
        tool = painting.active_tool(self.scene)
        if data.brush_radial > 1 and tool in painting.BUFFER_TOOLS - {'FILL'}:
            return True
        if brushes.per_dab(data, tool) and tool in painting.BUFFER_TOOLS - {'FILL'}:
            return True
        buffered = painting.uses_stroke_buffer(context, data)
        if tool == 'PAINT' and data.brush_dynamics != 'NONE':
            return True
        if obj.devil_painter.cross_tiles and len(tiles.numbers(data)) > 1 and tool in painting.BUFFER_TOOLS - {'FILL'}:
            return True
        return buffered and (tool in GESTURE_TOOLS or (tool == 'PAINT' and (brushes.textured(data) or ('flow' in data.brush_slots and data.brush_slots['flow'].enabled))))

    def start_gesture(self, context, event):
        obj, data = self.painted()
        if event.ctrl and painting.active_tool(self.scene) == 'CLONE':
            face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
            self.state.clone_source = None if face < 0 else (self.surface_point(obj, data, face, location)[0], location)
            return self.finish_message('Clone source set. Paint to copy from it.' if face >= 0 else 'Ctrl+click on the model to set the clone source.')
        self.prepare_stroke(context)
        self.state.gesture = [(self.pointer, max(event.pressure, .01))]
        return {'RUNNING_MODAL'}

    def shift_line(self, context, event):
        self.prepare_stroke(context)
        obj, data = self.painted()
        pressure = max(event.pressure, .01)
        start = self.anchor_point(obj)
        points = [(self.pointer, pressure)] if start is None else self.segment(data, start, self.pointer, pressure)
        return self.finish_message(self.run_gesture(context, points, shaped=False))

    def segment(self, data, start, end, pressure):
        step = brushes.spacing_step(data, painting.brush_value(self.scene, 'size'))
        count = int(math.dist(start, end) / step) + 1
        return [((start[0] + (end[0] - start[0]) * index / count, start[1] + (end[1] - start[1]) * index / count), pressure) for index in range(1, count + 1)]

    def anchor_key(self, obj):
        return obj.name, obj.devil_painter.active_set, painting.active_tool(self.scene)

    def remember_anchor(self, pointer):
        obj = self.painted()[0]
        face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, pointer)
        self.line_anchor = (self.anchor_key(obj), location) if face >= 0 else None

    def drop_stale_anchor(self):
        obj, data = self.painted()
        if self.line_anchor is not None and (data is None or self.line_anchor[0] != self.anchor_key(obj)):
            self.line_anchor = None

    def anchor_point(self, obj):
        self.drop_stale_anchor()
        if self.line_anchor is None:
            return None
        spot = view3d_utils.location_3d_to_region_2d(self._region, self._area.spaces.active.region_3d, obj.matrix_world @ self.line_anchor[1])
        return None if spot is None else (spot.x, spot.y)

    def native_stroke(self, context, event):
        self.begin_stroke(context, event)
        if not self.brushing():
            return
        self.remember_anchor(self.pointer)
        if self.painted()[1].brush_stroke != 'ANCHORED':
            bpy.app.timers.register(self.watch_stroke, first_interval=0.0)

    def watch_stroke(self):
        if not self._closed and any(operator.bl_idname.startswith('PAINT_OT') for operator in self._window.modal_operators):
            with bpy.context.temp_override(window=self._window, area=self._area, region=self._region):
                bpy.ops.devil_painter.stroke_end('INVOKE_DEFAULT')

    def finish_message(self, message):
        self.message = message
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def gesture_event(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.state.gesture.append((self.pointer, max(event.pressure, .01)))
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.state.gesture.append((self.pointer, max(event.pressure, .01)))
            points, self.state.gesture = self.state.gesture, None
            return self.finish_message(self.run_gesture(context, points))
        return {'RUNNING_MODAL'}

    def track_world_size(self):
        obj, data = self.painted()
        if data is None or not brushes.world_sized(data) or obj.mode != 'TEXTURE_PAINT':
            return
        source = painting.brush_source(self.scene, 'size')
        owner, written = self.world_pixels
        if owner == source.as_pointer() and written and source.size != written:
            data.brush_world_size = data.brush_world_size * source.size / written
        radius = brushes.world_radius(self._region, self._area.spaces.active.region_3d, obj, self.pointer, data.brush_world_size)
        if radius is not None:
            source.size = max(1, round(2 * radius))
        self.world_pixels = (source.as_pointer(), source.size)

    def follow_view(self):
        key = tuple(tuple(row) for row in self._area.spaces.active.region_3d.perspective_matrix)
        if key != self.view_key:
            self.view_key = key
            self.track_world_size()
            self._area.tag_redraw()

    def texture_point(self, obj, data, pointer):
        face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, pointer)
        return None if face < 0 else self.surface_point(obj, data, face, location)

    def surface_point(self, obj, data, face, location):
        mesh = sets.surface_mesh(obj)
        uv = sets.uv_at(mesh, obj.devil_painter.uv_map, sets.triangle_at(mesh, face, location), location)
        tile = FIRST_TILE + int(uv.x // 1) + 10 * int(uv.y // 1)
        return tile, uv.x % 1 * data.resolution, uv.y % 1 * data.resolution

    def symmetric_paths(self, obj, data, points, tile):
        turns = [Matrix.Rotation(-math.tau * turn / data.brush_radial, 3, data.brush_radial_axis) for turn in range(data.brush_radial)]
        flips = [Vector(signs) for signs in itertools.product(*(((1.0, -1.0) if mirrored else (1.0,)) for mirrored in data.brush_mirror))]
        hits = [sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, point) for point, _ in points]
        copies = []
        for turn, flip in [(turn, flip) for turn in turns for flip in flips][1:]:
            path = []
            for face, location in hits:
                if face < 0:
                    continue
                found, spot, _, near = obj.closest_point_on_mesh((turn @ location) * flip)
                texel = self.surface_point(obj, data, near, spot) if found else None
                if texel is not None and texel[0] == tile:
                    path.append(texel[1:])
            copies.append(path)
        return tuple(copies)

    def gesture_path(self, data, points):
        if data.brush_stroke == 'LINE' and len(points) > 1:
            (start, pressure), (end, _) = points[0], points[-1]
            count = max(2, int(math.dist(start, end) / 3))
            points = [((start[0] + (end[0] - start[0]) * index / (count - 1), start[1] + (end[1] - start[1]) * index / (count - 1)), pressure)
                      for index in range(count)]
        if data.brush_smoothing > 0:
            factor, smoothed, current = 1 - .9 * data.brush_smoothing, [], points[0][0]
            for point, pressure in points:
                current = (current[0] + (point[0] - current[0]) * factor, current[1] + (point[1] - current[1]) * factor)
                smoothed.append((current, pressure))
            points = smoothed
        return points

    def replay(self, context, obj, data, points):
        if not points:
            return
        points, radii = brushes.spaced_stroke(context, data, self._region, self._area.spaces.active.region_3d, obj, painting.brush_value(self.scene, 'size'), points)
        elements = [dict(name='', location=(0.0, 0.0, 0.0), mouse=point, mouse_event=point, is_start=index == 0, pressure=pressure, size=radius,
                         time=index * .01, x_tilt=0.0, y_tilt=0.0) for index, ((point, pressure), radius) in enumerate(zip(points, radii))]
        tool = painting.active_tool(self.scene)
        mapped = brushes.per_dab(data, tool)
        if brushes.per_point(data, tool):
            jitter = brushes.dab_jitter(data, len(points), brushes.jitter_seed(points)) if brushes.jittered(data, tool) else [(1.0, 1.0, 0.0)] * len(points)
            headings = brushes.path_angles(points) if data.brush_follow_path else [0.0] * len(points)
            for element, (size_scale, _, _) in zip(elements, jitter):
                element['size'] *= size_scale
                element['is_start'] = True
            dabs = [([element], flow_scale, heading + angle_offset) for element, (_, flow_scale, angle_offset), heading in zip(elements, jitter, headings)]
        elif mapped:
            dabs = []
            for _, group in itertools.groupby(elements, key=lambda element: element['pressure']):
                batch = list(group)
                batch[0]['is_start'] = True
                dabs.append((batch, 1.0, 0.0))
        else:
            dabs = [(elements, 1.0, 0.0)]
        original = obj.matrix_world.copy()
        axis = data.brush_radial_axis
        try:
            for turn in range(data.brush_radial):
                obj.matrix_world = original @ Matrix.Rotation(math.tau * turn / data.brush_radial, 4, axis)
                context.view_layer.update()
                for dab, flow_scale, angle_offset in dabs:
                    if mapped:
                        brushes.sync_pressure(context, data, dab[0]['pressure'], flow_scale, angle_offset)
                    with context.temp_override(window=self._window, area=self._area, region=self._region):
                        bpy.ops.paint.image_paint('EXEC_DEFAULT', False, stroke=dab, mode='NORMAL')
        finally:
            if mapped:
                brushes.sync_pressure(context, data, 1.0)
            obj.matrix_world = original
            context.view_layer.update()

    def run_gesture(self, context, points, shaped=True):
        obj, data = self.painted()
        if shaped:
            points = self.gesture_path(data, points)
        buffered = painting.uses_stroke_buffer(context, data)
        size = brushes.stroke_size(data, self._region, self._area.spaces.active.region_3d, obj, points, painting.brush_value(self.scene, 'size'))
        trails = [points]
        if data.brush_dynamics != 'NONE' and painting.active_tool(self.scene) == 'PAINT':
            trails = dynamics.trails(data.brush_dynamics, self._region, self._area.spaces.active.region_3d, obj, points, size)
        spots = [self.texture_point(obj, data, point) for point, _ in points]
        project = obj.devil_painter
        crossing = project.cross_tiles and len(tiles.numbers(data)) > 1
        touched = list(dict.fromkeys(spot[0] for spot in spots if spot and spot[0] in tiles.numbers(data))) if crossing else []
        home = project.active_tile
        before, after, notes = [], [], []
        try:
            for tile in touched or [home]:
                if crossing:
                    project.active_tile = tile
                    sets.mask_faces(obj, project)
                    painting.update_canvas(context, data)
                direct = None if buffered else variant(data, paint_target(data), tile)
                snapshot = strokes.read(direct).copy() if direct is not None else None
                for trail in trails:
                    self.replay(context, obj, data, trail)
                if buffered:
                    entry, note = self.merge_pass(obj, data, points, spots, size)
                    notes.append(note)
                    if entry is not None:
                        before += entry.before
                        after += entry.after
                elif direct is not None:
                    entry = strokes.diff(direct, snapshot)
                    if entry is not None:
                        before += entry.before
                        after += entry.after
        finally:
            if crossing and project.active_tile != home:
                project.active_tile = home
                sets.mask_faces(obj, project)
                painting.update_canvas(context, data)
        if before:
            history.push(self.stroke_label(data), strokes.Fill(before, after))
        self.remember_anchor(points[-1][0])
        message = next((note for note in notes if note), '')
        if len(touched) > 1 and not message:
            message = f'The stroke crossed UV tiles {", ".join(str(tile) for tile in touched)}.'
        return message

    def merge_pass(self, obj, data, points, spots, size):
        tile = active_tile(data)
        path = [(spot[1], spot[2]) for spot in spots if spot and spot[0] == tile]
        first, edge = spots[0], self.texture_point(obj, data, (points[0][0][0] + size / 2, points[0][0][1]))
        radius = math.dist(first[1:], edge[1:]) if first and edge and first[0] == edge[0] else size / 2
        source = self.state.clone_source[1] if self.state.clone_source and self.state.clone_source[0] == tile else None
        cloning = painting.active_tool(self.scene) == 'CLONE'
        if cloning and source is None:
            strokes.merge(obj, data, None)
            return None, 'Ctrl+click on the model to set the clone source first.'
        if cloning:
            source = self.clone_offset(obj, data, points, tile, source)
        copies = self.symmetric_paths(obj, data, points, tile) if brushes.textured(data) else ()
        return strokes.merge(obj, data, strokes.Gesture(path, radius, source, copies)), ''

    def clone_offset(self, obj, data, points, tile, source):
        view = self._area.spaces.active.region_3d
        hits = (sets.hit_under(self._region, view, obj, point) for point, _ in points)
        start = next((location for face, location in hits if face >= 0 and self.surface_point(obj, data, face, location)[0] == tile), None)
        return None if start is None else source - start

    def stroke_label(self, data):
        tool = painting.active_tool(self.scene)
        verb = next((label for key, label, _, _ in painting.TOOLS if key == tool), 'Paint')
        if data.quick_mask is not None:
            return 'Quick mask stroke'
        if data.bake_paint:
            return f'{data.bake_paint.title()} map stroke'
        effect = active_effect(data)
        if effect is not None and effect.kind == 'PAINT':
            return 'Paint effect stroke'
        if editing_mask(data):
            return 'Mask stroke'
        return f'{verb} stroke'

    def flat_target(self, event):
        if event is None or self.flat_space() is None:
            return None
        flat_region = next((item for item in self.flat_area.regions if item.type == 'WINDOW'), None)
        if flat_region is None:
            return None
        if not (flat_region.x <= event.mouse_x < flat_region.x + flat_region.width and flat_region.y <= event.mouse_y < flat_region.y + flat_region.height):
            return None
        return self.flat_space().image

    def prepare_stroke(self, context):
        obj, data = self.painted()
        if data is None or obj.mode != 'TEXTURE_PAINT':
            return obj, None, False
        inside = 0 <= self.pointer[0] < self._region.width and 0 <= self.pointer[1] < self._region.height
        if inside:
            face = sets.face_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
            if face >= 0:
                message = actions.activate(context, obj, obj.devil_painter, *sets.locate(obj, obj.devil_painter, face))
                if message:
                    self.message = message
                    data = texture_set(obj)
        if inside and data.material is None:
            compositing.sync(data)
        return obj, data, inside

    def begin_stroke(self, context, event=None):
        _, data, inside = self.prepare_stroke(context)
        if data is None:
            return
        if inside and painting.uses_stroke_buffer(context, data):
            self.stroke_pending = True
            self.direct_stroke = None
            self.stroke_label_pending = self.stroke_label(data)
            return
        target = variant(data, paint_target(data), active_tile(data)) if inside else self.flat_target(event)
        if target is not None:
            self.stroke_pending = True
            self.direct_stroke = (target.name, strokes.read(target).copy(), self.stroke_label(data))

    def finish_stroke(self, context):
        if any(operator.bl_idname.startswith('PAINT_OT') for operator in self._window.modal_operators):
            return
        self.stroke_pending = False
        direct, self.direct_stroke = self.direct_stroke, None
        label, self.stroke_label_pending = self.stroke_label_pending, ''
        obj, data = self.painted()
        if direct is not None:
            name, before, direct_label = direct
            image = bpy.data.images.get(name)
            entry = strokes.diff(image, before)
            if entry is not None:
                history.attach(direct_label, entry)
                caches.touch(image)
                self._area.tag_redraw()
            return
        entry = strokes.merge(obj, data) if data is not None else None
        if entry is not None:
            history.attach(label or 'Paint stroke', entry, buffered=True)
            self._area.tag_redraw()

    def after_history(self, context):
        obj, data = self.painted()
        if data is not None:
            if len(obj.devil_painter.sets) > 1 or len(tiles.numbers(data)) > 1:
                sets.mask_faces(obj, obj.devil_painter)
            painting.update_canvas(context, data)
        self._area.tag_redraw()

    def history_step(self, context, redo):
        if self.stroke_pending:
            self.finish_stroke(context)
        self.state.popover = None
        if history.step(redo):
            self.after_history(context)
            return 'Redid.' if redo else 'Undid.'
        return 'Nothing to redo.' if redo else 'Nothing to undo.'

    def history_jump(self, context, target):
        if self.stroke_pending:
            self.finish_stroke(context)
        self.state.popover = None
        if history.jump(target):
            self.after_history(context)
            current = history.cursor()
            label = 'Initial state' if current == 0 else history.entries()[current - 1].label
            return f'History: {label}.'
        return ''

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

    def fill_polygons(self, context):
        obj, data = self.painted()
        face, location = sets.hit_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
        if face < 0:
            return 'Click on the model to fill polygons.'
        color = strokes.rgb(tuple(painting.brush_value(self.scene, 'color')))
        face = sets.original_face(obj, face)
        if face < 0:
            return 'Click on the model to fill polygons.'
        return polyfill.polygon_fill(obj, data, self.state.poly_mode, face, location, color, self.state.poly_erase)

    def pick_geometry(self, context):
        obj, data = self.painted()
        face = sets.face_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
        face = sets.original_face(obj, face) if face >= 0 else -1
        if face < 0:
            return 'Click on the model to pick faces.'
        return actions.pick_geometry(context, obj, data, face, self.state.geo_pick == 'ISLAND')

    def load_column(self):
        saved = library.settings().get('workspace', {})
        try:
            strips = {side: [dict(size=float(strip['size']), items=[key for key in strip['items'] if key in SECTIONS]) for strip in saved.get('strips', {}).get(side, ())]
                      for side in SIDES}
            placed = [key for side in SIDES for strip in strips[side] for key in strip['items']]
            if sorted(placed) == sorted(SECTIONS) and not any(key in ROWS_ONLY for side in COLUMNS for strip in strips[side] for key in strip['items']):
                self.state.strips = {side: [strip for strip in strips[side] if strip['items']] for side in SIDES}
            self.state.section_heights.update({key: clamp_length(key, float(value)) for key, value in saved.get('heights', {}).items() if key in SECTIONS})
            self.state.section_widths.update({key: clamp_length(key, float(value)) for key, value in saved.get('widths', {}).items() if key in SECTIONS})
            self.state.collapsed |= {key for key in saved.get('collapsed', ()) if key in PANELS}
        except (TypeError, ValueError, AttributeError, KeyError):
            return

    def save_column(self):
        library.settings()['workspace'] = dict(strips=self.state.strips, heights=dict(self.state.section_heights), widths=dict(self.state.section_widths),
                                               collapsed=sorted(key for key in self.state.collapsed if key in PANELS))
        library.save_settings()

    def reset_layout(self):
        self.state.strips, self.state.section_heights, self.state.section_widths = default_strips(), dict(HEIGHTS), dict(WIDTHS)
        self.state.collapsed -= set(PANELS)
        self.save_column()
        return 'The workspace layout is back to its default.'

    def track_section(self, name, release, toggle):
        moved = math.dist(self.pointer, self.drag_origin) > DRAG_START * self.workspace.scale
        strips = place(self.state.strips, name, *self.pointer, self.workspace.zones) if moved else None
        self.state.drop = ('SECTION', name, strips) if strips is not None and not release else ()
        if not release:
            return
        if strips is not None:
            self.state.strips = strips
        elif toggle:
            self.state.collapsed ^= {name}
        else:
            return
        self.save_column()

    def resize_section(self, name):
        found, s = self.workspace.zones, self.workspace.scale
        rect, (side, index) = found.rects[name], found.places[name]
        items = [key for key in self.state.strips[side][index]['items'] if key in found.rects]
        if side in COLUMNS:
            keys = [key for key in items if flexible(key, self.state.collapsed, self.state.shelf_open) and key not in found.tails]
            if name in keys:
                want = (rect.top - self.pointer[1]) / s - (HEADER if name in PANELS else 0)
                self.state.section_heights = resize_run(keys, self.state.section_heights, name, want, found.rooms[(side, index)] - 48)
        else:
            keys = items[:-1]
            if name in keys:
                self.state.section_widths = resize_run(keys, self.state.section_widths, name, (self.pointer[0] - rect.x) / s, found.rooms[(side, index)] - 48)

    def resize_strip(self, side, index):
        rect = next(rect for where, number, rect in self.workspace.zones.strips if where == side and number == index)
        x, y = self.pointer
        size = dict(LEFT=x - rect.x, RIGHT=rect.x + rect.w - x, TOP=rect.top - y, BOTTOM=y - rect.y)[side] / self.workspace.scale
        strip = self.state.strips[side][index]
        strip['size'] = clamp_strip(side, size, strip['items'])

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
        ctrl, shift, _ = self.modifiers
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
            items = tuple((f'SET_FXBLEND.{mode}', label, mode == effect.blend) for mode, label, _ in MASK_BLENDS)
        elif key == 'FX_FILTER':
            offered = [item for item in FILTERS if effect.target == 'CONTENT' or not item.color_only]
            items = tuple(entry for group in GROUPS for entry in ((MENU_HEADING + group, group, False),) + tuple(
                (f'SET_FXFILTER.{item.key}', item.label, item.key == effect.filter) for item in offered if item.group == group))
        elif key == 'FX_SOURCE':
            items = (('SET_FXSOURCE.VALUE', 'Plain value', effect.source == 'VALUE'),
                     ('FX_PICK_TEXTURE', 'Texture from the shelf', effect.source == 'IMAGE')) + tuple(
                (f'SET_FXPATTERN.{item.key}', 'Pattern · ' + item.label, effect.source == 'PATTERN' and effect.pattern == item.key) for item in PATTERNS)
        elif key == 'FX_COMPONENT':
            items = tuple((f'SET_FXCOMPONENT.{mode}', label, mode == effect.levels_component) for mode, label in LEVEL_COMPONENTS)
        elif key == 'FX_PROJECTION':
            items = tuple((f'SET_FXPROJECTION.{mode}', label, mode == effect.projection) for mode, label in FILL_PROJECTIONS)
        elif key in {'FX_WRAP', 'FX_FILTERING'}:
            field = key.removeprefix('FX_').lower()
            items = tuple((f'SET_FX{field.upper()}.{mode}', label, mode == getattr(effect, field)) for mode, label, _ in TEXTURE_SAMPLING[field])
        elif key == 'FX_OTHER':
            items = tuple((f'SET_FXOTHER.{layer.uid}', layer.name, layer.uid == effect.other) for layer in data.layers
                          if layer.uid != data.active_uid and layer.kind != 'INSTANCE') or (('NO_LAYER', 'No other layer', False),)
        elif key == 'FX_ANCHOR':
            items = (('SET_FXANCHOR.', 'None', not effect.anchor),) + tuple(
                (f'SET_FXANCHOR.{layer.uid}', layer.name, layer.uid == effect.anchor) for layer in data.layers
                if layer.uid != data.active_uid and layer.kind != 'INSTANCE')
        elif key == 'FX_ANCHOR_CHANNEL':
            items = tuple((f'SET_FXANCHORCHANNEL.{channel.key}', channel.label, channel.key == effect.anchor_channel) for channel in set_channels(data))
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
        elif key == 'FX_CLAMP':
            self.message = actions.edit_effect(context, obj, data, 'clamp', not effect.clamp, True)
        elif key in {'FX_UP', 'FX_DOWN'}:
            layer = active_layer(data)
            index = next(position for position, item in enumerate(layer.effects) if item.uid == effect.uid)
            self.message = actions.move_effect(context, obj, data, layer.uid, effect.uid, index + (1 if key == 'FX_UP' else -1))
        elif key == 'FX_DELETE':
            self.message = actions.delete_effect(context, obj, data)
        elif key in {'FX_BLEND', 'FX_FILTER', 'FX_SOURCE', 'FX_OTHER', 'FX_CHANNEL', 'FX_COMPONENT', 'FX_PROJECTION', 'FX_WRAP', 'FX_FILTERING', 'FX_ANCHOR', 'FX_ANCHOR_CHANNEL'}:
            self.open_effect_menu(key, control, data)
        elif key.startswith('SET_FXPATTERN.'):
            actions.edit_effect(context, obj, data, 'source', 'PATTERN', False)
            self.message = actions.edit_effect(context, obj, data, 'pattern', key.removeprefix('SET_FXPATTERN.'), True)
        elif key == 'FX_PICK_TEXTURE':
            self.state.armed = EFFECT_TARGET
            self.state.shelf_open, self.state.shelf_tab = True, 'TEXTURES'
            self.message = 'Click a texture in the shelf to fill the effect with it.'
        elif key == 'FX_PICK_ID':
            self.state.picking = 'id:' + data.active_effect
            self.message = 'Click the model to pick an ID color.'
        elif key == 'FX_ADD_ID':
            self.state.picking = 'idadd:' + data.active_effect
            self.message = 'Click the model to add another ID color.'
        elif key.startswith('FX_REMOVE_ID.'):
            self.message = actions.remove_id_color(context, obj, data, int(key.removeprefix('FX_REMOVE_ID.')))
        elif key.startswith('FXCOLOR.'):
            self.open_color(control, 'fx:' + key.removeprefix('FXCOLOR.'))
        elif key.startswith(('SET_FXBLEND.', 'SET_FXFILTER.', 'SET_FXSOURCE.', 'SET_FXOTHER.', 'SET_FXCHANNEL.', 'SET_FXCOMPONENT.', 'SET_FXPROJECTION.',
                             'SET_FXWRAP.', 'SET_FXFILTERING.', 'SET_FXANCHOR.', 'SET_FXANCHORCHANNEL.')):
            prefix, value = key.split('.', 1)
            field = {'SET_FXBLEND': 'blend', 'SET_FXFILTER': 'filter', 'SET_FXSOURCE': 'source', 'SET_FXOTHER': 'other', 'SET_FXCHANNEL': 'channel',
                     'SET_FXCOMPONENT': 'levels_component', 'SET_FXPROJECTION': 'projection', 'SET_FXWRAP': 'wrap', 'SET_FXFILTERING': 'filtering', 'SET_FXANCHOR': 'anchor',
                     'SET_FXANCHORCHANNEL': 'anchor_channel'}[prefix]
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
        elif key.startswith('SET_FOLDERCH.'):
            _, channel, mode = key.split('.')
            self.message = actions.set_channel_blend(context, obj, data, channel, mode)
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
        items = [('RENAME', 'Rename', False), ('DUPLICATE', 'Duplicate', False), ('COPY_LAYERS', 'Copy', False), ('ADD_FOLDER', 'New folder above', False),
                 ('ISOLATE', 'Show all layers' if data.isolate == layer.uid else 'Show only this layer', False)]
        if self.state.clipboard:
            items += [('PASTE_LAYERS', 'Paste layers', False), ('PASTE_MASK', 'Paste mask', False), ('PASTE_EFFECTS', 'Paste effects', False)]
        if layer.kind == 'INSTANCE':
            items += [('MOVE_UP', 'Move up', False), ('MOVE_DOWN', 'Move down', False), ('DELETE', 'Delete', False)]
            self.state.popover = Popover('MENU', anchor, items=tuple(items))
            return
        if layer.kind == 'FOLDER':
            items.append(('FLATTEN', 'Flatten folder', False))
        items.append(('EXPORT_LAYER', 'Export flattened', False))
        if layer.mask is not None or layer.geo_mask or len(layer.effects):
            items.append(('EXPORT_MASK', 'Export mask', False))
        if layer.mask is not None or any(effect.target == 'MASK' for effect in layer.effects):
            items.append(('SAVE_SMART_MASK', 'Save mask as smart mask', False))
        items += [(f'INSTANCE_INTO.{index}', 'Instance into ' + item.name, False) for index, item in enumerate(project.sets)]
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

    def begin_number(self, key):
        spec = self.number_spec(key)
        if spec is None:
            return
        text = spec[0]
        self.state.text = TextEdit(key, text, len(text), numeric=True, selected=True)

    def next_slider(self, current_key, backwards):
        layout = self.workspace
        scope = layout.controls[layout.popover_start:] if layout.popover_start >= 0 else layout.controls
        sliders = [control.key for control in scope if control.kind == 'SLIDER'
                   and (control.clip is None or control.clip.contains(control.rect.x + control.rect.w / 2, control.rect.y + control.rect.h / 2))]
        if current_key not in sliders or len(sliders) < 2:
            return None
        return sliders[(sliders.index(current_key) + (-1 if backwards else 1)) % len(sliders)]

    def number_spec(self, key):
        obj, data = self.painted()
        if key == 'BRUSH_SIZE':
            if data is not None and brushes.world_sized(data):
                return (brushes.world_size_text(data.brush_world_size), lambda text: parse_world_size(self.scene, text),
                        lambda context, value: setattr(data, 'brush_world_size', value))
            current = painting.brush_value(self.scene, 'size')
            return (format_number(current, integer=True), lambda text: parse_number(text, 1, MAX_BRUSH_SIZE, integer=True, units=('px',)),
                    lambda context, value: painting.set_brush_value(self.scene, 'size', value))
        if key == 'BRUSH_STRENGTH' and data is not None:
            def write_strength(context, value):
                data.brush_opacity = value
                self.brush_changed(context, data)
            return format_number(data.brush_opacity * 100, decimals=2), lambda text: parse_number(text, 0.0, 1.0, scale=100.0, units=('%',)), write_strength
        if key in BRUSH_RANGES and data is not None:
            field, top, floor = BRUSH_RANGES[key]
            scale = 1.0 if key in {'BRUSH_SPACING', 'BRUSH_ANGLE'} else 100.0
            units = ('°', 'deg') if key == 'BRUSH_ANGLE' else ('%',)
            def write_brush(context, value):
                setattr(data, field, value)
                self.brush_changed(context, data)
            return format_number(getattr(data, field) * scale, decimals=2), lambda text: parse_number(text, floor, top, scale=scale, units=units), write_brush
        if key in GENERATOR_RANGES and data is not None:
            effect = active_effect(data)
            if effect is None:
                return None
            field, top = GENERATOR_RANGES[key]
            floor = .5 if key == 'GEN_SCALE' else 0.0
            def write_gen(context, value):
                actions.set_generator_value(context, obj, data, field, value)
                self.message = actions.commit_value(context, obj, data, 'Generator')
            return format_number(getattr(effect, field)), lambda text: parse_number(text, floor, top), write_gen
        if key in SHADER_RANGES and data is not None:
            field, top = SHADER_RANGES[key]
            return format_number(getattr(data, field)), lambda text: parse_number(text, 0.0, top), lambda context, value: setattr(self, 'message', actions.set_set_value(context, obj, data, field, value, True))
        if key == 'DISP_SCALE' and data is not None:
            def write_disp_scale(context, value):
                message = actions.set_set_value(context, obj, data, 'displacement_scale', value, True)
                if message:
                    self.message = message
            return format_number(data.displacement_scale), lambda text: parse_number(text, 0.0, DISPLACEMENT_SCALE_MAX, units=('m',)), write_disp_scale
        if key == 'DISP_SUBDIV' and data is not None:
            def write_disp_subdiv(context, value):
                message = actions.set_set_value(context, obj, data, 'displacement_subdivision', value, True)
                if message:
                    self.message = message
            return format_number(data.displacement_subdivision, integer=True), lambda text: parse_number(text, 0, DISPLACEMENT_SUBDIVISION_MAX, integer=True), write_disp_subdiv
        if key == 'PHYS_SIZE' and data is not None:
            return format_number(obj.devil_painter.physical_size), lambda text: parse_number(text, .01, 10.0, units=('m',)), lambda context, value: setattr(self, 'message', actions.set_project_value(context, obj, obj.devil_painter, 'physical_size', value))
        if key == 'ENV_ROTATION':
            space = self._area.spaces.active
            return format_number(math.degrees(space.shading.studiolight_rotate_z), decimals=2), lambda text: parse_number(text, -180.0, 180.0, units=('°', 'deg')), lambda context, value: setattr(space.shading, 'studiolight_rotate_z', math.radians(value))
        if key == 'ENV_STRENGTH':
            space = self._area.spaces.active
            return format_number(space.shading.studiolight_intensity), lambda text: parse_number(text, 0.0, 2.0), lambda context, value: setattr(space.shading, 'studiolight_intensity', value)
        if key == 'CAMERA_FOV':
            space = self._area.spaces.active
            return format_number(space.lens, decimals=2), lambda text: parse_number(text, FOV_RANGE[0], FOV_RANGE[1], units=('mm',)), lambda context, value: setattr(space, 'lens', value)
        if key == 'PROJ_BEND' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            return format_number(layer.proj_bend), lambda text: parse_number(text, 0.0, 1.0), lambda context, value: setattr(self, 'message', actions.set_projector(context, obj, data, dict(proj_bend=value), True) or self.message)
        if key == 'PROJ_SIZE' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            return format_number(layer.proj_size), lambda text: parse_number(text, .01, 1000.0), lambda context, value: setattr(self, 'message', actions.set_projector(context, obj, data, dict(proj_size=value), True) or self.message)
        if key == 'PROJ_SPIN' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            def write_proj_spin(context, value):
                rotation = active_layer(data).proj_rotation
                self.message = actions.set_projector(context, obj, data, dict(proj_rotation=(rotation[0], rotation[1], math.radians(value))), True) or self.message
            return format_number(math.degrees(layer.proj_rotation[2]) % 360, decimals=2), lambda text: parse_number(text, 0.0, 360.0, units=('°', 'deg')), write_proj_spin
        if key in {'UV_OFFSET_X', 'UV_OFFSET_Y'} and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            axis = 'XY'.index(key[-1])
            def write_uv_offset(context, value):
                offset = list(active_layer(data).uv_offset)
                offset[axis] = value
                self.message = actions.set_uv_projection(context, obj, data, dict(uv_offset=tuple(offset)), True) or self.message
            return format_number(layer.uv_offset[axis] % 1.0), lambda text: parse_number(text, 0.0, 1.0), write_uv_offset
        if key == 'UV_SPIN' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            return (format_number(math.degrees(layer.uv_rotation) % 360, decimals=2), lambda text: parse_number(text, 0.0, 360.0, units=('°', 'deg')),
                    lambda context, value: setattr(self, 'message', actions.set_uv_projection(context, obj, data, dict(uv_rotation=math.radians(value)), True) or self.message))
        if key == 'TRIPLANAR_HARDNESS' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            return format_number(1.0 - layer.triplanar_blend), lambda text: parse_number(text, 0.0, 1.0), lambda context, value: setattr(self, 'message', actions.set_projector(context, obj, data, dict(triplanar_blend=1.0 - value), True) or self.message)
        if key == 'FX_TRIPLANAR_HARDNESS' and data is not None:
            effect = active_effect(data)
            if effect is None:
                return None
            return format_number(1.0 - effect.triplanar_blend), lambda text: parse_number(text, 0.0, 1.0), lambda context, value: setattr(self, 'message', actions.edit_effect(context, obj, data, 'triplanar_blend', 1.0 - value, True))
        if key == 'RADIAL' and data is not None:
            return format_number(data.brush_radial, integer=True), lambda text: parse_number(text, 1, 16, integer=True), lambda context, value: setattr(data, 'brush_radial', value)
        if key in DRAG_FIELDS and data is not None:
            field, top = DRAG_FIELDS[key]
            floor = .05 if key == 'STENCIL_SCALE' else 0.0
            units = ('°', 'deg') if key in NORMAL_KEYS or key == 'STENCIL_ANGLE' else ()
            def write_drag_field(context, value):
                setattr(data, field, value)
                if key in NORMAL_KEYS:
                    brushes.normal_color(data)
                    compositing.update_values(data)
                self.brush_changed(context, data)
            return format_number(getattr(data, field), decimals=2 if units else 3), lambda text: parse_number(text, floor, top, units=units), write_drag_field
        if key == 'BAKE_SAMPLES' and data is not None:
            return format_number(data.bake_samples, integer=True), lambda text: parse_number(text, 1, 128, integer=True), lambda context, value: setattr(data, 'bake_samples', value)
        if key == 'BAKE_EXTRUSION' and data is not None:
            return format_number(data.bake_extrusion * 100, decimals=2), lambda text: parse_number(text, .005, .5, scale=100.0, units=('%',)), lambda context, value: setattr(data, 'bake_extrusion', value)
        if key == 'BAKE_MAP_SAMPLES' and data is not None:
            selected = self.state.bake_map
            return format_number(map_samples(data, selected), integer=True), lambda text: parse_number(text, 1, 128, integer=True), lambda context, value: setattr(bake_map_settings(data, selected), 'samples', value)
        if key == 'BAKE_MAP_EXTRUSION' and data is not None:
            selected = self.state.bake_map
            return format_number(map_extrusion(data, selected) * 100, decimals=2), lambda text: parse_number(text, .005, .5, scale=100.0, units=('%',)), lambda context, value: setattr(bake_map_settings(data, selected), 'extrusion', value)
        if key == 'BAKE_AO_DISTANCE' and data is not None:
            return format_number(data.bake_ao_distance * 100, decimals=2), lambda text: parse_number(text, .01, 2.0, scale=100.0, units=('%',)), lambda context, value: setattr(data, 'bake_ao_distance', value)
        if key == 'BAKE_AO_SPREAD' and data is not None:
            return format_number(data.bake_ao_spread, decimals=2), lambda text: parse_number(text, 15.0, 180.0, units=('°', 'deg')), lambda context, value: setattr(data, 'bake_ao_spread', value)
        if key == 'BAKE_THICKNESS_RANGE' and data is not None:
            return format_number(data.bake_thickness_range * 100, decimals=2), lambda text: parse_number(text, .01, 2.0, scale=100.0, units=('%',)), lambda context, value: setattr(data, 'bake_thickness_range', value)
        if key.startswith('BRUSHVAL.') and data is not None:
            channel = key.removeprefix('BRUSHVAL.')
            def write_brush_val(context, value):
                data.brush_slots[channel].value = value
                self.brush_changed(context, data)
            return format_number(data.brush_slots[channel].value), lambda text: parse_number(text, 0.0, 1.0), write_brush_val
        if key == 'OPACITY' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            def write_opacity(context, value):
                actions.set_opacity(context, obj, data, value)
                self.message = actions.commit_value(context, obj, data, 'Opacity')
            return format_number(layer.opacity * 100, decimals=2), lambda text: parse_number(text, 0.0, 1.0, scale=100.0, units=('%',)), write_opacity
        if key.startswith(('VALUE.', 'VALUEB.')) and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            kind, channel = key.split('.')
            second = kind == 'VALUEB'
            current = layer.slots[channel].value_b if second else layer.slots[channel].value
            def write_channel_val(context, value):
                actions.set_channel_value(context, obj, data, channel, (value,), second=second)
                self.message = actions.commit_value(context, obj, data, CHANNEL[channel].label)
            return format_number(current), lambda text: parse_number(text, 0.0, 1.0), write_channel_val
        if key.startswith('CHOPACITY.') and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            channel = key.removeprefix('CHOPACITY.')
            def write_ch_opacity(context, value):
                actions.set_slot_field(context, obj, data, channel, 'opacity', value)
                self.message = actions.commit_value(context, obj, data, f'{CHANNEL[channel].label} opacity')
            return format_number(layer.slots[channel].opacity * 100, decimals=2), lambda text: parse_number(text, 0.0, 1.0, scale=100.0, units=('%',)), write_ch_opacity
        if key.startswith(('SCALE.', 'DETAIL.', 'CONTRAST.')) and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            kind, channel = key.split('.')
            bounds = {'SCALE': (from_slider(0.0, SCALE_RANGE), from_slider(1.0, SCALE_RANGE)), 'DETAIL': (0.0, 1.0), 'CONTRAST': (0.0, .98)}[kind]
            field = kind.lower()
            def write_pattern(context, value):
                actions.set_slot_field(context, obj, data, channel, field, value)
                self.message = actions.commit_value(context, obj, data, f'{CHANNEL[channel].label} {field}')
            return format_number(getattr(layer.slots[channel], field)), lambda text: parse_number(text, bounds[0], bounds[1]), write_pattern
        if key == 'TILING' and data is not None:
            layer = active_layer(data)
            if layer is None:
                return None
            def write_tiling(context, value):
                actions.set_tiling(context, obj, data, value)
                self.message = actions.commit_value(context, obj, data, 'Tiling')
            return format_number(layer.tiling), lambda text: parse_number(text, from_slider(0.0, TILING_RANGE), from_slider(1.0, TILING_RANGE), units=('x',)), write_tiling
        if key == 'AUTOSAVE_MINUTES':
            return (format_number(max(autosave.minutes(), 1), integer=True),
                    lambda text: parse_number(text, autosave.MINUTE_RANGE[0], autosave.MINUTE_RANGE[1], integer=True, units=('min',)),
                    lambda context, value: autosave.set_minutes(value))
        if key == 'PREVIEW_SAMPLES':
            return format_number(self.scene.cycles.preview_samples, integer=True), lambda text: parse_number(text, 1, SAMPLE_TOP, integer=True), lambda context, value: setattr(self.scene.cycles, 'preview_samples', value)
        if key in POST_RANGES and obj is not None:
            field, top = POST_RANGES[key]
            def write_post(context, value):
                setattr(obj.devil_painter, field, value)
                post.write(self.scene, obj.devil_painter)
            return format_number(getattr(obj.devil_painter, field)), lambda text: parse_number(text, 0.0, top), write_post
        if key == 'CM_EXPOSURE':
            return format_number(self.scene.view_settings.exposure), lambda text: parse_number(text, EXPOSURE_RANGE[0], EXPOSURE_RANGE[1]), lambda context, value: setattr(self.scene.view_settings, 'exposure', value)
        if key == 'CM_GAMMA':
            return format_number(self.scene.view_settings.gamma), lambda text: parse_number(text, GAMMA_RANGE[0], GAMMA_RANGE[1]), lambda context, value: setattr(self.scene.view_settings, 'gamma', value)
        if key.startswith('FX_') and key.removeprefix('FX_') in FX_RANGES and data is not None:
            effect = active_effect(data)
            if effect is None:
                return None
            field = key.removeprefix('FX_')
            top, floor = FX_RANGES[field]
            holder = LevelsView(effect) if effect.kind == 'LEVELS' else effect
            scale = 100.0 if field == 'opacity' else 1.0
            units = ('%',) if field == 'opacity' else ('°', 'deg') if field == 'angle' else ()
            return (format_number(getattr(holder, field) * scale, decimals=2 if scale == 100.0 else 3),
                    lambda text: parse_number(text, floor, top, scale=scale, units=units),
                    lambda context, value: setattr(self, 'message', actions.edit_effect(context, obj, data, field, value, True)))
        return None

    def commit_text(self, context):
        edit = self.state.text
        self.state.text = None
        if edit.numeric:
            spec = self.number_spec(edit.key)
            if spec is not None:
                _, parse, write = spec
                write(context, parse(edit.text))
            return
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
        elif edit.key == 'STENCIL_TEXT' and data is not None and edit.text.strip():
            data.brush_stencil = vectors.text_stencil(edit.text.strip(), data.stencil_font)
            self.brush_changed(context, data)
            self.message = f'"{edit.text.strip()}" is the stencil now.'
        elif edit.key == 'BRIDGE_COMMAND':
            bridge.set_command(edit.text)
            self.message = 'Export & send uses this app now.' if edit.text.strip() else 'No app to send to.'
        elif edit.key == 'SHELF_SEARCH':
            self.state.shelf_query = edit.text.strip()
            self.state.scroll['SHELF'] = 0.0
        elif edit.key == 'LIBRARY_NEW':
            folder = edit.text.strip()
            self.message = f'Added the library {folder}.' if library.add_library(folder) else f'{folder} is not a folder.'

    def text_event(self, context, event, pointer_event):
        edit = self.state.text
        if pointer_event:
            if event.value in {'PRESS', 'DOUBLE_CLICK'} and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'}:
                control = self.workspace.hit(*self.pointer)
                owner = control is not None and (control.key == edit.key or control.key == 'ROW_' + edit.key.removeprefix('NAME_'))
                if not owner:
                    self.finish_text(context)
                    return None
                if edit.numeric and event.type == 'LEFTMOUSE':
                    edit.selected = event.value == 'DOUBLE_CLICK'
                    edit.cursor = len(edit.text)
                    self._area.tag_redraw()
                return {'RUNNING_MODAL'}
            return None
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type in {'RET', 'NUMPAD_ENTER'}:
            self.finish_text(context)
        elif event.type == 'TAB' and edit.numeric and not event.ctrl and not event.alt and not event.oskey:
            previous_key = edit.key
            self.finish_text(context)
            self.workspace = self.make_layout()
            following = self.next_slider(previous_key, event.shift)
            if following is not None:
                self.begin_number(following)
        elif event.type == 'ESC':
            self.state.text = None
        elif event.type == 'BACK_SPACE':
            if edit.selected:
                edit.text, edit.cursor, edit.selected = '', 0, False
            elif edit.cursor > 0:
                edit.text = edit.text[:edit.cursor - 1] + edit.text[edit.cursor:]
                edit.cursor -= 1
        elif event.type == 'DEL':
            if edit.selected:
                edit.text, edit.cursor, edit.selected = '', 0, False
            else:
                edit.text = edit.text[:edit.cursor] + edit.text[edit.cursor + 1:]
        elif event.type == 'LEFT_ARROW':
            edit.cursor = 0 if edit.selected else max(0, edit.cursor - 1)
            edit.selected = False
        elif event.type == 'RIGHT_ARROW':
            edit.cursor = len(edit.text) if edit.selected else min(len(edit.text), edit.cursor + 1)
            edit.selected = False
        elif event.type == 'HOME':
            edit.cursor, edit.selected = 0, False
        elif event.type == 'END':
            edit.cursor, edit.selected = len(edit.text), False
        elif event.ctrl and event.type == 'A':
            edit.selected, edit.cursor = True, len(edit.text)
        elif event.ctrl and event.type == 'C':
            context.window_manager.clipboard = edit.text
        elif event.ctrl and event.type == 'V':
            pasted = context.window_manager.clipboard.replace('\n', ' ')
            if edit.selected:
                edit.text, edit.cursor, edit.selected = pasted, len(pasted), False
            else:
                edit.text = edit.text[:edit.cursor] + pasted + edit.text[edit.cursor:]
                edit.cursor += len(pasted)
        else:
            typed = ('.' if edit.numeric and event.type == 'NUMPAD_PERIOD' and not event.ctrl and not event.alt
                     else event.unicode if event.unicode and event.unicode.isprintable() and not event.ctrl and not event.alt
                     else NUMERIC_KEYS.get(event.type, '') if edit.numeric and not event.ctrl and not event.alt and not event.shift else '')
            if typed:
                if edit.selected:
                    edit.text, edit.cursor, edit.selected = typed, len(typed), False
                else:
                    edit.text = edit.text[:edit.cursor] + typed + edit.text[edit.cursor:]
                    edit.cursor += len(typed)
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish_text(self, context):
        try:
            self.commit_text(context)
        except ValueError as failure:
            self.message = str(failure)

    def drag_event(self, context, event):
        key, rect = self.state.drag
        if key == 'ENV_ROTATE_DRAG':
            return self.env_rotate_event(event, rect)
        if key.startswith('SLIDER:'):
            slider_key = key.removeprefix('SLIDER:')
            release = event.type == 'LEFTMOUSE' and event.value == 'RELEASE'
            if not self.drag_moved and math.dist(self.pointer, self.drag_origin) > SLIDER_DRAG_START * self.workspace.scale:
                self.drag_moved = True
            if self.drag_moved and (event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} or release):
                x = max(0.0, min(1.0, (self.pointer[0] - rect.x) / rect.w))
                y = max(0.0, min(1.0, (self.pointer[1] - rect.y) / rect.h))
                self.apply_drag(context, slider_key, x, y, release)
            if release:
                self.state.drag = None
                if not self.drag_moved:
                    self.begin_number(slider_key)
                self.drag_moved = False
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        x = max(0.0, min(1.0, (self.pointer[0] - rect.x) / rect.w))
        y = max(0.0, min(1.0, (self.pointer[1] - rect.y) / rect.h))
        release = event.type == 'LEFTMOUSE' and event.value == 'RELEASE'
        if key.startswith('GIZMO_') and (event.type == 'MOUSEMOVE' or release):
            self.drag_gizmo(context, key, release)
        elif key.startswith('PATH_POINT.') and (event.type == 'MOUSEMOVE' or release):
            self.state.path_points[int(key.removeprefix('PATH_POINT.'))] = self.pointer
        elif event.type == 'MOUSEMOVE' or release:
            self.apply_drag(context, key, x, y, release)
        if release:
            self.state.drag = None
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def apply_drag(self, context, key, x, y, release):
        obj, data = self.painted()
        if key.startswith('SIZE.'):
            if key.removeprefix('SIZE.') in self.workspace.zones.rects:
                self.resize_section(key.removeprefix('SIZE.'))
            if release:
                self.save_column()
        elif key.startswith('STRIP.'):
            _, side, index = key.split('.')
            self.resize_strip(side, int(index))
            if release:
                self.save_column()
        elif key.startswith(('DRAG_SECTION.', 'GRAB_SECTION.')):
            self.track_section(key.partition('.')[2], release, key.startswith('DRAG_SECTION.'))
        elif key == 'BRUSH_SIZE' and data is not None and brushes.world_sized(data):
            data.brush_world_size = max(.001, x * MAX_WORLD_SIZE)
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
        elif key == 'DISP_SCALE' and data is not None:
            message = actions.set_set_value(context, obj, data, 'displacement_scale', x * DISPLACEMENT_SCALE_MAX, release)
            if message:
                self.message = message
        elif key == 'DISP_SUBDIV' and data is not None:
            message = actions.set_set_value(context, obj, data, 'displacement_subdivision', round(x * DISPLACEMENT_SUBDIVISION_MAX), release)
            if message:
                self.message = message
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
        elif key == 'PROJ_BEND' and data is not None:
            actions.set_projector(context, obj, data, dict(proj_bend=x), release)
        elif key == 'PROJ_SIZE' and data is not None:
            actions.set_projector(context, obj, data, dict(proj_size=from_slider(x, PROJECTOR_RANGE)), release)
        elif key == 'PROJ_SPIN' and data is not None:
            rotation = active_layer(data).proj_rotation
            actions.set_projector(context, obj, data, dict(proj_rotation=(rotation[0], rotation[1], math.radians(x * 360))), release)
        elif key in {'UV_OFFSET_X', 'UV_OFFSET_Y'} and data is not None:
            offset = list(active_layer(data).uv_offset)
            offset['XY'.index(key[-1])] = x
            actions.set_uv_projection(context, obj, data, dict(uv_offset=tuple(offset)), release)
        elif key == 'UV_SPIN' and data is not None:
            actions.set_uv_projection(context, obj, data, dict(uv_rotation=math.radians(x * 360)), release)
        elif key == 'TRIPLANAR_HARDNESS' and data is not None:
            actions.set_projector(context, obj, data, dict(triplanar_blend=1.0 - x), release)
        elif key == 'FX_TRIPLANAR_HARDNESS' and data is not None:
            actions.edit_effect(context, obj, data, 'triplanar_blend', 1.0 - x, False)
            if release:
                self.message = actions.edit_effect(context, obj, data, 'triplanar_blend', 1.0 - x, True)
        elif key == 'RADIAL' and data is not None:
            data.brush_radial = 1 + round(x * 15)
        elif key in DRAG_FIELDS and data is not None:
            field, top = DRAG_FIELDS[key]
            setattr(data, field, x * top)
            if key in NORMAL_KEYS:
                brushes.normal_color(data)
                compositing.update_values(data)
            self.brush_changed(context, data)
        elif key == 'BAKE_SAMPLES' and data is not None:
            data.bake_samples = max(1, round(x * 128))
        elif key == 'BAKE_EXTRUSION' and data is not None:
            data.bake_extrusion = max(.005, x * .5)
        elif key == 'BAKE_MAP_SAMPLES' and data is not None:
            bake_map_settings(data, self.state.bake_map).samples = max(1, round(x * 128))
        elif key == 'BAKE_MAP_EXTRUSION' and data is not None:
            bake_map_settings(data, self.state.bake_map).extrusion = max(.005, x * .5)
        elif key == 'BAKE_AO_DISTANCE' and data is not None:
            data.bake_ao_distance = max(.01, x * 2.0)
        elif key == 'BAKE_AO_SPREAD' and data is not None:
            data.bake_ao_spread = 15.0 + x * 165.0
        elif key == 'BAKE_THICKNESS_RANGE' and data is not None:
            data.bake_thickness_range = max(.01, x * 2.0)
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
        elif key.startswith('DRAG_ITEM.'):
            self.track_item(context, key, release)
        elif key == 'AUTOSAVE_MINUTES':
            autosave.set_minutes(round(autosave.MINUTE_RANGE[0] + x * (autosave.MINUTE_RANGE[1] - autosave.MINUTE_RANGE[0])))
        elif key == 'PREVIEW_SAMPLES':
            self.scene.cycles.preview_samples = max(1, round(x * SAMPLE_TOP))
        elif key in POST_RANGES and obj is not None:
            field, top = POST_RANGES[key]
            setattr(obj.devil_painter, field, x * top)
            post.write(self.scene, obj.devil_painter)
        elif key == 'CM_EXPOSURE':
            self.scene.view_settings.exposure = EXPOSURE_RANGE[0] + x * (EXPOSURE_RANGE[1] - EXPOSURE_RANGE[0])
        elif key == 'CM_GAMMA':
            self.scene.view_settings.gamma = GAMMA_RANGE[0] + x * (GAMMA_RANGE[1] - GAMMA_RANGE[0])
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

    def stencil_active(self, context, data):
        brush = context.tool_settings.image_paint.brush
        return (data.brush_stencil is not None and brush is not None
                and brush.texture is not None and brush.texture_slot.map_mode == 'STENCIL')

    def wants_env_rotate(self, context, event):
        data = self.painted()[1]
        if data is None or not event.shift or event.ctrl or event.alt or event.oskey:
            return False
        if not (0 <= self.pointer[0] < self._region.width and 0 <= self.pointer[1] < self._region.height):
            return False
        return not self.stencil_active(context, data)

    def start_env_rotate(self):
        space = self._area.spaces.active
        self.state.drag = ('ENV_ROTATE_DRAG', (self.pointer[0], float(space.shading.studiolight_rotate_z)))
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def env_rotate_event(self, event, origin):
        space = self._area.spaces.active
        start_x, start_angle = origin
        if event.type == 'ESC' and event.value == 'PRESS':
            space.shading.studiolight_rotate_z = start_angle
            self.state.drag = None
            self.message = f'Environment rotation {round(math.degrees(start_angle))}°.'
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        release = event.type == 'RIGHTMOUSE' and event.value == 'RELEASE'
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} or release:
            delta = (self.pointer[0] - start_x) / (ENV_ROTATE_PIXELS * self.workspace.scale) * math.tau
            angle = start_angle if delta == 0.0 else wrap_angle(start_angle + delta)
            space.shading.studiolight_rotate_z = angle
            self.message = f'Environment rotation {round(math.degrees(angle))}°.'
        if release:
            self.state.drag = None
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def stencil_moving(self):
        return any(operator.bl_idname == 'BRUSH_OT_stencil_control' for operator in self._window.modal_operators)

    def sync_stencil_resize(self, context):
        size = (self._region.width, self._region.height)
        if size == self.stencil_region or self.stencil_moving():
            return
        data = self.painted()[1]
        if data is None or data.brush_stencil is None:
            self.stencil_region = size
            return
        brush = context.tool_settings.image_paint.brush
        if brush is not None:
            brushes.sync_stencil(context, brush, data, self._region)
        self.stencil_region = size

    def finish_stencil(self, context):
        self.stencil_pending = False
        data = self.painted()[1]
        brush = context.tool_settings.image_paint.brush
        if data is not None and brush is not None and brushes.read_stencil(context, brush, data, self._region):
            self.brush_changed(context, data)
        self.stencil_region = (self._region.width, self._region.height)

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
        elif key.startswith('FOLDER_CHBLEND.'):
            channel = key.removeprefix('FOLDER_CHBLEND.')
            item = active_layer(data).channel_blends.get(channel)
            self.state.popover = Popover('MENU', control.rect, items=((f'SET_FOLDERCH.{channel}.{actions.SAME_AS_FOLDER}', 'Same as folder', item is None),) + tuple(
                (f'SET_FOLDERCH.{channel}.{mode}', label, item is not None and item.blend == mode) for mode, label in FOLDER_BLENDS))
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
        elif key == 'RESET_LAYOUT':
            self.state.popover = None
            self.message = self.reset_layout()
        elif control.kind == 'HEADER' and key.startswith('PANEL_'):
            self.state.drag = ('DRAG_SECTION.' + key.removeprefix('PANEL_'), control.rect)
            self.drag_origin = self.pointer
        elif control.kind == 'GIZMO':
            self.state.drag = (key, control.rect)
            if key.startswith('PATH_POINT.'):
                return None
        elif control.kind == 'SLIDER':
            self.state.drag = ('SLIDER:' + key, control.rect)
            self.drag_origin = self.pointer
            self.drag_moved = False
        elif control.kind in {'SV', 'HUE', 'GRIP'}:
            self.state.drag = (key, control.rect)
            x = max(0.0, min(1.0, (self.pointer[0] - control.rect.x) / control.rect.w))
            y = max(0.0, min(1.0, (self.pointer[1] - control.rect.y) / control.rect.h))
            self.apply_drag(context, key, x, y, False)
        elif key == 'QUICK_MASK':
            self.message = actions.toggle_quick_mask(context, obj, data)
        elif key == 'QUICK_APPLY':
            self.message = actions.apply_quick_mask(context, obj, data)
        elif key == 'PATH':
            self.state.path_mode = '' if self.state.path_mode else 'RIBBON'
            self.state.poly_mode, self.state.path_points = '', []
            self.message = 'Click points on the model, then press Enter.' if self.state.path_mode else 'Path tool off.'
        elif key.startswith('PATH.'):
            self.state.path_mode = key.removeprefix('PATH.')
        elif key == 'PATH_APPLY':
            self.message = self.apply_path(context)
        elif key == 'PATH_BACK':
            self.message = self.drop_point()
        elif key == 'PATH_CLEAR':
            self.state.path_points = []
        elif key == 'BRUSH_DYNAMICS':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_DYNAMICS.{value}', label, data.brush_dynamics == value)
                                                                           for value, label, _ in DYNAMICS))
        elif key.startswith('SET_DYNAMICS.'):
            data.brush_dynamics = key.removeprefix('SET_DYNAMICS.')
            self.message = f'Dynamics: {data.brush_dynamics.title()}.'
        elif key == 'STENCIL_TEXT':
            self.begin_text(key, '')
        elif key == 'STENCIL_FONT':
            self.fonts = vectors.system_fonts()
            self.state.popover = Popover('MENU', control.rect, items=(('SET_FONT.', 'Blender', not data.stencil_font),) + tuple(
                (f'SET_FONT.{index}', path.stem, str(path) == data.stencil_font) for index, path in enumerate(self.fonts)))
        elif key.startswith('SET_FONT.'):
            index = key.removeprefix('SET_FONT.')
            data.stencil_font = str(self.fonts[int(index)]) if index else ''
            self.message = f'Text stencils use {Path(data.stencil_font).stem if data.stencil_font else "Blender"}.'
        elif key == 'PROJ_SNAP':
            self.message = self.snap_projector(context, obj, data)
        elif key == 'PROJ_UNWARP':
            self.message = actions.set_projector(context, obj, data, dict(proj_warp=(0.0,) * 8), True)
        elif key == 'POLYFILL':
            self.state.path_mode = ''
            self.state.poly_mode = '' if self.state.poly_mode else 'FACE'
            self.message = 'Click the model to fill polygons.' if self.state.poly_mode else 'Polygon fill off.'
        elif key.startswith('POLY.'):
            self.state.poly_mode = key.removeprefix('POLY.')
            self.message = f'Click the model to fill a {POLY_NOUN[self.state.poly_mode]}.'
        elif key == 'POLY_ERASE':
            self.state.poly_erase = not self.state.poly_erase
        elif key in painting.BRUSH_NAMES:
            self.state.poly_mode = self.state.path_mode = ''
            painting.activate_tool(context, key)
            painting.update_canvas(context, data)
            brushes.sync(context, data)
            self.message = control.label + ' tool.'
        elif key == 'UNDO':
            self.message = self.history_step(context, redo=False)
        elif key == 'REDO':
            self.message = self.history_step(context, redo=True)
        elif key.startswith('HISTORY.'):
            self.message = self.history_jump(context, int(key.removeprefix('HISTORY.')))
        elif key == 'GENERATOR':
            current = active_effect(data).generator
            self.state.popover = Popover('MENU', control.rect, items=tuple(
                (f'SET_GENERATOR.{item.key}', item.label, current == item.key) for item in GENERATORS))
        elif key.startswith('SET_GENERATOR.'):
            self.message = actions.edit_effect(context, obj, data, 'generator', key.removeprefix('SET_GENERATOR.'), True)
        elif key == 'GEN_BREAKUP':
            current = active_effect(data).gen_breakup
            self.state.popover = Popover('MENU', control.rect, items=tuple(
                (f'SET_BREAKUP.{item.key}', item.label, current == item.key) for item in BREAKUPS))
        elif key.startswith('SET_BREAKUP.'):
            self.message = actions.edit_effect(context, obj, data, 'gen_breakup', key.removeprefix('SET_BREAKUP.'), True)
        elif key == 'GEN_INVERT':
            self.message = actions.edit_effect(context, obj, data, 'gen_invert', not active_effect(data).gen_invert, True)
        elif key == 'VIEW2D':
            self.message = self.close_flat(context) if self.flat_space() is not None else self.open_flat(context)
        elif key in {'BAKE', 'OPEN_BAKE'}:
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'BAKE' else Popover('BAKE', control.rect)
        elif key.startswith('BAKEMAP.'):
            self.state.bake_keys ^= {key.removeprefix('BAKEMAP.')}
        elif key.startswith('BAKE_SET.'):
            item = obj.devil_painter.sets[int(key.removeprefix('BAKE_SET.'))]
            self.message = actions.set_bake(context, obj, item, 'bake', not item.bake,
                                            f'{item.name} {"included in" if not item.bake else "excluded from"} baking.')
        elif key in BAKE_OBJECTS:
            field, prefix = BAKE_OBJECTS[key]
            current = getattr(data, field)
            meshes = [item.name for item in context.view_layer.objects if item.type == 'MESH' and item != obj]
            self.state.popover = Popover('MENU', control.rect, items=((prefix, 'None', current is None),) + tuple(
                (prefix + name, name, current is not None and current.name == name) for name in meshes))
        elif key.startswith(('SET_SOURCE.', 'SET_CAGE.')):
            field, prefix = next(item for item in BAKE_OBJECTS.values() if key.startswith(item[1]))
            self.message = actions.set_bake_object(context, obj, data, field, key.removeprefix(prefix))
        elif key == 'BAKE_ID':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BAKE_ID.{value}', label, data.bake_id == value) for value, label in BAKE_ID_LABELS.items()))
        elif key.startswith('SET_BAKE_ID.'):
            value = key.removeprefix('SET_BAKE_ID.')
            self.message = actions.set_bake(context, obj, data, 'bake_id', value, f'ID map colors by {BAKE_ID_LABELS[value].lower()}.')
        elif key == 'BAKE_RESOLUTION':
            self.state.popover = Popover('MENU', control.rect, items=tuple(
                (f'SET_BAKE_RESOLUTION.{size}', f'{size} px' if size else 'Texture set size', data.bake_resolution == size)
                for size in BAKE_RESOLUTIONS))
        elif key.startswith('SET_BAKE_RESOLUTION.'):
            size = int(key.removeprefix('SET_BAKE_RESOLUTION.'))
            self.message = actions.set_bake(context, obj, data, 'bake_resolution', size,
                                            f'Bake resolution: {size} px.' if size else 'Bake resolution: texture set size.')
        elif key == 'BAKE_ANTIALIAS':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BAKE_ANTIALIAS.{value}', label, data.bake_antialias == value)
                                                                           for value, label in BAKE_ANTIALIAS_LABELS.items()))
        elif key.startswith('SET_BAKE_ANTIALIAS.'):
            value = key.removeprefix('SET_BAKE_ANTIALIAS.')
            self.message = actions.set_bake(context, obj, data, 'bake_antialias', value, f'Bake anti-aliasing: {BAKE_ANTIALIAS_LABELS[value]}.')
        elif key.startswith('BAKE_SELECT.'):
            self.state.bake_map = key.removeprefix('BAKE_SELECT.')
        elif key == 'BAKE_MAP_SAMPLES_RESET':
            self.message = actions.reset_bake_map(context, obj, data, self.state.bake_map, 'samples')
        elif key == 'BAKE_MAP_EXTRUSION_RESET':
            self.message = actions.reset_bake_map(context, obj, data, self.state.bake_map, 'extrusion')
        elif key == 'BAKE_CURVATURE':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_BAKE_CURVATURE.{value}', label, data.bake_curvature == value)
                                                                           for value, label in BAKE_CURVATURE_LABELS.items()))
        elif key.startswith('SET_BAKE_CURVATURE.'):
            value = key.removeprefix('SET_BAKE_CURVATURE.')
            self.message = actions.set_bake(context, obj, data, 'bake_curvature', value, f'Curvature method: {BAKE_CURVATURE_LABELS[value]}.')
        elif key == 'BAKE_MATCH':
            self.message = actions.set_bake(context, obj, data, 'bake_match', not data.bake_match,
                                            'High-poly and cage match by name.' if not data.bake_match else 'High-poly and cage are picked by hand.')
        elif key.startswith('BAKE_PAINT.'):
            self.message = actions.paint_bake_map(context, obj, data, key.removeprefix('BAKE_PAINT.'))
        elif key.startswith('BAKE_UNPAINT.'):
            self.message = actions.clear_bake_map(context, obj, data, key.removeprefix('BAKE_UNPAINT.'))
        elif key == 'BAKE_AUTO':
            self.message = actions.set_bake(context, obj, data, 'bake_auto', not data.bake_auto,
                                            'Baked maps rebake when bake settings or meshes change.' if not data.bake_auto else 'Automatic rebaking is off.')
        elif key == 'BAKE_RUN':
            self.message = actions.start_bake(context, obj, data, [item.key for item in MESH_MAPS if item.key in self.state.bake_keys])
            if not bakejob.running():
                self.state.popover = None
        elif key == 'BAKE_CANCEL':
            self.message = actions.cancel_bake()
        elif key.startswith('MAP.'):
            self.message = actions.set_solo(context, obj, data, 'map:' + key.removeprefix('MAP.'))
        elif key == 'BRUSH_STROKE':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_STROKE.{value}', label, data.brush_stroke == value)
                                                                           for value, label, _ in STROKE_METHODS))
        elif key.startswith('SET_STROKE.'):
            data.brush_stroke = key.removeprefix('SET_STROKE.')
            self.brush_changed(context, data)
            self.message = f'{STROKE_LABEL[data.brush_stroke]} strokes.'
        elif key == 'SAVE_BRUSH':
            data.brush_preset = brushes.save_preset(data)
            self.message = f'Saved {data.brush_preset} to the brush shelf.'
        elif key.startswith('DELETE_BRUSH.'):
            self.message = f'Deleted {brushes.remove_preset(int(key.removeprefix("DELETE_BRUSH.")))}.'
        elif key == 'BRUSH_MATERIAL_CLEAR':
            brushes.clear_material(data)
            self.brush_changed(context, data)
            self.message = 'The brush paints plain values again.'
        elif key.startswith('PAINT_MATERIAL.'):
            brushes.use_material(context, data, shelf.resolved(self.shelf_item('ITEM.' + key.removeprefix('PAINT_MATERIAL.')).payload))
            self.brush_changed(context, data)
            self.message = f'The brush paints {data.brush_material} in every channel.'
        elif key in {'SYMMETRY', 'STENCIL_CARD'}:
            kind = 'SYMMETRY' if key == 'SYMMETRY' else 'STENCIL'
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == kind else Popover(kind, control.rect)
        elif key.startswith('MIRROR.'):
            index = 'XYZ'.index(key.removeprefix('MIRROR.'))
            data.brush_mirror[index] = not data.brush_mirror[index]
            self.brush_changed(context, data)
        elif key.startswith('RADIAL_AXIS.'):
            data.brush_radial_axis = key.removeprefix('RADIAL_AXIS.')
        elif key.startswith('USE_STENCIL.'):
            data.brush_stencil = bpy.data.images.load(str(self.shelf_item('ITEM.' + key.removeprefix('USE_STENCIL.')).payload), check_existing=True)
            self.brush_changed(context, data)
            self.message = 'Painting through the stencil. Open the stencil card to place or project it.'
        elif key == 'STENCIL_CLEAR':
            data.brush_stencil = None
            self.brush_changed(context, data)
        elif key == 'STENCIL_PROJECT':
            self.state.popover = None
            if data.brush_stencil is None:
                self.message = 'Pick a stencil first.'
            else:
                painting.update_canvas(context, data)
                self.message = projection.project(context, self._window, self._area, self._region, obj, data,
                                                  painting.uses_stroke_buffer(context, data))
        elif key == 'BRUSH_CARD':
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'BRUSH' else Popover('BRUSH', control.rect)
        elif key.startswith('SIZE_SPACE.'):
            data.brush_size_space = key.removeprefix('SIZE_SPACE.')
            self.world_pixels = (0, 0)
            self.brush_changed(context, data)
            self.message = ('The brush keeps its size on the model at any zoom.' if brushes.world_sized(data)
                            else 'The brush keeps its size on screen.')
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
            if self.state.shelf_tab == 'PACKS':
                packs.browse()
            library.rescan()
        elif key == 'SHELF_TOGGLE':
            self.state.shelf_open = not self.state.shelf_open
        elif key == 'TEXTURE_DIR':
            self.begin_text(key, library.texture_folder())
        elif key == 'TEXTURE_BROWSE':
            bpy.ops.devil_painter.choose_texture_folder('INVOKE_DEFAULT')
        elif key.startswith('ITEM.'):
            self.state.drag = ('DRAG_ITEM.' + key.removeprefix('ITEM.'), control.rect)
            self.drag_origin = self.pointer
        elif key == 'SHELF_SEARCH':
            self.begin_text(key, self.state.shelf_query)
        elif key.startswith('SCOPE.'):
            self.state.shelf_scope = key.removeprefix('SCOPE.')
            self.state.scroll['SHELF'] = 0.0
        elif key == 'SAVE_SEARCH':
            self.message = f'Saved the search {shelf.save_search(self.state.shelf_tab, self.state.shelf_query)}.'
        elif key.startswith('SEARCH.'):
            query = shelf.saved_searches()[int(key.removeprefix('SEARCH.'))]['query']
            self.state.shelf_query = '' if self.state.shelf_query == query else query
            self.state.scroll['SHELF'] = 0.0
        elif key.startswith('DELETE_SEARCH.'):
            self.message = f'Deleted the saved search {shelf.remove_search(int(key.removeprefix("DELETE_SEARCH.")))}.'
        elif key == 'PACKS_REFRESH':
            self.message = packs.refresh()
        elif key == 'PACK_BACK':
            packs.open_pack(None)
            self.state.scroll['SHELF'] = 0.0
        elif key == 'PACK_DOWNLOAD':
            self.message = packs.download(packs.open_entry())
        elif key.startswith('PACK_FILE.'):
            self.message = packs.download_file(*self.shelf_item('ITEM.' + key.removeprefix('PACK_FILE.')).payload)
        elif key.startswith('REMOVE_PACK.'):
            self.message = packs.remove(self.shelf_item('ITEM.' + key.removeprefix('REMOVE_PACK.')).payload)
        elif key == 'LIBRARIES':
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'LIBRARIES' else Popover('LIBRARIES', control.rect)
        elif key == 'LIBRARY_NEW':
            self.begin_text(key, '')
        elif key.startswith('LIBRARY.'):
            self.state.revealed ^= {library.libraries()[int(key.removeprefix('LIBRARY.'))]}
        elif key.startswith('LIB_REMOVE.'):
            self.message = f'Removed the library {library.remove_library(int(key.removeprefix("LIB_REMOVE.")))}.'
        elif key == 'LIBRARY_BROWSE':
            bpy.ops.devil_painter.choose_library_folder('INVOKE_DEFAULT')
        elif key == 'IMPORT_RESOURCES':
            bpy.ops.devil_painter.import_textures('INVOKE_DEFAULT')
        elif key == 'CM_VIEW':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_CM_VIEW.{name}', name, name == self.scene.view_settings.view_transform)
                                                                           for name in choices(self.scene, 'view_transform')))
        elif key.startswith('SET_CM_VIEW.'):
            self.scene.view_settings.view_transform = key.removeprefix('SET_CM_VIEW.')
            self.message = f'The viewport shows {self.scene.view_settings.view_transform}. Exports keep the raw texture values.'
        elif key == 'CM_LOOK':
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_CM_LOOK.{name}', name, name == self.scene.view_settings.look)
                                                                           for name in choices(self.scene, 'look')))
        elif key.startswith('SET_CM_LOOK.'):
            self.scene.view_settings.look = key.removeprefix('SET_CM_LOOK.')
            self.message = f'Look: {self.scene.view_settings.look}.'
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
        elif key == 'SAVE_SMART_MASK':
            self.message = actions.save_smart_mask(context, obj, data)
        elif key.startswith('DELETE_SMART_MASK.'):
            self.message = f'Deleted {smart.remove_mask(int(key.removeprefix("DELETE_SMART_MASK.")))}.'
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
        elif key == 'TILE_MATCH':
            layer = active_layer(data)
            layer.tile_match = not layer.tile_match
            self.message = actions.refresh(context, obj, data, f'{layer.name} repeats the same in every UV tile.' if layer.tile_match else f'{layer.name} runs across UV tiles.')
        elif key == 'PROJ_ALIGN':
            rotation = (obj.matrix_world.to_3x3().inverted() @ self._area.spaces.active.region_3d.view_rotation.to_matrix()).to_euler()
            self.message = actions.set_projector(context, obj, data, dict(proj_rotation=tuple(rotation)), True)
        elif key == 'PROJ_RESET':
            self.message = actions.set_projector(context, obj, data, dict(proj_offset=(0.0, 0.0, 0.0), proj_rotation=(0.0, 0.0, 0.0),
                                                                          proj_size=max(obj.dimensions) / 2 / max(max(obj.scale), 1e-6)), True)
        elif key.startswith('SET_PROJECTION.'):
            self.message = actions.set_projection(context, obj, data, key.removeprefix('SET_PROJECTION.'))
        elif key == 'COLOR_HEX':
            self.begin_text(key, control.text)
        elif key == 'EXPORT':
            self.state.popover = None if self.state.popover is not None and self.state.popover.kind == 'EXPORT' else Popover('EXPORT', control.rect)
        elif key == 'EXPORT_DIR':
            self.begin_text(key, obj.devil_painter.export_directory or default_directory(obj))
        elif key == 'BROWSE':
            bpy.ops.devil_painter.choose_export_folder('INVOKE_DEFAULT')
        elif key == 'BRIDGE_COMMAND':
            self.begin_text(key, bridge.command())
        elif key in {'SEND', 'OPEN_FOLDER'}:
            project = obj.devil_painter
            directory = bpy.path.abspath(project.export_directory or default_directory(obj))
            self.state.popover = None
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.message = actions.send_to_app(context, obj, project, directory) if key == 'SEND' else bridge.open_folder(directory)
        elif key in {'EXPORT_RUN', 'EXPORT_PSD'}:
            project = obj.devil_painter
            directory = bpy.path.abspath(project.export_directory or default_directory(obj))
            self.state.popover = None
            self.message = actions.export(context, obj, project, directory) if key == 'EXPORT_RUN' else actions.export_psd(context, obj, project, directory)
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
        elif key.startswith(('WRAP.', 'FILTERING.')):
            field, channel = key.lower().split('.')
            current = getattr(active_layer(data).slots[channel], field)
            self.state.popover = Popover('MENU', control.rect, items=tuple((f'SET_SAMPLING.{field}.{channel}.{mode}', label, mode == current)
                                                                          for mode, label, _ in TEXTURE_SAMPLING[field]))
        elif key.startswith('SET_SAMPLING.'):
            _, field, channel, mode = key.split('.')
            self.message = actions.set_sampling(context, obj, data, channel, field, mode)
        elif key in {'CHANNELS', 'PROJECT', 'VIEWPORT', 'OPEN_SHORTCUTS'}:
            kind = 'SHORTCUTS' if key == 'OPEN_SHORTCUTS' else key
            same = self.state.popover is not None and self.state.popover.kind == kind
            self.state.popover = None if same else Popover(kind, control.rect)
        elif key.startswith('CHANSET.'):
            channel = key.removeprefix('CHANSET.')
            self.message = actions.set_channel_enabled(context, obj, obj.devil_painter, channel, not data.channels[channel].enabled, self.state.channels_all)
        elif key.startswith('CHANDEPTH.'):
            channel = key.removeprefix('CHANDEPTH.')
            depths = [depth for depth, _, _ in CHANNEL_DEPTHS]
            depth = depths[(depths.index(data.channels[channel].depth) + 1) % len(depths)]
            self.message = actions.set_channel_depth(context, obj, obj.devil_painter, channel, depth, self.state.channels_all)
        elif key == 'CHANNELS_ALL':
            self.state.channels_all = not self.state.channels_all
        elif key.startswith(('PNF.', 'PNS.')):
            field = 'normal_format' if key.startswith('PNF.') else 'normal_space'
            self.message = actions.set_project_value(context, obj, obj.devil_painter, field, key.split('.', 1)[1])
        elif key == 'PHYS_USE':
            self.message = actions.set_project_value(context, obj, obj.devil_painter, 'use_physical', not obj.devil_painter.use_physical)
        elif key.startswith('SHADER.'):
            self.message = actions.set_set_value(context, obj, data, 'shader', key.removeprefix('SHADER.'), True)
        elif key == 'HEIGHT_DISP':
            self.message = actions.set_set_value(context, obj, data, 'height_displacement', not data.height_displacement, True)
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
        elif key.startswith('TRANSP.'):
            self.message = actions.set_set_value(context, obj, data, 'transparency', key.removeprefix('TRANSP.'), True)
        elif key == 'TRANSP_OVERLAP':
            self.message = actions.set_set_value(context, obj, data, 'transparency_overlap', not data.transparency_overlap, True)
        elif key == 'CROSS_TILES':
            obj.devil_painter.cross_tiles = not obj.devil_painter.cross_tiles
            self.message = ('Strokes cross UV tiles; they appear when you release the mouse.' if obj.devil_painter.cross_tiles
                            else 'Strokes stay in the tile they start in and show live.')
        elif key == 'AUTOSAVE':
            autosave.set_minutes(0 if autosave.minutes() else AUTOSAVE_DEFAULT)
            self.message = autosave.status() + '.'
        elif key == 'PATH_TRACED':
            self.message = self.toggle_path_traced(context)
        elif key == 'POST':
            obj.devil_painter.post_enabled = not obj.devil_painter.post_enabled
            self.message = post.apply(self.scene, self._area.spaces.active, obj.devil_painter)
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
            layer = active_layer(data)
            if layer is not None and (layer.mask is not None or mask_effects(layer)):
                items.append((f'SOLO.mask:{layer.uid}', 'Mask of ' + layer.name, data.solo == 'mask:' + layer.uid))
            self.state.popover = Popover('MENU', control.rect, items=tuple(items))
        elif key.startswith('SOLO.'):
            self.message = actions.set_solo(context, obj, data, key.removeprefix('SOLO.'))
        elif key == 'RENAME':
            self.begin_text(f'NAME_{data.active_uid}', active_layer(data).name)
        elif key == 'DUPLICATE':
            self.message = actions.duplicate_layer(context, obj, data)
        elif key.startswith('ROW_'):
            self.message = self.select_row(context, obj, data, key.removeprefix('ROW_'), control, double)
        elif key.startswith('EYE_') and self.modifiers[2]:
            self.message = actions.toggle_isolate(context, obj, data, key.removeprefix('EYE_'))
        elif key.startswith('EYE_'):
            self.message = actions.toggle_visible(context, obj, data, key.removeprefix('EYE_'))
        elif key == 'ISOLATE':
            self.message = actions.toggle_isolate(context, obj, data, data.active_uid)
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
        elif key in {'DELETE', 'DELETE_LAYER'}:
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
            uid = key.removeprefix('MASKTHUMB_')
            self.message = actions.select_layer(context, obj, data, uid, mask=True)
            if self.modifiers[2]:
                self.message = actions.set_solo(context, obj, data, '' if data.solo == 'mask:' + uid else 'mask:' + uid)
        elif key in {'SELECT_LAYER', 'SELECT_MASK'}:
            self.message = actions.set_target(context, obj, data, 'MASK' if key == 'SELECT_MASK' else 'CONTENT')
        return None

    def shelf_item(self, key):
        return shelf.visible(self.state.shelf_tab, self.state.shelf_query, self.state.shelf_scope)[int(key.removeprefix('ITEM.'))]

    def mesh_drop_target(self, obj, data, item):
        if data is None or item.kind not in LAYER_KINDS:
            return None
        if not (0 <= self.pointer[0] < self._region.width and 0 <= self.pointer[1] < self._region.height):
            return None
        if self.workspace.covers(*self.pointer):
            return None
        face = sets.face_under(self._region, self._area.spaces.active.region_3d, obj, self.pointer)
        if face < 0:
            return None
        return sets.locate(obj, obj.devil_painter, face)

    def slot_drop_target(self, data, item):
        if data is None or self.state.popover is not None:
            return None
        controls = {control.key: control for control in self.workspace.controls}
        px, py = self.pointer

        def over(left, right):
            area = Rect(left.rect.x, left.rect.y, right.rect.x + right.rect.w - left.rect.x, left.rect.h)
            return area.contains(px, py) and (left.clip is None or left.clip.contains(px, py))

        if item.kind in {'TEXTURE', 'PATTERN'}:
            layer = active_layer(data)
            if layer is not None and layer.kind == 'FILL':
                for control in self.workspace.controls:
                    if control.key.startswith('SOURCE.'):
                        channel = control.key.removeprefix('SOURCE.')
                        if over(controls.get('USE.' + channel, control), controls.get('BLEND.' + channel, control)):
                            return channel
            effect = active_effect(data)
            if effect is not None and effect.kind == 'FILL' and 'FX_SOURCE' in controls:
                source = controls['FX_SOURCE']
                if over(source, controls.get('FX_SOURCE_NAME', source)):
                    return EFFECT_TARGET
        if item.kind == 'MATERIAL':
            layer = active_layer(data)
            if layer is not None and layer.kind == 'FILL' and 'MATERIAL_THUMB' in controls:
                thumb = controls['MATERIAL_THUMB']
                if over(thumb, controls.get('REPLACE_MATERIAL', thumb)):
                    return REPLACE_TARGET
        return None

    def track_item(self, context, key, release):
        item = self.shelf_item('ITEM.' + key.removeprefix('DRAG_ITEM.'))
        moved = math.dist(self.pointer, self.drag_origin) > DRAG_START * self.workspace.scale
        obj, data = self.painted()
        target = self.drop_target('ROW_') if moved else None
        slot = None if target is not None or not moved else self.slot_drop_target(data, item)
        mesh_hit = None if target is not None or slot is not None or not moved else self.mesh_drop_target(obj, data, item)
        if target is not None:
            height = (self.pointer[1] - target.rect.y) / target.rect.h
            folder = find_layer(data, target.key.removeprefix('ROW_')).kind == 'FOLDER'
            mode = 'INTO' if item.kind in ONTO_KINDS or (folder and .33 <= height <= .66) else 'ABOVE' if height >= .5 else 'BELOW'
            self.state.drop = (target.key, mode)
        elif slot is not None:
            self.state.drop = ('SLOT', slot)
        elif mesh_hit is not None:
            self.state.drop = ('MESH', mesh_hit[0], mesh_hit[1])
        else:
            self.state.drop = ()
        self.highlight = mesh_hit[0] if mesh_hit is not None and not release else None
        self.state.ghost = (self.pointer[0], self.pointer[1], item.label, shelf.thumbnail(item)) if moved and not release else ()
        if not release:
            return
        drop, self.state.drop = self.state.drop, ()
        if not moved:
            self.message = self.use_shelf_item(context, obj, data, item)
        elif drop and drop[0] == 'SLOT':
            self.message = self.use_shelf_item(context, obj, data, item, drop[1])
        elif drop and drop[0] == 'MESH':
            self.message = self.drop_on_mesh(context, obj, item, drop[1], drop[2])
        elif drop:
            self.message = self.drop_item(context, obj, data, item, drop[0].removeprefix('ROW_'), drop[1])
        elif 'LAYERS' in self.workspace.scroll_areas and self.workspace.scroll_areas['LAYERS'][0].contains(*self.pointer):
            self.message = self.use_shelf_item(context, obj, data, item)

    def drop_on_mesh(self, context, obj, item, set_index, tile):
        actions.activate(context, obj, obj.devil_painter, set_index, tile)
        data = texture_set(obj)
        self.state.multi.clear()
        self.state.armed = ''
        top = next((layer.uid for layer in reversed(data.layers) if not layer.parent), '')
        if top:
            return self.drop_item(context, obj, data, item, top, 'ABOVE')
        return self.use_shelf_item(context, obj, data, item)

    def drop_item(self, context, obj, data, item, target_uid, mode):
        actions.select_layer(context, obj, data, target_uid)
        message = self.use_shelf_item(context, obj, data, item)
        if item.kind not in LAYER_KINDS or data.active_uid == target_uid:
            return message
        actions.drop_layer(context, obj, data, data.active_uid, target_uid, mode)
        return message

    def use_shelf_item(self, context, obj, data, item, slot=None):
        armed = self.state.armed if slot is None else slot
        self.state.armed = ''
        layer = active_layer(data)
        if item.kind == 'MATERIAL':
            item = shelf.Item(item.label, item.kind, shelf.resolved(item.payload), item.user_index, item.preview_file, item.managed, item.mine)
        if armed == REPLACE_TARGET and item.kind == 'MATERIAL' and layer is not None and layer.kind == 'FILL':
            return actions.replace_material(context, obj, data, item.payload)
        if armed == EFFECT_TARGET:
            effect = active_effect(data)
            if effect is not None and effect.kind == 'FILL':
                if item.kind == 'TEXTURE':
                    actions.edit_effect(context, obj, data, 'texture', library.load_image(item.payload, CHANNEL['roughness']), False)
                    return actions.edit_effect(context, obj, data, 'source', 'IMAGE', True)
                if item.kind == 'PATTERN':
                    actions.edit_effect(context, obj, data, 'source', 'PATTERN', False)
                    return actions.edit_effect(context, obj, data, 'pattern', item.payload, True)
        armed = '' if armed in {REPLACE_TARGET, EFFECT_TARGET} else armed
        target = armed if armed and layer is not None and layer.kind == 'FILL' else ''
        if item.kind == 'SMART':
            return actions.add_smart_material(context, obj, data, item.payload)
        if item.kind == 'GENERATOR':
            if layer is None:
                return 'Select a layer to mask.'
            return actions.add_generator(context, obj, data, dict(generator=item.payload))
        if item.kind == 'FILTER':
            if layer is None or layer.kind == 'INSTANCE':
                return 'Select a layer to filter.'
            target = 'MASK' if editing_mask(data) and not FILTER[item.payload].color_only else 'CONTENT'
            actions.add_effect(context, obj, data, 'FILTER', target)
            return actions.edit_effect(context, obj, data, 'filter', item.payload, True)
        if item.kind == 'PACK':
            packs.open_pack(item.payload)
            self.state.scroll['SHELF'] = 0.0
            return f'{item.label}: {len(packs.files(item.payload))} files. Click one to download it, or download the whole pack.'
        if item.kind == 'PACKFILE':
            entry, name = item.payload
            path = packs.file_path(entry, name)
            if not path.is_file():
                return packs.download_file(entry, name)
            if packs.kind_folder(entry, name) == 'Alphas':
                data.brush_alpha = brushes.load_alpha(str(path))
                brushes.sync(context, data)
                return f'Brush alpha: {item.label}.'
            return actions.add_material(context, obj, data, shelf.texture_definition(path))
        if item.kind == 'VECTOR':
            data.brush_stencil = vectors.svg_stencil(item.payload)
            self.brush_changed(context, data)
            return f'{item.label} is the stencil now. Paint through it or project it from the stencil card.'
        if item.kind == 'ENVIRONMENT':
            self._area.spaces.active.shading.studio_light = item.payload
            return f'The viewport is lit by {item.label}.'
        if item.kind == 'MASK' and item.user_index >= 0:
            return actions.apply_smart_mask(context, obj, data, item.payload)
        if item.kind == 'MASK':
            if layer is None:
                return 'Select a layer to mask.'
            return actions.add_generator(context, obj, data, {key: value for key, value in item.payload.items() if key != 'name'})
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
        elif key == 'EXPORT_PADDING_STYLE':
            items = tuple((f'SET_EXPORT_PADDING_STYLE.{style}', label, style == project.export_padding_style)
                          for style, label in exporting.PADDING_STYLES.items())
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
        if key.startswith('SET_EXPORT_PADDING_STYLE.'):
            project.export_padding_style = key.removeprefix('SET_EXPORT_PADDING_STYLE.')
            return 'Padding style set.'
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
        bakejob.cancel()
        window = found_window(self._window_address)
        space = None if window is None else found_space(window, self._space_address)
        if self.engine_before:
            try:
                if space is not None:
                    space.shading.type = 'MATERIAL'
                self.scene.render.engine = self.engine_before
            except ReferenceError:
                pass
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
        if space is not None:
            give_back_regions(space, self.saved_regions)
        if window is not None:
            if window.screen.show_fullscreen:
                _pending_regions.append((self._window_address, self._space_address, dict(self.saved_regions)))
                if not bpy.app.timers.is_registered(regions_after_full_screen):
                    bpy.app.timers.register(regions_after_full_screen, first_interval=.1)
            for area in window.screen.areas:
                area.tag_redraw()
        try:
            self.close_flat(bpy.context)
        except (ReferenceError, RuntimeError):
            self.flat_area = None
        if _active is self:
            _active = None

    def cancel(self, context):
        self.cleanup()


class DEVIL_PAINTER_OT_stroke_end(bpy.types.Operator):
    bl_idname = 'devil_painter.stroke_end'
    bl_label = 'Devil Painter stroke end'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        painting_now = any(operator.bl_idname.startswith('PAINT_OT') for operator in context.window.modal_operators)
        if _active is None or _active._closed or not painting_now:
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            _active.remember_anchor((event.mouse_x - _active._region.x, event.mouse_y - _active._region.y))
            return {'FINISHED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}
