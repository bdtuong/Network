import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit
from network_app.client import Client


class Bridge(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8080, downloads='downloads'):
        super().__init__(('127.0.0.1', port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.client = None
        self.downloads = downloads
        self.guard = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value, content='application/json'):
        data = json.dumps(value).encode() if content == 'application/json' else value
        self.send_response(code)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        host = self.headers.get('Host', '')
        expected = f'127.0.0.1:{self.server.server_port}'
        origin = self.headers.get('Origin')
        return (host == expected and origin in (None, 'http://' + expected)
                and secrets.compare_digest(self.headers.get('X-Token', ''), self.server.token))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/events':
            if not self.authorized():
                return self.reply(403, {'error': 'Forbidden'})
            client = self.server.client
            if not client:
                return self.reply(200, {'events': [], 'users': [], 'connected': False})
            with client.lock:
                events, client.events = client.events, []
            return self.reply(200, {'events': events, 'users': client.users, 'connected': client.running})
        assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                  '/style.css': ('style.css', 'text/css')}
        if path not in assets:
            return self.reply(404, {'error': 'Not found'})
        name, kind = assets[path]
        self.reply(200, (Path(__file__).parent / 'web' / name).read_bytes(), kind)

    def do_POST(self):
        if not self.authorized():
            return self.reply(403, {'error': 'Forbidden'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 <= length <= 32 * 1024 * 1024:
                raise ValueError('Upload limit: 32 MiB in browser; Python client supports 1 GiB')
            with self.server.guard:
                if self.path.startswith('/api/file?'):
                    from urllib.parse import parse_qs
                    params = parse_qs(urlsplit(self.path).query)
                    name = Path(params['name'][0].replace('\\', '/')).name
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / name
                        with path.open('wb') as output:
                            remaining = length
                            while remaining:
                                block = self.rfile.read(min(65536, remaining))
                                if not block:
                                    raise ValueError('Truncated upload')
                                output.write(block)
                                remaining -= len(block)
                        # Keep an owned spool file until the asynchronous sender finishes.
                        spool = Path(self.server.downloads) / ('upload-' + secrets.token_hex(8) + '-' + name)
                        spool.parent.mkdir(parents=True, exist_ok=True)
                        path.replace(spool)
                        self.server.client.send_file(spool, params['recipient'][0])
                    return self.reply(200, {'ok': True})
                if length > 16384:
                    raise ValueError('Request too large')
                data = json.loads(self.rfile.read(length))
                if self.path == '/api/login':
                    if self.server.client:
                        self.server.client.close()
                        self.server.client = None
                    self.server.client = Client(data['username'], data.get('host', '127.0.0.1'),
                                                int(data.get('port', 9000)), self.server.downloads,
                                                password=data['password'])
                elif self.path == '/api/message':
                    self.server.client.message(data['text'], data.get('recipient') or None)
                elif self.path == '/api/logout':
                    if self.server.client:
                        self.server.client.close()
                        self.server.client = None
                else:
                    return self.reply(404, {'error': 'Not found'})
            self.reply(200, {'ok': True})
        except (ValueError, KeyError, OSError, AttributeError, BufferError) as error:
            self.reply(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--downloads', default='downloads')
    args = parser.parse_args()
    bridge = Bridge(args.port, args.downloads)
    print(f'Open http://127.0.0.1:{bridge.server_port}/#{bridge.token}', flush=True)
    try:
        bridge.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if bridge.client:
            bridge.client.close()
        bridge.server_close()


if __name__ == '__main__':
    main()
