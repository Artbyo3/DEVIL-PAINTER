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
COLUMNS = ('LEFT', 'RIGHT')
STRIPS = dict(TOP=((36, ('BAR',)), (36, ('STRIP',))), LEFT=((40, ('DOCK',)),), RIGHT=((330, PANELS),), BOTTOM=((224, ('SHELF',)),))
HEIGHTS = dict(BAR=36, STRIP=36, DOCK=480, SHELF=224, SETS=128, LAYERS=220, PROPERTIES=280, MAPS=100)
WIDTHS = {key: 600 for key in SECTIONS}
MIN_PANEL = 48
MAX_SIZE = 1400
SPLIT = .25


@dataclass(frozen=True)
class Zones:
    stage: Rect
    rects: dict
    places: dict
    strips: list
    rooms: dict
    tails: set


def default_strips():
    return {side: [dict(size=size, items=list(items)) for size, items in STRIPS[side]] for side in SIDES}


def clamp_length(key, length):
    return max(36 if key == 'DOCK' else MIN_PANEL, min(MAX_SIZE, length))


def clamp_strip(side, size, items):
    if side in COLUMNS:
        return max(40 if all(key == 'DOCK' for key in items) else 200, min(MAX_SIZE, size))
    return max(36, min(96 if all(key in ROWS_ONLY for key in items) else MAX_SIZE, size))


def fixed_part(key, collapsed, shelf_open):
    if key in PANELS:
        return HEADER
    if key == 'SHELF' and not shelf_open:
        return SHELF_CLOSED
    return 0


def flexible(key, collapsed, shelf_open):
    return not (key in PANELS and key in collapsed) and not (key == 'SHELF' and not shelf_open)


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


def row_size(strip, items, collapsed, shelf_open):
    if all(key == 'SHELF' and not shelf_open for key in items):
        return SHELF_CLOSED
    return clamp_strip('TOP', strip['size'], items)


def arrange(bounds, s, strips, heights, widths, shown, collapsed, shelf_open):
    gap = GAP * s
    free = Rect(bounds.x + MARGIN * s, bounds.y + MARGIN * s, max(0.0, bounds.w - 2 * MARGIN * s), max(0.0, bounds.h - 2 * MARGIN * s))
    rects, places, found, rooms, tails = {}, {}, [], {}, set()
    for side in ('TOP', 'LEFT', 'RIGHT', 'BOTTOM'):
        for index, strip in enumerate(strips[side]):
            items = [key for key in strip['items'] if key in shown]
            if not items:
                continue
            if side in COLUMNS:
                size = min(clamp_strip(side, strip['size'], items) * s, max(0.0, free.w / 2))
                rect = Rect(free.x, free.y, size, free.h) if side == 'LEFT' else Rect(free.x + free.w - size, free.y, size, free.h)
                free = Rect(free.x + size + gap if side == 'LEFT' else free.x, free.y, max(0.0, free.w - size - gap), free.h)
                moving = [key for key in items if flexible(key, collapsed, shelf_open)]
                room = max(0.0, rect.h - gap * (len(items) - 1) - sum(fixed_part(key, collapsed, shelf_open) * s for key in items))
                fitted = dict(zip(moving, fit_heights([clamp_length(key, heights[key]) * s for key in moving], room, MIN_PANEL * s)))
                if moving:
                    fitted[moving[-1]] += max(0.0, room - sum(fitted.values()))
                    tails.add(moving[-1])
                rooms[(side, index)] = room / s
                y = rect.top
                for key in items:
                    length = fixed_part(key, collapsed, shelf_open) * s + fitted.get(key, 0.0)
                    rects[key], places[key] = Rect(rect.x, y - length, rect.w, length), (side, index)
                    y -= length + gap
            else:
                size = min(row_size(strip, items, collapsed, shelf_open) * s, max(0.0, free.h / 2))
                rect = Rect(free.x, free.top - size, free.w, size) if side == 'TOP' else Rect(free.x, free.y, free.w, size)
                free = Rect(free.x, free.y if side == 'TOP' else free.y + size + gap, free.w, max(0.0, free.h - size - gap))
                room = max(0.0, rect.w - gap * (len(items) - 1))
                fitted = fit_heights([clamp_length(key, widths[key]) * s for key in items[:-1]] + [0.0], room, MIN_PANEL * s)
                fitted[-1] = max(0.0, room - sum(fitted[:-1]))
                rooms[(side, index)] = room / s
                x = rect.x
                for key, length in zip(items, fitted):
                    rects[key], places[key] = Rect(x, rect.y, length, rect.h), (side, index)
                    x += length + gap
                tails.add(items[-1])
            found.append((side, index, rect))
    return Zones(free, rects, places, found, rooms, tails)


def new_strip(side, key):
    if side in COLUMNS:
        return dict(size=40 if key == 'DOCK' else 330, items=[key])
    return dict(size=36 if key in ROWS_ONLY or key == 'DOCK' else 260, items=[key])


def place(strips, key, x, y, found):
    result = {side: [dict(size=strip['size'], items=[item for item in strip['items'] if item != key]) for strip in strips[side]] for side in SIDES}
    target = next(((side, index, rect) for side, index, rect in found.strips if rect.contains(x, y)), None)
    if target is not None and key in ROWS_ONLY and target[0] in COLUMNS:
        target = None
    if target is None:
        stage = found.stage
        distance = dict(LEFT=x - stage.x, RIGHT=stage.x + stage.w - x, TOP=stage.top - y, BOTTOM=y - stage.y)
        if key in ROWS_ONLY:
            distance = dict(TOP=distance['TOP'], BOTTOM=distance['BOTTOM'])
        side = min(distance, key=distance.get)
        result[side].append(new_strip(side, key))
    else:
        side, index, rect = target
        if side in COLUMNS:
            edge = rect.w * SPLIT
            near = x < rect.x + edge, x > rect.x + rect.w - edge
            if any(near):
                outer = near[0] if side == 'LEFT' else near[1]
                result[side].insert(index if outer else index + 1, new_strip(side, key))
            else:
                others = result[side][index]['items']
                spot = sum(1 for name in others if name in found.rects and found.rects[name].y + found.rects[name].h / 2 > y)
                others.insert(spot, key)
        else:
            edge = rect.h * SPLIT
            near = y > rect.top - edge, y < rect.y + edge
            if any(near):
                outer = near[0] if side == 'TOP' else near[1]
                result[side].insert(index if outer else index + 1, new_strip(side, key))
            else:
                others = result[side][index]['items']
                spot = sum(1 for name in others if name in found.rects and found.rects[name].x + found.rects[name].w / 2 < x)
                others.insert(spot, key)
    return {side: [strip for strip in result[side] if strip['items']] for side in SIDES}


def resize_run(keys, lengths, key, want, room):
    lengths = dict(lengths)
    index = keys.index(key)
    after = keys[index + 1:]
    ceiling = room - sum(clamp_length(name, lengths[name]) for name in keys[:index]) - MIN_PANEL * len(after)
    lengths[key] = clamp_length(key, min(want, ceiling))
    excess = sum(clamp_length(name, lengths[name]) for name in keys) - room
    for name in after:
        if excess <= 0:
            break
        cut = max(0.0, min(excess, clamp_length(name, lengths[name]) - MIN_PANEL))
        lengths[name] = clamp_length(name, lengths[name]) - cut
        excess -= cut
    return lengths
