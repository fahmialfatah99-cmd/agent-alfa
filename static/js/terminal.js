
/* ==== ES MODULE BRIDGE ==== */
import { escAttr, showToast, updateSwarmArena } from './modules/state.js';
/* ==========================================================================
   ALFA DASHBOARD — Live Terminal, Log Streaming & ANSI Parser
   ========================================================================== */

/**
 * ANSI Color & Style parser
 * Converts standard ANSI escape sequences into styled HTML spans
 */
function parseAnsiToHtml(text) {
    if (!text) return "";
    let escaped = String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    const ansiMap = {
        "30": "color: #4b5563;",
        "31": "color: #f87171;",
        "32": "color: #4ade80;",
        "33": "color: #facc15;",
        "34": "color: #60a5fa;",
        "35": "color: #c084fc;",
        "36": "color: #22d3ee;",
        "37": "color: #f3f4f6;",
        "90": "color: #6b7280;",
        "91": "color: #fca5a5;",
        "92": "color: #86efac;",
        "93": "color: #fde047;",
        "94": "color: #93c5fd;",
        "95": "color: #d8b4fe;",
        "96": "color: #67e8f9;",
        "97": "color: #ffffff;",
        "1": "font-weight: bold;",
        "2": "opacity: 0.7;",
        "3": "font-style: italic;",
        "4": "text-decoration: underline;"
    };

    escaped = escaped.replace(/\x1b\[0?m/g, "</span>");
    escaped = escaped.replace(/\x1b\[([0-9;]+)m/g, (match, codes) => {
        const parts = codes.split(";");
        let styles = [];
        for (const c of parts) {
            if (ansiMap[c]) styles.push(ansiMap[c]);
        }
        return styles.length > 0 ? `<span style="${styles.join(" ")}">` : "";
    });
    return escaped;
}
window.parseAnsiToHtml = parseAnsiToHtml;

/**
 * WebSocket Terminal Client
 * Connects to /ws/terminal for live command execution and interactive shell streaming
 */
class TerminalWebSocketClient {
    constructor(options = {}) {
        this.url = options.url || `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/terminal`;
        this.token = options.token || localStorage.getItem("alfa_session_token") || localStorage.getItem("alfa_auth_token") || "";
        this.ws = null;
        this.onMessage = options.onMessage || null;
        this.onOpen = options.onOpen || null;
        this.onClose = options.onClose || null;
        this.onError = options.onError || null;
        this.pingTimer = null;
    }

    connect() {
        const fullUrl = this.token ? `${this.url}?token=${encodeURIComponent(this.token)}` : this.url;
        try {
            this.ws = new WebSocket(fullUrl);
            this.ws.onopen = (e) => {
                if (this.onOpen) this.onOpen(e);
                this.pingTimer = setInterval(() => {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({ type: "ping" }));
                    }
                }, 15000);
            };
            this.ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (this.onMessage) this.onMessage(data);
                } catch {
                    if (this.onMessage) this.onMessage({ type: "raw", data: e.data });
                }
            };
            this.ws.onclose = (e) => {
                clearInterval(this.pingTimer);
                if (this.onClose) this.onClose(e);
            };
            this.ws.onerror = (e) => {
                if (this.onError) this.onError(e);
            };
        } catch (err) {
            console.error("Terminal WebSocket connection failed:", err);
        }
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(typeof data === "string" ? data : JSON.stringify(data));
        }
    }

    disconnect() {
        clearInterval(this.pingTimer);
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}
window.TerminalWebSocketClient = TerminalWebSocketClient;

/**
 * WebSocket Logs Streaming Client
 * Connects to /ws/logs?unit=... for live journal logs
 */
class LogsWebSocketClient {
    constructor(unit = "telegram-ai-bot.service", onLog = null) {
        this.unit = unit;
        this.onLog = onLog;
        this.ws = null;
    }

    connect() {
        const token = localStorage.getItem("alfa_session_token") || localStorage.getItem("alfa_auth_token") || "";
        const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
        let url = `${wsProto}//${location.host}/ws/logs?unit=${encodeURIComponent(this.unit)}`;
        if (token) url += `&token=${encodeURIComponent(token)}`;
        try {
            this.ws = new WebSocket(url);
            this.ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (this.onLog) this.onLog(data);
                } catch {
                    if (this.onLog) this.onLog({ line: e.data });
                }
            };
        } catch (err) {
            console.error("Logs WebSocket failed:", err);
        }
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}
window.LogsWebSocketClient = LogsWebSocketClient;

