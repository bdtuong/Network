"""Rebuild the submission PDF using reportlab."""
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted
from reportlab.lib.units import inch

ROOT = Path(__file__).parent
styles = getSampleStyleSheet()
styles['BodyText'].leading = 15
styles['BodyText'].spaceAfter = 10
story = []


def title(text):
    story.append(Paragraph(text, styles['Heading1']))


def para(text):
    story.append(Paragraph(escape(text), styles['BodyText']))


def code(text):
    story.append(Preformatted(text, styles['Code']))


def page():
    story.append(PageBreak())


title('Distributed Streaming Collaboration')
para('Network Application Development - Technical Explanation Report')
para('Implementation: Relay / network_app. Python 3.11+ raw sockets; verified locally on Python 3.12. The official ten-milestone rubric guides this educational trusted-LAN implementation.')
title('1. System architecture')
code('Browser A -- HTTP loopback --> Client A\n                                  | TCP admission\n                                  | encrypted UDP records\n                             Central server\n                                  | encrypted UDP records\n                                  | TCP admission\nBrowser B -- HTTP loopback --> Client B')
para('The central server owns nickname/session state, source IP and active TCP/UDP ports, and routes global/private records. Every client owns its own transport, local file streams and bounded event history. The HTTP bridge is a separate loopback-only process with a random capability token. Static HTML/CSS and vanilla JavaScript poll that bridge; distributed application traffic never uses HTTP.')
para('The assignment contains a TCP-transfer example but explicitly grades UDP file transfer. This implementation uses TCP for HELLO/AUTH/AUTH_OK, session lifetime and logout; UDP handles messaging, presence, heartbeats and all file bytes. No high-level networking framework or WebSocket is used.')
para('Concurrency uses a thread per TCP session and a UDP receive/retransmission reactor plus application dispatch worker. Twenty simultaneous clients and simultaneous broadcasts are covered by real-socket tests. Server state is protected with a reentrant lock.')
para('Lifecycle: CONNECTED -> HELLO -> AUTH -> ACTIVE -> LOGOUT/EOF/INACTIVITY -> CLOSED. Duplicate active names are rejected. First login creates a persistent SQLite account; future logins verify salted PBKDF2-SHA256 hashes (600,000 iterations). Passwords are 6-128 characters.')
page()
title('2. Custom protocol specification')
para('TCP framing: unsigned 32-bit big-endian length followed by UTF-8 JSON, maximum 16,384 bytes. HELLO version 2 carries the ephemeral server key and a fresh 12-byte challenge. AUTH carries username, UDP port, client public key and AES-GCM-encrypted password. A separate login key and challenge nonce bind credentials to this connection; username/port form AAD. AUTH_OK returns session UUID and UDP port; AUTH_ERROR reports rejection.')
code('UDP fixed header: !2sB16sQ (27 bytes)\nmagic NC | kind 0=DATA,1=ACK | session UUID | counter\nbody: AES-GCM ciphertext + 16-byte tag\nmaximum complete datagram: 1200 bytes')
para('DATA plaintext is compact JSON. ACK plaintext is an eight-byte packet counter. Packet length follows the datagram boundary; NC identifies version 1. Header bytes are authenticated additional data. Counters form 12-byte nonces. Directional AES-GCM keys prevent counter collisions across directions. Retransmission resends the identical packet. A bounded 8192-counter replay window suppresses duplicates.')
para('Application types: READY, USER_LIST, HEARTBEAT, GLOBAL_MESSAGE, PRIVATE_MESSAGE, ERROR, FILE_OFFER, FILE_ACCEPT, FILE_ACK, FILE_CHUNK, FILE_COMPLETE and FILE_RESULT. Messages have id/text/recipient with server-stamped sender/time. Offers have id/name/size/SHA-256; chunks add index and base64 payload; results add success and computed hash. Presence snapshots carry a monotonic revision.')
para('A file UUID and sender identify its logical stream. Chunks carry 512 binary bytes before base64 encoding. Files are capped at 1 GiB (32 MiB browser upload). Temporary files receive indexed writes; unique byte counts and SHA-256 gate atomic finalization. Duplicate chunks do not inflate progress. An early completion waits for missing chunks. Stale partial transfers expire and are deleted.')
para('Selective-repeat windows begin at four packets and cap at 32. Missing ACKs trigger 150 ms initial retransmission timeout with exponential backoff capped at two seconds; twelve retries signal failure. A separate sixteen-chunk receiver-credit limit bounds per-file relay pressure. Chat records do not wait for file sequence gaps; chat itself is arrival ordered.')
page()
title('3. Message and file sequences')
code('Alice                Server                 Bob\n  | GLOBAL_MESSAGE ---->|                    |\n  |<------ hop ACK      |                    |\n  |<---- broadcast      |---- broadcast ----->|\n  |                     |<----- hop ACK -----|\n  | PRIVATE_MESSAGE --->|                    |\n  |                     |---- private ------>|\n  |                     |     (Bob only)     |')
story.append(Spacer(1, 16))
code('Alice                Server                 Bob\n  | FILE_OFFER -------->|---- FILE_OFFER ---->|\n  |<----- FILE_ACCEPT --|<--- FILE_ACCEPT ----|\n  |                     |                    |\n  | FILE_CHUNK(index) ->|---- FILE_CHUNK ---->|\n  |<----- FILE_ACK -----|<--- FILE_ACK -------|\n  | [repeat within sliding / credit windows] |\n  | FILE_COMPLETE ----->|---- COMPLETE ------>|\n  |                     |  reassemble + hash |\n  |<----- FILE_RESULT --|<--- FILE_RESULT ----|')
para('Packet ACKs operate independently on each encrypted hop. FILE_ACK credits reflect receipt at the destination. FILE_RESULT is the end-to-end integrity outcome. Local private message echo is not a read receipt. Offline or congested recipients produce errors.')
para('Congestion handling is educational CUBIC-inspired window growth: target = 0.4*(elapsed-K)^3 + Wmax, K = (0.3*Wmax/0.4)^(1/3), combined with additive ACK growth. Timeout reduces the window by 0.7 and restarts the epoch. It is not full CUBIC or BBR: pacing, adaptive RTT estimates, standards-level fairness and fast recovery are absent.')
para('X25519 and HKDF establish session secrets; AES-GCM protects UDP content and headers. The server decrypts routed data. No pinned certificate or identity authenticates the initial key exchange, so active man-in-the-middle attacks remain possible. Use a trusted LAN/VPN. TCP metadata and packet sizes remain visible.')
page()
title('4. Challenges and solutions')
for paragraph in (ROOT / 'challenges.md').read_text().split('\n\n')[1:]:
    para(paragraph)
