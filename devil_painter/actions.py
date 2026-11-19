import json
from pathlib import Path
import bpy
import numpy
from . import baking, bridge, brushes, compositing, exporting, library, meshmaps, painting, projects, sets, smart, strokes, tiles
from .blending import linear_to_srgb
from .effects import EFFECT_LABEL, copy_effect, find_effect, level_target, mask_effects
from .masks import GENERATOR, GENERATOR_FIELDS
from .meshmaps import MESH_MAP
from .blending import BLEND_MODES, CHANNEL, FOLDER_BLENDS, NORMAL_DETAIL
from .procedural import PATTERN
from .document import PROJECTIONS, PROJECTORS, SLOT_FIELDS, geometry_attribute, active_effect, active_layer, adopt_layer_generator, add_set_channels, add_slots, children, descendants, fill_slots, find_layer, layer_index, set_slot_value

KIND_NAMES = {'PAINT': 'Paint', 'FILL': 'Fill', 'FOLDER': 'Folder'}
LAYER_FIELDS = ('kind', 'visible', 'opacity', 'projection', 'tiling', 'proj_offset', 'proj_rotation', 'proj_size', 'tile_match', 'material', 'folder_blend', 'geo_mask', 'link_set', 'link_uid')
ID_TOLERANCE = .15
LAST_LAYER = 'A texture set keeps at least one layer. Add another layer before removing this one.'
SAME_AS_FOLDER = 'FOLDER'
EFFECT_BLENDS = {'PAINT': 'MIX', 'FILL': 'MULTIPLY', 'COMPARE': 'MULTIPLY', 'ANCHOR': 'MULTIPLY', 'LEVELS': 'MIX', 'FILTER': 'MIX', 'ID_COLOR': 'MULTIPLY', 'GENERATOR': 'MULTIPLY'}


def image_for(obj, data, label, opaque):
    return tiles.create(data, f'DP {obj.name} {data.name} {label}', (1.0, 1.0, 1.0, 1.0) if opaque else (0.0, 0.0, 0.0, 0.0))


def has_uvs(obj):
    return bool(obj.data.uv_layers)


def refresh(context, obj, data, message):
    strokes.ensure_canvases(obj, data)
    for item in obj.devil_painter.sets:
        compositing.sync(item)
    painting.update_canvas(context, data)
    bpy.ops.ed.undo_push(message='Devil Painter: ' + message)
    strokes.record(None)
    return message


def prepare(obj, data):
    fill_slots(data.brush_slots)
    add_set_channels(data)
    adopted = False
    for layer in data.layers:
        if layer.kind in {'PAINT', 'FILL'}:
            fill_slots(layer.slots)
        adopted = adopt_layer_generator(data, layer) or adopted
    strokes.ensure_buffer(obj, data)
    if adopted:
        compositing.sync(data)


def start(context, obj, resolutions, use_udim, template_name, normal_format, normal_space, unwrap_mode):
    if obj is None or obj.type != 'MESH':
        raise ValueError('Select a mesh object to paint.')
    unwrapped = ''
    if not has_uvs(obj):
        obj.data.uv_layers.new(name='UVMap')
        projects.unwrap(context, obj, unwrap_mode)
        unwrapped = f' It had no UVs, so it was unwrapped ({dict(projects.UNWRAP_MODES)[unwrap_mode]}).'
    template = projects.find_template(template_name)
    project = obj.devil_painter
    project.sets.clear()
    project.uv_map = sets.uv_name(obj)
    project.active_set, project.active_tile = 0, tiles.FIRST_TILE
    project.template, project.normal_format, project.normal_space = template['name'], normal_format, normal_space
    layout = sets.detect(obj, use_udim)
    if not obj.material_slots:
        obj.data.materials.append(None)
    for index, (name, found) in enumerate(layout):
        add_set(obj, project, index, name, found, resolutions[index] if index < len(resolutions) else resolutions[-1], template)
    project.enabled = True
    painting.enter_paint_mode(context, obj)
    for data in project.sets:
        project.active_set = list(project.sets).index(data)
        add_layer(context, obj, data, 'PAINT')
    project.active_set = 0
    project.active_tile = tiles.numbers(project.sets[0])[0]
    painting.activate_tool(context, 'PAINT')
    sets.mask_faces(obj, project)
    painting.update_canvas(context, project.sets[0])
    brushes.sync(context, project.sets[0])
    tile_count = sum(len(tiles.numbers(data)) for data in project.sets)
    return f'Painting {obj.name}: {len(project.sets)} texture sets, {tile_count} tiles.' + unwrapped


def add_set(obj, project, index, name, found, resolution, template):
    data = project.sets.add()
    data.name, data.slot, data.resolution = name, index, resolution
    for number in found:
        data.tiles.add().number = number
    prepare(obj, data)
    projects.apply_template(project, data, template)
    data.material = bpy.data.materials.new(f'Devil Painter {obj.name} {name}')
    obj.material_slots[index].material = data.material


def activate(context, obj, project, index, tile):
    if index == project.active_set and tile == project.active_tile:
        return ''
    project.active_set = index
    data = project.sets[index]
    project.active_tile = tile if tile in tiles.numbers(data) else tiles.numbers(data)[0]
    sets.mask_faces(obj, project)
    painting.update_canvas(context, data)
    compositing.sync(data)
    brushes.sync(context, data)
    count = len(tiles.numbers(data))
    return f'Painting {data.name}' + (f', tile {project.active_tile}.' if count > 1 else '.')


