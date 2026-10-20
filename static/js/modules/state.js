
/* ==== ES MODULE BRIDGE ==== */
import { fetchAffiliateCampaigns } from './affiliate.js';
import { fetchAgents, fetchAntigravityAccounts, fetchArtifacts, fetchDynamicPlugins, fetchGuardian, fetchKeys, fetchMemory, fetchServices, fetchSettings, fetchSuperpowersSkills, fetchTokenUsage, fetchWaFormats, fetchWaMediaRules, loadMeetingFolders, wsInit } from '../app.js';
import { loadChatAvailableModels } from '../chat.js';
import { fetchGdriveFiles, fetchGdriveStatus } from './gdrive.js';
import { fetchBudget, fetchSites, initCanvas } from './pipelines_sites.js';
import { fetchScraperBatches } from './scraper.js';
import { initTelemetryChart, startTelemetryPolling } from './telemetry.js';
import { fetchSwarmLive } from '../terminal.js';
import { allToolsData, fetchTools } from '../tools.js';
import { fetchPasskeyStatus, fetchVaultSecrets } from './vault_security.js';
/**
 * ==============================================================================
 * ALFA COMMAND CENTER - STATE & SESSION STORE MODULE (state.js)
 * ==============================================================================
 * Manages Alpine.js reactive store, session persistence, active tab state,
 * dark/light theme switching, and global UI notification state.
 */

// Helper: Escape string untuk konteks HTML (teks node maupun atribut).
//
// Escaping lengkap: & < > " ' — versi lama hanya escape & " < sehingga
// karakter ' dan > bisa keluar dari atribut dan membuka celah injeksi.
export function escHtml(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// Backwards-compatible alias — dipakai luas di seluruh app.
export function escAttr(s) {
    return escHtml(s);
}

// Helper: Render Markdown → HTML → sanitasi (DOMPurify).
//
// Output LLM (rapat, chat, consensus) disimpan ke DB lalu dirender ke
// dashboard. Tanpa sanitasi, satu output LLM berisi
// `<img src=x onerror=...>` menjadi stored XSS yang mengeksekusi di
// browser setiap operator. Bila DOMPurify tidak tersedia, jatuh ke escHtml
// (aman, walau tanpa format markdown).
export function safeMarkdown(src) {
    const raw = String(src ?? "");
    if (typeof marked === "undefined" || !marked.parse) return escHtml(raw);
    let html;
    try {
        html = marked.parse(raw);
    } catch (e) {
        return escHtml(raw);
    }
    if (typeof DOMPurify === "undefined" || !DOMPurify.sanitize) return escHtml(raw);
    try {
        return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
    } catch (e) {
        return escHtml(raw);
    }
}

// Helper: Format large token counts into human-readable strings
export function fmtTokens(n) {
    n = Number(n) || 0;
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
}

// URL Query Parameter Auth Check
(function checkUrlAuth() {
    try {
        if (typeof window !== "undefined" && window.location) {
            const urlParams = new URLSearchParams(window.location.search);
            const urlToken = urlParams.get('token') || urlParams.get('auth');
            if (urlToken) {
                localStorage.setItem('alfa_auth_token', urlToken);
                localStorage.setItem('alfa_session_token', urlToken);
            }
        }
    } catch (e) {
        console.debug('Failed to parse URL token:', e);
    }
})();

// Central Reactive App Store
const _initToken = localStorage.getItem("alfa_auth_token") || localStorage.getItem("alfa_session_token") || null;
export const AlfaStore = {
    theme: localStorage.getItem("alfa_theme") || "dark",
    activeTab: localStorage.getItem("alfa_active_tab") || "overview",
    stats: {},
    services: [],
    models: [],
    notifications: [],
    session: {
        token: _initToken,
        user: null,
        isAuthenticated: !!_initToken
    }
};

// Tab titles mapping for breadcrumbs and headers
const tabTitles = {
    'overview': 'Telemetry & Live Overview',
    'sovereign': 'ALFA Sovereign Console (Hermes • OpenClaw • OpenHuman • REA)',
    'swarm': 'AI Swarm — Eksekusi Langsung',
    'scraper': 'Master Scraper Pro Studio',
    'affiliate': 'Affiliate Sales Studio',
    'vault': 'Passkey Vault & Security',
    'keys': 'API Keys Manager',
    // Jumlah tool TIDAK di-hardcode — diisi dari /api/tools (lihat tools.js).
    // Nilai lama "126 Tools Catalog & Sandbox" sudah melenceng jauh dari
    // runtime (173) karena tidak pernah diperbarui.
    'tools': 'Memuat Tools Catalog...',
    'memory': 'Second Brain Memory',
    'artifacts': 'File Artifacts & Storage',
    'sites': 'Galeri Situs & Kuota',
    'gdrive': 'Google Drive & Google Cloud Suite',
    'services': 'System Services & Background Tasks',
    'canvas': 'Pipeline Canvas Studio — Drag & Drop Workflow',
    'guardian': 'Guardian Defense & Integrity',
    'console': 'Chat Agent ALFA (Multimodal Live)',
    'waformat': 'WA Laporan & Format SHEETS',
    'settings': 'System Settings & Environment Config'
};

// Initialize Alpine.js integration if available or on event
export function initAlpineState() {
    if (window.Alpine) {
        window.Alpine.store("alfa", {
            theme: AlfaStore.theme,
            activeTab: AlfaStore.activeTab,
            stats: AlfaStore.stats,
            services: AlfaStore.services,
            models: AlfaStore.models,
            session: AlfaStore.session,
            setTheme(t) {
                this.theme = t;
                setTheme(t);
            },
            switchTab(tab) {
                this.activeTab = tab;
                switchTab(tab);
            }
        });
    }
}

document.addEventListener("alpine:init", initAlpineState);
if (window.Alpine) {
    initAlpineState();
}

// ==================== THEME SWITCHER LOGIC ====================

export function initTheme() {
    const savedTheme = localStorage.getItem('alfa_theme') || 'dark';
    setTheme(savedTheme, false);
}

export function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    const newTheme = isDark ? 'light' : 'dark';
    setTheme(newTheme, true);
}

