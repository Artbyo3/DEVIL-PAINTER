import colorsys
from dataclasses import dataclass
import json
import math
import numpy
from . import shelf, thumbnails
from .blending import BLEND_MODES, CHANNEL, linear_to_srgb
from .canvas import Layout, Rect
from .document import PROJECTIONS, RESOLUTIONS, active_layer, children, editing_mask, set_channels, slot_value, uses_coordinates
from .library import capture, texture_folder
from .painting import TOOLS
from .shell import GAP, distribute, zones
from .ui_system import MinimalMetrics

MAX_BRUSH_SIZE = 500
HEADER = 30
ROW_HEIGHT = 42
LINE_HEIGHT = 28
THUMBNAIL = 32
INDENT = 14
CHANNEL_OPACITY_WIDTH = 44
BLEND_WIDTH = 78
TOGGLE_WIDTH = 100
BAR_MENU_WIDTH = 150
SHELF_TILE = 72
SHELF_LABEL = 18
SHELF_GAP = 8
REPLACE_TARGET = '@material'
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
    layout.add('PANEL_' + spec.key, header, 'HEADER', label=spec.title, active=not collapsed, tip='Collapse' if not collapsed else 'Expand')
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


def start_layout(layout, bounds, obj_name, resolution):
    s = layout.scale
    w, h = 320 * s, 176 * s
    card = Rect(bounds.x + (bounds.w - w) / 2, bounds.y + (bounds.h - h) / 2, w, h)
    layout.cards.append((card, 'Devil Painter'))
    layout.add('CLOSE', Rect(card.x + card.w - 32 * s, card.y + card.h - 32 * s, 24 * s, 24 * s), 'ICON', icon='CLOSE',
               tip='Close', shortcut='Ctrl Alt P')
    layout.add('TARGET', Rect(card.x + 14 * s, card.y + card.h - 70 * s, card.w - 28 * s, 22 * s), 'NOTE',
               label=obj_name or 'Select a mesh object to paint.')
    chip_w = (card.w - 28 * s - 8 * s) / len(RESOLUTIONS)
    for index, size in enumerate(RESOLUTIONS):
        layout.add(f'RES_{size}', Rect(card.x + 14 * s + index * (chip_w + 4 * s), card.y + 58 * s, chip_w, 24 * s), 'CHIP',
                   label=f'{size // 1024}K', active=size == resolution, tip=f'{size} x {size} textures')
    layout.add('START', Rect(card.x + 14 * s, card.y + 14 * s, card.w - 28 * s, 30 * s), 'PRIMARY', icon='PAINT',
               label='Start painting', tip='Create a layer stack for this mesh')


def workspace_bar(layout, zone, data, obj_name):
    s = layout.scale
    layout.cards.append((zone, ''))
    y, h = zone.y + 6 * s, zone.h - 12 * s
    right = zone.x + zone.w - 8 * s
    layout.add('CLOSE', Rect(right - 24 * s, y, 24 * s, h), 'ICON', icon='CLOSE', tip='Close Devil Painter', shortcut='Ctrl Alt P')
    export = Rect(right - 186 * s, y, 150 * s, h)
    layout.add('EXPORT', export, 'PRIMARY', icon='SAVE', label='Export textures', tip='Choose a folder and write the textures')
    menu_w = BAR_MENU_WIDTH * s
    view = Rect(export.x - 8 * s - menu_w, y, menu_w, h)
    layout.add('VIEW', view, 'DROPDOWN', label='View', text=CHANNEL[data.solo].label if data.solo else 'Material',
               tip='Show the full material or one channel on its own')
    channels = Rect(view.x - 6 * s - menu_w, y, menu_w, h)
    layout.add('CHANNELS', channels, 'DROPDOWN', label='Channels', text=str(len(set_channels(data))),
               tip=channel_names(data) + '. Choose which channels this texture set paints and exports')
    layout.add('SET_NAME', Rect(zone.x + 12 * s, y, max(0.0, channels.x - zone.x - 24 * s), h), 'NOTE',
               label=f'{obj_name}  ·  {data.resolution} px')


