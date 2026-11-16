from dataclasses import dataclass
from typing import Tuple
import blf
import bpy
from .canvas import Rect

BG_BASE = (0.098, 0.114, 0.133, 1.0)
BG_ELEVATED = (0.188, 0.220, 0.251, 1.0)
BG_WELL = (0.078, 0.094, 0.110, 1.0)

TEXT_PRIMARY = (0.949, 0.957, 0.965, 1.0)
TEXT_SECONDARY = (0.745, 0.780, 0.816, 1.0)
TEXT_MUTED = (0.600, 0.647, 0.694, 1.0)

BORDER = (0.176, 0.208, 0.243, 1.0)
SURFACE_FLOATING = (0.118, 0.137, 0.157, .99)
SURFACE_OUTLINE = (0.267, 0.306, 0.345, 1.0)

RADIUS_CONTROL = 4.0


@dataclass
class MinimalMetrics:
    toolbar_item: float = 4.0
    regular: float = 4.0
    menu_back: float = 4.0
    menu_item: float = 4.0
    text: float = 4.0
    box: float = 4.0
    tooltip: float = 4.0

    @classmethod
    def resolve(cls):
        m = cls()
        try:
            ui = bpy.context.preferences.themes[0].user_interface
            roles = ('toolbar_item', 'regular', 'menu_back', 'menu_item', 'text', 'box', 'tooltip')
            for role in roles:
                wcol = getattr(ui, 'wcol_' + role, None)
                if wcol is not None and hasattr(wcol, 'roundness'):
                    setattr(m, role, 0.5 * float(wcol.roundness) * 20.0)
        except Exception:
            pass
        return m


@dataclass
class Tooltip:
    text: str = ""
    shortcut: str = ""
    pos: Tuple[float, float] = (0.0, 0.0)
    visible: bool = False


class ComponentRenderer:

    @staticmethod
    def draw_tooltip(draw_ctx, tooltip: Tooltip, scale: float, metrics=None):
        if not tooltip.visible or not tooltip.text:
            return
        s = scale
        x, y = tooltip.pos
        blf.size(0, 10 * s)
        tw = blf.dimensions(0, tooltip.text)[0]
        kw = blf.dimensions(0, tooltip.shortcut)[0] if tooltip.shortcut else 0.0
        w = tw + (kw + 14 * s if tooltip.shortcut else 0.0) + 24 * s
        h = 30 * s

        r = Rect(x, y - h / 2, w, h)
        radius = metrics.menu_back if metrics else RADIUS_CONTROL
        draw_ctx.round_rect(r, SURFACE_FLOATING, radius=radius)
        draw_ctx.round_rect_outline(r, SURFACE_OUTLINE, radius=radius)
        draw_ctx.text(r.x + 12 * s, r.y + 11 * s, tooltip.text, 10, TEXT_PRIMARY)
        if tooltip.shortcut:
            draw_ctx.text(r.x + r.w - 12 * s - kw, r.y + 11 * s, tooltip.shortcut, 10, TEXT_MUTED)
