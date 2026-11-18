from .filters import FILTER

EFFECT_KINDS = (('PAINT', 'Paint', ('MASK',)), ('FILL', 'Fill', ('MASK',)), ('LEVELS', 'Levels', ('MASK', 'CONTENT')),
                ('FILTER', 'Filter', ('MASK', 'CONTENT')), ('COMPARE', 'Compare mask', ('MASK',)), ('ANCHOR', 'Anchor', ('MASK',)),
                ('ID_COLOR', 'ID color', ('MASK',)))
EFFECT_LABEL = {key: label for key, label, _ in EFFECT_KINDS}
EFFECT_ICONS = {'PAINT': 'PAINT', 'FILL': 'FILL', 'LEVELS': 'SETTINGS', 'FILTER': 'BLUR', 'COMPARE': 'SHAPE', 'ANCHOR': 'PIN', 'ID_COLOR': 'EYEDROPPER'}
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
                 'color', 'color_b', 'other', 'channel', 'clamp', 'levels_component', 'projection', 'tiling', 'offset_u', 'offset_v') + COMPONENT_FIELDS


def allowed(kind, target):
    return target in next(targets for key, _, targets in EFFECT_KINDS if key == kind)


def mask_effects(layer):
    return [effect for effect in layer.effects if effect.target == 'MASK']


def content_effects(layer):
    return [effect for effect in layer.effects if effect.target == 'CONTENT']


def find_effect(layer, uid):
    return next((effect for effect in layer.effects if effect.uid == uid), None)


def effect_label(effect):
    if effect.kind == 'FILTER':
        return FILTER[effect.filter].label
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