export async function fetchServiceLogs() {
    const svc = document.getElementById('log-service-select').value;
    const lines = document.getElementById('log-lines-select').value;
    const logBox = document.getElementById('service-logs-viewer');
    try {
        const res = await fetch(`/api/services/logs?service=${svc}&lines=${lines}`);
        const data = await res.json();
        if (data.status === 'success') {
            logBox.innerText = data.logs || '(Log kosong)';
            logBox.scrollTop = logBox.scrollHeight;
        }
    } catch (err) {
        logBox.innerText = `Error memuat log: ${err.message}`;
    }
}

export function copyLogsToClipboard() {
    const text = document.getElementById('service-logs-viewer').innerText;
    navigator.clipboard.writeText(text);
    showToast('Log service disalin ke clipboard!', 'info');
}

// Toggle Linux CLI Drawer
export function toggleChatCliDrawer(forceState = null) {
    const drawer = document.getElementById('chat-cli-drawer');
    if (!drawer) return;
    if (forceState === false || (forceState === null && !drawer.classList.contains('hidden'))) {
        drawer.classList.add('hidden');
    } else {
        drawer.classList.remove('hidden');
        document.getElementById('chat-cli-input')?.focus();
    }
    lucide.createIcons();
}

export function handleCliInputKeyDown(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        runCliTerminalCommand();
    }
}

