import ast
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_comments import check_repository

SCANNED = ('devil_painter', 'tools')
REFERENCING = SCANNED + ('tests',)
DRAW_FILES = ('devil_painter/editor.py', 'devil_painter/minimal.py', 'devil_painter/draw.py', 'devil_painter/canvas.py', 'devil_painter/shell.py', 'devil_painter/ui.py')
LIFECYCLE = {'bl_info', 'register', 'unregister'}
OBJECT_MEMBERS = set(dir(object)) | {'__dict__', '__dataclass_fields__'}
INSPECTORS = {'getattr', 'hasattr', 'setattr', 'delattr'}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = FUNCTIONS + (ast.Lambda, ast.ClassDef)


@dataclass
class Module:
    path: Path
    name: str
    tree: ast.Module
    relative: str
    aliases: dict = field(default_factory=dict)

    @property
    def package(self):
        return self.name if self.path.name == '__init__.py' else self.name.rpartition('.')[0]


@dataclass
class ClassInfo:
    module: Module
    node: ast.ClassDef
    members: set = field(default_factory=set)
    fields: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)
    closed: bool = False


def module_name(root, path):
    parts = list(path.relative_to(root).with_suffix('').parts)
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def load_modules(root, directories=REFERENCING):
    modules = {}
    for directory in directories:
        folder = root / directory
        if not folder.is_dir():
            raise FileNotFoundError(f'check_dead_code: folder {directory}/ is missing')
        for path in sorted(folder.rglob('*.py')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            name = module_name(root, path)
            modules[name] = Module(path, name, ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path)), path.relative_to(root).as_posix())
    for module in modules.values():
        module.aliases = import_aliases(module, modules)
    return modules


def import_base(module, node):
    if not node.level:
        return node.module or ''
    parts = module.package.split('.')
    parts = parts[:len(parts) - node.level + 1]
    return '.'.join(parts + ([node.module] if node.module else []))


def import_aliases(module, modules):
    aliases = {}
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = ('module', alias.name)
                else:
                    aliases[alias.name.split('.')[0]] = ('module', alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            base = import_base(module, node)
            for alias in node.names:
                if alias.name == '*':
                    continue
                target = f'{base}.{alias.name}' if base else alias.name
                aliases[alias.asname or alias.name] = ('module', target) if target in modules else ('symbol', base, alias.name)
    return aliases


def target_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in target_names(element)]
    if isinstance(target, ast.Starred):
        return target_names(target.value)
    return []


def top_level_statements(body):
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for branch in ('body', 'orelse', 'finalbody'):
                yield from top_level_statements(getattr(node, branch, []))
            for handler in getattr(node, 'handlers', []):
                yield from top_level_statements(handler.body)


