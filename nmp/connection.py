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
            self.loop.create_task(self.__pre_connect_loop_task())

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
        dummy = secrets.token_hex(randint(1, 4))
        uri = f'{self.endpoint}/{self.token}/{dummy}'
        ctx, name = None, None
        if self.endpoint.startswith('wss://'):
            ctx, name = ConnectionPool.new_ssl_context(
            ), self.endpoint.split('/')[2]
        try:
            return await websockets.connect(uri, extra_headers=headers,
                                            max_queue=WEBSOCKETS_MAX_QUEUE,
                                            # FIXME: add dummy data to ping/pong payload
                                            ping_interval=30, ping_timeout=None,
                                            compression=None, ssl=ctx, server_hostname=name)
        except Exception as e:
            self.logger.info(str(e))
            return None

    async def try_get_connection(self):
        if not self.pre_connect:
            return None
        self.last_active = time.time()
        if len(self.pre_connected_queue) > 0:
            wsock = self.pre_connected_queue.popleft()
            if not wsock.closed:
                self.logger.debug('hit!')
                return wsock
            self.logger.info('closed!')
            self.loop.create_task(self.__close_pre_connect())
        self.logger.info('miss hit!')
        self.loop.create_task(self.__pre_connect())
        return None

    async def __pre_connect(self):
        self.logger.debug('connect!')
        while len(self.pre_connected_queue) < MAX_PRE_CONNECTED_CONNECTION:
            self.pre_connected_queue.append(await self.new_connection())

    async def __close_pre_connect(self):
        while len(self.pre_connected_queue) > 0:
            wsock = self.pre_connected_queue.popleft()
            if wsock is not None:
                try:
                    await wsock.close()
                except Exception as e:
                    self.logger.info(str(e))

    async def __pre_connect_loop_task(self):
        while True:
            if time.time() - self.last_active > MAX_INACTIVE_TIME:
                if len(self.pre_connected_queue) > 0:
                    self.logger.info('close!')
                    await self.__close_pre_connect()
            else:
                await self.__pre_connect()
            await asyncio.sleep(PRE_CONNECTED_TASK_SLEEP)
