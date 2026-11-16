from .canvas import Rect
from .ui_system import MinimalMetrics


def minimal_layout(layout):
    scale = layout.scale
    panel = layout.panel
    layout.metrics = MinimalMetrics.resolve()
    layout.buttons = {}
    right = round(panel.x + panel.w - 14 * scale)
    layout.buttons['CLOSE'] = (Rect(round(right - 24 * scale), round(panel.y + panel.h - 30 * scale), round(24 * scale), round(24 * scale)), 'Close')
    right -= round(28 * scale)
    right -= round(88 * scale)
    if layout.full:
        layout.buttons['SHOW_3D'] = (Rect(right, round(panel.y + panel.h - 30 * scale), round(82 * scale), round(24 * scale)), '3D view')
    else:
        layout.buttons['RESTORE_CANVAS'] = (Rect(right, round(panel.y + panel.h - 30 * scale), round(82 * scale), round(24 * scale)), 'Full canvas')
    layout.canvas = Rect(round(panel.x + 4 * scale), round(panel.y + 4 * scale), round(panel.w - 8 * scale), round(panel.h - 8 * scale))