def definitions(module):
    found = {}
    for node in top_level_statements(module.tree.body):
        if isinstance(node, FUNCTIONS + (ast.ClassDef,)):
            found[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in target_names(target):
                    found[name] = node
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            for name in target_names(node.target):
                found[name] = node
    return found


def exports(module, modules):
    names = set(definitions(module))
    for node in top_level_statements(module.tree.body):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    prefix = module.name + '.'
    names.update(name[len(prefix):] for name in modules if name.startswith(prefix) and '.' not in name[len(prefix):])
    return names


def module_of(module, expr, modules):
    if isinstance(expr, ast.Name):
        alias = module.aliases.get(expr.id)
        return alias[1] if alias and alias[0] == 'module' and alias[1] in modules else None
    if isinstance(expr, ast.Attribute):
        base = module_of(module, expr.value, modules)
        if base and f'{base}.{expr.attr}' in modules:
            return f'{base}.{expr.attr}'
    return None


def dotted_target(text, modules):
    head, _, name = text.rpartition('.')
    return (head, name) if head in modules else None


def references(modules):
    found = set()
    for module in modules.values():
        own = definitions(module)
        collect_references(module, module.tree, None, own, modules, found)
        scripts = [node.value for node in ast.walk(module.tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        found.update((module.name, name) for name in own if any(f'.{name}(' in script for script in scripts))
        if '__all__' in own and isinstance(own['__all__'], ast.Assign) and isinstance(own['__all__'].value, (ast.List, ast.Tuple)):
            found.update((module.name, item.value) for item in own['__all__'].value.elts if isinstance(item, ast.Constant))
    changed = True
    while changed:
        changed = False
        for module in modules.values():
            for alias, target in module.aliases.items():
                if target[0] == 'symbol' and (module.name, alias) in found and (target[1], target[2]) not in found:
                    found.add((target[1], target[2]))
                    changed = True
    return found


def collect_references(module, node, owner, own, modules, found):
    for child in ast.iter_child_nodes(node):
        child_owner = owner
        if owner is None and node is module.tree and isinstance(child, FUNCTIONS + (ast.ClassDef,)):
            child_owner = child.name
        if isinstance(child, ast.Name) and not isinstance(child.ctx, ast.Store):
            alias = module.aliases.get(child.id)
            if alias and alias[0] == 'symbol':
                found.add((alias[1], alias[2]))
            elif child.id in own and child.id != child_owner:
                found.add((module.name, child.id))
        elif isinstance(child, ast.Attribute):
            target = module_of(module, child.value, modules)
            if target:
                found.add((target, child.attr))
        elif isinstance(child, ast.Call) and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
            name = child.func.id if isinstance(child.func, ast.Name) else child.func.attr if isinstance(child.func, ast.Attribute) else ''
            if name == 'patch' and dotted_target(child.args[0].value, modules):
                found.add(dotted_target(child.args[0].value, modules))
        if isinstance(child, ast.Call) and len(child.args) > 1 and isinstance(child.args[1], ast.Constant) and isinstance(child.args[1].value, str):
            name = child.func.id if isinstance(child.func, ast.Name) else child.func.attr if isinstance(child.func, ast.Attribute) else ''
            target = module_of(module, child.args[0], modules)
            if target and (name in INSPECTORS or name == 'object'):
                found.add((target, child.args[1].value))
        collect_references(module, child, child_owner, own, modules, found)


def unused_definitions(modules, scanned):
    found = references(modules)
    violations = []
    for module in scanned:
        for name, node in definitions(module).items():
            if name.startswith('__') and name.endswith('__'):
                continue
            if name in LIFECYCLE and module.name.startswith('devil_painter'):
                continue
            if (module.name, name) not in found:
                kind = 'class' if isinstance(node, ast.ClassDef) else 'function' if isinstance(node, FUNCTIONS) else 'variable'
                violations.append(f'{module.relative}:{node.lineno}: unused {kind} {name}')
    return violations


def unused_imports(module):
    imported = {}
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.asname or alias.name.split('.')[0]] = (alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.asname or alias.name] = (f'{node.module}.{alias.name}', node.lineno)
    used = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            used.add(node.id)
    return [f'{module.relative}:{line}: unused import {origin}' for name, (origin, line) in imported.items() if name not in used]


def rebound_names(module):
    names = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def missing_imports(modules, scanned):
    project_roots = {name.split('.')[0] for name in modules}
    table = {name: exports(module, modules) for name, module in modules.items()}
    violations = []
    for module in scanned:
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            base = import_base(module, node)
            if base.split('.')[0] not in project_roots:
                continue
            if base not in modules and not any(name.startswith(base + '.') for name in modules):
                violations.append(f'{module.relative}:{node.lineno}: missing module {base}')
                continue
            for alias in node.names:
                if alias.name != '*' and alias.name not in table.get(base, ()) and f'{base}.{alias.name}' not in modules:
                    violations.append(f'{module.relative}:{node.lineno}: missing import {alias.name} from {base}')
        rebound = rebound_names(module)
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id in rebound):
                target = module_of(module, node.value, modules)
                if target and node.attr not in table[target]:
                    violations.append(f'{module.relative}:{node.lineno}: missing attribute {node.attr} on module {target}')
    return violations


def symbol_of(module, expr, modules, seen=()):
    if isinstance(expr, ast.Name):
        alias = module.aliases.get(expr.id)
        if alias and alias[0] == 'symbol':
            target = (alias[1], alias[2])
        elif expr.id in definitions(module):
            return module.name, expr.id
        else:
            return None
    elif isinstance(expr, ast.Attribute):
        base = module_of(module, expr.value, modules)
        if not base:
            return None
        target = (base, expr.attr)
    else:
        return None
    source = modules.get(target[0])
    if source is None or target in seen:
        return None
    if target[1] in definitions(source):
        return target
    return symbol_of(source, ast.Name(target[1], ast.Load()), modules, seen + (target,))


def dataclass_decorator(decorator):
    core = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(core, ast.Name) and core.id == 'dataclass' or isinstance(core, ast.Attribute) and core.attr == 'dataclass'


class Classes:
    def __init__(self, modules):
        self.modules = modules
        self.table = {}
        for module in modules.values():
            for name, node in definitions(module).items():
                if isinstance(node, ast.ClassDef):
                    self.table[(module.name, name)] = ClassInfo(module, node)
        self.resolved = set()
        for key in list(self.table):
            self.resolve(key)

    def resolve(self, key):
        info = self.table[key]
        if key in self.resolved:
            return info
        self.resolved.add(key)
        bases = [symbol_of(info.module, base, self.modules) for base in info.node.bases]
        info.closed = all(base in self.table for base in bases) and all(dataclass_decorator(item) for item in info.node.decorator_list)
        for base in bases:
            if base in self.table:
                parent = self.resolve(base)
                info.closed = info.closed and parent.closed
                info.members |= parent.members
                info.fields.update(parent.fields)
                info.methods.update(parent.methods)
        for item in info.node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                info.members.add(item.target.id)
                info.fields[item.target.id] = item.annotation
            elif isinstance(item, ast.Assign):
                info.members.update(name for target in item.targets for name in target_names(target))
            elif isinstance(item, FUNCTIONS):
                info.members.add(item.name)
                info.methods[item.name] = item
                if item.args.args:
                    info.members.update(self_stores(item, item.args.args[0].arg))
            elif isinstance(item, ast.ClassDef):
                info.members.add(item.name)
        if {'__getattr__', '__getattribute__', '__slots__'} & info.members:
            info.closed = False
        return info

    def of(self, key):
        return self.table.get(key)


def self_stores(function, receiver):
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name) and node.value.id == receiver:
            names.add(node.attr)
    return names


