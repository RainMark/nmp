import asyncio
import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum

from nmp.log import get_logger, register_sensitive_value
from nmp.sockv5 import SockV5Server


logger = get_logger(__name__)


class ClientState(str, Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'


@dataclass(frozen=True)
class ClientEvent:
    state: ClientState
    message: str = ''


class ClientController:
    def __init__(self, server_factory=SockV5Server):
        self._server_factory = server_factory
        self._state = ClientState.STOPPED
        self._lock = threading.RLock()
        self._events = queue.SimpleQueue()
        self._subscribers = []
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._stop_requested = False
        self._server = None

    @property
    def state(self):
        with self._lock:
            return self._state

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def drain_events(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def start(self, config):
        config.validate()
        register_sensitive_value(config.token)
        with self._lock:
            if self._state not in (ClientState.STOPPED, ClientState.ERROR):
                raise RuntimeError(f'cannot start while client is {self._state.value}')
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError('client worker is still shutting down')
            self._stop_requested = False
            self._set_state_locked(ClientState.STARTING, '正在启动 SOCKS5 代理')
            self._thread = threading.Thread(
                target=self._worker_main,
                args=(config,),
                name='nmp-client-worker',
                daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            if self._state in (ClientState.STOPPED, ClientState.ERROR):
                return
            if self._state == ClientState.STOPPING:
                return
            self._stop_requested = True
            self._set_state_locked(ClientState.STOPPING, '正在停止 SOCKS5 代理')
            loop = self._loop
            stop_event = self._stop_event
        if loop is not None and stop_event is not None:
            loop.call_soon_threadsafe(stop_event.set)

    def shutdown(self, wait=True, timeout=10):
        self.stop()
        with self._lock:
            thread = self._thread
        if (wait and thread is not None and thread.is_alive() and
                thread is not threading.current_thread()):
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()

    def _worker_main(self, config):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        failed = False
        try:
            loop.run_until_complete(self._run(config))
        except Exception as error:
            failed = True
            logger.exception('client worker failed')
            self._set_state(ClientState.ERROR, str(error))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                logger.exception('failed to shut down async generators')
            loop.close()
            with self._lock:
                self._loop = None
                self._stop_event = None
                self._server = None
            if not failed:
                self._set_state(ClientState.STOPPED, 'SOCKS5 代理已停止')

    async def _run(self, config):
        stop_event = asyncio.Event()
        server = self._server_factory(config)
        with self._lock:
            self._stop_event = stop_event
            self._server = server
            stop_requested = self._stop_requested
        try:
            await server.start()
            logger.info(
                f'SOCKS5 proxy is listening on {config.host}:{config.port}')
            with self._lock:
                stop_requested = self._stop_requested
            if stop_requested:
                self._set_state(ClientState.STOPPING,
                                '正在停止 SOCKS5 代理')
                stop_event.set()
            else:
                self._set_state(
                    ClientState.RUNNING,
                    f'SOCKS5 代理运行于 {config.host}:{config.port}')
            await stop_event.wait()
        finally:
            await server.stop()
            logger.info('SOCKS5 proxy stopped')

    def _set_state(self, state, message=''):
        with self._lock:
            self._set_state_locked(state, message)

    def _set_state_locked(self, state, message):
        self._state = state
        event = ClientEvent(state, message)
        self._events.put(event)
        subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                logging.getLogger(__name__).exception(
                    'client state subscriber failed')
