"""Lightweight Real-time Web Dashboard Monitor for Server using standard Python http.server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Network Operations Center (NOC) - Server Telemetry</title>
    <style>
        :root {
            /* Light Theme (Default) */
            --bg-primary: #f8fafc;
            --bg-card: #ffffff;
            --bg-card-sub: #f1f5f9;
            --bg-console: #0f172a;
            --border: #e2e8f0;
            --border-focus: #3b82f6;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
            --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.08), 0 2px 4px -1px rgba(0,0,0,0.04);
            
            --accent-cyan: #0284c7;
            --accent-blue: #2563eb;
            --accent-green: #059669;
            --accent-yellow: #d97706;
            --accent-purple: #7c3aed;
            --accent-red: #dc2626;
            --accent-orange: #ea580c;
        }

        [data-theme="dark"] {
            --bg-primary: #0b1120;
            --bg-card: #151e32;
            --bg-card-sub: #1e293b;
            --bg-console: #060a12;
            --border: #26334d;
            --border-focus: #38bdf8;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
            --shadow-md: 0 4px 12px rgba(0,0,0,0.4);

            --accent-cyan: #38bdf8;
            --accent-blue: #60a5fa;
            --accent-green: #34d399;
            --accent-yellow: #fbbf24;
            --accent-purple: #a78bfa;
            --accent-red: #f87171;
            --accent-orange: #fb923c;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            padding: 20px 28px;
            font-size: 13.5px;
            line-height: 1.5;
            transition: background-color 0.2s, color 0.2s;
        }

        /* Top Navigation Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .brand-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            color: #fff;
            box-shadow: 0 2px 10px rgba(37, 99, 235, 0.3);
        }
        .brand h1 {
            font-size: 19px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.3px;
        }
        .brand p {
            font-size: 12px;
            color: var(--text-secondary);
        }
        .header-actions {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            border-radius: 9999px;
            font-size: 11.5px;
            font-weight: 600;
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            box-shadow: var(--shadow-sm);
        }
        .badge.pulse-green {
            background: rgba(16, 185, 129, 0.12);
            border-color: rgba(16, 185, 129, 0.3);
            color: var(--accent-green);
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 8px var(--accent-green);
            animation: pulse 1.8s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.85); }
        }

        .theme-toggle {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            box-shadow: var(--shadow-sm);
            transition: all 0.15s;
        }
        .theme-toggle:hover {
            border-color: var(--border-focus);
            background: var(--bg-card-sub);
        }

        /* Top 4 Metrics Cards */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 22px;
        }
        .metric-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 18px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            box-shadow: var(--shadow-sm);
            transition: transform 0.15s, box-shadow 0.15s;
        }
        .metric-card:hover {
            transform: translateY(-1px);
            box-shadow: var(--shadow-md);
        }
        .metric-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
        }
        .metric-value {
            font-size: 26px;
            font-weight: 800;
            color: var(--text-primary);
            letter-spacing: -0.5px;
        }
        .metric-sub {
            font-size: 11.5px;
            color: var(--accent-blue);
            margin-top: 2px;
            font-weight: 500;
        }

        /* Main 2-Column Grid */
        .main-grid {
            display: grid;
            grid-template-columns: 430px 1fr;
            gap: 20px;
        }

        /* Panels */
        .panel {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: var(--shadow-sm);
        }
        .panel-header {
            padding: 13px 18px;
            background: var(--bg-card-sub);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-title {
            font-size: 13px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--text-primary);
        }
        .panel-body {
            padding: 14px 16px;
            flex: 1;
            overflow-y: auto;
        }

        /* Sessions Table */
        .session-item {
            background: var(--bg-card-sub);
            border: 1px solid var(--border);
            border-radius: 9px;
            padding: 12px 14px;
            margin-bottom: 10px;
            transition: border-color 0.15s;
        }
        .session-item:hover {
            border-color: var(--border-focus);
        }
        .session-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }
        .session-user {
            font-weight: 700;
            font-size: 14px;
            color: var(--accent-blue);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .session-badge {
            font-size: 10.5px;
            padding: 2px 8px;
            border-radius: 9999px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            font-weight: 700;
        }
        .session-meta {
            font-size: 11.5px;
            color: var(--text-secondary);
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 5px;
        }
        .session-uuid {
            font-size: 10.5px;
            font-family: "SFMono-Regular", Consolas, Menlo, monospace;
            color: var(--text-muted);
            background: var(--bg-card);
            border: 1px solid var(--border);
            padding: 3px 7px;
            border-radius: 4px;
            margin-top: 7px;
            word-break: break-all;
        }

        /* Protocol Cheat Sheet */
        .proto-box {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px 18px;
            box-shadow: var(--shadow-sm);
        }
        .proto-title {
            font-size: 11.5px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--accent-cyan);
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .proto-item {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            padding: 4px 0;
            border-bottom: 1px dashed var(--border);
        }
        .proto-item:last-child { border-bottom: none; }
        .proto-key { color: var(--text-secondary); font-weight: 500; }
        .proto-val {
            font-family: "SFMono-Regular", Consolas, monospace;
            font-weight: 700;
            color: var(--text-primary);
        }

        /* Console Controls */
        .console-controls {
            display: flex;
            gap: 7px;
            align-items: center;
        }
        .filter-btn {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s;
        }
        .filter-btn:hover, .filter-btn.active {
            background: var(--accent-blue);
            color: #fff;
            border-color: var(--accent-blue);
        }
        .log-container {
            height: 540px;
            overflow-y: auto;
            padding: 12px 16px;
            background: var(--bg-console);
            font-family: "SFMono-Regular", Consolas, Menlo, monospace;
            font-size: 11.5px;
            line-height: 1.7;
            border-radius: 0 0 11px 11px;
        }
        .log-line {
            display: flex;
            align-items: baseline;
            gap: 9px;
            margin-bottom: 4px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 3px;
        }
        .log-time {
            color: #64748b;
            font-size: 10.5px;
            white-space: nowrap;
        }
        .log-badge {
            font-size: 9.5px;
            font-weight: 700;
            padding: 1px 6px;
            border-radius: 4px;
            white-space: nowrap;
            text-transform: uppercase;
        }
        .tag-TCP { background: rgba(6, 182, 212, 0.2); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.4); }
        .tag-HANDSHAKE { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
        .tag-AUTH { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
        .tag-CRYPTO { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
        .tag-ROUTING { background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); }
        .tag-FILE { background: rgba(249, 115, 22, 0.2); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.4); }
        .tag-PRESENCE { background: rgba(236, 72, 153, 0.2); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.4); }
        .tag-DISCONNECT, .tag-ERROR { background: rgba(239, 68, 68, 0.22); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
        .tag-SESSION { background: rgba(14, 165, 233, 0.2); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.4); }
        .log-msg { color: #f1f5f9; word-break: break-all; }
        .empty-hint {
            text-align: center;
            color: #64748b;
            padding: 35px 20px;
            font-style: italic;
        }
    </style>
</head>
<body>

<header>
    <div class="brand">
        <div class="brand-icon">🌐</div>
        <div>
            <h1>NETWORK OPERATIONS CENTER (NOC)</h1>
            <p>Hybrid TCP/UDP Distributed Collaboration Server · Real-time Telemetry</p>
        </div>
    </div>
    <div class="header-actions">
        <button class="theme-toggle" id="theme-btn" onclick="toggleTheme()">☀️ Light Mode</button>
        <div class="badge pulse-green"><span class="pulse-dot"></span> LIVE SYSTEM ACTIVE</div>
        <div class="badge">TCP: <strong id="val-tcpport" style="color:var(--accent-blue)">9000</strong></div>
        <div class="badge">UDP: <strong id="val-udpport" style="color:var(--accent-purple)">9000</strong></div>
        <div class="badge">UPTIME: <strong id="val-uptime" style="color:var(--text-primary)">00:00:00</strong></div>
    </div>
</header>

<!-- Metrics 4-Card Row -->
<div class="metrics-grid">
    <div class="metric-card">
        <span class="metric-label">👥 Active Online Clients</span>
        <span class="metric-value" id="val-users-count" style="color:var(--accent-blue)">0</span>
        <span class="metric-sub" id="val-users-list">No users connected</span>
    </div>
    <div class="metric-card">
        <span class="metric-label">📦 RUDP Packets Routed</span>
        <span class="metric-value" id="val-packets-in" style="color:var(--accent-green)">0</span>
        <span class="metric-sub">Reliable UDP Datagrams (Max 1200B)</span>
    </div>
    <div class="metric-card">
        <span class="metric-label">⚡ TCP Sessions Handled</span>
        <span class="metric-value" id="val-tcp-conns" style="color:var(--accent-yellow)">0</span>
        <span class="metric-sub">Control Plane Handshakes</span>
    </div>
    <div class="metric-card">
        <span class="metric-label">🛡️ Security Stack</span>
        <span class="metric-value" style="font-size:16px; margin-top:5px; color:var(--accent-purple)">X25519 · AES-GCM</span>
        <span class="metric-sub">PBKDF2-SHA256 (600k iters)</span>
    </div>
</div>

<!-- Main 2-Column Grid -->
<div class="main-grid">

    <!-- Column 1: Client Sessions & Network Specs -->
    <div style="display:flex; flex-direction:column; gap:16px;">
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">👥 Active Client Sessions (<span id="count-clients">0</span>)</div>
                <span class="badge" style="font-size:10px;">Revision: #<span id="val-revision">0</span></span>
            </div>
            <div class="panel-body" id="sessions-container" style="max-height: 290px;">
                <div class="empty-hint">Waiting for clients to connect via TCP 9000...</div>
            </div>
        </div>

        <div class="proto-box">
            <div class="proto-title">📐 Protocol Specifications & Rubric Mapping</div>
            <div class="proto-item"><span class="proto-key">MAX_PACKET (UDP Datagram):</span><span class="proto-val" style="color:var(--accent-blue)">1200 Bytes</span></div>
            <div class="proto-item"><span class="proto-key">Fixed RUDP Header:</span><span class="proto-val">27 Bytes (!2sB16sQ)</span></div>
            <div class="proto-item"><span class="proto-key">AES-GCM Auth Tag:</span><span class="proto-val">16 Bytes (AAD Protected)</span></div>
            <div class="proto-item"><span class="proto-key">File CHUNK Size:</span><span class="proto-val" style="color:var(--accent-green)">512 Bytes (Base64 -> 683B)</span></div>
            <div class="proto-item"><span class="proto-key">Flow Control Window:</span><span class="proto-val">16 Chunks (In-flight credit)</span></div>
            <div class="proto-item"><span class="proto-key">Congestion Control:</span><span class="proto-val">CUBIC (cwnd 4 -> 32)</span></div>
            <div class="proto-item"><span class="proto-key">PBKDF2 Iterations:</span><span class="proto-val" style="color:var(--accent-yellow)">600,000 Iterations (OWASP)</span></div>
            <div class="proto-item"><span class="proto-key">Inactivity Timeout:</span><span class="proto-val">20s Heartbeat / 45s File Cleanup</span></div>
        </div>
    </div>

    <!-- Column 2: Real-time Live Packet & Telemetry Console -->
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">📡 Real-Time Protocol & Telemetry Stream</div>
            <div class="console-controls">
                <button class="filter-btn active" onclick="setFilter('ALL')">All</button>
                <button class="filter-btn" onclick="setFilter('HANDSHAKE')">Handshake</button>
                <button class="filter-btn" onclick="setFilter('CRYPTO')">Crypto</button>
                <button class="filter-btn" onclick="setFilter('ROUTING')">Routing</button>
                <button class="filter-btn" onclick="setFilter('FILE')">File</button>
                <label style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:4px; margin-left:6px; cursor:pointer;">
                    <input type="checkbox" id="autoscroll-chk" checked> Auto-scroll
                </label>
            </div>
        </div>
        <div class="log-container" id="log-box">
            <div class="empty-hint">Server listening. Handshake events and UDP packet stream will appear here in real-time...</div>
        </div>
    </div>

</div>

<script>
    let activeFilter = 'ALL';
    let currentTheme = localStorage.getItem('noc_theme') || 'light';

    function applyTheme(theme) {
        currentTheme = theme;
        localStorage.setItem('noc_theme', theme);
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            document.getElementById('theme-btn').textContent = '🌙 Dark Mode';
        } else {
            document.documentElement.removeAttribute('data-theme');
            document.getElementById('theme-btn').textContent = '☀️ Light Mode';
        }
    }

    function toggleTheme() {
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
    }

    // Apply saved theme immediately
    applyTheme(currentTheme);

    function setFilter(filter) {
        activeFilter = filter;
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.classList.toggle('active', btn.textContent.toUpperCase() === filter);
        });
        fetchData();
    }

    async function fetchData() {
        try {
            const res = await fetch('/api/data');
            if (!res.ok) return;
            const data = await res.json();

            // 1. Update Header Badges & Metrics
            document.getElementById('val-tcpport').textContent = data.tcp_port;
            document.getElementById('val-udpport').textContent = data.udp_port;
            document.getElementById('val-uptime').textContent = data.uptime;
            document.getElementById('val-users-count').textContent = data.users.length;
            document.getElementById('count-clients').textContent = data.users.length;
            document.getElementById('val-revision').textContent = data.revision;

            const userNames = data.users.map(u => u.username).join(', ');
            document.getElementById('val-users-list').textContent = userNames ? `Online: ${userNames}` : 'No users connected';
            document.getElementById('val-packets-in').textContent = (data.stats.packets_in || 0).toLocaleString();
            document.getElementById('val-tcp-conns').textContent = (data.stats.tcp_conns || 0).toLocaleString();

            // 2. Render Sessions List
            const sessionsBox = document.getElementById('sessions-container');
            if (data.users.length === 0) {
                sessionsBox.innerHTML = '<div class="empty-hint">Waiting for clients to connect via TCP 9000...</div>';
            } else {
                sessionsBox.innerHTML = data.users.map(u => `
                    <div class="session-item">
                        <div class="session-top">
                            <span class="session-user">👤 ${escapeHtml(u.username)}</span>
                            <span class="session-badge">TCP + RUDP ONLINE</span>
                        </div>
                        <div class="session-meta">
                            <span>TCP: <strong>${u.ip}:${u.tcp_port}</strong></span>
                            <span>UDP: <strong>${u.ip}:${u.udp_port}</strong></span>
                            <span>Congestion cwnd: <strong>${u.cwnd} pkts</strong></span>
                            <span>Heartbeat: <strong>${u.last_seen}s ago</strong></span>
                        </div>
                        <div class="session-uuid" title="Full Session UUID: ${u.full_session}">
                            UUID: ${u.session}
                        </div>
                    </div>
                `).join('');
            }

            // 3. Render Logs
            const logBox = document.getElementById('log-box');
            const filteredLogs = activeFilter === 'ALL' 
                ? data.logs 
                : data.logs.filter(l => l.category === activeFilter);

            if (filteredLogs.length > 0) {
                logBox.innerHTML = filteredLogs.map(l => `
                    <div class="log-line">
                        <span class="log-time">${l.time}</span>
                        <span class="log-badge tag-${l.category}">${l.category}</span>
                        <span class="log-msg">${escapeHtml(l.message)}</span>
                    </div>
                `).join('');

                if (document.getElementById('autoscroll-chk').checked) {
                    logBox.scrollTop = logBox.scrollHeight;
                }
            }
        } catch (e) {
            console.error('Telemetry fetch error:', e);
        }
    }

    function escapeHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // Poll every 500ms
    setInterval(fetchData, 500);
    fetchData();
</script>

</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence default HTTP server access logs so terminal stays clean
        pass

    def do_GET(self):
        if self.path == '/api/data':
            try:
                data = self.server.app_server.get_dashboard_data()
                body = json.dumps(data).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            body = DASHBOARD_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host, port, app_server):
        self.app_server = app_server
        super().__init__((host, port), DashboardHandler)


def start_dashboard(app_server, host='127.0.0.1', port=9001):
    server = DashboardServer(host, port, app_server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
