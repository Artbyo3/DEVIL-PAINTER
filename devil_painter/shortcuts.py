from .library import save_settings, settings

ACTIONS = (('PAINT', 'Paint tool', 'B'), ('ERASE', 'Erase tool', 'E'), ('FILL', 'Fill tool', 'G'), ('BLUR', 'Blur tool', ''),
           ('SMEAR', 'Smear tool', ''), ('CLONE', 'Clone tool', ''), ('SIZE_DOWN', 'Smaller brush', 'LEFT_BRACKET'),
           ('SIZE_UP', 'Larger brush', 'RIGHT_BRACKET'), ('VIEW2D', 'Toggle the 2D view', ''), ('SHELF', 'Show or hide the shelf', ''))
KEY_LABELS = {'LEFT_BRACKET': '[', 'RIGHT_BRACKET': ']', 'SEMI_COLON': ';', 'QUOTE': "'", 'COMMA': ',', 'PERIOD': '.', 'SLASH': '/',
              'MINUS': '-', 'EQUAL': '=', 'ACCENT_GRAVE': '`', 'BACK_SLASH': '\\'}
BINDABLE = set('ABCDEGHIJKLMNOPQRSTUVWXY') | {'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'ZERO'} | set(KEY_LABELS)
SIZE_STEP = 1.15


def bindings():
    stored = settings().setdefault('shortcuts', {})
    return {action: stored.get(action, default) for action, _, default in ACTIONS}


def bind(action, key):
    stored = settings().setdefault('shortcuts', {})
    for other, current in bindings().items():
        if current == key and other != action:
            stored[other] = ''
    stored[action] = key
    save_settings()


def action_for(key):
    return next((action for action, current in bindings().items() if current and current == key), None)


def key_label(key):
    return KEY_LABELS.get(key, key.title() if len(key) > 1 else key) if key else 'None'
