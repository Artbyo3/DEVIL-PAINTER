import numpy
from .blending import BLEND_MODES, linear_to_srgb
from .canvas import Layout, Rect
from .document import RESOLUTIONS, active_layer
from .painting import TOOLS
from .ui_system import MinimalMetrics

MAX_BRUSH_SIZE = 500
CARD_WIDTH = 264
ROW_HEIGHT = 42
LINE_HEIGHT = 28


def display_color(color):
    return tuple(float(value) for value in linear_to_srgb(numpy.array(color[:3]))) + (1.0,)


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


def dock_layout(layout, bounds, tool):
    s = layout.scale
    button, width, gap = 36 * s, 40 * s, 6 * s
    groups = [[(key, label, shortcut) for key, label, _, shortcut in TOOLS], [('UNDO', 'Undo', 'Ctrl Z'), ('REDO', 'Redo', 'Ctrl Shift Z')]]
    height = sum(len(group) for group in groups) * button + gap * (len(groups) - 1)
    x, y = bounds.x + 8 * s, bounds.y + (bounds.h + height) / 2
    for group in groups:
        top = y
        for key, label, shortcut in group:
            y -= button
            layout.add(key, Rect(x, y, width, button), 'TOOL', icon=key, label=label, active=key == tool, tip=label, shortcut=shortcut)
        layout.tool_groups.append(Rect(x, y, width, top - y))
        y -= gap


def brush_layout(layout, bounds, size, strength, color):
    s = layout.scale
    w, h = 420 * s, 40 * s
    card = Rect(bounds.x + (bounds.w - w) / 2, bounds.y + bounds.h - 8 * s - h, w, h)
    layout.cards.append((card, ''))
    layout.add('BRUSH_COLOR', Rect(card.x + 10 * s, card.y + 8 * s, 32 * s, 24 * s), 'SWATCH', color=color, tip='Brush color')
    slider_w = (card.w - 64 * s) / 2
    layout.add('BRUSH_SIZE', Rect(card.x + 52 * s, card.y + 8 * s, slider_w - 4 * s, 24 * s), 'SLIDER', label='Size',
               value=size / MAX_BRUSH_SIZE, text=f'{size} px', tip='Brush radius', shortcut='F')
    layout.add('BRUSH_STRENGTH', Rect(card.x + 52 * s + slider_w, card.y + 8 * s, slider_w - 4 * s, 24 * s), 'SLIDER',
               label='Strength', value=strength, text=f'{strength * 100:.0f}%', tip='Brush strength', shortcut='Shift F')


def layer_rows(layout, card, data, top, rows):
    s = layout.scale
    first = max(0, len(data.layers) - rows)
    y = top
    for index in range(len(data.layers) - 1, first - 1, -1):
        layer = data.layers[index]
        y -= ROW_HEIGHT * s
        row = Rect(card.x + 6 * s, y, card.w - 12 * s, ROW_HEIGHT * s - 2 * s)
        layout.add(f'ROW_{index}', row, 'ROW', label=layer.name, text=f'{layer.opacity * 100:.0f}%', active=index == data.active,
                   preview=layer.image if layer.kind == 'PAINT' else None, mask=layer.mask,
                   color=display_color(layer.color), tip='Select layer; double-click to rename')
        layout.add(f'EYE_{index}', Rect(row.x + 4 * s, row.y + 6 * s, 22 * s, row.h - 12 * s), 'ICON',
                   icon='HIDE_OFF' if layer.visible else 'HIDE_ON', tip='Hide layer' if layer.visible else 'Show layer')
    return y


