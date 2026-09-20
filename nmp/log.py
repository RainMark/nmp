#!/usr/bin/env python3

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from urllib.parse import quote

import coloredlogs

fmt = '[%(asctime)s,%(msecs)03d] [%(levelname)7s] [%(filename)s -- %(funcName)s():%(lineno)s] %(message)s'
coloredlogs.DEFAULT_FIELD_STYLES['levelname'] = {'bold': True}

_lock = RLock()
_console_configured = False
_file_handlers = {}
_sensitive_values = set()


class RedactingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        with _lock:
            values = tuple(_sensitive_values)
        for value in values:
            message = message.replace(value, '[redacted]')
        record.msg = message
        record.args = ()
        return True


def register_sensitive_value(value):
    if not value:
        return
    with _lock:
        _sensitive_values.add(str(value))
        _sensitive_values.add(quote(str(value), safe=''))


def _configure_console_logging():
    global _console_configured
    with _lock:
        if _console_configured:
            return
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        if sys.stderr is not None:
            coloredlogs.install(level=logging.INFO,
                                fmt=fmt,
                                milliseconds=True,
                                logger=root)
            for handler in root.handlers:
                handler.addFilter(RedactingFilter())
        _console_configured = True


def configure_file_logging(path, max_bytes=2 * 1024 * 1024, backup_count=3):
    _configure_console_logging()
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(log_path.resolve())
    with _lock:
        if key in _file_handlers:
            return _file_handlers[key]
        handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count,
            encoding='utf-8')
        handler.setFormatter(logging.Formatter(fmt))
        handler.addFilter(RedactingFilter())
        logging.getLogger().addHandler(handler)
        _file_handlers[key] = handler
        return handler


def add_log_handler(handler):
    _configure_console_logging()
    handler.addFilter(RedactingFilter())
    logging.getLogger().addHandler(handler)


def remove_log_handler(handler):
    logging.getLogger().removeHandler(handler)


def remove_file_logging(handler):
    with _lock:
        logging.getLogger().removeHandler(handler)
        for key, registered_handler in tuple(_file_handlers.items()):
            if registered_handler is handler:
                del _file_handlers[key]
        handler.close()


def get_logger(name: str = None) -> logging.Logger:
    _configure_console_logging()
    return logging.getLogger(name)
