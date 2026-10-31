import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest
from network_app.server import Server
from network_app.webui import Bridge


def test_http_bridge_login_message_static_and_authorization(tmp_path):
    server = Server(port=0)
    bridge = Bridge(0, tmp_path)
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    root = f'http://127.0.0.1:{bridge.server_port}'
    def post(path, data, token=None):
        request = Request(root + path, json.dumps(data).encode(),
                          {'X-Token': token or bridge.token, 'Content-Type': 'application/json'})
        return json.load(urlopen(request, timeout=5))
    try:
        assert b'RELAY' in urlopen(root, timeout=5).read()
        assert b'setInterval' in urlopen(root + '/app.js', timeout=5).read()
        with pytest.raises(HTTPError) as denied:
            post('/api/login', {}, 'wrong')
        assert denied.value.code == 403
        denied.value.close()
        assert post('/api/login', {'username': 'Browser', 'port': server.port})['ok']
        assert post('/api/message', {'text': 'from browser'})['ok']
        request = Request(root + '/api/events', headers={'X-Token': bridge.token})
        assert json.load(urlopen(request, timeout=5))['connected']
        assert post('/api/logout', {})['ok']
    finally:
        if bridge.client:
            bridge.client.close()
        bridge.shutdown()
        bridge.server_close()
        thread.join(2)
        server.close()
