import argparse
import logging
import os
import queue
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from nmp.client import ClientConfig, default_config_path
from nmp.client_controller import ClientController, ClientState
from nmp.log import TokenFilter, fmt, get_logger

logger = get_logger(__name__)


def default_log_path():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'NMP' / 'logs' / 'nmp-client.log'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Logs' / 'NMP' / 'nmp-client.log'
    return default_config_path().parent / 'logs' / 'nmp-client.log'


def create_app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#2563eb'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(36)
    painter.setFont(font)
    painter.setPen(QColor('#ffffff'))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'N')
    painter.end()
    return QIcon(pixmap)


class QueueLogHandler(logging.Handler):
    def __init__(self, target_queue):
        super().__init__()
        self.target_queue = target_queue

    def emit(self, record):
        try:
            self.target_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class NmpClientWindow(QMainWindow):
    POLL_INTERVAL_MS = 100
    MAX_LOG_LINES = 1000

    def __init__(self, config_path=None, log_path=None, controller=None):
        super().__init__()
        self.config_path = (Path(config_path) if config_path is not None
                            else default_config_path())
        self.log_path = (Path(log_path) if log_path is not None
                         else default_log_path())
        self.controller = controller or ClientController()
        self.log_queue = queue.SimpleQueue()
        self.token_filter = TokenFilter()
        self._quitting = False
        self._quit_deadline = None
        self._handlers_closed = False

        self._configure_logging()
        self._configure_window()
        self._build_widgets()
        self._build_tray()
        self._load_config()
        self._apply_state(ClientState.STOPPED)
        QApplication.instance().applicationStateChanged.connect(
            self._application_state_changed)
        QApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start()

    def _configure_logging(self):
        self.log_handler = QueueLogHandler(self.log_queue)
        self.log_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_handler = RotatingFileHandler(
            self.log_path, maxBytes=2 * 1024 * 1024,
            backupCount=3, encoding='utf-8')
        self.file_handler.setFormatter(logging.Formatter(fmt))
        for handler in (self.log_handler, self.file_handler):
            handler.addFilter(self.token_filter)
            logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _configure_window(self):
        self.app_icon = create_app_icon()
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle('NMP Client')
        self.resize(760, 580)
        self.setMinimumSize(640, 500)

        quit_action = QAction('退出 NMP', self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_action.triggered.connect(self.request_quit)
        self.addAction(quit_action)

    def _build_widgets(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel('NMP Client')
        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()
        self.status_label = QLabel('● 已停止')
        header.addWidget(self.status_label)
        layout.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.endpoint_entry = QLineEdit()
        self.endpoint_entry.setPlaceholderText('wss://nmp.example.io')
        form.addRow('服务地址', self.endpoint_entry)

        self.token_entry = QLineEdit()
        self.token_entry.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Token', self.token_entry)

        local_proxy = QWidget()
        local_layout = QHBoxLayout(local_proxy)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(6)
        local_layout.addWidget(QLabel('127.0.0.1 :'))
        self.port_entry = QSpinBox()
        self.port_entry.setRange(1, 65535)
        self.port_entry.setValue(1234)
        self.port_entry.setMaximumWidth(110)
        local_layout.addWidget(self.port_entry)
        local_layout.addStretch()
        form.addRow('本地代理', local_proxy)

        self.pre_connect_check = QCheckBox('启用预连接')
        form.addRow('', self.pre_connect_check)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.save_button = QPushButton('保存配置')
        self.save_button.clicked.connect(self.save_config)
        actions.addWidget(self.save_button)
        self.toggle_button = QPushButton('启动代理')
        self.toggle_button.clicked.connect(self.toggle_proxy)
        actions.addWidget(self.toggle_button)
        actions.addStretch()
        actions.addWidget(QLabel('SOCKS5 地址：'))
        self.proxy_label = QLabel('127.0.0.1:1234')
        actions.addWidget(self.proxy_label)
        copy_button = QPushButton('复制')
        copy_button.clicked.connect(self.copy_proxy)
        actions.addWidget(copy_button)
        layout.addLayout(actions)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel('运行日志'))
        log_header.addStretch()
        clear_button = QPushButton('清空')
        clear_button.clicked.connect(self.clear_logs)
        log_header.addWidget(clear_button)
        open_logs_button = QPushButton('打开日志目录')
        open_logs_button.clicked.connect(self.open_logs)
        log_header.addWidget(open_logs_button)
        layout.addLayout(log_header)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_text.setFont(QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont))
        self.log_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log_text, 1)

        self._editable_widgets = (
            self.endpoint_entry,
            self.token_entry,
            self.port_entry,
            self.pre_connect_check,
        )

    def _build_tray(self):
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray_menu = QMenu(self)

        show_action = self.tray_menu.addAction('显示主窗口')
        show_action.triggered.connect(self.show_window)
        self.tray_status_action = self.tray_menu.addAction('状态：已停止')
        self.tray_status_action.setEnabled(False)
        self.tray_toggle_action = self.tray_menu.addAction('启动代理')
        self.tray_toggle_action.triggered.connect(self._toggle_from_tray)
        self.tray_menu.addSeparator()
        quit_action = self.tray_menu.addAction('退出 NMP')
        quit_action.triggered.connect(self.request_quit)

        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip('NMP Client — 已停止')
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()
        if not self.tray_available:
            logger.warning('system tray is unavailable; closing the window will exit')

    def _load_config(self):
        if not self.config_path.exists():
            logger.info(f'config file will be created at {self.config_path}')
            return
        try:
            config = ClientConfig.from_toml(self.config_path)
            self.endpoint_entry.setText(config.endpoint)
            self.token_entry.setText(config.token)
            self.token_filter.set_token(config.token)
            self.port_entry.setValue(config.port)
            self.pre_connect_check.setChecked(config.pre_connect)
            self._update_proxy_address()
            logger.info(f'loaded config from {self.config_path}')
        except Exception:
            logger.exception(f'failed to load config from {self.config_path}')

    def _config_from_form(self):
        config = ClientConfig(
            endpoint=self.endpoint_entry.text().strip(),
            token=self.token_entry.text(),
            port=self.port_entry.value(),
            pre_connect=self.pre_connect_check.isChecked())
        config.validate()
        return config

    def save_config(self):
        try:
            config = self._config_from_form()
            self.token_filter.set_token(config.token)
            config.save(self.config_path)
            self._update_proxy_address()
            logger.info(f'saved config to {self.config_path}')
            return config
        except Exception as error:
            QMessageBox.critical(self, '配置错误', str(error))
            return None

    def toggle_proxy(self):
        if self.controller.state in (ClientState.STOPPED, ClientState.ERROR):
            config = self.save_config()
            if config is not None:
                try:
                    self.controller.start(config)
                except Exception as error:
                    QMessageBox.critical(self, '启动失败', str(error))
        elif self.controller.state in (ClientState.STARTING,
                                       ClientState.RUNNING):
            self.controller.stop()

    def _toggle_from_tray(self):
        if self.controller.state in (ClientState.STOPPED, ClientState.ERROR):
            self.show_window()
        self.toggle_proxy()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def copy_proxy(self):
        QApplication.clipboard().setText(self.proxy_label.text())

    def clear_logs(self):
        self.log_text.clear()

    def open_logs(self):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.log_path.parent))):
                raise RuntimeError('系统没有可用的文件管理器')
        except Exception as error:
            QMessageBox.critical(self, '无法打开日志目录', str(error))

    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _application_state_changed(self, state):
        if (sys.platform == 'darwin' and
                state == Qt.ApplicationState.ApplicationActive and
                not self.isVisible() and not self._quitting):
            QTimer.singleShot(0, self.show_window)

    def request_quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._quit_deadline = time.monotonic() + 10
        self.hide()
        self.controller.stop()
        self._finish_quit_when_stopped()

    def _on_about_to_quit(self):
        if not self._quitting:
            self._quitting = True
            self.controller.shutdown(wait=True)
        self.tray_icon.hide()
        self._close_log_handlers()

    def _finish_quit_when_stopped(self):
        if not self._quitting:
            return
        if (self.controller.shutdown(wait=False) or
                time.monotonic() >= self._quit_deadline):
            self.poll_timer.stop()
            self.tray_icon.hide()
            self._close_log_handlers()
            QApplication.instance().quit()

    def _close_log_handlers(self):
        if self._handlers_closed:
            return
        self._handlers_closed = True
        for handler in (self.log_handler, self.file_handler):
            logging.getLogger().removeHandler(handler)
            handler.close()

    def closeEvent(self, event: QCloseEvent):
        if self._quitting:
            event.accept()
        elif self.tray_available:
            self.hide()
            event.ignore()
        else:
            self.request_quit()
            event.ignore()

    def _poll(self):
        for event in self.controller.drain_events():
            self._apply_state(event.state, event.message)
        self._drain_logs()
        if self._quitting:
            self._finish_quit_when_stopped()

    def _drain_logs(self):
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.log_text.appendPlainText('\n'.join(lines))
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _apply_state(self, state, message=''):
        labels = {
            ClientState.STOPPED: ('● 已停止', '已停止', '#64748b'),
            ClientState.STARTING: ('● 启动中', '启动中', '#b45309'),
            ClientState.RUNNING: ('● 运行中', '运行中', '#15803d'),
            ClientState.STOPPING: ('● 停止中', '停止中', '#b45309'),
            ClientState.ERROR: ('● 错误', '错误', '#b91c1c'),
        }
        label, short_label, color = labels[state]
        self.status_label.setText(label)
        self.status_label.setStyleSheet(f'color: {color}; font-weight: 600;')

        busy = state in (ClientState.STARTING,
                         ClientState.RUNNING,
                         ClientState.STOPPING)
        for widget in self._editable_widgets:
            widget.setEnabled(not busy)
        self.save_button.setEnabled(not busy)

        if state == ClientState.RUNNING:
            self.toggle_button.setText('停止代理')
            self.toggle_button.setEnabled(True)
            self.tray_toggle_action.setText('停止代理')
            self.tray_toggle_action.setEnabled(True)
        elif state in (ClientState.STARTING, ClientState.STOPPING):
            self.toggle_button.setText('正在处理…')
            self.toggle_button.setEnabled(False)
            self.tray_toggle_action.setText('正在处理…')
            self.tray_toggle_action.setEnabled(False)
        else:
            self.toggle_button.setText('启动代理')
            self.toggle_button.setEnabled(True)
            self.tray_toggle_action.setText('启动代理')
            self.tray_toggle_action.setEnabled(True)

        self.tray_status_action.setText(f'状态：{short_label}')
        self.tray_icon.setToolTip(f'NMP Client — {short_label}')
        if message:
            logger.info(message)

    def _update_proxy_address(self):
        self.proxy_label.setText(f'127.0.0.1:{self.port_entry.value()}')


def create_application(arguments=None):
    application = QApplication.instance()
    if application is None:
        application = QApplication(arguments or ['nmp-client'])
    application.setApplicationName('NMP Client')
    application.setOrganizationName('RainMark')
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(create_app_icon())
    return application


def main(argv=None):
    parser = argparse.ArgumentParser(description='NMP desktop client')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)

    application = create_application()
    window = NmpClientWindow(config_path=args.config)
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
