import asyncio
import socket
import struct
from types import SimpleNamespace

import websockets

from nmp.server import NmpServer


async def echo_handler(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def start_nmp_server():
    nmp = NmpServer(SimpleNamespace())
    server = await websockets.serve(
        nmp.dispatch, '127.0.0.1', 0,
        ping_interval=None, ping_timeout=None, compression=None)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def wait_for_port(host, port, timeout=30):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.05)


async def socks5_connect(proxy_port, target_host, target_port):
    reader, writer = await asyncio.open_connection('127.0.0.1', proxy_port)
    writer.write(b'\x05\x01\x00')
    await writer.drain()
    assert await reader.readexactly(2) == b'\x05\x00'

    host = target_host.encode()
    request = b'\x05\x01\x00\x03' + bytes([len(host)]) + host
    request += struct.pack('!H', target_port)
    writer.write(request)
    await writer.drain()

    version, status, _, address_type = await reader.readexactly(4)
    assert (version, status) == (5, 0)
    if address_type == 1:
        await reader.readexactly(4)
    elif address_type == 3:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length)
    else:
        raise AssertionError(f'unexpected SOCKS5 address type: {address_type}')
    await reader.readexactly(2)
    return reader, writer


def unused_tcp_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]
