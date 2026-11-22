import os
import re
import sys
import time
import ctypes
import shutil
import argparse
import threading
import traceback
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0, str(ROOT))
from tools import gate, gate_state, workspace
from tools.gate_state import GateBusy
from tools.workspace import FAILURE_RECORD_VARIABLE, child_environment, clean_scratch, extension_archive, prepare_scratch, scratch_root

MINIMUM_BLENDER = (5, 2)
STEAM_BLENDER = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
BLENDER_FOUNDATION = Path(r"C:\Program Files\Blender Foundation")
GUI_HELPERS = frozenset(("gui_harness.py",))


def discover_gui_suites(tests_dir=ROOT / "tests"):
    return tuple(sorted(path.name for path in tests_dir.glob("gui_*.py") if path.name not in GUI_HELPERS))


GUI_SUITES = discover_gui_suites()
JOURNEYS = ("blender_api.py",) + GUI_SUITES
SLOWEST_JOURNEYS = ("gui_layers.py", "gui_project.py", "gui_positional.py", "gui_slope_normal.py", "gui_extras.py", "gui_masks.py", "gui_anchors.py", "gui_editor.py")
EXCLUSIVE_JOURNEYS = ()
JOURNEY_THREADS = 4
JOURNEY_MEMORY = 4 * 2 ** 30
JOURNEY_VIDEO_MEMORY = 2 * 2 ** 30
JOURNEY_TIMEOUT = 1200
STEP_TIMEOUT = 1800
WAIT_LIMIT = 540
WAIT_POLL = 5
START_GRACE = 60
TAIL_LINES = 30
RUN_ID_VARIABLE = 'DEVIL_PAINTER_RUN_ID'
WINDOWS_DETACH = 0x08000000 | 0x00000200
WINDOWS_BREAKAWAY = 0x01000000
BLENDER = {}
SCAN_STEP = "Rule Zero, dead-code and import scan"
INSTALL_STEP = "Install the validated zip into Blender user extensions"
SMOKE_STEP = "Real-Blender smoke suite and zip load gate"


class BlenderMissing(Exception):
    pass


@dataclass
class Outcome:
    name: str
    passed: bool
    seconds: float
    log: Path | None
    detail: str


@dataclass
class Run:
    id: str
    folder: Path
    outcomes: list = field(default_factory=list)
    journeys: int = 0
    journeys_passed: int = 0
    exports: int = 0
    differences: int = 0
    package: dict | None = None

    @property
    def logs(self):
        return self.folder / 'logs'

    def record(self, name, passed, seconds=0.0, log=None, detail=''):
        self.outcomes.append(Outcome(name, passed, seconds, log, detail))
        where = f' log {shown(log)}' if log and not passed else ''
        print(f"<-- {name}: {'OK' if passed else 'FAILED'} ({detail + ', ' if detail and not passed else ''}{seconds:.1f}s){where}")
        return passed

    def failures(self):
        return [outcome for outcome in self.outcomes if not outcome.passed]


def shown(path):
    path = Path(path)
    return path.relative_to(workspace.ROOT).as_posix() if path.is_relative_to(workspace.ROOT) else path.name


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def slug(name):
    return re.sub(r'[^A-Za-z0-9_.]+', '-', name).strip('-').lower()


def blender_version(path):
    try:
        output = subprocess.run([str(path), '--version'], capture_output=True, text=True, errors='replace', timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r'Blender (\d+)\.(\d+)', output)
    return (int(match[1]), int(match[2])) if match else None


def blender_candidates():
    if os.environ.get('BLENDER'):
        return [Path(os.environ['BLENDER'])]
    found = shutil.which('blender')
    return [STEAM_BLENDER, *sorted(BLENDER_FOUNDATION.glob('Blender */blender.exe'), reverse=True), *([Path(found)] if found else [])]


