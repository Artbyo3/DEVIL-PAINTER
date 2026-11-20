import os
import sys
import time
import ctypes
import argparse
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from tools import gate
from tools.workspace import child_environment, clean_scratch, extension_archive, prepare_scratch

BLENDER_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
if not os.path.exists(BLENDER_PATH):
    for p in [r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"]:
        if os.path.exists(p):
            BLENDER_PATH = p
            break

GUI_SUITES = ("gui_editor.py", "gui_project.py", "gui_layers.py", "gui_baking.py", "gui_masks.py", "gui_content.py", "gui_anchors.py", "gui_positional.py", "gui_slope_normal.py", "gui_uv_transform.py", "gui_triplanar_hardness.py", "gui_pressure.py", "gui_jitter.py", "gui_follow_path.py", "gui_texture_sampling.py", "gui_painting.py", "gui_shelf.py", "gui_extras.py", "gui_packs.py", "gui_udim.py", "gui_library.py", "gui_layout.py", "gui_reopen.py", "gui_layer_delete.py", "gui_world_size.py", "gui_shift_line.py", "gui_stencil_drag.py", "gui_material_stroke.py")
JOURNEYS = ("blender_api.py",) + GUI_SUITES
SLOWEST_JOURNEYS = ("gui_layers.py", "gui_project.py", "gui_positional.py", "gui_slope_normal.py", "gui_extras.py", "gui_masks.py", "gui_anchors.py", "gui_editor.py")
EXCLUSIVE_JOURNEYS = ("blender_api.py", "gui_library.py", "gui_packs.py")
JOURNEY_THREADS = 4
JOURNEY_MEMORY = 4 * 2 ** 30
JOURNEY_VIDEO_MEMORY = 2 * 2 ** 30
SMOKE_COMMAND = [BLENDER_PATH, "--background", "--factory-startup", "--python-exit-code", "1", "--python", "tests/blender_smoke.py"]


def execute(cmd, environment):
    t0 = time.time()
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=environment)
    gui_test = any(Path(argument).name.startswith('gui_') for argument in cmd)
    return res, time.time() - t0, res.returncode == 0 and not (gui_test and 'Traceback' in res.stdout + res.stderr)


def report(res, dt, passed):
    if not passed:
        print(f"FAILED in {dt:.2f}s:")
        print(res.stdout)
        print(res.stderr)
        return False
    print(f"    OK ({dt:.2f}s)")
    return True


def run_cmd(cmd, desc="", env=None):
    if desc:
        print(f"--> {desc}...")
    return report(*execute(cmd, dict(child_environment(), **(env or {}))))


def do_quick_tests():
    print("\n=== RUNNING STATIC INTEGRITY & MOCKED HEADLESS UNIT TESTS ===")
    if not run_cmd([sys.executable, "-m", "tools.check_dead_code"], desc="Static Import & Dead-Code Integrity"):
        return False
    if not run_cmd(["git", "diff", "--check", gate.merge_base()], desc="Whitespace check against main"):
        return False
    return run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                   desc="Mocked Headless Unit Tests")


def do_smoke():
    print("\n=== RUNNING REAL-BLENDER BACKGROUND & LOAD SMOKE SUITE ===")
    return run_cmd(SMOKE_COMMAND, desc="Blender Background: blender_smoke.py")


def journey_command(journey):
    mode = ["--enable-event-simulate"] if journey.startswith("gui_") else ["--background", "--python-exit-code", "1"]
    return [BLENDER_PATH, *mode, "--factory-startup", "--python", "tools/journey_probe.py", "--python", f"tests/{journey}"]


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


def fresh_folder(parent):
    number = 0
    while True:
        try:
            (parent / str(number)).mkdir()
            return parent / str(number)
        except FileExistsError:
            number += 1


