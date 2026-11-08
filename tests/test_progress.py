import json
from pathlib import Path
import threading

import pytest
from test_application import system, wait


def test_sender_progress_waits_for_receiver_chunk_ack(system, tmp_path):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    entered, release = threading.Event(), threading.Event()
    original = server.transport.callback

    def pause_chunk(peer, payload):
        if json.loads(payload).get('type') == 'FILE_CHUNK':
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release chunk')
        original(peer, payload)

    server.transport.callback = pause_chunk
    path = tmp_path / 'tiny.bin'
    path.write_bytes(b'x' * 512)
    transfer = alice.send_file(path, 'Bob')
    try:
        assert entered.wait(3)
        progress = wait(lambda: [e for e in alice.events
                                if e['type'] == 'PROGRESS' and e.get('id') == transfer])
        assert all(e['progress'] == 0 for e in progress)
        assert next(iter(bob.incoming.values()))['received'] == 0
        assert not any(e['type'] == 'FILE_RESULT' and e.get('id') == transfer for e in alice.events)
    finally:
        release.set()
    result = wait(lambda: next((e for e in alice.events
                               if e['type'] == 'FILE_RESULT' and e.get('id') == transfer), None))
    assert result['success']
    progress = [e for e in alice.events if e['type'] == 'PROGRESS' and e.get('id') == transfer]
    assert progress[-1]['progress'] == 1
    assert progress[-1]['phase'] == 'verified'


@pytest.mark.parametrize('size', [0, 700])
def test_empty_and_partial_chunk_files_reach_verified_progress(system, tmp_path, size):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    path = tmp_path / 'partial.bin'
    path.write_bytes(b'x' * size)
    transfer = alice.send_file(path, 'Bob')
    wait(lambda: any(e['type'] == 'FILE_RESULT' and e.get('id') == transfer for e in alice.events))
    progress = [e for e in alice.events if e['type'] == 'PROGRESS' and e.get('id') == transfer]
    assert progress[-1]['progress'] == 1
    assert progress[-1]['phase'] == 'verified'
    assert all(0 <= e['progress'] <= 1 for e in progress)
    result = next(e for e in bob.events if e['type'] == 'FILE_RESULT' and e.get('id') == transfer)
    assert result['success']
    assert Path(result['path']).read_bytes() == path.read_bytes()