def find_blender():
    rejected = []
    for candidate in blender_candidates():
        if not candidate.is_file():
            if os.environ.get('BLENDER'):
                rejected.append(f'BLENDER points at {candidate}, which does not exist')
            continue
        version = blender_version(candidate)
        if version and version >= MINIMUM_BLENDER:
            return str(candidate)
        rejected.append(f"{candidate} is Blender {'.'.join(map(str, version)) if version else 'of unknown version'}")
    found = f" Rejected: {'; '.join(rejected)}." if rejected else ''
    raise BlenderMissing(f'No Blender {MINIMUM_BLENDER[0]}.{MINIMUM_BLENDER[1]} or newer was found.{found} '
                         'Set the BLENDER environment variable to the blender executable of Blender 5.2 or newer.')


def blender():
    if 'path' not in BLENDER:
        BLENDER['path'] = find_blender()
    return BLENDER['path']


def print_tail(path, lines=TAIL_LINES):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except FileNotFoundError:
        return
    print(f'    last {min(lines, len(text))} lines of {shown(path)}:')
    for line in text[-lines:]:
        print(f'    | {line}')


def run_process(command, log, environment, timeout, echo):
    started = time.time()
    with log.open('w', encoding='utf-8', errors='replace') as handle:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                   stdout=subprocess.PIPE if echo else handle, text=True, encoding='utf-8', errors='replace')
        reader = None
        if echo:
            def copy():
                for line in process.stdout:
                    handle.write(line)
                    handle.flush()
                    sys.stdout.write('    ' + line)
            reader = threading.Thread(target=copy, daemon=True)
            reader.start()
        try:
            code, timed_out = process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            process.kill()
            code, timed_out = process.wait(), True
        if reader:
            reader.join(30)
        if timed_out:
            handle.write(f'\n[gate] killed after {timeout}s without finishing\n')
    return code, timed_out, time.time() - started


def editor_failures(record):
    if not record.is_file():
        return 'the journey never opened its editor failure record'
    failures = record.read_text(encoding='utf-8', errors='replace').splitlines()
    return f"the editor recorded {len(failures)} failure(s), first: {failures[0]}" if failures else ''


def step(run, name, command, environment=None, timeout=STEP_TIMEOUT, echo=True, failure_record=None):
    print(f'--> {name}')
    log = run.logs / f'{slug(name)}.log'
    code, timed_out, seconds = run_process(command, log, environment or child_environment(run.folder), timeout, echo)
    recorded = editor_failures(failure_record) if failure_record else ''
    traceback_seen = failure_record is not None and 'Traceback' in log.read_text(encoding='utf-8', errors='replace')
    detail = (f'timed out after {timeout}s and was killed' if timed_out else f'exit code {code}' if code else recorded if recorded
              else 'Traceback in output' if traceback_seen else '')
    if detail and not echo:
        print_tail(log)
    return run.record(name, not detail, seconds, log, detail)


def python_step(run, name, *arguments):
    return step(run, name, [sys.executable, *arguments])


def smoke_command(package):
    return [blender(), "--background", "--factory-startup", "--python-exit-code", "1", "--python", "tests/blender_smoke.py", "--", str(package["path"]), package["sha256"]]


def do_public(run):
    print("\n=== PUBLICATION CHECK (CHEAPEST FAILURE FIRST) ===")
    python_step(run, "Publication check of source, history and archives", "tools/check_public.py")