def run_journey(journey, run):
    scratch = run / f"{JOURNEYS.index(journey):02d}"
    scratch.mkdir()
    log = run / f"{journey}.jsonl"
    return execute(journey_command(journey), dict(child_environment(scratch), DEVIL_PAINTER_JOURNEY_LOG=str(log))) + (log,)


def run_journeys(keep_going):
    print("\n=== RUNNING REAL-BLENDER JOURNEYS (EXPORTS HASHED) ===")
    journeys = prepare_scratch() / "j"
    journeys.mkdir(exist_ok=True)
    run = fresh_folder(journeys)
    shared = [journey for journey in sorted(JOURNEYS, key=slowest_first) if journey not in EXCLUSIVE_JOURNEYS]
    limits = journey_limits(len(shared))
    workers = max(1, min(limits.values()))
    print(f"    {len(JOURNEYS)} journeys, each in its own scratch folder {run.relative_to(ROOT).as_posix()}/<journey number>: "
          f"{', '.join(EXCLUSIVE_JOURNEYS)} alone, then {workers} at a time ({', '.join(f'{name} {limit}' for name, limit in limits.items())})")
    hashes = {}
    failed = []

    def finish(journey, res, dt, passed, log):
        print(f"--> Journey: {journey} ({JOURNEYS.index(journey):02d})...")
        hashes[journey] = gate.read_log(log)
        if not report(res, dt, passed):
            failed.append(journey)

    for journey in EXCLUSIVE_JOURNEYS:
        finish(journey, *run_journey(journey, run))
        if failed and not keep_going:
            return ordered(hashes), failed
    stopped = threading.Event()

    def unless_stopped(journey):
        if stopped.is_set():
            return None
        outcome = run_journey(journey, run)
        if not outcome[2] and not keep_going:
            stopped.set()
        return outcome

    with ThreadPoolExecutor(workers) as pool:
        running = {pool.submit(unless_stopped, journey): journey for journey in shared}
        for done in as_completed(running):
            if done.result() is not None:
                finish(running[done], *done.result())
    return ordered(hashes), [journey for journey in JOURNEYS if journey in failed]


def slowest_first(journey):
    return SLOWEST_JOURNEYS.index(journey) if journey in SLOWEST_JOURNEYS else len(SLOWEST_JOURNEYS)


def ordered(hashes):
    return {journey: hashes[journey] for journey in JOURNEYS if journey in hashes}


def do_journeys(golden_mode, keep_going=False):
    hashes, failed = run_journeys(keep_going)
    exports = sum(map(len, hashes.values()))
    if golden_mode == "update":
        if failed:
            print(f"Golden manifest not written: {', '.join(failed)} failed.")
            return False
        gate.write_golden(hashes)
        print(f"Golden manifest written: {exports} exports across {len(hashes)} journeys -> {gate.GOLDEN.relative_to(ROOT).as_posix()}")
        return True
    if failed and not keep_going:
        return False
    differences = gate.golden_differences(gate.read_golden(), hashes)
    print(f"Golden compare: {exports} exports across {len(hashes)} journeys, {len(differences)} differences")
    for difference in differences:
        print(f"    DIFFERS {difference}")
    if failed:
        print(f"Journeys that failed: {', '.join(failed)}")
    return not differences and not failed


def do_tests(golden_mode="compare"):
    print("\n=== RUNNING ALL TEST SUITES ===")
    if not (do_quick_tests() and do_smoke() and do_journeys(golden_mode)):
        return False
    print("ALL TESTS PASSED!\n")
    return True


