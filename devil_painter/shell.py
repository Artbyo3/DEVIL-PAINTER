from dataclasses import dataclass
from .canvas import Rect

MARGIN = 8
GAP = 8
MIN_COLUMN = 260
MAX_COLUMN = 480
PANELS = ('SETS', 'LAYERS', 'PROPERTIES', 'MAPS')
PANEL_HEIGHTS = dict(SETS=128, LAYERS=220, PROPERTIES=280, MAPS=100)
MIN_PANEL = 48
MAX_PANEL = 1200
SHELF_CLOSED = 34
HANDLE = 10
ZONE_ORDER = (('BAR', 'TOP'), ('COLUMN', 'RIGHT'), ('STRIP', 'TOP'), ('DOCK', 'LEFT'), ('SHELF', 'BOTTOM'))
ZONE_SIDES = dict(BAR=('TOP', 'BOTTOM'), STRIP=('TOP', 'BOTTOM'), SHELF=('TOP', 'BOTTOM'), DOCK=('LEFT', 'RIGHT'), COLUMN=('LEFT', 'RIGHT'))
ZONE_SIZES = dict(BAR=36, STRIP=36, DOCK=40, COLUMN=330, SHELF=224)
ZONE_LIMITS = dict(BAR=(36, 96), STRIP=(36, 96), DOCK=(40, 120), COLUMN=(MIN_COLUMN, MAX_COLUMN), SHELF=(120, 640))


@dataclass(frozen=True)
class Zones:
    bar: Rect
    strip: Rect
    dock: Rect
    stage: Rect
    shelf: Rect
    column: Rect
    sides: dict


def clamp_zone(key, size):
    low, high = ZONE_LIMITS[key]
    return max(low, min(high, size))


def clamp_panel(height):
    return max(MIN_PANEL, min(MAX_PANEL, height))


def zones(bounds, s, order, sizes, shelf_open=True):
    gap = GAP * s
    free = Rect(bounds.x + MARGIN * s, bounds.y + MARGIN * s, max(0.0, bounds.w - 2 * MARGIN * s), max(0.0, bounds.h - 2 * MARGIN * s))
    found = {}
    for key, side in order:
        size = SHELF_CLOSED if key == 'SHELF' and not shelf_open else clamp_zone(key, sizes[key])
        thick = min(size * s, max(0.0, (free.w if side in ('LEFT', 'RIGHT') else free.h) / 2))
        if side == 'TOP':
            found[key] = Rect(free.x, free.top - thick, free.w, thick)
            free = Rect(free.x, free.y, free.w, max(0.0, free.h - thick - gap))
        elif side == 'BOTTOM':
            found[key] = Rect(free.x, free.y, free.w, thick)
            free = Rect(free.x, free.y + thick + gap, free.w, max(0.0, free.h - thick - gap))
        elif side == 'LEFT':
            found[key] = Rect(free.x, free.y, thick, free.h)
            free = Rect(free.x + thick + gap, free.y, max(0.0, free.w - thick - gap), free.h)
        else:
            found[key] = Rect(free.x + free.w - thick, free.y, thick, free.h)
            free = Rect(free.x, free.y, max(0.0, free.w - thick - gap), free.h)
    return Zones(found['BAR'], found['STRIP'], found['DOCK'], free, found['SHELF'], found['COLUMN'], dict(order))


def edge_depth(rect, side, bounds):
    if side == 'TOP':
        return bounds.top - rect.y
    if side == 'BOTTOM':
        return rect.top - bounds.y
    if side == 'LEFT':
        return rect.x + rect.w - bounds.x
    return bounds.x + bounds.w - rect.x


def zone_size(rect, side, x, y):
    if side == 'TOP':
        return rect.top - y
    if side == 'BOTTOM':
        return y - rect.y
    if side == 'LEFT':
        return x - rect.x
    return rect.x + rect.w - x


def move_zone(order, key, x, y, rects, bounds):
    vertical = ZONE_SIDES[key] == ('LEFT', 'RIGHT')
    if vertical:
        side = 'LEFT' if x < bounds.x + bounds.w / 2 else 'RIGHT'
        depth = x - bounds.x if side == 'LEFT' else bounds.x + bounds.w - x
    else:
        side = 'TOP' if y > bounds.y + bounds.h / 2 else 'BOTTOM'
        depth = bounds.top - y if side == 'TOP' else y - bounds.y
    rest = [(name, where) for name, where in order if name != key]
    deeper = [index for index, (name, where) in enumerate(rest) if where == side and depth < edge_depth(rects[name], side, bounds)]
    same = [index for index, (_, where) in enumerate(rest) if where == side]
    index = deeper[0] if deeper else (same[-1] + 1 if same else len(rest))
    return tuple(rest[:index] + [(key, side)] + rest[index:])


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
