from .filters import FILTER

EFFECT_KINDS = (('PAINT', 'Paint', ('MASK',)), ('FILL', 'Fill', ('MASK',)), ('LEVELS', 'Levels', ('MASK', 'CONTENT')),
                ('FILTER', 'Filter', ('MASK', 'CONTENT')), ('COMPARE', 'Compare mask', ('MASK',)), ('ANCHOR', 'Anchor', ('MASK',)),
                ('ID_COLOR', 'ID color', ('MASK',)))
EFFECT_LABEL = {key: label for key, label, _ in EFFECT_KINDS}
EFFECT_ICONS = {'PAINT': 'PAINT', 'FILL': 'FILL', 'LEVELS': 'SETTINGS', 'FILTER': 'BLUR', 'COMPARE': 'SHAPE', 'ANCHOR': 'PIN', 'ID_COLOR': 'EYEDROPPER'}
MASK_BLENDS = (('MULTIPLY', 'Multiply'), ('ADD', 'Add'), ('SUBTRACT', 'Subtract'), ('MIX', 'Replace'), ('MINIMUM', 'Darken'),
               ('MAXIMUM', 'Lighten'), ('DIFFERENCE', 'Difference'))
LEVEL_COMPONENTS = (('ALL', 'All'), ('R', 'Red'), ('G', 'Green'), ('B', 'Blue'))
LEVEL_FIELDS = ('in_low', 'in_high', 'gamma', 'out_low', 'out_high')
COMPONENT_FIELDS = tuple('comp_' + field for field in LEVEL_FIELDS)
EFFECT_FIELDS = ('kind', 'target', 'enabled', 'blend', 'opacity', 'source', 'value', 'pattern', 'scale', 'detail', 'contrast', 'texture',
                 'in_low', 'in_high', 'gamma', 'out_low', 'out_high', 'filter', 'amount', 'radius', 'angle', 'hue', 'saturation', 'brightness',
                 'color', 'color_b', 'other', 'channel', 'clamp', 'levels_component') + COMPONENT_FIELDS


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
