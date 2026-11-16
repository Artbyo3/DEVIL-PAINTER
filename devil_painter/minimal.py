import colorsys
from dataclasses import dataclass
import numpy
from .blending import BLEND_MODES, linear_to_srgb
from .canvas import Layout, Rect
from .document import RESOLUTIONS, active_layer
from .painting import TOOLS
from .shell import GAP, distribute, zones
from .ui_system import MinimalMetrics

MAX_BRUSH_SIZE = 500
HEADER = 30
ROW_HEIGHT = 42
LINE_HEIGHT = 28
THUMBNAIL = 32
CHANNEL_NAMES = 'Base Color · Roughness · Metallic'


def display_color(color):
    return tuple(float(value) for value in linear_to_srgb(numpy.array(color[:3]))) + (1.0,)


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
    lines: int
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
    layout.add('SET_NAME', Rect(zone.x + 12 * s, y, max(0.0, export.x - zone.x - 24 * s), h), 'NOTE',
               label=f'{obj_name}  ·  {data.resolution} px  ·  {CHANNEL_NAMES}')


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
    return 'MASK' if data.paint_mask and active_layer(data).mask is not None else 'LAYER'


def fill_layers(layout, state, data, flow):
    s = layout.scale
    target = selection(data)
    size = THUMBNAIL * s
    for index in range(len(data.layers) - 1, -1, -1):
        layer = data.layers[index]
        line = flow.line(ROW_HEIGHT * s)
        if not flow.visible(line):
            continue
        row = Rect(line.x + 2 * s, line.y + 1 * s, line.w - 4 * s, line.h - 2 * s)
        selected = index == data.active
        editing = state.text is not None and state.text.key == f'NAME_{index}'
        flow.add(f'ROW_{index}', row, 'ROW', label=state.text.text if editing else layer.name, text=f'{layer.opacity * 100:.0f}%',
                 active=selected, second=1.0 if selected and target == 'LAYER' else 0.0,
                 preview=layer.image if layer.kind == 'PAINT' else None, mask=layer.mask, color=display_color(layer.color),
                 caret=state.text.cursor if editing else -1, tip='Click to select, double-click to rename, right-click for more')
        flow.add(f'EYE_{index}', Rect(row.x + 4 * s, row.y + 8 * s, 22 * s, row.h - 16 * s), 'ICON',
                 icon='HIDE_OFF' if layer.visible else 'HIDE_ON', tip='Hide layer' if layer.visible else 'Show layer')
        if layer.mask is not None:
            flow.add(f'MASKTHUMB_{index}', Rect(row.x + 34 * s + size, row.y + (row.h - size) / 2, size, size), 'THUMB',
                     preview=layer.mask, active=selected and target == 'MASK', tip='Select the mask to paint and edit it')


def layers_panel(layout, state, data):
    s = layout.scale
    actions = (('ADD_FILL', '+ Fill', 52, 'New fill layer above the selected one'),
               ('ADD_PAINT', '+ Paint', 64, 'New paint layer above the selected one'))
    return ColumnPanel('LAYERS', 'Layers', len(data.layers) * ROW_HEIGHT * s + 8 * s, fill_layers, 4 * s, actions)


def opacity_section(flow, data, layer, w):
    x, y, h = flow.field()
    flow.add('OPACITY', Rect(x, y, w, h), 'SLIDER', label='Opacity', value=layer.opacity, text=f'{layer.opacity * 100:.0f}%')
    x, y, h = flow.field()
    flow.add('BLEND', Rect(x, y, w, h), 'DROPDOWN', label='Blend', text=dict(BLEND_MODES)[layer.blend],
             tip='Choose how this layer mixes with the layers below')


def channels_section(flow, data, layer, w):
    s = flow.layout.scale
    x, y, h = flow.field()
    flow.add('USE_COLOR', Rect(x, y, 100 * s, h), 'TOGGLE', label='Color', active=layer.use_color, tip='Affect base color')
    if layer.kind == 'FILL':
        flow.add('LAYER_COLOR', Rect(x + 108 * s, y, w - 108 * s, h), 'SWATCH', color=display_color(layer.color), tip='Fill color')
    else:
        flow.add('PAINTED', Rect(x + 108 * s, y, w - 108 * s, h), 'NOTE', label='Brush color')
    for channel in ('roughness', 'metallic'):
        x, y, h = flow.field()
        value = getattr(layer, channel)
        flow.add('USE_' + channel.upper(), Rect(x, y, 100 * s, h), 'TOGGLE', label=channel.title(),
                 active=getattr(layer, 'use_' + channel), tip=f'Affect {channel}')
        flow.add(channel.upper(), Rect(x + 108 * s, y, w - 108 * s, h), 'SLIDER', value=value, text=f'{value:.2f}')


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


PROPERTY_SECTIONS = {'LAYER': (Section(2, opacity_section), Section(3, channels_section), Section(1, layer_mask_section)),
                     'MASK': (Section(2, mask_section),)}


def fill_properties(layout, state, data, flow):
    s = layout.scale
    layer = active_layer(data)
    flow.y -= 4 * s
    for section in PROPERTY_SECTIONS[selection(data)]:
        section.build(flow, data, layer, flow.viewport.w - 24 * s)


def properties_panel(layout, state, data):
    s = layout.scale
    target = selection(data)
    title = 'Properties · ' + active_layer(data).name + (' · Mask' if target == 'MASK' else '')
    lines = sum(section.lines for section in PROPERTY_SECTIONS[target])
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
    layout.add('EXPORT_INFO', Rect(x, card.top - 94 * s, w, 20 * s), 'NOTE', label=f'{CHANNEL_NAMES}  ·  PNG  ·  {data.resolution} px')
    layout.add('EXPORT_RUN', Rect(x, card.y + 12 * s, w, 28 * s), 'PRIMARY', icon='SAVE', label='Export', tip='Write the textures now')
    return card


def painter_layout(bounds, scale, state, data, obj_name, tool, brush, directory):
    layout = Layout(scale, MinimalMetrics.resolve(), zones(bounds, scale, state.column_width))
    if data is None:
        start_layout(layout, bounds, obj_name, state.resolution)
    else:
        workspace_bar(layout, layout.zones.bar, data, obj_name)
        tool_strip(layout, layout.zones.strip, tool, brush)
        dock_layout(layout, layout.zones.dock, tool)
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
