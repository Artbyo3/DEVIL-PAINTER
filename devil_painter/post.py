import bpy

TREE = 'Devil Painter Post'
POST_SLIDERS = (('POST_BLOOM', 'Bloom', 'post_bloom', 1.0), ('POST_VIGNETTE', 'Vignette', 'post_vignette', 1.0),
                ('POST_ABERRATION', 'Color fringe', 'post_aberration', 1.0), ('POST_SATURATION', 'Saturation', 'post_saturation', 2.0),
                ('POST_CONTRAST', 'Contrast', 'post_contrast', 2.0))


def owned_tree(scene):
    tree = scene.compositing_node_group
    return tree if tree is not None and tree.name.startswith(TREE) else None


def build_tree(scene):
    tree = bpy.data.node_groups.get(TREE) or bpy.data.node_groups.new(TREE, 'CompositorNodeTree')
    tree.nodes.clear()
    tree.interface.clear()
    tree.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    nodes, links = tree.nodes, tree.links
    source = nodes.new('CompositorNodeRLayers')
    source.scene = scene
    glare = nodes.new('CompositorNodeGlare')
    glare.name = 'post.bloom'
    glare.inputs['Type'].default_value = 'Bloom'
    glare.inputs['Threshold'].default_value = .8
    links.new(source.outputs['Image'], glare.inputs['Image'])
    grade = nodes.new('CompositorNodeHueSat')
    grade.name = 'post.grade'
    links.new(glare.outputs['Image'], grade.inputs['Image'])
    contrast = nodes.new('CompositorNodeBrightContrast')
    contrast.name = 'post.contrast'
    links.new(grade.outputs['Image'], contrast.inputs['Image'])
    fringe = nodes.new('CompositorNodeLensdist')
    fringe.name = 'post.fringe'
    links.new(contrast.outputs['Image'], fringe.inputs['Image'])
    vignette = nodes.new('CompositorNodeEllipseMask')
    vignette.name = 'post.vignette'
    vignette.inputs['Size'].default_value = (1.3, 1.3)
    vignette.inputs['Operation'].default_value = 'Subtract'
    vignette.inputs['Mask'].default_value = 1.0
    vignette.inputs['Value'].default_value = 1.0
    shade = nodes.new('ShaderNodeMix')
    shade.name = 'post.shade'
    shade.data_type = 'RGBA'
    shade.blend_type = 'MULTIPLY'
    links.new(vignette.outputs['Mask'], next(item for item in shade.inputs if item.name == 'Factor' and item.type == 'VALUE'))
    links.new(fringe.outputs['Image'], next(item for item in shade.inputs if item.name == 'A' and item.type == 'RGBA'))
    output = nodes.new('NodeGroupOutput')
    links.new(next(item for item in shade.outputs if item.name == 'Result' and item.type == 'RGBA'), output.inputs[0])
    scene.compositing_node_group = tree
    return tree


def write(scene, project):
    tree = owned_tree(scene)
    if tree is None:
        return
    nodes = tree.nodes
    nodes['post.bloom'].inputs['Strength'].default_value = project.post_bloom
    nodes['post.bloom'].mute = project.post_bloom <= 0
    nodes['post.grade'].inputs['Saturation'].default_value = project.post_saturation
    nodes['post.contrast'].inputs['Contrast'].default_value = (project.post_contrast - 1.0) * 50
    nodes['post.fringe'].inputs['Dispersion'].default_value = project.post_aberration * .1
    shade = nodes['post.shade']
    next(item for item in shade.inputs if item.name == 'B' and item.type == 'RGBA').default_value = (1.0 - project.post_vignette,) * 3 + (1.0,)
    shade.mute = project.post_vignette <= 0


def apply(scene, space, project):
    if project.post_enabled:
        if owned_tree(scene) is None and scene.compositing_node_group is not None:
            return 'The scene already has its own compositor, so Devil Painter leaves it alone.'
        if owned_tree(scene) is None:
            build_tree(scene)
        write(scene, project)
        space.shading.use_compositor = 'ALWAYS'
        return 'Post effects are on in the viewport.'
    if owned_tree(scene) is not None:
        space.shading.use_compositor = 'DISABLED'
    return 'Post effects are off.'
