import time
from network_app.client import Client
from network_app.server import Server
from network_app.shared import encode
from test_application import wait


def test_session_inactivity_expiry(tmp_path):
    server = Server(port=0, timeout=.3, accounts=tmp_path / 'users.sqlite3')
    client = Client('Idle', password='test-password', port=server.port, downloads=tmp_path)
    try:
        client.running = False
        wait(lambda: not server.users, 4)
    finally:
        client.close()
        server.close()


def test_retry_exhaustion_signals_failure_and_cleans_queue(tmp_path):
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    client = Client('Retry', password='test-password', port=server.port, downloads=tmp_path)
    try:
        wait(lambda: client.transport.idle(client.peer))
        with client.transport.lock:
            client.peer.pending[999] = (b'ignored', time.monotonic() - 10, 12)
        wait(lambda: client.peer.failed)
        wait(lambda: any('timed out' in e.get('error', '') for e in client.events))
        assert not client.peer.pending
        assert not client.peer.backlog
    finally:
        client.close()
        server.close()


def test_window_bounds_and_oversized_send(tmp_path):
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    client = Client('Window', password='test-password', port=server.port, downloads=tmp_path)
    try:
        import pytest
        with pytest.raises(ValueError):
            client.transport.send(client.peer, b'x' * 1200)
        for i in range(50):
            client.message(f'window-{i}')
        with client.transport.lock:
            assert len(client.peer.pending) <= int(client.peer.cwnd) <= 32
        wait(lambda: sum(e.get('text', '').startswith('window-') for e in client.events) == 50)
    finally:
        client.close()
        server.close()
