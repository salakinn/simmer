#!/usr/bin/env python3
"""Portable Simmer supervisor with hourly GitHub updates (Linux, macOS, Windows)."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

from scripts.updater_common import UpdateLock, active_env, default_state_dir, python_in, service_control, write_json


class Supervisor:
    def __init__(self, root, state, config):
        self.root, self.state, self.config = root, state, config
        self.child = None
        self.updater = None
        self.running = True
        self.desired_active = not (state / 'recovery.json').exists()
        self.next_start = 0
        self.next_update = time.monotonic() + (30 if self.desired_active else 0)

    def start(self):
        if self.child is None or self.child.poll() is not None:
            self.child = subprocess.Popen(
                [str(python_in(active_env(self.state))), '-m', 'uvicorn', 'app.main:app',
                 '--host', '127.0.0.1', '--port', str(self.config['port'])], cwd=self.root)
        self.desired_active = True

    def stop(self):
        self.desired_active = False
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=10)
        self.child = None

    def serve(self):
        supervisor = self
        token = secrets.token_urlsafe(32)

        class Control(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != '/control' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError('Ungültige Anfrage')
                    action = json.loads(self.rfile.read(length))['action']
                    if action == 'start':
                        supervisor.start()
                    elif action == 'stop':
                        supervisor.stop()
                    elif action == 'shutdown':
                        supervisor.running = False
                    elif action != 'status':
                        raise ValueError('Unbekannte Aktion')
                    response = {'ok': True, 'active': supervisor.child is not None and supervisor.child.poll() is None}
                except Exception as exc:
                    response = {'ok': False, 'error': str(exc)}
                data = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Control)
        server.timeout = .25
        write_json(self.state / 'controller.json', {'port': server.server_port, 'token': token, 'pid': os.getpid()})

        def shutdown(*args):
            self.running = False

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            if self.desired_active:
                self.start()
            while self.running:
                server.handle_request()
                now = time.monotonic()
                if self.desired_active and self.child is not None and self.child.poll() is not None and now >= self.next_start:
                    print('Simmer wurde beendet; starte erneut.', flush=True)
                    self.start()
                    self.next_start = now + 5
                if now >= self.next_update and (self.updater is None or self.updater.poll() is not None):
                    print('Starte GitHub-Updateprüfung.', flush=True)
                    self.updater = subprocess.Popen(
                        [sys.executable, '-m', 'scripts.auto_update', '--root', str(self.root), '--state-dir', str(self.state)],
                        cwd=self.root)
                    self.next_update = now + self.config['interval_seconds']
        finally:
            # A deployment interrupted here is recovered on the next start.
            if self.updater is not None and self.updater.poll() is None:
                self.updater.terminate()
                try:
                    self.updater.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.updater.kill()
                    self.updater.wait(timeout=10)
            self.stop()
            server.server_close()
            (self.state / 'controller.json').unlink(missing_ok=True)


def initialize(root, state, port=None, interval=None):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_file = state / 'config.json'
    if config_file.exists():
        config = json.loads(config_file.read_text(encoding='utf-8'))
        if config['root'] != str(root):
            raise RuntimeError('Dieses Statusverzeichnis gehört zu einer anderen Simmer-Installation.')
    else:
        repository = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=root, text=True).strip()
        if not repository.startswith('https://github.com/'):
            raise RuntimeError('Für automatische Updates ist ein HTTPS-GitHub-Repository erforderlich.')
        config = {'root': str(root), 'repository_url': repository, 'port': 8001, 'interval_seconds': 3600}
    if port is not None:
        config['port'] = port
    if interval is not None:
        if interval < 60:
            raise ValueError('Das Prüfintervall muss mindestens 60 Sekunden betragen.')
        config['interval_seconds'] = interval
    config['health_url'] = f"http://127.0.0.1:{config['port']}/api/recipes"
    write_json(config_file, config)
    if not (state / 'active-env.json').exists():
        if not python_in(root / '.venv').exists():
            raise RuntimeError('Bitte zuerst die Python-Umgebung .venv einrichten.')
        write_json(state / 'active-env.json', {'path': str(root / '.venv')})
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--state-dir', type=Path, default=default_state_dir())
    parser.add_argument('--port', type=int)
    parser.add_argument('--interval', type=int, help='Prüfintervall in Sekunden (Standard: 3600)')
    parser.add_argument('--detach', action='store_true', help='Plattformunabhängig im Hintergrund starten')
    parser.add_argument('--stop', action='store_true', help='Hintergrundprozess beenden')
    args = parser.parse_args()
    os.umask(0o077)
    root, state = args.root.resolve(), args.state_dir.resolve()
    if args.stop:
        service_control(state, 'shutdown')
        return 0
    config = initialize(root, state, args.port, args.interval)
    if args.detach:
        try:
            if service_control(state, 'status')['ok']:
                print(f'Simmer läuft bereits auf http://127.0.0.1:{config["port"]}')
                return 0
        except (OSError, ValueError):
            pass
        with (state / 'service.log').open('a', encoding='utf-8') as log:
            options = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen([sys.executable, '-m', 'scripts.run_service', '--root', str(root), '--state-dir', str(state)],
                                       cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       close_fds=True, **options)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f'Start fehlgeschlagen; siehe {state / "service.log"}')
            try:
                if service_control(state, 'status')['active']:
                    print(f'Simmer läuft im Hintergrund: http://127.0.0.1:{config["port"]}')
                    return 0
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        raise RuntimeError('Zeitüberschreitung beim Start des Hintergrundprozesses.')
    try:
        with UpdateLock(state / 'supervisor.lock'):
            Supervisor(root, state, config).serve()
    except BlockingIOError:
        raise RuntimeError('Simmer läuft bereits.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
