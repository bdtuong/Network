from pathlib import Path
import socket
import pytest
from network_app.client import Client
from network_app.crypto import identity, derive, seal_password, open_password
from network_app.server import Server
from network_app.server.accounts import Accounts
from network_app.shared import send, receive
from test_application import wait


def test_account_hashes_persistence_and_wrong_password(tmp_path):
    path = tmp_path / 'users.sqlite3'
    store = Accounts(path)
    assert store.authenticate('Alice', 'alice-secret')
    assert not Accounts(path).authenticate('Alice', 'alice-secret')
    assert store.authenticate('Bob', 'alice-secret')
    with pytest.raises(ValueError, match='Incorrect'):
        store.authenticate('Alice', 'wrong-secret')
    with pytest.raises(ValueError, match='6-128'):
        store.authenticate('New', 'short')
    assert b'alice-secret' not in path.read_bytes()
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute('SELECT salt, password_hash FROM accounts').fetchall()
    assert rows[0][0] != rows[1][0]
    assert rows[0][1] != rows[1][1]


def test_password_cipher_bound_to_handshake_and_identity():
    a, ap = identity()
    b, bp = identity()
    key = derive(a, bp)
    challenge = 'ab' * 12
    encrypted = seal_password(key, challenge, 'Alice', 5000, 'alice-secret')
    assert b'alice-secret' not in bytes.fromhex(encrypted)
    assert open_password(derive(b, ap), challenge, 'Alice', 5000, encrypted) == 'alice-secret'
    for nonce, name, port in [('cd' * 12, 'Alice', 5000),
                               (challenge, 'Bob', 5000), (challenge, 'Alice', 5001)]:
        with pytest.raises(ValueError, match='Invalid encrypted login'):
            open_password(key, nonce, name, port, encrypted)


def test_login_after_restart_requires_original_password(tmp_path):
    path = tmp_path / 'accounts.sqlite3'
    server = Server(port=0, accounts=path)
    client = Client('Alice', port=server.port, downloads=tmp_path,
                    password='alice-secret')
    client.close()
    server.close()
    server = Server(port=0, accounts=path)
    try:
        with pytest.raises(ValueError, match='Incorrect'):
            Client('Alice', port=server.port, downloads=tmp_path, password='wrong-secret')
        assert not server.users
        client = Client('Alice', port=server.port, downloads=tmp_path,
                        password='alice-secret')
        try:
            client.message('password login works')
            wait(lambda: any(e.get('text') == 'password login works' for e in client.events))
        finally:
            client.close()
    finally:
        server.close()


def test_plaintext_and_replayed_auth_are_rejected(tmp_path):
    server = Server(port=0, accounts=tmp_path / 'accounts.sqlite3')
    private, public = identity()
    request = None
    try:
        for attempt in range(3):
            with socket.create_connection(('127.0.0.1', server.port), timeout=5) as sock:
                hello = receive(sock)
                if attempt < 2:
                    request = {'type': 'AUTH', 'username': 'Alice', 'udp_port': 5000,
                               'public_key': public,
                               'password': 'plain-secret' if attempt == 0 else seal_password(
                                   derive(private, hello['public_key']), hello['challenge'],
                                   'Alice', 5000, 'alice-secret')}
                send(sock, request)
                response = receive(sock)
                assert response['type'] == ('AUTH_OK' if attempt == 1 else 'AUTH_ERROR')
    finally:
        server.close()


@pytest.mark.parametrize('same_password', [True, False])
@pytest.mark.parametrize('separate_stores', [True, False])
def test_concurrent_registration_keeps_one_account(tmp_path, monkeypatch,
                                                   same_password, separate_stores):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    import sqlite3
    import threading
    from network_app.server import accounts

    path = tmp_path / 'race.sqlite3'
    first = Accounts(path)
    second = Accounts(path) if separate_stores else first
    rendezvous = threading.Barrier(2)
    local = threading.local()
    original = accounts._hash_password

    def synchronized_hash(password, salt):
        if not getattr(local, 'started', False):
            local.started = True
            rendezvous.wait(timeout=5)
        return original(password, salt)

    passwords = ['first-secret', 'first-secret' if same_password else 'second-secret']

    def register(store, password):
        try:
            return store.authenticate('Alice', password)
        except ValueError:
            return 'rejected'

    with monkeypatch.context() as patch:
        patch.setattr(accounts, '_hash_password', synchronized_hash)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(register, store, password)
                       for store, password in zip([first, second], passwords)]
            results = [future.result(timeout=10) for future in futures]
    assert sum(result is True for result in results) == 1
    if same_password:
        assert sum(result is False for result in results) == 1
    else:
        assert results.count('rejected') == 1
    winner = passwords[results.index(True)]
    assert not Accounts(path).authenticate('Alice', winner)
    if not same_password:
        with pytest.raises(ValueError, match='Incorrect'):
            Accounts(path).authenticate('Alice', passwords[1 - results.index(True)])
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 1


def test_existing_password_checks_hash_concurrently(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from network_app.server import accounts

    store = Accounts(tmp_path / 'users.sqlite3')
    store.authenticate('Alice', 'alice-secret')
    store.authenticate('Bob', 'bob-secret')
    original = accounts._hash_password
    rendezvous = threading.Barrier(2)

    def synchronized_hash(password, salt):
        rendezvous.wait(timeout=5)
        return original(password, salt)

    monkeypatch.setattr(accounts, '_hash_password', synchronized_hash)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.authenticate, name, password)
                   for name, password in [('Alice', 'alice-secret'), ('Bob', 'bob-secret')]]
        assert all(future.result(timeout=10) is False for future in futures)


def test_default_authentication_waits_longer_than_old_five_second_limit(tmp_path, monkeypatch):
    import time
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    original = server.accounts.authenticate

    def slow_authenticate(username, password):
        time.sleep(5.2)
        return original(username, password)

    monkeypatch.setattr(server.accounts, 'authenticate', slow_authenticate)
    try:
        client = Client('Slow', port=server.port, downloads=tmp_path, password='slow-secret')
        try:
            assert client.running
            client.message('slow auth succeeded')
            wait(lambda: any(e.get('text') == 'slow auth succeeded' for e in client.events))
        finally:
            client.close()
    finally:
        server.close()


def test_auth_timeout_is_separate_and_still_bounded(tmp_path, monkeypatch):
    import time
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    original = server.accounts.authenticate

    def slow_authenticate(username, password):
        time.sleep(.4)
        return original(username, password)

    monkeypatch.setattr(server.accounts, 'authenticate', slow_authenticate)
    try:
        client = Client('Slow', port=server.port, downloads=tmp_path, password='slow-secret',
                        connect_timeout=.2, auth_timeout=3)
        client.close()
        with pytest.raises(TimeoutError):
            Client('Timeout', port=server.port, downloads=tmp_path, password='slow-secret',
                   connect_timeout=3, auth_timeout=.1)
    finally:
        server.close()
