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
