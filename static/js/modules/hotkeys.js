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
 * Handle Ctrl+K / Cmd+K quick focus shortcut.
 */
function handleQuickFocus(e) {
    e.preventDefault();
    const activeTab = window.AlfaStore?.activeTab || 'overview';

    if (activeTab === 'console') {
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.focus();
            chatInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }
    }

    if (activeTab === 'tools') {
        const toolSearch = document.getElementById('tools-search-input') || document.getElementById('tools-search');
        if (toolSearch) {
            toolSearch.focus();
            return;
        }
    }

    // Default: switch to console tab and focus chat
    if (typeof switchTab === 'function') {
        switchTab('console');
        setTimeout(() => {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) chatInput.focus();
        }, 100);
    }
}

/**
 * Handle Escape key press: closes modals and unfocuses active inputs.
 */
function handleEscapeKey(e) {
    // 1. Close Hotkeys Cheat Sheet modal if open
    const hotkeysModal = document.getElementById('alfa-hotkeys-modal');
    if (hotkeysModal && !hotkeysModal.classList.contains('hidden')) {
        closeHotkeysModal();
        return;
    }

    // 2. Close Vector Ingest modal
    if (typeof closeVectorIngestModal === 'function') {
        const vecModal = document.getElementById('vector-ingest-modal');
        if (vecModal && !vecModal.classList.contains('hidden')) {
            closeVectorIngestModal();
            return;
        }
    }

    // 3. Close Superpower Detail modal
    if (typeof closeSuperpowerDetailModal === 'function') {
        const spModal = document.getElementById('superpower-detail-modal');
        if (spModal && !spModal.classList.contains('hidden')) {
            closeSuperpowerDetailModal();
            return;
        }
    }

    // 4. Close Media Preview modal
    if (typeof closeMediaPreviewModal === 'function') {
        const mediaModal = document.getElementById('media-preview-modal');
        if (mediaModal && !mediaModal.classList.contains('hidden')) {
            closeMediaPreviewModal();
            return;
        }
    }

    // 5. Close Create Plugin modal
    if (typeof closeCreatePluginModal === 'function') {
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

function closeHotkeysModal() {
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
        if (typeof toggleTheme === 'function') {
            toggleTheme();
        }
        return;
    }

    // 5. Alt + 1..9 Tab navigation
    if (e.altKey && tabNumberMap[e.key]) {
        e.preventDefault();
        const tabId = tabNumberMap[e.key];
        if (typeof switchTab === 'function') {
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
function initHotkeys() {
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

// ==================== GLOBAL & MODULE EXPORTS ====================

window.initHotkeys = initHotkeys;
window.openHotkeysModal = openHotkeysModal;
window.closeHotkeysModal = closeHotkeysModal;
window.toggleHotkeysModal = toggleHotkeysModal;
window.registerHotkey = registerHotkey;

window.AlfaHotkeys = {
    initHotkeys,
    openHotkeysModal,
    closeHotkeysModal,
    toggleHotkeysModal,
    registerHotkey
};
