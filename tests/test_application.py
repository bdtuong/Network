from pathlib import Path
import hashlib
import json
import os
import socket
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.exceptions import InvalidTag
from network_app.client import Client
from network_app.server import Server
from network_app.shared import encode, receive, send
from network_app.transport import HEADER, Peer


def wait(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.02)
    raise AssertionError('Condition timed out')


@pytest.fixture
def system(tmp_path):
    server = Server(port=0)
    clients = []
    def connect(name):
        client = Client(name, port=server.port, downloads=tmp_path / name)
        clients.append(client)
        return client
    yield server, connect
    for client in clients:
        client.close()
    server.close()


def test_framing_unicode_binary_and_invalid_length():
    left, right = socket.socketpair()
    try:
        send(left, {'text': 'Xin chào 🌏', 'binary': list(b'\x00\xff')})
        assert receive(right)['text'] == 'Xin chào 🌏'
        left.sendall(struct.pack('!I', 20000))
        with pytest.raises(ValueError):
            receive(right)
    finally:
        left.close()
        right.close()


def test_directional_encryption_tamper_and_binary():
    key = os.urandom(32)
    sid = str(uuid.uuid4())
    client = Peer(sid, key, None, False)
    server = Peer(sid, key, None, True)
    nonce = (1).to_bytes(12, 'big')
    payload = b'\x00\xff hello'
    cipher = client.cipher.encrypt(nonce, payload, b'header')
    assert server.receiver.decrypt(nonce, cipher, b'header') == payload
    with pytest.raises(InvalidTag):
        server.receiver.decrypt(nonce, cipher[:-1] + bytes([cipher[-1] ^ 1]), b'header')
    assert server.cipher.encrypt(nonce, payload, b'header') != cipher


def test_auth_presence_private_global_offline_logout(system):
    server, connect = system
    alice, bob, charlie = [connect(n) for n in ('Alice', 'Bob', 'Charlie')]
    wait(lambda: len(alice.users) == 3)
    with pytest.raises(ValueError, match='already online'):
        connect('Alice')
    alice.message('hello 🌏')
    wait(lambda: any(e.get('text') == 'hello 🌏' for e in charlie.events))
    alice.message('secret', 'Bob')
    wait(lambda: any(e.get('text') == 'secret' for e in bob.events))
    assert not any(e.get('text') == 'secret' for e in charlie.events)
    alice.message('offline', 'Nobody')
    wait(lambda: any(e.get('error') == 'Recipient offline' for e in alice.events))
    charlie.close()
    wait(lambda: len(server.users) == 2)
    assert server.users['Alice']['udp_port'] > 0


@pytest.mark.parametrize('size', [0, 37, 65539, 10 * 1024 * 1024 + 31])
def test_files_and_concurrent_chat(system, tmp_path, size):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    path = tmp_path / 'sample.bin'
    path.write_bytes(os.urandom(size))
    transfer = alice.send_file(path, 'Bob')
    alice.message('while transferring')
    wait(lambda: any(e.get('text') == 'while transferring' for e in bob.events))
    result = wait(lambda: next((e for e in bob.events if e.get('id') == transfer and e['type'] == 'FILE_RESULT'), None), 100)
    assert result['success']
    assert hashlib.sha256(Path(result['path']).read_bytes()).digest() == hashlib.sha256(path.read_bytes()).digest()
    wait(lambda: any(e['type'] == 'FILE_RESULT' and e.get('id') == transfer for e in alice.events))
    assert not list((tmp_path / 'Bob').glob('*.part'))


def test_twenty_concurrent_clients(system):
    server, connect = system
    with ThreadPoolExecutor(max_workers=20) as pool:
        clients = list(pool.map(connect, [f'user{i}' for i in range(20)]))
    wait(lambda: all(len(c.users) == 20 for c in clients), 20)
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda c: c.message(c.username), clients))
    wait(lambda: all(sum(e['type'] == 'GLOBAL_MESSAGE' for e in c.events) == 20 for c in clients), 20)


def test_replay_and_malformed_packets(system):
    server, connect = system
    alice = connect('Alice')
    wait(lambda: alice.transport.idle(alice.peer))
    peer = server.users['Alice']['peer']
    captured = []
    original = alice.transport._packet
    def capture(*args):
        packet, seq = original(*args)
        if args[1] == 0:
            captured.append(packet)
        return packet, seq
    alice.transport._packet = capture
    alice.message('once')
    wait(lambda: any(e.get('text') == 'once' for e in alice.events))
    packet = next(p for p in captured if HEADER.unpack_from(p)[1] == 0)
    for _ in range(3):
        alice.transport.sock.sendto(packet, alice.peer.address)
        alice.transport.sock.sendto(b'garbage', alice.peer.address)
    time.sleep(.3)
    assert sum(e.get('text') == 'once' for e in alice.events) == 1
    assert not peer.failed


def test_corrupt_file_rejected(system):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    transfer = str(uuid.uuid4())
    alice.send({'type': 'FILE_OFFER', 'id': transfer, 'recipient': 'Bob', 'name': '../bad.txt',
                'size': 3, 'sha256': '0' * 64})
    wait(lambda: bool(bob.incoming))
    alice.send({'type': 'FILE_CHUNK', 'id': transfer, 'recipient': 'Bob', 'index': 0, 'data': 'YWJj'})
    alice.send({'type': 'FILE_COMPLETE', 'id': transfer, 'recipient': 'Bob'})
    result = wait(lambda: next((e for e in bob.events if e['type'] == 'FILE_RESULT'), None))
    assert not result['success']
    assert not list(bob.downloads.iterdir())


def test_abrupt_disconnect_and_shutdown(system):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    alice.socket.shutdown(socket.SHUT_RDWR)
    alice.socket.close()
    wait(lambda: 'Alice' not in server.users)
    bob.message('still works')
    wait(lambda: any(e.get('text') == 'still works' for e in bob.events))
    server.close()
    assert not server.thread.is_alive()
