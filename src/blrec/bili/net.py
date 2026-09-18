import asyncio
import socket
from typing import Dict

import aiohttp
import requests

from .network_settings import ipv4_only

__all__ = ('get_connector', 'close_connector', 'timeout')

# Startup-only: callers must set BLREC_IPV4 before importing the network stack.
USE_IPV4_ONLY = ipv4_only()

if not USE_IPV4_ONLY:
    family = 0
else:
    requests.packages.urllib3.util.connection.HAS_IPV6 = False  # type: ignore
    family = socket.AF_INET

timeout = aiohttp.ClientTimeout(total=10)
_connectors: Dict[asyncio.AbstractEventLoop, aiohttp.TCPConnector] = {}


def get_connector() -> aiohttp.TCPConnector:
    """Share one pool per running loop; Application owns its shutdown."""
    loop = asyncio.get_running_loop()
    connector = _connectors.get(loop)
    if connector is None or connector.closed:
        connector = aiohttp.TCPConnector(family=family, limit=200)
        _connectors[loop] = connector
    return connector


async def close_connector() -> None:
    """Close this loop's pool after its users stop, including standalone users."""
    connector = _connectors.pop(asyncio.get_running_loop(), None)
    if connector is not None:
        await connector.close()
