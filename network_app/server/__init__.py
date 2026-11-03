import json
import secrets
import re
import socket
import threading
import time
import uuid
from network_app.crypto import identity, derive, open_password
from .accounts import Accounts
from network_app.shared import receive, send, encode
from network_app.transport import Transport


class Server:
    def __init__(self, host='127.0.0.1', port=9000, timeout=15,
                 accounts='data/users.sqlite3'):
        self.accounts = Accounts(accounts)
        self.lock = threading.RLock()
        self.users = {}
        self.revision = 0
        self.connections = set()
        self.threads = []
        self.timeout = timeout
        self.running = True
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(64)
        self.sock.settimeout(.2)
        self.transport = Transport((host, self.sock.getsockname()[1]), self.route, server=True)
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.sock.getsockname()[1]

    def _accept(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.lock:
                self.connections.add(conn)
            thread = threading.Thread(target=self._session, args=(conn, addr), daemon=True)
            self.threads.append(thread)
            thread.start()

    def _session(self, conn, addr):
        name = None
        try:
            conn.settimeout(5)
            private, public = identity()
            challenge = secrets.token_hex(12)
            send(conn, {'type': 'HELLO', 'version': 2,
                        'public_key': public, 'challenge': challenge})
            request = receive(conn)
            candidate = request.get('username', '')
            if request.get('type') != 'AUTH' or not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', candidate):
                raise ValueError('Invalid login')
            port = request['udp_port']
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('Invalid UDP port')
            key = derive(private, request['public_key'])
            password = open_password(key, challenge, candidate, port, request['password'])
            self.accounts.authenticate(candidate, password)
            del password
            with self.lock:
                if candidate in self.users:
                    raise ValueError('Username already online')
                sid = str(uuid.uuid4())
                peer = self.transport.add(sid, key, (addr[0], port))
                self.users[candidate] = {'peer': peer, 'socket': conn, 'ip': addr[0], 'tcp_port': addr[1], 'udp_port': port}
                name = candidate
                send(conn, {'type': 'AUTH_OK', 'session': sid, 'public_key': public, 'udp_port': self.port})
            conn.settimeout(1)
            while self.running:
                try:
                    control = receive(conn)
                    if control.get('type') == 'LOGOUT':
                        break
                    if control.get('type') != 'HEARTBEAT':
                        raise ValueError('Invalid control request')
                except socket.timeout:
                    if time.monotonic() - peer.last_seen > self.timeout:
                        break
        except (OSError, EOFError, ValueError, KeyError, TypeError) as error:
            try:
                send(conn, {'type': 'AUTH_ERROR', 'error': str(error)})
            except OSError:
                pass
        finally:
            with self.lock:
                if name:
                    user = self.users.pop(name, None)
                    if user:
                        self.transport.peers.pop(user['peer'].session, None)
                self.connections.discard(conn)
            conn.close()
            self.presence()

    def presence(self):
        with self.lock:
            self.revision += 1
            payload = encode({'type': 'USER_LIST', 'revision': self.revision,
                              'users': [{'username': n} for n in self.users]})
            for user in self.users.values():
                try:
                    self.transport.send(user['peer'], payload)
                except (BufferError, ConnectionError):
                    pass

    def route(self, peer, data):
        request = json.loads(data)
        with self.lock:
            sender = next((n for n, u in self.users.items() if u['peer'] is peer), None)
            if not sender:
                return
            kind = request.get('type')
            if kind == 'HEARTBEAT':
                self.transport.send(peer, encode({'type': 'HEARTBEAT'}))
                return
            if kind == 'READY':
                self.presence()
                return
            if kind not in {'GLOBAL_MESSAGE', 'PRIVATE_MESSAGE', 'FILE_OFFER', 'FILE_ACCEPT', 'FILE_ACK', 'FILE_CHUNK', 'FILE_COMPLETE', 'FILE_RESULT'}:
                return
            request['sender'] = sender
            request['timestamp'] = time.time()
            if kind == 'GLOBAL_MESSAGE':
                targets = list(self.users.values())
            else:
                target = self.users.get(request.get('recipient'))
                if not target:
                    self.transport.send(peer, encode({'type': 'ERROR', 'error': 'Recipient offline', 'id': request.get('id'),
                                                       'conversation': request.get('recipient')}))
                    return
                targets = [target]
            payload = encode(request)
            for target in targets:
                try:
                    self.transport.send(target['peer'], payload)
                except (BufferError, ConnectionError):
                    self.transport.send(peer, encode({'type': 'ERROR', 'error': 'Recipient congested',
                                                       'id': request.get('id'),
                                                       'conversation': request.get('recipient')}))

    def close(self):
        self.running = False
        self.sock.close()
        with self.lock:
            connections = list(self.connections)
        for conn in connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        self.thread.join(2)
        for thread in self.threads:
            thread.join(2)
        self.transport.close()