export async function runCliTerminalCommand() {
    const input = document.getElementById('chat-cli-input');
    const outDiv = document.getElementById('chat-cli-output');
    const btn = document.getElementById('chat-cli-run-btn');
    if (!input || !outDiv) return;

    const cmd = input.value.trim();
    if (!cmd) return;

    btn.disabled = true;
    btn.innerText = 'Menjalankan...';
    outDiv.classList.remove('hidden');
    outDiv.innerHTML = `<span class="text-slate-400 animate-pulse">Menjalankan \`${cmd}\` di Linux Host...</span>`;

    try {
        const res = await fetch('/api/system/cli-exec', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        btn.disabled = false;
        btn.innerText = 'Jalankan';

        const result = data.result || {};
        const isSuccess = result.status === 'success' && result.exit_code === 0;
        const stdout = result.stdout || result.output || '';
        const stderr = result.stderr ? `\n[STDERR]: ${result.stderr}` : '';

        outDiv.innerHTML = `
            <div class="flex items-center justify-between pb-1 mb-1 border-b border-white/10 text-[10px] text-slate-400">
                <span class="${isSuccess ? 'text-emerald-400' : 'text-rose-400'} font-bold">
                    ${isSuccess ? '✓ Exit 0 (Sukses)' : `✗ Exit ${result.exit_code || 1} (Error)`}
                </span>
                <span>⏱️ ${data.execution_time_ms} ms • 📁 ${data.current_dir || '~'}</span>
            </div>
            <div>${stdout + stderr || '(Perintah selesai tanpa output terminal)'}</div>
        `;
        showToast(`CLI: Perintah selesai dalam ${data.execution_time_ms} ms!`, isSuccess ? 'success' : 'warning');
    } catch (err) {
        btn.disabled = false;
        btn.innerText = 'Jalankan';
        outDiv.innerHTML = `<span class="text-rose-400">Error: ${err.message}</span>`;
        showToast('Gagal menjalankan CLI: ' + err.message, 'error');
    }
}

// ── SWARM LIVE TERMINAL ──
let _swLastSeq = 0, _swAutoScroll = true;
const SW_TAG_STYLE = {
    SESSION: 'text-cyan-300 font-bold',
    PLAN:    'text-violet-300',
    DIALOG:  'text-slate-300',
    EXEC:    'text-amber-300',
    TOOL:    'text-sky-300',
    FILE:    'text-emerald-300 font-bold',
    VERIFY:  '',
    DONE:    'text-emerald-400 font-bold',
    ERROR:   'text-rose-400 font-bold',
};

export async function fetchSwarmLive() {
    if (document.hidden) return;
    const box = document.getElementById('sw-terminal');
    const arena = document.getElementById('swarm-arena');
    if (!box && !arena) return;
    try {
        const res = await fetch(`/api/swarm/live?since=${_swLastSeq}`);
        const data = await res.json();

        // Update Swarm Live Arena Visualizer DOM elements
        updateSwarmArena(data);

        const dot = document.getElementById('sw-live-dot');
        if (dot) {
            const running = data.running;
            dot.className = `w-2 h-2 rounded-full ${running ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`;
        }
        const entries = data.entries || [];
        if (!box) return;
        if (entries.length === 0) {
            // hapus placeholder menunggu bila ada
            const p = box.querySelector('p.text-slate-600');
            if (p) p.remove();
            return;
        }
        if (_swLastSeq === 0) box.innerHTML = '';
        for (const e of entries) {
            _swLastSeq = Math.max(_swLastSeq, e.i);
            const cls = SW_TAG_STYLE[e.tag] ?? 'text-slate-300';
            const line = document.createElement('div');
            line.className = 'whitespace-pre-wrap break-words';
            line.innerHTML = `<span class="text-slate-600">[${e.ts}]</span> <span class="${cls}">${escAttr(e.text)}</span>`;
            const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
            if (!_swAutoScroll && !nearBottom && false) { /* pause mode */ }
            box.appendChild(line);
        }
        while (box.children.length > 300) box.removeChild(box.firstChild);
        if (_swAutoScroll || true) box.scrollTop = box.scrollHeight;
        void(0);
    } catch (err) { /* silent */ }
}

export function toggleSwLiveScroll() {
    _swAutoScroll = !_swAutoScroll;
    const b = document.getElementById('btn-sw-scroll');
    if (b) {
        b.classList.toggle('text-emerald-300', _swAutoScroll);
        b.classList.toggle('border-emerald-500/40', _swAutoScroll);
        b.innerText = _swAutoScroll ? 'AUTO-SCROLL' : 'PAUSED';
    }
}

export function clearSwLiveView() {
    const box = document.getElementById('sw-terminal');
    if (box) box.innerHTML = '<p class="text-slate-600">// tampilan dibersihkan (log tetap berjalan)</p>';
}

// ── TELEMETRY WEBSOCKET & STATUS INDICATOR ──
let _telemetryWs = null;
let _telemetryPingStart = 0;
let _telemetryReconnectDelay = 2000;
let _telemetryReconnectTimer = null;

function initTelemetryWebSocket() {
    const badge = document.getElementById('ws-status-badge');
    const dot = document.getElementById('ws-status-dot');
    const txt = document.getElementById('ws-status-text');
    const lat = document.getElementById('ws-latency-text');
    if (!badge || !dot || !txt) return;

    if (_telemetryWs) {
        try { _telemetryWs.close(); } catch (_) {}
        _telemetryWs = null;
    }

    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const token = localStorage.getItem("alfa_session_token") || localStorage.getItem("alfa_auth_token") || "";
    let url = `${wsProto}//${location.host}/ws/broadcast`;
    if (token) url += `?token=${encodeURIComponent(token)}`;

    function setBadgeState(state, text, latencyMs = null) {
        if (!badge || !dot || !txt) return;
        if (state === 'connected') {
            badge.className = "px-2.5 py-1.5 rounded-xl bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-bold flex items-center gap-1.5 shadow-sm transition-all";
            dot.className = "w-2 h-2 rounded-full bg-emerald-400 animate-pulse";
            txt.innerText = text || "Live WS";
            if (lat) {
                lat.innerText = latencyMs !== null ? `${latencyMs}ms` : "";
                lat.className = "text-[10px] text-emerald-400/80 font-mono hidden md:inline";
            }
        } else if (state === 'connecting') {
            badge.className = "px-2.5 py-1.5 rounded-xl bg-amber-500/10 text-amber-300 border border-amber-500/30 font-bold flex items-center gap-1.5 shadow-sm transition-all";
            dot.className = "w-2 h-2 rounded-full bg-amber-400 animate-pulse";
            txt.innerText = text || "WS Connect...";
            if (lat) lat.innerText = "";
        } else {
            badge.className = "px-2.5 py-1.5 rounded-xl bg-rose-500/10 text-rose-300 border border-rose-500/30 font-bold flex items-center gap-1.5 shadow-sm transition-all";
            dot.className = "w-2 h-2 rounded-full bg-rose-400";
            txt.innerText = text || "WS Offline";
            if (lat) lat.innerText = "";
        }
    }

    setBadgeState('connecting');

    try {
        _telemetryWs = new WebSocket(url);

        _telemetryWs.onopen = () => {
            _telemetryReconnectDelay = 2000;
            setBadgeState('connected', 'Live WS');
            sendTelemetryPing();
        };

        _telemetryWs.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === "pong") {
                    const rtt = Math.max(1, Math.round(performance.now() - _telemetryPingStart));
                    setBadgeState('connected', 'Live WS', rtt);
                }
            } catch (_) {}
        };

        _telemetryWs.onclose = () => {
            setBadgeState('disconnected', 'WS Reconnecting...');
            scheduleTelemetryReconnect();
        };

        _telemetryWs.onerror = () => {
            setBadgeState('disconnected', 'WS Error');
        };
    } catch (err) {
        setBadgeState('disconnected', 'WS Error');
        scheduleTelemetryReconnect();
    }
}

