import argparse
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from pywinauto import Desktop
from pywinauto.keyboard import send_keys


def wait_until(description, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as error:  # noqa: BLE001 - UIA can fail transiently.
            last_error = error
        time.sleep(0.2)
    detail = f': {last_error}' if last_error is not None else ''
    raise AssertionError(f'timed out waiting for {description}{detail}')


def port_is_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


def button(window, title):
    return window.child_window(title=title, control_type='Button')


def window_is_visible(window):
    try:
        return window.exists(timeout=0.2) and window.is_visible()
    except Exception:  # noqa: BLE001 - A hidden Qt window leaves the UIA tree.
        return False


def desktop_elements(desktop):
    for window in desktop.windows():
        yield window
        try:
            yield from window.descendants()
        except Exception:  # noqa: BLE001,S112 - Ignore stale UIA trees.
            continue


def find_tray_icon(desktop, application_pid):
    for element in desktop_elements(desktop):
        try:
            if (element.element_info.process_id != application_pid and
                    element.window_text().startswith('NMP Client') and
                    element.is_visible()):
                return element
        except Exception:  # noqa: BLE001,S112 - Ignore stale UIA elements.
            continue
    return None


def find_visible_element(desktop, title, process_id):
    for element in desktop_elements(desktop):
        try:
            if (element.element_info.process_id == process_id and
                    element.window_text() == title and element.is_visible()):
                return element
        except Exception:  # noqa: BLE001,S112 - Ignore stale UIA elements.
            continue
    return None


def open_tray_overflow(desktop):
    titles = {'Show hidden icons', 'Notification Chevron'}
    for element in desktop_elements(desktop):
        try:
            if (element.window_text() in titles and element.is_visible()):
                element.click_input()
                return
        except Exception:  # noqa: BLE001,S112 - Ignore stale UIA elements.
            continue
    raise AssertionError('Windows notification-area overflow button was not found')


def write_diagnostics(path, desktop):
    lines = []
    for element in desktop_elements(desktop):
        try:
            title = element.window_text()
            if title:
                lines.append(
                    f'{element.element_info.control_type}\t'
                    f'{element.element_info.process_id}\t{title}')
        except Exception:  # noqa: BLE001,S112 - Diagnostics are best effort.
            continue
    path.write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument(
        '--artifacts-dir', type=Path,
        default=Path('artifacts/windows-gui'))
    args = parser.parse_args()

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    desktop = Desktop(backend='uia')

    with tempfile.TemporaryDirectory(prefix='nmp-gui-ci-') as directory:
        directory = Path(directory)
        config_path = directory / 'client.toml'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            proxy_port = sock.getsockname()[1]
        config_path.write_text(
            '[client]\n'
            'endpoint = "ws://127.0.0.1:1"\n'
            'token = "ci-test-token"\n'
            f'port = {proxy_port}\n'
            'pre_connect = false\n',
            encoding='utf-8')

        process = subprocess.Popen([
            str(args.executable.resolve()), '--config', str(config_path)
        ])
        try:
            # A one-file PyInstaller executable uses a parent bootloader
            # process, so the Qt window belongs to its child process.
            window = desktop.window(title='NMP Client')
            window.wait('visible enabled', timeout=30)
            application_pid = window.wrapper_object().element_info.process_id
            window.set_focus()

            save_button = button(window, '保存配置')
            save_button.wait('visible enabled ready', timeout=15)
            config_path.unlink()
            save_button.click_input()
            wait_until('configuration file to be saved', config_path.exists)

            start_button = button(window, '启动代理')
            start_button.wait('visible enabled ready', timeout=15)
            start_button.click_input()
            wait_until('SOCKS5 listener to open', lambda: port_is_open(proxy_port))
            wait_until(
                'running GUI state',
                lambda: button(window, '停止代理').exists(timeout=0.2))

            button(window, '停止代理').click_input()
            wait_until(
                'stopped GUI state',
                lambda: button(window, '启动代理').exists(timeout=0.2))
            wait_until('SOCKS5 listener to close', lambda: not port_is_open(proxy_port))

            window.set_focus()
            send_keys('%{F4}')
            wait_until('main window to hide',
                       lambda: not window_is_visible(window))
            if process.poll() is not None:
                raise AssertionError('closing the window exited instead of hiding to tray')

            tray_icon = find_tray_icon(desktop, application_pid)
            if tray_icon is None:
                open_tray_overflow(desktop)
                wait_until(
                    'NMP notification-area icon',
                    lambda: find_tray_icon(desktop, application_pid) is not None)
                tray_icon = find_tray_icon(desktop, application_pid)
            tray_icon.double_click_input()
            wait_until('main window to return from tray',
                       lambda: window_is_visible(window))

            tray_icon = find_tray_icon(desktop, application_pid)
            tray_icon.right_click_input()
            wait_until(
                'tray quit menu item',
                lambda: find_visible_element(
                    desktop, '退出 NMP', application_pid) is not None)
            find_visible_element(
                desktop, '退出 NMP', application_pid).click_input()
            wait_until('application to quit from tray menu',
                       lambda: process.poll() is not None)

            args.artifacts_dir.joinpath('result.txt').write_text(
                'Windows packaged GUI launch, buttons, proxy lifecycle, close-to-tray, '
                'tray restore, and tray quit passed.\n',
                encoding='utf-8')
        except Exception:
            write_diagnostics(args.artifacts_dir / 'uia-elements.txt', desktop)
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    print(args.artifacts_dir.joinpath('result.txt').read_text(encoding='utf-8').strip())


if __name__ == '__main__':
    main()
