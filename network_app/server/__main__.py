import argparse
import time
from . import Server
from .dashboard import start_dashboard

parser = argparse.ArgumentParser()
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=9000)
parser.add_argument('--accounts', default='data/users.sqlite3')
parser.add_argument('--dashboard', type=int, default=9001, help='Port for Server Web Dashboard (0 to disable)')
parser.add_argument('--verbose', action='store_true', default=True, help='Print live logs to console')
args = parser.parse_args()

server = Server(args.host, args.port, accounts=args.accounts, verbose=args.verbose)
print('=' * 75, flush=True)
print(f'  SERVER CORE LISTENING ON TCP/UDP {args.host}:{server.port}', flush=True)
if args.dashboard > 0:
    dashboard = start_dashboard(server, host=args.host, port=args.dashboard)
    print(f'  LIVE WEB DASHBOARD AVAILABLE AT: http://{args.host}:{args.dashboard}', flush=True)
print('=' * 75, flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    server.close()
