import os
from pathlib import Path
import stat
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SCRATCH_VARIABLE = 'DEVIL_PAINTER_SCRATCH'
FAILURE_RECORD_VARIABLE = 'DEVIL_PAINTER_FAILURE_RECORD'
SCRATCH = Path(os.environ[SCRATCH_VARIABLE]) if SCRATCH_VARIABLE in os.environ else ROOT / 'scratch'
DIST = ROOT / 'dist'
RUN_PREFIX = 'run-'


def read_manifest(root=None):
    return tomllib.loads(((root or ROOT) / 'devil_painter' / 'blender_manifest.toml').read_text(encoding='utf-8'))


def extension_archive():
    manifest = read_manifest()
    return DIST / f"{manifest['id']}-{manifest['version']}.zip"


def scratch_root():
    return ROOT.resolve() / 'scratch'


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def checked_scratch(target=None):
    expected = scratch_root()
    chosen = (target or SCRATCH).absolute()
    inside_run = '..' not in chosen.parts and chosen.is_relative_to(expected) and chosen != expected and chosen.relative_to(expected).parts[0].startswith(RUN_PREFIX)
    if chosen != expected and not inside_run:
        raise ValueError('Scratch must be the real scratch directory directly inside the repository, or a gate run folder scratch/run-<id> or a folder inside one.')
    for directory in [chosen, *chosen.parents][:len(chosen.relative_to(expected).parts) + 1]:
        try:
            linked = is_link(directory)
        except FileNotFoundError:
            continue
        if linked or not directory.is_dir():
            raise ValueError('Scratch cannot be a linked directory or a file.')
    return chosen


def prepare_scratch(target=None):
    directory = checked_scratch(target)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def child_environment(directory):
    directory = prepare_scratch(directory)
    temporary = directory / 'blender-temp'
    temporary.mkdir(exist_ok=True)
    config = directory / 'blender-config'
    config.mkdir(exist_ok=True)
    return dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
                BLENDER_USER_CONFIG=str(config), **{SCRATCH_VARIABLE: str(directory)})


def clean_scratch(target=None):
    directory = checked_scratch(target)
    if not directory.exists():
        return 0
    pending = [directory]
    directories = []
    files = []
    while pending:
        current = pending.pop()
        directories.append(current)
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                if is_link(path) or not path.resolve().is_relative_to(directory):
                    raise ValueError('Scratch cleanup refuses links and paths outside scratch.')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    files.append(path)
    for path in files:
        try:
            path.unlink()
        except OSError as error:
            raise OSError(f'Cannot remove scratch artifact {path.relative_to(directory)}; close its owner and run --clean again.') from error
    for path in reversed(directories):
        path.rmdir()
    return len(files)
