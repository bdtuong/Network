from pathlib import Path
import os
import socket
import threading
import time
from network_app.client import Client
from network_app.server import Server
from test_application import wait


class ImpairedSocket:
    """Deterministic outbound loss, duplication, reordering, and latency."""
    def __init__(self, sock):
        self.sock = sock
        self.count = 0
        self.held = None
        self.lock = threading.Lock()

    def sendto(self, data, address):
        with self.lock:
            self.count += 1
            if self.count % 11 == 0:
                return len(data)
            time.sleep(.001)
            if self.count % 7 == 0 and self.held is None:
                self.held = data, address
                return len(data)
            self.sock.sendto(data, address)
            if self.held:
                self.sock.sendto(*self.held)
                self.held = None
            if self.count % 5 == 0:
                self.sock.sendto(data, address)
            return len(data)

    def __getattr__(self, name):
        return getattr(self.sock, name)


def test_file_under_loss_duplication_reordering_latency(tmp_path):
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    alice = Client('Alice', password='test-password', port=server.port, downloads=tmp_path / 'alice')
    bob = Client('Bob', password='test-password', port=server.port, downloads=tmp_path / 'bob')
    try:
        alice.transport.sock = ImpairedSocket(alice.transport.sock)
        server.transport.sock = ImpairedSocket(server.transport.sock)
        path = tmp_path / 'loss.bin'
        path.write_bytes(os.urandom(80000))
        transfer = alice.send_file(path, 'Bob')
        alice.message('chat survives loss')
        result = wait(lambda: next((e for e in bob.events if e['type'] == 'FILE_RESULT' and e['id'] == transfer), None), 60)
        assert result['success']
        assert Path(result['path']).read_bytes() == path.read_bytes()
        assert alice.peer.retransmissions > 0
        wait(lambda: any(e.get('text') == 'chat survives loss' for e in bob.events))
    finally:
        alice.close()
        bob.close()
        server.close()