def do_quick_tests(run):
    print("\n=== STATIC INTEGRITY & MOCKED HEADLESS UNIT TESTS ===")
    python_step(run, SCAN_STEP, "-m", "tools.check_dead_code")
    step(run, "Whitespace check against main", ["git", "diff", "--check", gate.merge_base()])
    python_step(run, "Mocked headless unit tests", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")


def scanned(run):
    return any(outcome.name == SCAN_STEP and outcome.passed for outcome in run.outcomes)


def do_package(run):
    print("\n=== PACKAGING & VALIDATING THE EXTENSION ONCE ===")
    run.package = None
    if not python_step(run, "Package extension zip", "tools/build.py", *(["--scanned"] if scanned(run) else [])):
        return False
    archive = extension_archive()
    digest = gate_state.sha256(archive)
    print(f"    {shown(archive)} sha256 {digest}")
    if not step(run, "Validate extension package", [blender(), "--background", "--factory-startup", "--command", "extension", "validate", str(archive)]):
        return False
    run.package = dict(path=archive, sha256=digest)
    return True


def validated_package(run, name):
    if not run.package:
        return run.record(name, False, detail="no zip from this run passed validation")
    if gate_state.sha256(run.package["path"]) != run.package["sha256"]:
        return run.record(name, False, detail="the zip changed after it was validated")
    return True


def do_smoke(run):
    print("\n=== REAL-BLENDER SMOKE SUITE ON THE VALIDATED ZIP ===")
    if validated_package(run, SMOKE_STEP):
        step(run, SMOKE_STEP, smoke_command(run.package))


def journey_command(journey):
    mode = ["--enable-event-simulate"] if journey.startswith("gui_") else ["--background"]
    return [blender(), *mode, "--factory-startup", "--python-exit-code", "1", "--python", "tools/journey_probe.py", "--python", f"tests/{journey}"]


def available_memory():
    if os.name != "nt":
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in (
            "total", "available", "total_page", "available_page", "total_virtual", "available_virtual", "available_extended")]

    status = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Cannot read the available memory")
    return status.available


def free_video_memory():
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
        return min(int(line) for line in query.stdout.split()) * 2 ** 20
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def journey_limits(count):
    limits = dict(journeys=count, processors=(os.cpu_count() or 1) // JOURNEY_THREADS, memory=available_memory() // JOURNEY_MEMORY)
    video = free_video_memory()
    if video is not None:
        limits["video memory"] = video // JOURNEY_VIDEO_MEMORY
    return limits


def run_journey(journey, run):
    number = f"{JOURNEYS.index(journey):02d}"
    scratch = prepare_scratch(run.folder / "j" / number)
    exports = run.folder / "j" / f"{journey}.jsonl"
    record = run.folder / "j" / f"{journey}.failures" if journey.startswith("gui_") else None
    environment = dict(child_environment(scratch), DEVIL_PAINTER_JOURNEY_LOG=str(exports), **({FAILURE_RECORD_VARIABLE: str(record)} if record else {}))
    passed = step(run, f"Journey {number} {journey}", journey_command(journey), environment, JOURNEY_TIMEOUT, echo=False, failure_record=record)
    return gate.read_log(exports), passed


def slowest_first(journey):
    return SLOWEST_JOURNEYS.index(journey) if journey in SLOWEST_JOURNEYS else len(SLOWEST_JOURNEYS)


def ordered(hashes):
    return {journey: hashes[journey] for journey in JOURNEYS if journey in hashes}


def run_journeys(run):
    print("\n=== REAL-BLENDER JOURNEYS (EXPORTS HASHED) ===")
    shared = [journey for journey in sorted(JOURNEYS, key=slowest_first) if journey not in EXCLUSIVE_JOURNEYS]
    limits = journey_limits(len(shared))
    workers = max(1, min(limits.values()))
    alone = f"{', '.join(EXCLUSIVE_JOURNEYS)} alone, then " if EXCLUSIVE_JOURNEYS else ""
    print(f"    {len(JOURNEYS)} journeys, each in its own scratch folder {shown(run.folder)}/j/<journey number>, logs in {shown(run.logs)}, "
          f"killed after {JOURNEY_TIMEOUT}s: {alone}{workers} at a time "
          f"({', '.join(f'{name} {limit}' for name, limit in limits.items())})")
    hashes = {}
    failed = []

    def one(journey):
        hashes[journey], passed = run_journey(journey, run)
        if not passed:
            failed.append(journey)

    for journey in EXCLUSIVE_JOURNEYS:
        one(journey)
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, shared))
    run.journeys = len(JOURNEYS)
    run.journeys_passed = len(JOURNEYS) - len(failed)
    return ordered(hashes), [journey for journey in JOURNEYS if journey in failed]


