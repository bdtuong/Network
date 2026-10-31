# Ten-milestone evidence map

Status describes implementation and automated local evidence, not an instructor's grading decision. A manual multi-machine demonstration remains to be performed.

| # | PDF milestone | Implementation | Verification / demo | Status |
|---|---|---|---|---|
| 1 | Setup and protocol | `shared`, `docs/protocol.md`; framing, packet layout, state/sequence diagrams | framing and invalid-length tests; inspect protocol | Implemented; chronology caveat below |
| 2 | TCP handshake | `server._session`, `client.Client` | login/integration tests; launch three bridges | Verified locally |
| 3 | Authentication and state | unique nicknames, IP/TCP/UDP tracking, UUID sessions, presence revision | duplicate login, online list, logout and inactivity tests | Verified locally; nickname admission only |
| 4 | Concurrency | thread per TCP session, independent UDP reactor/worker | 20 concurrent clients and 20 simultaneous senders | Verified locally |
| 5 | UDP streaming routing | global/private records, independent file IDs, selective delivery | private isolation, global broadcast, concurrent chat/file test | Verified locally; chat arrival ordered |
| 6 | Reliable UDP file transfer | chunks, selective repeat, receiver credits, disk reassembly, SHA-256 | empty/37-byte/65,539-byte/10,485,791-byte files; deterministic impairment | Verified locally |
| 7 | Resilience | heartbeat expiry, bounded retry/backoff, EOF/logout, cleanup | abrupt disconnect, shutdown, retry exhaustion, inactivity tests | Verified locally |
| 8 | Encryption | X25519/HKDF, directional AES-GCM, authenticated headers, replay dedup | binary crypto, tamper rejection, replay tests; encrypted integration traffic | Verified locally; trusted LAN assumption |
| 9 | HTTP/JavaScript UI | `webui.py`, `web/`; login, people, chat, file progress/results | HTTP assets/API/auth tests; three-port demo in README | Implemented; HTTP and single-client browser smoke verified; three-browser/LAN demonstration pending |
| 10 | Testing and quality | `tests/`, modular implementation, `docs/testing.md` | pytest with warnings as errors, compile checks | See actual final test log |

Milestone 1 asks for documentation before coding. The protocol decisions were established before implementation, but the detailed Markdown specification was written alongside implementation. No historical before-coding artifact or Git commit is claimed.

The PDF references BBR/CUBIC as a technique rather than a separate rubric row. The implemented congestion controller is cubic-inspired educational logic, not full CUBIC or BBR. The protocol documentation identifies its omissions.
