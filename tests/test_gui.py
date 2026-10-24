import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nmp.client import ClientConfig
from nmp.client_controller import ClientState
from nmp.gui import NmpClientWindow


class FakeController:
    def __init__(self):
        self.state = ClientState.STOPPED
        self.stop_called = False

    def start(self, config):
        self.state = ClientState.STARTING

    def stop(self):
        self.stop_called = True
        self.state = ClientState.STOPPED

    def shutdown(self, wait=False):
        self.stop()
        return True

    def drain_events(self):
        return []


@pytest.fixture(scope='session')
def application():
    app = QApplication.instance() or QApplication(['nmp-gui-test'])
    app.setQuitOnLastWindowClosed(False)
    return app


def create_window(tmp_path, controller=None):
    return NmpClientWindow(
        config_path=tmp_path / 'client.toml',
        log_path=tmp_path / 'nmp-client.log',
        controller=controller or FakeController())


def dispose_window(window, application):
    window.poll_timer.stop()
    window.tray_icon.hide()
    window._close_log_handlers()
    window.deleteLater()
    application.processEvents()


def test_window_loads_config_and_updates_tray(tmp_path, application):
    config_path = tmp_path / 'client.toml'
    ClientConfig(
        endpoint='wss://nmp.example.com',
        token='secret',
        port=1080,
        pre_connect=True).save(config_path)

    window = create_window(tmp_path)
    try:
        assert window.endpoint_entry.text() == 'wss://nmp.example.com'
        assert window.token_entry.text() == 'secret'
        assert window.port_entry.value() == 1080
        assert window.pre_connect_check.isChecked()

        window._apply_state(ClientState.RUNNING)
        assert window.toggle_button.text() == '停止代理'
        assert window.tray_toggle_action.text() == '停止代理'
        assert window.tray_status_action.text() == '状态：运行中'
    finally:
        dispose_window(window, application)


def test_close_hides_window_when_tray_is_available(tmp_path, application):
    window = create_window(tmp_path)
    try:
        window.tray_available = True
        window.show()
        application.processEvents()
        window.close()
        application.processEvents()

        assert not window.isVisible()
        assert not window._quitting
    finally:
        dispose_window(window, application)


def test_macos_activation_restores_hidden_window(tmp_path, application,
                                                 monkeypatch):
    window = create_window(tmp_path)
    try:
        window.hide()
        monkeypatch.setattr('nmp.gui.sys.platform', 'darwin')
        window._application_state_changed(
            Qt.ApplicationState.ApplicationActive)
        application.processEvents()

        assert window.isVisible()
    finally:
        dispose_window(window, application)


def test_quit_stops_controller_and_cleans_up(tmp_path, application):
    controller = FakeController()
    window = create_window(tmp_path, controller)

    window.request_quit()
    application.processEvents()

    assert controller.stop_called
    assert window._handlers_closed
    assert not window.tray_icon.isVisible()


def test_system_quit_cleans_up_controller(tmp_path, application):
    controller = FakeController()
    window = create_window(tmp_path, controller)

    window._on_about_to_quit()

    assert controller.stop_called
    assert window._handlers_closed
    assert not window.tray_icon.isVisible()


def test_login_start_uses_saved_config_and_stays_hidden(tmp_path, application):
    config = ClientConfig(endpoint='wss://example.com', token='saved-token')
    config.save(tmp_path / 'client.toml')
    window = create_window(tmp_path)
    try:
        window.tray_available = True
        window.start_at_login()
        assert window.controller.state == ClientState.STARTING
        assert not window.isVisible()
        window._apply_state(ClientState.RUNNING)
        assert not window._autostart_pending
        assert not window.isVisible()
    finally:
        dispose_window(window, application)


def test_login_async_failure_shows_window(tmp_path, application):
    ClientConfig(endpoint='wss://example.com', token='secret').save(tmp_path / 'client.toml')
    window = create_window(tmp_path)
    try:
        window.tray_available = True
        window.start_at_login()
        window._apply_state(ClientState.ERROR, 'port in use')
        assert window.isVisible()
        assert not window._autostart_pending
    finally:
        dispose_window(window, application)


def test_invalid_login_config_is_preserved_and_shown(tmp_path, application, monkeypatch):
    path = tmp_path / 'client.toml'
    path.write_text('not valid TOML [')
    errors = []
    monkeypatch.setattr('nmp.gui.QMessageBox.critical', lambda *args: errors.append(args))
    window = create_window(tmp_path)
    try:
        window.start_at_login()
        assert window.isVisible()
        assert window.controller.state == ClientState.STOPPED
        assert errors
        assert path.read_text() == 'not valid TOML ['
    finally:
        dispose_window(window, application)


def test_startup_checkbox_saves_config_and_reverts_on_registry_error(tmp_path, application, monkeypatch):
    monkeypatch.setattr('nmp.gui.sys.platform', 'win32')
    monkeypatch.setattr('nmp.gui.sys.frozen', True, raising=False)
    monkeypatch.setattr('nmp.gui.windows_startup.is_enabled', lambda: False)
    changes = []
    monkeypatch.setattr('nmp.gui.windows_startup.set_enabled', lambda *args: changes.append(args))
    monkeypatch.setattr('nmp.gui.QMessageBox.critical', lambda *args: None)
    window = create_window(tmp_path)
    try:
        window.autostart_check.click()
        assert not changes  # Invalid connection settings must not register startup.
        assert not window.autostart_check.isChecked()
        window.endpoint_entry.setText('wss://example.com')
        window.token_entry.setText('secret')
        window.autostart_check.click()
        assert changes == [(True, window.config_path)]
        assert ClientConfig.from_toml(window.config_path).token == 'secret'

        def fail(*args):
            raise PermissionError('denied')
        monkeypatch.setattr('nmp.gui.windows_startup.set_enabled', fail)
        window.autostart_check.click()
        assert window.autostart_check.isChecked()
        assert not window.controller.stop_called
        monkeypatch.setattr('nmp.gui.windows_startup.set_enabled', lambda *args: changes.append(args))
        window.controller.state = ClientState.RUNNING
        window._apply_state(ClientState.RUNNING)
        window.autostart_check.click()
        assert changes[-1] == (False, window.config_path)
        assert not window.autostart_check.isChecked()
        assert not window.controller.stop_called
    finally:
        dispose_window(window, application)


def test_login_without_tray_remains_accessible(tmp_path, application):
    ClientConfig(endpoint='wss://example.com', token='secret').save(tmp_path / 'client.toml')
    window = create_window(tmp_path)
    try:
        window.tray_available = False
        window.start_at_login()
        assert window.isVisible()
    finally:
        dispose_window(window, application)