function setTheme(theme, showToastNotification = true) {
    const html = document.documentElement;
    const themeIcon = document.getElementById('theme-icon');
    const themeLabel = document.getElementById('theme-label');
    const sidebarThemeIcon = document.getElementById('sidebar-theme-icon');
    const sidebarThemeText = document.getElementById('sidebar-theme-text');

    if (theme === 'dark') {
        html.classList.add('dark');
        localStorage.setItem('alfa_theme', 'dark');
        AlfaStore.theme = 'dark';
        if (themeIcon) themeIcon.innerText = '🌙';
        if (themeLabel) themeLabel.innerText = 'Dark Mode';
        if (sidebarThemeIcon) sidebarThemeIcon.innerText = '🌙';
        if (sidebarThemeText) sidebarThemeText.innerText = 'Gelap 🌙';
    } else {
        html.classList.remove('dark');
        localStorage.setItem('alfa_theme', 'light');
        AlfaStore.theme = 'light';
        if (themeIcon) themeIcon.innerText = '☀️';
        if (themeLabel) themeLabel.innerText = 'Light Mode';
        if (sidebarThemeIcon) sidebarThemeIcon.innerText = '☀️';
        if (sidebarThemeText) sidebarThemeText.innerText = 'Terang ☀️';
    }

    if (window.Alpine && window.Alpine.store("alfa")) {
        window.Alpine.store("alfa").theme = theme;
    }

    if (showToastNotification) {
        showToast(`Beralih ke Mode ${theme === 'dark' ? 'Gelap 🌙' : 'Terang ☀️'}`, 'info');
    }
}

// Early theme check to avoid flash
initTheme();

// ==================== TAB NAVIGATION & PERSISTENCE ====================