def do_journeys(run, golden_mode):
    hashes, failed = run_journeys(run)
    run.exports = sum(map(len, hashes.values()))
    count_differences = gate.export_count_differences(hashes)
    if golden_mode == "update":
        if failed:
            return run.record("Golden manifest update", False, detail=f"not written because {', '.join(failed)} failed")
        if count_differences:
            for difference in count_differences:
                print(f"    COUNT {difference}")
            return run.record("Golden manifest update", False, detail=f"{len(count_differences)} export count mismatches")
        gate.write_golden(hashes)
        print(f"Golden manifest written: {run.exports} exports across {len(hashes)} journeys -> {shown(gate.GOLDEN)}")
        return run.record("Golden manifest update", True)
    if not run.exports:
        return run.record("Golden compare", False, detail="no journey produced an export")
    differences = count_differences + gate.golden_differences(gate.read_golden(), hashes)
    run.differences = len(differences)
    print(f"Golden compare: {run.exports} exports across {len(hashes)} journeys, {len(differences)} differences")
    for difference in differences:
        print(f"    DIFFERS {difference}")
    return run.record("Golden compare", not differences, detail=f"{len(differences)} differences" if differences else "")


def user_extension_installs():
    base = Path(os.path.expandvars(r"%APPDATA%\Blender Foundation\Blender"))
    return base, sorted(base.glob("*/extensions/user_default/devil_painter"))


def remove_folder(folder):
    if workspace.is_link(folder) or not folder.is_dir():
        raise ValueError(f"{folder.name} is a link or not a folder, so it is left alone")
    shutil.rmtree(folder)


def installed_differences(archive, target):
    with ZipFile(archive) as package:
        expected = {name: package.read(name) for name in package.namelist() if not name.endswith("/")}
    present = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    differences = sorted(present.symmetric_difference(expected))
    return differences + sorted(name for name in present & expected.keys() if (target / name).read_bytes() != expected[name])


def install_package(archive, target):
    if workspace.is_link(target) or not target.is_dir():
        raise ValueError(f"{target.name} is a link or not a folder, so it is left alone")
    staging = target.with_name(target.name + ".installing")
    replaced = target.with_name(target.name + ".replaced")
    for leftover in (staging, replaced):
        if leftover.exists():
            remove_folder(leftover)
    with ZipFile(archive) as package:
        package.extractall(staging)
    target.rename(replaced)
    try:
        staging.rename(target)
    except OSError:
        replaced.rename(target)
        raise
    remove_folder(replaced)
    return installed_differences(archive, target)


def do_install(run):
    print("\n=== INSTALLING THE VALIDATED ZIP ===")
    if not validated_package(run, INSTALL_STEP):
        return False
    print(f"--> {INSTALL_STEP}")
    started = time.time()
    base, installs = user_extension_installs()
    try:
        for target in installs:
            differences = install_package(run.package["path"], target)
            where = target.relative_to(base).as_posix()
            if differences:
                return run.record(INSTALL_STEP, False, time.time() - started, detail=f"{where} differs from the zip: {', '.join(differences[:5])}")
            print(f"    Replaced Blender {where} with the zip contents, every file identical to the zip (sha256 {run.package['sha256']})")
    except (OSError, ValueError) as error:
        return run.record(INSTALL_STEP, False, time.time() - started, detail=str(error))
    if not installs:
        print("    (No Devil Painter folder in Blender's user_default extensions, nothing to replace)")
    return run.record(INSTALL_STEP, True, time.time() - started)


def do_archive_public(run):
    python_step(run, "Publication check of the built archive", "tools/check_public.py")


def journeys_group(golden_mode):
    return lambda run: do_journeys(run, golden_mode)


def gate_groups(tier, golden_mode):
    journeys = [] if tier == "light" else [journeys_group(golden_mode)]
    return [do_public, do_quick_tests, do_package, do_smoke, *journeys, do_install, do_archive_public]


