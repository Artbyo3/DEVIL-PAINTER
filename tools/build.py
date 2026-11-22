from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
from tools.install_card import VERSION_PLACEHOLDER, VERSIONED_DOCS
from tools.workspace import extension_archive, read_manifest
from tools.check_dead_code import check_source_rules


PACKAGE = 'devil_painter'
ROOT_FILES = ('README.md', 'LICENSE', 'SPEC.md')


def glob_expression(pattern):
    parts = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if pattern.startswith('**', index):
            parts.append('.*')
            index += 2
            continue
        if character == '*':
            parts.append('[^/]*')
        elif character == '?':
            parts.append('[^/]')
        elif character == '[' and ']' in pattern[index + 1:]:
            end = pattern.index(']', index + 1)
            parts.append(pattern[index:end + 1])
            index = end
        else:
            parts.append(re.escape(character))
        index += 1
    return ''.join(parts)


def exclude_rule(pattern):
    keep = pattern.startswith('!')
    body = pattern[1:] if keep else pattern
    directory_only = body.endswith('/')
    body = body.rstrip('/')
    anchored = '/' in body
    expression = glob_expression(body.lstrip('/'))
    return keep, directory_only, re.compile(expression if anchored else f'(?:.*/)?{expression}')


def exclude_rules():
    manifest = read_manifest(root)
    return [exclude_rule(pattern) for pattern in manifest['build']['paths_exclude_pattern']]


def excluded(parts, rules):
    for depth in range(1, len(parts) + 1):
        path = '/'.join(parts[:depth])
        is_directory = depth < len(parts)
        verdict = False
        for keep, directory_only, expression in rules:
            if (is_directory or not directory_only) and expression.fullmatch(path):
                verdict = not keep
        if verdict:
            return True
    return False


def tracked_files():
    listing = subprocess.run(['git', 'ls-files', '-z', '--cached', '--', PACKAGE], cwd=root, capture_output=True, check=True).stdout
    return sorted(name for name in listing.decode('utf-8').split('\0') if name and (root / name).is_file())


def package_files():
    rules = exclude_rules()
    files = []
    for name in tracked_files():
        relative = PurePosixPath(name).relative_to(PACKAGE)
        if not excluded(relative.parts, rules):
            files.append((root / name, relative.as_posix()))
    return files + [(root / name, name) for name in ROOT_FILES]


def build_extension(scanned):
    if not scanned:
        check_source_rules(root)
    output = extension_archive()
    output.parent.mkdir(exist_ok=True)
    version = read_manifest(root)['version']
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for source, name in package_files():
            if name in VERSIONED_DOCS:
                text = source.read_text(encoding='utf-8').replace(VERSION_PLACEHOLDER, version)
                archive.writestr(name, text.encode('utf-8'))
            else:
                archive.write(source, name)
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Package the tracked add-on files into the installable extension zip')
    parser.add_argument('--scanned', action='store_true', help='Skip the comment and dead-code scans because the calling gate already ran them on this tree')
    build_extension(parser.parse_args().scanned)
