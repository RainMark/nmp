#!/bin/env python3

import sys
import logging
import argparse

from nmp.server import NmpServer
from nmp.sockv5 import SockV5Server
from nmp.apiserver import NmpApi
from nmp.encode import EncoderPool

def server_handle(args):
    nmp = NmpServer(3389)
    api = NmpApi(nmp)
    ep = EncoderPool('127.0.0.1:3306/v1')
    ep.generate(count=1024, lazy=True)
    logging.info('start api server...')
    api.set_encoder_pool(ep)
    api.run(port=3306)

    logging.info('start server...')
    nmp.bind_and_listen(listen_max=20)
    nmp.accept_and_dispatch()

def socks_handle(args):
    logging.info('start socks...')
    sockv5 = SockV5Server(1234)
    sockv5.bind_and_listen(listen_max=20)
    # sockv5.accept_and_dispatch('129.226.184.17', 3389)
    sockv5.accept_and_dispatch('127.0.0.1', 3389)

def main():
    fmt = '%(asctime)s:%(levelname)s:%(funcName)s:%(lineno)d:%(message)s'
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('server', 'socks'))
    args = parser.parse_args()

    if 'server' == args.action:
        server_handle(args)
    elif 'socks' == args.action:
        socks_handle(args)
    else:
        args.print_help()

if '__main__' == __name__:
    main()
