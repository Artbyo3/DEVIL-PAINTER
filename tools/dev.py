import os
import sys
import time
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from tools.workspace import child_environment, clean_scratch, extension_archive, prepare_scratch

BLENDER_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
if not os.path.exists(BLENDER_PATH):
    for p in [r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"]:
        if os.path.exists(p):
            BLENDER_PATH = p
            break


def run_cmd(cmd, cwd=str(ROOT), desc=""):
    if desc:
        print(f"--> {desc}...")
    t0 = time.time()
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=child_environment())
    dt = time.time() - t0
    gui_test = any(Path(argument).name.startswith('gui_') for argument in cmd)
    if res.returncode != 0 or (gui_test and 'Traceback' in res.stdout + res.stderr):
        print(f"FAILED in {dt:.2f}s:")
        print(res.stdout)
        print(res.stderr)
        return False
    print(f"    OK ({dt:.2f}s)")
    return True


def do_quick_tests():
    print("\n=== RUNNING STATIC INTEGRITY & MOCKED HEADLESS UNIT TESTS ===")
    if not run_cmd([sys.executable, "-m", "tools.check_dead_code"],
                   desc="Static Import & Dead-Code Integrity"):
        return False
    return run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                   desc="Mocked Headless Unit Tests")


def do_tests():
    print("\n=== RUNNING ALL TEST SUITES ===")

    if not do_quick_tests():
        return False

    print("\n=== RUNNING REAL-BLENDER BACKGROUND & LOAD SMOKE SUITES ===")
    for t in ["blender_smoke.py", "blender_api.py"]:
        if not run_cmd([BLENDER_PATH, "--background", "--factory-startup", "--python-exit-code", "1", "--python", f"tests/{t}"],
                       desc=f"Blender Background: {t}"):
            return False

    print("\n=== RUNNING REAL-BLENDER IN-ENGINE GUI SUITES ===")
    for t in ["gui_editor.py", "gui_project.py", "gui_layers.py", "gui_baking.py", "gui_masks.py", "gui_content.py", "gui_painting.py", "gui_shelf.py", "gui_extras.py", "gui_packs.py", "gui_udim.py", "gui_library.py", "gui_layout.py", "gui_reopen.py", "gui_layer_delete.py"]:
        if not run_cmd([BLENDER_PATH, "--enable-event-simulate", "--factory-startup", "--python", f"tests/{t}"],
                       desc=f"In-Engine GUI: {t}"):
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

    if not run_cmd([BLENDER_PATH, "--background", "--factory-startup", "--python-exit-code", "1", "--python", "tests/blender_smoke.py"],
                   desc="Real-Blender Full-Package & Zip Load Gate"):
        return False

    print("BUILD & VALIDATION COMPLETE!\n")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Devil Painter Dev Tool")
    parser.add_argument("--quick", action="store_true", help="Run fast headless unit tests only")
    parser.add_argument("--test", action="store_true", help="Run all unit, Blender smoke, and GUI tests")
    parser.add_argument("--build", action="store_true", help="Build, validate, and sync")
    parser.add_argument("--all", action="store_true", help="Test, build, and validate")
    parser.add_argument("--clean", action="store_true", help="Delete disposable scratch artifacts without touching dist or source")
    parser.add_argument("--keep-scratch", action="store_true", help="Keep artifacts after success for manual inspection")

    args = parser.parse_args(argv)
    if args.clean and args.keep_scratch:
        parser.error('--clean and --keep-scratch cannot be combined')
    if not any([args.quick, args.test, args.build, args.all, args.clean]):
        parser.print_help()
        return 0

    operations = [
        (args.quick, do_quick_tests),
        (args.test or args.all, do_tests),
        (args.build or args.all, do_build),
    ]
    if any(enabled for enabled, operation in operations):
        prepare_scratch()
    for enabled, operation in operations:
        if enabled and not operation():
            print('Task failed. Diagnostic artifacts remain in scratch; use --clean when finished.')
            return 1
    if not args.keep_scratch:
        try:
            removed = clean_scratch()
        except (OSError, ValueError) as error:
            print(f'Scratch cleanup failed: {error}')
            return 1
        print(f'Scratch removed ({removed} temporary files). Installable archives remain in dist.')

    print("Dev tasks completed successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
