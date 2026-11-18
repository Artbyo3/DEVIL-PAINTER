import colorsys
from dataclasses import dataclass
import json
import math
import numpy
from . import autosave, packs, shelf, thumbnails
from .post import POST_SLIDERS
from .bridge import command as bridge_command
from pathlib import Path
from .blending import BLEND_MODES, CHANNEL, CHANNELS, FOLDER_BLENDS, linear_to_srgb
from .canvas import Layout, Rect
from .document import (BAKE_ID_LABELS, DYNAMICS, NORMAL_FORMATS, PROJECTORS, STROKE_METHODS, TRANSPARENCY, NORMAL_SPACES, PROJECTIONS, RESOLUTIONS, SHADERS, active_effect, active_layer, children, editing_mask, find_layer, isolated_uids,
                       linked_layer, set_channels, slot_value, uses_coordinates)
from .effects import EFFECT_ICONS, EFFECT_KINDS, FILL_PROJECTIONS, LEVEL_COMPONENTS, MASK_BLEND_LABEL, LevelsView, effect_label
from .filters import FILTER, FILTERS
from .library import capture, libraries as library_folders, texture_folder
from .exporting import FORMAT_LABELS, SOURCES, TOKENS, find_template, is_custom
from .projects import UNWRAP_MODES
from .shortcuts import ACTIONS, bindings, key_label
from .masks import BUILDER_SLIDERS, GENERATOR
from .sets import tile_label
from .tiles import numbers
from .meshmaps import MESH_MAP, MESH_MAPS
from .painting import TOOLS
from .polyfill import POLY_MODES
from .privacy import masked, masked_path
from .shell import COLUMNS, HEADER, SECTIONS, arrange, flexible
from .ui_system import ACCENT, MinimalMetrics

MAX_BRUSH_SIZE = 500
ROW_HEIGHT = 42
LINE_HEIGHT = 28
MENU_ROW = 26
MENU_WIDTH = 196
MENU_HEADING = 'HEADING.'
STROKE_LABELS = {key: label for key, label, _ in STROKE_METHODS}
DYNAMIC_LABELS = {key: label for key, label, _ in DYNAMICS}
PROJECTOR_RANGE = (.05, 50.0)
GIZMO_HANDLE = 9
SAMPLE_TOP = 1024
EXPOSURE_RANGE = (-5.0, 5.0)
GAMMA_RANGE = (.2, 3.0)
SHELF_TIPS = {'GENERATOR': 'Click to mask the selected layer with this generator', 'FILTER': 'Click to add this filter to the selected layer',
              'ENVIRONMENT': 'Click to light the viewport with this environment'}
THUMBNAIL = 32
RECENT_COLORS = 8
FOV_RANGE = (10.0, 150.0)
MAP_TILE = 56
INDENT = 14
CHANNEL_OPACITY_WIDTH = 44
BLEND_WIDTH = 78
TOGGLE_WIDTH = 100
BAR_MENU_WIDTH = 150
SHELF_TILE = 72
SHELF_LABEL = 18
SHELF_GAP = 8
SEARCH_SPLIT = 520
PREFETCH_SCREENS = 2
REPLACE_TARGET = '@material'
EFFECT_TARGET = '@effect'
BAKE_TIPS = {'normal': 'Tangent normal from the high-poly, or this mesh with rounded edges when there is none',
             'height': 'Height difference from this mesh to the high-poly', 'id': 'Flat color regions to pick masks from'}
SHELF_PROMPTS = {REPLACE_TARGET: 'Click a material to put into the selected layer', EFFECT_TARGET: 'Click a texture to fill the selected effect'}
SCALE_RANGE = (-1.0, 9.0)
TILING_RANGE = (-3.0, 5.0)


def to_slider(value, span):
    low, high = span
    return (math.log2(value) - low) / (high - low)


def from_slider(position, span):
    low, high = span
    return 2 ** (low + position * (high - low))


def display_color(color):
    return tuple(float(value) for value in linear_to_srgb(numpy.array(color[:3]))) + (1.0,)


def slot_display(slot, second=False):
    value = slot_value(slot, second)
    rgb = value if len(value) == 3 else value * 3
    return display_color(rgb) if CHANNEL[slot.name].srgb else (*rgb, 1.0)


def channel_names(data):
    return ' · '.join(channel.label for channel in set_channels(data))


def hsv_color(hsv):
    return tuple(colorsys.hsv_to_rgb(*hsv)) + (1.0,)


@dataclass(frozen=True)
class ColumnPanel:
    key: str
    title: str
    body: float
    fill: object
    pad: float
    actions: tuple = ()


@dataclass(frozen=True)
class Section:
    lines: object
    build: object


class Flow:
    def __init__(self, layout, viewport, scroll, pad):
        self.layout, self.viewport, self.pad = layout, viewport, pad
        self.y = viewport.top + scroll - pad

    def line(self, height):
        self.y -= height
        return Rect(self.viewport.x + self.pad, self.y, self.viewport.w - 2 * self.pad, height)

    def field(self, height=24):
        s = self.layout.scale
        line = self.line(LINE_HEIGHT * s)
        return line.x, line.y + 2 * s, height * s

    def visible(self, rect):
        return rect.top > self.viewport.y and rect.y < self.viewport.top

    def add(self, key, rect, kind, **values):
        return self.layout.add(key, rect, kind, clip=self.viewport, **values)


def panel(layout, state, spec, x, top, width, view):
    s = layout.scale
    header = Rect(x, top - HEADER * s, width, HEADER * s)
    collapsed = spec.key in state.collapsed
    card = Rect(x, header.y - view, width, header.h + view)
    layout.cards.append((card, ''))
    layout.add('PANEL_' + spec.key, header, 'HEADER', label=spec.title, active=not collapsed,
               tip=('Collapse' if not collapsed else 'Expand') + '. Drag to move the panel')
    right = header.x + header.w - 6 * s
    for action_key, label, width_units, tip in spec.actions:
        w = width_units * s
        right -= w
        layout.add(action_key, Rect(right, header.y + 4 * s, w, header.h - 8 * s), 'CHIP', label=label, tip=tip)
        right -= 4 * s
    viewport = Rect(x, card.y, width, view)
    overflow = max(0.0, spec.body - view)
    scroll = min(max(0.0, state.scroll.get(spec.key, 0.0)), overflow)
    state.scroll[spec.key] = scroll
    if overflow > 0 and view > 0:
        layout.scroll_areas[spec.key] = (viewport, overflow)
        layout.add('SCROLL_' + spec.key, Rect(x + width - 5 * s, viewport.y + 2 * s, 3 * s, view - 4 * s), 'SCROLLBAR',
                   value=scroll / overflow, second=view / spec.body)
    return card, viewport, scroll


SETUP_ROW = 30
SHADER_SLIDERS = (('BUMP_STRENGTH', 'Height strength', 'bump_strength', 1.0), ('NORMAL_STRENGTH', 'Normal strength', 'normal_strength', 2.0),
                  ('EMIT_STRENGTH', 'Emission strength', 'emission_strength', 20.0))


def chip_row(layout, prefix, options, chosen, x, y, w, s, tip):
    width = (w - 4 * s * (len(options) - 1)) / len(options)
    for index, (key, label) in enumerate(options):
        layout.add(f'{prefix}.{key}', Rect(x + index * (width + 4 * s), y, width, 24 * s), 'CHIP', label=label, active=key == chosen, tip=tip)


def start_layout(layout, state, bounds, obj_name, setup):
    s = layout.scale
    rows, udim_found, has_uv = setup
    extra = 3 + (1 if not has_uv else 0)
    w, h = 480 * s, (196 + SETUP_ROW * (max(1, len(rows)) + extra)) * s
    card = Rect(bounds.x + (bounds.w - w) / 2, bounds.y + (bounds.h - h) / 2, w, h)
    layout.cards.append((card, 'New Devil Painter project'))
    layout.add('CLOSE', Rect(card.x + card.w - 32 * s, card.y + card.h - 32 * s, 24 * s, 24 * s), 'ICON', icon='CLOSE',
               tip='Close', shortcut='Ctrl Alt P')
    x, w = card.x + 14 * s, card.w - 28 * s
    layout.add('TARGET', Rect(x, card.top - 64 * s, w, 22 * s), 'NOTE', label=obj_name or 'Select a mesh object to paint.')
    y = card.top - 64 * s - SETUP_ROW * s
    layout.add('SETUP_TEMPLATE', Rect(x, y, w, 24 * s), 'DROPDOWN', label='Template', text=state.setup_template,
               tip='Channels, shader, normal format, and export template to start from')
    y -= SETUP_ROW * s
    layout.add('SETUP_NF_LABEL', Rect(x, y, 100 * s, 24 * s), 'NOTE', label='Normal map')
    chip_row(layout, 'SETUP_NF', [(key, label) for key, label, _ in NORMAL_FORMATS], state.setup_normal_format, x + 104 * s, y, 150 * s, s,
             'Green channel convention of normal maps')
    chip_row(layout, 'SETUP_NS', [(key, label) for key, label, _ in NORMAL_SPACES], state.setup_normal_space, x + 266 * s, y, w - 266 * s, s,
             'Tangent mode of the normal channel')
    if not has_uv:
        y -= SETUP_ROW * s
        layout.add('SETUP_UNWRAP_LABEL', Rect(x, y, 100 * s, 24 * s), 'NOTE', label='Unwrap')
        chip_row(layout, 'SETUP_UNWRAP', UNWRAP_MODES, state.setup_unwrap, x + 104 * s, y, w - 104 * s, s, 'The mesh has no UVs; pick how to unwrap it')
    y -= SETUP_ROW * s
    layout.add('SETUP_HINT', Rect(x, y, w, 20 * s), 'NOTE', label='One texture set per material slot')
    for index, (name, found) in enumerate(rows):
        y -= SETUP_ROW * s
        chosen = state.setup_resolutions.get(index, 2048)
        layout.add(f'SETUP_SET.{index}', Rect(x, y, 150 * s, 24 * s), 'NOTE', label=name)
        layout.add(f'SETUP_TILES.{index}', Rect(x + 154 * s, y, 120 * s, 24 * s), 'NOTE', label=tile_label(found))
        chip_w = (w - 280 * s - 8 * s) / len(RESOLUTIONS)
        for column, size in enumerate(RESOLUTIONS):
            layout.add(f'RES.{index}.{size}', Rect(x + 280 * s + column * (chip_w + 4 * s), y, chip_w, 24 * s), 'CHIP', label=f'{size // 1024}K',
                       active=size == chosen, tip=f'{size} x {size} pixels per tile for {name}')
    if udim_found:
        layout.add('SETUP_UDIM', Rect(x, card.y + 56 * s, w, 24 * s), 'TOGGLE', label='Use UDIM tiles from the UV layout', active=state.setup_udim,
                   tip='Paint, bake, and export every UV tile the mesh uses')
    layout.add('START', Rect(x, card.y + 14 * s, w, 30 * s), 'PRIMARY', icon='PAINT',
               label='Start painting', tip='Create the project: texture sets, materials, and a first paint layer in each')


def view_label(data):
    if data.solo.startswith('mask:'):
        layer = find_layer(data, data.solo.removeprefix('mask:'))
        return 'Mask · ' + layer.name if layer is not None else 'Material'
    if data.solo.startswith('map:'):
        return MESH_MAP[data.solo.removeprefix('map:')].label
    return CHANNEL[data.solo].label if data.solo else 'Material'


def workspace_bar(layout, zone, data, obj_name, view_2d):
    s = layout.scale
    layout.cards.append((zone, ''))
    h = min(zone.h - 12 * s, 24 * s)
    y = zone.y + (zone.h - h) / 2
    right = zone.x + zone.w - 8 * s
    layout.add('CLOSE', Rect(right - 24 * s, y, 24 * s, h), 'ICON', icon='CLOSE', tip='Close Devil Painter', shortcut='Ctrl Alt P')
    export = Rect(right - 186 * s, y, 150 * s, h)
    layout.add('EXPORT', export, 'PRIMARY', icon='SAVE', label='Export textures', tip='Choose a folder and write the textures')
    menu_w = BAR_MENU_WIDTH * s
    view = Rect(export.x - 8 * s - menu_w, y, menu_w, h)
    layout.add('VIEW', view, 'DROPDOWN', label='View', text=view_label(data), tip='Show the full material, one channel, or a mesh map')
    channels = Rect(view.x - 6 * s - menu_w, y, menu_w, h)
    bake = Rect(channels.x - 6 * s - 110 * s, y, 110 * s, h)
    layout.add('BAKE', bake, 'CHIP', label='Bake maps', tip='Bake ambient occlusion, curvature, thickness, position, world normal, and ID maps')
    flat = Rect(bake.x - 6 * s - 80 * s, y, 80 * s, h)
    layout.add('VIEW2D', flat, 'CHIP', label='2D view', active=view_2d, tip='Show the selected canvas flat in UV space next to the model and paint on it')
    viewport = Rect(flat.x - 6 * s - 84 * s, y, 84 * s, h)
    layout.add('VIEWPORT', viewport, 'CHIP', label='Viewport', tip='Environment lighting, rotation, field of view, and projection')
    project = Rect(viewport.x - 6 * s - 76 * s, y, 76 * s, h)
    layout.add('PROJECT', project, 'CHIP', label='Project', tip='Normal format, tangent mode, physical size, shader, mesh reimport, and shortcuts')
    bake = project
    layout.add('CHANNELS', channels, 'DROPDOWN', label='Channels', text=str(len(set_channels(data))),
               tip=channel_names(data) + '. Choose which channels this texture set paints and exports')
    count = len(numbers(data))
    tile = f'  ·  tile {data.id_data.devil_painter.active_tile}' if count > 1 else ''
    layout.add('SET_NAME', Rect(zone.x + 12 * s, y, max(0.0, bake.x - zone.x - 24 * s), h), 'NOTE',
               label=f'{obj_name}  ·  {data.name}  ·  {data.resolution} px{tile}')


