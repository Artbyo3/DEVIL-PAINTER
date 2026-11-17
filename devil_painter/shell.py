from dataclasses import dataclass
from .canvas import Rect

MARGIN = 8
GAP = 8
HEADER = 30
SHELF_CLOSED = 34
PANELS = ('SETS', 'LAYERS', 'PROPERTIES', 'MAPS')
SECTIONS = ('BAR', 'STRIP', 'DOCK', 'SHELF') + PANELS
ROWS_ONLY = ('BAR', 'STRIP')
SIDES = ('TOP', 'BOTTOM', 'LEFT', 'RIGHT')
PLACES = dict(TOP=('BAR', 'STRIP'), LEFT=('DOCK',), RIGHT=PANELS, BOTTOM=('SHELF',))
HEIGHTS = dict(BAR=36, STRIP=36, DOCK=480, SHELF=224, SETS=128, LAYERS=220, PROPERTIES=280, MAPS=100)
WIDTHS = dict(LEFT=40, RIGHT=330)
MIN_PANEL = 48
MAX_SIZE = 1400
ROW_LIMIT = 96
DOCK_WIDTH = 40
PANEL_WIDTH = 260


@dataclass(frozen=True)
class Zones:
    stage: Rect
    rects: dict
    sides: dict
    areas: dict
    rooms: dict


def clamp_height(key, height):
    if key in ROWS_ONLY:
        return max(36, min(ROW_LIMIT, height))
    return max(DOCK_WIDTH if key == 'DOCK' else MIN_PANEL, min(MAX_SIZE, height))


def clamp_width(width, keys):
    low = DOCK_WIDTH if all(key == 'DOCK' for key in keys) else PANEL_WIDTH
    return max(low, min(MAX_SIZE, width))


def fixed_part(key, collapsed, shelf_open):
    if key in PANELS:
        return HEADER
    if key == 'SHELF' and not shelf_open:
        return SHELF_CLOSED
    return 0


def flexible(key, collapsed, shelf_open):
    return not (key in PANELS and key in collapsed) and not (key == 'SHELF' and not shelf_open)


def thickness(key, heights, collapsed, shelf_open):
    return fixed_part(key, collapsed, shelf_open) + (clamp_height(key, heights[key]) if flexible(key, collapsed, shelf_open) else 0)


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


def arrange(bounds, s, places, heights, widths, shown, collapsed, shelf_open):
    gap = GAP * s
    free = Rect(bounds.x + MARGIN * s, bounds.y + MARGIN * s, max(0.0, bounds.w - 2 * MARGIN * s), max(0.0, bounds.h - 2 * MARGIN * s))
    rects, sides, areas, rooms = {}, {}, {}, {}
    top = free.top
    for key in [key for key in places['TOP'] if key in shown]:
        size = min(thickness(key, heights, collapsed, shelf_open) * s, max(0.0, free.h / 2))
        rects[key], sides[key] = Rect(free.x, free.top - size, free.w, size), 'TOP'
        free = Rect(free.x, free.y, free.w, max(0.0, free.h - size - gap))
    areas['TOP'] = Rect(free.x, free.top, free.w, max(0.0, top - free.top))
    for side in ('LEFT', 'RIGHT'):
        keys = [key for key in places[side] if key in shown]
        if not keys:
            areas[side], rooms[side] = Rect(free.x if side == 'LEFT' else free.x + free.w, free.y, 0.0, free.h), 0.0
            continue
        width = min(clamp_width(widths[side], keys) * s, max(0.0, free.w / 2))
        area = Rect(free.x, free.y, width, free.h) if side == 'LEFT' else Rect(free.x + free.w - width, free.y, width, free.h)
        free = Rect(free.x + width + gap if side == 'LEFT' else free.x, free.y, max(0.0, free.w - width - gap), free.h)
        moving = [key for key in keys if flexible(key, collapsed, shelf_open)]
        room = max(0.0, area.h - gap * (len(keys) - 1) - sum(fixed_part(key, collapsed, shelf_open) * s for key in keys))
        fitted = dict(zip(moving, fit_heights([clamp_height(key, heights[key]) * s for key in moving], room, MIN_PANEL * s)))
        areas[side], rooms[side] = area, room / s
        y = area.top
        for key in keys:
            size = fixed_part(key, collapsed, shelf_open) * s + fitted.get(key, 0.0)
            rects[key], sides[key] = Rect(area.x, y - size, area.w, size), side
            y -= size + gap
    bottom = free.y
    for key in [key for key in places['BOTTOM'] if key in shown]:
        size = min(thickness(key, heights, collapsed, shelf_open) * s, max(0.0, free.h / 2))
        rects[key], sides[key] = Rect(free.x, free.y, free.w, size), 'BOTTOM'
        free = Rect(free.x, free.y + size + gap, free.w, max(0.0, free.h - size - gap))
    areas['BOTTOM'] = Rect(free.x, bottom, free.w, max(0.0, free.y - bottom))
    return Zones(free, rects, sides, areas, rooms)


def place(places, key, x, y, found):
    stage = found.stage
    side = next((name for name in ('LEFT', 'RIGHT', 'TOP', 'BOTTOM') if found.areas[name].w > 0 and found.areas[name].h > 0
                 and found.areas[name].contains(x, y)), None)
    if side is None:
        distance = dict(LEFT=x - stage.x, RIGHT=stage.x + stage.w - x, TOP=stage.top - y, BOTTOM=y - stage.y)
        side = min(distance, key=distance.get)
    if key in ROWS_ONLY and side in ('LEFT', 'RIGHT'):
        side = 'TOP' if y > stage.y + stage.h / 2 else 'BOTTOM'
    others = [name for name in places[side] if name != key]
    middle = {name: found.rects[name].y + found.rects[name].h / 2 for name in others if name in found.rects}
    if side == 'BOTTOM':
        index = sum(1 for name in others if middle.get(name, y - 1) < y)
    else:
        index = sum(1 for name in others if middle.get(name, y + 1) > y)
    result = {name: [item for item in places[name] if item != key] for name in SIDES}
    result[side].insert(index, key)
    return result


def resize_stack(keys, heights, key, want, room):
    heights = dict(heights)
    index = keys.index(key)
    below = keys[index + 1:]
    ceiling = room - sum(clamp_height(name, heights[name]) for name in keys[:index]) - MIN_PANEL * len(below)
    heights[key] = clamp_height(key, min(want, ceiling))
    excess = sum(clamp_height(name, heights[name]) for name in keys) - room
    for name in below:
        if excess <= 0:
            break
        cut = max(0.0, min(excess, clamp_height(name, heights[name]) - MIN_PANEL))
        heights[name] = clamp_height(name, heights[name]) - cut
        excess -= cut
    return heights
