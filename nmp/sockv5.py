#!/bin/env python3

import asyncio
import base64
import socket
import struct
from contextlib import suppress
from nmp.connection import ConnectionPool
from nmp.listener import create_stream_socket
from nmp.log import get_logger
from nmp.pipe import Pipe, SocketStream
from nmp.proto import ATYP_DOMAINNAME, ATYP_IP_V4, CMD_CONNECT, IMPLEMENTED_METHODS, \
    NMP_FASTPATH_HOST, NMP_FASTPATH_MAX_BYTES, NMP_FASTPATH_PAYLOAD, NMP_FASTPATH_PORT, NMP_TCP_PIPE_WITH_DATA, RSV, SOCK_V5


class SockHandler:
    def __init__(self, sock, pool: ConnectionPool):
        self.logger = get_logger(__name__)
        self.sock = sock
        self.connection_pool = pool
        self.pipeing = False
        self.wsock = None

    async def handle(self):
        r = await self.parse_ver_and_reply()
        if not r:
            await self.sock.close()
            return

        wsock = await self.connect_and_reply()
        if wsock is None:
            await self.sock.close()
            return

        self.wsock = wsock
        pipe = Pipe(self.sock, wsock)
        await pipe.pipe()

    async def close(self):
        if not self.sock.closed:
            with suppress(Exception):
                await self.sock.close()
        if self.wsock is not None and not self.wsock.closed:
            with suppress(Exception):
                await self.wsock.close()

    async def parse_ver_and_reply(self):
        hdr = await self.sock.recv_exactly(2)
        ver, nmethods = struct.unpack('!BB', hdr)
        if SOCK_V5 != ver:
            self.logger.warning(f'invalid socks ver: {ver}')
            return False

        methods = await self.sock.recv_exactly(nmethods)
        for method in methods:
            if method in IMPLEMENTED_METHODS:
                await self.sock.send(struct.pack('!BB', SOCK_V5, method))
                return True

        self.logger.warning(f'methods exchange fail: {methods}')
        return False

    async def connect_and_reply(self):
        hdr = await self.sock.recv_exactly(4)
        _, cmd, _, atyp = struct.unpack('!BBBB', hdr)
        if CMD_CONNECT != cmd:
            return None

        if ATYP_IP_V4 == atyp:
            dst = await self.sock.recv_exactly(6)
            addr = socket.inet_ntoa(dst[:4]).encode()
            port = struct.unpack('!H', dst[4:])[0]
        elif ATYP_DOMAINNAME == atyp:
            length = await self.sock.recv_exactly(1)
            addr = await self.sock.recv_exactly(length[0])
            port = struct.unpack('!H', await self.sock.recv_exactly(2))[0]
        else:
            return None

        await self.send_socks_reply(0, atyp, addr, port)
        data = await self.sock.recv(NMP_FASTPATH_MAX_BYTES)
        wsock = await self.connection_pool.try_get_connection()
        if wsock is not None:
            await self.connect_and_send_data(wsock, addr, port, data)
            return wsock

        return await self.connection_pool.new_connection(self.make_headers(addr, port, data))

    async def send_socks_reply(self, rep, atyp, addr, port):
        reply = bytearray(struct.pack('!BBBB', SOCK_V5, rep, RSV, atyp))
        if atyp == ATYP_IP_V4:
            reply.extend(socket.inet_aton(addr.decode()))
        else:
            reply.extend(struct.pack('!B', len(addr)))
            reply.extend(addr)
        reply.extend(struct.pack('!H', port))
        await self.sock.send(reply)

    async def connect_and_send_data(self, wsock, host, port, data):
        req = bytearray(struct.pack(
            '!BHH', NMP_TCP_PIPE_WITH_DATA, port, len(host)))
        req.extend(host)
        req.extend(data)
        await wsock.send(req)

    def make_headers(self, host, port, data):
        return {
            NMP_FASTPATH_HOST: host.decode(),
            NMP_FASTPATH_PORT: port,
            NMP_FASTPATH_PAYLOAD: base64.b64encode(data).decode()
        }


class SockV5Server:
    def __init__(self, config):
        self.logger = get_logger(__name__)
        self.config = config
        self.server = None
        self.client_tasks = set()
        self.client_writers = set()
        self.connection_pool = ConnectionPool(
            config.endpoint, config.token, pre_connect=config.pre_connect)

    async def start_server(self):
        await self.start()
        try:
            await self.server.serve_forever()
        finally:
            await self.stop()

    async def start(self):
        if self.server is not None:
            raise RuntimeError('SOCKS5 server is already running')
        self.server = await asyncio.start_server(
            self._client_connected,
            sock=create_stream_socket(
                self.config.host, self.config.port))

    def _client_connected(self, reader, writer):
        task = asyncio.create_task(self.dispatch(reader, writer))
        self.client_tasks.add(task)
        self.client_writers.add(writer)

        def connection_done(completed_task):
            self.client_tasks.discard(completed_task)
            self.client_writers.discard(writer)

        task.add_done_callback(connection_done)

    async def stop(self):
        server = self.server
        if server is not None:
            server.close()
            # Python 3.13 waits for accepted clients in wait_closed().  This
            # also closes connections accepted immediately before stop(),
            # before their callback has had a chance to register a task.
            if hasattr(server, 'close_clients'):
                server.close_clients()

        writers = tuple(self.client_writers)
        for writer in writers:
            writer.close()
        current = asyncio.current_task()
        tasks = [task for task in self.client_tasks
                 if task is not current and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True)
        if server is not None:
            await server.wait_closed()
            self.server = None
        await self.connection_pool.close()

    async def dispatch(self, r, w):
        task = asyncio.current_task()
        if task is not None:
            self.client_tasks.add(task)
        handler = SockHandler(SocketStream(r, w), self.connection_pool)
        try:
            await handler.handle()
        except asyncio.CancelledError:
            await handler.close()
            raise
        except Exception as e:
            self.logger.exception(e)
            await handler.close()
        finally:
            if task is not None:
                self.client_tasks.discard(task)
