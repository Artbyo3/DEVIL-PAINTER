import ast
import importlib
from pathlib import Path
import pkgutil
import shutil
import sys
from zipfile import ZipFile
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def launcher_entries():
    return [function for function in bpy.types.VIEW3D_MT_view._dyn_ui_initialize() if function.__name__ == 'launch_menu']


def check_registered(label):
    check(hasattr(bpy.types, 'DEVIL_PAINTER_OT_editor'), label + ' editor operator registered')
    check(len(launcher_entries()) == 1, label + ' View menu launcher added once')
    check(not any(name.startswith('DEVIL_PAINTER_PT') for name in dir(bpy.types)), label + ' adds no sidebar panel')
    check(hasattr(bpy.types.Object, 'devil_painter'), label + ' layer stack property registered')
    check(all(hasattr(bpy.types, name) for name in ('DEVIL_PAINTER_OT_export_textures', 'DEVIL_PAINTER_OT_pick_color', 'DEVIL_PAINTER_OT_rename_layer')), label + ' export, color and rename operators registered')


def check_unregistered(label):
    check(not hasattr(bpy.types, 'DEVIL_PAINTER_OT_editor'), label + ' editor operator unregistered cleanly')
    check(not launcher_entries(), label + ' View menu launcher removed')
    check(not hasattr(bpy.types.Object, 'devil_painter'), label + ' layer stack property removed')


pkg_dir = ROOT / 'devil_painter'
py_files = sorted(pkg_dir.glob('*.py'))
loaded_modules = {'__init__': devil_painter}
for mod_info in sorted(pkgutil.iter_modules([str(pkg_dir)]), key=lambda m: m.name):
    full_name = f'devil_painter.{mod_info.name}'
    loaded_modules[mod_info.name] = importlib.import_module(full_name)
check(len(loaded_modules) == len(py_files), f'full package import in real Blender ({len(loaded_modules)}/{len(py_files)} modules)')

for pf in py_files:
    ast.parse(pf.read_text(encoding='utf-8-sig'), filename=str(pf))

from tools.build import build_extension
zip_path = build_extension()
check(zip_path.is_file(), f'packaged extension zip exists ({zip_path.name})')
ext_root = ROOT / 'scratch' / 'ext_load_check'
shutil.rmtree(ext_root, ignore_errors=True)
pkg_target = ext_root / 'bl_ext' / 'user_default' / 'devil_painter'
pkg_target.mkdir(parents=True, exist_ok=True)
(ext_root / 'bl_ext' / '__init__.py').write_text('', encoding='utf-8')
(ext_root / 'bl_ext' / 'user_default' / '__init__.py').write_text('', encoding='utf-8')
with ZipFile(zip_path, 'r') as zf:
    zf.extractall(pkg_target)
saved_bl_ext = {k: v for k, v in sys.modules.items() if k == 'bl_ext' or k.startswith('bl_ext.')}
for k in list(saved_bl_ext):
    del sys.modules[k]
sys.path.insert(0, str(ext_root))
try:
    bl_ext_mod = importlib.import_module('bl_ext')
    bl_ext_mod.__path__ = [str(ext_root / 'bl_ext')]
    user_def_mod = importlib.import_module('bl_ext.user_default')
    user_def_mod.__path__ = [str(ext_root / 'bl_ext' / 'user_default')]
    ext_pkg = importlib.import_module('bl_ext.user_default.devil_painter')
    check(Path(ext_pkg.__file__).resolve().is_relative_to(pkg_target.resolve()), 'bl_ext.user_default.devil_painter loaded from packaged zip')
    ext_pkg.register()
    check_registered('extension')
    ext_pkg.unregister()
    check_unregistered('extension')
finally:
    sys.path.remove(str(ext_root))
    for k in [k for k in sys.modules if k == 'bl_ext' or k.startswith('bl_ext.')]:
        del sys.modules[k]
    sys.modules.update(saved_bl_ext)
    shutil.rmtree(ext_root, ignore_errors=True)
    scratch_dir = ROOT / 'scratch'
    if scratch_dir.exists() and not any(scratch_dir.iterdir()):
        scratch_dir.rmdir()

devil_painter.register()
check_registered('direct package')
devil_painter.unregister()
check_unregistered('direct package')
print('ALL BLENDER SMOKE CHECKS PASSED', bpy.app.version_string)
