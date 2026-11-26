from .filters import FILTER
from .masks import GENERATOR, GENERATOR_FIELDS

EFFECT_KINDS = (('PAINT', 'Paint', ('MASK', 'CONTENT')), ('FILL', 'Fill', ('MASK', 'CONTENT')), ('LEVELS', 'Levels', ('MASK', 'CONTENT')),
                ('FILTER', 'Filter', ('MASK', 'CONTENT')), ('COMPARE', 'Compare', ('MASK',)), ('ANCHOR', 'Anchor', ('MASK',)),
                ('ID_COLOR', 'Color selection', ('MASK',)), ('GENERATOR', 'Generator', ('MASK', 'CONTENT')))
CONTENT_KINDS = frozenset(key for key, _, targets in EFFECT_KINDS if 'CONTENT' in targets)
CONTENT_SOURCES = frozenset({'PAINT', 'FILL', 'GENERATOR'})
ANCHORED_KINDS = frozenset({'GENERATOR', 'FILTER'})
EFFECT_LABEL = {key: label for key, label, _ in EFFECT_KINDS}
STACK_ADDS = ('PAINT', 'FILL', 'GENERATOR', 'FILTER', 'LEVELS', 'COMPARE', 'ID_COLOR', 'ANCHOR')
ROW_ADDS = ('PAINT', 'FILL', 'GENERATOR', 'LEVELS', 'COMPARE', 'FILTER', 'ID_COLOR', 'ANCHOR')
EFFECT_ICONS = {'PAINT': 'PAINT', 'FILL': 'FILL', 'LEVELS': 'SETTINGS', 'FILTER': 'BLUR', 'COMPARE': 'SHAPE', 'ANCHOR': 'PIN', 'ID_COLOR': 'EYEDROPPER', 'GENERATOR': 'GENERATOR'}
MASK_BLENDS = (('MIX', 'Replace', 3), ('MINIMUM', 'Darken', 4), ('MULTIPLY', 'Multiply', 0), ('BURN', 'Color burn', 7), ('MAXIMUM', 'Lighten', 5),
               ('SCREEN', 'Screen', 8), ('DODGE', 'Color dodge', 9), ('ADD', 'Linear dodge (Add)', 1), ('OVERLAY', 'Overlay', 10),
               ('SOFT_LIGHT', 'Soft light', 11), ('LINEAR_LIGHT', 'Linear light', 12), ('DIFFERENCE', 'Difference', 6), ('EXCLUSION', 'Exclusion', 13),
               ('SUBTRACT', 'Subtract', 2), ('DIVIDE', 'Divide', 14), ('HUE', 'Hue', 15), ('SATURATION', 'Saturation', 16), ('COLOR', 'Color', 17),
               ('VALUE', 'Value', 18))
MASK_BLEND_LABEL = {key: label for key, label, _ in MASK_BLENDS}
FILL_PROJECTIONS = (('AUTO', 'Automatic'), ('UV', 'UV'), ('TRIPLANAR', 'Tri-planar'))
LEVEL_COMPONENTS = (('ALL', 'All'), ('R', 'Red'), ('G', 'Green'), ('B', 'Blue'))
LEVEL_FIELDS = ('in_low', 'in_high', 'gamma', 'out_low', 'out_high')
COMPONENT_FIELDS = tuple('comp_' + field for field in LEVEL_FIELDS)
EFFECT_FIELDS = ('kind', 'target', 'enabled', 'blend', 'opacity', 'source', 'value', 'pattern', 'scale', 'detail', 'contrast', 'texture',
                 'in_low', 'in_high', 'gamma', 'out_low', 'out_high', 'filter', 'amount', 'radius', 'angle', 'hue', 'saturation', 'brightness',
                 'color', 'color_b', 'other', 'channel', 'anchor', 'anchor_channel', 'anchor_weight', 'clamp', 'levels_component', 'projection', 'tiling', 'offset_u', 'offset_v', 'triplanar_blend', 'wrap', 'filtering') + COMPONENT_FIELDS + GENERATOR_FIELDS


def effects_in(layer, target):
    return [effect for effect in layer.effects if effect.target == target]


def mask_effects(layer):
    return effects_in(layer, 'MASK')


def has_mask(layer):
    return layer.mask is not None or bool(mask_effects(layer))


def fitting_target(kind, wanted, color_only=False):
    if wanted == 'CONTENT':
        return 'CONTENT' if kind in CONTENT_KINDS else 'MASK'
    return 'CONTENT' if kind == 'FILTER' and color_only else 'MASK'


def uses_blend(effect):
    if effect.target == 'MASK':
        return not (effect.kind == 'FILTER' and FILTER[effect.filter].sampling)
    return effect.kind in CONTENT_SOURCES


def find_effect(layer, uid):
    return next((effect for effect in layer.effects if effect.uid == uid), None)


def effect_label(effect):
    if effect.kind == 'FILTER':
        return FILTER[effect.filter].label
    if effect.kind == 'GENERATOR':
        return GENERATOR[effect.generator].label
    return EFFECT_LABEL[effect.kind]


def level_target(effect, field):
    if effect.kind == 'LEVELS' and effect.target == 'CONTENT' and field in LEVEL_FIELDS and effect.levels_component != 'ALL':
        return 'comp_' + field, 'RGB'.index(effect.levels_component)
    return field, None


class LevelsView:
    def __init__(self, effect):
        self.effect = effect

    def __getattr__(self, name):
        field, index = level_target(self.effect, name)
        value = getattr(self.effect, field)
        return value if index is None else value[index]


def copy_effect(source, target):
    for field in EFFECT_FIELDS:
        setattr(target, field, getattr(source, field))
    target.image = source.image
    target.id_colors.clear()
    for item in source.id_colors:
        target.id_colors.add().color = item.color
