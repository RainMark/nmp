import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nmp.pipe import Pipe
from nmp.server import WebSockHandler


def stream_request(handler, mode):
    host = b'localhost'
    if mode == 'stream':
        return handler.handle_stream_type(struct.pack('!H', 80) + host)
    if mode == 'with_data':
        return handler.handle_stream_type_with_data(
            struct.pack('!HH', 80, len(host)) + host + b'payload')
    return handler.handle_stream_type_fastpath(('localhost', 80, b'payload'))


@pytest.mark.parametrize('mode', ['stream', 'with_data', 'fastpath'])
@pytest.mark.parametrize('stage', ['send', 'pipe', 'cancel'])
def test_server_closes_target_on_failure_or_cancellation(mode, stage):
    async def run():
        error = ConnectionResetError('connection interrupted')
        sock = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
        ws = SimpleNamespace(send=AsyncMock())
        pipe = AsyncMock()
        entered = asyncio.Event()

        async def blocked_pipe():
            entered.set()
            await asyncio.Event().wait()

        if stage == 'send':
            (ws.send if mode == 'stream' else sock.send).side_effect = error
        elif stage == 'pipe':
            pipe.side_effect = error
        else:
            pipe.side_effect = blocked_pipe

        with patch('nmp.server.SocketStream.open_connection',
                   AsyncMock(return_value=sock)), patch.object(Pipe, 'pipe', pipe):
            task = asyncio.create_task(stream_request(WebSockHandler(ws), mode))
            if stage == 'cancel':
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                # A cleanup error must not replace the original transfer error.
                sock.close.side_effect = OSError('close failed')
                with pytest.raises(ConnectionResetError) as caught:
                    await task
                assert caught.value is error
            sock.close.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize('error', [OSError('close failed'), asyncio.CancelledError()])
def test_pipe_closes_second_endpoint_when_first_close_fails(error):
    async def run():
        first = SimpleNamespace(close=AsyncMock(side_effect=error))
        second = SimpleNamespace(close=AsyncMock())
        pipe = Pipe(first, second)
        pipe.pipeing = True
        with pytest.raises(type(error)):
            await pipe.close()
        second.close.assert_awaited_once()
        assert not pipe.pipeing

    asyncio.run(run())
