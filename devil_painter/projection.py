from array import array
import math
import bpy
import numpy
from . import history, strokes
from .brushes import stencil_frame
from .document import active_tile, paint_target
from .tiles import variant

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


def project(context, window, area, region, obj, data, buffered, pixels=None, label=''):
    direct = None if buffered else variant(data, paint_target(data), active_tile(data))
    snapshot = strokes.read(direct).copy() if direct is not None else None
    shot = bpy.data.images.new(SHOT_NAME, region.width, region.height, alpha=True)
    try:
        shot.pixels.foreach_set((view_pixels(data, region.width, region.height) if pixels is None else pixels).ravel())
        space = area.spaces.active
        view = space.region_3d
        ortho = 1.0 if view.view_perspective == 'ORTHO' else 0.0
        shot['view_data'] = array('f', flattened(view.window_matrix) + flattened(view.view_matrix) + [space.clip_start, space.clip_end, ortho])
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.paint.project_image('EXEC_DEFAULT', False, image=shot.name)
    finally:
        bpy.data.images.remove(shot)
    entry = strokes.merge(obj, data, None, 'PAINT') if buffered else strokes.diff(direct, snapshot)
    name = label or data.brush_stencil.name
    history.push(f'Projected {name}', entry)
    return f'Projected {name} through the view.'
