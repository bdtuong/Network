"""Selective-repeat encrypted UDP with independent reliable records."""
import hashlib
import collections
import math
import queue
import socket
import struct
import threading
import time
import uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADER = struct.Struct('!2sB16sQ')
MAX_PACKET = 1200


class Peer:
    def __init__(self, session, key, address, server):
        self.session = session
        self.cipher = AESGCM(hashlib.sha256(key + (b'server' if server else b'client')).digest())
        self.receiver = AESGCM(hashlib.sha256(key + (b'client' if server else b'server')).digest())
        self.address = address
        self.sequence = 0
        self.highest = 0
        self.seen = set()
        self.pending = {}
        self.backlog = collections.deque()
        self.cwnd = 4.0
        self.window = 32
        self.epoch = time.monotonic()
        self.maximum = 4.0
        self.last_seen = time.monotonic()
        self.retransmissions = 0
        self.failed = False


class Transport:
    def __init__(self, bind, callback, failure=lambda peer: None, server=False):
        self.server = server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(bind)
        self.sock.settimeout(.02)
        self.callback, self.failure = callback, failure
        self.peers = {}
        self.lock = threading.RLock()
        self.running = True
        self.events = queue.Queue(maxsize=8192)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.worker = threading.Thread(target=self._dispatch, daemon=True)
        self.thread.start()
        self.worker.start()

    @property
    def address(self):
        return self.sock.getsockname()

    def add(self, session, key, address):
        with self.lock:
            peer = Peer(session, key, address, self.server)
            self.peers[session] = peer
            return peer

    def remove(self, session):
        with self.lock:
            peer = self.peers.pop(session, None)
            if peer is not None:
                peer.failed = True
                peer.pending.clear()
                peer.backlog.clear()

    def send(self, peer, payload):
        if len(payload) + HEADER.size + 16 > MAX_PACKET:
            raise ValueError('UDP payload too large')
        with self.lock:
            if peer.failed:
                raise ConnectionError('Peer unavailable')
            if len(peer.backlog) >= 256:
                raise BufferError('Send queue full')
            peer.backlog.append(payload)

    def _packet(self, peer, kind, payload):
        peer.sequence += 1
        header = HEADER.pack(b'NC', kind, uuid.UUID(peer.session).bytes, peer.sequence)
        nonce = peer.sequence.to_bytes(12, 'big')
        packet = header + peer.cipher.encrypt(nonce, payload, header)
        self.sock.sendto(packet, peer.address)
        return packet, peer.sequence

    def _read(self, packet, address):
        if not HEADER.size + 16 <= len(packet) <= MAX_PACKET:
            return
        magic, kind, sid, seq = HEADER.unpack_from(packet)
        peer = self.peers.get(str(uuid.UUID(bytes=sid)))
        if magic != b'NC' or kind not in (0, 1) or not peer or address != peer.address:
            return
        data = peer.receiver.decrypt(seq.to_bytes(12, 'big'), packet[HEADER.size:], packet[:HEADER.size])
        peer.last_seen = time.monotonic()
        if kind == 1:
            if len(data) != 8:
                return
            item = peer.pending.pop(struct.unpack('!Q', data)[0], None)
            if item:
                elapsed = time.monotonic() - peer.epoch
                k = (peer.maximum * .3 / .4) ** (1 / 3)
                target = .4 * (elapsed - k) ** 3 + peer.maximum
                peer.cwnd = min(peer.window, max(peer.cwnd + 1 / peer.cwnd, target))
            return
        if seq in peer.seen or seq <= peer.highest - 8192:
            self._packet(peer, 1, struct.pack('!Q', seq))
            return
        # ACK only after a bounded dispatch queue has accepted the record.
        self.events.put_nowait((peer, data))
        peer.highest = max(peer.highest, seq)
        peer.seen.add(seq)
        if len(peer.seen) > 8192:
            peer.seen = {n for n in peer.seen if n > peer.highest - 8192}
        self._packet(peer, 1, struct.pack('!Q', seq))

    def _run(self):
        while self.running:
            try:
                packet, address = self.sock.recvfrom(MAX_PACKET + 1)
                with self.lock:
                    self._read(packet, address)
            except (socket.timeout, ValueError, queue.Full):
                pass
            except Exception:
                if not self.running:
                    break
            with self.lock:
                if not self.running:
                    break
                for peer in list(self.peers.values()):
                    now = time.monotonic()
                    for seq, (packet, sent, retries) in list(peer.pending.items()):
                        if now - sent < min(2, .15 * 2 ** min(retries, 4)):
                            continue
                        if retries >= 12:
                            peer.failed = True
                            peer.pending.clear()
                            peer.backlog.clear()
                            self.events.put((peer, None))
                            break
                        self.sock.sendto(packet, peer.address)
                        peer.pending[seq] = packet, now, retries + 1
                        peer.retransmissions += 1
                        peer.maximum = peer.cwnd
                        peer.cwnd = max(2, peer.cwnd * .7)
                        peer.epoch = now
                    while not peer.failed and peer.backlog and len(peer.pending) < int(peer.cwnd):
                        packet, seq = self._packet(peer, 0, peer.backlog.popleft())
                        peer.pending[seq] = packet, now, 0

    def _dispatch(self):
        while self.running:
            try:
                peer, data = self.events.get(timeout=.1)
                if data is None:
                    self.failure(peer)
                else:
                    self.callback(peer, data)
            except queue.Empty:
                pass
            except Exception:
                import logging
                logging.exception('Rejected application record')

    def idle(self, peer):
        with self.lock:
            return not peer.pending and not peer.backlog

    def close(self):
        with self.lock:
            self.running = False
            self.sock.close()
        for thread in (self.thread, self.worker):
            if thread is not threading.current_thread():
                thread.join(2)
