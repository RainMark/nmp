#!/bin/env python3

import asyncio
import secrets
import ssl
import struct
import time
import websockets
from collections import deque
from random import randint
from nmp.log import get_logger
from nmp.proto import NMP_UDP_PIPE_IP, WEBSOCKETS_MAX_QUEUE

MAX_MSG_BUF_SIZE = 2 ** 16
MAX_IDLE_CONNECTION = 8
MAX_PRE_CONNECTED_CONNECTION = 8
MAX_INACTIVE_TIME = 300
PRE_CONNECTED_TASK_SLEEP = 5


class ConnectionPool:
    def __init__(self, endpoint, token, pre_connect=False) -> None:
        self.logger = get_logger(__name__)
        self.endpoint = endpoint
        self.token = token
        self.pre_connect = pre_connect
        self.queue = deque(maxlen=MAX_IDLE_CONNECTION)
        self.pre_connected_queue = deque(maxlen=MAX_PRE_CONNECTED_CONNECTION)
        self.last_active = time.time()
        self.loop = asyncio.get_event_loop()
        if self.pre_connect:
            self.loop.create_task(self.pre_connect_loop_task())

    async def open_connection(self):
        if len(self.queue) > 0:
            return self.queue.popleft()
        wsock = await self.new_connection()
        await wsock.send(struct.pack('!B', NMP_UDP_PIPE_IP))
        return wsock

    async def close_connection(self, connection):
        if len(self.queue) >= MAX_IDLE_CONNECTION:
            await connection.close()
            return
        self.queue.append(connection)

    @staticmethod
    def new_ssl_context():
        context = ssl.create_default_context()
        context.options |= ssl.OP_NO_COMPRESSION
        context.options |= ssl.OP_NO_TLSv1
        context.options |= ssl.OP_NO_TLSv1_1
        if ssl.HAS_TLSv1_3:
            context.options |= ssl.OP_NO_TLSv1_2
        if hasattr(ssl, 'OP_ENABLE_MIDDLEBOX_COMPAT'):
            context.options |= ssl.OP_ENABLE_MIDDLEBOX_COMPAT
        return context

    async def new_connection(self, headers=None):
        if headers is not None or not self.pre_connect:
            return await self.do_connect(headers)

        self.last_active = time.time()
        if len(self.pre_connected_queue) > 0:
            wsock = self.pre_connected_queue.popleft()
            if not wsock:
                wsock = await self.do_connect(headers=None)
            self.logger.debug('hit!')
            return wsock
        else:
            self.logger.info('miss hit!')
            self.loop.create_task(self.do_pre_connect())
            return await self.do_connect(headers=None)

    async def do_pre_connect(self):
        self.logger.debug('pre connect')
        while len(self.pre_connected_queue) < MAX_PRE_CONNECTED_CONNECTION:
            self.pre_connected_queue.append(await self.do_connect(headers=None))

    async def pre_connect_loop_task(self):
        while True:
            try:
                if time.time() - self.last_active > MAX_INACTIVE_TIME:
                    self.logger.debug('close timeout connection')
                    while len(self.pre_connected_queue) > 0:
                        wsock = self.pre_connected_queue.popleft()
                        if wsock:
                            await wsock.close()
                await self.do_pre_connect()
            except Exception as e:
                self.logger.exception(e)
            await asyncio.sleep(PRE_CONNECTED_TASK_SLEEP)

    async def do_connect(self, headers):
        try:
            dummy = secrets.token_hex(randint(1, 4))
            uri = f'{self.endpoint}/{self.token}/{dummy}'
            if self.endpoint.startswith('wss://'):
                return await websockets.connect(uri,
                                                extra_headers=headers,
                                                max_queue=WEBSOCKETS_MAX_QUEUE,
                                                ping_interval=None,
                                                compression=None, ssl=ConnectionPool.new_ssl_context(),
                                                server_hostname=self.endpoint.split('/')[2])
            else:
                return await websockets.connect(uri,
                                                extra_headers=headers,
                                                ping_interval=None,
                                                max_queue=WEBSOCKETS_MAX_QUEUE,
                                                compression=None)
        except Exception as e:
            self.logger.exception(e)
            return None
