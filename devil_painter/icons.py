import json
from functools import lru_cache
from pathlib import Path

ICON_GRID = 64
ICON_LEVELS = 32


@lru_cache(maxsize=1)
def icon_geometry():
    folder = Path(__file__).parent / 'assets' / 'icons'
    geometry = json.loads((folder / 'geometry.json').read_text(encoding='utf-8'))
    geometry.update(json.loads((folder / 'devil-painter' / 'geometry.json').read_text(encoding='utf-8')))
    return geometry


def icon_spans(name):
    return icon_geometry().get(name)


def overlaps(start, ratio, pixels):
    low, high = start * ratio, (start + 1) * ratio
    first = int(low)
    return [(cell, min(high, cell + 1) - max(low, cell)) for cell in range(first, min(pixels, int(high) + 1)) if min(high, cell + 1) > max(low, cell)]


@lru_cache(maxsize=None)
def icon_pixels(name, pixels):
    ratio = pixels / ICON_GRID
    coverage = {}
    for column, row, width, level in icon_spans(name):
        for source_x in range(column, column + width):
            for x, share_x in overlaps(source_x, ratio, pixels):
                for y, share_y in overlaps(row, ratio, pixels):
                    coverage[x, y] = coverage.get((x, y), 0) + share_x * share_y * level / 8
    levels = {}
    for cell, amount in coverage.items():
        step = min(ICON_LEVELS, round(amount * ICON_LEVELS))
        if step:
            levels.setdefault(step, []).append(cell)
    return levels


@lru_cache(maxsize=None)
def icon_bounds(name, pixels):
    cells = [cell for points in icon_pixels(name, pixels).values() for cell in points]
    if not cells:
        return 0, 0, 0, 0
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def glyph_extent(name, pixels):
    return max(icon_bounds(name, pixels)[2:])


@lru_cache(maxsize=None)
def icon_fit_size(name, target):
    spans = icon_spans(name)
    if not spans:
        return target
    xs = [value for column, _, width, _ in spans for value in (column, column + width)]
    ys = [value for _, row, _, _ in spans for value in (row, row + 1)]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    size = max(1, round(target * ICON_GRID / extent))
    while size > 1 and glyph_extent(name, size) > target:
        size -= 1
    while glyph_extent(name, size + 1) <= target:
        size += 1
    return size
