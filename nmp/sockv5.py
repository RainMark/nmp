#!/bin/env python3

import asyncio
import base64
import socket
import struct
from nmp.connection import ConnectionPool
from nmp.log import get_logger
from nmp.pipe import Pipe, SocketStream
from nmp.server import create_reuseport_stream_socket
from nmp.proto import ATYP_DOMAINNAME, ATYP_IP_V4, CMD_CONNECT, IMPLEMENTED_METHODS, \
    NMP_FASTPATH_HOST, NMP_FASTPATH_MAX_BYTES, NMP_FASTPATH_PAYLOAD, NMP_FASTPATH_PORT, NMP_TCP_PIPE_WITH_DATA, RSV, SOCK_V5


class SockHandler:
    def __init__(self, sock, pool: ConnectionPool):
        self.logger = get_logger(__name__)
        self.sock = sock
        self.connection_pool = pool
        self.pipeing = False

    async def handle(self):
        r = await self.parse_ver_and_reply()
        if not r:
            await self.sock.close()
            return

        wsock = await self.connect_and_reply()
        if wsock is None:
            await self.sock.close()
            return

        pipe = Pipe(self.sock, wsock)
        await pipe.pipe()

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
        self.connection_pool = ConnectionPool(
            config.endpoint, config.token, pre_connect=config.pre_connect)

    async def start_server(self):
        server = await asyncio.start_server(self.dispatch,
                                            sock=create_reuseport_stream_socket(self.config.host, self.config.port))
        async with server:
            await server.serve_forever()

    async def dispatch(self, r, w):
        handler = SockHandler(SocketStream(r, w), self.connection_pool)
        try:
            await handler.handle()
        except Exception as e:
            self.logger.exception(e)
            if not handler.sock.closed:
                await handler.sock.close()