BRUSH_SLIDERS = (('BRUSH_FLOW', 'Flow', 'brush_flow', 1.0, 'How much paint each dab lays down; low flow builds up gradually'),
                 ('BRUSH_SPACING', 'Spacing', 'brush_spacing', 200.0, 'Distance between dabs, in percent of the brush size'),
                 ('BRUSH_HARDNESS', 'Hardness', 'brush_hardness', 1.0, 'Soft or hard brush edge'),
                 ('BRUSH_SMOOTHING', 'Lazy mouse', 'brush_smoothing', 1.0, 'Stabilize the stroke so it trails the pointer smoothly'),
                 ('BRUSH_JITTER', 'Jitter', 'brush_jitter', 1.0, 'Scatter dabs around the stroke'),
                 ('BRUSH_ANGLE', 'Angle', 'brush_angle', 360.0, 'Rotate the brush tip and its alpha'))
NORMAL_SLIDERS = (('BRUSH_NORMAL_TILT', 'Normal tilt', 'brush_normal_tilt', 89.0), ('BRUSH_NORMAL_ANGLE', 'Normal direction', 'brush_normal_angle', 360.0))
STENCIL_SLIDERS = (('STENCIL_SCALE', 'Scale', 'stencil_scale', 4.0), ('STENCIL_ANGLE', 'Rotation', 'stencil_angle', 360.0),
                   ('STENCIL_X', 'Left to right', 'stencil_x', 1.0), ('STENCIL_Y', 'Bottom to top', 'stencil_y', 1.0))
BRUSH_TOGGLES = (('BRUSH_PRESSURE_SIZE', 'Pressure size', 'brush_pressure_size'), ('BRUSH_PRESSURE_OPACITY', 'Pressure flow', 'brush_pressure_opacity'),
                 ('BRUSH_RANDOM_ANGLE', 'Random angle', 'brush_random_angle'))
SHORT_NAMES = {'roughness': 'Rough', 'metallic': 'Metal', 'normal': 'Normal', 'height': 'Height', 'emission': 'Emit', 'opacity': 'Alpha'}


def brush_value_control(layout, channel, slot, rect):
    if channel.width == 3:
        return layout.add('BRUSHSW.' + channel.key, rect, 'SWATCH', color=slot_display(slot), tip=f'{channel.label} the brush paints')
    return layout.add('BRUSHVAL.' + channel.key, rect, 'SLIDER', label=SHORT_NAMES[channel.key], value=slot.value, text=f'{slot.value:.2f}',
                      tip=f'{channel.label} the brush paints')


def quick_controls(layout, zone, y, h, data):
    s = layout.scale
    right = zone.x + zone.w - 8 * s
    on = data.quick_mask is not None
    if on:
        right -= 132 * s
        layout.add('QUICK_APPLY', Rect(right, y, 128 * s, h), 'CHIP', label='Mask selected layer', tip='Use the quick mask as the mask of the selected layer')
    right -= 104 * s
    layout.add('QUICK_MASK', Rect(right, y, 100 * s, h), 'TOGGLE', label='Quick mask', active=on,
               tip='Paint a temporary mask; the next new layer takes it as its mask')
    return right - 6 * s


def path_strip(layout, x, y, h, color, state):
    s = layout.scale
    layout.add('TOOL_NAME', Rect(x, y, 60 * s, h), 'NOTE', label='Path')
    x += 62 * s
    layout.add('BRUSH_COLOR', Rect(x, y, 30 * s, h), 'SWATCH', color=color, tip='Path color')
    x += 36 * s
    for mode, label, tip in (('RIBBON', 'Ribbon', 'Stroke the brush along a smooth curve through the points'),
                             ('FILLED', 'Filled', 'Fill the shape the points enclose')):
        layout.add('PATH.' + mode, Rect(x, y, 70 * s, h), 'CHIP', label=label, active=state.path_mode == mode, tip=tip)
        x += 74 * s
    layout.add('PATH_APPLY', Rect(x, y, 80 * s, h), 'CHIP', label='Apply', tip='Paint the path', shortcut='Enter')
    x += 84 * s
    layout.add('PATH_BACK', Rect(x, y, 90 * s, h), 'CHIP', label='Remove point', tip='Remove the last point', shortcut='Backspace')
    x += 94 * s
    layout.add('PATH_CLEAR', Rect(x, y, 60 * s, h), 'CHIP', label='Clear', tip='Start the path again')


def poly_strip(layout, x, y, h, color, state):
    s = layout.scale
    layout.add('TOOL_NAME', Rect(x, y, 90 * s, h), 'NOTE', label='Polygon fill')
    x += 92 * s
    layout.add('BRUSH_COLOR', Rect(x, y, 30 * s, h), 'SWATCH', color=color, tip='Fill color')
    x += 36 * s
    for mode, label in POLY_MODES:
        layout.add('POLY.' + mode, Rect(x, y, 78 * s, h), 'CHIP', label=label, active=state.poly_mode == mode, tip=f'Click the model to fill a whole {label.lower()}')
        x += 82 * s
    layout.add('POLY_ERASE', Rect(x, y, 70 * s, h), 'TOGGLE', label='Erase', active=state.poly_erase, tip='Clear the picked polygons instead of filling them')


def tool_strip(layout, zone, tool, brush, data, state):
    s = layout.scale
    size, color = brush
    layout.cards.append((zone, ''))
    h = min(zone.h - 12 * s, 24 * s)
    y = zone.y + (zone.h - h) / 2
    x = zone.x + 12 * s
    right = quick_controls(layout, zone, y, h, data)
    if state.poly_mode:
        poly_strip(layout, x, y, h, color, state)
        return
    if state.path_mode:
        path_strip(layout, x, y, h, color, state)
        return
    label = next((name for key, name, _, _ in TOOLS if key == tool), 'Brush')
    layout.add('TOOL_NAME', Rect(x, y, 60 * s, h), 'NOTE', label=label)
    x += 62 * s
    layout.add('BRUSH_COLOR', Rect(x, y, 30 * s, h), 'SWATCH', color=color, tip='Brush color')
    x += 36 * s
    slider = max(80 * s, min(150 * s, (zone.x + zone.w - x) / 5))
    layout.add('BRUSH_SIZE', Rect(x, y, slider, h), 'SLIDER', label='Size', value=size / MAX_BRUSH_SIZE, text=f'{size} px',
               tip='Brush radius', shortcut='F')
    x += slider + 6 * s
    layout.add('BRUSH_STRENGTH', Rect(x, y, slider, h), 'SLIDER', label='Opacity', value=data.brush_opacity,
               text=f'{data.brush_opacity * 100:.0f}%', tip='Most a single stroke can cover', shortcut='Shift F')
    x += slider + 6 * s
    layout.add('BRUSH_ALPHA', Rect(x, y, h, h), 'SOURCE', icon='ELLIPSE', preview=data.brush_alpha, tip='Brush alpha: pick a stamp shape in the Alphas shelf')
    x += h + 6 * s
    layout.add('BRUSH_CARD', Rect(x, y, 120 * s, h), 'DROPDOWN', label='Brush', text=data.brush_preset,
               tip='Flow, spacing, hardness, lazy mouse, jitter, angle, stroke, pressure, and the channels the brush paints')
    x += 126 * s
    layout.add('SYMMETRY', Rect(x, y, 110 * s, h), 'DROPDOWN', label='Symmetry', text=symmetry_label(data), tip='Mirror and radial symmetry')
    x += 116 * s
    layout.add('STENCIL_CARD', Rect(x, y, h, h), 'SOURCE', icon='GRID', preview=data.brush_stencil, tip='Screen stencil and projection')
    x += h + 6 * s
    for channel in set_channels(data):
        slot = data.brush_slots[channel.key]
        width = (46 if channel.width == 3 else 92) * s
        if channel.key == 'base_color' or not slot.enabled:
            continue
        if x + width > right:
            break
        brush_value_control(layout, channel, slot, Rect(x, y, width, h))
        x += width + 4 * s


