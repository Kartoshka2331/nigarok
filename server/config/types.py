from typing import TypedDict, List


class TimeoutConfig(TypedDict):
    auth: float
    read: float
    write: float
    connection: float

class LimitConfig(TypedDict):
    max_auth_size: int
    max_data_size: int
    queue_size: int

class LoggingConfig(TypedDict):
    level: str
    file: str

class SecurityConfig(TypedDict):
    allow_test_mode: bool

class AccountConfig(TypedDict):
    login: str
    password: str

class Config(TypedDict):
    host: str
    port: int
    allowed_port_range: List[int]
    accounts: List[AccountConfig]
    timeouts: TimeoutConfig
    limits: LimitConfig
    logging: LoggingConfig
    security: SecurityConfig
