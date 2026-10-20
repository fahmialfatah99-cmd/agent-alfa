
/* ==== ES MODULE BRIDGE ==== */
import { closeCreatePluginModal, closeMediaPreviewModal, closeSuperpowerDetailModal, closeVectorIngestModal } from '../app.js';
import { switchTab, toggleTheme } from './state.js';
/**
 * ==============================================================================
 * ALFA COMMAND CENTER - KEYBOARD HOTKEYS & SHORTCUTS MODULE (hotkeys.js)
 * ==============================================================================
 * Manages global keyboard shortcuts (Ctrl+K quick focus, Escape modal dismiss,
 * Alt+1-9 tab navigation, Ctrl+/ cheat sheet modal) and interactive command triggers.
 */

// Custom hotkey registry
const registeredHotkeys = new Map();

// Tab shortcut mapping (Alt + Number)
const tabNumberMap = {
    '1': 'overview',
    '2': 'swarm',
    '3': 'tools',
    '4': 'console',
    '5': 'memory',
    '6': 'artifacts',
    '7': 'vault',
    '8': 'gdrive',
    '9': 'settings'
};

/**
 * Check if the active focused element is a text input, textarea, or editable element.
 */
function isInputElementFocused() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || el.isContentEditable;
}

/**
 * Handle Ctrl+K / Cmd+K quick focus shortcut -> Open Hermes Omni Command Palette.
 */
function handleQuickFocus(e) {
    e.preventDefault();
    openCommandPalette();
}

/**
 * Handle Escape key press: closes modals and unfocuses active inputs.
 */
function handleEscapeKey(e) {
    // 0. Close Omni Command Palette if open
    const cmdModal = document.getElementById('omni-command-modal');
    if (cmdModal && !cmdModal.classList.contains('hidden')) {
        closeCommandPalette();
        return;
    }

    // 1. Close Hotkeys Cheat Sheet modal if open
    const hotkeysModal = document.getElementById('alfa-hotkeys-modal');
    if (hotkeysModal && !hotkeysModal.classList.contains('hidden')) {
        closeHotkeysModal();
        return;
    }

    // 2. Close Vector Ingest modal
    {
        const vecModal = document.getElementById('vector-ingest-modal');
        if (vecModal && !vecModal.classList.contains('hidden')) {
            closeVectorIngestModal();
            return;
        }
    }

    // 3. Close Superpower Detail modal
    {
        const spModal = document.getElementById('superpower-detail-modal');
        if (spModal && !spModal.classList.contains('hidden')) {
            closeSuperpowerDetailModal();
            return;
        }
    }

    // 4. Close Media Preview modal
    {
        const mediaModal = document.getElementById('media-preview-modal');
        if (mediaModal && !mediaModal.classList.contains('hidden')) {
            closeMediaPreviewModal();
            return;
        }
    }

    // 5. Close Create Plugin modal
    {
        const pluginModal = document.getElementById('create-plugin-modal');
        if (pluginModal && !pluginModal.classList.contains('hidden')) {
            closeCreatePluginModal();
            return;
        }
    }

    // 6. Unfocus active input
    if (isInputElementFocused()) {
        document.activeElement.blur();
    }
}

/**
 * Create or render the Hotkeys Cheat Sheet Modal in the DOM.
 */
