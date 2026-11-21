import json
import subprocess
from fnmatch import fnmatch
from tools.workspace import ROOT

GOLDEN = ROOT / 'tools' / 'golden_journey_hashes.json'
CORE_FILES = frozenset(f'devil_painter/{name}.py' for name in (
    'bakejob', 'baking', 'blending', 'caches', 'compositing', 'document', 'effects', 'exporting', 'filters', 'masks',
    'meshmaps', 'nodes', 'polyfill', 'procedural', 'projection', 'sets', 'strokes', 'tiles',
))
LIGHT_PATTERNS = (
    '*.md', 'docs-site/*', '.github/*', 'devil_painter/blender_manifest.toml',
    'devil_painter/assets/*.txt', 'devil_painter/assets/icons/sources.json',
)
TIER_NAMES = ('light', 'standard', 'full')


def git(*arguments):
    return subprocess.run(['git', *arguments], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def main_ref():
    remote = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', 'origin/main'], cwd=ROOT, capture_output=True)
    return 'origin/main' if remote.returncode == 0 else 'main'


def merge_base():
    return git('merge-base', main_ref(), 'HEAD').strip()


def changed_files():
    return sorted(set(git('diff', '--name-only', '--no-renames', merge_base()).splitlines()))


def untracked_files():
    return sorted(git('ls-files', '--others', '--exclude-standard').splitlines())


def listed(paths, limit=6):
    shown = ', '.join(paths[:limit])
    return shown + (f' and {len(paths) - limit} more' if len(paths) > limit else '')


def select_tier(paths):
    if not paths:
        return 'full', f'no changes against {main_ref()}, so main itself gets the whole gate'
    core = [path for path in paths if path in CORE_FILES]
    if core:
        return 'full', f'core engine files changed: {listed(core)}'
    other = [path for path in paths if not any(fnmatch(path, pattern) for pattern in LIGHT_PATTERNS)]
    if other:
        return 'standard', f'files outside docs, manifest, workflows and asset metadata changed: {listed(other)}'
    return 'light', f'only docs, manifest, workflows or asset metadata changed: {listed(paths)}'


def read_log(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def read_golden():
    return json.loads(GOLDEN.read_text(encoding='utf-8'))


def write_golden(hashes):
    GOLDEN.write_text(json.dumps(hashes, indent=1) + '\n', encoding='utf-8', newline='\n')


def entry_text(entry):
    return f'{entry[0]} ({entry[1][:12]})' if entry else 'nothing'


def golden_differences(expected, actual):
    differences = []
    for journey in list(expected) + [name for name in actual if name not in expected]:
        if journey not in actual:
            differences.append(f'{journey}: journey did not run')
            continue
        if journey not in expected:
            differences.append(f'{journey}: journey has no golden entry')
            continue
        wanted, produced = expected[journey], actual[journey]
        for index in range(max(len(wanted), len(produced))):
            old = wanted[index] if index < len(wanted) else None
            new = produced[index] if index < len(produced) else None
            if old != new:
                differences.append(f'{journey} export #{index + 1}: expected {entry_text(old)}, got {entry_text(new)}')
    return differences
