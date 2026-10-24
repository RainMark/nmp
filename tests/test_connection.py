import asyncio
from unittest.mock import patch

from nmp.connection import ConnectionPool
from nmp.connection import MAX_PRE_CONNECTED_CONNECTION


def test_ssl_context_uses_certifi_ca_bundle():
    with patch('nmp.connection.certifi.where', return_value='/ca.pem'):
        with patch('nmp.connection.ssl.create_default_context') as create:
            ConnectionPool.new_ssl_context()

    create.assert_called_once_with(cafile='/ca.pem')


def test_connection_target_preserves_endpoint_path_and_port():
    async def run():
        pool = ConnectionPool('wss://example.com:8443/base/', 'a token')
        uri, hostname, port = pool.connection_target()

        assert uri.startswith('wss://example.com:8443/base/a%20token/')
        assert hostname == 'example.com'
        assert port == 8443

    asyncio.run(run())


def test_connection_target_defaults_ws_port():
    async def run():
        pool = ConnectionPool('ws://127.0.0.1', 'token')
        _, hostname, port = pool.connection_target()
        assert hostname == '127.0.0.1'
        assert port == 80

    asyncio.run(run())


class FakeConnection:
    closed = False

    async def close(self):
        self.closed = True


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), timeout=2)


def test_preconnect_requests_share_worker_and_close_cancels_pending_dial():
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0

        async def dial(self):
            nonlocal calls
            calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch.object(ConnectionPool, 'new_connection', dial):
            pool = ConnectionPool('wss://example.com', 'token', pre_connect=True)
            worker = pool.pre_connect_task
            try:
                await asyncio.wait_for(started.wait(), 2)
                assert await asyncio.gather(
                    *(pool.try_get_connection() for _ in range(20))) == [None] * 20
                await asyncio.sleep(0)
                assert calls == 1
            finally:
                await pool.close()
            assert cancelled.is_set()
            assert worker.done()
            assert await pool.try_get_connection() is None
            await asyncio.sleep(0)
            assert calls == 1
            assert not [t for t in asyncio.all_tasks()
                        if t is not asyncio.current_task() and not t.done()]

    asyncio.run(run())


def test_preconnect_failure_waits_and_recovers_without_caching_none():
    async def run():
        calls = 0
        connections = []

        async def dial(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            connection = FakeConnection()
            connections.append(connection)
            return connection

        with patch.object(ConnectionPool, 'new_connection', dial), \
                patch('nmp.connection.PRE_CONNECTED_TASK_SLEEP', 0.1):
            pool = ConnectionPool('wss://example.com', 'token', pre_connect=True)
            try:
                await wait_until(lambda: calls == 1)
                assert not pool.pre_connected_queue
                for _ in range(20):
                    assert await pool.try_get_connection() is None
                await asyncio.sleep(0)
                assert calls == 1
                await wait_until(lambda: len(pool.pre_connected_queue) ==
                                 MAX_PRE_CONNECTED_CONNECTION)
                assert calls == 1 + MAX_PRE_CONNECTED_CONNECTION
                assert list(pool.pre_connected_queue) == connections
            finally:
                await pool.close()
            assert all(c.closed for c in connections)

    asyncio.run(run())


def test_preconnect_consumption_wakes_refill_and_close_releases_pool():
    async def run():
        connections = []

        async def dial(self):
            connection = FakeConnection()
            connections.append(connection)
            return connection

        with patch.object(ConnectionPool, 'new_connection', dial), \
                patch('nmp.connection.PRE_CONNECTED_TASK_SLEEP', 60):
            pool = ConnectionPool('wss://example.com', 'token', pre_connect=True)
            taken = None
            try:
                await wait_until(lambda: len(connections) ==
                                 MAX_PRE_CONNECTED_CONNECTION)
                taken = await pool.try_get_connection()
                assert taken is connections[0]
                await wait_until(lambda: len(connections) ==
                                 MAX_PRE_CONNECTED_CONNECTION + 1)
                assert len(pool.pre_connected_queue) == MAX_PRE_CONNECTED_CONNECTION
            finally:
                await pool.close()
                if taken is not None:
                    await taken.close()
            assert all(c.closed for c in connections)
            assert not [t for t in asyncio.all_tasks()
                        if t is not asyncio.current_task() and not t.done()]

    asyncio.run(run())