def property_layout(layout, card, data, y):
    s = layout.scale
    layer = active_layer(data)
    x, w = card.x + 12 * s, card.w - 24 * s

    def line():
        nonlocal y
        y -= LINE_HEIGHT * s
        return y + 2 * s

    row = line()
    layout.add('OPACITY', Rect(x, row, w, 24 * s), 'SLIDER', label='Opacity', value=layer.opacity, text=f'{layer.opacity * 100:.0f}%')
    row = line()
    layout.add('BLEND', Rect(x, row, w, 24 * s), 'CHIP', label='Blend: ' + dict(BLEND_MODES)[layer.blend], tip='Click to change the blend mode')
    row = line()
    layout.add('USE_COLOR', Rect(x, row, 100 * s, 24 * s), 'TOGGLE', label='Color', active=layer.use_color, tip='Affect base color')
    if layer.kind == 'FILL':
        layout.add('LAYER_COLOR', Rect(x + 108 * s, row, w - 108 * s, 24 * s), 'SWATCH', color=display_color(layer.color), tip='Fill color')
    else:
        layout.add('PAINTED', Rect(x + 108 * s, row, w - 108 * s, 24 * s), 'NOTE', label='Brush color')
    for channel in ('roughness', 'metallic'):
        row = line()
        value = getattr(layer, channel)
        layout.add('USE_' + channel.upper(), Rect(x, row, 100 * s, 24 * s), 'TOGGLE', label=channel.title(),
                   active=getattr(layer, 'use_' + channel), tip=f'Affect {channel}')
        layout.add(channel.upper(), Rect(x + 108 * s, row, w - 108 * s, 24 * s), 'SLIDER', label='', value=value, text=f'{value:.2f}')
    row = line()
    if layer.mask is None:
        half = (w - 4 * s) / 2
        layout.add('ADD_MASK_WHITE', Rect(x, row, half, 24 * s), 'CHIP', label='White mask', tip='Show everything, paint black areas away')
        layout.add('ADD_MASK_BLACK', Rect(x + half + 4 * s, row, half, 24 * s), 'CHIP', label='Black mask', tip='Hide everything, paint areas in')
    else:
        third = (w - 36 * s) / 2
        if layer.kind == 'PAINT':
            layout.add('TARGET_LAYER', Rect(x, row, third, 24 * s), 'CHIP', label='Paint layer', active=not data.paint_mask)
        layout.add('TARGET_MASK', Rect(x + third + 4 * s, row, third, 24 * s), 'CHIP', label='Paint mask',
                   active=data.paint_mask or layer.kind == 'FILL')
        layout.add('REMOVE_MASK', Rect(x + w - 26 * s, row, 26 * s, 24 * s), 'ICON', icon='CLOSE', tip='Remove mask')
    return y


def layers_layout(layout, bounds, data):
    s = layout.scale
    w = CARD_WIDTH * s
    top = bounds.y + bounds.h - 8 * s
    properties = 6 * LINE_HEIGHT * s + 12 * s if data.layers else 0
    fixed = 34 * s + 30 * s + properties + 10 * s
    rows = max(1, min(len(data.layers), int((bounds.h - 70 * s - fixed) / (ROW_HEIGHT * s))))
    height = fixed + (rows * ROW_HEIGHT * s if data.layers else 0)
    card = Rect(bounds.x + bounds.w - 8 * s - w, top - height, w, height)
    layout.cards.append((card, 'Layers'))
    header = top - 30 * s
    layout.add('ADD_PAINT', Rect(card.x + 76 * s, header, 64 * s, 22 * s), 'CHIP', label='+ Paint', tip='New paint layer above the selected one')
    layout.add('ADD_FILL', Rect(card.x + 144 * s, header, 56 * s, 22 * s), 'CHIP', label='+ Fill', tip='New fill layer above the selected one')
    layout.add('CLOSE', Rect(card.x + card.w - 30 * s, header, 22 * s, 22 * s), 'ICON', icon='CLOSE', tip='Close', shortcut='Ctrl Alt P')
    y = layer_rows(layout, card, data, top - 34 * s, rows)
    actions = y - 28 * s
    for index, (key, icon, tip) in enumerate((('MOVE_UP', 'CHEVRON', 'Move layer up'), ('MOVE_DOWN', 'DOWN', 'Move layer down'),
                                              ('RENAME', 'MORE', 'Rename layer'), ('DELETE', 'CLOSE', 'Delete layer'))):
        layout.add(key, Rect(card.x + 12 * s + index * 30 * s, actions + 2 * s, 26 * s, 24 * s), 'ICON', icon=icon, tip=tip)
    if data.layers:
        property_layout(layout, card, data, actions - 6 * s)


def export_layout(layout, bounds):
    s = layout.scale
    rect = Rect(bounds.x + bounds.w - 8 * s - 180 * s, bounds.y + 12 * s, 180 * s, 30 * s)
    layout.cards.append((rect, ''))
    layout.add('EXPORT', rect, 'PRIMARY', icon='SAVE', label='Export textures', tip='Write Base Color, Roughness and Metallic PNGs')


def painter_layout(bounds, scale, data, obj_name, resolution, tool, brush):
    layout = Layout(scale, MinimalMetrics.resolve())
    if data is None:
        start_layout(layout, bounds, obj_name, resolution)
        return layout
    dock_layout(layout, bounds, tool)
    brush_layout(layout, bounds, *brush)
    layers_layout(layout, bounds, data)
    export_layout(layout, bounds)
    return layout
