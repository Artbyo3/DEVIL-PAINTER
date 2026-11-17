import os
import shlex
import subprocess
import sys
from pathlib import Path
from .library import save_settings, settings

FILES_TOKEN = '{files}'
FOLDER_TOKEN = '{folder}'


def command():
    return settings().get('bridge_command', '')


def set_command(text):
    settings()['bridge_command'] = text.strip()
    save_settings()


def arguments(template, files, folder):
    parts = [part.strip('"') for part in shlex.split(template, posix=os.name != 'nt')]
    result = []
    for part in parts:
        if part == FILES_TOKEN:
            result += [str(path) for path in files]
        else:
            result.append(part.replace(FOLDER_TOKEN, str(folder)))
    return result


def send(files, folder):
    template = command()
    if not template:
        return 'Type the command of the app to send to first, for example "C:/Apps/Viewer.exe" {files}.'
    args = arguments(template, files, folder)
    try:
        subprocess.Popen(args, cwd=str(folder))
    except OSError as error:
        return f'Could not start {Path(args[0]).name}: {error.strerror or error}.'
    return f'Sent {len(files)} textures to {Path(args[0]).stem}.'


def open_folder(folder):
    if sys.platform == 'win32':
        os.startfile(str(folder))
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)])
    return f'Opened {folder}.'
