from .exceptions import *
import logging
import websockets
from _typeshed import Incomplete

__logger__: logging.getLogger
logger = __logger__
connect: websockets.connect

class BinanceWebSocketApiConnection:
    manager: Incomplete
    stream_id: Incomplete
    api_key: Incomplete
    api_secret: Incomplete
    ping_interval: Incomplete
    ping_timeout: Incomplete
    close_timeout: Incomplete
    channels: Incomplete
    markets: Incomplete
    symbols: Incomplete
    websocket: Incomplete
    api: Incomplete
    add_timeout: Incomplete
    timeout_disabled: bool
    def __init__(self, manager, stream_id, channels, markets, symbols) -> None: ...
    async def __aenter__(self): ...
    async def __aexit__(self, *args, **kwargs) -> None: ...
    async def close(self): ...
    async def receive(self): ...
    async def send(self, data): ...
    def raise_exceptions(self) -> None: ...
