#!/bin/env python3

import asyncio
import socket
import struct
import websockets
from nmp.log import get_logger
from nmp.proto import NMP_CONNECT_FAILED, NMP_CONNECT_OK

BUFFER_SIZE = 2 ** 16


class SocketStream:
    def __init__(self, reader, writer):
        self.logger = get_logger(__name__)
        self.reader = reader
        self.writer = writer
        self.closed = False

    async def send(self, msg):
        self.writer.write(msg)
        await self.writer.drain()

    async def recv(self, n=BUFFER_SIZE):
        self.logger.debug('recv')
        msg = await self.reader.read(n)
        self.logger.debug(msg)
        return msg

    async def recv_exactly(self, n):
        return await self.reader.readexactly(n)

    async def close(self):
        self.closed = True
        self.writer.close()
        await self.writer.wait_closed()

    @staticmethod
    async def open_connection(host, port):
        try:
            r, w = await asyncio.open_connection(host, port)
            return SocketStream(r, w)
        except Exception as e:
            get_logger(__name__).exception(e)
            return None


PIPE_EXCEPTION = (RuntimeError, TimeoutError, ConnectionResetError,
                  websockets.ConnectionClosedError,
                  websockets.ConnectionClosedOK)


class Pipe:
    def __init__(self, sock1, sock2):
        self.logger = get_logger(__name__)
        self.sock1 = sock1
        self.sock2 = sock2
        self.pipeing = False

    async def recv_and_send(self, r, w):
        while self.pipeing:
            try:
                msg = await r.recv()
                if not len(msg):
                    await self.close()
                await w.send(msg)
            except PIPE_EXCEPTION as e:
                await self.close()
                self.logger.debug(e)
            except Exception as e:
                await self.close()
                self.logger.exception(e)

    async def pipe(self):
        self.pipeing = True
        await asyncio.gather(asyncio.create_task(self.recv_and_send(self.sock1, self.sock2)),
                             asyncio.create_task(self.recv_and_send(self.sock2, self.sock1)))

    async def close(self):
        self.pipeing = False
        await self.sock1.close()
        await self.sock2.close()


class DatagramHandler:
    def __init__(self, message, future):
        self.logger = get_logger(__name__)
        self.message = message
        self.future = future
        self.transport = None
        self.timer = None

    def connection_made(self, transport):
        self.logger.debug(f'send: {self.message}')
        self.transport = transport
        loop = asyncio.get_running_loop()
        self.timer = loop.call_later(
            delay=10, callback=self.connection_timeout)
        self.transport.sendto(self.message)

    def connection_timeout(self):
        self.logger.info(f'connection timeout: {self.transport}')
        self.connection_close()

    def datagram_received(self, data, addr):
        self.logger.debug(f'received: {addr}, data: {data}')
        self.future.set_result(data)
        if self.timer:
            self.timer.cancel()
        self.connection_close()

    def error_received(self, exc):
        self.logger.debug(f'exception: {exc}')
        self.future.set_result(None)

    def connection_lost(self, exc):
        self.logger.debug(f'connection lost: {exc}')

    def connection_close(self):
        if not self.transport:
            self.transport.close()
            self.transport = None
        if not self.future.done():
            self.future.set_result(None)


class DatagramPipe:
    def __init__(self, wsock):
        self.logger = get_logger(__name__)
        self.wsock = wsock

    async def accept(self):
        msg = await self.wsock.recv()
        self.logger.debug(msg)
        if not len(msg):
            self.logger.debug(f'websocket connection[{self.wsock}] closed')
            return False

        await self.send_and_reply(msg)
        return True

    # -------------------------------
    # | 4 bytes | 2 bytes  |  ...   |
    # |   ip   |   port   | payload |
    async def send_and_reply(self, msg):
        host = socket.inet_ntoa(msg[:4])
        port = struct.unpack('!H', msg[4:6])[0]
        payload = msg[6:]
        self.logger.debug(host)
        self.logger.debug(port)
        self.logger.debug(payload)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: DatagramHandler(payload, future), remote_addr=(host, port))
        data = await protocol.future
        transport.close()
        if not data:
            reply = struct.pack('!B', NMP_CONNECT_FAILED)
            await self.wsock.send(reply)
            return
        reply = bytearray(struct.pack('!B', NMP_CONNECT_OK))
        reply.extend(data)
        await self.wsock.send(reply)

    async def pipe(self):
        pipeing = True
        while pipeing:
            try:
                pipeing = await self.accept()
            except PIPE_EXCEPTION as e:
                self.logger.debug(e)
                pipeing = False
            except Exception as e:
                self.logger.exception(e)
                pipeing = False
        await self.wsock.close()