def dock_layout(layout, zone, tool, state):
    s = layout.scale
    button, gap = 36 * s, 6 * s
    groups = [[(key, label, shortcut, key) for key, label, _, shortcut in TOOLS], [('POLYFILL', 'Polygon fill', '', 'POLYGON'), ('PATH', 'Path', '', 'RULER')],
              [('UNDO', 'Undo', 'Ctrl Z', 'UNDO'), ('REDO', 'Redo', 'Ctrl Shift Z', 'REDO')]]
    per_row = max(1, int(zone.w // button))
    size = zone.w if per_row == 1 else button
    top, index = zone.top, 0
    for group in groups:
        rows = {}
        for key, label, shortcut, icon in group:
            row, column = divmod(index, per_row)
            rect = Rect(zone.x + column * size, top - (row + 1) * button, size, button)
            index += 1
            if rect.y < zone.y - .5:
                continue
            active = bool(state.poly_mode) if key == 'POLYFILL' else bool(state.path_mode) if key == 'PATH' else key == tool and not (state.poly_mode or state.path_mode)
            layout.add(key, rect, 'TOOL', icon=icon, label=label, active=active, tip=label, shortcut=shortcut)
            rows.setdefault(row, []).append(rect)
        for rects in rows.values():
            layout.tool_groups.append(Rect(rects[0].x, rects[0].y, rects[-1].x + rects[-1].w - rects[0].x, button))
        if per_row == 1:
            top -= index * button + gap
            index = 0


def selection(data):
    layer = active_layer(data)
    if layer.kind == 'INSTANCE':
        return 'INSTANCE'
    if active_effect(data) is not None:
        return 'EFFECT'
    if editing_mask(data):
        return 'MASK'
    return 'FOLDER' if layer.kind == 'FOLDER' else 'LAYER'


def layer_rows(data, collapsed):
    rows = []

    def walk(parent, depth):
        for layer in reversed(children(data.layers, parent)):
            rows.append((layer, depth, None))
            if 'FX_OPEN_' + layer.uid not in collapsed:
                rows.extend((layer, depth + 1, effect) for effect in reversed(layer.effects))
            if layer.kind == 'FOLDER' and 'FOLD_' + layer.uid not in collapsed:
                walk(layer.uid, depth + 1)
    walk('', 0)
    return rows


def layer_preview(layer):
    if layer.kind == 'INSTANCE':
        source = linked_layer(layer)
        return layer_preview(source) if source is not None else None
    if layer.kind == 'PAINT':
        return layer.image
    if layer.kind == 'FILL':
        return thumbnails.material_texture(capture(layer), owner=layer.uid)
    return None


def layer_color(layer):
    if layer.kind == 'INSTANCE':
        layer = linked_layer(layer)
    return slot_display(layer.slots['base_color']) if layer is not None and layer.kind != 'FOLDER' else None


def effect_preview(effect):
    if effect.kind == 'PAINT':
        return effect.image
    if effect.kind == 'FILL' and effect.source == 'IMAGE':
        return effect.texture
    if effect.kind == 'FILL' and effect.source == 'PATTERN':
        return shelf.thumbnail(shelf.Item(effect.pattern, 'PATTERN', effect.pattern))
    return None


def effect_row(flow, state, data, layer, effect, row):
    s = flow.layout.scale
    key = f'{layer.uid}.{effect.uid}'
    preview = effect_preview(effect)
    selected = layer.uid == data.active_uid and data.target == 'EFFECT' and data.active_effect == effect.uid
    flow.add('FX_' + key, row, 'ROW', label=effect_label(effect), text=effect.target.title(), active=selected, second=1.0 if selected else 0.0,
             preview=preview, icon='' if preview is not None else EFFECT_ICONS[effect.kind], color=(.5, .5, .5, 1.0),
             tip='Click to edit this effect, drag to reorder it')
    flow.add('FXEYE_' + key, Rect(row.x + 4 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
             icon='HIDE_OFF' if effect.enabled else 'HIDE_ON', tip='Turn the effect off' if effect.enabled else 'Turn the effect on')


def drop_marker(flow, state, key, row):
    s = flow.layout.scale
    if not state.drop or state.drop[0] != key:
        return
    mode = state.drop[1]
    if mode == 'INTO':
        flow.add('DROP_INTO', Rect(row.x, row.y, 3 * s, row.h), 'SWATCH', color=ACCENT)
        return
    y = row.top - 1 * s if mode == 'ABOVE' else row.y - 1 * s
    flow.add('DROP_LINE', Rect(row.x, y, row.w, 2 * s), 'SWATCH', color=ACCENT)


def fill_layers(layout, state, data, flow):
    s = layout.scale
    target = selection(data)
    size = THUMBNAIL * s
    isolated = isolated_uids(data)
    for layer, depth, effect in layer_rows(data, state.collapsed):
        uid = layer.uid
        line = flow.line(ROW_HEIGHT * s)
        if not flow.visible(line):
            continue
        indent = depth * INDENT * s
        row = Rect(line.x + 2 * s + indent, line.y + 1 * s, line.w - 4 * s - indent, line.h - 2 * s)
        if effect is not None:
            effect_row(flow, state, data, layer, effect, row)
            drop_marker(flow, state, f'FX_{uid}.{effect.uid}', row)
            continue
        selected = uid == data.active_uid or uid in state.multi
        editing = state.text is not None and state.text.key == f'NAME_{uid}'
        flow.add(f'ROW_{uid}', row, 'ROW', label=state.text.text if editing else layer.name, text=f'{layer.opacity * 100:.0f}%',
                 active=selected, second=1.0 if uid == data.active_uid and target in {'LAYER', 'INSTANCE'} else 0.0,
                 preview=layer_preview(layer), mask=layer.mask if layer.kind != 'INSTANCE' else None,
                 icon='LIBRARY' if layer.kind == 'FOLDER' else '', color=layer_color(layer),
                 caret=state.text.cursor if editing else -1,
                 tip='Click to select, Ctrl or Shift-click to select several, drag to reorder, double-click to rename, right-click for more')
        drop_marker(flow, state, f'ROW_{uid}', row)
        if layer.kind == 'INSTANCE':
            flow.add('LINKED_' + uid, Rect(row.x + row.w - 64 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON', icon='INTERNAL',
                     tip=f'Instance of a layer from {layer.link_set}; edits to the source show here')
        if len(layer.effects):
            opened = 'FX_OPEN_' + uid not in state.collapsed
            flow.add('FX_OPEN_' + uid, Rect(row.x + row.w - 90 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                     icon='DOWN' if opened else 'DISCLOSURE', tip='Hide the effects of this layer' if opened else 'Show the effects of this layer')
        shown = (layer.visible or uid == data.isolate) and (isolated is None or uid in isolated)
        flow.add(f'EYE_{uid}', Rect(row.x + 4 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON', icon='HIDE_OFF' if shown else 'HIDE_ON',
                 tip=('Hide layer' if layer.visible else 'Show layer') + '; Alt-click to show only this layer')
        if layer.kind == 'FOLDER':
            folded = 'FOLD_' + uid in state.collapsed
            flow.add('FOLD_' + uid, Rect(row.x + row.w - 64 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                     icon='DISCLOSURE' if folded else 'DOWN', tip='Show the layers in this folder' if folded else 'Hide the layers in this folder')
        if layer.mask is not None:
            flow.add(f'MASKTHUMB_{uid}', Rect(row.x + 34 * s + size, row.y + (row.h - size) / 2, size, size), 'THUMB',
                     preview=layer.mask, active=selected and target == 'MASK',
                     tip='Select the mask to paint and edit it; Alt-click to show the mask in the viewport')


def layers_panel(layout, state, data):
    s = layout.scale
    actions = (('ADD_FOLDER', '+ Folder', 66, 'New folder above the selected layer'),
               ('ADD_FILL', '+ Fill', 52, 'New fill layer above the selected one'),
               ('ADD_PAINT', '+ Paint', 64, 'New paint layer above the selected one'))
    return ColumnPanel('LAYERS', 'Layers', len(layer_rows(data, state.collapsed)) * ROW_HEIGHT * s + 8 * s, fill_layers, 4 * s, actions)


def effects_add_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    half = (w - 4 * s) / 2
    flow.add('ADD_FX_MASK', Rect(x, y, half, h), 'DROPDOWN', text='+ Mask effect', tip='Add paint, fill, levels, filter, compare, or anchor to the mask')
    flow.add('ADD_FX_CONTENT', Rect(x + half + 4 * s, y, half, h), 'DROPDOWN', text='+ Content effect', tip='Add levels or a filter to the layer content')


def geometry_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    flow.add('GEO_MASK', Rect(x, y, TOGGLE_WIDTH * s * 1.4, h), 'TOGGLE', label='Geometry mask', active=layer.geo_mask,
             tip='Limit this layer to the faces or mesh parts you pick')
    if not layer.geo_mask:
        return
    picking = flow.state.geo_pick
    x, y, h = flow.field()
    quarter = (w - 12 * s) / 4
    for index, (key, label, active, tip) in enumerate((('GEO_FACES', 'Faces', picking == 'FACE', 'Click faces on the model to add or remove them'),
                                                       ('GEO_ISLANDS', 'Parts', picking == 'ISLAND', 'Click a connected mesh part to add or remove it'),
                                                       ('GEO_INVERT', 'Invert', False, 'Swap picked and unpicked faces'),
                                                       ('GEO_CLEAR', 'Clear', False, 'Remove every face from the geometry mask'))):
        flow.add(key, Rect(x + index * (quarter + 4 * s), y, quarter, h), 'TOGGLE' if index < 2 else 'CHIP', label=label, active=active, tip=tip)


def geometry_lines(data):
    return 2 if active_layer(data).geo_mask else 1


def folder_blend_section(flow, data, layer, w):
    x, y, h = flow.field()
    flow.add('FOLDER_BLEND', Rect(x, y, w, h), 'DROPDOWN', label='Blend', text=dict(FOLDER_BLENDS)[layer.folder_blend],
             tip='Passthrough mixes children straight into the stack; any other mode merges the folder first, then blends it')


def folder_channels_section(flow, data, layer, w):
    s = flow.layout.scale
    half = (w - 4 * s) / 2
    for channel in set_channels(data):
        x, y, h = flow.field()
        item = layer.channel_blends.get(channel.key)
        flow.add('FOLDER_CHNAME.' + channel.key, Rect(x, y, half, h), 'NOTE', label=channel.label)
        flow.add('FOLDER_CHBLEND.' + channel.key, Rect(x + half + 4 * s, y, half, h), 'DROPDOWN',
                 text=dict(FOLDER_BLENDS)[item.blend] if item is not None else 'Same as folder',
                 tip=f'How {channel.label.lower()} of this folder blends; Same as folder follows the Blend above')


def folder_channel_lines(data):
    return len(set_channels(data))


def instance_section(flow, data, layer, w):
    x, y, h = flow.field()
    source = linked_layer(layer)
    label = f'Instance of {source.name} in {layer.link_set}' if source is not None else 'The source layer is gone'
    flow.add('INSTANCE_INFO', Rect(x, y, w, h), 'NOTE', label=label)


EFFECT_SLIDERS = {'LEVELS': (('in_low', 'In low', 1.0), ('in_high', 'In high', 1.0), ('gamma', 'Gamma', 4.0), ('out_low', 'Out low', 1.0),
                             ('out_high', 'Out high', 1.0)),
                  'FILL': (('scale', 'Scale', 50.0), ('detail', 'Detail', 1.0), ('contrast', 'Contrast', .98)),
                  'ID_COLOR': (('amount', 'Tolerance', 1.0),)}
FILL_TRANSFORM = (('tiling', 'Tiling', 8.0), ('angle', 'Rotation', 360.0), ('offset_u', 'Offset U', 1.0), ('offset_v', 'Offset V', 1.0))
FX_RANGES = {field: (top, floor) for group in (*EFFECT_SLIDERS.values(), *(item.sliders for item in FILTERS), FILL_TRANSFORM,
                                                (('opacity', 'Opacity', 1.0), ('value', 'Value', 1.0)))
             for field, _, top in group for floor in ({'gamma': .05, 'radius': 1.0, 'scale': .1, 'tiling': .1}.get(field, 0.0),)}


def effect_sliders(effect):
    if effect.kind == 'FILTER':
        return FILTER[effect.filter].sliders
    if effect.kind == 'FILL' and effect.source == 'PATTERN':
        return EFFECT_SLIDERS['FILL'] + FILL_TRANSFORM
    if effect.kind == 'FILL' and effect.source == 'IMAGE':
        return FILL_TRANSFORM
    if effect.kind == 'FILL' and effect.source == 'VALUE':
        return (('value', 'Value', 1.0),)
    return EFFECT_SLIDERS.get(effect.kind, ())


def slider_rows(flow, prefix, holder, sliders, w):
    s = flow.layout.scale
    for start in range(0, len(sliders), 2):
        x, y, h = flow.field()
        pair = sliders[start:start + 2]
        width = (w - 4 * s) / 2 if len(pair) == 2 else w
        for index, (field, label, top) in enumerate(pair):
            value = getattr(holder, field)
            flow.add(f'{prefix}{field}', Rect(x + index * (width + 4 * s), y, width, h), 'SLIDER', label=label, value=value / top,
                     text=f'{value:.0f}' if top >= 32 else f'{value:.2f}')


def effect_section(flow, data, layer, w):
    s = flow.layout.scale
    effect = active_effect(data)
    x, y, h = flow.field()
    flow.add('FX_ENABLED', Rect(x, y, TOGGLE_WIDTH * s, h), 'TOGGLE', label='Enabled', active=effect.enabled, tip='Turn this effect on or off')
    flow.add('FX_UP', Rect(x + w - 92 * s, y, 26 * s, h), 'ICON', icon='CHEVRON', tip='Move the effect up')
    flow.add('FX_DOWN', Rect(x + w - 62 * s, y, 26 * s, h), 'ICON', icon='DOWN', tip='Move the effect down')
    flow.add('FX_DELETE', Rect(x + w - 26 * s, y, 26 * s, h), 'ICON', icon='CLOSE', tip='Delete this effect')
    x, y, h = flow.field()
    half = (w - 4 * s) / 2
    if effect.target == 'MASK' and not (effect.kind == 'FILTER' and FILTER[effect.filter].sampling):
        flow.add('FX_BLEND', Rect(x, y, half, h), 'DROPDOWN', label='Blend', text=MASK_BLEND_LABEL[effect.blend],
                 tip='How this effect combines with the mask below it')
    else:
        flow.add('FX_KIND', Rect(x, y, half, h), 'NOTE', label=effect_label(effect))
    flow.add('FX_opacity', Rect(x + half + 4 * s, y, half, h), 'SLIDER', label='Opacity', value=effect.opacity, text=f'{effect.opacity * 100:.0f}%')
    if effect.kind == 'PAINT':
        x, y, h = flow.field()
        flow.add('FX_NOTE', Rect(x, y, w, h), 'NOTE', label='Paint on the model to edit this effect')
    if effect.kind == 'FILL':
        x, y, h = flow.field()
        sources = {'VALUE': 'Value', 'PATTERN': 'Pattern', 'IMAGE': 'Texture'}
        flow.add('FX_SOURCE', Rect(x, y, h, h), 'SOURCE', icon='GRID', preview=effect_preview(effect), tip='Fill with a value, a pattern, or a texture')
        flow.add('FX_SOURCE_NAME', Rect(x + h + 6 * s, y, w - h - 6 * s, h), 'NOTE',
                 label=sources[effect.source] + (' · ' + effect.pattern.title() if effect.source == 'PATTERN' else
                                                  ' · ' + effect.texture.name if effect.source == 'IMAGE' and effect.texture is not None else ''))
        if effect.source != 'VALUE':
            x, y, h = flow.field()
            flow.add('FX_PROJECTION', Rect(x, y, w, h), 'DROPDOWN', label='Projection', text=dict(FILL_PROJECTIONS)[effect.projection],
                     tip='Map the fill by UV or from three sides without seams; Automatic uses UV for textures and object space for patterns')
    if effect.kind == 'LEVELS':
        x, y, h = flow.field()
        width = half if effect.target == 'CONTENT' else w
        if effect.target == 'CONTENT':
            flow.add('FX_COMPONENT', Rect(x, y, half, h), 'DROPDOWN', label='Channel', text=dict(LEVEL_COMPONENTS)[effect.levels_component],
                     tip='Edit the levels of all color channels, or of red, green or blue on its own')
        flow.add('FX_CLAMP', Rect(x + w - width, y, width, h), 'TOGGLE', label='Clamp', active=effect.clamp,
                 tip='Keep values outside the input range at the output limits')
    if effect.kind == 'FILTER':
        x, y, h = flow.field()
        flow.add('FX_FILTER', Rect(x, y, w, h), 'DROPDOWN', label='Filter', text=FILTER[effect.filter].label, tip='Pick the filter')
    if effect.kind in {'COMPARE', 'ANCHOR'}:
        x, y, h = flow.field()
        other = find_layer(data, effect.other)
        width = w if effect.kind == 'COMPARE' else half
        flow.add('FX_OTHER', Rect(x, y, width, h), 'DROPDOWN', label='Layer', text=other.name if other is not None else 'Pick a layer',
                 tip='The layer whose mask is compared' if effect.kind == 'COMPARE' else 'The layer whose result feeds this mask')
        if effect.kind == 'ANCHOR':
            flow.add('FX_CHANNEL', Rect(x + half + 4 * s, y, half, h), 'DROPDOWN', label='Channel', text=CHANNEL[effect.channel].label,
                     tip='Which channel of the anchored result to use')
    if effect.kind == 'ID_COLOR':
        x, y, h = flow.field()
        flow.add('FXCOLOR.color', Rect(x, y, half, h), 'SWATCH', color=(*linear_to_srgb(numpy.array(effect.color)), 1.0), tip='The ID color this mask keeps')
        flow.add('FX_PICK_ID', Rect(x + half + 4 * s, y, half, h), 'CHIP', label='Pick on model',
                 tip='Click the model to pick a color from the baked ID map')
        for index, item in enumerate(effect.id_colors):
            x, y, h = flow.field()
            flow.add(f'FX_ID_COLOR.{index}', Rect(x, y, half, h), 'SWATCH', color=(*linear_to_srgb(numpy.array(item.color)), 1.0),
                     tip='Another ID color this mask keeps')
            flow.add(f'FX_REMOVE_ID.{index}', Rect(x + half + 4 * s, y, half, h), 'CHIP', label='Remove', tip='Stop keeping this ID color')
        x, y, h = flow.field()
        flow.add('FX_ADD_ID', Rect(x, y, w, h), 'CHIP', label='Add color', tip='Click the model to keep one more ID color')
        if 'id' not in data.maps or data.maps['id'].image is None:
            x, y, h = flow.field()
            flow.add('FX_ID_MISSING', Rect(x, y, w - 106 * s, h), 'NOTE', label='Needs the ID map')
            flow.add('OPEN_BAKE', Rect(x + w - 100 * s, y, 100 * s, h), 'CHIP', label='Bake maps', tip='Open the bake card')
    slider_rows(flow, 'FX_', LevelsView(effect) if effect.kind == 'LEVELS' else effect, effect_sliders(effect), w)
    colors = FILTER[effect.filter].colors if effect.kind == 'FILTER' else ()
    if colors:
        x, y, h = flow.field()
        for index, (field, label) in enumerate(colors):
            flow.add(f'FXCOLOR.{field}', Rect(x + index * (half + 4 * s), y, half, h), 'SWATCH', color=(*linear_to_srgb(numpy.array(getattr(effect, field))), 1.0),
                     tip=label)


def effect_lines(data):
    effect = active_effect(data)
    lines = 2 + (effect.kind in {'PAINT', 'FILL', 'FILTER', 'COMPARE', 'ANCHOR', 'LEVELS'}) + (effect.kind == 'FILL' and effect.source != 'VALUE')
    lines += (len(effect_sliders(effect)) + 1) // 2
    if effect.kind == 'ID_COLOR':
        lines += 2 + len(effect.id_colors) + int('id' not in data.maps or data.maps['id'].image is None)
    return lines + int(effect.kind == 'FILTER' and bool(FILTER[effect.filter].colors))


def effect_menu(target):
    return tuple((f'NEW_FX.{target}.{key}', label, False) for key, label, targets in EFFECT_KINDS if target in targets)


def opacity_section(flow, data, layer, w):
    x, y, h = flow.field()
    flow.add('OPACITY', Rect(x, y, w, h), 'SLIDER', label='Opacity', value=layer.opacity, text=f'{layer.opacity * 100:.0f}%')


def value_control(flow, channel, slot, rect, second):
    key = ('B.' if second else '.') + channel.key
    if channel.width == 3:
        flow.add('SWATCH' + key, rect, 'SWATCH', color=slot_display(slot, second), tip=f'{channel.label} of this layer')
    else:
        value = slot.value_b if second else slot.value
        flow.add('VALUE' + key, rect, 'SLIDER', value=value, text=f'{value:.2f}')


def source_preview(slot):
    if slot.source == 'IMAGE':
        return slot.image
    if slot.source == 'PATTERN':
        return shelf.thumbnail(shelf.Item(slot.pattern, 'PATTERN', slot.pattern))
    return None


def pattern_line(flow, channel, slot, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    third = (w - 8 * s) / 3
    for index, (name, label, value, text) in enumerate((('SCALE', 'Scale', to_slider(slot.scale, SCALE_RANGE), f'{slot.scale:.1f}'),
                                                         ('DETAIL', 'Detail', slot.detail, f'{slot.detail:.2f}'),
                                                         ('CONTRAST', 'Contrast', slot.contrast / .98, f'{slot.contrast:.2f}'))):
        flow.add(f'{name}.{channel.key}', Rect(x + index * (third + 4 * s), y, third, h), 'SLIDER', label=label, value=value, text=text)


def channels_section(flow, data, layer, w):
    s = flow.layout.scale
    toggle, blend = TOGGLE_WIDTH * s, BLEND_WIDTH * s
    fill = layer.kind == 'FILL'
    for channel in set_channels(data):
        key, slot = channel.key, layer.slots[channel.key]
        x, y, h = flow.field()
        flow.add('USE.' + key, Rect(x, y, toggle, h), 'TOGGLE', label=channel.label, active=slot.enabled,
                 tip=f'Let this layer affect {channel.label.lower()}')
        left = x + toggle + 6 * s
        if fill:
            flow.add('SOURCE.' + key, Rect(left, y, h, h), 'SOURCE', icon='GRID', preview=source_preview(slot),
                     tip='Use a plain value, a texture, or a pattern')
            left += h + 6 * s
        opacity = CHANNEL_OPACITY_WIDTH * s
        flow.add('CHOPACITY.' + key, Rect(x + w - blend - 4 * s - opacity, y, opacity, h), 'SLIDER', value=slot.opacity,
                 text=f'{slot.opacity * 100:.0f}%', tip=f'Opacity of {channel.label.lower()} on this layer')
        value = Rect(left, y, x + w - blend - opacity - 10 * s - left, h)
        if key == 'base_color' and not fill:
            flow.add('PAINTED', value, 'NOTE', label='Brush color')
        elif slot.source == 'IMAGE' and slot.image is not None:
            flow.add('IMAGE_NAME.' + key, value, 'NOTE', label=slot.image.name if fill else 'Painted')
        elif fill and slot.source == 'PATTERN':
            half = (value.w - 4 * s) / 2
            value_control(flow, channel, slot, Rect(value.x, y, half, h), False)
            value_control(flow, channel, slot, Rect(value.x + half + 4 * s, y, half, h), True)
        else:
            value_control(flow, channel, slot, value, False)
        flow.add('BLEND.' + key, Rect(x + w - blend, y, blend, h), 'DROPDOWN', text=dict(BLEND_MODES)[slot.blend],
                 tip=f'How {channel.label.lower()} mixes with the layers below')
        if fill and slot.source == 'PATTERN':
            pattern_line(flow, channel, slot, w)


def projection_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    half = (w - 4 * s) / 2
    flow.add('PROJECTION', Rect(x, y, half, h), 'DROPDOWN', label='Projection', text=dict((key, label) for key, label, _ in PROJECTIONS)[layer.projection],
             tip='Map textures and patterns by UV or from three sides without seams')
    flow.add('TILING', Rect(x + half + 4 * s, y, half, h), 'SLIDER', label='Tiling', value=to_slider(layer.tiling, TILING_RANGE),
             text=f'{layer.tiling:.2f}x')
    if layer.projection == 'PLANAR':
        x, y, h = flow.field()
        flow.add('PROJ_BEND', Rect(x, y, half, h), 'SLIDER', label='Bend', value=layer.proj_bend, text=f'{layer.proj_bend:.2f}',
                 tip='Wrap the projection around a curved surface')
        flow.add('PROJ_SNAP', Rect(x + half + 4 * s, y, half, h), 'CHIP', label='Snap to surface', tip='Place the projector on the surface under it')
        x, y, h = flow.field()
        flow.add('PROJ_UNWARP', Rect(x, y, w, h), 'CHIP', label='Reset warp', tip='Square the corner handles again')
    if layer.projection in PROJECTORS:
        x, y, h = flow.field()
        flow.add('PROJ_SIZE', Rect(x, y, half, h), 'SLIDER', label='Size', value=to_slider(layer.proj_size, PROJECTOR_RANGE), text=f'{layer.proj_size:.2f}',
                 tip='Size of the projector; drag the corner handle on the model too')
        flow.add('PROJ_SPIN', Rect(x + half + 4 * s, y, half, h), 'SLIDER', label='Spin', value=(math.degrees(layer.proj_rotation[2]) % 360) / 360,
                 text=f'{math.degrees(layer.proj_rotation[2]) % 360:.0f}°', tip='Turn the projection around its axis')
        x, y, h = flow.field()
        flow.add('PROJ_ALIGN', Rect(x, y, half, h), 'CHIP', label='Align to view', tip='Point the projector along the current view')
        flow.add('PROJ_RESET', Rect(x + half + 4 * s, y, half, h), 'CHIP', label='Reset', tip='Center the projector on the mesh again')
    elif layer.projection == 'UV':
        x, y, h = flow.field()
        flow.add('TILE_MATCH', Rect(x, y, w, h), 'TOGGLE', label='Same on every UV tile', active=layer.tile_match,
                 tip='Repeat the fill identically in each UDIM tile')


def material_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    definition = json.loads(layer.material)
    flow.add('MATERIAL_THUMB', Rect(x, y, h, h), 'SOURCE', icon='GRID', preview=thumbnails.material_texture(definition))
    flow.add('MATERIAL_NAME', Rect(x + h + 6 * s, y, w - h - 150 * s, h), 'NOTE', label='Material · ' + definition['name'])
    flow.add('REPLACE_MATERIAL', Rect(x + w - 138 * s, y, 70 * s, h), 'CHIP', label='Replace', tip='Click a material in the shelf to swap it in, keeping the mask')
    flow.add('RESET_MATERIAL', Rect(x + w - 64 * s, y, 64 * s, h), 'CHIP', label='Reset', tip='Restore every channel to the material values')


def layer_mask_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    if layer.mask is None:
        half = (w - 4 * s) / 2
        flow.add('ADD_MASK_WHITE', Rect(x, y, half, h), 'CHIP', label='White mask', tip='Show everything, paint black areas away')
        flow.add('ADD_MASK_BLACK', Rect(x + half + 4 * s, y, half, h), 'CHIP', label='Black mask', tip='Hide everything, paint areas in')
    else:
        flow.add('SELECT_MASK', Rect(x, y, w, h), 'CHIP', label='Edit mask', tip='Select the mask to paint and edit it')


GENERATOR_SLIDERS = (('GEN_LEVEL', 'Level', 'gen_level', 1.0), ('GEN_CONTRAST', 'Contrast', 'gen_contrast', 1.0),
                     ('GEN_NOISE', 'Noise', 'gen_noise', 1.0), ('GEN_SCALE', 'Scale', 'gen_scale', 200.0))


def missing_maps(data, layer):
    return [key for key in GENERATOR[layer.generator].maps if key not in data.maps or data.maps[key].image is None]


def generator_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    label = GENERATOR[layer.generator].label if layer.generator != 'NONE' else 'None'
    flow.add('GENERATOR', Rect(x, y, w, h), 'DROPDOWN', label='Generator', text=label,
             tip='Mask this layer from the baked mesh maps or a procedural pattern: wear, dirt, gradients, surfaces, UV borders, and more')
    if layer.generator == 'NONE':
        return
    missing = missing_maps(data, layer)
    if missing:
        x, y, h = flow.field()
        flow.add('GEN_MISSING', Rect(x, y, w - 106 * s, h), 'NOTE', label=f'Needs the {MESH_MAP[missing[0]].label.lower()} map')
        flow.add('OPEN_BAKE', Rect(x + w - 100 * s, y, 100 * s, h), 'CHIP', label='Bake maps', tip='Open the bake card')
        return
    half = (w - 4 * s) / 2
    for row in range(2):
        x, y, h = flow.field()
        for column, (key, text, field, top) in enumerate(GENERATOR_SLIDERS[row * 2:row * 2 + 2]):
            width = half if row == 0 else (w - 8 * s - 80 * s) / 2
            value = getattr(layer, field)
            flow.add(key, Rect(x + column * (width + 4 * s), y, width, h), 'SLIDER', label=text, value=value / top,
                     text=f'{value:.0f}' if key == 'GEN_SCALE' else f'{value:.2f}')
    flow.add('GEN_INVERT', Rect(x + w - 80 * s, y, 80 * s, h), 'TOGGLE', label='Invert', active=layer.gen_invert, tip='Swap revealed and hidden areas')
    if layer.generator == 'BUILDER':
        x, y, h = flow.field()
        third = (w - 8 * s) / 3
        for column, (key, text, field) in enumerate(BUILDER_SLIDERS):
            value = getattr(layer, field)
            flow.add(key, Rect(x + column * (third + 4 * s), y, third, h), 'SLIDER', label=text, value=value, text=f'{value:.2f}',
                     tip=f'How much {text.lower()} feed the mask')


def generator_lines(data):
    layer = active_layer(data)
    if layer.generator == 'NONE':
        return 1
    if missing_maps(data, layer):
        return 2
    return 4 if layer.generator == 'BUILDER' else 3


def mask_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    flow.add('MASK_INFO', Rect(x, y, w, h), 'NOTE', label='Paint reveals the layer, Erase hides it')
    x, y, h = flow.field()
    flow.add('SELECT_LAYER', Rect(x, y, w - 34 * s, h), 'CHIP', label='Back to layer', tip='Select the layer content')
    flow.add('REMOVE_MASK', Rect(x + w - 26 * s, y, 26 * s, h), 'ICON', icon='CLOSE', tip='Remove mask')


def one_line(data):
    return 1


def two_lines(data):
    return 2


def channel_lines(data):
    layer = active_layer(data)
    return sum(1 + (layer.kind == 'FILL' and layer.slots[channel.key].source == 'PATTERN') for channel in set_channels(data))


def projection_lines(data):
    layer = active_layer(data)
    if not (layer.kind == 'FILL' and uses_coordinates(layer)):
        return 0
    return 5 if layer.projection == 'PLANAR' else 3 if layer.projection in PROJECTORS else 2 if layer.projection == 'UV' else 1


def material_lines(data):
    layer = active_layer(data)
    return int(layer.kind == 'FILL' and bool(layer.material))


PROPERTY_SECTIONS = {'LAYER': (Section(one_line, opacity_section), Section(material_lines, material_section), Section(projection_lines, projection_section),
                               Section(channel_lines, channels_section), Section(one_line, layer_mask_section),
                               Section(generator_lines, generator_section), Section(geometry_lines, geometry_section),
                               Section(one_line, effects_add_section)),
                     'FOLDER': (Section(one_line, opacity_section), Section(one_line, folder_blend_section),
                                Section(folder_channel_lines, folder_channels_section), Section(one_line, layer_mask_section),
                                Section(generator_lines, generator_section), Section(geometry_lines, geometry_section),
                                Section(one_line, effects_add_section)),
                     'MASK': (Section(two_lines, mask_section), Section(generator_lines, generator_section)),
                     'EFFECT': (Section(effect_lines, effect_section), Section(one_line, effects_add_section)),
                     'INSTANCE': (Section(one_line, opacity_section), Section(one_line, instance_section))}


def fill_properties(layout, state, data, flow):
    s = layout.scale
    layer = active_layer(data)
    flow.y -= 4 * s
    flow.state = state
    for section in PROPERTY_SECTIONS[selection(data)]:
        if section.lines(data):
            section.build(flow, data, layer, flow.viewport.w - 24 * s)


def properties_panel(layout, state, data):
    s = layout.scale
    target = selection(data)
    suffix = {'MASK': ' · Mask', 'EFFECT': ' · Effect'}.get(target, '')
    title = 'Properties · ' + active_layer(data).name + suffix
    lines = sum(section.lines(data) for section in PROPERTY_SECTIONS[target])
    return ColumnPanel('PROPERTIES', title, lines * LINE_HEIGHT * s + 16 * s, fill_properties, 12 * s)


def baked_maps(data):
    return [(item, data.maps[item.key].image) for item in MESH_MAPS if item.key in data.maps and data.maps[item.key].image is not None]


def fill_maps(layout, state, data, flow):
    s = layout.scale
    maps = baked_maps(data)
    if not maps:
        x, y, h = flow.field()
        flow.add('MAPS_EMPTY', Rect(x, y, flow.viewport.w - 130 * s, h), 'NOTE', label='No mesh maps yet')
        flow.add('OPEN_BAKE', Rect(x + flow.viewport.w - 124 * s, y, 100 * s, h), 'CHIP', label='Bake maps', tip='Open the bake card')
        return
    tile = MAP_TILE * s
    columns = max(1, int((flow.viewport.w - 2 * flow.pad) // (tile + 6 * s)))
    for index, (item, image) in enumerate(maps):
        row, column = divmod(index, columns)
        rect = Rect(flow.viewport.x + flow.pad + column * (tile + 6 * s), flow.y - (row + 1) * (tile + 20 * s), tile, tile + 16 * s)
        if flow.visible(rect):
            flow.add('MAP.' + item.key, rect, 'TILE', label=item.label, preview=image, tip=f'View the {item.label.lower()} map on the model')


def maps_panel(layout, state, data, width):
    s = layout.scale
    count = len(baked_maps(data))
    columns = max(1, int((width / s - 24) // (MAP_TILE + 6)))
    rows = math.ceil(count / columns) if count else 0
    return ColumnPanel('MAPS', 'Mesh maps', (rows * (MAP_TILE + 20) + 12) * s if rows else (LINE_HEIGHT + 12) * s, fill_maps, 10 * s)


def set_preview(data):
    top = next((layer for layer in reversed(data.layers) if layer.kind != 'FOLDER'), None)
    return layer_preview(top) if top is not None else None


def fill_sets(layout, state, data, flow):
    s = layout.scale
    project = data.id_data.devil_painter
    for index, item in enumerate(project.sets):
        line = flow.line(ROW_HEIGHT * s)
        if not flow.visible(line):
            continue
        row = Rect(line.x + 2 * s, line.y + 1 * s, line.w - 4 * s, line.h - 2 * s)
        count = len(numbers(item))
        flow.add(f'SET.{index}', row, 'ROW', label=item.name, text=f'{item.resolution // 1024}K' + (f' · {count} tiles' if count > 1 else ''),
                 active=index == project.active_set, second=1.0 if index == project.active_set else 0.0, preview=set_preview(item),
                 color=(.2, .2, .2, 1.0), tip='Paint this texture set. Clicking its faces in the viewport selects it too')
        flow.add(f'SETRES.{index}', Rect(row.x + row.w - 112 * s, row.y + 9 * s, 50 * s, row.h - 18 * s), 'DROPDOWN',
                 text=f'{item.resolution // 1024}K', tip='Change the resolution of this texture set')
        flow.add(f'SETEYE.{index}', Rect(row.x + 4 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                 icon='HIDE_OFF' if item.visible else 'HIDE_ON', tip='Disable this texture set' if item.visible else 'Enable this texture set')
    tile_numbers = numbers(data)
    if len(tile_numbers) > 1:
        x, y, h = flow.field()
        width = min(64 * s, (flow.viewport.w - 24 * s) / len(tile_numbers) - 4 * s)
        for column, number in enumerate(tile_numbers):
            flow.add(f'TILE.{number}', Rect(x + column * (width + 4 * s), y, width, h), 'CHIP', label=str(number),
                     active=number == project.active_tile, tip=f'Paint UDIM tile {number}')


def sets_panel(layout, state, data):
    s = layout.scale
    project = data.id_data.devil_painter
    lines = len(project.sets) * ROW_HEIGHT + (LINE_HEIGHT if len(numbers(data)) > 1 else 0)
    return ColumnPanel('SETS', 'Texture sets', (lines + 8) * s, fill_sets, 4 * s)


def tab_rows(zone, s):
    tab_w = max(64 * s, min(76 * s, (zone.w - 46 * s) / len(shelf.TABS) - 4 * s))
    per_row = max(1, int((zone.w - 38 * s) // (tab_w + 4 * s)))
    return tab_w, per_row, math.ceil(len(shelf.TABS) / per_row)


def shelf_header(layout, state, zone, header):
    s = layout.scale
    tab_w, per_row, rows = tab_rows(zone, s)
    for index, (tab, label) in enumerate(shelf.TABS):
        row, column = divmod(index, per_row)
        x = zone.x + 8 * s + column * (tab_w + 4 * s)
        layout.add('SHELF_TAB.' + tab, Rect(x, header.y - row * 26 * s, tab_w, header.h), 'CHIP', label=label,
                   active=state.shelf_open and tab == state.shelf_tab, tip=f'Browse {label.lower()}')
    x = zone.x + 8 * s + len(shelf.TABS) * (tab_w + 4 * s) if rows == 1 else zone.x + zone.w
    toggle = Rect(zone.x + zone.w - 30 * s, header.y, 22 * s, header.h)
    layout.add('SHELF_TOGGLE', toggle, 'ICON', icon='DOWN' if state.shelf_open else 'DISCLOSURE',
               tip='Hide the shelf' if state.shelf_open else 'Show the shelf')
    x += 8 * s
    room = toggle.x - 8 * s - x
    if state.armed:
        label = SHELF_PROMPTS.get(state.armed) or f'Click a texture or pattern for {CHANNEL[state.armed].label.lower()}'
        layout.add('ARM_INFO', Rect(x, header.y, max(0.0, room - 78 * s), header.h), 'NOTE', label=label)
        layout.add('CANCEL_ARM', Rect(toggle.x - 78 * s, header.y, 70 * s, header.h), 'CHIP', label='Cancel', tip='Stop picking', shortcut='Esc')
    elif state.shelf_open and state.shelf_tab == 'TEXTURES' and room > 230 * s:
        editing = state.text is not None and state.text.key == 'TEXTURE_DIR'
        layout.add('TEXTURE_IMPORT', Rect(x, header.y, 70 * s, header.h), 'CHIP', label='Import', tip='Copy image files into your texture library')
        x += 76 * s
        room -= 76 * s
        field = min(360 * s, max(0.0, room - 78 * s))
        layout.add('TEXTURE_DIR', Rect(x, header.y, field, header.h), 'FIELD', text=state.text.text if editing else masked_path(texture_folder()),
                   caret=state.text.cursor if editing else -1, tip='Folder of textures to browse')
        layout.add('TEXTURE_BROWSE', Rect(x + field + 6 * s, header.y, 70 * s, header.h), 'CHIP', label='Browse', tip='Pick a texture folder')


def shelf_query(state):
    return state.text.text if state.text is not None and state.text.key == 'SHELF_SEARCH' else state.shelf_query


def packs_row(layout, zone, viewport):
    s = layout.scale
    y = viewport.top - 26 * s
    opened = packs.open_entry()
    if opened is not None:
        layout.add('PACK_BACK', Rect(zone.x + 8 * s, y, 90 * s, 22 * s), 'CHIP', label='All packs', tip='Back to the list of packs')
        layout.add('PACK_DOWNLOAD', Rect(zone.x + 104 * s, y, 170 * s, 22 * s), 'CHIP', label='Download whole pack',
                   active=packs.installed(opened), tip=f'Download all of {opened["name"]} ({opened.get("size", "")})')
        layout.add('PACKS_INFO', Rect(zone.x + 282 * s, y, zone.w - 296 * s, 22 * s), 'NOTE',
                   label=packs.message() or f'{opened["name"]} · {packs.status(opened)}. Click a file to download only that file.')
        return
    layout.add('PACKS_REFRESH', Rect(zone.x + 8 * s, y, 130 * s, 22 * s), 'CHIP', label='Check for packs',
               tip='Read the list of free packs from the Devil Painter asset library')
    layout.add('PACKS_INFO', Rect(zone.x + 146 * s, y, zone.w - 160 * s, 22 * s), 'NOTE', label=packs.message() or 'Free CC0 packs. Click one to browse it.')


def search_row(layout, state, zone, row):
    s = layout.scale
    x = zone.x + 8 * s
    editing = state.text is not None and state.text.key == 'SHELF_SEARCH'
    query = shelf_query(state)
    narrow = zone.w < SEARCH_SPLIT * s
    width = max(60 * s, zone.w - 120 * s) if narrow else 180 * s
    layout.add('SHELF_SEARCH', Rect(x, row.y, width, row.h), 'FIELD', text=query if query or editing else 'Search',
               caret=state.text.cursor if editing else -1, tip='Type to filter this shelf by name')
    x += width + 6 * s
    if narrow:
        row = Rect(row.x, row.y - 26 * s, row.w, row.h)
        x = zone.x + 8 * s
    for scope, label in shelf.SCOPES:
        layout.add('SCOPE.' + scope, Rect(x, row.y, 62 * s, row.h), 'CHIP', label=label, active=state.shelf_scope == scope,
                   tip={'ALL': 'Show everything', 'BUILTIN': 'Show what ships with Devil Painter', 'MINE': 'Show your saved assets and libraries'}[scope])
        x += 66 * s
    right = zone.x + zone.w - 8 * s - 84 * s
    layout.add('LIBRARIES', Rect(right, row.y + (26 * s if narrow else 0.0), 84 * s, row.h), 'CHIP', label='Libraries', tip='Add library folders and import files')
    if query and state.shelf_query:
        layout.add('SAVE_SEARCH', Rect(x, row.y, 90 * s, row.h), 'CHIP', label='Save search', tip='Keep this search as a chip')
        x += 96 * s
    for index, entry in enumerate(shelf.saved_searches()):
        width = min(120 * s, (len(entry['query']) * 7 + 18) * s)
        if x + width > right - 6 * s:
            break
        if entry['tab'] == state.shelf_tab:
            layout.add(f'SEARCH.{index}', Rect(x, row.y, width, row.h), 'CHIP', label=entry['query'], active=state.shelf_query == entry['query'],
                       tip='Saved search. Right-click to delete')
            x += width + 4 * s


def libraries_popover(layout, state, bounds):
    s = layout.scale
    folders = library_folders()
    card = place_popover(bounds, state.popover.anchor, 420 * s, ((len(folders) + 4) * LINE_HEIGHT + 20) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 10 * s - LINE_HEIGHT * s
    layout.add('LIBRARIES_TITLE', Rect(x, y, w, 24 * s), 'NOTE', label='Library folders: images, texture sets, and .blend materials')
    for index, folder in enumerate(folders):
        y -= LINE_HEIGHT * s
        shown = folder in state.revealed
        layout.add(f'LIBRARY.{index}', Rect(x, y, w - 30 * s, 24 * s), 'NOTE', label=folder if shown else masked_path(folder),
                   tip='Click to hide the full path' if shown else 'Click to show the full path')
        layout.add(f'LIB_REMOVE.{index}', Rect(x + w - 24 * s, y, 24 * s, 24 * s), 'ICON', icon='CLOSE', tip='Stop browsing this folder')
    y -= LINE_HEIGHT * s
    editing = state.text is not None and state.text.key == 'LIBRARY_NEW'
    layout.add('LIBRARY_NEW', Rect(x, y, w - 76 * s, 24 * s), 'FIELD', text=state.text.text if editing else 'Type a folder and press Enter',
               caret=state.text.cursor if editing else -1, tip='Add a folder of images and .blend files to the shelf')
    layout.add('LIBRARY_BROWSE', Rect(x + w - 70 * s, y, 70 * s, 24 * s), 'CHIP', label='Browse', tip='Pick a library folder')
    y -= LINE_HEIGHT * s
    layout.add('IMPORT_RESOURCES', Rect(x, y, w, 24 * s), 'CHIP', label='Import images and .blend files',
               tip='Copy files into your Devil Painter library')
    return card


def drag_ghost(layout, state):
    s = layout.scale
    x, y, label, preview = state.ghost
    layout.add('DRAG_GHOST', Rect(x + 8 * s, y - SHELF_TILE * s - 8 * s, SHELF_TILE * s, (SHELF_TILE + SHELF_LABEL) * s), 'TILE', label=label, preview=preview)


def shelf_layout(layout, state, zone):
    s = layout.scale
    layout.cards.append((zone, ''))
    header = Rect(zone.x, zone.top - 30 * s, zone.w, 22 * s)
    shelf_header(layout, state, zone, header)
    if not state.shelf_open:
        return
    search = Rect(zone.x, header.y - tab_rows(zone, s)[2] * 26 * s - 2 * s, zone.w, 22 * s)
    search_row(layout, state, zone, search)
    lowest = search.y - (26 * s if zone.w < SEARCH_SPLIT * s else 0.0)
    viewport = Rect(zone.x, zone.y + 4 * s, zone.w, max(0.0, lowest - 6 * s - zone.y - 4 * s))
    query = shelf_query(state)
    entries = shelf.visible(state.shelf_tab, query, state.shelf_scope)
    if state.shelf_tab == 'PACKS':
        packs_row(layout, zone, viewport)
        viewport = Rect(viewport.x, viewport.y, viewport.w, max(0.0, viewport.h - 28 * s))
    if not entries and state.shelf_tab == 'PACKS':
        return
    if not entries:
        if query or state.shelf_scope != 'ALL':
            empty = f'Nothing in {dict(shelf.TABS)[state.shelf_tab].lower()} matches this search.'
        else:
            empty = 'Pick a folder of textures to browse them here.' if state.shelf_tab == 'TEXTURES' else 'Save a layer from its right-click menu to see it here.'
        layout.add('SHELF_EMPTY', Rect(zone.x + 16 * s, viewport.top - 30 * s, viewport.w - 32 * s, 22 * s), 'NOTE', label=empty)
        return
    tile_w, tile_h = (SHELF_TILE + SHELF_GAP) * s, (SHELF_TILE + SHELF_LABEL + SHELF_GAP) * s
    columns = max(1, int((viewport.w - 2 * SHELF_GAP * s) // tile_w))
    body = math.ceil(len(entries) / columns) * tile_h + SHELF_GAP * s
    overflow = max(0.0, body - viewport.h)
    scroll = min(max(0.0, state.scroll.get('SHELF', 0.0)), overflow)
    state.scroll['SHELF'] = scroll
    if overflow > 0:
        layout.scroll_areas['SHELF'] = (viewport, overflow)
        layout.add('SCROLL_SHELF', Rect(zone.x + zone.w - 6 * s, viewport.y + 2 * s, 3 * s, viewport.h - 4 * s), 'SCROLLBAR',
                   value=scroll / overflow, second=viewport.h / body)
    first_row = max(0, int((scroll - SHELF_GAP * s) // tile_h))
    rows = int(viewport.h // tile_h) + 2
    for item in entries[(first_row + rows) * columns:(first_row + rows * (PREFETCH_SCREENS + 1)) * columns]:
        shelf.prefetch(item)
    shown = entries[first_row * columns:(first_row + rows) * columns]
    if state.shelf_tab == 'PACKS':
        packs.request_previews([shelf.pack_preview(item) for item in shown])
        packs.focus_previews([shelf.pack_preview(item) for item in shown if not item.preview_file])
    for index, item in enumerate(shown, first_row * columns):
        row, column = divmod(index, columns)
        top = viewport.top + scroll - SHELF_GAP * s - row * tile_h
        rect = Rect(viewport.x + SHELF_GAP * s + column * tile_w, top - tile_h + SHELF_GAP * s, SHELF_TILE * s, tile_h - SHELF_GAP * s)
        if rect.top < viewport.y or rect.y > viewport.top:
            continue
        preview = shelf.thumbnail(item)
        icon = 'FAILED' if preview is None and shelf.failed(item) else ''
        if state.armed == REPLACE_TARGET and item.kind == 'MATERIAL':
            tip = 'Click to put this material into the selected layer'
        elif state.armed == EFFECT_TARGET and item.kind == 'TEXTURE':
            tip = 'Click to fill the selected effect with this texture'
        elif state.armed in CHANNEL and item.kind != 'MATERIAL':
            tip = f'Click to use for {CHANNEL[state.armed].label.lower()}'
        else:
            tip = 'Click to add as a fill layer'
        if item.kind == 'PACK':
            state_text = packs.status(item.payload)
            tip = f'{item.payload.get("description", "")} {state_text}. Click to browse its files. Right-click to remove'
            layout.add(f'ITEM.{index}', rect, 'TILE', label=f'{item.label} · {state_text}', preview=preview, icon=icon, clip=viewport, tip=tip)
            continue
        if item.kind == 'PACKFILE':
            state_text = packs.file_status(*item.payload)
            label = f'{item.label} · {state_text}' if state_text else item.label
            tip = 'Installed: click to use it' if state_text == 'Installed' else 'Click to download only this file'
            layout.add(f'ITEM.{index}', rect, 'TILE', label=label, preview=preview, icon=icon, clip=viewport, tip=tip)
            continue
        if item.kind in SHELF_TIPS:
            tip = SHELF_TIPS[item.kind]
        tip += '. Drag onto the layers to place it'
        if item.kind == 'TEXTURE':
            tip += '. Right-click for more'
        layout.add(f'ITEM.{index}', rect, 'TILE', label=item.label, preview=preview, icon=icon, clip=viewport,
                   tip=tip + ('. Right-click to delete' if item.user_index >= 0 else ''))


def place_popover(bounds, anchor, w, h, s):
    x = min(max(bounds.x + 8 * s, anchor.x), bounds.x + bounds.w - 8 * s - w)
    y = anchor.y - 6 * s - h
    if y < bounds.y + 8 * s:
        y = min(anchor.top + 6 * s, bounds.top - 8 * s - h)
    return Rect(x, y, w, h)


def color_popover(layout, state, bounds):
    s = layout.scale
    card = place_popover(bounds, state.popover.anchor, 232 * s, 282 * s, s)
    hue, saturation, value = state.hsv
    x = card.x + 12 * s
    layout.add('COLOR_SV', Rect(x, card.y + 74 * s, card.w - 24 * s, 166 * s), 'SV', value=saturation, second=value,
               color=hsv_color((hue, 1.0, 1.0)))
    layout.add('COLOR_HUE', Rect(x, card.y + 52 * s, card.w - 24 * s, 14 * s), 'HUE', value=hue)
    layout.add('COLOR_PREVIEW', Rect(x, card.y + 14 * s, 40 * s, 28 * s), 'SWATCH', color=hsv_color(state.hsv))
    editing = state.text is not None and state.text.key == 'COLOR_HEX'
    red, green, blue = colorsys.hsv_to_rgb(*state.hsv)
    hex_text = '#%02X%02X%02X' % tuple(round(channel * 255) for channel in (red, green, blue))
    layout.add('COLOR_HEX', Rect(x + 48 * s, card.y + 16 * s, card.w - 104 * s, 24 * s), 'FIELD',
               text=state.text.text if editing else hex_text, caret=state.text.cursor if editing else -1, tip='Type a hex color')
    layout.add('COLOR_PICK', Rect(card.x + card.w - 46 * s, card.y + 16 * s, 24 * s, 24 * s), 'ICON', icon='EYEDROPPER',
               tip='Pick a color from the model')
    swatch = (card.w - 24 * s - 4 * s * (RECENT_COLORS - 1)) / RECENT_COLORS
    for index, color in enumerate(state.recent_colors[:RECENT_COLORS]):
        layout.add(f'RECENT.{index}', Rect(x + index * (swatch + 4 * s), card.top - 34 * s, swatch, 20 * s), 'SWATCH', color=(*color, 1.0),
                   tip='Recent color')
    return card


def menu_popover(layout, state, bounds):
    s = layout.scale
    items = state.popover.items
    rows = max(1, min(len(items), int((bounds.h - 24 * s) // (MENU_ROW * s))))
    columns = math.ceil(len(items) / rows)
    card = place_popover(bounds, state.popover.anchor, MENU_WIDTH * columns * s, (rows * MENU_ROW + 8) * s, s)
    for index, (key, label, active) in enumerate(items):
        column, row = divmod(index, rows)
        rect = Rect(card.x + (4 + column * MENU_WIDTH) * s, card.top - (4 + (row + 1) * MENU_ROW) * s, (MENU_WIDTH - 8) * s, MENU_ROW * s)
        layout.add(key, rect, 'NOTE' if key.startswith(MENU_HEADING) else 'MENUITEM', label=label, active=active)
    return card


def painting_normal(data):
    return any(channel.key == 'normal' for channel in set_channels(data)) and data.brush_slots['normal'].enabled


def brush_popover(layout, state, bounds, data):
    s = layout.scale
    channels = list(set_channels(data))
    lines = len(BRUSH_SLIDERS) + len(BRUSH_TOGGLES) + len(channels) + 4 + int(painting_normal(data)) + int(bool(data.brush_material))
    card = place_popover(bounds, state.popover.anchor, 300 * s, (lines * LINE_HEIGHT + 20) * s, s)
    x, w = card.x + 12 * s, card.w - 24 * s
    y = card.top - 10 * s
    half = (w - 4 * s) / 2
    for key, label, field, top, tip in BRUSH_SLIDERS:
        y -= LINE_HEIGHT * s
        value = getattr(data, field)
        text = f'{value:.0f}%' if key == 'BRUSH_SPACING' else f'{value:.0f}°' if key == 'BRUSH_ANGLE' else f'{value * 100:.0f}%'
        layout.add(key, Rect(x, y + 2 * s, w, 24 * s), 'SLIDER', label=label, value=value / top, text=text, tip=tip)
    y -= LINE_HEIGHT * s
    layout.add('BRUSH_STROKE', Rect(x, y + 2 * s, half, 24 * s), 'DROPDOWN', label='Stroke', text=STROKE_LABELS[data.brush_stroke],
               tip='Space dabs evenly, draw straight lines, dots, airbrush, or anchored stamps')
    layout.add('SAVE_BRUSH', Rect(x + half + 4 * s, y + 2 * s, half, 24 * s), 'CHIP', label='Save as preset', tip='Add these settings to the brush shelf')
    y -= LINE_HEIGHT * s
    layout.add('BRUSH_DYNAMICS', Rect(x, y + 2 * s, w, 24 * s), 'DROPDOWN', label='Dynamics', text=DYNAMIC_LABELS[data.brush_dynamics],
               tip='Drips that run down the surface, splatter around the stroke, or a width that follows the speed')
    for key, label, field in BRUSH_TOGGLES:
        y -= LINE_HEIGHT * s
        layout.add(key, Rect(x, y + 2 * s, w, 24 * s), 'TOGGLE', label=label, active=getattr(data, field))
    y -= LINE_HEIGHT * s
    layout.add('BRUSH_PAINTS', Rect(x, y + 2 * s, w, 24 * s), 'NOTE', label='Each stroke paints and erases')
    for channel in channels:
        y -= LINE_HEIGHT * s
        slot = data.brush_slots[channel.key]
        base = channel.key == 'base_color'
        tip = 'Erase base color and coverage; when off, Erase only clears the other channels' if base else f'Paint {channel.label.lower()} with every stroke'
        layout.add('BRUSHUSE.' + channel.key, Rect(x, y + 2 * s, 110 * s, 24 * s), 'TOGGLE', label=channel.label, active=slot.enabled, tip=tip)
        if slot.source == 'IMAGE' and slot.image is not None:
            layout.add('BRUSHIMG.' + channel.key, Rect(x + 116 * s, y + 2 * s, w - 116 * s, 24 * s), 'NOTE', label=slot.image.name)
        elif not base:
            brush_value_control(layout, channel, slot, Rect(x + 116 * s, y + 2 * s, w - 116 * s, 24 * s))
    if painting_normal(data):
        y -= LINE_HEIGHT * s
        for column, (key, label, field, top) in enumerate(NORMAL_SLIDERS):
            value = getattr(data, field)
            layout.add(key, Rect(x + column * (half + 4 * s), y + 2 * s, half, 24 * s), 'SLIDER', label=label, value=value / top, text=f'{value:.0f}°',
                       tip='Tilt and direction of the painted normal')
    if data.brush_material:
        y -= LINE_HEIGHT * s
        layout.add('BRUSH_MATERIAL', Rect(x, y + 2 * s, w - 70 * s, 24 * s), 'NOTE', label='Material · ' + data.brush_material)
        layout.add('BRUSH_MATERIAL_CLEAR', Rect(x + w - 64 * s, y + 2 * s, 64 * s, 24 * s), 'CHIP', label='Clear', tip='Paint plain values again')
    return card


def symmetry_label(data):
    axes = [axis for axis, on in zip('XYZ', data.brush_mirror) if on]
    parts = (['Mirror ' + ' '.join(axes)] if axes else []) + ([f'Radial {data.brush_radial}'] if data.brush_radial > 1 else [])
    return ', '.join(parts) or 'Off'


def symmetry_popover(layout, state, bounds, data):
    s = layout.scale
    card = place_popover(bounds, state.popover.anchor, 280 * s, (3 * LINE_HEIGHT + 20) * s, s)
    x, w = card.x + 12 * s, card.w - 24 * s
    y = card.top - 10 * s - LINE_HEIGHT * s
    third = (w - 8 * s) / 3
    for index, axis in enumerate('XYZ'):
        layout.add('MIRROR.' + axis, Rect(x + index * (third + 4 * s), y + 2 * s, third, 24 * s), 'TOGGLE', label='Mirror ' + axis,
                   active=data.brush_mirror[index], tip=f'Mirror strokes across the {axis} axis of the mesh')
    y -= LINE_HEIGHT * s
    layout.add('RADIAL', Rect(x, y + 2 * s, w, 24 * s), 'SLIDER', label='Radial copies', value=(data.brush_radial - 1) / 15, text=str(data.brush_radial),
               tip='Repeat every stroke around the mesh')
    y -= LINE_HEIGHT * s
    for index, axis in enumerate('XYZ'):
        layout.add('RADIAL_AXIS.' + axis, Rect(x + index * (third + 4 * s), y + 2 * s, third, 24 * s), 'CHIP', label='Around ' + axis,
                   active=data.brush_radial_axis == axis, tip=f'Radial copies turn around the {axis} axis')
    return card


def stencil_popover(layout, state, bounds, data):
    s = layout.scale
    lines = 4 + (len(STENCIL_SLIDERS) if data.brush_stencil is not None else 0)
    card = place_popover(bounds, state.popover.anchor, 300 * s, (lines * LINE_HEIGHT + 56) * s, s)
    x, w = card.x + 12 * s, card.w - 24 * s
    y = card.top - 10 * s - LINE_HEIGHT * s
    if data.brush_stencil is None:
        layout.add('STENCIL_NOTE', Rect(x, y + 2 * s, w, 24 * s), 'NOTE', label='Right-click a texture, then Use as stencil')
    else:
        layout.add('STENCIL_THUMB', Rect(x, y - 2 * s, 28 * s, 28 * s), 'SOURCE', icon='GRID', preview=data.brush_stencil)
        layout.add('STENCIL_NAME', Rect(x + 34 * s, y + 2 * s, w - 104 * s, 24 * s), 'NOTE', label=data.brush_stencil.name)
        layout.add('STENCIL_CLEAR', Rect(x + w - 64 * s, y + 2 * s, 64 * s, 24 * s), 'CHIP', label='Remove', tip='Stop painting through the stencil')
        for key, label, field, top in STENCIL_SLIDERS:
            y -= LINE_HEIGHT * s
            value = getattr(data, field)
            text = f'{value:.0f}°' if key == 'STENCIL_ANGLE' else f'{value:.2f}'
            layout.add(key, Rect(x, y + 2 * s, w, 24 * s), 'SLIDER', label=label, value=value / top, text=text)
    y -= LINE_HEIGHT * s
    editing = state.text is not None and state.text.key == 'STENCIL_TEXT'
    layout.add('STENCIL_TEXT', Rect(x, y + 2 * s, w, 24 * s), 'FIELD', text=state.text.text if editing else 'Type text and press Enter',
               caret=state.text.cursor if editing else -1, tip='Turn text into a stencil')
    y -= LINE_HEIGHT * s
    layout.add('STENCIL_FONT', Rect(x, y + 2 * s, w, 24 * s), 'DROPDOWN', label='Font', text=Path(data.stencil_font).stem if data.stencil_font else 'Blender',
               tip='Blender\'s font or one of the system fonts')
    y -= LINE_HEIGHT * s
    layout.add('STENCIL_TIP', Rect(x, y + 2 * s, w, 24 * s), 'NOTE', label='Paint through it, or project it in one click. SVGs are in Textures')
    layout.add('STENCIL_PROJECT', Rect(x, card.y + 12 * s, w, 28 * s), 'PRIMARY', icon='PLAY', label='Project through the view',
               tip='Project the stencil image and the brush channels onto the model as seen from here')
    return card


def bake_popover(layout, state, bounds, data):
    s, sources = layout.scale, state.bake_found
    card = place_popover(bounds, state.popover.anchor, 340 * s, ((len(MESH_MAPS) + 10) * LINE_HEIGHT + 24) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('BAKE_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Bake mesh maps')
    for item in MESH_MAPS:
        y -= LINE_HEIGHT * s
        baked = data.maps[item.key].image if item.key in data.maps else None
        layout.add('BAKEMAP.' + item.key, Rect(x, y, w - 30 * s, 24 * s), 'TOGGLE', label=item.label + (' (needs high-poly)' if item.needs_source else ''),
                   active=item.key in state.bake_keys, tip=BAKE_TIPS.get(item.key, 'Include this map in the bake'))
        layout.add('BAKETHUMB.' + item.key, Rect(x + w - 24 * s, y, 24 * s, 24 * s), 'SOURCE', icon='GRID', preview=baked)
    y -= LINE_HEIGHT * s
    layout.add('BAKE_ID', Rect(x, y, w, 24 * s), 'DROPDOWN', label='ID from', text=BAKE_ID_LABELS[data.bake_id],
               tip='Color the ID map by UV island, material, object, or vertex color')
    y -= LINE_HEIGHT * s
    layout.add('BAKE_SAMPLES', Rect(x, y, w, 24 * s), 'SLIDER', label='Samples', value=data.bake_samples / 128, text=str(data.bake_samples),
               tip='More samples give smoother occlusion and thickness')
    y -= LINE_HEIGHT * s
    layout.add('BAKE_MATCH', Rect(x, y, w, 24 * s), 'TOGGLE', label='Match high-poly and cage by name', active=data.bake_match,
               tip='Use meshes named like this one with _high and _cage, for example Crate_low, Crate_high, Crate_cage')
    y -= LINE_HEIGHT * s
    if data.bake_match:
        names = ', '.join(item.name for item in sources.high) or 'no match'
        layout.add('BAKE_MATCHED', Rect(x, y, w, 24 * s), 'NOTE', label=f'High-poly: {names}')
        y -= LINE_HEIGHT * s
        layout.add('BAKE_MATCHED_CAGE', Rect(x, y, w, 24 * s), 'NOTE', label='Cage: ' + (sources.cage.name if sources.cage else 'none'))
    else:
        layout.add('BAKE_SOURCE', Rect(x, y, w, 24 * s), 'DROPDOWN', label='High-poly', text=data.bake_source.name if data.bake_source else 'None',
                   tip='Bake normal, height, and ID from a detailed mesh onto this one')
        y -= LINE_HEIGHT * s
        layout.add('BAKE_CAGE', Rect(x, y, w, 24 * s), 'DROPDOWN', label='Cage', text=data.bake_cage.name if data.bake_cage else 'None',
                   tip='A copy of this mesh pushed out over the high-poly to control where rays start')
    y -= LINE_HEIGHT * s
    layout.add('BAKE_EXTRUSION', Rect(x, y, w, 24 * s), 'SLIDER', label='Ray distance', value=data.bake_extrusion / .5,
               text=f'{data.bake_extrusion * 100:.1f}%', tip='How far above and below this mesh to search for the high-poly, as a share of its size')
    y -= LINE_HEIGHT * s
    quarter = (w - 12 * s) / 4
    for index, (kind, label, tip) in enumerate((('CAGE', 'Paint cage', 'Paint how far rays reach per pixel'),
                                                ('SKEW', 'Paint skew', 'Paint where rays go straight down the face'))):
        image = data.cage_map if kind == 'CAGE' else data.skew_map
        left = x + index * 2 * (quarter + 4 * s)
        layout.add('BAKE_PAINT.' + kind, Rect(left, y, quarter, 24 * s), 'TOGGLE', label=label, active=data.bake_paint == kind, tip=tip)
        layout.add('BAKE_UNPAINT.' + kind, Rect(left + quarter + 4 * s, y, quarter, 24 * s), 'CHIP', label='Clear' if image is not None else 'Unused',
                   tip=f'Remove the painted {kind.lower()} map')
    y -= LINE_HEIGHT * s
    layout.add('BAKE_AUTO', Rect(x, y, w, 24 * s), 'TOGGLE', label='Rebake automatically', active=data.bake_auto,
               tip='Rebake the baked maps when these settings, the high-poly, the cage, or this mesh change')
    layout.add('BAKE_RUN', Rect(x, card.y + 12 * s, w, 28 * s), 'PRIMARY', icon='PLAY', label='Bake', tip='Bake the selected maps now')
    return card


EXPORT_WIDTH = 600
SOURCE_CELL = 74


def output_row(layout, x, y, w, index, item, editable, s):
    h = 24 * s
    if editable:
        layout.add(f'OUT_NAME.{index}', Rect(x, y, 120 * s, h), 'FIELD', text=item['name'], tip='Output name, used by the {output} token')
    else:
        layout.add(f'OUT_LABEL.{index}', Rect(x, y, 120 * s, h), 'NOTE', label=item['name'])
    cell_x = x + 124 * s
    for slot in range(4):
        rect = Rect(cell_x + slot * (SOURCE_CELL + 2) * s, y, SOURCE_CELL * s, h)
        text = SOURCES[item['sources'][slot]][0] if slot < len(item['sources']) else '-'
        if editable:
            layout.add(f'OUT_SRC.{index}.{slot}', rect, 'DROPDOWN', text=text, tip='RGBA'[slot] + ' channel of this file')
        else:
            layout.add(f'OUT_CELL.{index}.{slot}', rect, 'NOTE', label=text)
    tail = cell_x + 4 * (SOURCE_CELL + 2) * s + 4 * s
    if editable:
        layout.add(f'OUT_FORMAT.{index}', Rect(tail, y, 56 * s, h), 'DROPDOWN', text=FORMAT_LABELS[item['format']], tip='File format')
        layout.add(f'OUT_DEPTH.{index}', Rect(tail + 60 * s, y, 44 * s, h), 'DROPDOWN', text=item['depth'], tip='Bits per channel')
        layout.add(f'OUT_REMOVE.{index}', Rect(x + w - 20 * s, y, 20 * s, h), 'ICON', icon='CLOSE', tip='Remove this output')
    else:
        layout.add(f'OUT_INFO.{index}', Rect(tail, y, w - (tail - x), h), 'NOTE', label=f'{FORMAT_LABELS[item["format"]]} {item["depth"]}')


def size_label(size):
    return f'{size} px' if size else 'Set size'


def padding_label(padding):
    return 'Infinite' if padding < 0 else f'{padding} px'


def project_popover(layout, state, bounds, data):
    s = layout.scale
    project = data.id_data.devil_painter
    card = place_popover(bounds, state.popover.anchor, 420 * s, (16 * LINE_HEIGHT + 30) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('PROJECT_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Project · ' + project.template)
    y -= LINE_HEIGHT * s
    layout.add('PNF_LABEL', Rect(x, y, 110 * s, 24 * s), 'NOTE', label='Normal map')
    chip_row(layout, 'PNF', [(key, label) for key, label, _ in NORMAL_FORMATS], project.normal_format, x + 114 * s, y, w - 114 * s, s,
             'Green channel convention used by the normal channel and exports')
    y -= LINE_HEIGHT * s
    layout.add('PNS_LABEL', Rect(x, y, 110 * s, 24 * s), 'NOTE', label='Tangent mode')
    chip_row(layout, 'PNS', [(key, label) for key, label, _ in NORMAL_SPACES], project.normal_space, x + 114 * s, y, w - 114 * s, s,
             'Space the normal channel is painted in')
    y -= LINE_HEIGHT * s
    layout.add('PHYS_USE', Rect(x, y, 200 * s, 24 * s), 'TOGGLE', label='Real-world scale', active=project.use_physical,
               tip='Tri-planar fills keep their size in meters whatever the object scale')
    layout.add('PHYS_SIZE', Rect(x + 206 * s, y, w - 206 * s, 24 * s), 'SLIDER', label='Tile', value=project.physical_size / 10,
               text=f'{project.physical_size:.2f} m', tip='Meters covered by one repeat of a tri-planar fill')
    y -= LINE_HEIGHT * s
    layout.add('SHADER_LABEL', Rect(x, y, w, 22 * s), 'NOTE', label='Shader · ' + data.name)
    y -= LINE_HEIGHT * s
    chip_row(layout, 'SHADER', [(key, label) for key, label, _ in SHADERS], data.shader, x, y, w, s, 'Viewport shader of this texture set')
    for key, label, field, top in SHADER_SLIDERS:
        y -= LINE_HEIGHT * s
        value = getattr(data, field)
        layout.add(key, Rect(x, y, w, 24 * s), 'SLIDER', label=label, value=value / top, text=f'{value:.2f}')
    y -= LINE_HEIGHT * s
    chip_row(layout, 'TRANSP', [(key, label) for key, label, _ in TRANSPARENCY], data.transparency, x, y, w - 126 * s, s,
             'Order independent transparency never sorts badly; blended is smoother for thin glass')
    layout.add('TRANSP_OVERLAP', Rect(x + w - 120 * s, y, 120 * s, 24 * s), 'TOGGLE', label='Overlap', active=data.transparency_overlap,
               tip='Let blended surfaces of this set show through each other')
    y -= LINE_HEIGHT * s
    minutes = autosave.minutes()
    layout.add('AUTOSAVE', Rect(x, y, 120 * s, 24 * s), 'TOGGLE', label='Autosave', active=bool(minutes),
               tip='Save a copy of the file with every painted image packed, in the background')
    layout.add('AUTOSAVE_MINUTES', Rect(x + 126 * s, y, w - 126 * s, 24 * s), 'SLIDER', label='Every',
               value=(max(minutes, 1) - autosave.MINUTE_RANGE[0]) / (autosave.MINUTE_RANGE[1] - autosave.MINUTE_RANGE[0]), text=f'{max(minutes, 1)} min')
    y -= LINE_HEIGHT * s
    layout.add('AUTOSAVE_INFO', Rect(x, y, w, 24 * s), 'NOTE', label=autosave.status())
    y -= LINE_HEIGHT * s
    layout.add('CROSS_TILES', Rect(x, y, w, 24 * s), 'TOGGLE', label='Strokes cross UV tiles', active=project.cross_tiles,
               tip='Paint one stroke across UDIM tiles; it shows when you release the mouse. Off, strokes stay in their tile and show live')
    y -= LINE_HEIGHT * s
    half = (w - 4 * s) / 2
    layout.add('REIMPORT', Rect(x, y, half, 24 * s), 'CHIP', label='Reimport from file', tip='Swap in an updated mesh file and keep the layers')
    layout.add('REIMPORT_OBJECT', Rect(x + half + 4 * s, y, half, 24 * s), 'DROPDOWN', label='From object', text='Pick',
               tip='Swap in the mesh of another object in the scene and keep the layers')
    y -= LINE_HEIGHT * s
    layout.add('OPEN_SHORTCUTS', Rect(x, y, w, 24 * s), 'CHIP', label='Shortcuts', tip='Change the Devil Painter keys')
    return card


def viewport_popover(layout, state, bounds, shading, lens, ortho, view, project, cycles):
    s = layout.scale
    lines = 13 + (len(POST_SLIDERS) if project.post_enabled else 0)
    card = place_popover(bounds, state.popover.anchor, 360 * s, (lines * LINE_HEIGHT + 30) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('VIEWPORT_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Viewport')
    y -= LINE_HEIGHT * s
    layout.add('ENV', Rect(x, y, w, 24 * s), 'DROPDOWN', label='Environment', text=shading.studio_light.rsplit('.', 1)[0],
               tip='HDRI that lights the material preview')
    y -= LINE_HEIGHT * s
    rotation = (shading.studiolight_rotate_z + math.pi) / (2 * math.pi)
    layout.add('ENV_ROTATION', Rect(x, y, w, 24 * s), 'SLIDER', label='Rotation', value=rotation, text=f'{math.degrees(shading.studiolight_rotate_z):.0f}°')
    y -= LINE_HEIGHT * s
    layout.add('ENV_STRENGTH', Rect(x, y, w, 24 * s), 'SLIDER', label='Strength', value=shading.studiolight_intensity / 2,
               text=f'{shading.studiolight_intensity:.2f}')
    y -= LINE_HEIGHT * s
    layout.add('ENV_BACKGROUND', Rect(x, y, w, 24 * s), 'TOGGLE', label='Show the environment as background', active=shading.studiolight_background_alpha > .5)
    y -= LINE_HEIGHT * s
    low, high = FOV_RANGE
    layout.add('CAMERA_FOV', Rect(x, y, w, 24 * s), 'SLIDER', label='Lens', value=(lens - low) / (high - low), text=f'{lens:.0f} mm',
               tip='Field of view of the viewport camera')
    y -= LINE_HEIGHT * s
    layout.add('CAMERA_ORTHO', Rect(x, y, w, 24 * s), 'TOGGLE', label='Orthographic', active=ortho, tip='Switch between perspective and orthographic')
    y -= LINE_HEIGHT * s
    layout.add('CM_VIEW', Rect(x, y, w, 24 * s), 'DROPDOWN', label='View transform', text=view.view_transform,
               tip='How the viewport maps scene light to the display. Exports always keep the raw texture values')
    y -= LINE_HEIGHT * s
    layout.add('CM_LOOK', Rect(x, y, w, 24 * s), 'DROPDOWN', label='Look', text=view.look.replace(f'{view.view_transform} - ', '') or 'None',
               tip='Contrast look applied on top of the view transform')
    y -= LINE_HEIGHT * s
    layout.add('CM_EXPOSURE', Rect(x, y, w, 24 * s), 'SLIDER', label='Exposure', value=(view.exposure - EXPOSURE_RANGE[0]) / (EXPOSURE_RANGE[1] - EXPOSURE_RANGE[0]),
               text=f'{view.exposure:+.2f}')
    y -= LINE_HEIGHT * s
    layout.add('CM_GAMMA', Rect(x, y, w, 24 * s), 'SLIDER', label='Gamma', value=(view.gamma - GAMMA_RANGE[0]) / (GAMMA_RANGE[1] - GAMMA_RANGE[0]),
               text=f'{view.gamma:.2f}')
    y -= LINE_HEIGHT * s
    half = (w - 4 * s) / 2
    layout.add('PATH_TRACED', Rect(x, y, half, 24 * s), 'TOGGLE', label='Path traced', active=shading.type == 'RENDERED',
               tip='Preview the final look with Cycles; painting keeps working')
    layout.add('PREVIEW_SAMPLES', Rect(x + half + 4 * s, y, half, 24 * s), 'SLIDER', label='Samples', value=cycles.preview_samples / SAMPLE_TOP,
               text=str(cycles.preview_samples), tip='Samples the path-traced preview converges to')
    y -= LINE_HEIGHT * s
    layout.add('POST', Rect(x, y, w, 24 * s), 'TOGGLE', label='Post effects', active=project.post_enabled,
               tip='Bloom, vignette, color fringe, saturation, and contrast in the viewport only')
    if project.post_enabled:
        for key, label, field, top in POST_SLIDERS:
            y -= LINE_HEIGHT * s
            value = getattr(project, field)
            layout.add(key, Rect(x, y, w, 24 * s), 'SLIDER', label=label, value=value / top, text=f'{value:.2f}')
    return card


def channels_popover(layout, state, bounds, data):
    s = layout.scale
    choices = [channel for channel in CHANNELS if channel.key != 'base_color']
    card = place_popover(bounds, state.popover.anchor, 300 * s, ((len(choices) + 2) * LINE_HEIGHT + 30) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('CHANNELS_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Channels · ' + data.name)
    for channel in choices:
        y -= LINE_HEIGHT * s
        layout.add('CHANSET.' + channel.key, Rect(x, y, w, 24 * s), 'TOGGLE', label=channel.label + ('' if channel.in_shader else '  (export only)'),
                   active=channel.key in data.channels and data.channels[channel.key].enabled)
    y -= LINE_HEIGHT * s
    layout.add('CHANNELS_ALL', Rect(x, y, w, 24 * s), 'TOGGLE', label='Apply to every texture set', active=state.channels_all,
               tip='Add or remove channels in all texture sets at once')
    return card


def shortcuts_popover(layout, state, bounds):
    s = layout.scale
    card = place_popover(bounds, state.popover.anchor, 340 * s, (len(ACTIONS) * LINE_HEIGHT + 60) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('SHORTCUTS_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Click a key, then press the new key. Esc clears it.')
    keys = bindings()
    for action, label, _ in ACTIONS:
        y -= LINE_HEIGHT * s
        layout.add('SHORTCUT_LABEL.' + action, Rect(x, y, w - 100 * s, 24 * s), 'NOTE', label=label)
        layout.add('BIND.' + action, Rect(x + w - 94 * s, y, 94 * s, 24 * s), 'CHIP', label='Press a key' if state.binding == action else key_label(keys[action]),
                   active=state.binding == action)
    return card


def export_popover(layout, state, bounds, data, directory):
    s = layout.scale
    project = data.id_data.devil_painter
    template = find_template(project.export_template)
    editable = is_custom(template['name'])
    lines = len(template['outputs']) + len(project.sets) + 8 + (1 if editable else 0)
    card = place_popover(bounds, state.popover.anchor, EXPORT_WIDTH * s, (lines * LINE_HEIGHT + 40) * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    y = card.top - 34 * s
    layout.add('EXPORT_TITLE', Rect(x, y, w, 22 * s), 'NOTE', label='Export textures')
    y -= LINE_HEIGHT * s
    layout.add('EXPORT_TEMPLATE', Rect(x, y, w - 190 * s, 24 * s), 'DROPDOWN', label='Template', text=template['name'],
               tip='Which files to write and how channels pack into them')
    layout.add('TEMPLATE_DUPLICATE', Rect(x + w - 184 * s, y, 120 * s, 24 * s), 'CHIP', label='Copy to custom', tip='Make an editable copy of this template')
    if editable:
        layout.add('TEMPLATE_DELETE', Rect(x + w - 58 * s, y, 58 * s, 24 * s), 'CHIP', label='Delete', tip='Delete this custom template')
    for index, item in enumerate(template['outputs']):
        y -= LINE_HEIGHT * s
        output_row(layout, x, y, w, index, item, editable, s)
    if editable:
        y -= LINE_HEIGHT * s
        layout.add('OUT_ADD', Rect(x, y, 120 * s, 24 * s), 'CHIP', label='+ Output', tip='Add a file to this template')
    for index, item in enumerate(project.sets):
        y -= LINE_HEIGHT * s
        count = len(numbers(item))
        layout.add(f'EXPORT_SET.{index}', Rect(x, y, w, 24 * s), 'TOGGLE', active=item.export,
                   label=f'{item.name}  ·  {item.resolution} px' + (f'  ·  {count} UDIM tiles' if count > 1 else ''), tip='Export this texture set')
    y -= LINE_HEIGHT * s
    depth = 'From template' if project.export_depth == 'TEMPLATE' else project.export_depth + '-bit'
    third = (w - 8 * s) / 3
    layout.add('EXPORT_DEPTH', Rect(x, y, third, 24 * s), 'DROPDOWN', label='Depth', text=depth,
               tip='Override the bit depth; formats that cannot hold it use their closest depth')
    layout.add('EXPORT_SIZE', Rect(x + third + 4 * s, y, third, 24 * s), 'DROPDOWN', label='Size', text=size_label(project.export_size),
               tip='Write every file at this size, or at each texture set resolution')
    layout.add('EXPORT_PADDING', Rect(x + 2 * (third + 4 * s), y, third, 24 * s), 'DROPDOWN', label='Padding', text=padding_label(project.export_padding),
               tip='How far colors bleed past the UV islands')
    y -= LINE_HEIGHT * s
    editing = state.text is not None and state.text.key == 'EXPORT_PATTERN'
    layout.add('EXPORT_PATTERN', Rect(x, y, w, 24 * s), 'FIELD', text=state.text.text if editing else project.export_pattern,
               caret=state.text.cursor if editing else -1, tip='File names. Tokens: ' + ' '.join(TOKENS))
    y -= LINE_HEIGHT * s
    editing = state.text is not None and state.text.key == 'EXPORT_DIR'
    layout.add('EXPORT_DIR', Rect(x, y, w - 76 * s, 24 * s), 'FIELD', text=state.text.text if editing else masked_path(directory),
               caret=state.text.cursor if editing else -1, tip='Folder for the textures')
    layout.add('BROWSE', Rect(x + w - 70 * s, y, 70 * s, 24 * s), 'CHIP', label='Browse', tip='Pick a folder')
    y -= LINE_HEIGHT * s
    editing = state.text is not None and state.text.key == 'BRIDGE_COMMAND'
    bridge_text = bridge_command()
    layout.add('BRIDGE_COMMAND', Rect(x, y, w - 196 * s, 24 * s), 'FIELD',
               text=state.text.text if editing else masked(bridge_text) or 'Optional app to send to, with {files} or {folder}',
               caret=state.text.cursor if editing else -1, tip='Command of another app; {files} becomes the exported files, {folder} the folder')
    layout.add('SEND', Rect(x + w - 190 * s, y, 92 * s, 24 * s), 'CHIP', label='Export & send', tip='Export, then open the textures in that app')
    layout.add('OPEN_FOLDER', Rect(x + w - 94 * s, y, 94 * s, 24 * s), 'CHIP', label='Open folder', tip='Show the export folder')
    layout.add('EXPORT_RUN', Rect(x, card.y + 12 * s, w, 28 * s), 'PRIMARY', icon='SAVE', label='Export', tip='Bake and write the textures now')
    return card


def path_layout(layout, points, closed):
    s = layout.scale
    handle = GIZMO_HANDLE * s * .7
    loop = points + points[:1] if closed and len(points) > 2 else points
    segments = tuple(spot for first, second in zip(loop, loop[1:]) for spot in (first, second))
    for index, (x, y) in enumerate(points):
        layout.add(f'PATH_POINT.{index}', Rect(x - handle, y - handle, handle * 2, handle * 2), 'GIZMO', points=segments if index == 0 else (),
                   tip='Drag to move this point')


def gizmo_layout(layout, gizmo):
    s = layout.scale
    lines, center, corner, pins = gizmo
    handle = GIZMO_HANDLE * s
    for index, (x, y) in enumerate(pins):
        layout.add(f'GIZMO_PIN.{index}', Rect(x - handle * .7, y - handle * .7, handle * 1.4, handle * 1.4), 'GIZMO', tip='Drag to warp this corner')
    layout.add('GIZMO_MOVE', Rect(center[0] - handle, center[1] - handle, handle * 2, handle * 2), 'GIZMO', points=lines,
               tip='Drag to move the projection')
    layout.add('GIZMO_SIZE', Rect(corner[0] - handle, corner[1] - handle, handle * 2, handle * 2), 'GIZMO', tip='Drag to resize the projection')


SECTION_NAMES = dict(BAR='workspace bar', STRIP='tool strip', DOCK='tool dock', SHELF='asset browser', SETS='Texture sets panel',
                     LAYERS='Layers panel', PROPERTIES='Properties panel', MAPS='Mesh maps panel')


def shown_sections(data):
    return {key for key in SECTIONS if key != 'PROPERTIES' or data.layers}


def section_controls(layout, state, key, rect, side, tail):
    s = layout.scale
    if side in COLUMNS:
        if flexible(key, state.collapsed, state.shelf_open) and not tail:
            layout.add('SIZE.' + key, Rect(rect.x, rect.y - 6 * s, rect.w, 6 * s), 'GRIP', tip=f'Drag to resize the {SECTION_NAMES[key]}')
    elif not tail:
        layout.add('SIZE.' + key, Rect(rect.x + rect.w, rect.y, 6 * s, rect.h), 'GRIP', tip=f'Drag to resize the {SECTION_NAMES[key]}')


def strip_grip(side, rect, s):
    return dict(LEFT=Rect(rect.x + rect.w, rect.y, 6 * s, rect.h), RIGHT=Rect(rect.x - 6 * s, rect.y, 6 * s, rect.h),
                TOP=Rect(rect.x, rect.y - 6 * s, rect.w, 6 * s), BOTTOM=Rect(rect.x, rect.top, rect.w, 6 * s))[side]


def sections_layout(layout, state, data, bounds, obj_name, tool, brush):
    s, found = layout.scale, layout.zones
    builders = dict(SETS=sets_panel, LAYERS=layers_panel, PROPERTIES=properties_panel)
    for key, rect in found.rects.items():
        if key == 'BAR':
            workspace_bar(layout, rect, data, obj_name, state.view_2d)
        elif key == 'STRIP':
            tool_strip(layout, rect, tool, brush, data, state)
        elif key == 'DOCK':
            dock_layout(layout, rect, tool, state)
        elif key == 'SHELF':
            shelf_layout(layout, state, rect)
        else:
            spec = maps_panel(layout, state, data, rect.w) if key == 'MAPS' else builders[key](layout, state, data)
            view = max(0.0, rect.h - HEADER * s)
            card, viewport, scroll = panel(layout, state, spec, rect.x, rect.top, rect.w, view)
            if view > 0:
                spec.fill(layout, state, data, Flow(layout, viewport, scroll, spec.pad))
        section_controls(layout, state, key, rect, found.places[key][0], key in found.tails)
    for side, index, rect in found.strips:
        layout.add(f'STRIP.{side}.{index}', strip_grip(side, rect, s), 'GRIP', tip='Drag to resize this column' if side in COLUMNS else 'Drag to resize this row')
    if state.drop and state.drop[0] == 'SECTION':
        moved = arrange(bounds, s, state.drop[2], state.section_heights, state.section_widths, shown_sections(data), state.collapsed, state.shelf_open)
        if state.drop[1] in moved.rects:
            layout.add('SECTION_GHOST', moved.rects[state.drop[1]], 'GHOST')


def painter_layout(bounds, scale, state, data, obj_name, tool, brush, directory, setup, viewport):
    shown = shown_sections(data) if data is not None else set(SECTIONS)
    layout = Layout(scale, MinimalMetrics.resolve(), arrange(bounds, scale, state.strips, state.section_heights, state.section_widths, shown,
                                                              state.collapsed, state.shelf_open))
    if data is not None and state.gizmo:
        gizmo_layout(layout, state.gizmo)
    if data is not None and state.path_mode and state.path_points:
        path_layout(layout, state.path_points, state.path_mode == 'FILLED')
    if data is None:
        start_layout(layout, state, bounds, obj_name, setup)
    else:
        sections_layout(layout, state, data, bounds, obj_name, tool, brush)
    if state.ghost:
        drag_ghost(layout, state)
    if state.popover is not None:
        layout.popover_start = len(layout.controls)
        if state.popover.kind == 'COLOR':
            layout.popover = color_popover(layout, state, bounds)
        elif state.popover.kind == 'MENU':
            layout.popover = menu_popover(layout, state, bounds)
        elif state.popover.kind == 'PROJECT' and data is not None:
            layout.popover = project_popover(layout, state, bounds, data)
        elif state.popover.kind == 'VIEWPORT' and data is not None:
            layout.popover = viewport_popover(layout, state, bounds, *viewport)
        elif state.popover.kind == 'CHANNELS' and data is not None:
            layout.popover = channels_popover(layout, state, bounds, data)
        elif state.popover.kind == 'SHORTCUTS':
            layout.popover = shortcuts_popover(layout, state, bounds)
        elif state.popover.kind == 'BAKE' and data is not None:
            layout.popover = bake_popover(layout, state, bounds, data)
        elif state.popover.kind == 'LIBRARIES':
            layout.popover = libraries_popover(layout, state, bounds)
        elif state.popover.kind == 'SYMMETRY' and data is not None:
            layout.popover = symmetry_popover(layout, state, bounds, data)
        elif state.popover.kind == 'STENCIL' and data is not None:
            layout.popover = stencil_popover(layout, state, bounds, data)
        elif state.popover.kind == 'BRUSH' and data is not None:
            layout.popover = brush_popover(layout, state, bounds, data)
        elif data is not None:
            layout.popover = export_popover(layout, state, bounds, data, directory)
    return layout
