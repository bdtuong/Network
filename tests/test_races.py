import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import socket
import threading
import time
import uuid

from network_app.client import Client
from network_app.server import Server
from network_app.shared import encode
from test_application import system, wait


class PausedStream:
    def __init__(self, stream, operation):
        self.stream = stream
        self.operation = operation
        self.entered = threading.Event()
        self.release = threading.Event()
        self.writing = False
        self.closed_during_write = False
        self.writes = 0

    def _pause(self, operation):
        if self.operation == operation:
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError('Test did not release file operation')

    def write(self, data):
        self.writing = True
        try:
            self._pause('write')
            self.writes += 1
            return self.stream.write(data)
        finally:
            self.writing = False

    def close(self):
        self.closed_during_write |= self.writing
        self._pause('close')
        return self.stream.close()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def offered_file(client, operation):
    transfer = str(uuid.uuid4())
    offer = {'type': 'FILE_OFFER', 'id': transfer, 'sender': 'Alice',
             'recipient': client.username, 'name': 'race.bin', 'size': 3,
             'sha256': hashlib.sha256(b'abc').hexdigest()}
    client._receive(client.peer, encode(offer))
    key = ('Alice', transfer)
    state = client.incoming[key]
    state['stream'] = PausedStream(state['stream'], operation)
    chunk = {'type': 'FILE_CHUNK', 'id': transfer, 'sender': 'Alice',
             'recipient': client.username, 'index': 0,
             'data': base64.b64encode(b'abc').decode()}
    return key, state, chunk


def test_expiry_skips_active_write_and_rechecks_fresh_timestamp(system):
    server, connect = system
    bob = connect('Bob')
    key, state, chunk = offered_file(bob, 'write')
    stream = state['stream']
    started = threading.Event()

    def expire():
        started.set()
        bob._expire_incoming()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(bob._receive, bob.peer, encode(chunk))
        try:
            assert stream.entered.wait(3)
            expiry = pool.submit(expire)
            assert started.wait(3)
            expiry.result(timeout=3)
            assert not stream.closed
            assert key in bob.incoming
        finally:
            stream.release.set()
        writing.result(timeout=3)
        expiry.result(timeout=3)
    assert not stream.closed_during_write
    assert not state['closed']
    assert state['received'] == 3
    complete = dict(chunk, type='FILE_COMPLETE')
    bob._receive(bob.peer, encode(complete))
    assert state['closed']
    assert state['path'].read_bytes() == b'abc'
    assert key not in bob.incoming


def test_late_chunk_waits_for_expiry_then_ignores_closed_transfer(system):
    server, connect = system
    bob = connect('Bob')
    key, state, chunk = offered_file(bob, 'close')
    stream = state['stream']
    with state['lock']:
        state['updated'] = time.monotonic() - 46
    started = threading.Event()

    def receive():
        started.set()
        bob._receive(bob.peer, encode(chunk))

    with ThreadPoolExecutor(max_workers=2) as pool:
        expiry = pool.submit(bob._expire_incoming)
        try:
            assert stream.entered.wait(3)
            late = pool.submit(receive)
            assert started.wait(3)
            time.sleep(.05)
            assert not late.done()
        finally:
            stream.release.set()
        expiry.result(timeout=3)
        late.result(timeout=3)
    assert stream.writes == 0
    assert key not in bob.incoming
    assert not state['temp'].exists()
    assert sum(e.get('id') == key[1] and e.get('error') == 'Incoming file expired'
               for e in bob.events) == 1


def test_disconnect_waits_for_write_before_discarding_partial_file(system):
    server, connect = system
    bob = connect('Bob')
    key, state, chunk = offered_file(bob, 'write')
    stream = state['stream']
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(bob._receive, bob.peer, encode(chunk))
        try:
            assert stream.entered.wait(3)
            closing = pool.submit(bob.close)
            assert bob._closing.wait(3)
            assert not stream.closed
        finally:
            stream.release.set()
        writing.result(timeout=3)
        closing.result(timeout=5)
    assert not stream.closed_during_write
    assert state['closed']
    assert key not in bob.incoming
    assert not state['temp'].exists()