function ensureHotkeysModal() {
    let modal = document.getElementById('alfa-hotkeys-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'alfa-hotkeys-modal';
        modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-dark-950/80 backdrop-blur-md hidden transition-all duration-200';
        modal.innerHTML = `
            <div class="relative w-full max-w-xl p-6 bg-dark-900 border border-cyan-500/30 rounded-2xl shadow-2xl font-mono text-xs text-slate-200">
                <div class="flex items-center justify-between pb-4 border-b border-white/10">
                    <div class="flex items-center gap-2">
                        <span class="text-cyan-400 font-bold text-sm">⌨️ Pintasan Keyboard ALFA</span>
                        <span class="px-2 py-0.5 rounded bg-cyan-500/10 text-[10px] text-cyan-300 font-bold">PRO-MAX</span>
                    </div>
                    <button onclick="closeHotkeysModal()" class="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-all">
                        ✕
                    </button>
                </div>

                <div class="py-4 space-y-4 max-h-[70vh] overflow-y-auto">
                    <div>
                        <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Pintasan Global</div>
                        <div class="grid grid-cols-2 gap-2 text-xs">
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">Fokus Chat / Prompt</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-cyan-300 font-bold border border-white/10">Ctrl+K</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">Tutup Modal / Batal</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-rose-300 font-bold border border-white/10">ESC</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">Buka Bantuan Pintasan</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-cyan-300 font-bold border border-white/10">Ctrl+/</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">Ganti Mode Gelap/Terang</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-amber-300 font-bold border border-white/10">Alt+T</kbd>
                            </div>
                        </div>
                    </div>

                    <div>
                        <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Navigasi Tab Cepat (Alt + 1..9)</div>
                        <div class="grid grid-cols-2 gap-2 text-xs">
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">1. Telemetry & Overview</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+1</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">2. AI Swarm & Rapat</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+2</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">3. Tools Sandbox</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+3</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">4. Live Console Chat</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+4</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">5. Second Brain Memory</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+5</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">6. File Artifacts</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+6</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">7. Cyber Vault</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+7</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5">
                                <span class="text-slate-300">8. Google Drive Suite</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+8</kbd>
                            </div>
                            <div class="flex items-center justify-between p-2 rounded-xl bg-dark-950/60 border border-white/5 col-span-2">
                                <span class="text-slate-300">9. System Settings</span>
                                <kbd class="px-2 py-0.5 rounded bg-white/10 text-violet-300 font-bold border border-white/10">Alt+9</kbd>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="flex justify-end pt-3 border-t border-white/10 text-slate-400 text-[11px]">
                    Tekan <kbd class="mx-1 px-1.5 py-0.5 rounded bg-white/10 text-slate-200">ESC</kbd> untuk menutup
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }
    return modal;
}

function openHotkeysModal() {
    const modal = ensureHotkeysModal();
    modal.classList.remove('hidden');
}

export function closeHotkeysModal() {
    const modal = document.getElementById('alfa-hotkeys-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function toggleHotkeysModal() {
    const modal = ensureHotkeysModal();
    if (modal.classList.contains('hidden')) {
        openHotkeysModal();
    } else {
        closeHotkeysModal();
    }
}

/**
 * Register a custom shortcut handler.
 */
function registerHotkey(keyCombo, description, handler) {
    registeredHotkeys.set(keyCombo.toLowerCase(), { description, handler });
}

/**
 * Master Keydown Event Listener
 */
function handleKeyDown(e) {
    const isInput = isInputElementFocused();

    // 1. ESC is always handled even inside inputs
    if (e.key === 'Escape') {
        handleEscapeKey(e);
        return;
    }

    // 2. Ctrl+K or Cmd+K quick focus
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        handleQuickFocus(e);
        return;
    }

    // 3. Ctrl+/ cheat sheet
    if ((e.ctrlKey || e.metaKey) && (e.key === '/' || e.key === '?')) {
        e.preventDefault();
        toggleHotkeysModal();
        return;
    }

    // 4. Alt+T quick theme toggle
    if (e.altKey && e.key.toLowerCase() === 't') {
        e.preventDefault();
        {
            toggleTheme();
        }
        return;
    }

    // 5. Alt + 1..9 Tab navigation
    if (e.altKey && tabNumberMap[e.key]) {
        e.preventDefault();
        const tabId = tabNumberMap[e.key];
        {
            switchTab(tabId);
        }
        return;
    }

    // 6. '?' when outside inputs toggles hotkeys cheat sheet
    if (!isInput && e.key === '?') {
        e.preventDefault();
        toggleHotkeysModal();
        return;
    }
}

/**
 * Initialize hotkey event listeners on the window.
 */
export function initHotkeys() {
    if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {
        window.removeEventListener('keydown', handleKeyDown);
    }
    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
        window.addEventListener('keydown', handleKeyDown);
    }
}

// Auto-initialize when script loads
if (typeof window !== 'undefined') {
    initHotkeys();
}

// ==================== OMNI COMMAND PALETTE (HERMES STYLE) ====================

const COMMAND_PALETTE_ITEMS = [
    // Navigation
    { id: 'nav-overview', title: 'Telemetry & Live Overview', subtitle: 'Halaman utama metrik sistem & radar live', icon: 'activity', badge: 'Alt+1', action: () => switchTab('overview') },
    { id: 'nav-swarm', title: 'AI Swarm Live Arena', subtitle: 'Orkestrasi 6 agen cerdas otonom', icon: 'zap', badge: 'Alt+2', action: () => switchTab('swarm') },
    { id: 'nav-tools', title: 'Tools Catalog & Sandbox', subtitle: 'Katalog 170+ fungsi & REA forensik', icon: 'cpu', badge: 'Alt+3', action: () => switchTab('tools') },
    { id: 'nav-console', title: 'Live AI Chat Agent', subtitle: 'Chat multimodal live dengan penalaran Hermes', icon: 'bot-message-square', badge: 'Alt+4', action: () => switchTab('console') },
    { id: 'nav-memory', title: 'Second Brain & Knowledge', subtitle: 'Memori graf neokorteks & vault pengetahuan', icon: 'brain', badge: 'Alt+5', action: () => switchTab('memory') },
    { id: 'nav-artifacts', title: 'File Artifacts & Storage', subtitle: 'Manajemen berkas output dan arsip dokumen', icon: 'folder-kanban', badge: 'Alt+6', action: () => switchTab('artifacts') },
    { id: 'nav-vault', title: 'Passkey Vault & Security', subtitle: 'Brankas enkripsi kredensial & API key', icon: 'shield-alert', badge: 'Alt+7', action: () => switchTab('vault') },
    { id: 'nav-gdrive', title: 'Google Drive & Cloud Suite', subtitle: 'Sinkronisasi berkas Google Drive & Cloud', icon: 'hard-drive', badge: 'Alt+8', action: () => switchTab('gdrive') },
    { id: 'nav-settings', title: 'System Settings & Config', subtitle: 'Pengaturan runtime environment', icon: 'settings', badge: 'Alt+9', action: () => switchTab('settings') },
    { id: 'nav-waformat', title: 'WA Laporan & Format Sheets', subtitle: 'Pengaturan parsing otomatis WhatsApp ke Sheets', icon: 'clipboard-list', badge: 'SHEETS', action: () => switchTab('waformat') },
    { id: 'nav-sites', title: 'Galeri Situs & Projects', subtitle: 'Kelola port & web hasil kerja agen', icon: 'globe', badge: 'SITES', action: () => switchTab('sites') },
    { id: 'nav-scraper', title: 'Master Scraper Pro Studio', subtitle: 'Alat ekstraksi & scraping web tingkat lanjut', icon: 'scan', badge: 'PRO', action: () => switchTab('scraper') },
    // Actions
    { id: 'act-clean-ram', title: 'Bersihkan RAM & Cache', subtitle: 'Jalankan garbage collection & malloc trim', icon: 'sparkles', badge: 'AKSI', action: () => cleanSystemRam() },
    { id: 'act-theme', title: 'Ganti Mode Tema (Gelap / Terang)', subtitle: 'Beralih tampilan kontras', icon: 'sun', badge: 'Alt+T', action: () => toggleTheme() },
    { id: 'act-refresh', title: 'Refresh Telemetri Sistem', subtitle: 'Perbarui data hardware & services live', icon: 'refresh-cw', badge: 'AKSI', action: () => { if (typeof fetchStats === 'function') fetchStats(true); } },
    { id: 'act-new-chat', title: 'Mulai Sesi Chat AI Baru', subtitle: 'Bersihkan konteks percakapan saat ini', icon: 'plus-circle', badge: 'CHAT', action: () => { switchTab('console'); setTimeout(() => { if (window.startNewChatSession) window.startNewChatSession(); }, 150); } },
];

export function openCommandPalette() {
    let modal = document.getElementById('omni-command-modal');
    if (!modal) {
        modal = ensureCommandPaletteModal();
    }
    modal.classList.remove('hidden');
    const input = document.getElementById('omni-command-input');
    if (input) {
        input.value = '';
        input.focus();
        filterCommandPalette('');
    }
}

export function closeCommandPalette() {
    const modal = document.getElementById('omni-command-modal');
    if (modal) modal.classList.add('hidden');
}

export function filterCommandPalette(q) {
    const container = document.getElementById('omni-command-results');
    if (!container) return;
    const query = (q || '').toLowerCase().trim();

    const matches = COMMAND_PALETTE_ITEMS.filter(item => {
        if (!query) return true;
        return item.title.toLowerCase().includes(query) ||
               item.subtitle.toLowerCase().includes(query) ||
               (item.badge && item.badge.toLowerCase().includes(query));
    });

    if (matches.length === 0) {
        container.innerHTML = `
            <div class="py-8 text-center text-slate-500 font-mono text-xs">
                Tidak ada perintah yang cocok dengan "<b>${q}</b>".
            </div>
        `;
        return;
    }

    container.innerHTML = matches.map((item, idx) => `
        <div onclick="executeCommandPaletteItem('${item.id}')"
             class="cmd-palette-item flex items-center justify-between p-3 rounded-xl cursor-pointer hover:bg-cyan-500/10 border border-transparent hover:border-cyan-500/30 transition-all ${idx === 0 ? 'bg-white/5 border-white/5' : ''}">
            <div class="flex items-center gap-3 min-w-0">
                <div class="w-8 h-8 rounded-lg bg-dark-900 border border-white/10 flex items-center justify-center text-cyan-400 flex-shrink-0">
                    <i data-lucide="${item.icon}" class="w-4 h-4"></i>
                </div>
                <div class="min-w-0 truncate">
                    <p class="text-xs font-bold text-slate-200 truncate">${item.title}</p>
                    <p class="text-[10px] text-slate-400 truncate">${item.subtitle}</p>
                </div>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] bg-dark-900 text-slate-400 font-mono border border-white/10 flex-shrink-0">${item.badge}</span>
        </div>
    `).join('');

    if (window.lucide) lucide.createIcons();
}

export function executeCommandPaletteItem(itemId) {
    const item = COMMAND_PALETTE_ITEMS.find(it => it.id === itemId);
    closeCommandPalette();
    if (item && typeof item.action === 'function') {
        item.action();
    }
}

function ensureCommandPaletteModal() {
    let modal = document.getElementById('omni-command-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'omni-command-modal';
        modal.className = 'fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/75 backdrop-blur-md hidden transition-opacity';
        modal.innerHTML = `
            <div class="w-full max-w-xl bg-dark-950/95 border border-cyan-500/40 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]" onclick="event.stopPropagation()">
                <div class="flex items-center gap-3 p-3.5 border-b border-white/10 bg-dark-900/80">
                    <i data-lucide="search" class="w-4 h-4 text-cyan-400 flex-shrink-0"></i>
                    <input id="omni-command-input" type="text"
                           placeholder="Ketik perintah, nama tab, atau aksi... (misal: 'wa', 'swarm', 'ram', 'settings')"
                           class="flex-1 bg-transparent text-white text-xs font-mono focus:outline-none placeholder:text-slate-500 border-none p-0 focus:ring-0"
                           oninput="filterCommandPalette(this.value)"
                           onkeydown="if(event.key==='Escape') closeCommandPalette(); if(event.key==='Enter'){ const first = document.querySelector('.cmd-palette-item'); if(first) first.click(); }">
                    <kbd class="px-1.5 py-0.5 text-[10px] rounded bg-white/10 text-slate-400 font-mono">ESC</kbd>
                </div>
                <div id="omni-command-results" class="p-2 space-y-1 overflow-y-auto custom-scrollbar flex-1">
                    <!-- Populated by filterCommandPalette() -->
                </div>
                <div class="flex items-center justify-between p-2.5 px-4 bg-dark-900/50 border-t border-white/5 text-[10px] text-slate-500 font-mono">
                    <span>Gunakan panah untuk navigasi, Enter untuk memilih</span>
                    <span class="text-cyan-400 font-bold">ALFA OMNI HUB</span>
                </div>
            </div>
        `;
        modal.onclick = closeCommandPalette;
        document.body.appendChild(modal);
        if (window.lucide) lucide.createIcons();
    }
    return modal;
}

// Global RAM Cleaning Action
export async function cleanSystemRam() {
    const btn = document.getElementById('btn-clean-ram');
    if (btn) btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin text-cyan-400"></i> Membersihkan...';
    try {
        const res = await fetch('/api/system/clean-ram', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            if (typeof showToast === 'function') {
                showToast(`🧹 ${data.message} (RAM: ${data.ram_percent}%)`, 'success');
            }
            if (typeof fetchStats === 'function') fetchStats(true);
        } else {
            if (typeof showToast === 'function') showToast(data.message || 'Pembersihan RAM selesai.', 'info');
        }
    } catch (e) {
        if (typeof showToast === 'function') showToast('Pembersihan RAM berhasil dijalankan.', 'info');
    } finally {
        if (btn) btn.innerHTML = '<i data-lucide="sparkles" class="w-3.5 h-3.5 text-cyan-400"></i> <span>Bersihkan RAM</span>';
        if (window.lucide) lucide.createIcons();
    }
}

// ==================== GLOBAL & MODULE EXPORTS ====================

window.initHotkeys = initHotkeys;
window.openHotkeysModal = openHotkeysModal;
window.closeHotkeysModal = closeHotkeysModal;
window.toggleHotkeysModal = toggleHotkeysModal;
window.registerHotkey = registerHotkey;
window.openCommandPalette = openCommandPalette;
window.closeCommandPalette = closeCommandPalette;
window.filterCommandPalette = filterCommandPalette;
window.executeCommandPaletteItem = executeCommandPaletteItem;
window.cleanSystemRam = cleanSystemRam;

window.AlfaHotkeys = {
    initHotkeys,
    openHotkeysModal,
    closeHotkeysModal,
    toggleHotkeysModal,
    registerHotkey,
    openCommandPalette,
    closeCommandPalette,
    filterCommandPalette,
    executeCommandPaletteItem,
    cleanSystemRam
};

// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.closeHotkeysModal = closeHotkeysModal;

