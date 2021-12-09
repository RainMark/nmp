#!/bin/env python3

import asyncio
import json
import os
import secrets
import string
import struct
import websockets
from random import randint, choices
from http import HTTPStatus
from nmp.log import get_logger
from nmp.pipe import DatagramPipe, SocketStream, Pipe
from nmp.proto import NMP_CONNECT_FAILED, NMP_CONNECT_OK, NMP_TCP_PIPE_DOMAIN, NMP_TCP_PIPE_IP, NMP_UDP_PIPE_IP, WEBSOCKETS_MAX_QUEUE


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
        if not sock:
            reply = struct.pack('!B', NMP_CONNECT_FAILED)
            await self.wsock.send(reply)
            await self.wsock.close()
            return

        reply = struct.pack('!B', NMP_CONNECT_OK)
        await self.wsock.send(reply)
        pipe = Pipe(self.wsock, sock)
        await pipe.pipe()

    async def handle_datagram_type(self):
        pipe = DatagramPipe(self.wsock)
        await pipe.pipe()

    # -----------
    # | 1 bytes |
    # |  type   |
    async def handle(self):
        req = await self.wsock.recv()
        self.logger.debug(req)
        rtype = struct.unpack('!B', req[:1])[0]
        if rtype == NMP_TCP_PIPE_IP or rtype == NMP_TCP_PIPE_DOMAIN:
            await self.handle_stream_type(req[1:])
        elif rtype == NMP_UDP_PIPE_IP:
            await self.handle_datagram_type()
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

    def token_auth(self, path):
        # /token/dummy
        return self.token == path[1:].split('/')[0]

    def http_handler(self, path, headers):
        self.logger.debug(path)
        if self.token_auth(path):
            return None

        self.logger.warning(
            f'auth token failed, path: {path}, headers: {headers}')
        status = [HTTPStatus.INTERNAL_SERVER_ERROR,
                  HTTPStatus.OK][randint(0, 1)]
        reply = {'data': ''.join(
            choices(string.ascii_letters + string.digits, k=32))}
        return status, {'Content-Type': 'application/json'}, json.dumps(reply).encode('utf-8')

    async def start_server(self):
        self.load_token()
        self.logger.info(f'### Token: {self.token} ###')
        async with websockets.serve(self.dispatch, self.config.host, self.config.port,
                                    process_request=self.http_handler,
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
