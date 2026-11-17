import re

ROOT = r'(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|/(?=[^\s/]))'
QUOTED = re.compile(r'''(["'])(''' + ROOT + r'''[^"']*)\1''')
BARE = re.compile(r'''(?<![\w.•])''' + ROOT + r'''[^\s'"]*''')
SEPARATORS = re.compile(r'[\\/]+')
TRAILING = '.,;:)'
MASK = '•••'


def masked_path(path):
    if not path:
        return path
    core = path.rstrip(TRAILING)
    separator = '\\' if '\\' in core else '/'
    parts = [part for part in SEPARATORS.split(core) if part]
    tail = parts[-1] if len(parts) > 1 or not core[:1].isalpha() else ''
    return MASK + (separator + tail if tail else '') + path[len(core):]


def masked(text):
    if not text:
        return text
    text = QUOTED.sub(lambda match: match.group(1) + masked_path(match.group(2)) + match.group(1), text)
    return BARE.sub(lambda match: masked_path(match.group(0)), text)
