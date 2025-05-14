import struct

PING = 1
PONG = 2
NEW_CONNECTION = 3
DATA = 4
CLOSE = 5


def pack_message(message_type: int, connection_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("!BII", message_type, connection_id, len(payload)) + payload

def unpack_message(sock) -> tuple[int, int, bytes]:
    header = sock.recv(9)
    if not header or len(header) < 9:
        raise ConnectionResetError("Header lost")

    message_type, connection_id, length = struct.unpack("!BII", header)
    payload = b""
    while len(payload) < length:
        data = sock.recv(length - len(payload))
        if not data:
            break
        payload += data

    return message_type, connection_id, payload
