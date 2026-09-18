#!/bin/env python3

import asyncio
import argparse
import os
import sys
from pathlib import Path
from nmp.log import get_logger
from nmp.runtime import add_stop_signal
from nmp.server import NmpServer
from nmp.sockv5 import SockV5Server
from nmp.transparent import TransparentServer

logger = get_logger(__name__)


class Config:
    def __init__(self):
        self.uvloop = False
        self.server = None
        self.host = '127.0.0.1'
        self.port = 8888
        # for sockv5
        self.endpoint = None
        self.token = None
        self.pre_connect = False
        # for nmp server
        self.conf = os.path.join(Path.home(), '.NMP_TOKEN')

    def from_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--server', dest='server',
                            help='server type: nmp/sockv5')
        parser.add_argument('--host', dest='host',
                            help='bind host (default: 127.0.0.1)')
        parser.add_argument('--port', dest='port',
                            help='bind port (default: 8888)')
        parser.add_argument('--endpoint', dest='endpoint',
                            help='nmp server endpoint (wss://example.com)')
        parser.add_argument('--token', dest='token', help='nmp server token')
        parser.add_argument('--uvloop', dest='uvloop', help='use uvloop')
        parser.add_argument('--pre_connect', dest='pre_connect', help='pre connect')
        args = parser.parse_args()
        if args.server:
            self.server = args.server
        if args.host:
            self.host = args.host
        if args.port:
            self.port = int(args.port)
        if args.endpoint:
            self.endpoint = args.endpoint
        if args.token:
            self.token = args.token
        if args.uvloop:
            self.uvloop = True
        if args.pre_connect:
            self.pre_connect = True

        if not self.validate():
            parser.print_help()
            sys.exit(-1)

    def validate(self):
        if not self.server:
            return False
        if self.server == 'sockv5' or self.server == 'tproxy':
            return self.endpoint and self.token
        return True


async def start_nmp_server(config):
    logger.info(f'start nmp server: ({config.host}:{config.port})')
    add_stop_signal()
    nmp = NmpServer(config)
    await nmp.start_server()


async def start_sockv5_server(config):
    logger.info(f'start sockv5 server: ({config.host}:{config.port})')
    add_stop_signal()
    sockv5 = SockV5Server(config)
    await sockv5.start_server()


async def start_transparent_server(config):
    logger.info(f'start transparent server: ({config.host}:{config.port})')
    add_stop_signal()
    transparent = TransparentServer(config)
    await transparent.start_server()


def main():
    config = Config()
    config.from_args()
    if config.uvloop:
        import uvloop
        uvloop.install()
    try:
        import ssl
        logger.info(ssl.OPENSSL_VERSION)
        if config.server == 'sockv5':
            asyncio.run(start_sockv5_server(config))
        elif config.server == 'tproxy':
            asyncio.run(start_transparent_server(config))
        else:
            asyncio.run(start_nmp_server(config))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('stopped')
    except Exception as e:
        logger.exception(e)
    finally:
        logger.info('stoped')


if '__main__' == __name__:
    main()
