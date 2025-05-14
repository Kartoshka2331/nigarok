import struct
from asyncio import StreamReader

PING = 1
PONG = 2
NEW_CONNECTION = 3
DATA = 4
CLOSE = 5


def pack_message(message_type: int, connection_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("!BII", message_type, connection_id, len(payload)) + payload

async def unpack_message(reader: StreamReader) -> tuple[int, int, bytes]:
    header = await reader.readexactly(9)
    message_type, connection_id, length = struct.unpack("!BII", header)
    payload = await reader.readexactly(length)

    return message_type, connection_id, payload
