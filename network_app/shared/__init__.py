import json
import struct

MAX_FRAME = 16384
CONNECT_TIMEOUT = 5
AUTH_TIMEOUT = 30


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def receive(sock):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            block = sock.recv(size - len(data))
            if not block:
                raise EOFError('Connection closed')
            data.extend(block)
        return bytes(data)
    size = struct.unpack('!I', exact(4))[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError('Invalid frame length')
    return json.loads(exact(size))


def send(sock, value):
    data = encode(value)
    if len(data) > MAX_FRAME:
        raise ValueError('Frame too large')
    sock.sendall(struct.pack('!I', len(data)) + data)
