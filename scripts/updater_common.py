import json
import os
from pathlib import Path
import urllib.request


def default_state_dir():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Simmer'
    return Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'simmer-updater'


def python_in(environment):
    return Path(environment) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def active_env(state):
    return Path(json.loads((Path(state) / 'active-env.json').read_text(encoding='utf-8'))['path'])


def service_control(state, action):
    controller = json.loads((Path(state) / 'controller.json').read_text(encoding='utf-8'))
    request = urllib.request.Request(
        f"http://127.0.0.1:{int(controller['port'])}/control",
        data=json.dumps({'action': action}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + controller['token']},
    )
    # Do not use system proxies for the private loopback control channel.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=40) as response:
        return json.load(response)


class UpdateLock:
    """OS locks are released automatically even if a process crashes."""
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.file = open(self.path, 'a+b')
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            if not self.file.read(1):
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.file.close()
                raise BlockingIOError('Ein Prozess läuft bereits.')
        else:
            import fcntl
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.file.close()
                raise BlockingIOError('Ein Prozess läuft bereits.')
        return self

    def __exit__(self, *args):
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()
