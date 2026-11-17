import math
import bpy
import numpy
from . import strokes
from .brushes import stencil_frame

SHOT_NAME = 'DP Projection'


def view_pixels(data, width, height):
    position, dimension, angle = stencil_frame(data, width, height)
    stencil = strokes.read(data.brush_stencil)
    rows, columns = numpy.mgrid[0:height, 0:width].astype(numpy.float32) + .5
    dx, dy = columns - position[0], rows - position[1]
    cosine, sine = math.cos(-angle), math.sin(-angle)
    u = ((dx * cosine - dy * sine) / dimension[0] + 1) / 2
    v = ((dx * sine + dy * cosine) / dimension[1] + 1) / 2
    inside = (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
    pixels = numpy.zeros((height, width, 4), dtype=numpy.float32)
    pixels[inside] = stencil[(v[inside] * stencil.shape[0]).astype(int), (u[inside] * stencil.shape[1]).astype(int)]
    return pixels


def flattened(matrix):
    return [value for row in matrix.transposed() for value in row]


def project(context, window, area, region, obj, data, buffered):
    shot = bpy.data.images.new(SHOT_NAME, region.width, region.height, alpha=True)
    try:
        shot.pixels.foreach_set(view_pixels(data, region.width, region.height).ravel())
        view = area.spaces.active.region_3d
        shot['win_mat'], shot['view_mat'] = flattened(view.window_matrix), flattened(view.view_matrix)
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.paint.project_image('EXEC_DEFAULT', False, image=shot.name)
    finally:
        bpy.data.images.remove(shot)
    entry = strokes.merge(obj, data, None, 'PAINT') if buffered else None
    bpy.ops.ed.undo_push(message='Devil Painter: projection')
    strokes.record(entry)
    return f'Projected {data.brush_stencil.name} through the view.'