def own_nodes(node):
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, SCOPES):
            yield from own_nodes(child)


class Inference:
    def __init__(self, modules, classes):
        self.modules = modules
        self.classes = classes
        self.returns = {}

    def class_of(self, module, expr):
        key = symbol_of(module, expr, self.modules)
        return key if key in self.classes.table else None

    def scope(self, module, function, owner, parent):
        bindings = {}
        arguments = function.args
        positional = arguments.posonlyargs + arguments.args
        method = owner is not None and not any(isinstance(item, ast.Name) and item.id in ('staticmethod', 'classmethod') for item in function.decorator_list)
        for index, argument in enumerate(positional + arguments.kwonlyargs + [item for item in (arguments.vararg, arguments.kwarg) if item]):
            if method and index == 0:
                bindings[argument.arg] = [owner]
            else:
                bindings[argument.arg] = [self.class_of(module, argument.annotation) if argument.annotation is not None else None]
        assigned = set()
        for node in own_nodes(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                bindings.setdefault(node.targets[0].id, []).append(node.value)
                assigned.add(id(node.targets[0]))
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and id(node) not in assigned:
                bindings.setdefault(node.id, []).append(None)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for name in node.names:
                    bindings.setdefault(name, []).append(None)
            elif isinstance(node, FUNCTIONS + (ast.ClassDef,)):
                bindings.setdefault(node.name, []).append(None)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bindings.setdefault(alias.asname or alias.name.split('.')[0], []).append(None)
        frame = Frame(module, bindings, parent)
        return frame

    def infer(self, frame, expr):
        if isinstance(expr, ast.Name):
            return frame.lookup(expr.id, self)
        if isinstance(expr, ast.IfExp):
            branch = self.infer(frame, expr.body)
            return branch if branch == self.infer(frame, expr.orelse) else None
        if isinstance(expr, ast.Call):
            key = self.class_of(frame.module, expr.func)
            if key:
                return key
            if isinstance(expr.func, ast.Attribute):
                owner = self.infer(frame, expr.func.value)
                info = self.classes.of(owner)
                if info and expr.func.attr in info.methods:
                    return self.returned(info.module, info.methods[expr.func.attr], owner)
                return None
            target = symbol_of(frame.module, expr.func, self.modules)
            if target:
                node = definitions(self.modules[target[0]]).get(target[1])
                if isinstance(node, FUNCTIONS):
                    return self.returned(self.modules[target[0]], node, None)
            return None
        if isinstance(expr, ast.Attribute):
            info = self.classes.of(self.infer(frame, expr.value))
            if info is None:
                return None
            if expr.attr in info.fields:
                return self.class_of(info.module, info.fields[expr.attr])
            method = info.methods.get(expr.attr)
            if method and any(isinstance(item, ast.Name) and item.id == 'property' for item in method.decorator_list):
                return self.returned(info.module, method, (info.module.name, info.node.name))
        return None

    def returned(self, module, function, owner):
        key = id(function)
        if key in self.returns:
            return self.returns[key]
        self.returns[key] = None
        frame = self.scope(module, function, owner, None)
        results = {self.infer(frame, node.value) if node.value is not None else None for node in own_nodes(function) if isinstance(node, ast.Return)}
        self.returns[key] = results.pop() if len(results) == 1 else None
        return self.returns[key]


class Frame:
    def __init__(self, module, bindings, parent):
        self.module = module
        self.bindings = bindings
        self.parent = parent
        self.cache = {}

    def lookup(self, name, inference):
        if name not in self.bindings:
            return self.parent.lookup(name, inference) if self.parent else None
        if name in self.cache:
            return self.cache[name]
        self.cache[name] = None
        kinds = set()
        for item in self.bindings[name]:
            kinds.add(inference.infer(self, item) if isinstance(item, ast.AST) else item)
        self.cache[name] = kinds.pop() if len(kinds) == 1 else None
        return self.cache[name]


def find_draw_integrity_violations(root, draw_files=DRAW_FILES):
    missing = [name for name in draw_files if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f'check_dead_code: draw file(s) missing: {", ".join(missing)}')
    modules = load_modules(root, SCANNED)
    classes = Classes(modules)
    inference = Inference(modules, classes)
    violations = []
    for name in draw_files:
        module = modules[module_name(root, root / name)]
        check_draw_scope(module, module.tree, None, None, inference, violations)
    return sorted(set(violations), key=lambda item: (item.split(':')[0], int(item.split(':')[1]), item))


def check_draw_scope(module, node, owner, frame, inference, violations):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, FUNCTIONS):
            check_draw_scope(module, child, None, inference.scope(module, child, owner, frame), inference, violations)
            continue
        if isinstance(child, ast.ClassDef):
            key = (module.name, child.name) if node is module.tree else None
            check_draw_scope(module, child, key, frame, inference, violations)
            continue
        if isinstance(child, ast.Attribute) and frame is not None:
            info = inference.classes.of(inference.infer(frame, child.value))
            if info is not None and info.closed and child.attr not in info.members | OBJECT_MEMBERS:
                violations.append(f"{module.relative}:{child.lineno}: invalid attribute '{child.attr}' on {info.node.name}")
        check_draw_scope(module, child, owner, frame, inference, violations)


def find_missing_imports(root):
    modules = load_modules(root)
    return missing_imports(modules, scanned_modules(modules))


def scanned_modules(modules):
    return [module for name, module in modules.items() if name.split('.')[0] in SCANNED]


def find_dead_code(root):
    modules = load_modules(root)
    scanned = scanned_modules(modules)
    violations = missing_imports(modules, scanned) + find_draw_integrity_violations(root)
    for module in scanned:
        violations += unused_imports(module)
    return violations + unused_definitions(modules, scanned)


def check_dead_code(root):
    violations = find_dead_code(root)
    if violations:
        raise ValueError('\n'.join(violations))
    return len(scanned_modules(load_modules(root)))


def check_source_rules(root):
    return check_repository(root), check_dead_code(root)


if __name__ == '__main__':
    files, modules = check_source_rules(Path(__file__).resolve().parents[1])
    print(f'Checked {files} Python files: zero comments or docstrings. Checked {modules} package and tools modules: zero dead code, unused imports, missing cross-module imports, or draw integrity violations detected.')
