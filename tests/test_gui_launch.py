"""Exercise real process startup, listener binding and stale instance locks."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import pytest

from nmp.client import ClientConfig


def wait_for_port(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        assert process.poll() is None, 'GUI exited before binding its proxy'
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2) as sock:
                sock.sendall(b'\x05\x01\x00')
                assert sock.recv(2) == b'\x05\x00'
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError('proxy did not start')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows-only login startup')
def test_login_launch_duplicate_and_stale_lock(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = tmp_path / 'client.toml'
    ClientConfig(endpoint='ws://127.0.0.1:1', token='test-token', port=port).save(config)
    command = [sys.executable, str(Path(__file__).parents[1] / 'nmp_client_gui.py'),
               '--config', str(config), '--autostart']
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', LOCALAPPDATA=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path))
    for attempt in range(2):
        process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        try:
            wait_for_port(process, port)
            duplicate = subprocess.run(command, env=env, capture_output=True, timeout=15)
            assert duplicate.returncode == 1
            wait_for_port(process, port)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
