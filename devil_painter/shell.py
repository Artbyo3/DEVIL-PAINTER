from dataclasses import dataclass
from .canvas import Rect

MARGIN = 8
GAP = 8
BAR_HEIGHT = 36
STRIP_HEIGHT = 36
DOCK_WIDTH = 40
MIN_COLUMN = 260
MAX_COLUMN = 480
MIN_SPLIT = .15
SHELF_OPEN = 196
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


def clamp_split(split):
    return max(MIN_SPLIT, min(1 - MIN_SPLIT, split))


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


def distribute(wants, room, weights):
    shares = [0.0] * len(wants)
    open_panels = [index for index, want in enumerate(wants) if want > 0]
    while open_panels and room > 0:
        total = sum(weights[index] for index in open_panels)
        capped = [index for index in open_panels if wants[index] <= room * weights[index] / total]
        if not capped:
            for index in open_panels:
                shares[index] = room * weights[index] / total
            break
        for index in capped:
            shares[index] = wants[index]
            room -= wants[index]
        open_panels = [index for index in open_panels if index not in capped]
    return shares
