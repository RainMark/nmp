import argparse
import logging
import os
import queue
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

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


def open_directory(path):
    directory = str(Path(path))
    if os.name == 'nt':
        os.startfile(directory)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', directory])
    else:
        subprocess.Popen(['xdg-open', directory])


class QueueLogHandler(logging.Handler):
    def __init__(self, target_queue):
        super().__init__()
        self.target_queue = target_queue

    def emit(self, record):
        try:
            self.target_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class NmpClientApp:
    POLL_INTERVAL_MS = 100
    MAX_LOG_LINES = 1000

    def __init__(self, root, config_path=None, log_path=None, controller=None):
        self.root = root
        self.config_path = (Path(config_path) if config_path is not None
                            else default_config_path())
        self.log_path = (Path(log_path) if log_path is not None
                         else default_log_path())
        self.controller = controller or ClientController()
        self.log_queue = queue.SimpleQueue()
        self.token_filter = TokenFilter()
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
        self._quitting = False
        self._quit_deadline = None

        self.endpoint_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self.port_var = tk.StringVar(value='1234')
        self.pre_connect_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value='● 已停止')
        self.proxy_var = tk.StringVar(value='127.0.0.1:1234')

        self._configure_window()
        self._build_widgets()
        self._load_config()
        self._apply_state(ClientState.STOPPED)
        self.root.protocol('WM_DELETE_WINDOW', self.quit)
        self.root.after(self.POLL_INTERVAL_MS, self._poll)

    def _configure_window(self):
        self.root.title('NMP Client')
        self.root.geometry('720x560')
        self.root.minsize(620, 480)
        style = ttk.Style(self.root)
        if os.name == 'nt' and 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Status.Stopped.TLabel', foreground='#666666')
        style.configure('Status.Busy.TLabel', foreground='#b26a00')
        style.configure('Status.Running.TLabel', foreground='#16833b')
        style.configure('Status.Error.TLabel', foreground='#b42318')

    def _build_widgets(self):
        container = ttk.Frame(self.root, padding=16)
        container.grid(row=0, column=0, sticky='nsew')
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(7, weight=1)

        title = ttk.Label(container, text='NMP Client',
                          font=('', 16, 'bold'))
        title.grid(row=0, column=0, sticky='w', pady=(0, 14))
        self.status_label = ttk.Label(
            container, textvariable=self.status_var,
            style='Status.Stopped.TLabel')
        self.status_label.grid(row=0, column=1, sticky='e', pady=(0, 14))

        ttk.Label(container, text='服务地址').grid(
            row=1, column=0, sticky='w', padx=(0, 12), pady=5)
        self.endpoint_entry = ttk.Entry(
            container, textvariable=self.endpoint_var)
        self.endpoint_entry.grid(row=1, column=1, sticky='ew', pady=5)

        ttk.Label(container, text='Token').grid(
            row=2, column=0, sticky='w', padx=(0, 12), pady=5)
        self.token_entry = ttk.Entry(
            container, textvariable=self.token_var, show='●')
        self.token_entry.grid(row=2, column=1, sticky='ew', pady=5)

        local_frame = ttk.Frame(container)
        local_frame.grid(row=3, column=1, sticky='w', pady=5)
        ttk.Label(container, text='本地代理').grid(
            row=3, column=0, sticky='w', padx=(0, 12), pady=5)
        ttk.Label(local_frame, text='127.0.0.1 :').grid(row=0, column=0)
        self.port_entry = ttk.Entry(
            local_frame, textvariable=self.port_var, width=9)
        self.port_entry.grid(row=0, column=1, padx=(6, 0))

        self.pre_connect_check = ttk.Checkbutton(
            container, text='启用预连接',
            variable=self.pre_connect_var)
        self.pre_connect_check.grid(row=4, column=1, sticky='w', pady=5)

        action_frame = ttk.Frame(container)
        action_frame.grid(row=5, column=0, columnspan=2,
                          sticky='ew', pady=(10, 12))
        action_frame.columnconfigure(2, weight=1)
        self.save_button = ttk.Button(
            action_frame, text='保存配置', command=self.save_config)
        self.save_button.grid(row=0, column=0, padx=(0, 8))
        self.toggle_button = ttk.Button(
            action_frame, text='启动代理', command=self.toggle_proxy)
        self.toggle_button.grid(row=0, column=1)

        ttk.Label(action_frame, text='SOCKS5 地址：').grid(
            row=0, column=3, padx=(12, 0))
        ttk.Label(action_frame, textvariable=self.proxy_var).grid(
            row=0, column=4)
        ttk.Button(action_frame, text='复制', command=self.copy_proxy).grid(
            row=0, column=5, padx=(8, 0))

        log_header = ttk.Frame(container)
        log_header.grid(row=6, column=0, columnspan=2,
                        sticky='ew', pady=(4, 4))
        log_header.columnconfigure(0, weight=1)
        ttk.Label(log_header, text='运行日志').grid(row=0, column=0, sticky='w')
        ttk.Button(log_header, text='清空', command=self.clear_logs).grid(
            row=0, column=1, padx=(8, 0))
        ttk.Button(log_header, text='打开日志目录',
                   command=self.open_logs).grid(row=0, column=2, padx=(8, 0))

        self.log_text = scrolledtext.ScrolledText(
            container, height=14, state='disabled', wrap='word',
            font=('Consolas', 9))
        self.log_text.grid(row=7, column=0, columnspan=2, sticky='nsew')

        self._editable_widgets = (
            self.endpoint_entry,
            self.token_entry,
            self.port_entry,
            self.pre_connect_check,
        )

    def _load_config(self):
        if not self.config_path.exists():
            logger.info(f'config file will be created at {self.config_path}')
            return
        try:
            config = ClientConfig.from_toml(self.config_path)
            self.endpoint_var.set(config.endpoint)
            self.token_var.set(config.token)
            self.token_filter.set_token(config.token)
            self.port_var.set(str(config.port))
            self.pre_connect_var.set(config.pre_connect)
            self._update_proxy_address()
            logger.info(f'loaded config from {self.config_path}')
        except Exception:
            logger.exception(f'failed to load config from {self.config_path}')

    def _config_from_form(self):
        try:
            port = int(self.port_var.get().strip())
        except ValueError as error:
            raise ValueError('本地端口必须是整数') from error
        config = ClientConfig(
            endpoint=self.endpoint_var.get().strip(),
            token=self.token_var.get(),
            port=port,
            pre_connect=bool(self.pre_connect_var.get()))
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
            messagebox.showerror('配置错误', str(error), parent=self.root)
            return None

    def toggle_proxy(self):
        if self.controller.state in (ClientState.STOPPED, ClientState.ERROR):
            config = self.save_config()
            if config is not None:
                try:
                    self.controller.start(config)
                except Exception as error:
                    messagebox.showerror('启动失败', str(error), parent=self.root)
        elif self.controller.state in (ClientState.STARTING,
                                       ClientState.RUNNING):
            self.controller.stop()

    def copy_proxy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.proxy_var.get())
        self.root.update_idletasks()

    def clear_logs(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def open_logs(self):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            open_directory(self.log_path.parent)
        except Exception as error:
            messagebox.showerror('无法打开日志目录', str(error), parent=self.root)

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.root.withdraw()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._quit_deadline = time.monotonic() + 10
        self.controller.stop()
        self._finish_quit_when_stopped()

    def _finish_quit_when_stopped(self):
        if (self.controller.shutdown(wait=False) or
                time.monotonic() >= self._quit_deadline):
            for handler in (self.log_handler, self.file_handler):
                logging.getLogger().removeHandler(handler)
                handler.close()
            self.root.destroy()
            return
        self.root.after(self.POLL_INTERVAL_MS, self._finish_quit_when_stopped)

    def _poll(self):
        for event in self.controller.drain_events():
            self._apply_state(event.state, event.message)
        self._drain_logs()
        if not self._quitting:
            self.root.after(self.POLL_INTERVAL_MS, self._poll)

    def _drain_logs(self):
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        self.log_text.configure(state='normal')
        self.log_text.insert('end', '\n'.join(lines) + '\n')
        line_count = int(self.log_text.index('end-1c').split('.')[0])
        if line_count > self.MAX_LOG_LINES:
            self.log_text.delete(
                '1.0', f'{line_count - self.MAX_LOG_LINES + 1}.0')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def _apply_state(self, state, message=''):
        labels = {
            ClientState.STOPPED: ('● 已停止', 'Status.Stopped.TLabel'),
            ClientState.STARTING: ('● 启动中', 'Status.Busy.TLabel'),
            ClientState.RUNNING: ('● 运行中', 'Status.Running.TLabel'),
            ClientState.STOPPING: ('● 停止中', 'Status.Busy.TLabel'),
            ClientState.ERROR: ('● 错误', 'Status.Error.TLabel'),
        }
        label, style = labels[state]
        self.status_var.set(label)
        self.status_label.configure(style=style)
        busy = state in (ClientState.STARTING,
                         ClientState.RUNNING,
                         ClientState.STOPPING)
        widget_state = 'disabled' if busy else 'normal'
        for widget in self._editable_widgets:
            widget.configure(state=widget_state)
        self.save_button.configure(state=widget_state)

        if state == ClientState.RUNNING:
            self.toggle_button.configure(text='停止代理', state='normal')
        elif state in (ClientState.STARTING, ClientState.STOPPING):
            self.toggle_button.configure(
                text='正在处理…', state='disabled')
        else:
            self.toggle_button.configure(text='启动代理', state='normal')
        if message:
            logger.info(message)

    def _update_proxy_address(self):
        port = self.port_var.get().strip() or '1234'
        self.proxy_var.set(f'127.0.0.1:{port}')


def self_test():
    with tempfile.TemporaryDirectory(prefix='nmp-gui-test-') as directory:
        root = tk.Tk()
        root.withdraw()
        app = NmpClientApp(
            root,
            config_path=Path(directory) / 'client.toml',
            log_path=Path(directory) / 'nmp-client.log')
        root.update_idletasks()
        app.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description='NMP Windows GUI client')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--self-test', action='store_true',
                        help='verify that the packaged GUI can start')
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    root = tk.Tk()
    NmpClientApp(root, config_path=args.config)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
