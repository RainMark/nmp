import asyncio
from types import SimpleNamespace

from nmp.sockv5 import SockV5Server
from tests.helpers import echo_handler, socks5_connect, start_nmp_server


def test_socks5_to_nmp_tcp_round_trip():
    async def run():
        echo_server = await asyncio.start_server(echo_handler, '127.0.0.1', 0)
        echo_port = echo_server.sockets[0].getsockname()[1]
        nmp_server, nmp_port = await start_nmp_server()

        config = SimpleNamespace(
            endpoint=f'ws://127.0.0.1:{nmp_port}',
            token='test-token',
            pre_connect=False,
        )
        socks = SockV5Server(config)
        socks_server = await asyncio.start_server(
            socks.dispatch, '127.0.0.1', 0)
        socks_port = socks_server.sockets[0].getsockname()[1]

        try:
            reader, writer = await socks5_connect(
                socks_port, '127.0.0.1', echo_port)
            payload = b'nmp-windows-client-test'
            writer.write(payload)
            await writer.drain()
            assert await asyncio.wait_for(
                reader.readexactly(len(payload)), timeout=5) == payload
            writer.close()
            await writer.wait_closed()
        finally:
            socks_server.close()
            await socks_server.wait_closed()
            nmp_server.close()
            await nmp_server.wait_closed()
            echo_server.close()
            await echo_server.wait_closed()

    asyncio.run(run())
