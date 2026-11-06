import collections
import json
import secrets
import re
import socket
import threading
import time
import uuid
from network_app.crypto import identity, derive, open_password
from .accounts import Accounts
from network_app.shared import AUTH_TIMEOUT, receive, send, encode
from network_app.transport import Transport


class Server:
    def __init__(self, host='127.0.0.1', port=9000, timeout=15,
                 accounts='data/users.sqlite3', verbose=False):
        self.accounts = Accounts(accounts)
        self.lock = threading.RLock()
        self._close_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.verbose = verbose
        self.logs = collections.deque(maxlen=300)
        self.stats = {
            'tcp_conns': 0,
            'packets_in': 0,
            'packets_out': 0,
            'bytes_in': 0,
            'bytes_out': 0,
            'start_time': time.time()
        }
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
        self.log('INIT', f'Server listening on TCP/UDP {host}:{self.sock.getsockname()[1]} (MAX_PACKET=1200B)')
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def log(self, category, message):
        record = {
            'time': time.strftime('%H:%M:%S'),
            'timestamp': time.time(),
            'category': category,
            'message': message
        }
        with self.log_lock:
            self.logs.append(record)
        if self.verbose:
            print(f"[{record['time']}][{category}] {message}", flush=True)

    def get_dashboard_data(self):
        with self.lock:
            users_list = []
            for name, u in self.users.items():
                p = u['peer']
                users_list.append({
                    'username': name,
                    'ip': u['ip'],
                    'tcp_port': u['tcp_port'],
                    'udp_port': u['udp_port'],
                    'session': p.session[:8] + '...' + p.session[-4:],
                    'full_session': p.session,
                    'cwnd': round(getattr(p, 'cwnd', 4.0), 2),
                    'last_seen': round(time.monotonic() - getattr(p, 'last_seen', time.monotonic()), 1)
                })
            rev = self.revision
        with self.log_lock:
            recent_logs = list(self.logs)

        elapsed = int(time.time() - self.stats['start_time'])
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

        return {
            'uptime': uptime_str,
            'tcp_port': self.port,
            'udp_port': self.port,
            'revision': rev,
            'users': users_list,
            'stats': dict(self.stats),
            'logs': recent_logs
        }

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
                if not self.running:
                    conn.close()
                    break
                self.connections.add(conn)
                self.stats['tcp_conns'] += 1
                self.log('TCP', f'New connection accepted from {addr[0]}:{addr[1]}')
                thread = threading.Thread(target=self._session, args=(conn, addr), daemon=True)
                self.threads.append(thread)
                thread.start()

    def _session(self, conn, addr):
        name = None
        try:
            conn.settimeout(AUTH_TIMEOUT)
            private, public = identity()
            challenge = secrets.token_hex(12)
            send(conn, {'type': 'HELLO', 'version': 2,
                        'public_key': public, 'challenge': challenge})
            self.log('HANDSHAKE', f'Sent HELLO v2 -> Challenge: {challenge[:8]}... | Server X25519 PubKey ({len(public)}B)')
            request = receive(conn)
            candidate = request.get('username', '')
            if request.get('type') != 'AUTH' or not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', candidate):
                raise ValueError('Invalid login')
            port = request['udp_port']
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('Invalid UDP port')
            self.log('HANDSHAKE', f'Received AUTH from user="{candidate}" | UDP Port: {port} | Client PubKey ({len(request.get("public_key", b""))}B)')
            key = derive(private, request['public_key'])
            self.log('CRYPTO', f'Derived 256-bit AES shared key via ECDH (X25519) + HKDF-SHA256 for "{candidate}"')
            password = open_password(key, challenge, candidate, port, request['password'])
            self.accounts.authenticate(candidate, password)
            self.log('AUTH', f'Password verified via PBKDF2 (600,000 iters) & SQLite for "{candidate}" -> SUCCESS')
            del password
            with self.lock:
                if not self.running:
                    raise ConnectionError('Server is shutting down')
                if candidate in self.users:
                    raise ValueError('Username already online')
                sid = str(uuid.uuid4())
                peer = self.transport.add(sid, key, (addr[0], port))
                self.users[candidate] = {'peer': peer, 'socket': conn, 'ip': addr[0], 'tcp_port': addr[1], 'udp_port': port}
                name = candidate
                self.log('SESSION', f'Assigned RUDP Session UUID: {sid} to user="{candidate}"')
                send(conn, {'type': 'AUTH_OK', 'session': sid, 'public_key': public, 'udp_port': self.port})
                self.log('HANDSHAKE', f'Sent AUTH_OK to "{candidate}" (Server UDP Port: {self.port})')
            conn.settimeout(1)
            while self.running:
                try:
                    control = receive(conn)
                    if control.get('type') == 'LOGOUT':
                        self.log('SESSION', f'User "{name}" requested LOGOUT')
                        break
                    if control.get('type') != 'HEARTBEAT':
                        raise ValueError('Invalid control request')
                except socket.timeout:
                    if time.monotonic() - peer.last_seen > self.timeout:
                        self.log('TIMEOUT', f'User "{name}" timed out (> {self.timeout}s inactive)')
                        break
        except (OSError, EOFError, ValueError, KeyError, TypeError) as error:
            self.log('ERROR', f'Authentication/Session error from {addr[0]}:{addr[1]}: {error}')
            try:
                send(conn, {'type': 'AUTH_ERROR', 'error': str(error)})
            except OSError:
                pass
        finally:
            with self.lock:
                if name:
                    user = self.users.pop(name, None)
                    if user:
                        self.transport.remove(user['peer'].session)
                        self.log('DISCONNECT', f'Client "{name}" disconnected. Revoked RUDP session.')
                self.connections.discard(conn)
            conn.close()
            self.presence()

    def presence(self):
        with self.lock:
            if not self.running:
                return
            self.revision += 1
            payload = encode({'type': 'USER_LIST', 'revision': self.revision,
                              'users': [{'username': n} for n in self.users]})
            user_keys = list(self.users.keys())
            for user in self.users.values():
                try:
                    self.transport.send(user['peer'], payload)
                except (BufferError, ConnectionError):
                    pass
        self.log('PRESENCE', f'Broadcasting USER_LIST revision={self.revision} with {len(user_keys)} online user(s): {user_keys}')

    def route(self, peer, data):
        request = json.loads(data)
        self.stats['packets_in'] += 1
        self.stats['bytes_in'] += len(data)
        with self.lock:
            if not self.running:
                return
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
                self.log('ROUTING', f'GLOBAL_MESSAGE from "{sender}": "{request.get("text", "")[:32]}" -> Broadcasted')
            else:
                target = self.users.get(request.get('recipient'))
                if not target:
                    self.transport.send(peer, encode({'type': 'ERROR', 'error': 'Recipient offline', 'id': request.get('id'),
                                                       'conversation': request.get('recipient')}))
                    self.log('ROUTING', f'Cannot route {kind} from "{sender}": recipient "{request.get("recipient")}" offline')
                    return
                targets = [target]
                if kind == 'PRIVATE_MESSAGE':
                    self.log('ROUTING', f'PRIVATE_MESSAGE from "{sender}" -> Unicast to "{request.get("recipient")}"')
                elif kind == 'FILE_OFFER':
                    self.log('FILE', f'FILE_OFFER from "{sender}" -> "{request.get("recipient")}": "{request.get("name")}" ({request.get("size")}B, SHA-256: {request.get("sha256", "")[:12]}...)')
                elif kind == 'FILE_ACCEPT':
                    self.log('FILE', f'FILE_ACCEPT from "{sender}" -> "{request.get("recipient")}"')
                elif kind == 'FILE_CHUNK':
                    idx = request.get('index', 0)
                    if idx == 0 or idx % 25 == 0:
                        self.log('FILE', f'FILE_CHUNK #{idx} from "{sender}" -> "{request.get("recipient")}" (512B raw / ~836B UDP)')
                elif kind == 'FILE_COMPLETE':
                    self.log('FILE', f'FILE_COMPLETE from "{sender}" -> "{request.get("recipient")}"')
                elif kind == 'FILE_RESULT':
                    self.log('FILE', f'FILE_RESULT: "{sender}" confirmed transfer success={request.get("success")} for "{request.get("name")}"')
            payload = encode(request)
            for target in targets:
                try:
                    self.transport.send(target['peer'], payload)
                except (BufferError, ConnectionError):
                    self.transport.send(peer, encode({'type': 'ERROR', 'error': 'Recipient congested',
                                                       'id': request.get('id'),
                                                       'conversation': request.get('recipient')}))

    def close(self):
        with self._close_lock:
            with self.lock:
                if not self.running:
                    return
                self.running = False
                connections = list(self.connections)
                threads = list(self.threads)
            self.sock.close()
            for conn in connections:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                conn.close()
            self.thread.join(2)
            for thread in threads:
                thread.join(2)
            self.transport.close()
