# Observed validation

Date: 2026-10-30. Host: macOS arm64. Runtime: Python 3.12.14. Dependencies installed in `.venv312`: cryptography 50.0.2, pytest 9.2.0, reportlab 5.1.0.

Final command: `.venv312/bin/python -m pytest -q -W error` from repository root. Actual captured output is in `pytest-results.txt`:

```text
................                                                         [100%]
16 passed in 69.77s (0:01:09)
```

The suite bound real localhost TCP/UDP sockets outside the execution sandbox, which otherwise prohibits socket binding. No tests were skipped or marked expected-failure. Initial iterations exposed shutdown and resource warnings; these were fixed before this final run. The final full run includes the presence revision change and all 16 tests. A subsequent frontend-only filter hides internal control events in chat; JavaScript syntax was checked after that change.

## Evidence by category

- Framing: UTF-8/Unicode, binary JSON values and invalid frame length.
- Crypto: binary encryption round trip, tampered-tag rejection and distinct ciphertext under opposite traffic keys.
- Authentication/state: nickname login, duplicate rejection, sessions with active UDP ports, presence, graceful logout and idle expiry.
- Routing: global delivery, private isolation, offline recipient error, twenty concurrent connections and simultaneous senders.
- Files: 0, 37, 65,539 and 10,485,791 bytes; byte/hash equality, receiver success returned to sender, no remaining partials, concurrent chat and intentional SHA-256 mismatch rejection.
- Transport: actual packet replay and malformed datagrams, window bounds, oversized outbound datagrams, retry exhaustion and failure notification.
- Impairment: 80,000-byte file with every eleventh outbound packet dropped, every fifth duplicated, every seventh delayed until the next packet, plus 1 ms delay. Impairment is applied to Alice's and the server's outbound sockets. Hash and byte equality, continued chat and positive sender retransmission count are asserted. The test adapter is test-only and seed-independent.
- HTTP bridge: static assets, capability rejection, login, message API, event polling and logout.
- Resilience: abrupt TCP disconnect leaves other clients operational, server shutdown, timeout expiry and bounded retry cleanup.

## Browser smoke test

Using the in-app browser against a running loopback bridge on port 8081 and server on port 9000: logged in as Alice, observed one online user and connected status, sent a global message, and observed it in the chat. `browser-smoke.png` records the final visible message. The frontend filter was verified in this browser check. This is single-client browser evidence; twenty-client behavior and private/file routing were verified through socket/HTTP integration tests. Manual three-browser file selection and multi-machine LAN tests remain recommended.

## Other checks

Python compileall completed successfully for package/tests/report builder. Node `--check` validates `web/app.js`. The five-page PDF was rendered with Poppler and every page visually inspected for clipping and legibility.

## Reproduce report

```sh
python docs/build_report.py
```

The PDF uses reportlab and includes architecture, wire format, message/file sequences, a one-page challenges reflection and validation/limitations. Markdown diagrams are available in `protocol.md`. Generated PDF/source contain no fabricated demo transcript or benchmark claims.
