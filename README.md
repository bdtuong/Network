# Relay - network_app

A Python raw-socket collaboration application with password-protected accounts, live presence, global/private chat and verified reliable UDP file transfer. The HTML/CSS/vanilla JavaScript interface talks to a local Python client through a small standard-library HTTP bridge. All distributed messaging and file bytes use the custom encrypted UDP protocol; TCP establishes and monitors sessions.

## Install

Python 3.11+ is required (tested with Python 3.12). From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

Windows: use `py -3.11 -m venv .venv` and `.venv\Scripts\activate` instead. This workspace also has a prepared Python 3.12 environment: `source .venv312/bin/activate`.

## Start the server

```sh
python -m network_app.server --host 127.0.0.1 --port 9000
```

## Start three independent browser clients

Run each command in a separate terminal with the environment activated:

```sh
python -m network_app.webui --port 8081 --downloads downloads/alice
python -m network_app.webui --port 8082 --downloads downloads/bob
python -m network_app.webui --port 8083 --downloads downloads/charlie
```

Open each **full URL including its random fragment token** printed by its process. Log in as Alice, Bob and Charlie, each with a password of 6-128 characters, using server `127.0.0.1`, port `9000`. Each bridge owns one client session; multiple browser tabs on the same bridge share that session. A new username is automatically registered on its first successful login. Later logins require the same password, even after server restart. The UI explains this first-login registration. The server stores accounts in `data/users.sqlite3` (ignored by Git); keep that file private and back it up to preserve accounts. Select a different store using `--accounts /path/to/users.sqlite3`. Old nickname-only server/client versions are incompatible: restart the server and all bridges and reload the full token URLs after upgrading. No extra dependency is needed.

These commands are the client entry points; a terminal chat UI is not included.

1. Confirm all three clients show three online users.
2. Select Global and send a message as Alice; Bob and Charlie should receive it.
3. Select Bob as Alice and send a private message. Select Alice as Bob to see it; Charlie should not receive it.
4. Select Bob, choose a file and click Send file. Bob sees receive progress and final SHA-256 verification. Both parties receive FILE_RESULT. File progress updates reuse one progress item per transfer, so control packets and repeated progress updates do not crowd earlier chat messages out of the browser history. File offers, progress, completion and transfer errors are scoped to the private conversation with the other participant; they do not appear in Global chat or another person's conversation. Received files are in Bob's local downloads directory with a transfer UUID prefix.
5. Terminate Charlie's bridge (Ctrl-C for graceful exit, process termination for abrupt exit). Alice/Bob should update their online lists and continue chatting.
6. Run the impairment test below for a reproducible real-socket retransmission demonstration. No fake loss logs are produced.
7. Security tests demonstrate binary AES-GCM round trips, ciphertext tampering rejection and directional key separation. Encrypted transport means plaintext message content should not appear in UDP packet captures.

The Python API supports files above the browser's 32 MiB upload cap:

```python
from network_app.client import Client
from getpass import getpass
client = Client('AliceAPI', host='127.0.0.1', port=9000, password=getpass('Password: '))
client.message('Hello')
client.send_file('example.zip', 'Bob')
# Keep the process alive until FILE_RESULT appears in client.events.
# Then call client.close().
```

## Concurrent login and timeouts

Password hashing runs outside the account database lock, so concurrent clients do not queue behind every PBKDF2 calculation. Only short reads/inserts use the lock. SQLite's unique username constraint resolves concurrent registration: the winning account is preserved and another login must verify its password. Existing account files remain compatible; hashes still use 600,000 iterations.

The TCP connect timeout defaults to 5 seconds. After connecting, HELLO/AUTH response reads use a separate 30-second authentication timeout; server-side waiting for AUTH also uses 30 seconds. The Python API can override these with `Client(..., password=..., connect_timeout=5, auth_timeout=30)`. UDP/session timeouts are unchanged. This addresses the earlier Windows trace showing a timeout waiting for AUTH_OK under 20 simultaneous logins, but Windows verification must still be repeated on the affected machine.

