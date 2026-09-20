import asyncio
import functools
import signal

from nmp.log import get_logger


logger = get_logger(__name__)


def add_stop_signal():
    task = asyncio.current_task()

    def shutdown(name):
        logger.info(f'stop for signal: {name}')
        logger.info(f'cancel {len(asyncio.all_tasks())} tasks')
        if task is not None:
            task.cancel()

    loop = asyncio.get_running_loop()
    for name in ('SIGINT', 'SIGTERM'):
        try:
            loop.add_signal_handler(
                getattr(signal, name),
                functools.partial(shutdown, name))
        except (NotImplementedError, RuntimeError):
            # Windows' default ProactorEventLoop doesn't implement
            # add_signal_handler. Ctrl+C still raises KeyboardInterrupt and
            # asyncio.run() cancels the server task during shutdown.
            logger.debug(f'signal handler is not supported: {name}')