def toggle_set_visible(context, obj, project, index):
    data = project.sets[index]
    data.visible = not data.visible
    data.export = data.visible
    compositing.sync(data)
    bpy.ops.ed.undo_push(message='Devil Painter: texture set visibility')
    strokes.record(None)
    return f'{data.name} {"enabled" if data.visible else "disabled"}.'


def set_channel_enabled(context, obj, project, key, enabled, every_set):
    targets = list(project.sets) if every_set else [project.sets[project.active_set]]
    for data in targets:
        data.channels[key].enabled = enabled
        if not enabled and data.solo == key:
            data.solo = ''
        strokes.ensure_canvases(obj, data)
        compositing.sync(data)
    data = project.sets[project.active_set]
    scope = 'every texture set' if every_set else data.name
    return refresh(context, obj, data, f'{CHANNEL[key].label} {"added to" if enabled else "removed from"} {scope}.')


def set_project_value(context, obj, project, field, value):
    setattr(project, field, value)
    for data in project.sets:
        compositing.sync(data)
    return refresh(context, obj, project.sets[project.active_set], 'Project settings updated.')


def set_set_value(context, obj, data, field, value, commit):
    setattr(data, field, value)
    if commit:
        return refresh(context, obj, data, f'{data.name} shader settings updated.')
    compositing.sync(data)
    return ''


def carry(obj, source, target, key, name):
    created = None
    for number in tiles.numbers(target):
        origin = tiles.variant(source, key, number) if number in tiles.numbers(source) else None
        label = name if created is None else f'{name} {number}'
        image = tiles.duplicate(origin, label) if origin is not None else tiles.blank(label, target.resolution, (0.0, 0.0, 0.0, 0.0), key.colorspace_settings.is_data)
        if tuple(image.size) != (target.resolution, target.resolution):
            image.scale(target.resolution, target.resolution)
        image.pack()
        if created is None:
            created = image
        else:
            tiles.register(target, created, number, image)
    return created


def transfer(obj, source, target, layer, parent):
    target.serial += 1
    uid = f'L{target.serial}'
    values = {key: getattr(layer, key) for key in LAYER_FIELDS}
    copy = target.layers.add()
    for key, value in values.items():
        setattr(copy, key, value)
    copy.uid, copy.parent, copy.name = uid, parent, layer.name
    base = f'DP {obj.name} {target.name} {uid}'
    for slot in layer.slots:
        item = copy.slots.add()
        item.name = slot.name
        for key in SLOT_FIELDS + ('image',):
            setattr(item, key, getattr(slot, key))
        if layer.kind == 'PAINT' and slot.source == 'IMAGE' and slot.image is not None:
            item.image = carry(obj, source, target, slot.image, f'{base} {slot.name}')
    if layer.image is not None:
        copy.image = carry(obj, source, target, layer.image, base)
    if layer.mask is not None:
        copy.mask = carry(obj, source, target, layer.mask, base + ' mask')
    copy_channel_blends(layer, copy)
    copy_effects(obj, source, target, layer.effects, copy)
    for child in children(source.layers, layer.uid):
        transfer(obj, source, target, child, uid)
    return uid


def copy_channel_blends(source, target):
    for item in source.channel_blends:
        copy = target.channel_blends.add()
        copy.name, copy.blend = item.name, item.blend


def copy_effects(obj, source, target, effects, copy):
    for effect in effects:
        target.serial += 1
        item = copy.effects.add()
        copy_effect(effect, item)
        item.uid = f'E{target.serial}'
        if effect.kind == 'PAINT' and effect.image is not None:
            item.image = carry(obj, source, target, effect.image, f'DP {obj.name} {target.name} {copy.uid} {item.uid}')


def move_to_set(context, obj, project, index):
    source = project.sets[project.active_set]
    target = project.sets[index]
    layer = active_layer(source)
    doomed_layers(source, [layer.uid])
    name = layer.name
    uid = transfer(obj, source, target, layer, '')
    remove_layers(source, [layer.uid])
    compositing.sync(source)
    target.active_uid = uid
    prepare(obj, target)
    message = activate(context, obj, project, index, project.active_tile)
    return refresh(context, obj, target, f'Moved {name} to {target.name}. {message}')


def reimport_mesh(context, obj, project, mesh):
    mode = obj.mode
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    faceless, new_slots = projects.swap_mesh(obj, project, mesh)
    labels = sets.slot_names(obj)
    template, resolution = projects.find_template(project.template), project.sets[project.active_set].resolution
    use_udim, first = tiles.numbers(project.sets[0]) != [tiles.FIRST_TILE], len(project.sets)
    for index in new_slots:
        found = tiles.slot_tiles(obj.data, project.uv_map, index, use_udim) if project.uv_map else [tiles.FIRST_TILE]
        add_set(obj, project, index, labels[index] if index < len(labels) else f'Slot {index + 1}', found, resolution, template)
    added = list(project.sets)[first:]
    for data in project.sets:
        prepare(obj, data)
        strokes.ensure_canvases(obj, data)
        data.material[compositing.SIGNATURE_KEY] = ''
        compositing.sync(data)
    painting.enter_paint_mode(context, obj)
    for data in added:
        add_layer(context, obj, data, 'PAINT')
    if project.sets[project.active_set].name in faceless and len(faceless) < len(project.sets):
        project.active_set = next(index for index, data in enumerate(project.sets) if data.name not in faceless)
    sets.mask_faces(obj, project)
    notes = [f'{name} has no faces now, its layers are kept.' for name in faceless]
    notes += [f'New texture set {data.name}.' for data in added]
    return refresh(context, obj, project.sets[project.active_set], ' '.join(['Reimported.', *notes]))


