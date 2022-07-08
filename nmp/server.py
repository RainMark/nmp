#!/bin/env python3

import asyncio
import base64
import os
import secrets
import socket
import struct
import websockets
from random import randint
from nmp.log import get_logger
from nmp.pipe import DatagramPipe, SocketStream, Pipe
from nmp.proto import NMP_CONNECT_FAILED, NMP_CONNECT_OK, NMP_FASTPATH_HOST, NMP_FASTPATH_PAYLOAD, \
    NMP_FASTPATH_PORT, NMP_TCP_PIPE_DOMAIN, NMP_TCP_PIPE_IP, NMP_UDP_PIPE_IP, NMP_UDP_PIPE_IP_WITH_DATA, WEBSOCKETS_MAX_QUEUE


MAX_BACKLOG = 2 ** 10


def create_reuseport_stream_socket(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.bind((host, port))
    sock.listen(MAX_BACKLOG)
    sock.setblocking(False)
    return sock


class WebSockHandler:
    def __init__(self, wsock):
        self.logger = get_logger(__name__)
        self.wsock = wsock

    # -----------------------
    # | 2 bytes |    ...    |
    # |  port   | ip/domain |
    async def handle_stream_type(self, data):
        port = struct.unpack('!H', data[:2])[0]
        host = data[2:].decode()
        self.logger.debug(host)
        self.logger.debug(port)
        sock = await SocketStream.open_connection(host, port)
        if sock is None:
            reply = struct.pack('!B', NMP_CONNECT_FAILED)
            await self.wsock.send(reply)
            await self.wsock.close()
            return

        reply = struct.pack('!B', NMP_CONNECT_OK)
        await self.wsock.send(reply)
        pipe = Pipe(self.wsock, sock)
        await pipe.pipe()

    # ---------------------------------------------
    # | 2 bytes |  2 bytes |  length bytes | ...  |
    # |   port  |  length  |   ip/domain   | data |
    async def handle_stream_type_with_data(self, data):
        port, length = struct.unpack('!HH', data[:4])
        offset = length + 4
        host = data[4:offset].decode()
        sock = await SocketStream.open_connection(host, port)
        if sock is None:
            await self.wsock.close()
            return

        await sock.send(data[offset:])
        pipe = Pipe(self.wsock, sock)
        await pipe.pipe()

    async def handle_datagram_type(self):
        pipe = DatagramPipe(self.wsock)
        await pipe.pipe()

    async def handle_stream_type_fastpath(self, fastpath):
        # 0:host 1:port 2:payload
        sock = await SocketStream.open_connection(fastpath[0], fastpath[1])
        if sock is None:
            await self.wsock.close()
            return
        await sock.send(fastpath[2])
        pipe = Pipe(self.wsock, sock)
        await pipe.pipe()

    async def stream_fastpath(self):
        headers = self.wsock.request_headers
        if headers is None:
            return None
        host = headers.get(NMP_FASTPATH_HOST, None)
        port = headers.get(NMP_FASTPATH_PORT, None)
        payload = headers.get(NMP_FASTPATH_PAYLOAD, None)
        if host is None or port is None or payload is None:
            return None
        return (host, int(port), base64.b64decode(payload))

    async def handle(self):
        fastpath = await self.stream_fastpath()
        if fastpath is not None:
            await self.handle_stream_type_fastpath(fastpath)
            return

        # -----------
        # | 1 bytes |
        # |  type   |
        req = await self.wsock.recv()
        self.logger.debug(req)
        rtype = struct.unpack('!B', req[:1])[0]
        if rtype == NMP_TCP_PIPE_IP or rtype == NMP_TCP_PIPE_DOMAIN:
            await self.handle_stream_type(req[1:])
        elif rtype == NMP_UDP_PIPE_IP:
            await self.handle_datagram_type()
        elif rtype == NMP_UDP_PIPE_IP_WITH_DATA:
            await self.handle_stream_type_with_data(req[1:])
        else:
            self.logger.error(f'not supported type[{rtype}]')


class NmpServer:
    def __init__(self, config):
        self.logger = get_logger(__name__)
        self.config = config

    def load_token(self):
        if os.path.exists(self.config.conf):
            with open(self.config.conf, 'r') as f:
                self.token = f.read()
        else:
            self.token = secrets.token_hex(randint(8, 16))
            with open(self.config.conf, 'w') as f:
                f.write(self.token)

    async def start_server(self):
        self.load_token()
        self.logger.info(f'### Token: {self.token} ###')
        async with websockets.serve(
            self.dispatch, sock=create_reuseport_stream_socket(
                self.config.host, self.config.port),
                ping_interval=None,
                process_request=None,
                max_queue=WEBSOCKETS_MAX_QUEUE,
                compression=None):
            await asyncio.Future()

    async def dispatch(self, wsock, path):
        handler = WebSockHandler(wsock)
        self.logger.debug(f'connect: {path}')
        try:
            await handler.handle()
        except Exception as e:
            self.logger.exception(e)
            if not wsock.closed:
                await wsock.close()
