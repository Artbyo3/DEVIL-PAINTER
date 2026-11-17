import math
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector
from .sets import hit_under

DRIP_EVERY = 5
DRIP_STEPS = 40
DRIP_STEP = .012
SPLAT_EVERY = 4
SPLAT_COUNT = 6
SPLAT_REACH = 3.0
SPEED_FADE = 40.0


def spline(points, steps=6):
    if len(points) < 3:
        return points
    padded = [points[0], *points, points[-1]]
    result = []
    for index in range(1, len(padded) - 2):
        p0, p1, p2, p3 = (numpy.array(padded[index + offset]) for offset in (-1, 0, 1, 2))
        for step in range(steps):
            t = step / steps
            result.append(tuple(.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    result.append(tuple(points[-1]))
    return result


def by_speed(points):
    shaped = []
    for index, (point, pressure) in enumerate(points):
        previous = points[max(index - 1, 0)][0]
        shaped.append((point, pressure * max(.15, 1 - math.dist(point, previous) / SPEED_FADE)))
    return [shaped]


def splatter(points, size, seed):
    random = numpy.random.default_rng(seed)
    trails = []
    for point, pressure in points[::SPLAT_EVERY]:
        for _ in range(SPLAT_COUNT):
            angle, reach = random.uniform(0, math.tau), random.uniform(.3, SPLAT_REACH) * size
            spot = (point[0] + math.cos(angle) * reach, point[1] + math.sin(angle) * reach)
            trails.append([(spot, pressure * random.uniform(.2, .8))])
    return trails


def drips(region, view, obj, points, seed):
    random = numpy.random.default_rng(seed)
    inverse = obj.matrix_world.inverted()
    gravity = (inverse.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    step = max(obj.dimensions) * DRIP_STEP / max(max(obj.scale), 1e-6)
    trails = []
    for point, pressure in points[::DRIP_EVERY]:
        face, location = hit_under(region, view, obj, point)
        if face < 0:
            continue
        position, normal = Vector(location), obj.data.polygons[face].normal
        trail = []
        length = int(DRIP_STEPS * random.uniform(.4, 1.0))
        for index in range(length):
            flow = gravity - normal * gravity.dot(normal)
            if flow.length < 1e-4:
                break
            position = position + flow.normalized() * step
            found, position, normal, _ = obj.closest_point_on_mesh(position)
            if not found:
                break
            spot = view3d_utils.location_3d_to_region_2d(region, view, obj.matrix_world @ position)
            if spot is None:
                break
            trail.append(((spot.x, spot.y), pressure * (1 - .7 * index / max(length, 1))))
        if trail:
            trails.append(trail)
    return trails


def trails(kind, region, view, obj, points, size):
    seed = int(sum(point[0] + point[1] for point, _ in points)) % 100000
    if kind == 'SPEED':
        return by_speed(points)
    if kind == 'SPLATTER':
        return splatter(points, size, seed)
    return [points] + drips(region, view, obj, points, seed)