def new_effect(data, layer, kind, target):
    data.serial += 1
    effect = layer.effects.add()
    effect.uid, effect.kind, effect.target = f'E{data.serial}', kind, target
    effect.blend = EFFECT_BLENDS[kind]
    data.target, data.active_effect = 'EFFECT', effect.uid
    return effect


def add_effect(context, obj, data, kind, target):
    layer = active_layer(data)
    effect = new_effect(data, layer, kind, target)
    if kind == 'PAINT':
        effect.image = tiles.create(data, f'DP {obj.name} {data.name} {layer.uid} {effect.uid}', (0.0, 0.0, 0.0, 0.0))
    if kind == 'FILL':
        effect.source = 'PATTERN'
    if kind == 'FILTER' and target == 'CONTENT':
        effect.filter = 'HSV'
    if kind == 'ANCHOR':
        effect.channel = 'base_color'
    if kind == 'ID_COLOR':
        effect.amount = ID_TOLERANCE
    return refresh(context, obj, data, f'{EFFECT_LABEL[kind]} effect added to the {target.lower()} of {layer.name}.')


def select_effect(context, obj, data, uid, effect_uid):
    data.active_uid, data.target, data.active_effect = uid, 'EFFECT', effect_uid
    painting.update_canvas(context, data)
    return 'Effect selected.'


def edit_effect(context, obj, data, field, value, commit):
    layer = active_layer(data)
    effect = find_effect(layer, data.active_effect)
    field, index = level_target(effect, field)
    if index is not None:
        values = list(getattr(effect, field))
        values[index] = value
        value = tuple(values)
    setattr(effect, field, value)
    if commit:
        return refresh(context, obj, data, f'{layer.name} effect updated.')
    compositing.sync(data)
    return ''


def toggle_effect(context, obj, data, uid, effect_uid):
    effect = find_effect(find_layer(data, uid), effect_uid)
    effect.enabled = not effect.enabled
    return refresh(context, obj, data, f'Effect {"enabled" if effect.enabled else "disabled"}.')


def delete_effect(context, obj, data):
    layer = active_layer(data)
    index = next(position for position, effect in enumerate(layer.effects) if effect.uid == data.active_effect)
    image = layer.effects[index].image
    layer.effects.remove(index)
    if image is not None and image.name.startswith('DP '):
        tiles.release(data, image)
    data.target, data.active_effect = 'CONTENT', ''
    return refresh(context, obj, data, 'Effect deleted.')


def move_effect(context, obj, data, uid, effect_uid, index):
    layer = find_layer(data, uid)
    current = next(position for position, effect in enumerate(layer.effects) if effect.uid == effect_uid)
    layer.effects.move(current, max(0, min(len(layer.effects) - 1, index)))
    return refresh(context, obj, data, 'Effect reordered.')


def drop_layer(context, obj, data, uid, target_uid, mode):
    if uid == target_uid or target_uid in descendants(data.layers, uid):
        return 'A layer cannot move into itself.'
    layer, target = find_layer(data, uid), find_layer(data, target_uid)
    name = layer.name
    if mode == 'INTO':
        if target.kind != 'FOLDER':
            return 'Layers can only be dropped into folders.'
        layer.parent = target.uid
        return refresh(context, obj, data, f'Moved {name} into {target.name}.')
    layer.parent = target.parent
    source, destination = layer_index(data, uid), layer_index(data, target_uid)
    if mode == 'ABOVE':
        destination = destination + 1 if source > destination else destination
    else:
        destination = destination if source > destination else destination - 1
    data.layers.move(source, max(0, destination))
    return refresh(context, obj, data, f'Moved {name}.')


def group_layers(context, obj, data, uids):
    ordered = [layer for layer in data.layers if layer.uid in uids]
    data.active_uid = ordered[-1].uid
    folder = new_layer(data, 'FOLDER')
    folder.name = f'Folder {sum(1 for item in data.layers if item.kind == "FOLDER")}'
    folder.parent = ordered[-1].parent
    folder_uid = folder.uid
    nested = {child for uid in uids for child in descendants(data.layers, uid)}
    for uid in uids:
        if uid not in nested:
            find_layer(data, uid).parent = folder_uid
    data.active_uid = folder_uid
    return refresh(context, obj, data, f'Grouped {len(uids)} layers into a folder.')


def doomed_layers(data, uids):
    doomed = set(uids)
    for uid in uids:
        doomed |= set(descendants(data.layers, uid))
    if all(layer.uid in doomed for layer in data.layers):
        raise ValueError(LAST_LAYER)
    return doomed


def successor(data, doomed):
    if data.active_uid not in doomed:
        return data.active_uid
    parent = active_layer(data).parent
    while parent in doomed:
        parent = find_layer(data, parent).parent
    siblings = [layer for layer in children(data.layers, parent) if layer.uid not in doomed]
    return siblings[-1].uid if siblings else parent


def remove_layers(data, uids):
    doomed = doomed_layers(data, uids)
    data.active_uid = successor(data, doomed)
    for position in range(len(data.layers) - 1, -1, -1):
        layer = data.layers[position]
        if layer.uid in doomed:
            for image in owned_images(layer):
                tiles.release(data, image)
            data.layers.remove(position)
    data.target = 'CONTENT'


