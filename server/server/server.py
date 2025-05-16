import asyncio
import logging
from typing import Dict

from config.types import Config
from .handler import TunnelClientHandler


async def shutdown(loop: asyncio.AbstractEventLoop) -> None:
    tasks = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    await loop.shutdown_asyncgens()
    await loop.shutdown_default_executor()


async def start_server(config: Config, shutdown_event: asyncio.Event, clients_lock: asyncio.Lock, clients: Dict, used_ports: set) -> None:
    logger = logging.getLogger(__name__)

    try:
        server = await asyncio.start_server(lambda r, w: TunnelClientHandler(r, w, config, clients_lock, clients, used_ports).listen_loop(), config["host"], config["port"], reuse_address=True)
        logger.info(f"Server started on {config['host']}:{config['port']}.", extra={"client_ip": "server"})

        async with server:
            try:
                await shutdown_event.wait()
            except asyncio.CancelledError:
                pass
    except Exception as error:
        logger.critical(f"Server startup error: {error}", extra={"client_ip": "server"})
        raise
