from _typeshed import Incomplete

class BinanceAPIException(Exception):
    code: int
    message: Incomplete
    status_code: Incomplete
    response: Incomplete
    request: Incomplete
    def __init__(self, response) -> None: ...

class BinanceRequestException(Exception):
    message: Incomplete
    def __init__(self, message) -> None: ...

class BinanceOrderException(Exception):
    code: Incomplete
    message: Incomplete
    def __init__(self, code, message) -> None: ...

class BinanceOrderMinAmountException(BinanceOrderException):
    def __init__(self, value) -> None: ...

class BinanceOrderMinPriceException(BinanceOrderException):
    def __init__(self, value) -> None: ...

class BinanceOrderMinTotalException(BinanceOrderException):
    def __init__(self, value) -> None: ...

class BinanceOrderUnknownSymbolException(BinanceOrderException):
    def __init__(self, value) -> None: ...

class BinanceOrderInactiveSymbolException(BinanceOrderException):
    def __init__(self, value) -> None: ...

class BinanceWithdrawException(Exception):
    message: Incomplete
    def __init__(self, message) -> None: ...

class UnknownExchange(Exception): ...
class AlreadyStoppedError(Exception): ...
