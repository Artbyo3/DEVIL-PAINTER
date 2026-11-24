import hashlib
import bpy
from .tiles import variant

KEY = 'devil_painter_below'
PREFIX = 'DP Below '
_state = dict(revision=0)
_painted = {}
_fresh = {}


def touch(image=None):
    if image is None:
        _state['revision'] += 1
    else:
        _painted[image.name_full] = _painted.get(image.name_full, 0) + 1


def revision(images):
    return _state['revision'], tuple(_painted.get(image.name_full, 0) for image in images)


def owner(data):
    return data.id_data.name, data.name


def tile(data, key, number):
    digest = hashlib.sha1('|'.join((*owner(data), key)).encode()).hexdigest()[:16]
    name = f'{PREFIX}{digest} {number}'
    image = bpy.data.images.get(name)
    if image is not None and tuple(image.size) == (data.resolution, data.resolution):
        return image
    if image is not None:
        bpy.data.images.remove(image)
    image = bpy.data.images.new(name, data.resolution, data.resolution, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image[KEY] = key
    return image


def tile_variant(data, image, number):
    key = image.get(KEY) if image is not None else None
    return variant(data, image, number) if key is None else tile(data, key, number)


def fresh(data, stamp):
    return _fresh.get(owner(data)) == stamp


def mark(data, stamp):
    _fresh[owner(data)] = stamp


def write(image, pixels):
    image.pixels.foreach_set(pixels.ravel())
    image.update()


def cached_images():
    return [image for image in bpy.data.images if image.get(KEY) is not None and image.users]