function sendTelemetryPing() {
    if (_telemetryWs && _telemetryWs.readyState === WebSocket.OPEN) {
        _telemetryPingStart = performance.now();
        _telemetryWs.send("ping");
        setTimeout(sendTelemetryPing, 10000);
    }
}

function scheduleTelemetryReconnect() {
    clearTimeout(_telemetryReconnectTimer);
    _telemetryReconnectTimer = setTimeout(() => {
        initTelemetryWebSocket();
        _telemetryReconnectDelay = Math.min(_telemetryReconnectDelay * 1.5, 30000);
    }, _telemetryReconnectDelay);
}

// ── LIVE LOGS WEBSOCKET STREAMING ──
let _liveLogsClient = null;
let _isLiveLogsStreaming = false;

export function toggleLiveLogsStream() {
    const btn = document.getElementById('btn-toggle-live-logs');
    const dot = document.getElementById('live-logs-dot');
    const label = document.getElementById('live-logs-label');
    const viewer = document.getElementById('service-logs-viewer');
    const svcSelect = document.getElementById('log-service-select');
    const svc = svcSelect ? svcSelect.value : 'telegram-ai-bot.service';

    if (_isLiveLogsStreaming) {
        if (_liveLogsClient) {
            _liveLogsClient.disconnect();
            _liveLogsClient = null;
        }
        _isLiveLogsStreaming = false;
        if (btn) {
            btn.className = "px-2.5 py-1.5 bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border border-white/10 rounded-lg font-mono text-xs flex items-center gap-1.5 transition-all cursor-pointer";
        }
        if (dot) {
            dot.className = "w-2 h-2 rounded-full bg-slate-400";
        }
        if (label) {
            label.innerText = "Live Stream";
        }
        {
            showToast("Streaming log WebSocket dihentikan.", "info");
        }
    } else {
        _isLiveLogsStreaming = true;
        if (btn) {
            btn.className = "px-2.5 py-1.5 bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 rounded-lg font-mono text-xs flex items-center gap-1.5 transition-all cursor-pointer shadow-sm shadow-emerald-500/10";
        }
        if (dot) {
            dot.className = "w-2 h-2 rounded-full bg-emerald-400 animate-pulse";
        }
        if (label) {
            label.innerText = "Streaming...";
        }

        if (viewer) {
            viewer.innerHTML = `<span class="text-emerald-400 font-bold">[WS LOGS] Terhubung ke stream live log: ${svc}...</span>\n`;
        }

        _liveLogsClient = new LogsWebSocketClient(svc, (data) => {
            if (!viewer) return;
            const line = data.data || data.line || (typeof data === "string" ? data : "");
            if (!line) return;
            const parsed = parseAnsiToHtml(line);
            viewer.innerHTML += parsed;
            viewer.scrollTop = viewer.scrollHeight;
        });

        _liveLogsClient.connect();
        {
            showToast(`Streaming log ${svc} aktif via WebSocket!`, "success");
        }
    }
}

window.toggleLiveLogsStream = toggleLiveLogsStream;
window.initTelemetryWebSocket = initTelemetryWebSocket;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTelemetryWebSocket);
} else {
    initTelemetryWebSocket();
}


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.clearSwLiveView = clearSwLiveView;
window.copyLogsToClipboard = copyLogsToClipboard;
window.fetchServiceLogs = fetchServiceLogs;
window.fetchSwarmLive = fetchSwarmLive;
window.handleCliInputKeyDown = handleCliInputKeyDown;
window.runCliTerminalCommand = runCliTerminalCommand;
window.toggleChatCliDrawer = toggleChatCliDrawer;
window.toggleLiveLogsStream = toggleLiveLogsStream;
window.toggleSwLiveScroll = toggleSwLiveScroll;