export function switchTab(tabId) {
    document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('text-cyan-300', 'bg-cyan-500/10', 'border', 'border-cyan-500/30', 'shadow-glow-cyan', 'active');
        el.classList.add('text-slate-400');
    });

    const targetView = document.getElementById(`view-${tabId}`);
    const targetBtn = document.getElementById(`tab-btn-${tabId}`);
    if (targetView) targetView.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.remove('text-slate-400');
        targetBtn.classList.add('text-cyan-300', 'bg-cyan-500/10', 'border', 'border-cyan-500/30', 'shadow-glow-cyan', 'active');
    }

    // Sinkron highlight bottom-nav HP
    document.querySelectorAll('.mnav').forEach(el => {
        const on = el.getAttribute('data-mtab') === tabId;
        el.classList.toggle('text-cyan-300', on);
        el.classList.toggle('text-slate-400', !on);
    });

    // Persist active tab
    localStorage.setItem('alfa_active_tab', tabId);
    AlfaStore.activeTab = tabId;
    if (window.Alpine && window.Alpine.store("alfa")) {
        window.Alpine.store("alfa").activeTab = tabId;
    }

    // Update Breadcrumb Title
    const titleEl = document.getElementById('top-current-tab-title');
    if (titleEl && tabTitles[tabId]) {
        titleEl.innerText = tabTitles[tabId];
    }

    // Close sidebar drawer on mobile after clicking
    if (window.innerWidth < 1024) {
        toggleSidebar(false);
    }

    // Lazy load tab data based on active view
    if (tabId === 'overview') {
        initTelemetryChart();
        startTelemetryPolling();
        fetchServices();
    }
    if (tabId === 'console' ) loadChatAvailableModels();
    if (tabId === 'tools') {
        if (typeof allToolsData !== 'undefined' && allToolsData.length === 0 ) fetchTools();
        fetchDynamicPlugins();
        fetchSuperpowersSkills();
        // Judul tab diisi dari jumlah tool runtime (bukan angka hardcode).
        if (typeof allToolsData !== 'undefined' && allToolsData.length) {
            tabTitles.tools = `${allToolsData.length} Tools Catalog & Sandbox`;
        }
    }
    if (tabId === 'services' ) fetchServices();
    if (tabId === 'canvas' ) initCanvas();
    if (tabId === 'memory' ) fetchMemory();
    if (tabId === 'sites') {
        fetchSites();
        fetchBudget();
    }
    if (tabId === 'artifacts') {
        fetchArtifacts();
        if (!wsInit._done) { wsInit._done = true; wsInit(); }
    }
    if (tabId === 'guardian' ) fetchGuardian();
    if (tabId === 'swarm') {
        fetchAgents();
        fetchKeys();
        fetchSwarmLive();
        loadMeetingFolders();
    }
    if (tabId === 'affiliate' ) fetchAffiliateCampaigns();
    if (tabId === 'keys') {
        fetchKeys();
        fetchTokenUsage();
        fetchAntigravityAccounts();
    }
    if (tabId === 'waformat') {
        fetchWaFormats();
        fetchWaMediaRules();
    }
    if (tabId === 'vault') {
        fetchVaultSecrets();
        fetchPasskeyStatus();
    }
    if (tabId === 'scraper' ) fetchScraperBatches();
    if (tabId === 'gdrive') {
        fetchGdriveStatus();
        fetchGdriveFiles();
    }
    if (tabId === 'settings') {
        fetchSettings();
        fetchAgents();
        fetchKeys();
    }

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

export function restoreActiveTab() {
    const savedTab = localStorage.getItem('alfa_active_tab');
    if (savedTab && tabTitles[savedTab]) {
        switchTab(savedTab);
    }
}

// ==================== SIDEBAR & UI MODALS ====================