def task_groups(args, golden_mode):
    return [group for enabled, group in (
        (args.quick or args.test, do_quick_tests),
        (args.test or args.build, do_package),
        (args.test or args.build, do_smoke),
        (args.test or args.golden, journeys_group(golden_mode)),
        (args.build, do_install),
        (args.build, do_archive_public),
    ) if enabled]


def chosen_tier(args):
    if args.tier == "auto":
        return gate.select_tier(gate.changed_files())
    if args.tier:
        return args.tier, f"chosen with --tier {args.tier}"
    return "full", "default for --test --build and --all"


def new_run_id():
    return os.environ.get(RUN_ID_VARIABLE) or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"


def report(run, seconds):
    failures = run.failures()
    print(f"\n=== GATE REPORT: {len(run.outcomes)} steps, {len(failures)} failed, {gate_state.duration_text(seconds)} ===")
    for outcome in failures:
        print(f"FAILED  {outcome.name}: {outcome.detail}" + (f" -> {shown(outcome.log)}" if outcome.log else ""))
    return failures


def gate_record(run, tier, tree, seconds, failures):
    archive = extension_archive()
    return dict(verdict="failed" if failures else "passed", tier=tier, tree=tree,
                zip_sha256=gate_state.sha256(archive) if archive.is_file() else None,
                journeys=run.journeys, journeys_passed=run.journeys_passed, exports=run.exports, differences=run.differences,
                steps=len(run.outcomes), steps_passed=len(run.outcomes) - len(failures), seconds=round(seconds, 1), finished=stamp())


def run_gate(groups, args, tier, run_id, command):
    started = time.time()
    status = dict(pid=os.getpid(), run=run_id, command=command, started=stamp(), started_at=started)
    if os.environ.get(RUN_ID_VARIABLE):
        status["console"] = shown(gate_state.console_path())
    tree = None
    if tier:
        tree = gate_state.tree_fingerprint()
        saved = None if args.golden == "update" or args.rerun else gate_state.saved_pass(tree, tier, extension_archive())
        if saved:
            line = gate_state.summary_line(saved)
            print(f"The gate already passed on this exact tree ({tree[:12]}) and archive; reporting the saved result instead of running it again (--rerun forces a run).")
            print(line)
            gate_state.write_status(**status, state="passed", exit_code=0, finished=stamp(), summary=line, saved=True, failures=[])
            return 0
    if any(group not in (do_public, do_quick_tests) for group in groups):
        try:
            print(f"Blender: {blender()}")
        except BlenderMissing as missing:
            print(missing)
            gate_state.write_status(**status, state="failed", exit_code=1, finished=stamp(), summary=str(missing), failures=[])
            return 1
    run = Run(run_id, prepare_scratch(scratch_root() / f"run-{run_id}"))
    run.logs.mkdir(exist_ok=True)
    status["folder"] = shown(run.folder)
    gate_state.write_status(**status, state="running")
    print(f"Gate run {run_id}: scratch and logs in {shown(run.folder)}")
    try:
        for group in groups:
            group(run)
    except Exception:
        traceback.print_exc()
        run.record("Gate runner", False, detail="the runner itself raised; see the traceback above")
    seconds = time.time() - started
    failures = report(run, seconds)
    summary = f"{len(run.outcomes)} steps, {len(failures)} failed, {gate_state.duration_text(seconds)}"
    if tier:
        record = gate_record(run, tier, tree, seconds, failures)
        summary = gate_state.summary_line(record)
        if not failures:
            if gate_state.tree_fingerprint() == tree:
                gate_state.save_result(record)
            else:
                print("The source tree changed while the gate ran, so this pass is not saved for it.")
        print(summary)
    code = 1 if failures else 0
    if failures:
        print(f"Task failed after {seconds:.0f}s. Diagnostic artifacts remain in {shown(run.folder)}; use --clean when finished.")
    elif not args.keep_scratch:
        try:
            removed = clean_scratch(run.folder)
            print(f"Scratch run folder removed ({removed} temporary files). Installable archives remain in dist.")
        except (OSError, ValueError) as error:
            print(f"Scratch cleanup failed: {error}")
            code = 1
    gate_state.write_status(**status, state="passed" if code == 0 else "failed", exit_code=code, finished=stamp(), summary=summary,
                            failures=[dict(name=outcome.name, detail=outcome.detail, log=shown(outcome.log) if outcome.log else None) for outcome in failures])
    if code == 0:
        print(f"Dev tasks completed successfully in {seconds:.0f}s!")
    return code


