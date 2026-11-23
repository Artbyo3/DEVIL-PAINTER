import colorsys
import math
import time
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from .canvas import Rect
from .icons import ICON_LEVELS, icon_bounds, icon_fit_size, icon_pixels, icon_spans
from .minimal import THUMBNAIL
from .previews import draw_image
from .privacy import masked
from .ui_system import (ACCENT, ACCENT_BG, ACCENT_BORDER, ACCENT_HOVER, BG_ELEVATED, BG_WELL, BORDER, CHIP_ICON_SIZE, SURFACE_FLOATING,
                        SURFACE_OUTLINE, TEXT_MUTED, TEXT_ON_ACCENT, TEXT_PRIMARY, TEXT_SECONDARY, ComponentRenderer, Tooltip)

TOAST_SECONDS = 3
COMPACT_SLIDER = 104
LABEL_MINIMUM = 28
CHECKER = ((0.32, 0.32, 0.32, 1.0), (0.22, 0.22, 0.22, 1.0))


class Renderer:
    def __init__(self):
        self.shader = None
        self.line_shader = None
        self.smooth_shader = None
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

    def fitted(self, label, size, max_width):
        blf.size(0, size * self.s)
        original = label
        while label and blf.dimensions(0, label)[0] > max_width:
            original = original[:-1]
            label = original + "..." if original else ""
        return label

    def text_width(self, label, size):
        blf.size(0, size * self.s)
        return blf.dimensions(0, label)[0]

    def text(self, x, y, label, size=11, color=TEXT_PRIMARY, center=False, max_width=None):
        blf.size(0, size * self.s)
        if max_width is not None:
            label = self.fitted(label, size, max_width)
        if center:
            x -= blf.dimensions(0, label)[0] / 2
        blf.color(0, *color)
        blf.position(0, round(x), round(y), 0)
        blf.draw(0, label)

    def text_right(self, right, y, label, size, color, max_width=None):
        if max_width is not None:
            label = self.fitted(label, size, max_width)
        self.text(right - self.text_width(label, size), y, label, size, color)

    def label_room(self, rect, value, size, right_reserve):
        return rect.w - 8 * self.s - right_reserve - self.text_width(value, size) - 6 * self.s

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

    def clip(self, rect):
        if rect is None:
            gpu.state.scissor_test_set(False)
            blf.disable(0, blf.CLIPPING)
            return
        x, y, w, h = round(rect.x), round(rect.y), round(rect.w), round(rect.h)
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(self.offset[0] + x), int(self.offset[1] + y), max(1, int(w)), max(1, int(h)))
        blf.enable(0, blf.CLIPPING)
        blf.clipping(0, x, y, x + w, y + h)

    def gradient(self, rect, corners):
        if self.smooth_shader is None:
            self.smooth_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        x, y, w, h = rect.x, rect.y, rect.w, rect.h
        batch = batch_for_shader(self.smooth_shader, 'TRIS', {'pos': ((x, y), (x + w, y), (x + w, y + h), (x, y + h)), 'color': corners},
                                 indices=((0, 1, 2), (0, 2, 3)))
        gpu.state.blend_set('ALPHA')
        self.smooth_shader.bind()
        batch.draw(self.smooth_shader)

    def controls(self, ed, controls, metrics):
        hovered = None
        for control in controls:
            self.clip(control.clip)
            hover = control.hit(*ed.pointer)
            DRAWERS[control.kind](self, control, hover, metrics)
            if hover and control.tip:
                hovered = control
        self.clip(None)
        return hovered

    def draw(self, ed):
        layout = ed.workspace
        self.s = s = layout.scale
        metrics = layout.metrics
        blend = gpu.state.blend_get()
        depth = gpu.state.depth_test_get()
        scissor = gpu.state.scissor_get()
        self.offset = gpu.state.viewport_get()[:2]
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        split = layout.popover_start if layout.popover_start >= 0 else len(layout.controls)
        try:
            self.toast(ed, metrics)
            for rect, title in layout.cards:
                self.round_rect(rect, SURFACE_FLOATING, radius=metrics.menu_back)
                self.round_rect_outline(rect, SURFACE_OUTLINE, radius=metrics.menu_back)
                if title:
                    self.text(rect.x + 14 * s, rect.y + rect.h - 24 * s, title, 13, TEXT_PRIMARY)
            for group in layout.tool_groups:
                self.round_rect(group, SURFACE_FLOATING, radius=metrics.toolbar_item)
            hovered = self.controls(ed, layout.controls[:split], metrics)
            for group in layout.tool_groups:
                self.round_rect_outline(group, SURFACE_OUTLINE, radius=metrics.toolbar_item)
            if layout.popover is not None:
                self.round_rect(layout.popover, SURFACE_FLOATING, radius=metrics.menu_back)
                self.round_rect_outline(layout.popover, SURFACE_OUTLINE, radius=metrics.menu_back)
                inside = layout.popover.contains(*ed.pointer)
                hovered = self.controls(ed, layout.controls[split:], metrics) or (None if inside else hovered)
            if hovered is not None:
                rect = hovered.rect
                if hovered.kind == 'TOOL':
                    position = (rect.x + rect.w + 6 * s, rect.y + rect.h / 2)
                else:
                    position = (min(rect.x, ed.bounds.x + ed.bounds.w - 260 * s), rect.y - 18 * s)
                ComponentRenderer.draw_tooltip(self, Tooltip(text=hovered.tip, shortcut=hovered.shortcut, pos=position, visible=True), s, metrics)
        finally:
            self.clip(None)
            gpu.state.scissor_set(*scissor)
            gpu.state.depth_test_set(depth)
            gpu.state.blend_set(blend)

    def toast(self, ed, metrics):
        s = self.s
        if ed.message != ed.toast_text:
            ed.toast_text = ed.message
            ed.toast_until = time.monotonic() + TOAST_SECONDS
            ed.toast_revealed = False
        ed.toast_rect = None
        if not ed.message or time.monotonic() >= ed.toast_until:
            return
        stage = ed.workspace.zones.stage
        toast = Rect(stage.x, stage.y, min(460 * s, max(120 * s, stage.w)), 30 * s)
        ed.toast_rect = toast
        self.round_rect(toast, SURFACE_FLOATING, radius=metrics.tooltip)
        self.text(toast.x + 12 * s, toast.y + 10 * s, ed.message if ed.toast_revealed else masked(ed.message), 10, TEXT_SECONDARY, max_width=toast.w - 24 * s)

    def tool(self, control, hover, metrics):
        rect = control.rect
        if control.active or hover:
            self.round_rect(rect, ACCENT_BG if control.active else BG_ELEVATED, radius=metrics.toolbar_item)
        self.draw_icon(control.icon, rect.x + rect.w / 2, rect.y + rect.h / 2, min(26, rect.h / self.s - 8),
                       ACCENT if control.active else TEXT_SECONDARY)

    def icon_button(self, control, hover, metrics):
        rect = control.rect
        if hover:
            self.round_rect(rect, BG_ELEVATED, radius=metrics.regular)
        self.draw_icon(control.icon, rect.x + rect.w / 2, rect.y + rect.h / 2, 14, TEXT_PRIMARY if hover else TEXT_SECONDARY)

    def chip(self, control, hover, metrics):
        rect = control.rect
        self.round_rect(rect, ACCENT_BG if control.active else BG_ELEVATED if hover else BG_WELL, radius=metrics.regular)
        if control.active:
            self.round_rect_outline(rect, ACCENT_BORDER, radius=metrics.regular)
        color = ACCENT if control.active else TEXT_PRIMARY if hover else TEXT_SECONDARY
        if control.icon:
            pixels = icon_fit_size(control.icon, max(1, round(CHIP_ICON_SIZE * self.s)))
            gx, gy, gw, gh = icon_bounds(control.icon, pixels)
            cx = rect.x + rect.w / 2 + (pixels / 2 - (gx + gw / 2))
            cy = rect.y + rect.h / 2 + (pixels / 2 - (gy + gh / 2))
            self.draw_icon(control.icon, cx, cy, pixels / self.s, color)
        else:
            self.text(rect.x + rect.w / 2, rect.y + (rect.h - 10 * self.s) / 2, control.label, 10, color, True, max_width=rect.w - 8 * self.s)

    def primary(self, control, hover, metrics):
        rect, s = control.rect, self.s
        self.round_rect(rect, ACCENT_HOVER if hover else ACCENT, radius=metrics.regular)
        self.round_rect_outline(rect, ACCENT_BORDER, radius=metrics.regular)
        self.draw_icon(control.icon, rect.x + 18 * s, rect.y + rect.h / 2, 16, TEXT_ON_ACCENT)
        self.text(rect.x + 34 * s, rect.y + (rect.h - 11 * s) / 2, control.label, 11, TEXT_ON_ACCENT, max_width=rect.w - 42 * s)

    def slider(self, control, hover, metrics):
        rect, s = control.rect, self.s
        if control.caret >= 0:
            self.round_rect(rect, BG_WELL, radius=metrics.text)
            self.round_rect_outline(rect, ACCENT_BORDER, radius=metrics.text)
            baseline = rect.y + (rect.h - 10 * s) / 2
            pad = 4 * s if rect.w <= COMPACT_SLIDER * s else 8 * s
            tx = rect.x + pad
            if control.selected and control.text:
                blf.size(0, 10 * s)
                width = min(rect.w - 2 * pad + 2 * s, blf.dimensions(0, control.text)[0] + 2 * s)
                self.rect(Rect(tx - 1 * s, baseline - 2 * s, max(0.0, width), 14 * s), ACCENT_BG)
            self.text(tx, baseline, control.text, 10, TEXT_PRIMARY)
            if not control.selected:
                self.caret(tx, baseline, control.text, control.caret, 10)
            return
        self.round_rect(rect, BG_WELL, radius=metrics.regular)
        filled = max(0.0, min(1.0, control.value)) * rect.w
        if filled >= 1:
            self.round_rect(Rect(rect.x, rect.y, filled, rect.h), ACCENT_BG, radius=metrics.regular)
        self.round_rect_outline(rect, ACCENT_BORDER if hover else BORDER, radius=metrics.regular)
        baseline = rect.y + (rect.h - 10 * s) / 2
        room = self.label_room(rect, control.text, 10, 8 * s)
        if control.label and room >= LABEL_MINIMUM * s:
            self.text(rect.x + 8 * s, baseline, control.label, 10, TEXT_SECONDARY, max_width=room)
        self.text_right(rect.x + rect.w - 8 * s, baseline, control.text, 10, TEXT_PRIMARY, max_width=rect.w - 16 * s)

    def swatch(self, control, hover, metrics):
        rect = control.rect
        self.round_rect(rect, control.color, radius=metrics.regular)
        self.round_rect_outline(rect, ACCENT_BORDER if hover else SURFACE_OUTLINE, radius=metrics.regular)

    def toggle(self, control, hover, metrics):
        rect, s = control.rect, self.s
        self.round_rect(rect, BG_ELEVATED if hover else BG_WELL, radius=metrics.regular)
        if control.active:
            self.draw_icon('CHECK', rect.x + 12 * s, rect.y + rect.h / 2, 12, ACCENT)
        self.text(rect.x + 24 * s, rect.y + (rect.h - 10 * s) / 2, control.label, 10, TEXT_PRIMARY if control.active else TEXT_MUTED, max_width=rect.w - 28 * s)

    def checker(self, rect):
        cells = 4
        size = rect.w / cells
        for parity, color in enumerate(CHECKER):
            points, indices = [], []
            for column in range(cells):
                for row in range(cells):
                    if (column + row) % 2 != parity:
                        continue
                    x, y = round(rect.x + column * size), round(rect.y + row * size)
                    w, h = round(rect.x + (column + 1) * size) - x, round(rect.y + (row + 1) * size) - y
                    base = len(points)
                    points += [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                    indices += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            self.triangles(points, color, indices)

    def thumbnail(self, rect, image, color, mask, selected):
        if mask:
            draw_image(image, rect, True)
        elif image is not None:
            self.checker(rect)
            draw_image(image, rect, False)
        else:
            self.rect(rect, color)
        self.round_rect_outline(rect, ACCENT if selected else SURFACE_OUTLINE, radius=0)

    def row(self, control, hover, metrics):
        rect, s = control.rect, self.s
        if control.active or hover:
            self.round_rect(rect, ACCENT_BG if control.active else BG_ELEVATED, radius=metrics.menu_item)
        size = THUMBNAIL * s
        y = rect.y + (rect.h - size) / 2
        x = rect.x + 30 * s
        if control.icon:
            self.round_rect(Rect(x, y, size, size), BG_WELL, radius=metrics.regular)
            self.draw_icon(control.icon, x + size / 2, y + size / 2, 18, ACCENT if control.second > 0 else TEXT_SECONDARY)
        else:
            self.thumbnail(Rect(x, y, size, size), control.preview, control.color, False, control.second > 0)
        if control.mask is not None:
            x += size + 4 * s
        x += size + 8 * s
        baseline = rect.y + (rect.h - 11 * s) / 2
        if control.caret >= 0:
            field = Rect(x - 4 * s, rect.y + 8 * s, rect.x + rect.w - x - 40 * s, rect.h - 16 * s)
            self.round_rect(field, BG_WELL, radius=metrics.text)
            self.round_rect_outline(field, ACCENT_BORDER, radius=metrics.text)
            self.text(x, baseline, control.label, 11, TEXT_PRIMARY)
            self.caret(x, baseline, control.label, control.caret, 11)
        else:
            self.text(x, baseline, control.label, 11, TEXT_PRIMARY, max_width=rect.x + rect.w - x - max(44 * s, control.value))
        self.text_right(rect.x + rect.w - 8 * s, baseline + s, control.text, 9, TEXT_MUTED)

    def thumb(self, control, hover, metrics):
        self.thumbnail(control.rect, control.preview, None, True, control.active)
        if hover and not control.active:
            self.round_rect_outline(control.rect, ACCENT_BORDER, radius=0)

    def tile(self, control, hover, metrics):
        rect, s = control.rect, self.s
        image = Rect(rect.x, rect.top - rect.w, rect.w, rect.w)
        if hover:
            self.round_rect(Rect(rect.x - 3 * s, rect.y - 2 * s, rect.w + 6 * s, rect.h + 4 * s), BG_ELEVATED, radius=metrics.regular)
        if control.preview is None:
            self.round_rect(image, BG_WELL, radius=metrics.regular)
            if control.icon == 'FAILED':
                self.text(image.x + image.w / 2, image.y + image.h / 2 - 4 * s, 'Preview failed', 9, TEXT_MUTED, True, max_width=image.w - 4 * s)
        else:
            self.checker(image)
            draw_image(control.preview, image, False)
        self.round_rect_outline(image, ACCENT_BORDER if hover else SURFACE_OUTLINE, radius=0)
        self.text(rect.x + rect.w / 2, rect.y + 3 * s, control.label, 9, TEXT_PRIMARY if hover else TEXT_SECONDARY, True, max_width=rect.w)

    def source(self, control, hover, metrics):
        rect = control.rect
        if control.preview is None:
            self.round_rect(rect, BG_ELEVATED if hover else BG_WELL, radius=metrics.regular)
            self.draw_icon(control.icon, rect.x + rect.w / 2, rect.y + rect.h / 2, 12, TEXT_PRIMARY if hover else TEXT_SECONDARY)
        else:
            self.checker(rect)
            draw_image(control.preview, rect, False)
        self.round_rect_outline(rect, ACCENT_BORDER if hover else SURFACE_OUTLINE, radius=0)

    def ghost(self, control, hover, metrics):
        self.round_rect_outline(control.rect, ACCENT, radius=metrics.regular, width=2)

    def grip(self, control, hover, metrics):
        if not hover:
            return
        rect, s = control.rect, self.s
        if rect.h > rect.w:
            x = rect.x + rect.w / 2
            self.lines([(x, rect.y), (x, rect.top)], ACCENT, 2)
        else:
            y = rect.y + rect.h / 2
            self.lines([(rect.x + 8 * s, y), (rect.x + rect.w - 8 * s, y)], ACCENT, 2)

    def caret(self, x, baseline, text, cursor, size):
        blf.size(0, size * self.s)
        offset = blf.dimensions(0, text[:cursor])[0]
        self.rect(Rect(x + offset, baseline - 2 * self.s, max(1, round(self.s)), (size + 4) * self.s), ACCENT)

    def header(self, control, hover, metrics):
        rect, s = control.rect, self.s
        if hover:
            self.round_rect(rect, BG_ELEVATED, radius=metrics.menu_back)
        self.draw_icon('DOWN' if control.active else 'DISCLOSURE', rect.x + 14 * s, rect.y + rect.h / 2, 10, TEXT_SECONDARY)
        self.text(rect.x + 26 * s, rect.y + (rect.h - 12 * s) / 2, control.label, 12, TEXT_PRIMARY, max_width=rect.w - 34 * s - control.second)

    def dropdown(self, control, hover, metrics):
        rect, s = control.rect, self.s
        self.round_rect(rect, BG_ELEVATED if hover else BG_WELL, radius=metrics.regular)
        baseline = rect.y + (rect.h - 10 * s) / 2
        room = self.label_room(rect, control.text, 10, 24 * s)
        if control.label and room >= LABEL_MINIMUM * s:
            self.text(rect.x + 8 * s, baseline, control.label, 10, TEXT_SECONDARY, max_width=room)
        self.text_right(rect.x + rect.w - 24 * s, baseline, control.text, 10, TEXT_PRIMARY, max_width=rect.w - 32 * s)
        self.draw_icon('DOWN', rect.x + rect.w - 12 * s, rect.y + rect.h / 2, 10, TEXT_SECONDARY)

    def field(self, control, hover, metrics):
        rect, s = control.rect, self.s
        editing = control.caret >= 0
        self.round_rect(rect, BG_WELL, radius=metrics.text)
        self.round_rect_outline(rect, ACCENT_BORDER if editing or hover else BORDER, radius=metrics.text)
        baseline = rect.y + (rect.h - 10 * s) / 2
        self.text(rect.x + 8 * s, baseline, control.text, 10, TEXT_PRIMARY, max_width=None if editing else rect.w - 16 * s)
        if editing:
            self.caret(rect.x + 8 * s, baseline, control.text, control.caret, 10)

    def menu_item(self, control, hover, metrics):
        rect, s = control.rect, self.s
        if hover:
            self.round_rect(rect, ACCENT_BG, radius=metrics.menu_item)
        if control.active:
            self.draw_icon('CHECK', rect.x + rect.w - 14 * s, rect.y + rect.h / 2, 12, ACCENT)
        self.text(rect.x + 10 * s, rect.y + (rect.h - 10 * s) / 2, control.label, 10, ACCENT if hover else TEXT_PRIMARY)

    def saturation_value(self, control, hover, metrics):
        rect, s = control.rect, self.s
        hue = control.color
        self.gradient(rect, ((1, 1, 1, 1), hue, hue, (1, 1, 1, 1)))
        self.gradient(rect, ((0, 0, 0, 1), (0, 0, 0, 1), (0, 0, 0, 0), (0, 0, 0, 0)))
        center = (rect.x + control.value * rect.w, rect.y + control.second * rect.h)
        marker = Rect(center[0] - 5 * s, center[1] - 5 * s, 10 * s, 10 * s)
        self.round_rect_outline(marker, (0, 0, 0, 1), radius=5)
        self.round_rect_outline(Rect(marker.x + s, marker.y + s, marker.w - 2 * s, marker.h - 2 * s), (1, 1, 1, 1), radius=4)

    def hue(self, control, hover, metrics):
        rect, s = control.rect, self.s
        stops = [tuple(colorsys.hsv_to_rgb(index / 6, 1, 1)) + (1.0,) for index in range(7)]
        width = rect.w / 6
        for index in range(6):
            segment = Rect(rect.x + index * width, rect.y, width, rect.h)
            self.gradient(segment, (stops[index], stops[index + 1], stops[index + 1], stops[index]))
        x = rect.x + control.value * rect.w
        self.rect(Rect(x - 2 * s, rect.y - 2 * s, 4 * s, rect.h + 4 * s), (1, 1, 1, 1))

    def scrollbar(self, control, hover, metrics):
        rect = control.rect
        thumb_h = max(12 * self.s, rect.h * min(1.0, control.second))
        y = rect.y + (rect.h - thumb_h) * (1 - control.value)
        self.round_rect(Rect(rect.x, y, rect.w, thumb_h), SURFACE_OUTLINE, radius=2)

    def gizmo(self, control, hover, metrics):
        if control.points:
            self.lines(control.points, ACCENT, 2)
        rect = control.rect
        self.round_rect(rect, ACCENT_HOVER if hover else ACCENT, radius=rect.w / 2)

    def history_row(self, control, hover, metrics):
        rect, s = control.rect, self.s
        if control.active or hover:
            self.round_rect(rect, ACCENT_BG if control.active else BG_ELEVATED, radius=metrics.menu_item)
        if control.active:
            self.draw_icon('CHECK', rect.x + 12 * s, rect.y + rect.h / 2, 10, ACCENT)
        color = TEXT_PRIMARY if control.active or hover else TEXT_SECONDARY if control.value >= .5 else TEXT_MUTED
        self.text(rect.x + 24 * s, rect.y + (rect.h - 10 * s) / 2, control.label, 10, color, max_width=rect.w - 30 * s)

    def note(self, control, hover, metrics):
        rect = control.rect
        self.text(rect.x + 2 * self.s, rect.y + (rect.h - 10 * self.s) / 2, control.label, 10, TEXT_MUTED, max_width=rect.w)


DRAWERS = {'TOOL': Renderer.tool, 'ICON': Renderer.icon_button, 'CHIP': Renderer.chip, 'PRIMARY': Renderer.primary,
           'SLIDER': Renderer.slider, 'PROGRESS': Renderer.slider, 'SWATCH': Renderer.swatch, 'TOGGLE': Renderer.toggle, 'ROW': Renderer.row, 'NOTE': Renderer.note,
           'HEADER': Renderer.header, 'DROPDOWN': Renderer.dropdown, 'FIELD': Renderer.field, 'MENUITEM': Renderer.menu_item,
           'SV': Renderer.saturation_value, 'HUE': Renderer.hue, 'SCROLLBAR': Renderer.scrollbar, 'THUMB': Renderer.thumb,
           'GRIP': Renderer.grip, 'TILE': Renderer.tile, 'SOURCE': Renderer.source, 'GIZMO': Renderer.gizmo,
           'GHOST': Renderer.ghost, 'HISTORY': Renderer.history_row}