def set_layers_visible(context, obj, data, uids, visible):
    for uid in uids:
        find_layer(data, uid).visible = visible
    return refresh(context, obj, data, f'{len(uids)} layers {"shown" if visible else "hidden"}.')


def delete_layers(context, obj, data, uids):
    remove_layers(data, uids)
    return refresh(context, obj, data, f'Deleted {len(uids)} layers.')


def duplicate_layers(context, obj, data, uids):
    for uid in [layer.uid for layer in data.layers if layer.uid in uids]:
        source = find_layer(data, uid)
        copy_layer(obj, data, source, source.parent, layer_index(data, uid) + 1)
    return refresh(context, obj, data, f'Duplicated {len(uids)} layers.')


def paste_layers(context, obj, project, source_index, uids):
    source, target = project.sets[source_index], project.sets[project.active_set]
    pasted = []
    for uid in uids:
        layer = find_layer(source, uid)
        if layer is not None:
            pasted.append(transfer(obj, source, target, layer, ''))
    target.active_uid = pasted[-1] if pasted else target.active_uid
    prepare(obj, target)
    return refresh(context, obj, target, f'Pasted {len(pasted)} layers.')


def paste_mask(context, obj, project, source_index, uid):
    source, target = project.sets[source_index], project.sets[project.active_set]
    origin, layer = find_layer(source, uid), active_layer(target)
    if origin.mask is not None:
        if layer.mask is not None:
            tiles.release(target, layer.mask)
        layer.mask = carry(obj, source, target, origin.mask, f'DP {obj.name} {target.name} {layer.uid} mask')
    layer.geo_mask = origin.geo_mask
    copy_effects(obj, source, target, mask_effects(origin), layer)
    return refresh(context, obj, target, f'Pasted the mask of {origin.name} onto {layer.name}.')


def paste_effects(context, obj, project, source_index, uid):
    source, target = project.sets[source_index], project.sets[project.active_set]
    origin, layer = find_layer(source, uid), active_layer(target)
    copy_effects(obj, source, target, list(origin.effects), layer)
    return refresh(context, obj, target, f'Pasted {len(origin.effects)} effects onto {layer.name}.')


def instance_into(context, obj, project, index):
    source = project.sets[project.active_set]
    layer = active_layer(source)
    target = project.sets[index]
    target.serial += 1
    link = target.layers.add()
    link.uid, link.kind, link.name = f'L{target.serial}', 'INSTANCE', layer.name
    link.link_set, link.link_uid = source.name, layer.uid
    return refresh(context, obj, source, f'{layer.name} is now instanced in {target.name}.')


def geometry_values(obj, data, layer):
    mesh = obj.data
    name = geometry_attribute(data, layer)
    attribute = mesh.attributes.get(name) or mesh.attributes.new(name, 'FLOAT', 'FACE')
    values = numpy.zeros(len(mesh.polygons), dtype=numpy.float32)
    attribute.data.foreach_get('value', values)
    return attribute, values


def set_geometry(obj, data, layer, values):
    attribute, _ = geometry_values(obj, data, layer)
    attribute.data.foreach_set('value', values)
    obj.data.update()


def toggle_geometry_mask(context, obj, data):
    layer = active_layer(data)
    layer.geo_mask = not layer.geo_mask
    if layer.geo_mask:
        geometry_values(obj, data, layer)
    return refresh(context, obj, data, f'Geometry mask {"on" if layer.geo_mask else "off"} for {layer.name}.')


def pick_geometry(context, obj, data, face, island):
    layer = active_layer(data)
    _, values = geometry_values(obj, data, layer)
    faces = sets.island_of(obj.data, face) if island else [face]
    values[faces] = 0.0 if values[face] > .5 else 1.0
    set_geometry(obj, data, layer, values)
    bpy.ops.ed.undo_push(message='Devil Painter: geometry mask')
    strokes.record(None)
    return f'{int(values.sum())} faces in the geometry mask of {layer.name}.'


def edit_geometry(context, obj, data, operation):
    layer = active_layer(data)
    _, values = geometry_values(obj, data, layer)
    values = numpy.zeros_like(values) if operation == 'CLEAR' else 1.0 - values
    set_geometry(obj, data, layer, values)
    return refresh(context, obj, data, f'Geometry mask {"cleared" if operation == "CLEAR" else "inverted"}.')


def set_channel_blend(context, obj, data, key, mode):
    layer = active_layer(data)
    index = layer.channel_blends.find(key)
    if mode == SAME_AS_FOLDER:
        if index >= 0:
            layer.channel_blends.remove(index)
    else:
        item = layer.channel_blends[index] if index >= 0 else layer.channel_blends.add()
        item.name, item.blend = key, mode
    return refresh(context, obj, data, f'{CHANNEL[key].label} of {layer.name} now blends with {"the folder" if mode == SAME_AS_FOLDER else dict(FOLDER_BLENDS)[mode]}.')


def set_layer_field(context, obj, data, field, value):
    layer = active_layer(data)
    setattr(layer, field, value)
    return refresh(context, obj, data, f'{layer.name} updated.')


def flatten_bake(context, obj, project, roots, keys, mask_uid=''):
    data = project.sets[project.active_set]
    results = {}
    for key in keys:
        def isolate(item, key=key):
            compositing.isolated_tree(item, item.material.node_tree, roots, key, mask_uid)
        for (index, number), pixels in baking.bake_pass(context, obj, project, [project.active_set], isolate).items():
            results[(key, number)] = pixels
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    return data, results