def test_ack_update_and_transfer_cleanup_are_atomic(system):
    server, connect = system
    alice = connect('Alice')
    transfer = str(uuid.uuid4())
    entered, release, cleanup_started = threading.Event(), threading.Event(), threading.Event()

    class PausedAcks(dict):
        def get(self, key, default=None):
            if key == transfer and not release.is_set():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release ACK lookup')
            return super().get(key, default)

    with alice.lock:
        alice.file_acks = PausedAcks({transfer: set()})
        alice.outgoing[transfer] = threading.Event()
    ack = encode({'type': 'FILE_ACK', 'id': transfer, 'index': 0})

    def cleanup():
        cleanup_started.set()
        alice._forget_upload(transfer)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receiving = pool.submit(alice._receive, alice.peer, ack)
        try:
            assert entered.wait(3)
            forgetting = pool.submit(cleanup)
            assert cleanup_started.wait(3)
            time.sleep(.05)
            assert not forgetting.done()
        finally:
            release.set()
        receiving.result(timeout=3)
        forgetting.result(timeout=3)
    alice._receive(alice.peer, ack)
    assert transfer not in alice.file_acks
    assert transfer not in alice.outgoing


def test_connection_accepted_during_shutdown_is_closed_without_starting_session(tmp_path, monkeypatch):
    accepted, release = threading.Event(), threading.Event()
    sockets, listeners = [], []
    original_accept = socket.socket.accept

    def paused_accept(listener):
        conn, addr = original_accept(listener)
        if listeners and listener is listeners[0]:
            sockets.append(conn)
            accepted.set()
            if not release.wait(5):
                conn.close()
                raise TimeoutError('Test did not release accept')
        return conn, addr

    monkeypatch.setattr(socket.socket, 'accept', paused_accept)
    server = Server(port=0, accounts=tmp_path / 'accounts.sqlite3')
    listeners.append(server.sock)
    conn = socket.create_connection(('127.0.0.1', server.port), timeout=3)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                assert accepted.wait(3)
                closing = pool.submit(server.close)
                wait(lambda: not server.running, 3)
            finally:
                release.set()
            closing.result(timeout=5)
        try:
            assert conn.recv(1) == b''
        except ConnectionResetError:
            pass
        assert sockets[0].fileno() == -1
        assert not server.threads
        assert not server.connections
        assert not server.users
        assert not server.thread.is_alive()
    finally:
        release.set()
        conn.close()
        server.close()


def test_auth_finishing_after_shutdown_cannot_publish_new_session(tmp_path, monkeypatch):
    server = Server(port=0, accounts=tmp_path / 'accounts.sqlite3')
    port = server.port
    entered, release = threading.Event(), threading.Event()
    original_auth = server.accounts.authenticate
    additions = []
    original_add = server.transport.add

    def paused_auth(username, password):
        entered.set()
        if not release.wait(5):
            raise TimeoutError('Test did not release authentication')
        return original_auth(username, password)

    def record_add(*args):
        additions.append(args[0])
        return original_add(*args)

    def connect():
        try:
            client = Client('Alice', port=port, downloads=tmp_path, password='alice-secret')
        except (OSError, EOFError, ValueError):
            return False
        client.close()
        return True

    monkeypatch.setattr(server.accounts, 'authenticate', paused_auth)
    monkeypatch.setattr(server.transport, 'add', record_add)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            connecting = pool.submit(connect)
            try:
                assert entered.wait(3)
                closing = pool.submit(server.close)
                wait(lambda: not server.running, 3)
            finally:
                release.set()
            assert not connecting.result(timeout=5)
            closing.result(timeout=5)
        assert not additions
        assert not server.users
        assert not server.connections
        assert all(not thread.is_alive() for thread in server.threads)
    finally:
        release.set()
        server.close()
