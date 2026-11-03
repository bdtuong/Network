# Latest validation: retain chat history during file transfer

Command: `.venv312/bin/python -m pytest -q -W error`. Actual full-suite output:

```text
.......................                                                  [100%]
23 passed in 70.54s (0:01:10)
```

The sender-history regression sends a private `hello` from Alice to Bob, transfers 1,228,800 bytes (2,400 chunks), and verifies that both parties retain the message, the file verifies successfully, and FILE_ACK/FILE_ACCEPT/FILE_CHUNK never enter UI event queues. It deliberately does not poll/drain events while the file is transferred.

The JavaScript suite now has six cases. Its new case renders `hello`, ingests 2,500 control ACK events plus 1,250 progress updates across multiple batches, then appends FILE_RESULT and verifies that hello, one latest progress item and Verified all remain visible. Switching to Global hides these private records and switching back restores them. This tests the actual frontend rendering/history functions with a lightweight DOM harness, not a manual browser session.

Restart Python bridges (and the server if still on an older version), then reopen the full terminal token URLs to load the new Python and JavaScript. Old messages already evicted by the previous implementation cannot be recovered from that in-memory history.

## Previous conversation-isolation validation

Command: `.venv312/bin/python -m pytest -q -W error`. Actual output:

```text
......................                                                   [100%]
22 passed in 65.19s (0:01:05)
```

The new real-socket test transfers a 70,000-byte file from Alice to Bob while Charlie is online. It verifies that Bob's file offer/progress/result events all identify Alice as the conversation, Alice's result identifies Bob, received bytes match, and Charlie receives no event for this transfer. Global messaging still reaches Charlie afterward.

Five JavaScript regression cases execute the real `app.js` renderer in Node's VM with a small DOM test harness: file events are hidden in Global and Charlie, visible in Alice, channel switching restores the matching history, and internal/unscoped events are not rendered as private cards. `node --test tests/test_web.cjs` passed all five cases; pytest invokes this suite when Node.js is available. No tests were skipped in the latest local run. This is automated rendering evidence, not a claim of a new manual browser demonstration.

Restart server and all Python bridges, then open each full URL including its token so both Python event metadata and JavaScript filters are refreshed. Existing accounts and downloaded files are preserved.

## Previous password-update validation

Latest command: `.venv312/bin/python -m pytest -q -W error`. Actual full-run output:

```text
....................                                                     [100%]
20 passed in 63.58s (0:01:03)
```

Output is also saved in `pytest-results.txt`. A subsequent focused HTTP bridge test (including wrong-password feedback) passed: `1 passed in 2.84s`. New tests cover salted account hashes, persistence across server restart, wrong and short passwords, credential encryption, identity/challenge binding, old AUTH replay rejection and plaintext password rejection. Existing integration tests now pass passwords and use isolated temporary SQLite account stores. No user account database is touched by tests.

The bridge integration test submits the password through the same HTTP endpoint used by the UI. Manual password-field browser interaction has not been repeated; `browser-smoke.png` is historical evidence from the earlier nickname-only UI, not a screenshot of the new password form. Old servers/bridges must be restarted and browser pages reloaded with the new terminal token URLs.

## Previous verification (before password update)

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