def flatten_layers(context, obj, project, uids):
    data = project.sets[project.active_set]
    roots = [layer for layer in data.layers if layer.uid in uids]
    channels = [channel.key for channel in compositing.set_channels(data)]
    data, baked = flatten_bake(context, obj, project, roots, channels + ['ALPHA'])
    root_uids, name, parent = [root.uid for root in roots], roots[-1].name, roots[-1].parent
    data.active_uid = root_uids[-1]
    layer = new_layer(data, 'PAINT')
    layer.name = 'Flattened ' + name
    layer.parent = parent
    add_slots(layer)
    for slot in layer.slots:
        slot.enabled = slot.name in channels
    layer.image = image_for(obj, data, layer.uid, False)
    strokes.ensure_canvases(obj, data)
    for number in tiles.numbers(data):
        alpha = baked[('ALPHA', number)][..., 0]
        color = numpy.ones(alpha.shape + (4,), dtype=numpy.float32)
        color[..., :3] = linear_to_srgb(baked[('base_color', number)][..., :3]) if 'base_color' in channels else 0.0
        color[..., 3] = numpy.clip(alpha, 0, 1)
        strokes.write(tiles.variant(data, layer.image, number), color)
        for slot in layer.slots:
            if slot.name != 'base_color' and slot.enabled and slot.image is not None:
                values = numpy.ones(alpha.shape + (4,), dtype=numpy.float32)
                values[..., :3] = baked[(slot.name, number)][..., :3]
                strokes.write(tiles.variant(data, slot.image, number), values)
    flattened = layer.uid
    remove_layers(data, root_uids)
    data.active_uid = flattened
    return refresh(context, obj, data, f'Flattened {len(root_uids)} layers into one paint layer.')


def export_layer(context, obj, project, uids, directory, mask=False):
    data = project.sets[project.active_set]
    roots = [layer for layer in data.layers if layer.uid in uids]
    channels = [channel for channel in compositing.set_channels(data)]
    keys = ['MASK'] if mask else [channel.key for channel in channels] + ['ALPHA']
    data, baked = flatten_bake(context, obj, project, roots, keys, roots[0].uid if mask else '')
    folder = Path(directory)
    written = []
    stem = bpy.path.clean_name(roots[-1].name)
    for number in tiles.numbers(data):
        suffix = f'.{number}' if len(tiles.numbers(data)) > 1 else ''
        if mask:
            path = folder / f'{stem}_Mask{suffix}.png'
            exporting.write(path, [numpy.clip(baked[('MASK', number)][..., 0], 0, 1)], 'PNG', '8', 0)
            written.append(path)
            continue
        alpha = numpy.clip(baked[('ALPHA', number)][..., 0], 0, 1)
        for channel in channels:
            values = baked[(channel.key, number)][..., :channel.width]
            values = linear_to_srgb(values) if channel.srgb else numpy.clip(values, 0, 1)
            planes = [values[..., index] for index in range(channel.width)] + [alpha]
            path = folder / f'{stem}_{channel.suffix}{suffix}.png'
            exporting.write(path, planes if channel.width == 3 else [planes[0], planes[0], planes[0], alpha], 'PNG', '8', 0)
            written.append(path)
    return f'Exported {len(written)} files of {roots[-1].name} to {directory}.'


def set_resolution(context, obj, data, size):
    keys = [image for layer in data.layers for image in owned_images(layer)] + [item.image for item in data.maps if item.image is not None]
    for image in tiles.every_image(data, keys):
        image.scale(size, size)
        image.pack()
    data.resolution = size
    if data.stroke is not None:
        data.stroke.scale(size, size)
    return refresh(context, obj, data, f'{data.name} now paints at {size} px.')


def new_layer(data, kind):
    data.serial += 1
    active = active_layer(data)
    index = layer_index(data, data.active_uid)
    parent = '' if active is None else active.uid if active.kind == 'FOLDER' else active.parent
    layer = data.layers.add()
    layer.uid = f'L{data.serial}'
    layer.kind = kind
    layer.parent = parent
    data.layers.move(len(data.layers) - 1, index + 1)
    layer = data.layers[index + 1]
    data.active_uid = layer.uid
    data.target = 'CONTENT'
    if data.quick_mask is not None:
        layer.mask, data.quick_mask = data.quick_mask, None
        layer.mask.name = f'DP {data.id_data.name} {data.name} {layer.uid} mask'
    return layer


def add_layer(context, obj, data, kind):
    layer = new_layer(data, kind)
    layer.name = f'{KIND_NAMES[kind]} {sum(1 for item in data.layers if item.kind == kind)}'
    if kind != 'FOLDER':
        add_slots(layer)
    if kind == 'PAINT':
        layer.image = image_for(obj, data, layer.uid, False)
        layer.slots['normal'].blend = NORMAL_DETAIL
    return refresh(context, obj, data, f'Added {layer.name}.')


def apply_material(layer, definition):
    layer.material = json.dumps(definition)
    library.apply_definition(layer, definition)


def add_material(context, obj, data, definition):
    layer = new_layer(data, 'FILL')
    layer.name = definition['name']
    add_slots(layer)
    apply_material(layer, definition)
    return refresh(context, obj, data, f'Added {layer.name}.')


def add_smart_material(context, obj, data, definition):
    folder = new_layer(data, 'FOLDER')
    folder.name = definition['name']
    folder_uid = folder.uid
    smart.build(obj, data, definition, folder, image_for)
    data.active_uid = folder_uid
    return refresh(context, obj, data, f'Added the {definition["name"]} smart material.')


