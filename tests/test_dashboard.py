import json
import socket
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from network_app.server import Server
from network_app.server import __main__ as server_cli
from network_app.server.dashboard import DASHBOARD_HTML, start_dashboard
from network_app.shared import receive
from network_app.transport import HEADER
from test_application import system, wait


def test_dashboard_requires_token_and_same_origin_on_loopback(tmp_path):
    server = Server(port=0, accounts=tmp_path / 'users.sqlite3')
    dashboard = start_dashboard(server, port=0)
    root = dashboard.url.split('/#')[0]
    try:
        assert dashboard.server_address[0] == '127.0.0.1'
        assert dashboard.token in dashboard.url
        with urlopen(root + '/', timeout=3) as response:
            html = response.read().decode()
            assert 'X-Token' in html
            assert '684B' in html
            assert 'CUBIC-inspired' in html
        for headers in [{}, {'X-Token': 'wrong'},
                        {'X-Token': dashboard.token, 'Origin': 'https://untrusted.example'},
                        {'X-Token': dashboard.token, 'Host': 'untrusted.example'}]:
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(root + '/api/data', headers=headers), timeout=3)
            try:
                assert denied.value.code == 403
                assert json.load(denied.value) == {'error': 'Forbidden'}
                assert denied.value.headers.get('Access-Control-Allow-Origin') is None
            finally:
                denied.value.close()
        with urlopen(Request(root + '/api/data', headers={
                'X-Token': dashboard.token, 'Origin': root}), timeout=3) as response:
            data = json.load(response)
            assert response.headers.get('Access-Control-Allow-Origin') is None
            assert response.headers['Cache-Control'] == 'no-store'
            assert data['session_timeout'] == 15
    finally:
        dashboard.close()
        dashboard.close()
        server.close()
    assert not dashboard.thread.is_alive()


def test_dashboard_counts_udp_acks_retries_and_redacts_chat(system):
    server, connect = system
    alice, bob = connect('Alice'), connect('Bob')
    wait(lambda: len(alice.users) == len(bob.users) == 2)
    original = server.transport.sock

    class DropFirstData:
        dropped = False
        def sendto(self, packet, address):
            if not self.dropped and HEADER.unpack_from(packet)[1] == 0:
                self.dropped = True
                return len(packet)
            return original.sendto(packet, address)
        def __getattr__(self, name):
            return getattr(original, name)

    server.transport.sock = DropFirstData()
    secret = 'private-review-content-never-log'
    alice.message(secret)
    wait(lambda: any(e.get('text') == secret for e in bob.events))
    wait(lambda: server.transport.snapshot_metrics()['retransmissions'] > 0)
    metrics = server.get_dashboard_data()['stats']
    assert all(metrics[name] > 0 for name in (
        'packets_in', 'packets_out', 'bytes_in', 'bytes_out',
        'acks_in', 'acks_out', 'retransmissions', 'records_in'))
    assert metrics['bytes_in'] >= metrics['packets_in'] * (HEADER.size + 16)
    assert not any(secret in record['message'] for record in server.logs)
    assert 'val-acks' in DASHBOARD_HTML and 'val-retries' in DASHBOARD_HTML


def cli_server(monkeypatch, tmp_path, dashboard_port):
    cores = []
    def create(*args, **kwargs):
        core = Server(*args, **kwargs)
        cores.append(core)
        return core
    monkeypatch.setattr(server_cli, 'Server', create)
    monkeypatch.setattr(sys, 'argv', ['server', '--port', '0', '--accounts',
                                     str(tmp_path / 'users.sqlite3'), '--dashboard',
                                     str(dashboard_port), '--no-verbose'])
    def stop_after_check(_):
        assert cores[0].running
        with socket.create_connection(('127.0.0.1', cores[0].port), timeout=3) as sock:
            assert receive(sock)['type'] == 'HELLO'
        raise KeyboardInterrupt
    monkeypatch.setattr(server_cli.time, 'sleep', stop_after_check)
    return cores


def test_dashboard_bind_failure_does_not_stop_core(monkeypatch, tmp_path, capsys):
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen(1)
        cores = cli_server(monkeypatch, tmp_path, occupied.getsockname()[1])
        server_cli.main()
    output = capsys.readouterr().out
    assert 'Dashboard unavailable' in output
    assert 'Core server is still running' in output
    assert not cores[0].running
    assert not cores[0].transport.thread.is_alive()


def test_normal_cli_shutdown_closes_dashboard(monkeypatch, tmp_path, capsys):
    dashboards = []
    def start(core, **kwargs):
        dashboard = start_dashboard(core, port=0)
        dashboards.append(dashboard)
        return dashboard
    cores = cli_server(monkeypatch, tmp_path, 9001)
    monkeypatch.setattr(server_cli, 'start_dashboard', start)
    server_cli.main()
    output = capsys.readouterr().out
    assert dashboards[0].url in output
    assert dashboards[0]._closed
    assert not dashboards[0].thread.is_alive()
    assert not cores[0].running
