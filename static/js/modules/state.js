/**
 * ==============================================================================
 * ALFA COMMAND CENTER - STATE & SESSION STORE MODULE (state.js)
 * ==============================================================================
 * Manages Alpine.js reactive store, session persistence, active tab state,
 * dark/light theme switching, and global UI notification state.
 */

// Helper: Escape string for HTML attribute injection
function escAttr(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

// Helper: Format large token counts into human-readable strings
function fmtTokens(n) {
    n = Number(n) || 0;
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
}

// Central Reactive App Store
const AlfaStore = {
    theme: localStorage.getItem("alfa_theme") || "dark",
    activeTab: localStorage.getItem("alfa_active_tab") || "overview",
    stats: {},
    services: [],
    models: [],
    notifications: [],
    session: {
        token: localStorage.getItem("alfa_auth_token") || null,
        user: null,
        isAuthenticated: !!localStorage.getItem("alfa_auth_token")
    }
};

// Tab titles mapping for breadcrumbs and headers
const tabTitles = {
    'overview': 'Telemetry & Live Overview',
    'swarm': 'AI Swarm — Eksekusi Langsung',
    'scraper': 'Master Scraper Pro Studio',
    'affiliate': 'Affiliate Sales Studio',
    'vault': 'Passkey Vault & Security',
    'keys': 'API Keys Manager',
    'tools': '126 Tools Catalog & Sandbox',
    'memory': 'Second Brain Memory',
    'artifacts': 'File Artifacts & Storage',
    'gdrive': 'Google Drive & Google Cloud Suite',
    'services': 'System Services & Background Tasks',
    'canvas': 'Pipeline Canvas Studio — Drag & Drop Workflow',
    'guardian': 'Guardian Defense & Integrity',
    'console': 'Chat Agent ALFA (Multimodal Live)',
    'settings': 'System Settings & Environment Config'
};

// Initialize Alpine.js integration if available or on event
function initAlpineState() {
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

function initTheme() {
    const savedTheme = localStorage.getItem('alfa_theme') || 'dark';
    setTheme(savedTheme, false);
}

function toggleTheme() {
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

function switchTab(tabId) {
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
    if (tabId === 'console' && typeof loadChatAvailableModels === 'function') loadChatAvailableModels();
    if (tabId === 'tools') {
        if (typeof allToolsData !== 'undefined' && allToolsData.length === 0 && typeof fetchTools === 'function') fetchTools();
        if (typeof fetchDynamicPlugins === 'function') fetchDynamicPlugins();
        if (typeof fetchSuperpowersSkills === 'function') fetchSuperpowersSkills();
    }
    if (tabId === 'services' && typeof fetchServices === 'function') fetchServices();
    if (tabId === 'canvas' && typeof initCanvas === 'function') initCanvas();
    if (tabId === 'memory' && typeof fetchMemory === 'function') fetchMemory();
    if (tabId === 'artifacts') {
        if (typeof fetchArtifacts === 'function') fetchArtifacts();
        if (typeof wsInit === 'function' && !wsInit._done) { wsInit._done = true; wsInit(); }
    }
    if (tabId === 'guardian' && typeof fetchGuardian === 'function') fetchGuardian();
    if (tabId === 'swarm') {
        if (typeof fetchAgents === 'function') fetchAgents();
        if (typeof fetchKeys === 'function') fetchKeys();
        if (typeof fetchSwarmLive === 'function') fetchSwarmLive();
        if (typeof loadMeetingFolders === 'function') loadMeetingFolders();
    }
    if (tabId === 'affiliate' && typeof fetchAffiliateCampaigns === 'function') fetchAffiliateCampaigns();
    if (tabId === 'keys') {
        if (typeof fetchKeys === 'function') fetchKeys();
        if (typeof fetchTokenUsage === 'function') fetchTokenUsage();
        if (typeof fetchAntigravityAccounts === 'function') fetchAntigravityAccounts();
    }
    if (tabId === 'waformat') {
        if (typeof fetchWaFormats === 'function') fetchWaFormats();
        if (typeof fetchWaMediaRules === 'function') fetchWaMediaRules();
    }
    if (tabId === 'vault') {
        if (typeof fetchVaultSecrets === 'function') fetchVaultSecrets();
        if (typeof fetchPasskeyStatus === 'function') fetchPasskeyStatus();
    }
    if (tabId === 'scraper' && typeof fetchScraperBatches === 'function') fetchScraperBatches();
    if (tabId === 'gdrive') {
        if (typeof fetchGdriveStatus === 'function') fetchGdriveStatus();
        if (typeof fetchGdriveFiles === 'function') fetchGdriveFiles();
    }
    if (tabId === 'settings') {
        if (typeof fetchSettings === 'function') fetchSettings();
        if (typeof fetchAgents === 'function') fetchAgents();
        if (typeof fetchKeys === 'function') fetchKeys();
    }

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

function restoreActiveTab() {
    const savedTab = localStorage.getItem('alfa_active_tab');
    if (savedTab && tabTitles[savedTab]) {
        switchTab(savedTab);
    }
}

// ==================== SIDEBAR & UI MODALS ====================

function toggleSidebar(show = null) {
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
function showToast(message, type = 'info') {
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
    return localStorage.getItem('alfa_auth_token');
}

function setSessionToken(token) {
    if (token) {
        localStorage.setItem('alfa_auth_token', token);
        AlfaStore.session.token = token;
        AlfaStore.session.isAuthenticated = true;
    } else {
        clearSessionToken();
    }
}

function clearSessionToken() {
    localStorage.removeItem('alfa_auth_token');
    AlfaStore.session.token = null;
    AlfaStore.session.isAuthenticated = false;
    AlfaStore.session.user = null;
}

// ==================== SWARM LIVE ARENA VISUALIZER HOOK ====================

function updateSwarmArena(data) {
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

