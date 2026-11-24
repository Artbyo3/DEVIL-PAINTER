import ctypes
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from tools import workspace

STILL_ACTIVE = 259
QUERY_LIMITED_INFORMATION = 0x1000
TIER_RANK = {'light': 0, 'standard': 1, 'full': 2}


class GateBusy(Exception):
    pass


def lock_path():
    return workspace.scratch_root() / 'gate.lock'


def status_path():
    return workspace.scratch_root() / 'gate-status.json'


def console_path():
    return workspace.scratch_root() / 'gate-console.log'


def git(*arguments, environment=None):
    return subprocess.run(['git', *arguments], cwd=workspace.ROOT, capture_output=True, text=True, check=True, env=environment).stdout.strip()


def git_path(name):
    return (workspace.ROOT / git('rev-parse', '--git-path', name)).resolve()


def result_path():
    return git_path('devil-painter-gate-result.json')


def process_alive(pid):
    if not pid:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        if Path('/proc').is_dir():
            try:
                text = Path(f'/proc/{pid}/stat').read_text(encoding='utf-8', errors='replace')
            except FileNotFoundError:
                return False
            except OSError:
                return True
            state = text.rpartition(')')[2].split()
            if state and state[0] in {'Z', 'X'}:
                return False
        return True
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + f'.{os.getpid()}.tmp')
    pending.write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8')
    os.replace(pending, path)


def lock_owner():
    owner = read_json(lock_path())
    return owner if owner and process_alive(owner.get('pid')) else None


def acquire_lock(run_id):
    workspace.prepare_scratch(workspace.scratch_root())
    for _ in range(2):
        try:
            descriptor = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = lock_owner()
            if owner:
                raise GateBusy(f"Another gate is already running in this worktree (PID {owner['pid']}, run {owner.get('run')}). "
                               'Follow it with `python tools/dev.py --wait`; start a new gate after it ends.')
            lock_path().unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(dict(pid=os.getpid(), run=run_id), handle)
        return
    raise GateBusy('The gate lock could not be taken; remove scratch/gate.lock if no gate is running.')


def release_lock():
    owner = read_json(lock_path())
    if owner and owner.get('pid') == os.getpid():
        lock_path().unlink(missing_ok=True)


def read_status():
    return read_json(status_path())


def write_status(**fields):
    write_json(status_path(), fields)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def tree_fingerprint():
    index = git_path(f'devil-painter-fingerprint-{os.getpid()}.index')
    real_index = git_path('index')
    if real_index.is_file():
        shutil.copyfile(real_index, index)
    environment = dict(os.environ, GIT_INDEX_FILE=str(index))
    try:
        if not real_index.is_file():
            git('read-tree', 'HEAD', environment=environment)
        git('add', '--all', environment=environment)
        return git('write-tree', environment=environment)
    finally:
        index.unlink(missing_ok=True)


def saved_pass(tree, tier, archive):
    record = read_json(result_path())
    if not record or record.get('verdict') != 'passed' or record.get('tree') != tree:
        return None
    if TIER_RANK.get(record.get('tier'), -1) < TIER_RANK[tier] or not archive.is_file() or sha256(archive) != record.get('zip_sha256'):
        return None
    return record


def save_result(record):
    write_json(result_path(), record)


def duration_text(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    return f'{minutes}m {seconds:02d}s'


def summary_line(record):
    return (f"GATE RESULT: {record['verdict'].upper()} | tier {record['tier'].upper()} | tree {record['tree'][:12]} | "
            f"zip sha256 {(record['zip_sha256'] or 'none')[:12]} | journeys {record['journeys_passed']}/{record['journeys']} | "
            f"golden {record['exports']} exports, {record['differences']} differences | "
            f"steps {record['steps_passed']}/{record['steps']} | {duration_text(record['seconds'])} | finished {record['finished']}")
