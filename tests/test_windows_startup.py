import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from nmp import windows_startup as startup


@pytest.fixture
def registry(monkeypatch):
    values = {}

    def query(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    def delete(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        del values[name]

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_SZ=1,
        OpenKey=lambda *args: nullcontext('key'),
        CreateKeyEx=lambda *args: nullcontext('key'),
        QueryValueEx=query, DeleteValue=delete,
        SetValueEx=lambda key, name, reserved, kind, value: values.__setitem__(name, value))
    monkeypatch.setitem(sys.modules, 'winreg', fake)
    return values


def test_startup_roundtrip_quotes_paths_without_credentials(tmp_path, monkeypatch, registry):
    executable = Path(tmp_path.anchor) / 'NMP Client' / 'NMP.exe'
    config = tmp_path / 'User Data' / 'client.toml'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(executable))
    assert not startup.is_enabled()
    startup.set_enabled(True, config)
    assert startup.is_enabled()
    assert registry['NMP'] == subprocess.list2cmdline([
        str(executable.resolve()), '--autostart', '--config', str(config.resolve())])
    startup.set_enabled(False, config)
    startup.set_enabled(False, config)
    assert not startup.is_enabled()


def test_source_launch_cannot_register_startup(tmp_path, monkeypatch, registry):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    with pytest.raises(RuntimeError):
        startup.set_enabled(True, tmp_path / 'client.toml')
    assert not registry


def test_overlong_command_does_not_replace_existing_entry(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    registry['NMP'] = 'existing command'
    with pytest.raises(ValueError):
        startup.set_enabled(True, tmp_path / ('a' * 270) / 'client.toml')
    assert registry['NMP'] == 'existing command'