def replace_material(context, obj, data, definition):
    layer = active_layer(data)
    apply_material(layer, definition)
    layer.name = definition['name']
    return refresh(context, obj, data, f'{layer.name} now carries the {definition["name"]} material and keeps its mask.')


def reset_material(context, obj, data):
    layer = active_layer(data)
    apply_material(layer, json.loads(layer.material))
    return refresh(context, obj, data, f'{layer.name} reset to its material.')


def owned_images(layer):
    canvases = [slot.image for slot in layer.slots if slot.source == 'IMAGE'] if layer.kind == 'PAINT' else []
    painted = [effect.image for effect in layer.effects if effect.kind == 'PAINT']
    return [image for image in (layer.image, layer.mask, *canvases, *painted) if image is not None]


def delete_layer(context, obj, data):
    name = active_layer(data).name
    remove_layers(data, [data.active_uid])
    return refresh(context, obj, data, f'Deleted {name}.')


def move_layer(context, obj, data, step):
    layer = active_layer(data)
    siblings = [index for index, item in enumerate(data.layers) if item.parent == layer.parent]
    position = siblings.index(layer_index(data, layer.uid))
    if not 0 <= position + step < len(siblings):
        return 'The layer is already at the edge of its stack.'
    name = layer.name
    data.layers.move(siblings[position], siblings[position + step])
    return refresh(context, obj, data, f'Moved {name} {"up" if step > 0 else "down"}.')


def folder_below(data, layer):
    siblings = [item for item in data.layers if item.parent == layer.parent]
    position = next(index for index, item in enumerate(siblings) if item.uid == layer.uid)
    return next((item for item in reversed(siblings[:position]) if item.kind == 'FOLDER'), None)


def move_into_folder(context, obj, data):
    layer = active_layer(data)
    folder = folder_below(data, layer)
    if folder is None:
        return 'There is no folder under this layer to move it into.'
    layer.parent = folder.uid
    return refresh(context, obj, data, f'Moved {layer.name} into {folder.name}.')


def move_out_of_folder(context, obj, data):
    layer = active_layer(data)
    folder = find_layer(data, layer.parent)
    if folder is None:
        return 'The layer is not in a folder.'
    layer.parent = folder.parent
    message = f'Moved {layer.name} out of {folder.name}.'
    source, target = layer_index(data, layer.uid), layer_index(data, folder.uid)
    data.layers.move(source, target + 1 if source > target else target)
    return refresh(context, obj, data, message)


def select_layer(context, obj, data, uid, mask=False):
    layer = find_layer(data, uid)
    data.active_uid = uid
    data.target = 'MASK' if mask and layer.mask is not None else 'CONTENT'
    painting.update_canvas(context, data)
    return f'{layer.name}{" mask" if data.target == "MASK" else ""} selected.'


def toggle_visible(context, obj, data, uid):
    layer = find_layer(data, uid)
    layer.visible = not layer.visible
    return refresh(context, obj, data, f'{layer.name} {"shown" if layer.visible else "hidden"}.')


def toggle_isolate(context, obj, data, uid):
    data.isolate = '' if data.isolate == uid else uid
    return refresh(context, obj, data, f'Showing only {find_layer(data, uid).name}.' if data.isolate else 'Showing every layer.')


def set_blend(context, obj, data, key, mode):
    layer = active_layer(data)
    layer.slots[key].blend = mode
    return refresh(context, obj, data, f'{CHANNEL[key].label} of {layer.name} blends with {dict(BLEND_MODES)[mode]}.')


def rename_layer(context, obj, data, uid, name):
    layer = find_layer(data, uid)
    layer.name = name.strip() or layer.name
    return refresh(context, obj, data, f'Renamed to {layer.name}.')


def copy_layer(obj, data, source, parent, position):
    data.serial += 1
    values = {key: getattr(source, key) for key in LAYER_FIELDS}
    slots = [(slot.name, {key: getattr(slot, key) for key in SLOT_FIELDS + ('image',)}) for slot in source.slots]
    blends = [(item.name, item.blend) for item in source.channel_blends]
    images = {key: getattr(source, key) for key in ('image', 'mask')}
    name, uid = source.name, source.uid
    layer = data.layers.add()
    for key, value in values.items():
        setattr(layer, key, value)
    layer.uid, layer.parent, layer.name = f'L{data.serial}', parent, name + (' copy' if position is not None else '')
    for slot_name, slot_values in slots:
        slot = layer.slots.add()
        slot.name = slot_name
        for key, value in slot_values.items():
            setattr(slot, key, value)
        if values['kind'] == 'PAINT' and slot.image is not None:
            slot.image = tiles.copy(data, slot.image, f'DP {obj.name} {data.name} {layer.uid} {slot_name}')
    for key, image in images.items():
        if image is not None:
            setattr(layer, key, tiles.copy(data, image, f'DP {obj.name} {data.name} {layer.uid}' + (' mask' if key == 'mask' else '')))
    for key, blend in blends:
        item = layer.channel_blends.add()
        item.name, item.blend = key, blend
    copy_effects(obj, data, data, list(source.effects), layer)
    new_uid = layer.uid
    if position is not None:
        data.layers.move(len(data.layers) - 1, position)
    for child in [item.uid for item in data.layers if item.parent == uid]:
        copy_layer(obj, data, find_layer(data, child), new_uid, None)
    return new_uid


