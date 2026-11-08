#!/usr/bin/env python3
"""Test GitHub updates in isolation, then deploy with a recoverable rollback."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from scripts.updater_common import UpdateLock, active_env, default_state_dir, python_in, service_control, write_json


class UpdateError(RuntimeError):
    pass


class Updater:
    def __init__(self, root, state):
        self.root = Path(root).resolve()
        self.state = Path(state).resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.state / 'empty-hooks').mkdir(exist_ok=True)
        self.config = json.loads((self.state / 'config.json').read_text(encoding='utf-8'))

    def command(self, args, cwd=None, check=True, timeout=120, env=None):
        result = subprocess.run(args, cwd=cwd or self.root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                timeout=timeout, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', **(env or {})})
        if result.stdout.strip():
            print(result.stdout.strip(), flush=True)
        if check and result.returncode:
            raise UpdateError(f'Befehl fehlgeschlagen ({result.returncode}): {args[0]}')
        return result

    def git(self, *args, cwd=None, check=True):
        return self.command(['git', '-c', 'core.hooksPath=' + str(self.state / 'empty-hooks'),
                             '-c', 'commit.gpgsign=false', '-c', 'user.name=Simmer Updater',
                             '-c', 'user.email=simmer-updater@localhost', *args],
                            cwd=cwd, check=check).stdout.strip()

    def status(self, status, detail, **extra):
        record = {'status': status, 'detail': detail,
                  'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **extra}
        write_json(self.state / 'status.json', record)
        print(f'{status}: {detail}', flush=True)

    def switch_env(self, target):
        write_json(self.state / 'active-env.json', {'path': str(target)})

    def service(self, action, check=True):
        result = service_control(self.state, 'status' if action == 'is-active' else action)
        if not result.get('ok') and check:
            raise UpdateError(result.get('error', 'Simmer konnte nicht gesteuert werden.'))
        return result

    def healthy(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(self.config['health_url'], timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise UpdateError('Simmer ist nach dem Neustart nicht erreichbar.')

    def database_path(self, python):
        result = self.command([str(python), '-c',
                               'from app.config import settings; import json; print(json.dumps(settings.database_url))'])
        url = json.loads(result.stdout)
        if not url.startswith('sqlite:///') or url == 'sqlite:///:memory:':
            raise UpdateError('Automatische Datenbanksicherung erfordert eine SQLite-Datei.')
        path = Path(url.removeprefix('sqlite:///'))
        return (self.root / path).resolve() if not path.is_absolute() else path

    def rollback(self, recovery):
        self.service('stop')
        self.git('reset', '--merge', recovery['old_head'])
        self.switch_env(recovery['old_env'])
        if recovery.get('backup'):
            database = Path(recovery['database'])
            with sqlite3.connect(recovery['backup']) as source, sqlite3.connect(database) as destination:
                source.backup(destination)
        if recovery['was_active']:
            self.service('start')
            self.healthy()
        (self.state / 'recovery.json').unlink()
        self.status('rolled_back', 'Vorherige Version und Datenbank wiederhergestellt.', commit=recovery['old_head'])

    def deploy(self, candidate, new_env, old_head):
        if self.git('status', '--porcelain') or self.git('rev-parse', 'HEAD') != old_head:
            raise UpdateError('Der Arbeitsstand wurde während der Prüfung verändert; Update abgebrochen.')
        old_env = active_env(self.state)
        database = self.database_path(python_in(old_env))
        was_active = self.service('is-active')['active']
        recovery = None
        try:
            self.service('stop')
            backup = None
            if database.exists():
                backups = self.state / 'backups'
                backups.mkdir(exist_ok=True, mode=0o700)
                backup = backups / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.db')
                with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
                    source.backup(destination)
            recovery = {'old_head': old_head, 'old_env': str(old_env),
                        'database': str(database), 'backup': str(backup) if backup else None,
                        'was_active': was_active}
            write_json(self.state / 'recovery.json', recovery)
            self.git('merge', '--ff-only', self.git('rev-parse', 'HEAD', cwd=candidate))
            self.switch_env(new_env)
            if was_active:
                self.service('start')
                self.healthy()
            (self.state / 'recovery.json').unlink()
            self.status('updated', 'Neue Version installiert und geprüft.', commit=self.git('rev-parse', 'HEAD'))
        except Exception:
            if recovery is not None:
                self.rollback(recovery)
            elif was_active:
                self.service('start')
            raise

    def update(self, check_only=False):
        recovery_file = self.state / 'recovery.json'
        if recovery_file.exists():
            self.rollback(json.loads(recovery_file.read_text(encoding='utf-8')))
            return
        self.status('checking', 'Prüfe GitHub auf neue Änderungen.')
        if self.git('remote', 'get-url', 'origin') != self.config['repository_url']:
            raise UpdateError('Das GitHub-Repository wurde verändert; Konfiguration prüfen.')
        self.git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
        target = self.git('rev-parse', 'origin/main')
        old_head = self.git('rev-parse', 'HEAD')
        ancestor = self.command(['git', 'merge-base', '--is-ancestor', target, old_head], check=False)
        if ancestor.returncode == 0:
            self.status('current', 'Keine neue GitHub-Version verfügbar.', commit=old_head, upstream=target)
            return
        if ancestor.returncode != 1:
            raise UpdateError('Die Git-Historie konnte nicht geprüft werden.')
        if check_only:
            self.status('available', 'Eine neue GitHub-Version ist verfügbar.', upstream=target)
            return
        if self.git('status', '--porcelain'):
            self.status('blocked', 'Nicht gespeicherte Codeänderungen: Update bis zum nächsten sauberen Git-Stand ausgesetzt.')
            return
        self.git('merge-base', old_head, target)
        self.status('preparing', 'Führe Änderungen zusammen und teste die neue Version.', upstream=target)
        identifier = uuid.uuid4().hex
        candidate = self.state / 'candidates' / identifier
        new_env = self.state / 'environments' / identifier
        candidate.parent.mkdir(exist_ok=True)
        new_env.parent.mkdir(exist_ok=True)
        self.git('worktree', 'add', '--detach', str(candidate), old_head)
        try:
            self.git('merge', '--no-edit', target, cwd=candidate)
            self.command([sys.executable, '-m', 'venv', str(new_env)], timeout=120)
            python = python_in(new_env)
            self.command([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                          '-r', 'requirements.txt'], cwd=candidate, timeout=600)
            self.command([str(python), '-m', 'pip', 'check'], cwd=candidate)
            test_env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(candidate / 'data/validation.db'),
                        'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_ALLOWED_USER_IDS': ''}
            self.command([str(python), '-m', 'pytest', '-q'], cwd=candidate, timeout=600, env=test_env)
            self.status('installing', 'Prüfungen erfolgreich; sichere Datenbank und starte Simmer neu.')
            self.deploy(candidate, new_env, old_head)
        finally:
            self.git('worktree', 'remove', '--force', str(candidate))
            active = active_env(self.state)
            # Keep an environment referenced by an interrupted deployment for recovery.
            if new_env != active and not (self.state / 'recovery.json').exists():
                shutil.rmtree(new_env, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--state-dir', type=Path, default=default_state_dir())
    parser.add_argument('--check', action='store_true', help='Nur prüfen, keine Installation')
    args = parser.parse_args()
    os.umask(0o077)
    updater = Updater(args.root, args.state_dir)
    try:
        with UpdateLock(updater.state / 'update.lock'):
            try:
                updater.update(args.check)
                return 0
            except Exception as exc:
                if (updater.state / 'recovery.json').exists():
                    updater.status('recovery_required', str(exc))
                elif not (updater.state / 'status.json').exists() or json.loads((updater.state / 'status.json').read_text(encoding='utf-8')).get('status') != 'rolled_back':
                    updater.status('error', str(exc))
                print(f'Update abgebrochen: {exc}', file=sys.stderr, flush=True)
                return 1
    except BlockingIOError:
        print('Ein Update läuft bereits.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
