import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from devil_painter import exporting
from tools.workspace import SCRATCH

LOG = Path(os.environ['DEVIL_PAINTER_JOURNEY_LOG'])
write_export = exporting.write


def published_name(path):
    path = Path(path).resolve()
    return path.relative_to(SCRATCH.resolve()).as_posix() if path.is_relative_to(SCRATCH.resolve()) else path.name


def hashed_write(path, *arguments):
    write_export(path, *arguments)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    with LOG.open('a', encoding='utf-8') as log:
        log.write(json.dumps([published_name(path), digest]) + '\n')


exporting.write = hashed_write
