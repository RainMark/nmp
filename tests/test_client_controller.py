import asyncio
import time

from nmp.client import ClientConfig
from nmp.client_controller import ClientController, ClientState


def wait_for_state(controller, expected, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.state == expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f'client state is {controller.state}, expected {expected}')


class FakeServer:
    def __init__(self, config, instances):
        self.config = config
        self.started = False
        self.stopped = False
        instances.append(self)

    async def start(self):
        await asyncio.sleep(0)
        self.started = True

    async def stop(self):
        await asyncio.sleep(0)
        self.stopped = True


def test_controller_can_start_stop_and_restart():
    instances = []
    controller = ClientController(
        server_factory=lambda config: FakeServer(config, instances))
    config = ClientConfig(
        endpoint='wss://nmp.example.com', token='secret', port=1080)

    for _ in range(2):
        controller.start(config)
        wait_for_state(controller, ClientState.RUNNING)
        controller.stop()
        wait_for_state(controller, ClientState.STOPPED)

    assert len(instances) == 2
    assert all(server.started and server.stopped for server in instances)
    states = [event.state for event in controller.drain_events()]
    assert states.count(ClientState.RUNNING) == 2
    assert states.count(ClientState.STOPPED) == 2


def test_controller_reports_start_failure():
    class FailingServer(FakeServer):
        async def start(self):
            raise OSError('address is already in use')

    controller = ClientController(
        server_factory=lambda config: FailingServer(config, []))
    config = ClientConfig(
        endpoint='wss://nmp.example.com', token='secret', port=1080)

    controller.start(config)
    wait_for_state(controller, ClientState.ERROR)

    errors = [event.message for event in controller.drain_events()
              if event.state == ClientState.ERROR]
    assert errors == ['address is already in use']
