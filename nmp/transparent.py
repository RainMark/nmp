#!/bin/env python3

'''
1. Capabilities
   # cap_net_admin for IP_TRANSPARENT, cap_net_bind_service for bind ports less than 1024.
   $ sudo setcap 'cap_net_admin+eip cap_net_bind_service=+eip' /usr/bin/python3.7

2. Route
   $ ip rule add fwmark 1 lookup 100
   $ ip route add local default dev lo table 100

3. Sysctl
   $ sysctl -w net.ipv4.ip_forward=1
   $ sysctl -w net.ipv4.conf.default.rp_filter=0
   $ sysctl -w net.ipv4.conf.all.rp_filter=0
   $ sysctl -w net.ipv4.conf.wlp2s0.rp_filter=0 # Change wlp2s0 to your interface

4. Iptables
   $ iptables -t mangle -N DIVERT
   $ iptables -t mangle -A DIVERT -j MARK --set-mark 1
   $ iptables -t mangle -A DIVERT -j ACCEPT

   $ iptables -t mangle -A PREROUTING -p udp -m socket -j DIVERT
   $ iptables -t mangle -A PREROUTING -p tcp -m socket -j DIVERT
   $ iptables -t mangle -A PREROUTING -p udp -s 192.168.101.45 -j TPROXY --on-port 1111 --tproxy-mark 0x1/0x1
   $ iptables -t mangle -A PREROUTING -p tcp -s 192.168.101.45 -j TPROXY --on-port 1111 --tproxy-mark 0x1/0x1
   # Maybe your need change -s/--on-port rule.
'''

import asyncio
import socket
import struct
from nmp.connection import ConnectionPool
from nmp.log import get_logger
from nmp.pipe import Pipe, SocketStream
from nmp.proto import NMP_CONNECT_OK, NMP_TCP_PIPE_IP

MAX_MSG_BUF_SIZE = 2 ** 16
MAX_IDLE_CONNECTION = 2 ** 10

# TPROXY
IP_TRANSPARENT = 19
IP_ORIGDSTADDR = 20
IP_RECVORIGDSTADDR = IP_ORIGDSTADDR


class DatagramHandler:
    def __init__(self, pool: ConnectionPool):
        self.logger = get_logger(__name__)
        self.pool = pool

    @staticmethod
    def new(pool: ConnectionPool):
        return DatagramHandler(pool)

    def get_dst_addr(self, anc):
        for cmsg_level, cmsg_type, cmsg_data in anc:
            if cmsg_level == socket.SOL_IP and cmsg_type == IP_ORIGDSTADDR:
                family, port = struct.unpack('=HH', cmsg_data[0:4])
                port = socket.htons(port)
                if family != socket.AF_INET:
                    self.logger.error(f'unsupported socket type {family}')
                    return None
                ip = socket.inet_ntop(family, cmsg_data[4:8])
                return ip, port
        self.logger.error('fail to get datagram dst addr')
        return None

    async def received(self, data, anc, from_addr,):
        to_addr = self.get_dst_addr(anc)
        self.logger.debug(from_addr)
        self.logger.debug(to_addr)
        self.logger.debug(data)
        if not to_addr:
            return
        reply = await self.forward_and_recv(data, to_addr)
        if reply:
            await self.reply(reply, to_addr, from_addr)

    async def forward_and_recv(self, data, addr):
        wsock = await self.pool.open_connection()
        if not wsock:
            return
        self.logger.debug(addr)
        msg = bytearray(socket.inet_aton(addr[0]))
        msg.extend(struct.pack('!H', addr[1]))
        msg.extend(data)
        self.logger.debug(msg)
        await wsock.send(msg)
        reply = await wsock.recv()
        await self.pool.close_connection(wsock)
        statu = struct.unpack('!B', reply[:1])[0]
        if statu != NMP_CONNECT_OK:
            self.logger.warning(
                f'forward message failed, addr={addr}, error={statu}')
            return None

        return reply[1:]

    async def reply(self, data, from_addr, to_addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
        self.logger.debug(from_addr)
        self.logger.debug(to_addr)
        self.logger.debug(data)
        sock.bind(from_addr)
        sock.sendto(data, to_addr)
        sock.close()


class StreamHandler:
    def __init__(self, sock: SocketStream, pool: ConnectionPool):
        self.logger = get_logger(__name__)
        self.sock = sock
        self.pool = pool

    async def handle(self):
        wsock = await self.open_remote_connection()
        if not wsock:
            await self.sock.close()
            return

        pipe = Pipe(self.sock, wsock)
        await pipe.pipe()

    def get_dst_addr(self):
        return self.sock.writer.get_extra_info('sockname')

    async def open_remote_connection(self):
        host, port = self.get_dst_addr()
        self.logger.debug(host)
        self.logger.debug(port)
        req = bytearray(struct.pack("!BH", NMP_TCP_PIPE_IP, port))
        req.extend(host.encode())
        self.logger.debug(req)
        wsock = await self.pool.new_connection()
        if not wsock:
            return None

        await wsock.send(req)
        reply = await wsock.recv()
        code = struct.unpack('!B', reply[:1])[0]
        if code != NMP_CONNECT_OK:
            self.logger.warning(f'connect refused, error code {code}')
            await wsock.close()
            return None

        return wsock


class TransparentServer:
    def __init__(self, config):
        self.logger = get_logger(__name__)
        self.config = config
        self.stream_sock = None
        self.datagram_sock = None
        self.pool = ConnectionPool(config.endpoint, config.token)

    def new_datagram_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
        sock.setsockopt(socket.SOL_IP, IP_RECVORIGDSTADDR, 1)
        sock.bind((self.config.host, self.config.port))
        return sock

    def datagram_handler(self):
        data, anc, flags, from_addr = self.datagram_sock.recvmsg(
            MAX_MSG_BUF_SIZE, socket.CMSG_SPACE(24))
        self.logger.debug(f'recieved anc: {anc}')
        asyncio.create_task(DatagramHandler
                            .new(self.pool)
                            .received(data, anc, from_addr))

    async def start_datagram_server(self):
        self.datagram_sock = self.new_datagram_socket()
        loop = asyncio.get_running_loop()
        loop.add_reader(self.datagram_sock, self.datagram_handler)
        self.logger.debug('datagram server started')
        await asyncio.Future()

    def new_stream_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
        sock.bind((self.config.host, self.config.port))
        sock.listen(MAX_BACKLOG)
        return sock

    async def stream_handler(self, r, w):
        self.logger.debug(r)
        self.logger.debug(w)
        handler = StreamHandler(SocketStream(r, w), self.pool)
        try:
            await handler.handle()
        except Exception as e:
            self.logger.exception(e)
            if not handler.sock.closed:
                await handler.sock.close()

    async def start_stream_server(self):
        self.stream_sock = self.new_stream_socket()
        server = await asyncio.start_server(self.stream_handler, sock=self.stream_sock)
        self.logger.debug(f'stream server started {server}')
        await asyncio.Future()

    async def start_server(self):
        await asyncio.gather(asyncio.create_task(self.start_stream_server()),
                             asyncio.create_task(self.start_datagram_server()))

    def close(self):
        if self.stream_sock:
            self.stream_sock.close()
        if self.datagram_sock:
            self.datagram_sock.close()