page()
title('5. Validation and practical limits')
para('Automated tests exercise real localhost TCP/UDP sockets, not only mocks. Coverage includes Unicode and binary framing, invalid lengths, persistent password authentication, wrong-password rejection, duplicate login, presence, global/private isolation, twenty concurrent sessions, file integrity and concurrent chat, replay and tampering, abrupt disconnect, inactivity, retry exhaustion and HTTP bridge authorization.')
para('File sizes include zero bytes, 37 bytes, 65,539 bytes and 10,485,791 bytes. A separate 80,000-byte test uses deterministic outbound loss every eleventh packet, duplicates every fifth, holds every seventh for reordering, and adds one millisecond latency. Success requires a receiver hash match and observed retransmissions.')
para('Actual final pytest results are recorded in docs/testing.md alongside the raw pytest output. The implementation was iteratively tested; an initial successful functional run exposed shutdown-thread warnings, and stricter warning checks drove resource cleanup fixes. No manual multi-machine or full browser interaction result is claimed. The earlier browser screenshot predates the password field; current password handling is verified by HTTP and socket tests.')
para('Run: python -m pytest -q -W error. Start server: python -m network_app.server. Start three client bridges with python -m network_app.webui --port 8081, 8082 and 8083 in separate terminals. Open each full token URL and log in as Alice, Bob and Charlie. README supplies detailed installation, LAN firewall and demonstration steps.')
para('Remaining limits: no account recovery, offline history, transfer resume, NAT traversal or hostile-client resource defense. Shared windows still permit scheduling contention. Browser uploads retain spool files for inspection. Presence supports the required twenty-client scale, not arbitrary large rosters. Congestion control and authentication remain educational simplifications; manual browser and cross-platform LAN validation should precede submission.')


def footer(canvas, document):
    canvas.setStrokeColor(colors.HexColor('#087e82'))
    canvas.line(42, 40, 553, 40)
    canvas.setFont('Helvetica', 9)
    canvas.drawString(42, 26, 'Relay | Network Application Development')
    canvas.drawRightString(553, 26, str(document.page))


SimpleDocTemplate(str(ROOT / 'report.pdf'), rightMargin=48, leftMargin=48,
                  topMargin=40, bottomMargin=54).build(story, onFirstPage=footer, onLaterPages=footer)
