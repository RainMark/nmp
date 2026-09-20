#!/usr/bin/env python3

import logging
import sys
from urllib.parse import quote

import coloredlogs

fmt = '[%(asctime)s,%(msecs)03d] [%(levelname)7s] [%(filename)s -- %(funcName)s():%(lineno)s] %(message)s'
coloredlogs.DEFAULT_FIELD_STYLES['levelname'] = {'bold': True}


class TokenFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.values = ()

    def set_token(self, token):
        self.values = tuple(filter(None, (token, quote(token, safe=''))))

    def filter(self, record):
        message = record.getMessage()
        for value in self.values:
            message = message.replace(value, '[redacted]')
        record.msg = message
        record.args = ()
        return True


def get_logger(name: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if sys.stderr is not None:
        coloredlogs.install(level=logging.INFO,
                            fmt=fmt,
                            milliseconds=True,
                            logger=logger)
    return logger
