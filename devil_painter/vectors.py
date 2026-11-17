import hashlib
import math
import os
import re
import sys
import xml.etree.ElementTree as tree
from pathlib import Path
import bpy
import numpy

STENCIL_SIZE = 512
CURVE_STEPS = 16
BUILTIN_FONT = '<builtin>'
FONT_SUFFIXES = {'.ttf', '.otf'}
MAX_FONTS = 60
NUMBER = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
COMMAND = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def font_folders():
    if sys.platform == 'win32':
        return [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts']
    if sys.platform == 'darwin':
        return [Path('/Library/Fonts'), Path('/System/Library/Fonts'), Path.home() / 'Library' / 'Fonts']
    return [Path('/usr/share/fonts'), Path.home() / '.fonts', Path.home() / '.local' / 'share' / 'fonts']


def system_fonts():
    found = []
    for folder in font_folders():
        if folder.is_dir():
            found += [path for path in folder.rglob('*') if path.suffix.lower() in FONT_SUFFIXES]
    return sorted(found, key=lambda path: path.stem.lower())[:MAX_FONTS]


def fill(polygons, width, height):
    mask = numpy.zeros((height, width), dtype=bool)
    edges = []
    for polygon in polygons:
        points = numpy.asarray(polygon, dtype=numpy.float64)
        if len(points) >= 3:
            edges.append(numpy.concatenate([points, numpy.roll(points, -1, axis=0)], axis=1))
    if not edges:
        return mask
    edges = numpy.concatenate(edges)
    x0, y0, x1, y1 = edges.T
    columns = numpy.arange(width) + .5
    for row in range(height):
        y = row + .5
        crossing = (y0 <= y) != (y1 <= y)
        if not crossing.any():
            continue
        xs = x0[crossing] + (y - y0[crossing]) * (x1[crossing] - x0[crossing]) / (y1[crossing] - y0[crossing])
        mask[row] = (numpy.searchsorted(numpy.sort(xs), columns) % 2) == 1
    return mask


def text_polygons(text, font_path):
    font = bpy.data.fonts.load(font_path or BUILTIN_FONT, check_existing=True)
    curve = bpy.data.curves.new('DP Text', 'FONT')
    curve.body, curve.font = text, font
    holder = bpy.data.objects.new('DP Text', curve)
    bpy.context.scene.collection.objects.link(holder)
    try:
        evaluated = holder.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        polygons = [[tuple(mesh.vertices[index].co.xy) for index in triangle.vertices] for triangle in mesh.loop_triangles]
        evaluated.to_mesh_clear()
    finally:
        bpy.data.objects.remove(holder)
        bpy.data.curves.remove(curve)
    return polygons


def union(polygons, width, height):
    mask = numpy.zeros((height, width), dtype=bool)
    for polygon in polygons:
        mask |= fill([polygon], width, height)
    return mask


def numbers(text):
    return [float(value) for value in NUMBER.findall(text or '')]


def transform_of(text):
    matrix = numpy.identity(3)
    for name, values in re.findall(r'(\w+)\s*\(([^)]*)\)', text or ''):
        args = numbers(values)
        if name == 'matrix' and len(args) == 6:
            step = numpy.array([[args[0], args[2], args[4]], [args[1], args[3], args[5]], [0, 0, 1]])
        elif name == 'translate':
            step = numpy.array([[1, 0, args[0]], [0, 1, args[1] if len(args) > 1 else 0], [0, 0, 1]])
        elif name == 'scale':
            step = numpy.diag([args[0], args[1] if len(args) > 1 else args[0], 1])
        elif name == 'rotate':
            angle = math.radians(args[0])
            step = numpy.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
        else:
            continue
        matrix = matrix @ step
    return matrix


def bezier(points, steps=CURVE_STEPS):
    points = numpy.array(points, dtype=numpy.float64)
    degree = len(points) - 1
    result = []
    for step in range(1, steps + 1):
        t = step / steps
        result.append(tuple(sum(math.comb(degree, index) * (1 - t) ** (degree - index) * t ** index * points[index] for index in range(degree + 1))))
    return result


def path_polygons(data):
    tokens = COMMAND.findall(data or '')
    polygons, current, start, point, last_control, command = [], [], (0.0, 0.0), (0.0, 0.0), None, 'M'
    position = 0

    def take(count):
        nonlocal position
        values = [float(value) for value in tokens[position:position + count]]
        position += count
        return values

    while position < len(tokens):
        if tokens[position].isalpha():
            command = tokens[position]
            position += 1
            if command in 'Zz':
                if current:
                    polygons.append(current)
                current, point, last_control = [], start, None
                continue
        relative = command.islower()
        base = point if relative else (0.0, 0.0)
        kind = command.upper()
        if kind == 'M':
            x, y = take(2)
            if current:
                polygons.append(current)
            point = start = (base[0] + x, base[1] + y)
            current = [point]
            command = 'l' if relative else 'L'
        elif kind in 'LHV':
            if kind == 'L':
                x, y = take(2)
                point = (base[0] + x, base[1] + y)
            elif kind == 'H':
                point = ((point[0] if relative else 0.0) + take(1)[0], point[1])
            else:
                point = (point[0], (point[1] if relative else 0.0) + take(1)[0])
            current.append(point)
            last_control = None
        elif kind in 'CS':
            values = take(6 if kind == 'C' else 4)
            first = (base[0] + values[0], base[1] + values[1]) if kind == 'C' else (
                (2 * point[0] - last_control[0], 2 * point[1] - last_control[1]) if last_control else point)
            rest = values[2:] if kind == 'C' else values
            second, end = (base[0] + rest[0], base[1] + rest[1]), (base[0] + rest[2], base[1] + rest[3])
            current += bezier([point, first, second, end])
            point, last_control = end, second
        elif kind in 'QT':
            values = take(4 if kind == 'Q' else 2)
            control = (base[0] + values[0], base[1] + values[1]) if kind == 'Q' else (
                (2 * point[0] - last_control[0], 2 * point[1] - last_control[1]) if last_control else point)
            end = (base[0] + values[-2], base[1] + values[-1])
            current += bezier([point, control, end])
            point, last_control = end, control
        elif kind == 'A':
            values = take(7)
            point = (base[0] + values[5], base[1] + values[6])
            current.append(point)
            last_control = None
        else:
            position += 1
    if current:
        polygons.append(current)
    return polygons


def attribute(element, key):
    values = numbers(element.get(key))
    return values[0] if values else 0.0


def shape_polygons(element):
    name = element.tag.rsplit('}', 1)[-1]
    get = lambda key: attribute(element, key)
    if name == 'path':
        return path_polygons(element.get('d'))
    if name in {'polygon', 'polyline'}:
        values = numbers(element.get('points'))
        return [list(zip(values[0::2], values[1::2]))]
    if name == 'rect':
        x, y, w, h = get('x'), get('y'), get('width'), get('height')
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
    if name in {'circle', 'ellipse'}:
        cx, cy = get('cx'), get('cy')
        rx = get('r') if name == 'circle' else get('rx')
        ry = get('r') if name == 'circle' else get('ry')
        return [[(cx + rx * math.cos(step * math.tau / 48), cy + ry * math.sin(step * math.tau / 48)) for step in range(48)]]
    return []


def svg_polygons(path):
    root = tree.parse(str(path)).getroot()
    polygons = []

    def walk(element, matrix):
        matrix = matrix @ transform_of(element.get('transform'))
        for polygon in shape_polygons(element):
            if len(polygon) >= 3:
                points = numpy.c_[numpy.asarray(polygon, dtype=numpy.float64), numpy.ones(len(polygon))] @ matrix.T
                polygons.append(points[:, :2])
        for child in element:
            walk(child, matrix)
    walk(root, numpy.identity(3))
    return [numpy.c_[polygon[:, 0], -polygon[:, 1]] for polygon in polygons]


def rasterize(polygons, size=STENCIL_SIZE, triangles=False):
    if not polygons:
        return numpy.zeros((size, size, 4), dtype=numpy.float32)
    points = numpy.concatenate([numpy.asarray(polygon, dtype=numpy.float64) for polygon in polygons])
    low, high = points.min(axis=0), points.max(axis=0)
    span = max(float((high - low).max()), 1e-9)
    width = max(8, int(round(size * (high[0] - low[0]) / span)))
    height = max(8, int(round(size * (high[1] - low[1]) / span)))
    scaled = [(numpy.asarray(polygon, dtype=numpy.float64) - low) / span * (size - 1) for polygon in polygons]
    mask = union(scaled, width, height) if triangles else fill(scaled, width, height)
    pixels = numpy.ones((height, width, 4), dtype=numpy.float32)
    pixels[..., 3] = mask
    return pixels


def stencil_image(name, pixels):
    height, width = pixels.shape[:2]
    image = bpy.data.images.get(name)
    if image is None or tuple(image.size) != (width, height):
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new(name, width, height, alpha=True)
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    return image


def text_stencil(text, font_path):
    return stencil_image('DP Text Stencil', rasterize(text_polygons(text, font_path), triangles=True))


def svg_stencil(path):
    return stencil_image(f'DP {Path(path).stem} Stencil', rasterize(svg_polygons(path)))


def preview_file(path, folder):
    digest = hashlib.sha1(f'{path}:{Path(path).stat().st_mtime}'.encode('utf-8')).hexdigest()[:20]
    target = folder / f'{digest}.png'
    if not target.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        pixels = rasterize(svg_polygons(path), 96)
        pixels[..., :3] = 1 - pixels[..., 3:]
        pixels[..., 3] = 1.0
        image = bpy.data.images.new(target.stem, pixels.shape[1], pixels.shape[0], alpha=True)
        try:
            image.pixels.foreach_set(pixels.ravel())
            image.filepath_raw = str(target)
            image.file_format = 'PNG'
            image.save()
        finally:
            bpy.data.images.remove(image)
    return str(target)