export function toggleSidebar(show = null) {
    const sidebar = document.getElementById('main-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar) return;

    const isCurrentlyHidden = sidebar.classList.contains('-translate-x-full');
    const willShow = show !== null ? show : isCurrentlyHidden;

    if (willShow) {
        sidebar.classList.remove('-translate-x-full');
        backdrop?.classList.remove('hidden');
    } else {
        sidebar.classList.add('-translate-x-full');
        backdrop?.classList.add('hidden');
    }
}

// Toast Notification System
export function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    const colors = {
        info: 'border-cyan-500/40 bg-dark-900/90 text-cyan-300',
        success: 'border-emerald-500/40 bg-dark-900/90 text-emerald-300',
        error: 'border-rose-500/40 bg-dark-900/90 text-rose-300',
        warning: 'border-amber-500/40 bg-dark-900/90 text-amber-300'
    };
    toast.className = `toast px-4 py-3 rounded-xl border backdrop-blur-xl shadow-2xl font-mono text-xs flex items-center gap-2.5 ${colors[type] || colors.info}`;
    toast.innerHTML = `<span>${type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'}</span> <span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Header Live Clock
function updateClock() {
    const clockEl = document.getElementById('header-clock');
    if (!clockEl) return;
    const now = new Date();
    clockEl.innerText = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' WIB';
}
setInterval(updateClock, 1000);
updateClock();

// ==================== SESSION / AUTH STATE ====================

function getSessionToken() {
    return localStorage.getItem('alfa_auth_token') || localStorage.getItem('alfa_session_token') || '';
}

function setSessionToken(token) {
    if (token) {
        localStorage.setItem('alfa_auth_token', token);
        localStorage.setItem('alfa_session_token', token);
        AlfaStore.session.token = token;
        AlfaStore.session.isAuthenticated = true;
    } else {
        clearSessionToken();
    }
}

function clearSessionToken() {
    localStorage.removeItem('alfa_auth_token');
    localStorage.removeItem('alfa_session_token');
    AlfaStore.session.token = null;
    AlfaStore.session.isAuthenticated = false;
    AlfaStore.session.user = null;
}

// Transparent fetch interceptor: attaches credentials & session headers
(function initFetchInterceptor() {
    const origFetch = window.fetch;
    if (typeof origFetch !== "function") return;
    window.fetch = function(resource, init) {
        const token = getSessionToken();
        if (typeof Request !== "undefined" && resource instanceof Request) {
            if (token && resource.headers && typeof resource.headers.has === "function" && !resource.headers.has('Authorization')) {
                try {
                    resource.headers.set('Authorization', `Bearer ${token}`);
                    resource.headers.set('X-Session-Token', token);
                } catch (e) {}
            }
            return origFetch.call(this, resource, init);
        }
        const options = init ? { ...init } : {};
        if (!options.credentials) {
            options.credentials = 'same-origin';
        }
        if (token) {
            if (typeof Headers !== "undefined") {
                const headers = new Headers(options.headers || {});
                if (!headers.has('Authorization')) {
                    headers.set('Authorization', `Bearer ${token}`);
                }
                if (!headers.has('X-Session-Token')) {
                    headers.set('X-Session-Token', token);
                }
                options.headers = headers;
            } else {
                options.headers = options.headers || {};
                if (!options.headers['Authorization']) {
                    options.headers['Authorization'] = `Bearer ${token}`;
                }
                if (!options.headers['X-Session-Token']) {
                    options.headers['X-Session-Token'] = token;
                }
            }
        }
        return origFetch.call(this, resource, options);
    };
})();

// ==================== SWARM LIVE ARENA VISUALIZER HOOK ====================

export function updateSwarmArena(data) {
    if (!data) return;
    const arena = document.getElementById('swarm-arena');
    if (!arena) return;

    const isRunning = Boolean(data.running);
    const activeSpeaker = data.active_speaker || null;
    const stage = data.stage || 'idle';
    const consensusPct = Math.max(0, Math.min(100, Number(data.consensus_percent) || 0));
    const agentStates = data.agent_states || {};

    // 1. Update Arena Status Badge & Active Speaker Label
    const statusBadge = document.getElementById('swarm-arena-status-badge');
    if (statusBadge) {
        if (!isRunning) {
            statusBadge.className = 'text-[10px] px-2.5 py-0.5 rounded-full font-mono font-bold bg-slate-500/20 text-slate-400 border border-white/10';
            statusBadge.innerText = 'ARENA STANDBY';
        } else {
            statusBadge.className = 'text-[10px] px-2.5 py-0.5 rounded-full font-mono font-bold bg-violet-500/20 text-violet-300 border border-violet-500/40 animate-pulse';
            statusBadge.innerText = `SWARM ACTIVE // ${stage.toUpperCase()}`;
        }
    }

    const speakerLabel = document.getElementById('swarm-active-speaker-label');
    if (speakerLabel) {
        speakerLabel.innerText = activeSpeaker ? activeSpeaker : (isRunning ? 'Orchestrating...' : 'Standby');
    }

    // 2. Highlight Stage Progress Tracker Pills
    const stagesOrder = ['plan', 'debate', 'vote', 'consensus', 'execute'];
    const currentStageIdx = stagesOrder.indexOf(stage);

    stagesOrder.forEach((stg, idx) => {
        const pill = document.getElementById(`stage-pill-${stg}`);
        if (!pill) return;

        pill.classList.remove('is-active-stage', 'is-completed-stage');
        const dot = pill.querySelector('span');

        if (!isRunning && stage === 'idle') {
            pill.className = 'stage-pill px-3 py-1.5 rounded-full border border-white/10 bg-white/5 text-slate-400 font-mono text-xs flex items-center gap-1.5';
            if (dot) dot.className = 'w-1.5 h-1.5 rounded-full bg-slate-500';
        } else if (idx === currentStageIdx) {
            pill.classList.add('is-active-stage');
            if (dot) dot.className = 'w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping';
        } else if (currentStageIdx > -1 && idx < currentStageIdx) {
            pill.classList.add('is-completed-stage');
            if (dot) dot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400';
        } else {
            pill.className = 'stage-pill px-3 py-1.5 rounded-full border border-white/10 bg-white/5 text-slate-400 font-mono text-xs flex items-center gap-1.5';
            if (dot) dot.className = 'w-1.5 h-1.5 rounded-full bg-slate-600';
        }
    });

    // 3. Update Consensus Agreement Bar
    const pctEl = document.getElementById('swarm-consensus-percent');
    if (pctEl) {
        pctEl.innerText = `${consensusPct}%`;
    }

    const fillEl = document.getElementById('swarm-consensus-fill');
    if (fillEl) {
        fillEl.style.width = `${consensusPct}%`;
        if (consensusPct >= 80) {
            fillEl.className = 'h-full rounded-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-emerald-300 transition-all duration-500 shadow-glow-emerald';
        } else if (consensusPct >= 40) {
            fillEl.className = 'h-full rounded-full bg-gradient-to-r from-violet-500 via-cyan-400 to-blue-400 transition-all duration-500 shadow-glow-cyan';
        } else {
            fillEl.className = 'h-full rounded-full bg-gradient-to-r from-violet-600 to-purple-500 transition-all duration-500';
        }
    }

    const consensusText = document.getElementById('swarm-consensus-text');
    if (consensusText) {
        if (!isRunning) {
            consensusText.innerText = consensusPct === 100 ? '✅ Misi tuntas — konsensus 100% tercapai.' : 'Menunggu deliberasi tim & konsensus...';
        } else if (stage === 'plan') {
            consensusText.innerText = '📋 Alpha Lead sedang memetakan dekomposisi rencana...';
        } else if (stage === 'debate') {
            consensusText.innerText = '💬 Deliberasi persona aktif: analisis data & sudut pandang berlawanan...';
        } else if (stage === 'vote') {
            consensusText.innerText = '🗳️ Voting matriks berjalan: mengevaluasi opsi solusi terbaik...';
        } else if (stage === 'consensus') {
            consensusText.innerText = '🤝 Konsensus tercapai: tim menyepakati strategi final...';
        } else if (stage === 'execute') {
            consensusText.innerText = '⚡ Eksekusi aktif: perkakas sandbox & penulisan berkas berlangsung...';
        }
    }

    // 4. Update Agent Cards (Commander, Researcher, Critic, Executor)
    const personaIds = ['commander', 'researcher', 'critic', 'executor'];
    personaIds.forEach(id => {
        const card = document.getElementById(`agent-card-${id}`);
        const statusEl = document.getElementById(`agent-status-${id}`);
        if (!card) return;

        const st = (agentStates[id] || (isRunning ? 'waiting' : 'idle')).toLowerCase();
        const isSpeaking = st === 'speaking';

        if (isSpeaking) {
            card.classList.add('is-speaking');
            if (statusEl) {
                statusEl.className = 'text-[9px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse';
                statusEl.innerText = 'SPEAKING ⚡';
            }
        } else {
            card.classList.remove('is-speaking');
            if (statusEl) {
                if (!isRunning) {
                    statusEl.className = 'text-[9px] font-mono font-bold px-2 py-0.5 rounded bg-white/5 text-slate-400 border border-white/10';
                    statusEl.innerText = 'STANDBY';
                } else if (st === 'done') {
                    statusEl.className = 'text-[9px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
                    statusEl.innerText = 'DONE ✓';
                } else {
                    statusEl.className = 'text-[9px] font-mono font-bold px-2 py-0.5 rounded bg-white/5 text-slate-400 border border-white/10';
                    statusEl.innerText = 'LISTENING';
                }
            }
        }
    });

    // 5. Update Current Agent Thought & Quote Bubble
    const entries = Array.isArray(data.entries) ? data.entries : [];
    if (entries.length > 0) {
        let lastThoughtEntry = null;
        for (let i = entries.length - 1; i >= 0; i--) {
            const ent = entries[i];
            const tag = (ent.tag || '').toUpperCase();
            if (['DIALOG', 'PLAN', 'EXEC', 'QA', 'CONSENSUS', 'VOTE'].includes(tag) || (ent.text && ent.text.includes('💬'))) {
                lastThoughtEntry = ent;
                break;
            }
        }

        if (lastThoughtEntry) {
            const thoughtText = lastThoughtEntry.text || '';
            const activeThoughtEl = document.getElementById('swarm-active-thought');
            const speakerTag = document.getElementById('swarm-thought-speaker-badge');

            if (activeThoughtEl) {
                activeThoughtEl.innerText = thoughtText;
            }
            if (speakerTag) {
                speakerTag.innerText = activeSpeaker || lastThoughtEntry.tag || 'AGENT';
            }

            if (activeSpeaker) {
                const spLower = activeSpeaker.toLowerCase();
                let matchedId = null;
                if (spLower.includes('lead') || spLower.includes('commander') || spLower.includes('alpha')) matchedId = 'commander';
                else if (spLower.includes('researcher') || spLower.includes('intel') || spLower.includes('analis')) matchedId = 'researcher';
                else if (spLower.includes('auditor') || spLower.includes('critic') || spLower.includes('sentinel')) matchedId = 'critic';
                else if (spLower.includes('crafter') || spLower.includes('executor') || spLower.includes('code')) matchedId = 'executor';

                if (matchedId) {
                    const bubble = document.getElementById(`agent-bubble-${matchedId}`);
                    if (bubble) {
                        const cleanThought = thoughtText.replace(/^💬\s*[^:]+:\s*/, '').replace(/^⚙️\s*[^:]+:\s*/, '');
                        bubble.innerText = cleanThought;
                    }
                }
            }
        }
    }
}

