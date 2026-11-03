import argparse
import time
from . import Server

parser = argparse.ArgumentParser()
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=9000)
parser.add_argument('--accounts', default='data/users.sqlite3')
args = parser.parse_args()
server = Server(args.host, args.port, accounts=args.accounts)
print(f'Server listening on TCP/UDP {args.host}:{server.port}', flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    server.close()
