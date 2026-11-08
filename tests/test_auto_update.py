"""Real temporary Git repositories exercise update, conflict and rollback paths."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.auto_update import Updater, UpdateError
from scripts.updater_common import UpdateLock, active_env, python_in, write_json


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'user.name=Test', '-c', 'user.email=test@localhost',
                                    '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
                                   cwd=root, text=True, stderr=subprocess.STDOUT).strip()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    remote, publisher, root, state = [tmp_path / name for name in ('remote.git', 'publisher', 'installed', 'state')]
    git(tmp_path, 'init', '--bare', '--initial-branch=main', str(remote))
    git(tmp_path, 'clone', str(remote), str(publisher))
    (publisher / 'README.md').write_text('base\n')
    (publisher / '.gitignore').write_text('.venv/\ndata/*\n')
    (publisher / 'requirements.txt').write_text('')
    git(publisher, 'add', '.')
    git(publisher, 'commit', '-m', 'Base')
    git(publisher, 'push', 'origin', 'main')
    git(tmp_path, 'clone', str(remote), str(root))
    (root / 'local.txt').write_text('Keep local extensions\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'Local extensions')
    old_head = git(root, 'rev-parse', 'HEAD')
    state.mkdir()
    environment = root / '.venv'
    environment.mkdir()
    write_json(state / 'active-env.json', {'path': str(environment)})
    write_json(state / 'config.json', {'repository_url': str(remote), 'health_url': 'http://127.0.0.1:8001/api/recipes'})
    database = root / 'data/simmer.db'
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE recipes (title TEXT)')
        db.execute("INSERT INTO recipes VALUES ('Original recipe')")
    updater = Updater(root, state)
    monkeypatch.setattr(updater, 'database_path', lambda python: database)
    calls = []
    original_command = updater.command

    def command(args, **kwargs):
        if args[:3] == [sys.executable, '-m', 'venv']:
            python = python_in(Path(args[3]))
            python.parent.mkdir(parents=True)
            python.touch()
            calls.append('venv')
            return subprocess.CompletedProcess(args, 0, '')
        if 'pip' in args or 'pytest' in args:
            calls.append('pytest' if 'pytest' in args else 'pip')
            return subprocess.CompletedProcess(args, 0, '')
        return original_command(args, **kwargs)

    monkeypatch.setattr(updater, 'command', command)
    def service(action, check=True):
        calls.append(action)
        return {'ok': True, 'active': True}
    monkeypatch.setattr(updater, 'service', service)
    monkeypatch.setattr(updater, 'healthy', lambda: calls.append('healthy'))
    return updater, publisher, root, state, old_head, database, calls


def publish(publisher, name='new.txt', content='New upstream feature\n'):
    (publisher / name).write_text(content)
    git(publisher, 'add', '.')
    git(publisher, 'commit', '-m', 'Upstream update')
    git(publisher, 'push', 'origin', 'main')
    return git(publisher, 'rev-parse', 'HEAD')


def test_no_update_leaves_service_and_environment_untouched(installation):
    updater, _, root, state, old, _, calls = installation
    updater.update()
    assert git(root, 'rev-parse', 'HEAD') == old
    assert active_env(state) == root / '.venv'
    assert calls == []
    assert json.loads((state / 'status.json').read_text())['status'] == 'current'


def test_update_preserves_local_commits_and_deploys_tested_merge(installation):
    updater, publisher, root, state, _, _, calls = installation
    target = publish(publisher)
    updater.update()
    git(root, 'merge-base', '--is-ancestor', target, 'HEAD')
    assert (root / 'local.txt').read_text() == 'Keep local extensions\n'
    assert (root / 'new.txt').exists()
    assert git(root, 'status', '--porcelain') == ''
    assert active_env(state).parent == state / 'environments'
    assert calls.index('pytest') < calls.index('stop') < calls.index('start') < calls.index('healthy')
    assert list((state / 'backups').glob('*.db'))
    assert not (state / 'recovery.json').exists()
    assert json.loads((state / 'status.json').read_text())['status'] == 'updated'


def test_dirty_files_block_installation_without_losing_edits(installation):
    updater, publisher, root, state, old, _, calls = installation
    publish(publisher)
    (root / 'local.txt').write_text('Work in progress')
    updater.update()
    assert (root / 'local.txt').read_text() == 'Work in progress'
    assert git(root, 'rev-parse', 'HEAD') == old
    assert calls == []
    assert json.loads((state / 'status.json').read_text())['status'] == 'blocked'


def test_merge_conflict_does_not_change_running_installation(installation):
    updater, publisher, root, state, _, _, calls = installation
    (root / 'README.md').write_text('Local content\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'Conflicting local change')
    old = git(root, 'rev-parse', 'HEAD')
    publish(publisher, 'README.md', 'Different upstream content\n')
    with pytest.raises(UpdateError):
        updater.update()
    assert git(root, 'rev-parse', 'HEAD') == old
    assert (root / 'README.md').read_text() == 'Local content\n'
    assert not list((state / 'candidates').iterdir())
    assert calls == []


def test_failed_validation_never_stops_live_service(installation, monkeypatch):
    updater, publisher, root, state, old, _, calls = installation
    publish(publisher)
    original = updater.command
    def fail_tests(args, **kwargs):
        if 'pytest' in args:
            raise UpdateError('Tests failed')
        return original(args, **kwargs)
    monkeypatch.setattr(updater, 'command', fail_tests)
    with pytest.raises(UpdateError, match='Tests failed'):
        updater.update()
    assert git(root, 'rev-parse', 'HEAD') == old
    assert 'stop' not in calls
    assert not list((state / 'environments').iterdir())


def test_failed_restart_restores_code_database_and_environment(installation, monkeypatch):
    updater, publisher, root, state, old, database, calls = installation
    publish(publisher)
    checks = []
    def unhealthy_once():
        checks.append(True)
        if len(checks) == 1:
            with sqlite3.connect(database) as db:
                db.execute("UPDATE recipes SET title='Changed by new version'")
            raise UpdateError('Health check failed')
    monkeypatch.setattr(updater, 'healthy', unhealthy_once)
    with pytest.raises(UpdateError, match='Health check failed'):
        updater.update()
    assert git(root, 'rev-parse', 'HEAD') == old
    assert active_env(state) == root / '.venv'
    assert not (root / 'new.txt').exists()
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT title FROM recipes').fetchone()[0] == 'Original recipe'
    assert len(checks) == 2
    assert not (state / 'recovery.json').exists()
    assert json.loads((state / 'status.json').read_text())['status'] == 'rolled_back'


def test_check_only_does_not_install(installation):
    updater, publisher, root, state, old, _, calls = installation
    publish(publisher)
    updater.update(check_only=True)
    assert git(root, 'rev-parse', 'HEAD') == old
    assert calls == []
    assert json.loads((state / 'status.json').read_text())['status'] == 'available'


def test_process_lock_prevents_parallel_updates(tmp_path):
    path = tmp_path / 'lock'
    with UpdateLock(path):
        with pytest.raises(BlockingIOError):
            with UpdateLock(path):
                pass
    with UpdateLock(path):
        pass