def tool_strip(layout, zone, tool, brush):
    s = layout.scale
    size, strength, color = brush
    layout.cards.append((zone, ''))
    y, h = zone.y + 6 * s, zone.h - 12 * s
    x = zone.x + 12 * s
    label = next((name for key, name, _, _ in TOOLS if key == tool), 'Brush')
    layout.add('TOOL_NAME', Rect(x, y, 70 * s, h), 'NOTE', label=label)
    x += 74 * s
    layout.add('BRUSH_COLOR', Rect(x, y, 32 * s, h), 'SWATCH', color=color, tip='Brush color')
    x += 42 * s
    slider = max(60 * s, min(200 * s, (zone.x + zone.w - 18 * s - x) / 2))
    layout.add('BRUSH_SIZE', Rect(x, y, slider, h), 'SLIDER', label='Size', value=size / MAX_BRUSH_SIZE, text=f'{size} px',
               tip='Brush radius', shortcut='F')
    x += slider + 6 * s
    layout.add('BRUSH_STRENGTH', Rect(x, y, slider, h), 'SLIDER', label='Strength', value=strength, text=f'{strength * 100:.0f}%',
               tip='Brush strength', shortcut='Shift F')


def dock_layout(layout, zone, tool):
    s = layout.scale
    button, gap = 36 * s, 6 * s
    groups = [[(key, label, shortcut) for key, label, _, shortcut in TOOLS], [('UNDO', 'Undo', 'Ctrl Z'), ('REDO', 'Redo', 'Ctrl Shift Z')]]
    y = zone.top
    for group in groups:
        start = y
        for key, label, shortcut in group:
            y -= button
            layout.add(key, Rect(zone.x, y, zone.w, button), 'TOOL', icon=key, label=label, active=key == tool, tip=label, shortcut=shortcut)
        layout.tool_groups.append(Rect(zone.x, y, zone.w, start - y))
        y -= gap


def selection(data):
    if editing_mask(data):
        return 'MASK'
    return 'FOLDER' if active_layer(data).kind == 'FOLDER' else 'LAYER'


def layer_rows(data, collapsed):
    rows = []

    def walk(parent, depth):
        for layer in reversed(children(data.layers, parent)):
            rows.append((layer, depth))
            if layer.kind == 'FOLDER' and 'FOLD_' + layer.uid not in collapsed:
                walk(layer.uid, depth + 1)
    walk('', 0)
    return rows


def layer_preview(layer):
    if layer.kind == 'PAINT':
        return layer.image
    if layer.kind == 'FILL':
        return thumbnails.material_texture(capture(layer), owner=layer.uid)
    return None


