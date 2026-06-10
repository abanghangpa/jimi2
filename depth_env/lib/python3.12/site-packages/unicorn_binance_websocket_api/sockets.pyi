from .exceptions import *
import logging
from .connection import BinanceWebSocketApiConnection as BinanceWebSocketApiConnection
from _typeshed import Incomplete

__logger__: logging.getLogger
logger = __logger__

class BinanceWebSocketApiSocket:
    manager: Incomplete
    stream_id: Incomplete
    channels: Incomplete
    markets: Incomplete
    symbols: Incomplete
    output: Incomplete
    unicorn_fy: Incomplete
    exchange: Incomplete
    websocket: Incomplete
    def __init__(self, manager, stream_id, channels, markets) -> None: ...
    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
    async def start_socket(self) -> None: ...
    def raise_exceptions(self) -> None: ...