def execute(groups, args, tier, command):
    run_id = new_run_id()
    try:
        gate_state.acquire_lock(run_id)
    except GateBusy as busy:
        print(busy)
        return 1
    try:
        return run_gate(groups, args, tier, run_id, command)
    finally:
        gate_state.release_lock()


def clean_all():
    owner = gate_state.lock_owner()
    if owner:
        print(f"A gate is running in this worktree (PID {owner['pid']}); scratch is left alone until it ends.")
        return 1
    try:
        removed = clean_scratch(scratch_root())
    except (OSError, ValueError) as error:
        print(f"Scratch cleanup failed: {error}")
        return 1
    print(f"Scratch removed ({removed} temporary files). Installable archives remain in dist.")
    return 0


def detach(arguments):
    owner = gate_state.lock_owner()
    if owner:
        print(f"Another gate is already running in this worktree (PID {owner['pid']}, run {owner.get('run')}). Follow it with `python tools/dev.py --wait`.")
        return 1
    run_id = new_run_id()
    console = gate_state.console_path()
    prepare_scratch(scratch_root())
    command = " ".join(arguments)
    gate_state.write_status(pid=None, run=run_id, command=command, started=stamp(), started_at=time.time(), state="starting", console=shown(console))
    spawn = [sys.executable, "-B", "-u", str(Path(__file__).resolve()), *arguments]
    environment = dict(os.environ, PYTHONUNBUFFERED="1", **{RUN_ID_VARIABLE: run_id})
    with console.open("w", encoding="utf-8") as handle:
        options = dict(cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT)
        if os.name == "nt":
            try:
                process = subprocess.Popen(spawn, creationflags=WINDOWS_DETACH | WINDOWS_BREAKAWAY, **options)
            except OSError:
                process = subprocess.Popen(spawn, creationflags=WINDOWS_DETACH, **options)
        else:
            process = subprocess.Popen(spawn, start_new_session=True, **options)
    status = gate_state.read_status()
    if status and status.get("run") == run_id and status.get("state") == "starting":
        gate_state.write_status(**dict(status, pid=process.pid))
    print(f"Gate started in the background: run {run_id}, PID {process.pid}, console log {shown(console)}.")
    print("Wait for it with `python tools/dev.py --wait` (exit 0 passed, 1 failed, 2 still running).")
    return 0


def still_running(status):
    if status.get("pid"):
        return gate_state.process_alive(status["pid"])
    return time.time() - status.get("started_at", 0) < START_GRACE


def show_finished(status):
    if status.get("console"):
        print_tail(workspace.ROOT / status["console"])
    for failure in status.get("failures") or []:
        print(f"FAILED  {failure['name']}: {failure['detail']}" + (f" -> {failure['log']}" if failure.get("log") else ""))
    print(status.get("summary", ""))
    return 0 if status["state"] == "passed" else 1


