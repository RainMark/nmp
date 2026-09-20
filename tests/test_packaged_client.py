import asyncio
import os

import pytest

from tests.helpers import (echo_handler, socks5_connect, start_nmp_server,
                           unused_tcp_port, wait_for_port)


def test_packaged_client_round_trip():
    executable = os.environ.get('NMP_PACKAGED_EXE')
    if not executable:
        pytest.skip('NMP_PACKAGED_EXE is only set by the packaging job')

    async def run():
        echo_server = await asyncio.start_server(echo_handler, '127.0.0.1', 0)
        echo_port = echo_server.sockets[0].getsockname()[1]
        nmp_server, nmp_port = await start_nmp_server()
        socks_port = unused_tcp_port()
        process = await asyncio.create_subprocess_exec(
            executable,
            '--endpoint', f'ws://127.0.0.1:{nmp_port}',
            '--token', 'test-token',
            '--port', str(socks_port),
        )

        try:
            await wait_for_port('127.0.0.1', socks_port)
            reader, writer = await socks5_connect(
                socks_port, '127.0.0.1', echo_port)
            payload = b'packaged-nmp-client-test'
            writer.write(payload)
            await writer.drain()
            assert await asyncio.wait_for(
                reader.readexactly(len(payload)), timeout=10) == payload
            writer.close()
            await writer.wait_closed()
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            nmp_server.close()
            await nmp_server.wait_closed()
            echo_server.close()
            await echo_server.wait_closed()

    asyncio.run(run())
