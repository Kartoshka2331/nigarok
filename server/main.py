import asyncio
import logging

from config.config import load_config
from logger.logger import setup_logging
from server.server import start_server, shutdown as server_shutdown


async def main():
    config = load_config()
    setup_logging(config["logging"])

    shutdown_event = asyncio.Event()
    clients_lock = asyncio.Lock()
    clients = {}
    used_ports = set()

    server_task = asyncio.create_task(start_server(config, shutdown_event, clients_lock, clients, used_ports))

    try:
        await server_task
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Received KeyboardInterrupt, shutting down.", extra={"client_ip": "server"})
        shutdown_event.set()
    finally:
        await server_shutdown(asyncio.get_running_loop())
        logging.getLogger(__name__).debug("Shutdown complete. Exiting.", extra={"client_ip": "server"})


if __name__ == "__main__":
    asyncio.run(main())
