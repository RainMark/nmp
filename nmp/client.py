#!/usr/bin/env python3

import argparse
import asyncio
import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

if sys.version_info >= (3, 11):
    import tomllib
else:  # Keep the import dynamic so Python 3.11+ bundles don't include tomli.
    tomllib = importlib.import_module('tomli')

from nmp.log import get_logger
from nmp.runtime import add_stop_signal
from nmp.sockv5 import SockV5Server


logger = get_logger(__name__)


def default_config_path():
    if os.name == 'nt' and os.environ.get('APPDATA'):
        return Path(os.environ['APPDATA']) / 'NMP' / 'client.toml'
    return Path.home() / '.config' / 'nmp' / 'client.toml'


@dataclass
class ClientConfig:
    endpoint: str = ''
    token: str = ''
    host: str = '127.0.0.1'
    port: int = 1234
    pre_connect: bool = False

    @classmethod
    def from_toml(cls, path):
        with Path(path).open('rb') as config_file:
            values = tomllib.load(config_file).get('client', {})
        if not isinstance(values, dict):
            raise ValueError('[client] must be a TOML table')

        supported = {'endpoint', 'token', 'host', 'port', 'pre_connect'}
        unknown = set(values) - supported
        if unknown:
            raise ValueError(f'unsupported client options: {", ".join(sorted(unknown))}')
        return cls(**values)

    def validate(self):
        if not isinstance(self.endpoint, str):
            raise ValueError('endpoint must be a string')
        endpoint = urlsplit(self.endpoint)
        if endpoint.scheme not in ('ws', 'wss') or not endpoint.hostname:
            raise ValueError('endpoint must be a ws:// or wss:// URL')
        try:
            endpoint.port
        except ValueError as error:
            raise ValueError(f'invalid endpoint port: {error}') from error
        if not isinstance(self.token, str) or not self.token.strip():
            raise ValueError('token is required')
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError('port must be between 1 and 65535')
        if not isinstance(self.host, str) or not self.host:
            raise ValueError('host is required')
        if not isinstance(self.pre_connect, bool):
            raise ValueError('pre_connect must be true or false')

    def save(self, path=None):
        self.validate()
        config_path = Path(path) if path is not None else default_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = config_path.with_name(f'{config_path.name}.tmp')
        contents = (
            '[client]\n'
            f'endpoint = {json.dumps(self.endpoint, ensure_ascii=False)}\n'
            f'token = {json.dumps(self.token, ensure_ascii=False)}\n'
            f'host = {json.dumps(self.host, ensure_ascii=False)}\n'
            f'port = {self.port}\n'
            f'pre_connect = {str(self.pre_connect).lower()}\n'
        )
        temporary_path.write_text(contents, encoding='utf-8')
        os.replace(temporary_path, config_path)
        return config_path


def parse_args(argv=None):
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument('--config', type=Path)
    config_args, _ = config_parser.parse_known_args(argv)

    config_path = config_args.config or default_config_path()
    if config_path.exists():
        config = ClientConfig.from_toml(config_path)
    elif config_args.config:
        config_parser.error(f'config file not found: {config_path}')
    else:
        config = ClientConfig()

    parser = argparse.ArgumentParser(
        parents=[config_parser],
        description='NMP local SOCKS5 client')
    parser.add_argument('--endpoint', default=config.endpoint,
                        help='NMP server endpoint, for example wss://nmp.example.com')
    parser.add_argument('--token', default=config.token,
                        help='NMP server token')
    parser.add_argument('--host', default=config.host,
                        help='local bind host (default: 127.0.0.1)')
    parser.add_argument('--port', default=config.port, type=int,
                        help='local SOCKS5 port (default: 1234)')
    pre_connect = parser.add_mutually_exclusive_group()
    pre_connect.add_argument('--pre-connect', dest='pre_connect',
                             action='store_true',
                             help='maintain idle WebSocket connections')
    pre_connect.add_argument('--no-pre-connect', dest='pre_connect',
                             action='store_false',
                             help='disable idle WebSocket connections')
    parser.set_defaults(pre_connect=config.pre_connect)
    args = parser.parse_args(argv)

    result = ClientConfig(endpoint=args.endpoint, token=args.token,
                          host=args.host, port=args.port,
                          pre_connect=args.pre_connect)
    try:
        result.validate()
    except ValueError as error:
        parser.error(str(error))
    return result


async def run(config):
    logger.info(f'start local SOCKS5 server: ({config.host}:{config.port})')
    add_stop_signal()
    await SockV5Server(config).start_server()


def main(argv=None):
    config = parse_args(argv)
    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('stopped')
        return 0
    except Exception as error:
        logger.exception(error)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
