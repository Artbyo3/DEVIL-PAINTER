import json
import subprocess
from fnmatch import fnmatch
from tools.workspace import ROOT

GOLDEN = ROOT / 'tools' / 'golden_journey_hashes.json'
CORE_FILES = frozenset(f'devil_painter/{name}.py' for name in (
    'bakejob', 'baking', 'blending', 'caches', 'compositing', 'document', 'effects', 'exporting', 'filters', 'history', 'masks',
    'meshmaps', 'nodes', 'polyfill', 'procedural', 'projection', 'sets', 'strokes', 'tiles',
))
LIGHT_PATTERNS = (
    '*.md', 'docs-site/*', '.github/*', 'devil_painter/blender_manifest.toml',
    'devil_painter/assets/*.txt', 'devil_painter/assets/icons/sources.json',
)
TIER_NAMES = ('light', 'standard', 'full')
EXPECTED_EXPORTS = {
    'blender_api.py': (22, ''),
    'gui_anchors.py': (80, ''),
    'gui_baking.py': (0, 'verifies background mesh-map baking, cage/skew maps, and bake cancel rather than texture export'),
    'gui_clone_surface.py': (0, 'verifies surface-space clone source picking and seam-crossing strokes directly on layer pixels'),
    'gui_content.py': (50, ''),
    'gui_displacement.py': (0, 'verifies height displacement preview, scale, and viewport subdivision without exporting textures'),
    'gui_editor.py': (12, ''),
    'gui_env_rotate.py': (0, 'verifies Shift+right-drag environment rotation, wrapping, cancel, slider sync, and stencil coexistence without exporting textures'),
    'gui_extras.py': (5, ''),
    'gui_follow_path.py': (5, ''),
    'gui_history.py': (0, 'verifies unified undo/redo across strokes, masks, effects, and the history panel without exporting textures'),
    'gui_jitter.py': (5, ''),
    'gui_layer_delete.py': (0, 'verifies layer deletion, undo/redo, and workspace liveness without exporting textures'),
    'gui_layers.py': (91, ''),
    'gui_layout.py': (0, 'verifies docking, resizing, privacy path masking, and layout persistence without exporting textures'),
    'gui_library.py': (0, 'verifies 600-texture background thumbnail streaming, caching, and worker shutdown'),
    'gui_masks.py': (24, ''),
    'gui_material_stroke.py': (5, ''),
    'gui_missing_material.py': (0, 'verifies recovering a deleted texture-set material on open and mid-session paint strokes'),
    'gui_packs.py': (0, 'verifies online/offline asset-pack catalog security, checksum checks, install, and removal'),
    'gui_painting.py': (20, ''),
    'gui_positional.py': (65, ''),
    'gui_pressure.py': (0, 'verifies pen-pressure size, flow, hardness, and angle response directly on layer pixels'),
    'gui_project.py': (26, ''),
    'gui_reopen.py': (0, 'verifies reopening, fullscreen/maximize screen toggles, region restoration, and error recovery'),
    'gui_shelf.py': (11, ''),
    'gui_shift_line.py': (0, 'verifies Shift-click straight-line stroke geometry directly on layer pixels'),
    'gui_slope_normal.py': (65, ''),
    'gui_stencil_drag.py': (0, 'verifies viewport stencil move, scale, and rotate transforms directly on layer pixels'),
    'gui_texture_sampling.py': (35, ''),
    'gui_triplanar_hardness.py': (25, ''),
    'gui_udim.py': (10, ''),
    'gui_uv_transform.py': (30, ''),
    'gui_world_size.py': (5, ''),
}


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


def export_count_differences(actual, declared=None):
    declared = EXPECTED_EXPORTS if declared is None else declared
    differences = []
    for journey in list(declared) + [name for name in actual if name not in declared]:
        if journey not in declared:
            differences.append(f'{journey}: missing expected export count declaration')
            continue
        expected, reason = declared[journey]
        if expected == 0 and not reason.strip():
            differences.append(f'{journey}: declared 0 exports without a reason')
        if journey not in actual:
            differences.append(f'{journey}: declared journey did not run')
            continue
        produced = len(actual[journey])
        if produced != expected:
            differences.append(f'{journey}: expected {expected} exports, got {produced}')
    return differences


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
