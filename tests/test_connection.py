import asyncio
from unittest.mock import patch

from nmp.connection import ConnectionPool


def test_ssl_context_uses_certifi_ca_bundle():
    with patch('nmp.connection.certifi.where', return_value='/ca.pem'):
        with patch('nmp.connection.ssl.create_default_context') as create:
            ConnectionPool.new_ssl_context()

    create.assert_called_once_with(cafile='/ca.pem')


def test_connection_target_preserves_endpoint_path_and_port():
    async def run():
        pool = ConnectionPool('wss://example.com:8443/base/', 'a token')
        uri, hostname, port = pool.connection_target()

        assert uri.startswith('wss://example.com:8443/base/a%20token/')
        assert hostname == 'example.com'
        assert port == 8443

    asyncio.run(run())


def test_connection_target_defaults_ws_port():
    async def run():
        pool = ConnectionPool('ws://127.0.0.1', 'token')
        _, hostname, port = pool.connection_target()
        assert hostname == '127.0.0.1'
        assert port == 80

    asyncio.run(run())
