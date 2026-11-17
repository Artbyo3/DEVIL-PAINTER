from dataclasses import dataclass
from .canvas import Rect

MARGIN = 8
GAP = 8
BAR_HEIGHT = 36
STRIP_HEIGHT = 36
DOCK_WIDTH = 40
MIN_COLUMN = 260
MAX_COLUMN = 480
PANELS = ('SETS', 'LAYERS', 'PROPERTIES', 'MAPS')
PANEL_HEIGHTS = dict(SETS=128, LAYERS=220, PROPERTIES=280, MAPS=100)
MIN_PANEL = 48
MAX_PANEL = 1200
SHELF_OPEN = 224
SHELF_CLOSED = 34


@dataclass(frozen=True)
class Zones:
    bar: Rect
    strip: Rect
    dock: Rect
    stage: Rect
    shelf: Rect
    column: Rect


def clamp_column(width):
    return max(MIN_COLUMN, min(MAX_COLUMN, width))


def clamp_panel(height):
    return max(MIN_PANEL, min(MAX_PANEL, height))


def zones(bounds, s, column_width, shelf_open=True):
    margin, gap = MARGIN * s, GAP * s
    left, bottom = bounds.x + margin, bounds.y + margin
    bar = Rect(left, bounds.top - margin - BAR_HEIGHT * s, max(0.0, bounds.w - 2 * margin), BAR_HEIGHT * s)
    width = min(clamp_column(column_width) * s, max(0.0, bounds.w / 2))
    column = Rect(bar.x + bar.w - width, bottom, width, max(0.0, bar.y - gap - bottom))
    strip = Rect(left, bar.y - gap - STRIP_HEIGHT * s, max(0.0, column.x - gap - left), STRIP_HEIGHT * s)
    dock = Rect(left, bottom, DOCK_WIDTH * s, max(0.0, strip.y - gap - bottom))
    stage_x = dock.x + dock.w + gap
    width = max(0.0, column.x - gap - stage_x)
    shelf = Rect(stage_x, bottom, width, min((SHELF_OPEN if shelf_open else SHELF_CLOSED) * s, dock.h / 2))
    stage = Rect(stage_x, shelf.top + gap, width, max(0.0, dock.top - shelf.top - gap))
    return Zones(bar, strip, dock, stage, shelf, column)


def fit_heights(heights, room, minimum):
    total = sum(heights)
    if total <= room:
        return list(heights)
    spare = [max(0.0, height - minimum) for height in heights]
    available = sum(spare)
    ratio = min(1.0, (total - room) / available) if available > 0 else 0.0
    fitted = [height - extra * ratio for height, extra in zip(heights, spare)]
    if sum(fitted) > room:
        scale = room / sum(fitted) if sum(fitted) > 0 else 0.0
        fitted = [height * scale for height in fitted]
    return fitted


def resize_panel(keys, heights, key, want, room):
    heights = dict(heights)
    index = keys.index(key)
    below = keys[index + 1:]
    ceiling = room - sum(heights[name] for name in keys[:index]) - MIN_PANEL * len(below)
    heights[key] = clamp_panel(min(want, ceiling))
    excess = sum(heights[name] for name in keys) - room
    for name in below:
        if excess <= 0:
            break
        cut = max(0.0, min(excess, heights[name] - MIN_PANEL))
        heights[name] -= cut
        excess -= cut
    return heights


def reorder(order, key, target, below):
    order = [name for name in order if name != key]
    index = order.index(target) + (1 if below else 0)
    return order[:index] + [key] + order[index:]
