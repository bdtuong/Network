import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid
from network_app.crypto import identity, derive, seal_password
from network_app.shared import AUTH_TIMEOUT, CONNECT_TIMEOUT, receive, send, encode
from network_app.transport import Transport

CHUNK = 512
MAX_FILE = 1024 * 1024 * 1024


class Client:
    def __init__(self, username, host='127.0.0.1', port=9000, downloads='downloads',
                 *, password, connect_timeout=CONNECT_TIMEOUT, auth_timeout=AUTH_TIMEOUT):
        if not isinstance(password, str) or not 6 <= len(password) <= 128:
            raise ValueError('Password must contain 6-128 characters')
        if connect_timeout <= 0 or auth_timeout <= 0:
            raise ValueError('Connection and authentication timeouts must be positive')
        self.username = username
        self.downloads = Path(downloads)
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._closing = threading.Event()
        self.incoming = {}
        self.uploads = []
        self.outgoing = {}
        self.file_acks = {}
        self.users = []
        self.revision = 0
        self.running = False
        self.transport = Transport(('0.0.0.0', 0), self._receive, self._failed)
        self.socket = socket.socket()
        self.socket.settimeout(connect_timeout)
        try:
            self.socket.connect((host, port))
            self.socket.settimeout(auth_timeout)
            hello = receive(self.socket)
            if hello.get('type') != 'HELLO' or hello.get('version') != 2:
                raise ValueError('Unsupported server')
            private, public = identity()
            key = derive(private, hello['public_key'])
            encrypted_password = seal_password(key, hello['challenge'], username,
                                               self.transport.address[1], password)
            send(self.socket, {'type': 'AUTH', 'username': username,
                               'udp_port': self.transport.address[1], 'public_key': public,
                               'password': encrypted_password})
            response = receive(self.socket)
            if response['type'] != 'AUTH_OK':
                raise ValueError(response.get('error', 'Login failed'))
            self.socket.settimeout(connect_timeout)
            self.peer = self.transport.add(response['session'], key,
                                           (socket.gethostbyname(host), response['udp_port']))
            self.running = True
            self.send({'type': 'READY'})
            self.monitor = threading.Thread(target=self._heartbeat, daemon=True)
            self.monitor.start()
        except Exception:
            self.transport.close()
            self.socket.close()
            raise

    def _event(self, event):
        if event.get('type') in {'PRIVATE_MESSAGE', 'FILE_OFFER', 'FILE_RESULT', 'PROGRESS'}:
            sender = event.get('sender')
            other = event.get('recipient') if sender == self.username else sender
            event = dict(event, conversation=other)
        with self.lock:
            self.events.append(event)
            if len(self.events) > 2000:
                del self.events[:1000]

    def send(self, record):
        self.transport.send(self.peer, encode(record))

    def message(self, text, recipient=None):
        if not text.strip() or len(text.encode()) > 600:
            raise ValueError('Message must contain 1-600 UTF-8 bytes')
        record = {'type': 'PRIVATE_MESSAGE' if recipient else 'GLOBAL_MESSAGE',
                  'text': text, 'id': str(uuid.uuid4()), 'recipient': recipient}
        self.send(record)
        if recipient:
            self._event(dict(record, sender=self.username, timestamp=time.time()))
        return record['id']

    def send_file(self, path, recipient):
        path = Path(path)
        size = path.stat().st_size
        if size > MAX_FILE:
            raise ValueError('File exceeds 1 GiB')
        transfer = str(uuid.uuid4())
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(65536), b''):
                digest.update(block)
        accepted = threading.Event()
        with self.lock:
            if self._closing.is_set() or not self.running:
                raise ConnectionError('Client is closing')
            self.outgoing[transfer] = accepted
            self.file_acks[transfer] = set()
            try:
                self.send({'type': 'FILE_OFFER', 'id': transfer, 'recipient': recipient,
                           'name': path.name, 'size': size, 'sha256': digest.hexdigest()})
                thread = threading.Thread(target=self._upload,
                                          args=(transfer, path, recipient, accepted), daemon=True)
                thread.start()
                self.uploads.append(thread)
            except Exception:
                self._forget_upload(transfer)
                raise
        return transfer

    def _forget_upload(self, transfer):
        with self.lock:
            self.outgoing.pop(transfer, None)
            self.file_acks.pop(transfer, None)

    def _ack_count(self, transfer):
        with self.lock:
            return len(self.file_acks.get(transfer, ()))

    def _upload(self, transfer, path, recipient, accepted):
        try:
            if not accepted.wait(10):
                raise TimeoutError('File offer not accepted')
            size = path.stat().st_size
            count = (size + CHUNK - 1) // CHUNK
            reported = -1

            def report_progress():
                nonlocal reported
                with self.lock:
                    acknowledged = self.file_acks.get(transfer, set())
                    received_chunks = len(acknowledged)
                    received = received_chunks * CHUNK
                    if count and count - 1 in acknowledged:
                        received -= CHUNK - (size - (count - 1) * CHUNK)
                if received_chunks != reported and (
                    reported < 1 or received_chunks == count or received_chunks - reported >= 64
                ):
                    self._event({'type': 'PROGRESS', 'id': transfer, 'name': path.name,
                                 'progress': min(size, received) / size if size else 0,
                                 'phase': 'received', 'sender': self.username,
                                 'recipient': recipient})
                    reported = received_chunks
                return received_chunks

            with path.open('rb') as stream:
                index = 0
                while self.running:
                    deadline = time.monotonic() + 30
                    while index - report_progress() >= 16:
                        if not self.running or time.monotonic() > deadline:
                            raise TimeoutError('Receiver stalled')
                        time.sleep(.01)
                    block = stream.read(CHUNK)
                    if not block:
                        break
                    self._bounded_send({'type': 'FILE_CHUNK', 'id': transfer, 'recipient': recipient,
                                        'index': index, 'data': base64.b64encode(block).decode()})
                    index += 1
            deadline = time.monotonic() + 30
            while report_progress() < count:
                if not self.running or time.monotonic() > deadline:
                    raise TimeoutError('Receiver stalled')
                time.sleep(.01)
            self._bounded_send({'type': 'FILE_COMPLETE', 'id': transfer, 'recipient': recipient})
        except Exception as error:
            self._event({'type': 'ERROR', 'id': transfer, 'error': str(error),
                         'conversation': recipient})
        finally:
            self._forget_upload(transfer)

    def _bounded_send(self, record):
        deadline = time.monotonic() + 30
        while self.running and time.monotonic() < deadline:
            with self.transport.lock:
                queued = len(self.peer.backlog)
            if queued < 48:
                self.send(record)
                return
            time.sleep(.01)
        raise TimeoutError('Transfer stalled')

    def _receive(self, peer, payload):
        if self._closing.is_set():
            return
        record = json.loads(payload)
        kind = record.get('type')
        if kind == 'USER_LIST':
            with self.lock:
                if record.get('revision', 0) > self.revision:
                    self.users = record['users']
                    self.revision = record['revision']
        elif kind == 'FILE_ACK':
            with self.lock:
                acknowledged = self.file_acks.get(record['id'])
                if acknowledged is not None:
                    acknowledged.add(record['index'])
        elif kind == 'FILE_ACCEPT':
            with self.lock:
                accepted = self.outgoing.get(record['id'])
            if accepted:
                accepted.set()
        elif kind == 'FILE_OFFER':
            self._receive_offer(record)
            return
        elif kind in ('FILE_CHUNK', 'FILE_COMPLETE'):
            self._receive_file(record)
            return
        if kind == 'FILE_RESULT' and record.get('success'):
            self._event({'type': 'PROGRESS', 'id': record['id'], 'name': record['name'],
                         'progress': 1.0, 'phase': 'verified',
                         'sender': self.username, 'recipient': record['sender']})
        if kind in {'GLOBAL_MESSAGE', 'PRIVATE_MESSAGE', 'FILE_RESULT', 'ERROR'}:
            self._event(record)

    def _receive_offer(self, record):
        size = record['size']
        transfer = str(uuid.UUID(record['id']))
        if type(size) is not int or not 0 <= size <= MAX_FILE:
            return
        key = (record['sender'], transfer)
        name = Path(record['name'].replace('\\', '/')).name
        if name in ('', '.', '..'):
            name = 'file'
        path = self.downloads / (transfer + '-' + name)
        temp = path.with_name(path.name + '.part')
        with self.lock:
            if self._closing.is_set() or key in self.incoming or len(self.incoming) >= 8:
                return
            self.incoming[key] = dict(record, path=path, temp=temp, stream=temp.open('w+b'),
                                      seen=set(), received=0, updated=time.monotonic(),
                                      lock=threading.RLock(), closed=False)
        self.send({'type': 'FILE_ACCEPT', 'id': transfer, 'recipient': record['sender']})
        self._event(record)

    def _receive_file(self, record):
        key = (record['sender'], record['id'])
        with self.lock:
            state = self.incoming.get(key)
        if state is None:
            return
        # Never hold the client-wide lock while waiting for a file lock or hashing.
        with state['lock']:
            if state['closed'] or self._closing.is_set():
                return
            state['updated'] = time.monotonic()
            if record['type'] == 'FILE_CHUNK':
                index = record['index']
                block = base64.b64decode(record['data'], validate=True)
                count = (state['size'] + CHUNK - 1) // CHUNK
                if type(index) is not int or not 0 <= index < count:
                    return
                expected = min(CHUNK, state['size'] - index * CHUNK)
                if len(block) != expected:
                    return
                if index not in state['seen']:
                    state['stream'].seek(index * CHUNK)
                    state['stream'].write(block)
                    state['seen'].add(index)
                    state['received'] += len(block)
                    if len(state['seen']) == 1 or len(state['seen']) % 64 == 0:
                        self._event({'type': 'PROGRESS', 'id': record['id'], 'name': state['name'],
                                     'progress': state['received'] / max(1, state['size']),
                                     'sender': state['sender'], 'recipient': self.username})
                self.send({'type': 'FILE_ACK', 'id': record['id'],
                           'recipient': record['sender'], 'index': index})
            else:
                state['complete'] = True
            if state.get('complete') and state['received'] == state['size']:
                self._event({'type': 'PROGRESS', 'id': record['id'], 'name': state['name'],
                             'progress': 1.0,
                             'sender': state['sender'], 'recipient': self.username})
                state['stream'].seek(0)
                digest = hashlib.sha256()
                for block in iter(lambda: state['stream'].read(65536), b''):
                    digest.update(block)
                state['stream'].close()
                valid = digest.hexdigest() == state['sha256']
                if valid:
                    os.replace(state['temp'], state['path'])
                else:
                    state['temp'].unlink(missing_ok=True)
                state['closed'] = True
                with self.lock:
                    self.incoming.pop(key, None)
                result = {'type': 'FILE_RESULT', 'id': record['id'], 'recipient': record['sender'],
                          'success': valid, 'name': state['name'], 'sha256': digest.hexdigest()}
                self.send(result)
                self._event(dict(result, sender=self.username,
                                 path=str(state['path']) if valid else None))

    def _discard_incoming(self, key, state):
        with state['lock']:
            if state['closed']:
                return
            state['closed'] = True
            state['stream'].close()
            state['temp'].unlink(missing_ok=True)
            with self.lock:
                if self.incoming.get(key) is state:
                    self.incoming.pop(key)

    def _expire_incoming(self):
        with self.lock:
            transfers = list(self.incoming.items())
        for key, state in transfers:
            # A busy transfer must not stall the heartbeat thread.
            if not state['lock'].acquire(blocking=False):
                continue
            try:
                if state['closed'] or time.monotonic() - state['updated'] <= 45:
                    continue
                self._discard_incoming(key, state)
                self._event({'type': 'ERROR', 'id': key[1],
                             'conversation': key[0], 'error': 'Incoming file expired'})
            finally:
                state['lock'].release()

    def _failed(self, peer):
        self._event({'type': 'ERROR', 'error': 'Reliable transport timed out'})
        self.running = False

    def _heartbeat(self):
        while self.running:
            try:
                self.send({'type': 'HEARTBEAT'})
                if time.monotonic() - self.peer.last_seen > 20:
                    raise TimeoutError('Server unreachable')
                self._expire_incoming()
            except (OSError, ConnectionError, BufferError) as error:
                self._event({'type': 'ERROR', 'error': str(error)})
                self.running = False
            time.sleep(1)

    def close(self):
        with self._close_lock:
            if self._closing.is_set():
                return
            with self.lock:
                self._closing.set()
                self.running = False
                accepted_events = list(self.outgoing.values())
                uploads = list(self.uploads)
            for accepted in accepted_events:
                accepted.set()
            for thread in uploads:
                thread.join(2)
            try:
                send(self.socket, {'type': 'LOGOUT'})
            except OSError:
                pass
            self.socket.close()
            self.transport.close()
            if hasattr(self, 'monitor'):
                self.monitor.join(2)
            with self.lock:
                transfers = list(self.incoming.items())
            for key, state in transfers:
                self._discard_incoming(key, state)