def duplicate_layer(context, obj, data):
    source = active_layer(data)
    if source is None:
        return 'No layer to duplicate.'
    name = source.name
    data.active_uid = copy_layer(obj, data, source, source.parent, layer_index(data, source.uid) + 1)
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Duplicated {name}.')


def toggle_slot(context, obj, data, key):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled = not slot.enabled
    return refresh(context, obj, data, f'{CHANNEL[key].label} {"on" if slot.enabled else "off"} for {layer.name}.')


def set_opacity(context, obj, data, value):
    active_layer(data).opacity = max(0.0, min(1.0, value))
    compositing.update_values(data)


def set_channel_value(context, obj, data, key, value, second=False):
    set_slot_value(active_layer(data).slots[key], tuple(max(0.0, min(1.0, part)) for part in value), second)
    compositing.update_values(data)


def set_slot_field(context, obj, data, key, field, value):
    setattr(active_layer(data).slots[key], field, value)
    compositing.update_values(data)


def set_tiling(context, obj, data, value):
    active_layer(data).tiling = value
    compositing.update_values(data)


def set_projection(context, obj, data, projection):
    layer = active_layer(data)
    layer.projection = projection
    if projection in PROJECTORS and layer.proj_size == 1.0 and not any(layer.proj_offset):
        layer.proj_size = max(obj.dimensions) / 2 / max(max(obj.scale), 1e-6)
    label = dict((key, label) for key, label, _ in PROJECTIONS)[projection]
    return refresh(context, obj, data, f'{layer.name} projects {"by UV" if projection == "UV" else label.lower()}.')


def set_projector(context, obj, data, values, commit):
    layer = active_layer(data)
    for field, value in values.items():
        setattr(layer, field, value)
    compositing.update_values(data)
    return refresh(context, obj, data, f'{layer.name} projector moved.') if commit else ''


def use_value(context, obj, data, key):
    layer = active_layer(data)
    layer.slots[key].source = 'VALUE'
    return refresh(context, obj, data, f'{CHANNEL[key].label} of {layer.name} is a plain value.')


def assign_image(context, obj, data, key, image):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled, slot.source, slot.image = True, 'IMAGE', image
    compositing.assign_image_colorspace(image, CHANNEL[key])
    return refresh(context, obj, data, f'{image.name} drives {CHANNEL[key].label.lower()} of {layer.name}.')


def assign_pattern(context, obj, data, key, pattern):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled, slot.source, slot.pattern = True, 'PATTERN', pattern
    return refresh(context, obj, data, f'{PATTERN[pattern].label} drives {CHANNEL[key].label.lower()} of {layer.name}.')


def commit_value(context, obj, data, label):
    return refresh(context, obj, data, f'{label} of {active_layer(data).name} set.')


def set_solo(context, obj, data, key):
    data.solo = key
    if key.startswith('mask:'):
        return refresh(context, obj, data, f'Viewing the mask of {find_layer(data, key.removeprefix("mask:")).name}.')
    if key.startswith('map:'):
        return refresh(context, obj, data, f'Viewing the {MESH_MAP[key.removeprefix("map:")].label.lower()} map.')
    return refresh(context, obj, data, f'Viewing {CHANNEL[key].label} only.' if key else 'Viewing the full material.')


