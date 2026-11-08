import argparse
import time
from . import Server
from .dashboard import start_dashboard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--accounts', default='data/users.sqlite3')
    parser.add_argument('--dashboard', type=int, default=9001,
                        help='Loopback dashboard port (0 to disable)')
    parser.add_argument('--verbose', action=argparse.BooleanOptionalAction, default=True,
                        help='Print live logs to console')
    args = parser.parse_args()
    server = Server(args.host, args.port, accounts=args.accounts, verbose=args.verbose)
    dashboard = None
    try:
        print(f'SERVER CORE LISTENING ON TCP/UDP {args.host}:{server.port}', flush=True)
        if args.dashboard > 0:
            try:
                dashboard = start_dashboard(server, port=args.dashboard)
                print(f'LIVE WEB DASHBOARD: {dashboard.url}', flush=True)
            except OSError as error:
                print(f'Dashboard unavailable: {error}. Core server is still running.', flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if dashboard is not None:
                dashboard.close()
        finally:
            server.close()


if __name__ == '__main__':
    main()
