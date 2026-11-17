from dataclasses import dataclass
from .baking import bake_pass, emission_tree
from .signals import map_signal
from .tiles import create, variant

CAGE_EXTRUSION = .1


@dataclass(frozen=True)
class MeshMap:
    key: str
    label: str
    needs_source: bool = False


MESH_MAPS = (MeshMap('ao', 'Ambient occlusion'), MeshMap('curvature', 'Curvature'), MeshMap('thickness', 'Thickness'),
             MeshMap('position', 'Position'), MeshMap('world_normal', 'World normal'), MeshMap('id', 'ID'),
             MeshMap('normal', 'Normal', needs_source=True))
MESH_MAP = {item.key: item for item in MESH_MAPS}


def object_size(obj):
    return max(max(obj.dimensions), 1e-3)


def map_key_image(obj, data, key):
    item = data.maps.get(key)
    if item is None:
        item = data.maps.add()
        item.name = key
    if item.image is None or tuple(item.image.size) != (data.resolution, data.resolution):
        item.image = create(data, f'DP {obj.name} {data.name} {key} map', (0.0, 0.0, 0.0, 0.0), True)
    return item.image


def store(data, key_image, number, pixels):
    image = variant(data, key_image, number)
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    image.pack()


def bake_maps(context, obj, project, wanted, keys, source, samples):
    size = object_size(obj)
    baked = []
    for key in keys:
        if MESH_MAP[key].needs_source and source is None:
            continue
        if key == 'normal':
            results = bake_pass(context, obj, project, wanted, lambda data: emission_tree(data.material.node_tree, (0.5, 0.5, 1.0, 1.0)),
                                'NORMAL', samples, (source,), normal_space='TANGENT', use_selected_to_active=True,
                                cage_extrusion=CAGE_EXTRUSION * size)
        else:
            def prepare(data, key=key):
                tree = data.material.node_tree
                emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
                emission = next(node for node in tree.nodes if node.type == 'EMISSION')
                tree.links.new(map_signal(tree.nodes, tree.links, key, size), emission.inputs['Color'])
            results = bake_pass(context, obj, project, wanted, prepare, 'EMIT', samples)
        for (index, number), pixels in results.items():
            data = project.sets[index]
            store(data, map_key_image(obj, data, key), number, pixels)
        baked.append(key)
    return baked