## LAN deployment

Start the server with `--host 0.0.0.0`. Allow inbound **TCP and UDP 9000** through the server firewall. Run each HTTP bridge on its own user's computer and enter the server's LAN IP in the login form. The bridge stays on loopback; do not expose it to the LAN. Clients must have mutually routable IP/UDP ports; NAT traversal is not implemented. Use a trusted LAN/VPN because the initial key exchange has no pinned server identity.

## Test

```sh
python -m pytest -q -W error
python -m pytest -q tests/test_impairment.py
```

If Node.js is installed, pytest also runs the JavaScript conversation-rendering regression tests (otherwise that one UI test is skipped). You can run them directly with `node --test tests/test_web.cjs`. They exercise the actual UI render function for Global/Alice/Charlie channels, including file progress and completion.

Tests use real ephemeral localhost sockets and deterministic outbound loss (every 11th packet), duplication (every 5th), reordering (every 7th) and 1 ms latency. They include 20 concurrent clients, simultaneous global messages, private isolation, empty/text/binary/>10 MiB transfers, concurrent chat, hash mismatch rejection, replay rejection, malformed packets, bridge authorization, disconnects and cleanup. See `docs/testing.md` for actual observed results.

## Architecture and report

- `network_app/server/`: TCP admission, session tracking and UDP routing.
- `network_app/client/`: application state, file streams, verification and event history.
- `network_app/transport/`: encrypted selective-repeat transport and cubic-inspired windows.
- `network_app/shared/`: TCP framing and compact JSON serialization.
- `network_app/crypto.py`: X25519/HKDF key establishment.
- `network_app/webui.py` and `network_app/web/`: loopback bridge and browser assets.
- `docs/protocol.md`: exact protocol, diagrams, security and congestion-control tradeoffs.
- `docs/report.pdf`: technical explanation report.
- `docs/rubric.md`: milestone evidence map.

## Troubleshooting and limits

- Address in use: stop the previous server or choose another port; update each login form accordingly.
- No UDP/presence: check firewall, server IP and direct UDP reachability. TCP alone is insufficient.
- Forbidden bridge requests: open the complete terminal URL with token, using `127.0.0.1`, not `localhost`.
- Duplicate login: disconnect the old client or wait for the 15-second inactivity expiry.
- Browser upload is limited to 32 MiB; the Python client caps files at 1 GiB. Upload spool files remain in the local downloads folder and may be removed after transmission.
- Accounts use salted PBKDF2-HMAC-SHA256 hashes (600,000 iterations). Passwords are encrypted with AES-GCM over TCP after ephemeral X25519 key agreement, with a fresh connection challenge and separate login key. Username and UDP port are authenticated additional data. This protects against passive sniffing but does not authenticate server identity: active MITM attacks remain possible. Use only on a trusted LAN/VPN. There is no end-to-end encryption, certificate validation, offline history, reconnect/resume, rate limiting, account recovery or protection against malicious users consuming resources. First use claims an unused username; use a disposable demo password, not a password reused elsewhere.
- CUBIC-inspired window growth is educational, not a complete CUBIC/BBR implementation. Shared queues still create scheduling contention. Chat uses arrival ordering rather than guaranteed per-sender ordering.
- Packet ACKs mean the next hop accepted a record, not that a person read it. Private-send UI displays a local echo and reports offline/congestion errors; file success requires receiver SHA-256 result.
- Presence snapshots fit one datagram and are intended for the required 20-client scale. Oversized rosters and arbitrary scale are not supported.
- A recipient disconnect or severe congestion can fail an active transfer; incomplete files expire rather than reporting success. No progress persistence across restart.
- Automated HTTP integration is included; manual multi-machine/browser demonstration remains appropriate before submission.
