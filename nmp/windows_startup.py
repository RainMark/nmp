"""Current-user Windows login startup; credentials stay in client.toml."""

import subprocess
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'NMP'


def is_enabled():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def startup_command(config_path):
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('请使用已打包的 NMP 客户端设置登录自启动')
    command = subprocess.list2cmdline([
        str(Path(sys.executable).resolve()), '--autostart',
        '--config', str(Path(config_path).resolve())])
    if len(command) > 260:
        raise ValueError('启动路径过长，请将 NMP 和配置放到较短的路径')
    return command


def set_enabled(enabled, config_path):
    import winreg

    command = startup_command(config_path) if enabled else None
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
