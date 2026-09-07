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
        this.token = options.token || localStorage.getItem("alfa_session_token") || "";
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
        const token = localStorage.getItem("alfa_session_token") || "";
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

async function fetchServiceLogs() {
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

function copyLogsToClipboard() {
    const text = document.getElementById('service-logs-viewer').innerText;
    navigator.clipboard.writeText(text);
    showToast('Log service disalin ke clipboard!', 'info');
}

// Toggle Linux CLI Drawer
function toggleChatCliDrawer(forceState = null) {
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

function handleCliInputKeyDown(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        runCliTerminalCommand();
    }
}

async function runCliTerminalCommand() {
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

async function fetchSwarmLive() {
    if (document.hidden) return;
    const box = document.getElementById('sw-terminal');
    if (!box) return;
    try {
        const res = await fetch(`/api/swarm/live?since=${_swLastSeq}`);
        const data = await res.json();
        const dot = document.getElementById('sw-live-dot');
        if (dot) {
            const running = data.running;
            dot.className = `w-2 h-2 rounded-full ${running ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`;
        }
        const entries = data.entries || [];
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

function toggleSwLiveScroll() {
    _swAutoScroll = !_swAutoScroll;
    const b = document.getElementById('btn-sw-scroll');
    if (b) {
        b.classList.toggle('text-emerald-300', _swAutoScroll);
        b.classList.toggle('border-emerald-500/40', _swAutoScroll);
        b.innerText = _swAutoScroll ? 'AUTO-SCROLL' : 'PAUSED';
    }
}

function clearSwLiveView() {
    const box = document.getElementById('sw-terminal');
    if (box) box.innerHTML = '<p class="text-slate-600">// tampilan dibersihkan (log tetap berjalan)</p>';
}
