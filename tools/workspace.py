import os
from pathlib import Path
import stat
import tomllib


ROOT = Path(__file__).resolve().parents[1]
JOURNEY_SCRATCH = 'DEVIL_PAINTER_SCRATCH'
SCRATCH = Path(os.environ[JOURNEY_SCRATCH]) if JOURNEY_SCRATCH in os.environ else ROOT / 'scratch'
DIST = ROOT / 'dist'


def extension_archive():
    manifest = tomllib.loads((ROOT / 'devil_painter' / 'blender_manifest.toml').read_text(encoding='utf-8'))
    return DIST / f"{manifest['id']}-{manifest['version']}.zip"


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def checked_scratch():
    expected = ROOT.resolve() / 'scratch'
    chosen = SCRATCH.absolute()
    journey = '..' not in chosen.parts and chosen.is_relative_to(expected / 'j') and chosen != expected / 'j'
    if chosen != expected and not journey:
        raise ValueError('Scratch must be the real scratch directory directly inside the repository, or a journey folder inside scratch/j.')
    for directory in [chosen, *chosen.parents][:len(chosen.relative_to(expected).parts) + 1]:
        try:
            linked = is_link(directory)
        except FileNotFoundError:
            continue
        if linked or not directory.is_dir():
            raise ValueError('Scratch cannot be a linked directory or a file.')
    return chosen


def prepare_scratch():
    directory = checked_scratch()
    directory.mkdir(exist_ok=True)
    return directory


def child_environment(journey=None):
    directory = journey or prepare_scratch()
    temporary = directory / 'blender-temp'
    temporary.mkdir(exist_ok=True)
    config = directory / 'blender-config'
    config.mkdir(exist_ok=True)
    own = {JOURNEY_SCRATCH: str(directory)} if journey else {}
    return dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
                BLENDER_USER_CONFIG=str(config), **own)


def clean_scratch():
    directory = checked_scratch()
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
