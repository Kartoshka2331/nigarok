import asyncio
import struct
import enum
from asyncio import StreamReader
from typing import Tuple


class PackageType(enum.IntEnum):
    PING = 1
    PONG = 2
    NEW_CONNECTION = 3
    DATA = 4
    CLOSE = 5

class ProtocolError(Exception):
    pass


def pack_package(package_type: int, connection_id: int, payload: bytes = b"", max_payload_size: int = 65536) -> bytes:
    if not isinstance(package_type, int) or package_type not in PackageType:
        raise ProtocolError(f"Invalid package type: {package_type}")
    if not isinstance(connection_id, int) or connection_id < 0 or connection_id > 2**31 - 1:
        raise ProtocolError(f"Invalid connection_id: {connection_id}")
    if len(payload) > max_payload_size:
        raise ProtocolError(f"Payload too large: {len(payload)} bytes, maximum {max_payload_size}")

    return struct.pack("!BII", package_type, connection_id, len(payload)) + payload

async def unpack_package(reader: StreamReader, max_payload_size: int = 65536) -> Tuple[int, int, bytes]:
    try:
        header = await reader.readexactly(9)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError(f"Incomplete header: expected 9 bytes, received {len(error.partial)}") from error

    try:
        package_type, connection_id, length = struct.unpack("!BII", header)
    except struct.error as error:
        raise ProtocolError("Failed to unpack header") from error

    if package_type not in PackageType:
        raise ProtocolError(f"Unknown package type: {package_type}")
    if connection_id < 0 or connection_id > 2**31 - 1:
        raise ProtocolError(f"Invalid connection_id: {connection_id}")
    if length > max_payload_size:
        raise ProtocolError(f"Payload too large: {length} bytes, maximum {max_payload_size}")

    try:
        payload = await reader.readexactly(length)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError(f"Incomplete payload: expected {length} bytes, received {len(error.partial)}") from error

    return package_type, connection_id, payload
