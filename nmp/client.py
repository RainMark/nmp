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

def default_config_path():
    if os.name == 'nt' and os.environ.get('APPDATA'):
        return Path(os.environ['APPDATA']) / 'NMP' / 'client.toml'
    if sys.platform == 'darwin':
        return (Path.home() / 'Library' / 'Application Support' /
                'NMP' / 'client.toml')
    return Path.home() / '.config' / 'nmp' / 'client.toml'


@dataclass
class ClientConfig:
    endpoint: str = ''
    token: str = ''
    port: int = 1234
    pre_connect: bool = False

    @property
    def host(self):
        return '127.0.0.1'

    @classmethod
    def from_toml(cls, path):
        with Path(path).open('rb') as config_file:
            values = tomllib.load(config_file).get('client', {})
        if not isinstance(values, dict):
            raise ValueError('[client] must be a TOML table')
        values.pop('host', None)  # Older clients exposed this fixed value.

        supported = {'endpoint', 'token', 'port', 'pre_connect'}
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
            f'port = {self.port}\n'
            f'pre_connect = {str(self.pre_connect).lower()}\n'
        )
        temporary_path.write_text(contents, encoding='utf-8')
        os.replace(temporary_path, config_path)
        return config_path