def wait_for_gate():
    deadline = time.time() + WAIT_LIMIT
    announced = False
    while True:
        status = gate_state.read_status()
        if not status:
            print("No gate run is recorded in this worktree. Start one with `python tools/dev.py --detach --tier auto`.")
            return 1
        if status["state"] in ("passed", "failed", "dead"):
            print(f"Gate run {status['run']} {status['state']} ({status['command']}).")
            return show_finished(status)
        if not still_running(status):
            gate_state.write_status(**dict(status, state="dead", finished=stamp(), summary="the gate process ended without reporting a verdict"))
            print(f"Gate run {status['run']} is dead: its process (PID {status.get('pid')}) ended without reporting a verdict.")
            if status.get("console"):
                print_tail(workspace.ROOT / status["console"])
            if status.get("folder"):
                print(f"Its logs remain in {status['folder']}/logs.")
            return 1
        if time.time() >= deadline:
            print(f"Gate run {status['run']} is still running after {WAIT_LIMIT // 60} minutes of waiting. Run --wait again.")
            if status.get("console"):
                print_tail(workspace.ROOT / status["console"], 10)
            return 2
        if not announced:
            print(f"Waiting up to {WAIT_LIMIT // 60} minutes for gate run {status['run']} (PID {status.get('pid')})...")
            announced = True
        time.sleep(WAIT_POLL)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True, errors="replace")
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Devil Painter Dev Tool")
    parser.add_argument("--quick", action="store_true", help="Run fast headless unit tests only")
    parser.add_argument("--test", action="store_true", help="Run all unit, Blender smoke, and GUI tests with the golden journey compare")
    parser.add_argument("--build", action="store_true", help="Build, validate, and sync")
    parser.add_argument("--all", action="store_true", help="Test, build, and validate")
    parser.add_argument("--tier", choices=("auto", *gate.TIER_NAMES), help="Run the gate at a risk tier; auto picks it from the tracked diff against main")
    parser.add_argument("--plan", action="store_true", help="With --tier, print the chosen tier and why without running it")
    parser.add_argument("--golden", choices=("compare", "update"), help="Alone, run every journey and compare to or rewrite the golden manifest; with a gate, choose what its journeys do")
    parser.add_argument("--rerun", action="store_true", help="Run the gate even when it already passed on this exact tree")
    parser.add_argument("--detach", action="store_true", help="Start the requested task in the background and return at once")
    parser.add_argument("--wait", action="store_true", help="Wait up to 9 minutes for the gate: exit 0 passed, 1 failed or dead, 2 still running")
    parser.add_argument("--clean", action="store_true", help="Delete disposable scratch artifacts without touching dist or source")
    parser.add_argument("--keep-scratch", action="store_true", help="Keep artifacts after success for manual inspection")

    args = parser.parse_args(arguments)
    tasks = [args.quick, args.test, args.build, args.all, args.golden, args.tier]
    if args.wait and (any(tasks) or args.detach or args.clean):
        parser.error('--wait follows a running gate; do not combine it with other options')
    if args.clean and (any(tasks) or args.keep_scratch or args.detach):
        parser.error('--clean runs alone')
    if args.tier and (args.quick or args.test or args.build or args.all):
        parser.error('--tier runs the whole gate; do not combine it with --quick, --test, --build or --all')
    if args.plan and not args.tier:
        parser.error('--plan needs --tier')
    if args.detach and (args.plan or not any(tasks)):
        parser.error('--detach needs a task to run, such as --tier auto')
    if args.wait:
        return wait_for_gate()
    if args.clean:
        return clean_all()
    if not any(tasks):
        parser.print_help()
        return 0
    if args.detach:
        return detach([argument for argument in arguments if argument != "--detach"])

    golden_mode = args.golden or "compare"
    gated = bool(args.tier or args.all or (args.test and args.build))
    tier = None
    if gated:
        tier, reason = chosen_tier(args)
        print(f"GATE TIER: {tier.upper()} ({reason})")
        untracked = gate.untracked_files()
        if untracked:
            print(f"Untracked files (named only, they do not change the tier): {gate.listed(untracked)}")
        if args.plan:
            return 0
        groups = gate_groups(tier, golden_mode)
    else:
        groups = task_groups(args, golden_mode)
    return execute(groups, args, tier, " ".join(arguments))


if __name__ == '__main__':
    sys.exit(main())
