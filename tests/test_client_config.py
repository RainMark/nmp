from pathlib import Path

import pytest

from nmp.client import ClientConfig


def test_load_client_config(tmp_path):
    config_path = tmp_path / 'client.toml'
    config_path.write_text(
        '[client]\n'
        'endpoint = "wss://nmp.example.com/base"\n'
        'token = "secret"\n'
        'host = "0.0.0.0"\n'
        'port = 1080\n'
        'pre_connect = true\n',
        encoding='utf-8')

    config = ClientConfig.from_toml(config_path)

    assert config.endpoint == 'wss://nmp.example.com/base'
    assert config.token == 'secret'
    assert config.host == '127.0.0.1'
    assert config.port == 1080
    assert config.pre_connect is True


@pytest.mark.parametrize('endpoint', ['', 'https://example.com', 'wss:///missing-host'])
def test_reject_invalid_endpoint(endpoint):
    config = ClientConfig(endpoint=endpoint, token='token')
    with pytest.raises(ValueError, match='endpoint'):
        config.validate()


def test_reject_unknown_config_option(tmp_path):
    config_path = Path(tmp_path) / 'client.toml'
    config_path.write_text(
        '[client]\nendpoint = "wss://example.com"\n'
        'token = "secret"\nunknown = true\n', encoding='utf-8')

    with pytest.raises(ValueError, match='unsupported client options'):
        ClientConfig.from_toml(config_path)


def test_save_and_reload_client_config(tmp_path):
    config_path = tmp_path / 'nested' / 'client.toml'
    config = ClientConfig(
        endpoint='wss://nmp.example.com/base',
        token='secret "value"',
        port=1080,
        pre_connect=True)

    saved_path = config.save(config_path)
    loaded = ClientConfig.from_toml(config_path)

    assert saved_path == config_path
    assert loaded == config
    assert not config_path.with_name('client.toml.tmp').exists()
