from dataclasses import dataclass
from typing import Tuple
import blf
import bpy
from .canvas import Rect

BG_BASE = (0.133, 0.098, 0.104, 1.0)
BG_ELEVATED = (0.251, 0.188, 0.199, 1.0)
BG_WELL = (0.110, 0.078, 0.083, 1.0)

TEXT_PRIMARY = (0.965, 0.949, 0.952, 1.0)
TEXT_SECONDARY = (0.816, 0.745, 0.757, 1.0)
TEXT_MUTED = (0.694, 0.600, 0.616, 1.0)

ACCENT = (0.835, 0.439, 0.505, 1.0)
ACCENT_BG = (0.212, 0.118, 0.134, 1.0)
ACCENT_BORDER = (0.420, 0.227, 0.259, 1.0)
ACCENT_HOVER = (0.890, 0.520, 0.582, 1.0)
TEXT_ON_ACCENT = (0.145, 0.047, 0.063, 1.0)

BORDER = (0.243, 0.176, 0.187, 1.0)
SURFACE_FLOATING = (0.157, 0.118, 0.124, .99)
SURFACE_OUTLINE = (0.345, 0.267, 0.280, 1.0)

RADIUS_CONTROL = 4.0
CHIP_ICON_SIZE = 16


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