// ==================== GLOBAL & MODULE EXPORTS ====================

window.escAttr = escAttr;
window.fmtTokens = fmtTokens;
window.AlfaStore = AlfaStore;
window.tabTitles = tabTitles;
window.initAlpineState = initAlpineState;
window.initTheme = initTheme;
window.toggleTheme = toggleTheme;
window.setTheme = setTheme;
window.switchTab = switchTab;
window.restoreActiveTab = restoreActiveTab;
window.toggleSidebar = toggleSidebar;
window.showToast = showToast;
window.updateClock = updateClock;
window.getSessionToken = getSessionToken;
window.setSessionToken = setSessionToken;
window.clearSessionToken = clearSessionToken;
window.updateSwarmArena = updateSwarmArena;

window.AlfaState = {
    store: AlfaStore,
    tabTitles,
    initTheme,
    toggleTheme,
    setTheme,
    switchTab,
    restoreActiveTab,
    toggleSidebar,
    showToast,
    updateClock,
    escAttr,
    fmtTokens,
    getSessionToken,
    setSessionToken,
    clearSessionToken,
    updateSwarmArena
};


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.escAttr = escAttr;
window.escHtml = escHtml;
window.safeMarkdown = safeMarkdown;
window.showToast = showToast;
window.switchTab = switchTab;
window.toggleSidebar = toggleSidebar;
window.toggleTheme = toggleTheme;