def pick_id_color(context, obj, data, effect_uid, face, location, add):
    item = data.maps.get('id')
    if item is None or item.image is None:
        return 'Bake the ID map first.'
    mesh = obj.data
    uv = sets.uv_at(mesh, obj.devil_painter.uv_map, sets.triangle_at(mesh, face, location), location)
    tile = tiles.FIRST_TILE + int(uv.x // 1) + 10 * int(uv.y // 1)
    image = tiles.variant(data, item.image, tile)
    width, height = image.size
    column, row = min(int(uv.x % 1 * width), width - 1), min(int(uv.y % 1 * height), height - 1)
    start = (row * width + column) * 4
    color = tuple(image.pixels[start:start + 3])
    layer = active_layer(data)
    effect = find_effect(layer, effect_uid)
    if add:
        effect.id_colors.add().color = color
        return refresh(context, obj, data, f'{layer.name} also keeps the picked ID color.')
    effect.color = color
    return refresh(context, obj, data, f'{layer.name} keeps the picked ID color.')


def remove_id_color(context, obj, data, index):
    layer = active_layer(data)
    find_effect(layer, data.active_effect).id_colors.remove(index)
    return refresh(context, obj, data, f'{layer.name} no longer keeps that ID color.')


def paint_bake_map(context, obj, data, kind):
    field = 'cage_map' if kind == 'CAGE' else 'skew_map'
    if getattr(data, field) is None:
        setattr(data, field, tiles.create(data, f'DP {obj.name} {data.name} {kind.lower()} map', meshmaps.BAKE_PAINT_FILL[kind], True))
    data.bake_paint = '' if data.bake_paint == kind else kind
    painting.update_canvas(context, data)
    label = 'cage reach (white reaches the full ray distance, black reaches nothing)' if kind == 'CAGE' else 'skew (white bakes straight down the face)'
    return refresh(context, obj, data, f'Painting the {label}.' if data.bake_paint else 'Back to painting layers.')


def clear_bake_map(context, obj, data, kind):
    field = 'cage_map' if kind == 'CAGE' else 'skew_map'
    image = getattr(data, field)
    if image is not None:
        bpy.data.images.remove(image)
    if data.bake_paint == kind:
        data.bake_paint = ''
    painting.update_canvas(context, data)
    return refresh(context, obj, data, f'Removed the painted {kind.lower()} map.')


def bake_mesh_maps(context, obj, data, keys):
    project = obj.devil_painter
    failure = ''
    try:
        baked = meshmaps.bake_maps(context, obj, project, list(range(len(project.sets))), keys, data)
    except RuntimeError as error:
        baked, failure = [], 'Bake failed. ' + str(error).strip()
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    data.bake_signature = meshmaps.signature(context, obj, data)
    if failure:
        return failure
    if not baked:
        return 'Nothing to bake. Height needs a high-poly source.'
    return refresh(context, obj, data, f'Baked {len(baked)} mesh maps.')


def rebake(context, obj, data):
    keys = meshmaps.baked_keys(data)
    if not keys:
        data.bake_signature = meshmaps.signature(context, obj, data)
        return None
    return 'Rebaked: ' + bake_mesh_maps(context, obj, data, keys)


def set_bake(context, obj, data, name, value, message):
    setattr(data, name, value)
    bpy.ops.ed.undo_push(message='Devil Painter: ' + message)
    return message


def set_bake_object(context, obj, data, name, value):
    target = bpy.data.objects.get(value) if value else None
    noun = {'bake_source': 'High-poly source', 'bake_cage': 'Cage'}[name]
    return set_bake(context, obj, data, name, target, f'{noun}: {value}.' if value else f'{noun}: none.')


def add_generator(context, obj, data, values):
    layer = active_layer(data)
    effect = new_effect(data, layer, 'GENERATOR', 'MASK')
    for field in GENERATOR_FIELDS:
        if field in values:
            setattr(effect, field, values[field])
    generator = GENERATOR[effect.generator]
    absent = [key for key in generator.maps if key not in data.maps or data.maps[key].image is None]
    missing = f' Bake the {MESH_MAP[absent[0]].label.lower()} map to see it.' if absent else ''
    return refresh(context, obj, data, f'{generator.label} added to the mask of {layer.name}.{missing}')


def set_generator_value(context, obj, data, field, value):
    setattr(active_effect(data), field, value)
    compositing.update_values(data)


def save_smart_mask(context, obj, data):
    layer = active_layer(data)
    project = obj.devil_painter
    _, baked = flatten_bake(context, obj, project, [layer], ['MASK'], layer.uid)
    values = numpy.clip(baked[('MASK', tiles.numbers(data)[0])][..., 0], 0, 1)
    preview = numpy.ones(values.shape + (4,), dtype=numpy.float32)
    preview[..., :3] = values[..., None]
    name = smart.save_mask(active_layer(data), preview)
    return refresh(context, obj, data, f'Saved {name} to the mask shelf.')


def apply_smart_mask(context, obj, data, definition):
    layer = active_layer(data)
    if layer is None or layer.kind == 'INSTANCE':
        return 'Select a layer to mask.'
    smart.apply_mask(obj, data, layer, definition)
    return refresh(context, obj, data, f'{layer.name} uses the {definition["name"]} smart mask.')


def toggle_quick_mask(context, obj, data):
    if data.quick_mask is None:
        data.quick_mask = image_for(obj, data, 'quick mask', False)
        message = 'Quick mask on. Paint or fill where the next layer should show.'
    else:
        bpy.data.images.remove(data.quick_mask)
        message = 'Quick mask cleared.'
    painting.update_canvas(context, data)
    return refresh(context, obj, data, message)


def apply_quick_mask(context, obj, data):
    layer = active_layer(data)
    if layer is None or layer.kind == 'INSTANCE':
        return 'Select a layer to mask.'
    stencil, data.quick_mask = data.quick_mask, None
    if layer.mask is None:
        layer.mask = stencil
    else:
        data.serial += 1
        effect = layer.effects.add()
        effect.uid, effect.kind, effect.target, effect.blend, effect.image = f'E{data.serial}', 'PAINT', 'MASK', 'MULTIPLY', stencil
    painting.update_canvas(context, data)
    return refresh(context, obj, data, f'{layer.name} is masked by the quick mask.')


def add_mask(context, obj, data, white):
    layer = active_layer(data)
    layer.mask = image_for(obj, data, layer.uid + ' mask', white)
    data.target = 'MASK'
    return refresh(context, obj, data, f'{"White" if white else "Black"} mask added to {layer.name}. Painting now edits the mask.')


def remove_mask(context, obj, data):
    layer = active_layer(data)
    mask = layer.mask
    layer.mask = None
    if mask is not None:
        tiles.release(data, mask)
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Mask removed from {layer.name}.')


def set_target(context, obj, data, target):
    data.target = target
    painting.update_canvas(context, data)
    return 'Painting edits the mask.' if target == 'MASK' else 'Painting edits the layer.'


def export_files(context, obj, project, directory):
    wanted = [index for index, data in enumerate(project.sets) if data.export]
    if not wanted:
        return [], 'Pick at least one texture set to export.'
    template = exporting.find_template(project.export_template)
    written = exporting.export(context, obj, project, template, wanted, directory, project.export_pattern, project.export_depth,
                               project.export_size, project.export_padding)
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    painting.update_canvas(context, project.sets[project.active_set])
    return written, f'Exported {len(written)} textures to {directory}.'


def export(context, obj, project, directory):
    return export_files(context, obj, project, directory)[1]


def send_to_app(context, obj, project, directory):
    written, message = export_files(context, obj, project, directory)
    if not written:
        return message
    return bridge.send(written, directory)