def fill_layers(layout, state, data, flow):
    s = layout.scale
    target = selection(data)
    size = THUMBNAIL * s
    for layer, depth in layer_rows(data, state.collapsed):
        uid = layer.uid
        line = flow.line(ROW_HEIGHT * s)
        if not flow.visible(line):
            continue
        indent = depth * INDENT * s
        row = Rect(line.x + 2 * s + indent, line.y + 1 * s, line.w - 4 * s - indent, line.h - 2 * s)
        selected = uid == data.active_uid
        editing = state.text is not None and state.text.key == f'NAME_{uid}'
        flow.add(f'ROW_{uid}', row, 'ROW', label=state.text.text if editing else layer.name, text=f'{layer.opacity * 100:.0f}%',
                 active=selected, second=1.0 if selected and target == 'LAYER' else 0.0,
                 preview=layer_preview(layer), mask=layer.mask, icon='LIBRARY' if layer.kind == 'FOLDER' else '',
                 color=slot_display(layer.slots['base_color']) if layer.kind != 'FOLDER' else None,
                 caret=state.text.cursor if editing else -1, tip='Click to select, double-click to rename, right-click for more')
        flow.add(f'EYE_{uid}', Rect(row.x + 4 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                 icon='HIDE_OFF' if layer.visible else 'HIDE_ON', tip='Hide layer' if layer.visible else 'Show layer')
        if layer.kind == 'FOLDER':
            folded = 'FOLD_' + uid in state.collapsed
            flow.add('FOLD_' + uid, Rect(row.x + row.w - 64 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                     icon='DISCLOSURE' if folded else 'DOWN', tip='Show the layers in this folder' if folded else 'Hide the layers in this folder')
        if layer.mask is not None:
            flow.add(f'MASKTHUMB_{uid}', Rect(row.x + 34 * s + size, row.y + (row.h - size) / 2, size, size), 'THUMB',
                     preview=layer.mask, active=selected and target == 'MASK', tip='Select the mask to paint and edit it')


def layers_panel(layout, state, data):
    s = layout.scale
    actions = (('ADD_FOLDER', '+ Folder', 66, 'New folder above the selected layer'),
               ('ADD_FILL', '+ Fill', 52, 'New fill layer above the selected one'),
               ('ADD_PAINT', '+ Paint', 64, 'New paint layer above the selected one'))
    return ColumnPanel('LAYERS', 'Layers', len(layer_rows(data, state.collapsed)) * ROW_HEIGHT * s + 8 * s, fill_layers, 4 * s, actions)


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
        elif fill and slot.source == 'IMAGE' and slot.image is not None:
            flow.add('IMAGE_NAME.' + key, value, 'NOTE', label=slot.image.name)
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
    return int(layer.kind == 'FILL' and uses_coordinates(layer))


def material_lines(data):
    layer = active_layer(data)
    return int(layer.kind == 'FILL' and bool(layer.material))


PROPERTY_SECTIONS = {'LAYER': (Section(one_line, opacity_section), Section(material_lines, material_section), Section(projection_lines, projection_section),
                               Section(channel_lines, channels_section), Section(one_line, layer_mask_section)),
                     'FOLDER': (Section(one_line, opacity_section), Section(one_line, layer_mask_section)),
                     'MASK': (Section(two_lines, mask_section),)}


def fill_properties(layout, state, data, flow):
    s = layout.scale
    layer = active_layer(data)
    flow.y -= 4 * s
    for section in PROPERTY_SECTIONS[selection(data)]:
        if section.lines(data):
            section.build(flow, data, layer, flow.viewport.w - 24 * s)


def properties_panel(layout, state, data):
    s = layout.scale
    target = selection(data)
    title = 'Properties · ' + active_layer(data).name + (' · Mask' if target == 'MASK' else '')
    lines = sum(section.lines(data) for section in PROPERTY_SECTIONS[target])
    return ColumnPanel('PROPERTIES', title, lines * LINE_HEIGHT * s + 16 * s, fill_properties, 12 * s)


def column_layout(layout, state, data, zone):
    s = layout.scale
    panels = [layers_panel(layout, state, data)] + ([properties_panel(layout, state, data)] if data.layers else [])
    room = max(0.0, zone.h - len(panels) * HEADER * s - (len(panels) - 1) * GAP * s)
    wants = [0.0 if spec.key in state.collapsed else spec.body for spec in panels]
    views = distribute(wants, room, (state.split, 1 - state.split)[:len(panels)])
    layout.add('COLUMN_EDGE', Rect(zone.x - 6 * s, zone.y, 6 * s, zone.h), 'GRIP', tip='Drag to resize the column')
    layout.splitter = (zone.top - HEADER * s, room)
    top = zone.top
    for index, (spec, view) in enumerate(zip(panels, views)):
        card, viewport, scroll = panel(layout, state, spec, zone.x, top, zone.w, view)
        if view > 0:
            spec.fill(layout, state, data, Flow(layout, viewport, scroll, spec.pad))
        top = card.y - GAP * s
        if index == 0 and len(panels) > 1 and all(wants) and sum(wants) > room:
            layout.add('SPLITTER', Rect(zone.x, top, zone.w, GAP * s), 'GRIP', tip='Drag to share space between the panels')


def shelf_header(layout, state, zone, header):
    s = layout.scale
    x = zone.x + 8 * s
    for tab, label in shelf.TABS:
        layout.add('SHELF_TAB.' + tab, Rect(x, header.y, 88 * s, header.h), 'CHIP', label=label, active=state.shelf_open and tab == state.shelf_tab,
                   tip=f'Browse {label.lower()}')
        x += 92 * s
    toggle = Rect(zone.x + zone.w - 30 * s, header.y, 22 * s, header.h)
    layout.add('SHELF_TOGGLE', toggle, 'ICON', icon='DOWN' if state.shelf_open else 'DISCLOSURE',
               tip='Hide the shelf' if state.shelf_open else 'Show the shelf')
    x += 8 * s
    room = toggle.x - 8 * s - x
    if state.armed:
        label = 'Click a material to put into the selected layer' if state.armed == REPLACE_TARGET else f'Click a texture or pattern for {CHANNEL[state.armed].label.lower()}'
        layout.add('ARM_INFO', Rect(x, header.y, max(0.0, room - 78 * s), header.h), 'NOTE', label=label)
        layout.add('CANCEL_ARM', Rect(toggle.x - 78 * s, header.y, 70 * s, header.h), 'CHIP', label='Cancel', tip='Stop picking', shortcut='Esc')
    elif state.shelf_open and state.shelf_tab == 'TEXTURES':
        editing = state.text is not None and state.text.key == 'TEXTURE_DIR'
        layout.add('TEXTURE_IMPORT', Rect(x, header.y, 70 * s, header.h), 'CHIP', label='Import', tip='Copy image files into your texture library')
        x += 76 * s
        room -= 76 * s
        field = min(360 * s, max(0.0, room - 78 * s))
        layout.add('TEXTURE_DIR', Rect(x, header.y, field, header.h), 'FIELD', text=state.text.text if editing else texture_folder(),
                   caret=state.text.cursor if editing else -1, tip='Folder of textures to browse')
        layout.add('TEXTURE_BROWSE', Rect(x + field + 6 * s, header.y, 70 * s, header.h), 'CHIP', label='Browse', tip='Pick a texture folder')


def shelf_layout(layout, state, zone):
    s = layout.scale
    layout.cards.append((zone, ''))
    header = Rect(zone.x, zone.top - 30 * s, zone.w, 22 * s)
    shelf_header(layout, state, zone, header)
    if not state.shelf_open:
        return
    viewport = Rect(zone.x, zone.y + 4 * s, zone.w, max(0.0, header.y - 6 * s - zone.y - 4 * s))
    entries = shelf.items(state.shelf_tab)
    if not entries:
        empty = 'Pick a folder of textures to browse them here.' if state.shelf_tab == 'TEXTURES' else 'Save a fill layer as a material to see it here.'
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
    for index, item in enumerate(entries):
        row, column = divmod(index, columns)
        top = viewport.top + scroll - SHELF_GAP * s - row * tile_h
        rect = Rect(viewport.x + SHELF_GAP * s + column * tile_w, top - tile_h + SHELF_GAP * s, SHELF_TILE * s, tile_h - SHELF_GAP * s)
        if rect.top < viewport.y or rect.y > viewport.top:
            continue
        if state.armed == REPLACE_TARGET and item.kind == 'MATERIAL':
            tip = 'Click to put this material into the selected layer'
        elif state.armed and state.armed != REPLACE_TARGET and item.kind != 'MATERIAL':
            tip = f'Click to use for {CHANNEL[state.armed].label.lower()}'
        else:
            tip = 'Click to add as a fill layer'
        if item.kind == 'TEXTURE':
            tip += '. Right-click for more'
        layout.add(f'ITEM.{index}', rect, 'TILE', label=item.label, preview=shelf.thumbnail(item), clip=viewport,
                   tip=tip + ('. Right-click to delete' if item.user_index >= 0 else ''))


def place_popover(bounds, anchor, w, h, s):
    x = min(max(bounds.x + 8 * s, anchor.x), bounds.x + bounds.w - 8 * s - w)
    y = anchor.y - 6 * s - h
    if y < bounds.y + 8 * s:
        y = min(anchor.top + 6 * s, bounds.top - 8 * s - h)
    return Rect(x, y, w, h)


def color_popover(layout, state, bounds):
    s = layout.scale
    card = place_popover(bounds, state.popover.anchor, 232 * s, 252 * s, s)
    hue, saturation, value = state.hsv
    x = card.x + 12 * s
    layout.add('COLOR_SV', Rect(x, card.y + 74 * s, card.w - 24 * s, 166 * s), 'SV', value=saturation, second=value,
               color=hsv_color((hue, 1.0, 1.0)))
    layout.add('COLOR_HUE', Rect(x, card.y + 52 * s, card.w - 24 * s, 14 * s), 'HUE', value=hue)
    layout.add('COLOR_PREVIEW', Rect(x, card.y + 14 * s, 40 * s, 28 * s), 'SWATCH', color=hsv_color(state.hsv))
    editing = state.text is not None and state.text.key == 'COLOR_HEX'
    red, green, blue = colorsys.hsv_to_rgb(*state.hsv)
    hex_text = '#%02X%02X%02X' % tuple(round(channel * 255) for channel in (red, green, blue))
    layout.add('COLOR_HEX', Rect(x + 48 * s, card.y + 16 * s, card.w - 72 * s, 24 * s), 'FIELD',
               text=state.text.text if editing else hex_text, caret=state.text.cursor if editing else -1, tip='Type a hex color')
    return card


def menu_popover(layout, state, bounds):
    s = layout.scale
    items = state.popover.items
    card = place_popover(bounds, state.popover.anchor, 196 * s, (len(items) * 26 + 8) * s, s)
    y = card.top - 4 * s
    for key, label, active in items:
        y -= 26 * s
        layout.add(key, Rect(card.x + 4 * s, y, card.w - 8 * s, 26 * s), 'MENUITEM', label=label, active=active)
    return card


def export_popover(layout, state, bounds, data, directory):
    s = layout.scale
    card = place_popover(bounds, state.popover.anchor, 360 * s, 150 * s, s)
    x, w = card.x + 14 * s, card.w - 28 * s
    layout.add('EXPORT_TITLE', Rect(x, card.top - 34 * s, w, 22 * s), 'NOTE', label='Export textures')
    editing = state.text is not None and state.text.key == 'EXPORT_DIR'
    layout.add('EXPORT_DIR', Rect(x, card.top - 66 * s, w - 76 * s, 24 * s), 'FIELD', text=state.text.text if editing else directory,
               caret=state.text.cursor if editing else -1, tip='Folder for the textures')
    layout.add('BROWSE', Rect(x + w - 70 * s, card.top - 66 * s, 70 * s, 24 * s), 'CHIP', label='Browse', tip='Pick a folder')
    layout.add('EXPORT_INFO', Rect(x, card.top - 94 * s, w, 20 * s), 'NOTE', label=f'{channel_names(data)}  ·  PNG  ·  {data.resolution} px')
    layout.add('EXPORT_RUN', Rect(x, card.y + 12 * s, w, 28 * s), 'PRIMARY', icon='SAVE', label='Export', tip='Write the textures now')
    return card


def painter_layout(bounds, scale, state, data, obj_name, tool, brush, directory):
    layout = Layout(scale, MinimalMetrics.resolve(), zones(bounds, scale, state.column_width, state.shelf_open))
    if data is None:
        start_layout(layout, bounds, obj_name, state.resolution)
    else:
        workspace_bar(layout, layout.zones.bar, data, obj_name)
        tool_strip(layout, layout.zones.strip, tool, brush)
        dock_layout(layout, layout.zones.dock, tool)
        shelf_layout(layout, state, layout.zones.shelf)
        column_layout(layout, state, data, layout.zones.column)
    if state.popover is not None:
        layout.popover_start = len(layout.controls)
        if state.popover.kind == 'COLOR':
            layout.popover = color_popover(layout, state, bounds)
        elif state.popover.kind == 'MENU':
            layout.popover = menu_popover(layout, state, bounds)
        elif data is not None:
            layout.popover = export_popover(layout, state, bounds, data, directory)
    return layout