def do_build():
    print("\n=== BUILDING & VALIDATING EXTENSION ===")

    if not run_cmd([sys.executable, "tools/build.py"], desc="Package extension zip"):
        return False

    zip_path = extension_archive()

    if not run_cmd([BLENDER_PATH, "--background", "--factory-startup", "--command", "extension", "validate", str(zip_path)],
                   desc="Validate extension package"):
        return False

    import shutil
    installs = sorted(Path(os.path.expandvars(r"%APPDATA%\Blender Foundation\Blender")).glob("*/extensions/user_default/devil_painter"))
    for user_ext in installs:
        shutil.copytree(ROOT / "devil_painter", user_ext, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        print(f"    Synced to {user_ext}")
    if not installs:
        print(f"    (User extensions folder not found, skipping sync)")

    if not run_cmd(SMOKE_COMMAND, desc="Real-Blender Full-Package & Zip Load Gate"):
        return False

    if not run_cmd([sys.executable, "tools/check_public.py"], desc="Public source and archive check"):
        return False

    print("BUILD & VALIDATION COMPLETE!\n")
    return True


def test_step(golden_mode):
    return do_tests if golden_mode == "compare" else lambda: do_tests(golden_mode)


def tier_steps(tier, golden_mode):
    return [do_quick_tests if tier == "light" else test_step(golden_mode), do_build]


def chosen_tier(args):
    if args.tier == "auto":
        return gate.select_tier(gate.changed_files())
    if args.tier:
        return args.tier, f"chosen with --tier {args.tier}"
    return "full", "default for --test --build and --all"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Devil Painter Dev Tool")
    parser.add_argument("--quick", action="store_true", help="Run fast headless unit tests only")
    parser.add_argument("--test", action="store_true", help="Run all unit, Blender smoke, and GUI tests with the golden journey compare")
    parser.add_argument("--build", action="store_true", help="Build, validate, and sync")
    parser.add_argument("--all", action="store_true", help="Test, build, and validate")
    parser.add_argument("--tier", choices=("auto", *gate.TIER_NAMES), help="Run the gate at a risk tier; auto picks it from the diff against main")
    parser.add_argument("--plan", action="store_true", help="With --tier, print the chosen tier and why without running it")
    parser.add_argument("--golden", choices=("compare", "update"), help="Alone, run every journey and compare to or rewrite the golden manifest; with a gate, choose what its journeys do")
    parser.add_argument("--clean", action="store_true", help="Delete disposable scratch artifacts without touching dist or source")
    parser.add_argument("--keep-scratch", action="store_true", help="Keep artifacts after success for manual inspection")

    args = parser.parse_args(argv)
    if args.clean and args.keep_scratch:
        parser.error('--clean and --keep-scratch cannot be combined')
    if args.tier and (args.quick or args.test or args.build or args.all):
        parser.error('--tier runs the whole gate; do not combine it with --quick, --test, --build or --all')
    if args.plan and not args.tier:
        parser.error('--plan needs --tier')
    gated = bool(args.tier or args.all or (args.test and args.build))
    if not any([args.quick, args.test, args.build, args.golden, gated, args.clean]):
        parser.print_help()
        return 0

    started = time.time()
    golden_mode = args.golden or "compare"
    if gated:
        tier, reason = chosen_tier(args)
        print(f"GATE TIER: {tier.upper()} ({reason})")
        if args.plan:
            return 0
        operations = [(True, step) for step in tier_steps(tier, golden_mode)]
    else:
        operations = [
            (args.quick, do_quick_tests),
            (args.test, test_step(golden_mode)),
            (args.golden and not args.test, lambda: do_journeys(golden_mode, keep_going=True)),
            (args.build, do_build),
        ]
    if any(enabled for enabled, operation in operations):
        prepare_scratch()
    for enabled, operation in operations:
        if enabled and not operation():
            print(f'Task failed after {time.time() - started:.0f}s. Diagnostic artifacts remain in scratch; use --clean when finished.')
            return 1
    if not args.keep_scratch:
        try:
            removed = clean_scratch()
        except (OSError, ValueError) as error:
            print(f'Scratch cleanup failed: {error}')
            return 1
        print(f'Scratch removed ({removed} temporary files). Installable archives remain in dist.')

    print(f"Dev tasks completed successfully in {time.time() - started:.0f}s!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
