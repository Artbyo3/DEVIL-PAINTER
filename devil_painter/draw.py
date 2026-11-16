import math
import time
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from .canvas import Rect, grid_step
from .icons import ICON_LEVELS, icon_pixels, icon_spans
from .ui_system import (BG_BASE, BG_ELEVATED, BG_WELL, BORDER, GRID_MAJOR, GRID_MINOR, GRID_ORIGIN, TEXT_PRIMARY, TEXT_SECONDARY,
                        SURFACE_FLOATING, ComponentRenderer, Tooltip)

SHELL = BG_BASE
TOOLTIP_SHORTCUTS = {'CLOSE': 'Ctrl Alt P'}
EMPTY_TITLE = 'Devil Painter'
EMPTY_HINT = 'Painting tools come next. Middle-drag pans, scroll zooms.'


class Renderer:
    def __init__(self):
        self.shader = None
        self.line_shader = None
        self.s = 1
        self.offset = (0, 0)
        self.icon_batches = {}

    def triangles(self, points, color, indices=None):
        if not points:
            return
        if self.shader is None:
            self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        batch = batch_for_shader(self.shader, 'TRIS', {"pos": points}, indices=indices)
        self.shader.bind()
        self.shader.uniform_float("color", color)
        batch.draw(self.shader)

    def rect(self, r, color):
        x = round(r.x)
        y = round(r.y)
        w = round(r.w)
        h = round(r.h)
        self.triangles([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                       color, [(0, 1, 2), (0, 2, 3)])

    def round_rect(self, r, color, radius=8):
        x = round(r.x)
        y = round(r.y)
        w = round(r.w)
        h = round(r.h)
        rad = min(radius * self.s, w / 2, h / 2)
        if rad <= 1.5:
            self.rect(Rect(x, y, w, h), color)
            return
        pts = [
            (x + rad, y), (x + w - rad, y), (x + w - rad, y + h), (x + rad, y + h),
            (x, y + rad), (x + rad, y + rad), (x + rad, y + h - rad), (x, y + h - rad),
            (x + w - rad, y + rad), (x + w, y + rad), (x + w, y + h - rad), (x + w - rad, y + h - rad),
        ]
        indices = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7), (8, 9, 10), (8, 10, 11)]
        corners = [
            (x + rad, y + rad, math.pi, 1.5 * math.pi),
            (x + w - rad, y + rad, 1.5 * math.pi, 2 * math.pi),
            (x + w - rad, y + h - rad, 0, 0.5 * math.pi),
            (x + rad, y + h - rad, 0.5 * math.pi, math.pi),
        ]
        n = max(6, min(12, int(rad)))
        for cx, cy, a0, a1 in corners:
            pts.append((cx, cy))
            c_idx = len(pts) - 1
            for i in range(n + 1):
                angle = a0 + (a1 - a0) * i / n
                pts.append((cx + math.cos(angle) * rad, cy + math.sin(angle) * rad))
                if i > 0:
                    indices.append((c_idx, len(pts) - 2, len(pts) - 1))
        self.triangles(pts, color, indices)

    def round_rect_outline(self, r, color, radius=8, width=1):
        x = round(r.x)
        y = round(r.y)
        w = round(r.w)
        h = round(r.h)
        rad = min(radius * self.s, w / 2, h / 2)
        line_w = (1.0 / max(1.0, self.s)) if width <= 1.2 else width
        if width <= 1.2:
            x_out = x + 0.5
            y_out = y + 0.5
            w_out = max(0.0, w - 1.0)
            h_out = max(0.0, h - 1.0)
            rad_out = max(0.0, rad - 0.5)
        else:
            x_out, y_out, w_out, h_out, rad_out = x, y, w, h, rad

        if rad_out <= 1.0:
            self.lines([(x_out, y_out), (x_out + w_out, y_out),
                        (x_out + w_out, y_out + h_out), (x_out, y_out + h_out),
                        (x_out, y_out)],
                       color, line_w, strip=True)
            return

        corners = [
            (x_out + rad_out, y_out + rad_out, math.pi, 1.5 * math.pi),
            (x_out + w_out - rad_out, y_out + rad_out, 1.5 * math.pi, 2 * math.pi),
            (x_out + w_out - rad_out, y_out + h_out - rad_out, 0, 0.5 * math.pi),
            (x_out + rad_out, y_out + h_out - rad_out, 0.5 * math.pi, math.pi),
        ]
        pts = []
        n = max(6, min(12, int(rad_out)))
        for cx, cy, a0, a1 in corners:
            for i in range(n + 1):
                angle = a0 + (a1 - a0) * i / n
                pts.append((cx + math.cos(angle) * rad_out, cy + math.sin(angle) * rad_out))
        self.lines(pts + pts[:1], color, line_w, strip=True)

    def lines(self, points, color, width=1, strip=False):
        if len(points) < 2:
            return
        if self.line_shader is None:
            self.line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        sh = self.line_shader
        is_1px = (width * self.s <= 1.2)
        if is_1px and len(points) == 2:
            p0, p1 = points
            if abs(p0[1] - p1[1]) < 1e-4:
                y = math.floor(p0[1]) + 0.5
                points = [(round(p0[0]), y), (round(p1[0]), y)]
            elif abs(p0[0] - p1[0]) < 1e-4:
                x = math.floor(p0[0]) + 0.5
                points = [(x, round(p0[1])), (x, round(p1[1]))]
        batch = batch_for_shader(sh, 'LINE_STRIP' if strip else 'LINES', {"pos": points})
        sh.bind()
        sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        sh.uniform_float("lineWidth", width * self.s)
        sh.uniform_float("color", color)
        batch.draw(sh)

    def text(self, x, y, label, size=11, color=TEXT_PRIMARY, center=False, max_width=None):
        blf.size(0, size * self.s)
        if max_width is not None:
            original = label
            while label and blf.dimensions(0, label)[0] > max_width:
                original = original[:-1]
                label = original + "..." if original else ""
        if center:
            x -= blf.dimensions(0, label)[0] / 2
        blf.color(0, *color)
        blf.position(0, round(x), round(y), 0)
        blf.draw(0, label)

    def clip(self, r):
        x, y, w, h = round(r.x), round(r.y), round(r.w), round(r.h)
        gpu.state.scissor_set(int(self.offset[0] + x), int(self.offset[1] + y), max(1, int(w)), max(1, int(h)))
        blf.enable(0, blf.CLIPPING)
        blf.clipping(0, x, y, x + w, y + h)

    def draw_icon(self, name, cx, cy, size, color):
        spans = icon_spans(name)
        px_size = max(1, round(size * self.s))
        left_px = round(cx - px_size / 2.0)
        bottom_px = round(cy - px_size / 2.0)
        snap_cx = left_px + px_size / 2.0
        snap_cy = bottom_px + px_size / 2.0
        if spans is not None:
            if self.shader is None:
                self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            self.smooth_icon(name, snap_cx, snap_cy, size, color)

    def smooth_icon(self, name, cx, cy, size, color):
        pixels = max(1, round(size * self.s))
        key = (name, pixels)
        if key not in self.icon_batches:
            batches = []
            for level, cells in icon_pixels(name, pixels).items():
                vertices = []
                for x, y in cells:
                    vertices.extend([(x, y), (x + 1, y), (x + 1, y + 1), (x, y), (x + 1, y + 1), (x, y + 1)])
                batches.append((level, batch_for_shader(self.shader, 'TRIS', {'pos': vertices})))
            self.icon_batches[key] = batches
        gpu.state.blend_set('ALPHA')
        with gpu.matrix.push_pop():
            gpu.matrix.translate((round(cx - pixels / 2), round(cy - pixels / 2), 0))
            self.shader.bind()
            for level, batch in self.icon_batches[key]:
                self.shader.uniform_float('color', (*color[:3], color[3] * level / ICON_LEVELS))
                batch.draw(self.shader)

    def draw(self, ed):
        self.s = s = ed.canvas_layout.scale
        layout, view = ed.canvas_layout, ed.view
        metrics = layout.metrics
        p, c = layout.panel, layout.canvas
        blend = gpu.state.blend_get()
        depth = gpu.state.depth_test_get()
        scissor = gpu.state.scissor_get()
        viewport = gpu.state.viewport_get()
        self.offset = viewport[:2]
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.scissor_test_set(True)
        try:
            self.clip(p)
            self.round_rect(p, SHELL, radius=metrics.box)
            self.round_rect_outline(p, BORDER, radius=metrics.box, width=1.0)
            self.round_rect(c, BG_BASE, radius=0)
            self.clip(c)
            self.grid(view, c)
            self.text(c.x + c.w / 2, c.y + c.h / 2 + 12 * s, EMPTY_TITLE, 17, TEXT_PRIMARY, True, max_width=c.w - 32 * s)
            self.text(c.x + c.w / 2, c.y + c.h / 2 - 14 * s, EMPTY_HINT, 11, TEXT_SECONDARY, True, max_width=c.w - 32 * s)
            self.minimal_workspace(ed)
        finally:
            blf.disable(0, blf.CLIPPING)
            gpu.state.scissor_set(*scissor)
            gpu.state.scissor_test_set(False)
            gpu.state.depth_test_set(depth)
            gpu.state.blend_set(blend)

    def minimal_workspace(self, ed):
        layout = ed.canvas_layout
        scale = self.s
        metrics = layout.metrics
        self.clip(layout.panel)
        tooltip = None
        for key, (rect, label) in layout.buttons.items():
            hover = rect.contains(*ed.pointer)
            if key in {'RESTORE_CANVAS', 'SHOW_3D'}:
                self.round_rect(rect, BG_ELEVATED if hover else BG_WELL, radius=metrics.regular)
                self.text(rect.x + rect.w / 2, rect.y + 8 * scale, label, 10, TEXT_SECONDARY, True)
            else:
                if hover:
                    self.round_rect(rect, BG_ELEVATED, radius=metrics.toolbar_item)
                self.draw_icon(key, rect.x + rect.w / 2, rect.y + rect.h / 2, min(28, rect.h / scale - 6), TEXT_SECONDARY)
            if hover:
                tooltip = (label, TOOLTIP_SHORTCUTS.get(key, ''), (rect.x - 70 * scale, rect.y - 18 * scale))
        panel = layout.panel
        if ed.message != ed.toast_text:
            ed.toast_text = ed.message
            ed.toast_until = time.monotonic() + 3
        if ed.message and time.monotonic() < ed.toast_until:
            width = min(420 * scale, max(80 * scale, panel.w - 390 * scale))
            toast = Rect(panel.x + 76 * scale, panel.y + 15 * scale, width, 30 * scale)
            self.round_rect(toast, SURFACE_FLOATING, radius=metrics.tooltip)
            self.text(toast.x + 12 * scale, toast.y + 10 * scale, ed.message, 10, TEXT_SECONDARY, max_width=toast.w - 24 * scale)
        if tooltip:
            ComponentRenderer.draw_tooltip(self, Tooltip(text=tooltip[0], shortcut=tooltip[1], pos=tooltip[2], visible=True), scale, metrics)

    def grid(self, view, c):
        step = grid_step(view.zoom)
        low, high = view.world((c.x, c.y), c), view.world((c.x + c.w, c.y + c.h), c)
        minor, major = [], []
        for axis in (0, 1):
            for i in range(math.floor(low[axis] / step), math.ceil(high[axis] / step) + 1):
                val = i * step
                if axis == 0:
                    x = view.screen((val, 0), c)[0]
                    pts = [(x, c.y), (x, c.y + c.h)]
                else:
                    y = view.screen((0, val), c)[1]
                    pts = [(c.x, y), (c.x + c.w, y)]
                (major if i % 5 == 0 else minor).extend(pts)
        self.lines(minor, GRID_MINOR)
        self.lines(major, GRID_MAJOR)
        origin = view.screen((0, 0), c)
        self.lines([(origin[0], c.y), (origin[0], c.y + c.h),
                    (c.x, origin[1]), (c.x + c.w, origin[1])], GRID_ORIGIN)
