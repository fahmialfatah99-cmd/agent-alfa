/* ==========================================================================
   ALFA DASHBOARD — Core Application Orchestrator
   Modular frontend architecture:
   - /static/js/modules/state.js     (Reactive store, theme, tab navigation, UI toasts)
   - /static/js/modules/audio.js     (Web Audio API, visualizer, mic recorder, TTS)
   - /static/js/modules/hotkeys.js   (Keyboard navigation, modal shortcuts, cheat sheet)
   - /static/js/modules/telemetry.js (Chart.js metrics, hardware polling, service badges)
   ========================================================================== */

// Initialize Lucide icons on load
if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
}

// ==================== SYSTEM SETTINGS MANAGER ====================

// ── Model dropdown live per kunci ──
const _modelCache = {};

const AG_STATIC_MODELS = [
    'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3-flash', 'gemini-3.1-pro',
    'gemini-2.5-pro', 'gemini-2.5-flash',
    'claude-sonnet-4.6', 'claude-opus-4.6',
    'gpt-oss-120b'
];

function _populateModelsStatic(sel, models, current) {
    sel.innerHTML = models.map(m =>
        `<option value="${escAttr(m)}" ${m === current ? 'selected' : ''}>${escAttr(m)}</option>`
    ).join('');
}

async function loadModelsForKey(keyId, providerHint) {
    const sel = document.getElementById('cfg-main-brain-model');
    if (!sel) return;
    sel.innerHTML = '<option value="">Memuat daftar model...</option>';

    // Antigravity tanpa akun login: sediakan daftar valid statik
    if (String(keyId) && providerHint === 'antigravity') {
        _populateModels(sel, keyId, AG_STATIC_MODELS, null);
        sel.dataset.current = sel.value;
        return;
    }
    if (!keyId) { sel.innerHTML = '<option value="">Pilih kunci dahulu</option>'; return; }

    if (_modelCache[keyId]) {
        _populateModels(sel, keyId, _modelCache[keyId]);
        return;
    }
    try {
        const res = await fetch(`/api/models-for-key?key_id=${keyId}`);
        const data = await res.json();
        if (data.status === 'success' && (data.models || []).length) {
            _modelCache[keyId] = data.models;
            _populateModels(sel, keyId, data.models);
        } else {
            sel.innerHTML = '<option value="">(tidak ada model tersedia)</option>';
        }
    } catch (e) {
        sel.innerHTML = '<option value="">Gagal memuat model</option>';
    }
}

function _populateModels(sel, keyId, models) {
    const current = sel.dataset.current || '';
    sel.innerHTML = models.map(m =>
        `<option value="${escAttr(m)}" ${m === current ? 'selected' : ''}>${escAttr(m)}</option>`
    ).join('');
    if (current && !models.includes(current)) {
        const opt = document.createElement('option');
        opt.value = current; opt.textContent = current + ' (model saat ini)';
        sel.insertBefore(opt, sel.firstChild);
        sel.value = current;
    }
}

// ── 🛰️ ANTIGRAVITY MULTI-ACCOUNT LOGIN ──
let _agPollTimer = null;

async function startAntigravityLogin() {
    const nameInput = document.getElementById('ag-name-input');
    const btn = document.getElementById('btn-ag-login');
    const statusBox = document.getElementById('ag-login-status');
    const name = (nameInput?.value || '').trim().toLowerCase();

    if (!name) { showToast('Isi nama akun dulu.', 'warning'); return; }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menunggu Google...';
    lucide.createIcons();
    if (statusBox) {
        statusBox.classList.remove('hidden');
        statusBox.innerHTML = '⏳ Membuka jendela login Google... pilih akun & izinkan. Jendela popup diblokir? Buka manual: <span id="ag-auth-url" class="text-cyan-300 break-all"></span>';
    }

    try {
        const res = await fetch('/api/antigravity/login/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await res.json();

        if (data.status !== 'success') {
            showToast(data.message || 'Gagal memulai login.', 'error');
            if (statusBox) statusBox.innerHTML = '❌ ' + (data.message || 'gagal');
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login Google';
            lucide.createIcons();
            return;
        }

        window.open(data.auth_url, '_blank', 'width=520,height=640');

        // Poll status tiap 2.5s hingga selesai/maks 5 menit
        let elapsed = 0;
        _agPollTimer = setInterval(async () => {
            elapsed += 2.5;
            try {
                const sr = await fetch(`/api/antigravity/login/status?name=${encodeURIComponent(name)}`);
                const sd = await sr.json();
                if (sd.status === 'success') {
                    clearInterval(_agPollTimer);
                    showToast(`✅ Akun ${sd.email || name} terhubung!`, 'success');
                    if (statusBox) statusBox.innerHTML = `✅ <b class="text-emerald-400">Berhasil:</b> ${sd.email || name} masuk rotasi gateway.`;
                    btn.disabled = false;
                    btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login Google';
                    fetchAntigravityAccounts();
                    lucide.createIcons();
                } else if (sd.status === 'error') {
                    clearInterval(_agPollTimer);
                    showToast('Login gagal: ' + (sd.error || ''), 'error');
                    if (statusBox) statusBox.innerHTML = '❌ Gagal: ' + escAttr(sd.error || '') ;
                    btn.disabled = false;
                    btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login Google';
                } else if (elapsed > 300) {
                    clearInterval(_agPollTimer);
                    showToast('Timeout menunggu login.', 'warning');
                    if (statusBox) statusBox.innerHTML += '<br>⏱️ Timeout.';
                    btn.disabled = false;
                    btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login Google';
                }
            } catch (e) { /* keep polling */ }
        }, 2500);

    } catch (err) {
        showToast('Error: ' + err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login Google';
    }
}

async function removeAntigravityAccount(name) {
    if (!confirm('Hapus akun "' + name + '" dari gateway?')) return;
    try {
        await fetch('/api/antigravity/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        showToast('Akun dihapus.', 'success');
        fetchAntigravityAccounts();
    } catch (err) { showToast('Error: ' + err.message, 'error'); }
}

async function fetchAntigravityAccounts() {
    const list = document.getElementById('ag-accounts-list');
    const badge = document.getElementById('ag-acct-badge');
    if (!list) return;
    try {
        const res = await fetch('/api/antigravity/accounts');
        const data = await res.json();
        const accs = data.accounts || [];
        if (badge) badge.innerText = accs.length ? accs.length + ' akun' : '';
        if (accs.length === 0) {
            list.innerHTML = '<p class="text-center text-slate-600 font-mono text-[10px] py-2">Belum ada akun terdaftar.</p>';
            return;
        }
        list.innerHTML = accs.map(a => `
            <div class="flex items-center gap-2 p-1.5 rounded-lg bg-dark-950/60 border border-white/5">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0"></span>
                <div class="min-w-0 flex-1 leading-tight">
                    <span class="text-[11px] font-bold text-slate-200 truncate block">${escAttr(a.email || a.name)}</span>
                    <span class="text-[9px] font-mono text-slate-500">proxy :${a.port || '?'} </span>
                </div>
                <button onclick="removeAntigravityAccount('${escAttr(a.name)}')" class="p-1 rounded bg-white/5 text-slate-500 hover:text-rose-300 transition-all shrink-0" title="Hapus">
                    <i data-lucide="trash-2" class="w-3 h-3"></i>
                </button>
            </div>`
        ).join('');
        lucide.createIcons();
    } catch (err) { console.error('fetchAntigravityAccounts:', err); }
}

async function applyAntigravityModel() {
    const sel = document.getElementById('ag-model-select');
    const chk = document.getElementById('ag-apply-all');
    const btn = document.getElementById('btn-ag-apply');
    if (!sel?.value) { showToast('Pilih model dulu.', 'warning'); return; }
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menerapkan...';
    lucide.createIcons();
    try {
        const res = await fetch('/api/antigravity/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: sel.value,
                apply_all_agents: chk?.checked ?? true
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Model ${sel.value} diterapkan ke ${data.agents_count} agen + otak utama!`, 'success');
        } else {
            showToast(data.message || data.detail || 'Gagal.', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="check-check" class="w-3.5 h-3.5"></i> Simpan & Terapkan ke Semua Agent';
        lucide.createIcons();
    }
}

async function testMainBrainCombo() {
    const sel = document.getElementById('cfg-main-brain');
    const msel = document.getElementById('cfg-main-brain-model');
    const btn = document.getElementById('btn-test-main-brain');
    if (!sel?.value) { showToast('Pilih kunci dulu.', 'warning'); return; }
    btn.disabled = true;
    const oldTxt = btn.innerHTML;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i>';
    lucide.createIcons();
    try {
        const res = await fetch('/api/main-brain/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key_id: Number(sel.value), model: msel?.value || '' })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ Koneksi OK (${data.latency_ms}ms): ${data.snippet}`, 'success');
        } else {
            showToast('❌ ' + (data.message || 'gagal'), 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="plug-zap" class="w-3.5 h-3.5"></i> Tes';
        lucide.createIcons();
    }
}

function mbOnProviderChange() {
    const prov = document.getElementById('cfg-mb-provider')?.value || '';
    const keys = (dataSettingsCache?.vault_keys || []).filter(k => k.provider === prov);
    const keySel = document.getElementById('cfg-main-brain');
    if (!keySel) return;
    if (keys.length === 0) {
        keySel.innerHTML = '<option value="">Tidak ada kunci utk provider ini</option>';
        const msel = document.getElementById('cfg-main-brain-model');
        if (msel) {
            msel.dataset.current = '';
            msel.innerHTML = '<option value="">Pilih kunci dahulu</option>';
        }
        return;
    }
    keySel.innerHTML = keys.map(k =>
        `<option value="${k.id}">#${k.id} ${escAttr(k.name)}${k.is_active ? " ← AKTIF" : ""}</option>`
    ).join('');
    mbOnKeyChange(keySel.value);
}

function mbOnKeyChange(keyId) {
    const k = (dataSettingsCache?.vault_keys || []).find(x => String(x.id) === String(keyId));
    // Sinkronkan pilihan model dgn kunci/provider baru: pakai default
    // kunci tsb, jangan sisakan model milik provider sebelumnya.
    const msel = document.getElementById('cfg-main-brain-model');
    if (msel) msel.dataset.current = k?.model || '';
    const prov = k ? k.provider : (document.getElementById('cfg-mb-provider')?.value || '');
    loadModelsForKey(keyId, prov);
}

async function saveMainBrain() {
    const sel = document.getElementById('cfg-main-brain');
    const modelInput = document.getElementById('cfg-main-brain-model');
    const btn = document.getElementById('btn-save-main-brain');
    if (!sel?.value) { showToast('Pilih kunci otak utama dulu.', 'warning'); return; }
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menerapkan...';
    lucide.createIcons();
    try {
        const res = await fetch('/api/settings/main-brain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key_id: Number(sel.value), model: modelInput?.value.trim() || '' })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Otak utama: ${data.main_brain.provider} · ${data.main_brain.model}`, 'success');
            fetchSettings();
        } else {
            showToast(data.message || data.detail || 'Gagal.', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="zap" class="w-3.5 h-3.5"></i> Terapkan Otak';
        lucide.createIcons();
    }
}

async function fetchSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (data.status === 'success' && data.env) {
            dataSettingsCache = data;
            const env = data.env;
            const tokenHint = document.getElementById('cfg-bot-token-hint');

            if (tokenHint) {
                tokenHint.innerHTML = env.has_bot_token
                    ? `<span class="text-emerald-400 font-mono">✅ Terhubung: ${env.masked_bot_token}</span>`
                    : `<span class="text-rose-400 font-mono">❌ Belum dikonfigurasi</span>`;
            }

            // Main Brain picker (cascade: Provider -> Kunci -> Model)
            const mbProv = document.getElementById('cfg-mb-provider');
            const mbSel = document.getElementById('cfg-main-brain');
            const mbModel = document.getElementById('cfg-main-brain-model');
            const mbBadge = document.getElementById('mb-current-badge');
            if (data.main_brain && mbSel) {
                const keys = data.vault_keys || [];

                // 1) Provider unik dari kunci vault
                const provs = [...new Set(keys.map(k => k.provider))];
                if (mbProv) {
                    mbProv.innerHTML = provs.map(p =>
                        `<option value="${p}">${p.toUpperCase()}</option>`).join('');
                    mbProv.value = data.main_brain.provider || provs[0] || '';
                }

                // 2) Kunci milik provider terpilih
                const pKeys = keys.filter(k => k.provider === (mbProv?.value || ''));
                if (pKeys.length === 0) {
                    mbSel.innerHTML = '<option value="">Tidak ada kunci utk provider ini</option>';
                } else {
                    mbSel.innerHTML = pKeys.map(k => {
                        const cur = data.main_brain.key_id === k.id ? ' ← OTAK UTAMA' : '';
                        return `<option value="${k.id}" ${data.main_brain.key_id === k.id ? 'selected' : ''}>` +
                            `#${k.id} ${escAttr(k.name)}${cur}</option>`;
                    }).join('');
                }

                // 3) Model live utk kunci otak; fallback statik antigravity
                if (mbModel) {
                    mbModel.dataset.current = data.main_brain.model || '';
                    loadModelsForKey(data.main_brain.key_id, data.main_brain.provider);
                }
                if (mbBadge) {
                    const p = data.main_brain.provider || '?';
                    const m = data.main_brain.model || '-';
                    mbBadge.innerText = `${p.toUpperCase()} · ${m}`;
                    mbBadge.className = 'ml-auto text-[10px] px-2 py-0.5 rounded font-bold bg-violet-500/20 text-violet-300 border border-violet-500/40';
                }
            }

            const allowedInput = document.getElementById('cfg-allowed-ids');
            if (allowedInput && env.allowed_user_ids !== undefined) {
                allowedInput.value = env.allowed_user_ids;
            }

            const instrText = document.getElementById('cfg-system-instruction');
            if (instrText && env.system_instruction !== undefined) {
                instrText.value = env.system_instruction;
            }
            const promptHint = document.getElementById('cfg-prompt-source-hint');
            if (promptHint && env.system_instruction_source) {
                const src = env.system_instruction_source === 'file'
                    ? '~/.alfa/system_prompt.txt (file persona aktif)'
                    : '.env SYSTEM_INSTRUCTION (file ~/.alfa/system_prompt.txt belum ada)';
                promptHint.innerHTML = `Sumber aktif: <span class="text-cyan-400">${src}</span> — berlaku untuk Telegram &amp; Web seketika setelah disimpan.`;
            }
        }
    } catch (err) {
        console.error('Fetch settings error:', err);
    }
}

async function saveSettings(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-save-settings');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Menyimpan...';
    }

    try {
        const payload = {
            telegram_bot_token: document.getElementById('cfg-bot-token')?.value || '',
            allowed_user_ids: document.getElementById('cfg-allowed-ids')?.value || '',
            system_instruction: document.getElementById('cfg-system-instruction')?.value || ''
        };

        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message || 'Pengaturan berhasil disimpan!', 'success');
            const tokenInput = document.getElementById('cfg-bot-token');
            if (tokenInput) tokenInput.value = '';
            fetchSettings();
        } else {
            showToast(data.message || 'Gagal menyimpan pengaturan', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="save" class="w-4 h-4"></i> Simpan Pengaturan';
            lucide.createIcons();
        }
    }
}

// Navigation & Telemetry logic modularized into /static/js/modules/state.js and /static/js/modules/telemetry.js

// Services Hub
async function fetchServices() {
    try {
        const res = await fetch('/api/services');
        const data = await res.json();
        if (data.status === 'success') {
            const tb = data.services.find(s => s.name === 'telegram-ai-bot.service');
            const wa = data.services.find(s => s.name === 'wa-sheets-bot.service');
            const dash = data.services.find(s => s.name === 'alfa-dashboard.service');

            if (tb) {
                document.getElementById('svc-stat-tb').innerText = tb.state.toUpperCase();
                document.getElementById('svc-stat-tb').className = tb.is_active 
                    ? 'px-2.5 py-0.5 text-xs font-mono rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'px-2.5 py-0.5 text-xs font-mono rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20';
                document.getElementById('svc-details-tb').innerText = tb.details;
            }
            if (wa) {
                document.getElementById('svc-stat-wa').innerText = wa.state.toUpperCase();
                document.getElementById('svc-stat-wa').className = wa.is_active 
                    ? 'px-2.5 py-0.5 text-xs font-mono rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'px-2.5 py-0.5 text-xs font-mono rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20';
                document.getElementById('svc-details-wa').innerText = wa.details;
            }
            if (dash) {
                document.getElementById('svc-stat-dash').innerText = dash.state.toUpperCase();
                document.getElementById('svc-details-dash').innerText = dash.details;
            }
        }
        fetchServiceLogs();
        fetchWaQr();
        fetchWaReports();
    } catch (err) {
        showToast(`Services error: ${err.message}`, 'error');
    }
}

async function controlService(service, action) {
    try {
        const res = await fetch('/api/services/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ service, action })
        });
        const data = await res.json();
        showToast(data.status === 'success' ? `Service ${service} ${action} berhasil!` : `Gagal: ${data.output}`, data.status === 'success' ? 'success' : 'error');
        fetchServices();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// Second Brain & Memory
async function fetchMemory() {
    try {
        const res = await fetch('/api/memory');
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById('memory-count-badge').innerText = `${data.total_memories} Fakta • ${data.total_kg_relations} Relasi`;
            const container = document.getElementById('memory-cards-container');

            if (data.memories.length === 0 && data.knowledge_graph.length === 0) {
                container.innerHTML = '<div class="text-slate-500 text-center py-12 font-mono text-xs">Belum ada memori yang tersimpan.</div>';
                return;
            }

            const memHTML = data.memories.map(m => `
                <div class="p-3.5 rounded-xl bg-dark-950 border border-white/5 flex items-start justify-between gap-3 group hover:border-cyan-500/30 transition-all">
                    <div>
                        <span class="px-2 py-0.5 text-[9px] font-mono rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 uppercase font-bold">${m.category}</span>
                        <h4 class="text-xs font-bold text-white mt-1 font-mono">${m.key_topic}</h4>
                        <p class="text-xs text-slate-300 mt-0.5 leading-relaxed">${m.content}</p>
                    </div>
                    <button onclick="deleteMemoryFact('${m.key_topic}')" class="opacity-0 group-hover:opacity-100 p-1 rounded bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 transition-all" title="Hapus Fakta">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `).join('');

            const kgHTML = data.knowledge_graph.map(k => `
                <div class="p-3 rounded-xl bg-dark-950 border border-violet-500/20 flex items-center justify-between gap-3 font-mono text-xs">
                    <div class="flex items-center space-x-2">
                        <span class="text-white font-bold">${k.entity}</span>
                        <span class="text-violet-400">──(${k.relation})──></span>
                        <span class="text-cyan-300 font-bold">${k.target_value}</span>
                    </div>
                    <span class="px-2 py-0.5 text-[9px] rounded bg-violet-500/10 text-violet-300 uppercase">${k.category}</span>
                </div>
            `).join('');

            container.innerHTML = memHTML + kgHTML;
            lucide.createIcons();
        }
    } catch (err) {
        showToast(`Gagal memuat memori: ${err.message}`, 'error');
    }
}

async function submitNewMemory(e) {
    e.preventDefault();
    const key = document.getElementById('mem-key').value.trim();
    const cat = document.getElementById('mem-cat').value;
    const content = document.getElementById('mem-content').value.trim();

    try {
        const res = await fetch('/api/memory/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'fact', key_topic: key, category: cat, content })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Fakta berhasil disimpan ke Second Brain!', 'success');
            document.getElementById('mem-key').value = '';
            document.getElementById('mem-content').value = '';
            fetchMemory();
        }
    } catch (err) {
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    }
}

async function deleteMemoryFact(key) {
    if (!confirm(`Hapus fakta '${key}' dari Second Brain?`)) return;
    try {
        const res = await fetch('/api/memory/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key_topic: key })
        });
        const data = await res.json();
        showToast(data.message || 'Fakta dihapus', 'info');
        fetchMemory();
    } catch (err) {
        showToast(`Gagal menghapus: ${err.message}`, 'error');
    }
}

async function exportSecondBrain() {
    try {
        const res = await fetch('/api/brain/export');
        const data = await res.json();
        const blob = new Blob([data.markdown], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ALFA_Second_Brain_${new Date().toISOString().slice(0,10)}.md`;
        a.click();
        showToast('Second Brain diexport sebagai file Markdown!', 'success');
    } catch (err) {
        showToast(`Export gagal: ${err.message}`, 'error');
    }
}

// ==================== NEURAL VECTOR BRAIN JS ====================
function openVectorIngestModal() {
    document.getElementById('vector-ingest-modal').classList.remove('hidden');
    document.getElementById('vector-ingest-modal').classList.add('flex');
    lucide.createIcons();
}

function closeVectorIngestModal() {
    document.getElementById('vector-ingest-modal').classList.add('hidden');
    document.getElementById('vector-ingest-modal').classList.remove('flex');
}

async function submitVectorIngest(e) {
    e.preventDefault();
    const title = document.getElementById('vec-title').value.trim();
    const cat = document.getElementById('vec-cat').value;
    const content = document.getElementById('vec-content').value.trim();
    const btn = document.getElementById('btn-submit-ingest');

    btn.innerHTML = '<span class="animate-spin">⏳</span> Mengindeks...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/brain/vector/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content, category: cat })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            closeVectorIngestModal();
            document.getElementById('vec-title').value = '';
            document.getElementById('vec-content').value = '';
        } else {
            showToast(data.message || 'Gagal mengindeks dokumen', 'error');
        }
    } catch (err) {
        showToast(`Ingestion error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="database" class="w-4 h-4"></i> Indeks ke Vector Brain';
        btn.disabled = false;
        lucide.createIcons();
    }
}

async function runVectorSearch() {
    const query = document.getElementById('vector-search-query').value.trim();
    if (!query) {
        showToast('Masukkan kueri pencarian semantik terlebih dahulu.', 'info');
        return;
    }
    const container = document.getElementById('vector-results-container');
    const btn = document.getElementById('btn-vector-search');

    btn.innerHTML = '<span class="animate-spin">⏳</span> Mencari...';
    btn.disabled = true;
    container.classList.remove('hidden');
    container.innerHTML = '<div class="text-slate-400 text-center py-6 font-mono text-xs animate-pulse">Menghitung embedding & cosine similarity...</div>';

    try {
        const res = await fetch('/api/brain/vector/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, top_k: 5 })
        });
        const data = await res.json();
        if (data.status === 'success') {
            if (data.matches.length === 0) {
                container.innerHTML = '<div class="p-4 rounded-xl bg-dark-950 border border-white/5 text-slate-400 text-center font-mono text-xs">Tidak ditemukan kecocokan semantik di Vector Brain.</div>';
                return;
            }
            container.innerHTML = data.matches.map(m => `
                <div class="p-3.5 rounded-xl bg-dark-950 border border-cyan-500/30 flex flex-col space-y-2">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-2">
                            <span class="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 font-mono font-bold text-[10px] uppercase">${m.category}</span>
                            <span class="text-xs font-bold text-white font-mono">${m.doc_title} (Chunk #${m.chunk_index + 1})</span>
                        </div>
                        <span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono font-bold text-[10px]">Score: ${(m.similarity_score * 100).toFixed(1)}%</span>
                    </div>
                    <p class="text-xs text-slate-300 font-mono leading-relaxed bg-dark-900/80 p-2.5 rounded-lg border border-white/5">${m.chunk_text}</p>
                </div>
            `).join('');
        }
    } catch (err) {
        container.innerHTML = `<div class="p-3 text-rose-400 text-xs font-mono">Error: ${err.message}</div>`;
    } finally {
        btn.innerHTML = '<i data-lucide="search" class="w-3.5 h-3.5"></i> Cari Semantik';
        btn.disabled = false;
        lucide.createIcons();
    }
}

// ==================== SUPERPOWERS AGENTIC SKILLS JS ====================
let allSuperpowersData = [];
let activeSuperpowersCategory = 'all';
let currentSuperpowerMarkdown = '';

async function fetchSuperpowersSkills() {
    const grid = document.getElementById('superpowers-skills-grid');
    if (!grid) return;
    try {
        const res = await fetch('/api/skills/superpowers');
        const data = await res.json();
        if (data.status === 'success') {
            allSuperpowersData = data.skills || [];
            const countPill = document.getElementById('superpowers-count-pill');
            if (countPill) countPill.innerText = `⚡ ${allSuperpowersData.length} Superpower Skills`;
            renderSuperpowersSkills(allSuperpowersData);
        } else {
            grid.innerHTML = `<div class="text-rose-400 text-xs col-span-full font-mono">Gagal memuat skills: ${data.message || 'Error'}</div>`;
        }
    } catch (err) {
        grid.innerHTML = `<div class="text-rose-400 text-xs col-span-full font-mono">Gagal memuat Superpowers: ${err.message}</div>`;
    }
}

function renderSuperpowersSkills(skills) {
    const grid = document.getElementById('superpowers-skills-grid');
    if (!grid) return;
    if (skills.length === 0) {
        grid.innerHTML = '<div class="text-slate-500 text-center py-6 col-span-full font-mono text-xs">Tidak ada skill yang cocok dengan filter / pencarian.</div>';
        return;
    }

    grid.innerHTML = skills.map(s => `
        <div class="p-4 rounded-2xl bg-dark-950/90 border border-amber-500/20 hover:border-amber-400/60 hover:bg-dark-900 transition-all flex flex-col justify-between space-y-3 group shadow-lg relative overflow-hidden">
            <div class="space-y-2.5">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="text-2xl">${s.icon || '🦸'}</span>
                        <span class="px-2 py-0.5 text-[9px] font-mono font-bold rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 truncate max-w-[130px]">${s.category}</span>
                    </div>
                    <span class="w-2 h-2 rounded-full bg-emerald-400 shadow-glow-emerald" title="Active on all agents"></span>
                </div>
                <div>
                    <h4 class="text-xs font-bold text-white font-mono group-hover:text-amber-300 transition-colors flex items-center gap-1.5">
                        ${s.name}
                    </h4>
                    <p class="text-[11px] text-slate-300 mt-1 line-clamp-2 leading-relaxed font-sans">${s.description}</p>
                </div>
            </div>
            <div class="pt-2 border-t border-white/5 flex items-center justify-between gap-2">
                <span class="text-[10px] text-emerald-400/90 font-mono font-semibold flex items-center gap-1">
                    <i data-lucide="check" class="w-3 h-3 text-emerald-400"></i> All Units
                </span>
                <button onclick="openSuperpowerDetailModal('${s.id}')" class="px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-xl text-xs font-mono font-bold flex items-center gap-1.5 transition-all shadow-sm">
                    <i data-lucide="book-open" class="w-3 h-3"></i> Panduan
                </button>
            </div>
        </div>
    `).join('');

    lucide.createIcons();
}

function filterSuperpowersCategory(category, btn) {
    activeSuperpowersCategory = category;
    document.querySelectorAll('.sp-cat-btn').forEach(b => {
        b.classList.remove('bg-amber-500/20', 'text-amber-300', 'border-amber-500/40', 'active');
        b.classList.add('bg-dark-950', 'text-slate-400', 'border-white/10');
    });
    if (btn) {
        btn.classList.remove('bg-dark-950', 'text-slate-400', 'border-white/10');
        btn.classList.add('bg-amber-500/20', 'text-amber-300', 'border-amber-500/40', 'active');
    }

    const searchVal = (document.getElementById('superpowers-search-input')?.value || '').toLowerCase().trim();
    applySuperpowersFilters(category, searchVal);
}

function handleSuperpowersSearch(query) {
    applySuperpowersFilters(activeSuperpowersCategory, query.toLowerCase().trim());
}

function applySuperpowersFilters(category, query) {
    let filtered = allSuperpowersData;
    if (category !== 'all') {
        filtered = filtered.filter(s => s.category.toLowerCase().includes(category.toLowerCase()));
    }
    if (query) {
        filtered = filtered.filter(s => 
            s.name.toLowerCase().includes(query) || 
            s.id.toLowerCase().includes(query) || 
            s.description.toLowerCase().includes(query)
        );
    }
    renderSuperpowersSkills(filtered);
}

async function openSuperpowerDetailModal(skillId) {
    const modal = document.getElementById('superpower-detail-modal');
    const body = document.getElementById('sp-modal-body');
    const title = document.getElementById('sp-modal-title');
    const icon = document.getElementById('sp-modal-icon');
    if (!modal) return;

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    body.innerHTML = '<div class="text-slate-500 text-center py-8 font-mono">Memuat dokumentasi skill...</div>';

    try {
        const res = await fetch(`/api/skills/superpowers/${skillId}`);
        const data = await res.json();
        if (data.status === 'success') {
            currentSuperpowerMarkdown = data.content;
            const sk = allSuperpowersData.find(x => x.id === skillId);
            if (title) title.innerText = data.name.toUpperCase();
            if (icon) icon.innerText = sk?.icon || '🦸';

            let renderedHtml = '';
            if (typeof marked !== 'undefined' && marked.parse) {
                renderedHtml = marked.parse(data.content);
            } else {
                renderedHtml = `<pre class="p-4 bg-dark-950 rounded-xl font-mono text-xs text-slate-300 whitespace-pre-wrap overflow-x-auto">${data.content}</pre>`;
            }

            let refsHtml = '';
            if (data.reference_files && data.reference_files.length > 0) {
                refsHtml = `
                    <div class="mt-4 p-3 bg-amber-500/[0.05] border border-amber-500/20 rounded-xl space-y-2">
                        <h5 class="text-xs font-bold text-amber-300 font-mono flex items-center gap-1.5">
                            <i data-lucide="file-code" class="w-3.5 h-3.5"></i> Reference Files & Prompts (${data.reference_files.length})
                        </h5>
                        <div class="flex flex-wrap gap-2">
                            ${data.reference_files.map(rf => `<span class="px-2 py-1 bg-dark-950 border border-white/10 rounded text-[11px] font-mono text-slate-300">${rf}</span>`).join('')}
                        </div>
                    </div>
                `;
            }

            body.innerHTML = `
                <div class="prose prose-invert max-w-none text-xs space-y-3 font-sans">
                    ${renderedHtml}
                    ${refsHtml}
                </div>
            `;
            lucide.createIcons();
        } else {
            body.innerHTML = `<div class="p-4 text-rose-400 text-xs font-mono">Error: ${data.detail || 'Gagal memuat'}</div>`;
        }
    } catch (err) {
        body.innerHTML = `<div class="p-4 text-rose-400 text-xs font-mono">Error: ${err.message}</div>`;
    }
}

function closeSuperpowerDetailModal() {
    const modal = document.getElementById('superpower-detail-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function copySuperpowerContent() {
    if (!currentSuperpowerMarkdown) return;
    navigator.clipboard.writeText(currentSuperpowerMarkdown).then(() => {
        showToast('Panduan Superpower berhasil disalin ke clipboard!', 'success');
    }).catch(() => {
        showToast('Gagal menyalin panduan.', 'error');
    });
}

// ==================== UI/UX PRO MAX DESIGN INTELLIGENCE JS ====================
async function executeUiUxSearch() {
    const query = (document.getElementById('uiux-query-input')?.value || '').trim();
    const domain = document.getElementById('uiux-domain-select')?.value || 'auto';
    const body = document.getElementById('uiux-results-body');
    const btn = document.getElementById('btn-uiux-search');
    if (!query) {
        showToast('Masukkan topik atau kata kunci desain terlebih dahulu.', 'info');
        return;
    }

    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="animate-spin">⏳</span> Mencari...'; }
    if (body) body.innerText = '🔍 Menganalisis 67 gaya UI dan 192 reasoning rules...';

    try {
        const res = await fetch(`/api/skills/ui-ux-pro-max/search?q=${encodeURIComponent(query)}&domain=${domain}`);
        const data = await res.json();
        if (data.status === 'success') {
            body.innerText = data.formatted_output || JSON.stringify(data.results, null, 2);
        } else {
            body.innerText = `⚠️ Error: ${data.message || 'Pencarian gagal'}`;
        }
    } catch (err) {
        if (body) body.innerText = `⚠️ Network Error: ${err.message}`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="search" class="w-3.5 h-3.5"></i> Cari'; lucide.createIcons(); }
    }
}

async function executeUiUxDesignSystem() {
    const query = (document.getElementById('uiux-query-input')?.value || '').trim();
    const body = document.getElementById('uiux-results-body');
    const btn = document.getElementById('btn-uiux-ds');
    if (!query) {
        showToast('Masukkan topik produk atau nama proyek terlebih dahulu.', 'info');
        return;
    }

    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="animate-spin">⏳</span> Merancang DS...'; }
    if (body) body.innerText = '✨ Menghasilkan arsitektur Design System (Pola, Palet Hex, Font Pairing, dan Anti-Patterns)...';

    try {
        const res = await fetch('/api/skills/ui-ux-pro-max/design-system', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, project_name: query })
        });
        const data = await res.json();
        if (data.status === 'success') {
            body.innerText = data.design_system_text || 'Design system berhasil dibuat!';
            showToast(data.summary || 'Design system berhasil dibuat!', 'success');
        } else {
            body.innerText = `⚠️ Error: ${data.message || data.detail || 'Gagal membuat design system'}`;
        }
    } catch (err) {
        if (body) body.innerText = `⚠️ Network Error: ${err.message}`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="sparkles" class="w-3.5 h-3.5"></i> Buat DS'; lucide.createIcons(); }
    }
}

// ==================== SELF-EVOLUTION DYNAMIC PLUGINS JS ====================
function openCreatePluginModal() {
    document.getElementById('plugin-create-modal').classList.remove('hidden');
    document.getElementById('plugin-create-modal').classList.add('flex');
    lucide.createIcons();
}

function closeCreatePluginModal() {
    document.getElementById('plugin-create-modal').classList.add('hidden');
    document.getElementById('plugin-create-modal').classList.remove('flex');
}

async function fetchDynamicPlugins() {
    const grid = document.getElementById('dynamic-plugins-grid');
    if (!grid) return;
    try {
        const res = await fetch('/api/plugins/list');
        const data = await res.json();
        if (data.status === 'success') {
            if (data.plugins.length === 0) {
                grid.innerHTML = '<div class="text-slate-500 text-center py-6 col-span-full font-mono text-xs">Belum ada plugin buatan AI. Klik tombol "+ Buat Plugin Baru" di atas atau minta ALFA di Telegram!</div>';
                return;
            }
            grid.innerHTML = data.plugins.map(p => `
                <div class="p-4 rounded-xl bg-dark-950 border border-violet-500/30 flex flex-col justify-between space-y-3 group hover:border-violet-400/60 transition-all">
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <span class="px-2 py-0.5 text-[9px] font-mono font-bold rounded bg-violet-500/20 text-violet-300 border border-violet-500/30">DYNAMIC PLUGIN</span>
                            <button onclick="deleteDynamicPlugin('${p.tool_name}')" class="text-rose-400 hover:text-rose-300 p-1" title="Hapus Plugin">
                                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                            </button>
                        </div>
                        <h4 class="text-xs font-bold text-white font-mono flex items-center gap-1.5 truncate">
                            <span>⚡</span> ${p.tool_name}()
                        </h4>
                        <p class="text-[11px] text-slate-300 mt-1 line-clamp-2 leading-relaxed">${p.description}</p>
                    </div>
                    <button onclick="openToolModal('${p.tool_name}')" class="w-full py-2 bg-violet-500/10 hover:bg-violet-500/20 text-violet-300 border border-violet-500/30 rounded-xl text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-all">
                        <i data-lucide="play" class="w-3 h-3"></i> Test Eksekusi
                    </button>
                </div>
            `).join('');
            lucide.createIcons();
        }
    } catch (err) {
        grid.innerHTML = `<div class="text-rose-400 text-xs col-span-full font-mono">Gagal memuat plugin: ${err.message}</div>`;
    }
}

async function submitCreatePlugin(e) {
    e.preventDefault();
    const tool_name = document.getElementById('plugin-name').value.trim();
    const tool_description = document.getElementById('plugin-desc').value.trim();
    const tool_code = document.getElementById('plugin-code').value.trim();
    const btn = document.getElementById('btn-submit-plugin');

    btn.innerHTML = '<span class="animate-spin">⏳</span> Mengompilasi...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/plugins/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_name, tool_description, tool_code })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            closeCreatePluginModal();
            document.getElementById('plugin-name').value = '';
            document.getElementById('plugin-desc').value = '';
            document.getElementById('plugin-code').value = '';
            fetchDynamicPlugins();
            fetchTools();
        } else {
            showToast(data.message || 'Gagal membuat plugin', 'error');
        }
    } catch (err) {
        showToast(`Kompilasi error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="cpu" class="w-4 h-4"></i> Kompilasi & Pasang Tool';
        btn.disabled = false;
        lucide.createIcons();
    }
}

async function deleteDynamicPlugin(toolName) {
    if (!confirm(`Hapus plugin '${toolName}' secara permanen?`)) return;
    try {
        const res = await fetch('/api/plugins/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_name: toolName })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            fetchDynamicPlugins();
            fetchTools();
        } else {
            showToast(data.message || 'Gagal menghapus plugin', 'error');
        }
    } catch (err) {
        showToast(`Hapus error: ${err.message}`, 'error');
    }
}

// Artifacts Gallery
async function fetchArtifacts() {
    try {
        const res = await fetch('/api/artifacts');
        const data = await res.json();
        const grid = document.getElementById('artifacts-grid');
        if (data.status === 'success') {
            if (data.artifacts.length === 0) {
                grid.innerHTML = '<div class="text-slate-500 text-center py-12 col-span-full font-mono text-xs">Belum ada artifact file yang dibuat.</div>';
                return;
            }
            grid.innerHTML = data.artifacts.map(a => `
                <div class="glass-card p-4 rounded-2xl flex flex-col justify-between space-y-3 group hover:border-cyan-500/40">
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <span class="px-2 py-0.5 text-[9px] font-mono font-bold rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">${a.extension}</span>
                            <span class="text-[10px] text-slate-500 font-mono">${a.size_kb} KB</span>
                        </div>
                        <h4 class="text-xs font-bold text-white font-mono truncate" title="${a.name}">${a.name}</h4>
                        <p class="text-[10px] text-slate-500 font-mono mt-0.5">${a.modified}</p>
                    </div>
                    <a href="/api/artifacts/download?path=${encodeURIComponent(a.path)}" target="_blank" class="w-full py-2 bg-dark-950 hover:bg-cyan-500/20 text-slate-300 hover:text-cyan-300 border border-white/5 hover:border-cyan-500/30 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all">
                        <i data-lucide="download" class="w-3.5 h-3.5"></i> Download File
                    </a>
                </div>
            `).join('');
            lucide.createIcons();
        }
    } catch (err) {
        showToast(`Artifacts error: ${err.message}`, 'error');
    }
}

// ── 📁 Workspace Explorer ──
let wsStack = [];   // tumpukan path untuk breadcrumb

async function wsInit() {
    try {
        const res = await fetch('/api/workspace/roots');
        const data = await res.json();
        const sel = document.getElementById('ws-root-select');
        if (!sel) return;
        sel.innerHTML = (data.roots || []).map(r =>
            `<option value="${escAttr(r.path)}" ${r.exists ? '' : 'disabled'}>${r.label}${r.exists ? '' : ' (kosong)'}</option>`
        ).join('');
        const first = (data.roots || []).find(r => r.exists);
        if (first) { sel.value = first.path; wsLoadTree(first.path); }
    } catch (e) { console.error('wsInit', e); }
}

function _fmtSize(n) {
    if (n == null) return '';
    if (n > 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n > 1024) return (n / 1024).toFixed(1) + ' KB';
    return n + ' B';
}

async function wsLoadTree(path, pushStack = true) {
    const box = document.getElementById('ws-tree');
    if (!box) return;
    if (!path) { box.innerHTML = '<div class="text-amber-400 text-xs font-mono py-6 text-center">Pilih folder proyek di dropdown atas.</div>'; return; }
    if (pushStack && path) {
        const top = wsStack[wsStack.length - 1]?.path;
        if (path !== top) wsStack.push({ path });
    }
    box.innerHTML = '<div class="text-slate-500 text-xs font-mono py-6 text-center">Memuat...</div>';
    try {
        const res = await fetch(`/api/workspace/tree?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error((await res.json()).detail || res.status);
        const data = await res.json();
        if (!data.items.length) {
            box.innerHTML = '<div class="text-slate-500 text-xs font-mono py-6 text-center">(folder kosong)</div>';
            return;
        }
        const upBtn = wsStack.length > 1
            ? `<div class="sticky top-0 bg-dark-950/95 px-2 py-1.5 border-b border-white/5 mb-1">
                   <button onclick="wsGoUp()" class="text-[11px] font-mono text-cyan-400 hover:text-cyan-300">← naik ke folder atas</button>
               </div>` : '';
        box.innerHTML = upBtn + data.items.map(it => it.type === 'dir'
            ? `<button onclick="wsLoadTree('${escAttr(data.path)}/${escAttr(it.name)}')" class="w-full text-left px-2 py-1.5 rounded-lg hover:bg-white/5 flex items-center gap-2 group">
                   <span class="text-amber-400">📁</span>
                   <span class="text-xs text-slate-200 font-medium truncate group-hover:text-amber-300">${escAttr(it.name)}</span>
               </button>`
            : `<button onclick="wsOpenFile('${escAttr(data.path)}/${escAttr(it.name)}', '${escAttr(it.name)}')" class="w-full text-left px-2 py-1.5 rounded-lg hover:bg-white/5 flex items-center gap-2 group">
                   <span class="text-cyan-500 text-xs">${it.name.match(/\.(png|jpe?g|gif|webp)$/i) ? '🖼️' : '📄'}</span>
                   <span class="text-xs text-slate-300 truncate group-hover:text-cyan-300 flex-1">${escAttr(it.name)}</span>
                   <span class="text-[9px] font-mono text-slate-600 shrink-0">${_fmtSize(it.size)}</span>
               </button>`).join('');
    } catch (err) {
        box.innerHTML = `<div class="text-rose-400 text-xs font-mono p-3">${escAttr(String(err.message))}</div>`;
    }
}

function wsGoUp() {
    wsStack.pop();
    const prev = wsStack[wsStack.length - 1];
    if (prev) wsLoadTree(prev.path, false);
}

async function wsChangeRoot(sel) {
    const p = sel.value;
    if (!p) return;
    wsStack = [];            // root baru: reset navigasi breadcrumb
    await wsLoadTree(p);     // pushStack=true -> stack=[{p}]
}

async function wsOpenFile(path, name) {
    const view = document.getElementById('ws-file-view');
    const nameEl = document.getElementById('ws-file-name');
    const dl = document.getElementById('ws-file-dl');
    nameEl.textContent = name;
    view.textContent = 'Memuat...';
    dl.classList.add('hidden');
    try {
        const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        dl.href = data.download_url || '#';
        if (data.status === 'binary') {
            view.textContent = `📦 ${data.message}\nUkuran: ${_fmtSize(data.size)}`;
            dl.classList.remove('hidden');
            return;
        }
        view.textContent = data.content + (data.truncated
            ? `\n\n… [dipotong — total ${_fmtSize(data.size)}. Gunakan Download utk file lengkap]` : '');
        dl.classList.remove('hidden');
    } catch (err) {
        view.textContent = `Gagal membaca: ${err.message}`;
    }
}

// Guardian & Proactive
async function fetchGuardian() {
    try {
        const res = await fetch('/api/guardian/config');
        const data = await res.json();
        if (data.status === 'success') {
            if (data.guardian) {
                document.getElementById('guard-cpu').value = data.guardian.cpu_threshold || 90;
                document.getElementById('val-cpu').innerText = (data.guardian.cpu_threshold || 90) + '%';
                document.getElementById('guard-ram').value = data.guardian.ram_threshold || 85;
                document.getElementById('val-ram').innerText = (data.guardian.ram_threshold || 85) + '%';
                document.getElementById('guard-batt').value = data.guardian.battery_critical || 10;
                document.getElementById('val-batt').innerText = (data.guardian.battery_critical || 10) + '%';
                document.getElementById('guard-autokill').checked = data.guardian.auto_kill_ram_hogs || false;
            }
            if (data.proactive) {
                document.getElementById('proact-interval').value = data.proactive.min_hours_between_pings || 3;
                document.getElementById('val-interval').innerText = (data.proactive.min_hours_between_pings || 3) + ' Jam';
            }
        }
    } catch (err) {
        showToast(`Guardian error: ${err.message}`, 'error');
    }
}

async function saveGuardianConfig(e) {
    e.preventDefault();
    const payload = {
        guardian: {
            enabled: true,
            cpu_threshold: Number(document.getElementById('guard-cpu').value),
            ram_threshold: Number(document.getElementById('guard-ram').value),
            battery_critical: Number(document.getElementById('guard-batt').value),
            auto_kill_ram_hogs: document.getElementById('guard-autokill').checked
        },
        proactive: {
            enabled: true,
            min_hours_between_pings: Number(document.getElementById('proact-interval').value)
        }
    };
    try {
        const res = await fetch('/api/guardian/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        showToast(data.message || 'Konfigurasi guardian tersimpan!', 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

function openMediaPreviewModal(title, url, type) {
    const modal = document.getElementById('media-preview-modal');
    const titleEl = document.getElementById('preview-modal-title');
    const downloadEl = document.getElementById('preview-modal-download');
    const bodyEl = document.getElementById('preview-modal-body');

    if (!modal || !bodyEl) return;

    titleEl.innerText = title || 'Pratinjau Berkas';
    downloadEl.href = url;
    downloadEl.setAttribute('download', title || 'download');

    if (type === 'image') {
        bodyEl.innerHTML = `<img src="${url}" class="max-w-full max-h-[75vh] object-contain rounded-xl shadow-2xl border border-white/10" alt="${title}">`;
    } else if (type === 'pdf') {
        bodyEl.innerHTML = `<iframe src="${url}" class="w-full h-[75vh] rounded-xl border border-white/10 bg-white"></iframe>`;
    } else {
        bodyEl.innerHTML = `<div class="p-8 text-center text-slate-400 font-mono text-xs">Format pratinjau tidak didukung secara langsung. Silakan gunakan tombol Unduh di atas.</div>`;
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    lucide.createIcons();
}

function closeMediaPreviewModal() {
    const modal = document.getElementById('media-preview-modal');
    const bodyEl = document.getElementById('preview-modal-body');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    if (bodyEl) bodyEl.innerHTML = '';
}

function copyPathToClipboard(pathText) {
    navigator.clipboard.writeText(pathText).then(() => {
        showToast('Path berhasil disalin ke clipboard!', 'success');
    }).catch(() => {
        showToast('Gagal menyalin path.', 'error');
    });
}

function decorateArtifactCards(container) {
    if (!container) return;
    // Scan for file paths in text or code blocks — uses dynamic home dir to support any username
    const homeDir = window._alfaHomeDir || '/home';
    const escapedHome = homeDir.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pathRegex = new RegExp('(?:' + escapedHome + '\\/[^\\s`"\'<>\\)]+|~\\/Dokumen\\/[^\\s`"\'<>\\)]+|~\\/output\\/[^\\s`"\'<>\\)]+|\\/dev\\/shm\\/alfa_sandbox\\/[^\\s`"\'<>\\)]+)', 'g');
    const textNodes = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    let n;
    while (n = walker.nextNode()) {
        if (n.parentElement && !['A', 'BUTTON', 'SCRIPT', 'STYLE'].includes(n.parentElement.tagName)) {
            textNodes.push(n);
        }
    }

    // Also enhance any image links
    container.querySelectorAll('img').forEach(img => {
        if (!img.classList.contains('decorated-img') && !img.closest('#chat-attachments-preview')) {
            img.classList.add('decorated-img', 'rounded-xl', 'max-h-64', 'cursor-pointer', 'hover:opacity-90', 'transition-all', 'border', 'border-white/10', 'my-2');
            img.onclick = () => openMediaPreviewModal('Gambar', img.src, 'image');
        }
    });
}

// WhatsApp Live Authentication & QR Controller
async function fetchWaQr(isManual = false) {
    try {
        const res = await fetch('/api/wa/qr');
        const data = await res.json();
        const badge = document.getElementById('wa-auth-badge');
        const container = document.getElementById('wa-qr-container');

        if (data.status === 'READY' || data.status === 'AUTHENTICATED' || data.is_ready) {
            badge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold';
            badge.innerText = 'ONLINE (Logged In)';
            container.innerHTML = `
                <div class="p-5 flex flex-col items-center space-y-2">
                    <div class="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center justify-center text-xl shadow-glow-emerald">
                        <i data-lucide="check-circle-2" class="w-6 h-6"></i>
                    </div>
                    <h4 class="text-sm font-bold text-white">Akun WhatsApp Berhasil Terhubung!</h4>
                    <p class="text-xs text-slate-400 max-w-md">Bot WhatsApp aktif memantau pesan dan mengeksekusi integrasi Google Sheets 24/7.</p>
                </div>
            `;
        } else if (data.status === 'QR_READY' || data.qr_data_url) {
            badge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold pulse-dot';
            badge.innerText = 'PERLU SCAN QR (Waiting)';
            container.innerHTML = `
                <div class="flex flex-col items-center space-y-3">
                    <div class="p-3 bg-white rounded-2xl shadow-2xl inline-block border-4 border-emerald-400">
                        <img src="${data.qr_data_url}" alt="WhatsApp QR Code" class="w-64 h-64 object-contain rounded-lg">
                    </div>
                    <div class="space-y-1">
                        <h4 class="text-sm font-bold text-amber-400">Silakan Scan QR Code di Atas</h4>
                        <p class="text-xs text-slate-400">Buka WhatsApp di HP > Menu Perangkat Tertaut > Tautkan Perangkat</p>
                        <p class="text-[11px] text-slate-500 font-mono">QR refresh otomatis setiap 20 detik.</p>
                    </div>
                </div>
            `;
        } else if (data.status === 'INITIALIZING' || data.status === 'AUTHENTICATING') {
            badge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold pulse-dot';
            badge.innerText = 'MENGHUBUNGKAN (Loading)';
            container.innerHTML = `
                <div class="p-5 flex flex-col items-center space-y-3">
                    <div class="w-12 h-12 rounded-full bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 flex items-center justify-center text-xl animate-pulse">
                        <i data-lucide="loader" class="w-6 h-6 animate-spin"></i>
                    </div>
                    <h4 class="text-sm font-bold text-white">Menghubungkan ke WhatsApp Web...</h4>
                    <p class="text-xs text-slate-400 max-w-md">Memuat sesi tersimpan dan sinkronisasi enkripsi chat. Mohon tunggu beberapa detik...</p>
                </div>
            `;
        } else {
            badge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold';
            badge.innerText = `${data.status} (Disconnected)`;
            container.innerHTML = `
                <div class="p-5 flex flex-col items-center space-y-3">
                    <div class="w-12 h-12 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 flex items-center justify-center text-xl">
                        <i data-lucide="alert-triangle" class="w-6 h-6"></i>
                    </div>
                    <h4 class="text-sm font-bold text-white">Sesi WhatsApp Terputus / Belum Siap</h4>
                    <p class="text-xs text-slate-400 max-w-md">Klik tombol di bawah untuk membuat QR code baru atau cek service.</p>
                    <button onclick="controlService('wa-sheets-bot.service', 'restart')" class="px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 rounded-xl text-xs font-bold transition-all">
                        🔄 Restart Service & Buat QR Code
                    </button>
                </div>
            `;
        }
        lucide.createIcons();
        if (isManual) showToast(`Status WhatsApp: ${data.status}`, 'info');
    } catch (err) {
        console.error('WA QR fetch error:', err);
    }
}

async function logoutWa() {
    if (!confirm('Apakah Anda yakin ingin logout sesi WhatsApp? QR code baru akan langsung dibuat.')) return;
    try {
        const res = await fetch('/api/wa/logout', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'Logout diproses, menyiapkan QR code...', 'info');
        setTimeout(fetchWaQr, 1500);
    } catch (err) {
        showToast(`Gagal logout: ${err.message}`, 'error');
    }
}

// WhatsApp Google Sheets Recorded Reports Hub
let waReportsData = [];
let dataSettingsCache = null;
let waFormatsData = [];
let activeFormatFilter = 'all';

const formatColors = {
    'Laporan': { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/30' },
    'TJHIN': { bg: 'bg-violet-500/10', text: 'text-violet-400', border: 'border-violet-500/30' },
    'IMT': { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
    'SMDT': { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/30' },
    'Recon': { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
    'Pengambilan Material': { bg: 'bg-indigo-500/10', text: 'text-indigo-400', border: 'border-indigo-500/30' },
    'Stok': { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' }
};

// ── WA → Drive realtime uploads ──
function waDriveTypeIcon(name) {
    const n = String(name || '').toLowerCase();
    if (n.match(/\.(jpg|jpeg|png|webp|gif)$/)) return { icon: 'image', cls: 'text-emerald-400' };
    if (n.match(/\.(mp4|mkv|mov|webm)$/)) return { icon: 'video', cls: 'text-rose-400' };
    if (n.endsWith('.pdf')) return { icon: 'file-text', cls: 'text-rose-300' };
    if (n.match(/\.(xlsx|xls|csv)$/)) return { icon: 'sheet', cls: 'text-emerald-300' };
    return { icon: 'file', cls: 'text-slate-400' };
}

async function fetchWaDriveUploads(isManual = false) {
    const list = document.getElementById('wa-drive-uploads-list');
    if (!list) return;
    try {
        const res = await fetch('/api/wa/drive-uploads');
        const data = await res.json();
        const ups = data.uploads || [];
        const badge = document.getElementById('wa-drive-total-badge');
        if (badge) badge.innerText = `${ups.length} Berkas`;

        if (data.status !== 'success') {
            list.innerHTML = '<p class="text-center text-rose-400 font-mono text-xs py-4">Gagal memuat.</p>';
            return;
        }
        if (ups.length === 0) {
            list.innerHTML = '<p class="text-center text-slate-600 font-mono text-xs py-6">Belum ada berkas terunggah dari WhatsApp. Kirim berkas di grup sesuai Aturan Drive.</p>';
            return;
        }
        list.innerHTML = ups.map(u => {
            const ic = waDriveTypeIcon(u.file_name);
            const link = u.web_link
                ? `<a href="${u.web_link}" target="_blank" class="ml-2 text-[10px] text-cyan-300 hover:text-cyan-200 font-bold shrink-0">Buka ↗</a>`
                : '';
            return `<div class="flex items-center gap-2.5 p-2 rounded-lg bg-dark-950/60 border border-white/5 hover:border-white/15 transition-all">
                <i data-lucide="${ic.icon}" class="w-4 h-4 ${ic.cls} shrink-0"></i>
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-bold text-slate-200 truncate">${escAttr(u.file_name || '-')}</span>
                        <span class="text-[9px] font-mono px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 shrink-0">${escAttr((u.folder || '').replace('WA Media / ',''))}</span>
                    </div>
                    <div class="text-[9px] text-slate-500 font-mono truncate">
                        ${u.ts ? u.ts.slice(5, 16) : ''} ${u.sender ? '· ' + escAttr(u.sender) : ''} ${u.group ? '· ' + escAttr(u.group) : ''}
                        ${u.caption ? ' · <span class="italic">' + escAttr(String(u.caption).slice(0, 60)) + '</span>' : ''}
                    </div>
                </div>
                ${link}
            </div>`;
        }).join('');
        lucide.createIcons();
        if (isManual) showToast('Daftar unggahan Drive dimuat!', 'success');
    } catch (err) {
        console.error('fetchWaDriveUploads error:', err);
    }
}

async function fetchWaReports(isManual = false) {
    try {
        const res = await fetch('/api/wa/reports');
        const data = await res.json();
        if (data.status === 'success') {
            waReportsData = data.reports || [];
            waFormatsData = data.formats || [];
            document.getElementById('reports-total-badge').innerText = `${waReportsData.length} Laporan Tercatat`;

            renderFormatPills();
            renderReportsTable();
            if (isManual) showToast('Data laporan WhatsApp Google Sheets dimuat!', 'success');
        }
    } catch (err) {
        console.error('Error fetching WA reports:', err);
        if (isManual) showToast(`Gagal memuat laporan: ${err.message}`, 'error');
    }
}

function renderFormatPills() {
    const container = document.getElementById('format-pills-container');
    const filterSelect = document.getElementById('report-format-filter');
    if (!container || !filterSelect) return;

    let html = `
        <button onclick="setFormatFilter('all')" class="px-3 py-1 rounded-xl text-xs font-mono font-semibold transition-all border ${activeFormatFilter === 'all' ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-sm' : 'bg-dark-950 text-slate-400 border-white/5 hover:border-white/20'}">
            Semua (${waReportsData.length})
        </button>
    `;

    let optionsHtml = `<option value="all">Semua Format Tab</option>`;

    waFormatsData.forEach(fmt => {
        const count = waReportsData.filter(r => (r.format_name || r.tab) === fmt.name || (r.format_name || r.tab) === fmt.tab).length;
        const col = formatColors[fmt.name] || { bg: 'bg-white/5', text: 'text-slate-300', border: 'border-white/10' };
        const isActive = activeFormatFilter === fmt.name || activeFormatFilter === fmt.tab;

        html += `
            <button onclick="setFormatFilter('${fmt.name}')" class="px-3 py-1 rounded-xl text-xs font-mono transition-all border flex items-center gap-1.5 ${isActive ? 'bg-white/10 text-white border-cyan-400 font-bold' : `${col.bg} ${col.text} ${col.border} hover:opacity-80`}" title="Keyword: ${fmt.keywords.join(', ')}">
                <span>${fmt.name}</span>
                <span class="px-1.5 py-0.2 rounded bg-black/40 text-[10px]">${count}</span>
            </button>
        `;
        optionsHtml += `<option value="${fmt.name}" ${activeFormatFilter === fmt.name ? 'selected' : ''}>${fmt.name} (${fmt.tab})</option>`;
    });

    container.innerHTML = html;
    filterSelect.innerHTML = optionsHtml;
}

function setFormatFilter(fmt) {
    activeFormatFilter = fmt;
    const filterEl = document.getElementById('report-format-filter');
    if (filterEl) filterEl.value = fmt;
    renderFormatPills();
    renderReportsTable();
}

function renderReportsTable() {
    const queryEl = document.getElementById('report-search-input');
    const filterEl = document.getElementById('report-format-filter');
    const tbody = document.getElementById('reports-table-body');
    if (!tbody) return;

    const query = queryEl ? queryEl.value.toLowerCase().trim() : '';
    const formatFilter = filterEl ? filterEl.value : 'all';
    activeFormatFilter = formatFilter;

    let filtered = waReportsData.filter(r => {
        const matchFmt = formatFilter === 'all' || (r.format_name || r.tab) === formatFilter;
        const matchQuery = !query || 
            (r.body && r.body.toLowerCase().includes(query)) ||
            (r.sender && r.sender.toLowerCase().includes(query)) ||
            (r.group && r.group.toLowerCase().includes(query)) ||
            (r.format_name && r.format_name.toLowerCase().includes(query));
        return matchFmt && matchQuery;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="p-8 text-center text-slate-500 font-mono space-y-2">
                    <div class="text-2xl">📋</div>
                    <div class="text-xs font-semibold text-slate-400">Belum ada data laporan yang cocok.</div>
                    <div class="text-[11px] text-slate-600">Kirim pesan laporan di grup/chat WhatsApp dengan awalan format (contoh: <code>laporan</code>, <code>tjhin</code>, <code>imt</code>, <code>smdt</code>, <code>recon</code>, <code>stok</code>).</div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = filtered.map(r => {
        const col = formatColors[r.format_name || r.tab] || { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/20' };
        const safeBody = (r.body || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `
            <tr class="hover:bg-white/[0.02] transition-colors group">
                <td class="p-3.5 font-mono text-[11px] text-slate-400 whitespace-nowrap">${r.timestamp}</td>
                <td class="p-3.5 whitespace-nowrap">
                    <span class="px-2.5 py-0.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider ${col.bg} ${col.text} border ${col.border}">
                        ${r.format_name || r.tab}
                    </span>
                </td>
                <td class="p-3.5 font-mono text-xs text-slate-200 whitespace-nowrap">
                    <div class="flex items-center gap-1.5">
                        <i data-lucide="user" class="w-3.5 h-3.5 text-slate-400"></i>
                        <span>${r.sender}</span>
                    </div>
                </td>
                <td class="p-3.5 text-xs text-slate-300 whitespace-nowrap font-medium">
                    <span class="px-2 py-0.5 rounded bg-dark-900 border border-white/5 text-[11px]">${r.group}</span>
                </td>
                <td class="p-3.5 text-xs text-slate-200 leading-relaxed min-w-[280px]">
                    <div class="max-h-24 overflow-y-auto custom-scrollbar font-mono text-[11px] bg-dark-900/80 p-2 rounded-lg border border-white/5 whitespace-pre-wrap">${safeBody}</div>
                </td>
                <td class="p-3.5 text-center whitespace-nowrap">
                    ${r.synced_to_sheets 
                        ? '<span class="px-2.5 py-1 rounded-lg text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold inline-flex items-center gap-1"><i data-lucide="check" class="w-3 h-3"></i> Synced</span>' 
                        : '<span class="px-2.5 py-1 rounded-lg text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold inline-flex items-center gap-1"><i data-lucide="clock" class="w-3 h-3"></i> Queue</span>'}
                </td>
            </tr>
        `;
    }).join('');
    lucide.createIcons();
}

// ==========================================
// AI AGENT WORKFORCE & SWARM CONTROLLER
// ==========================================
let allAgentsData = [];
let allMeetingsData = [];
let allKeysData = [];
let modelsCatalog = {};
let activeTestingAgentId = null;

async function fetchModelsCatalog() {
    try {
        const res = await fetch('/api/models');
        const data = await res.json();
        if (data.status === 'success') {
            modelsCatalog = data.providers || {};
            onProviderSelectChange();
            onAgentProviderChange();
        }
    } catch (err) {
        console.error('Fetch models error:', err);
    }
}

async function fetchAgents() {
    try {
        const res = await fetch('/api/agents');
        const data = await res.json();
        if (data.status === 'success') {
            allAgentsData = data.agents || [];
            const badge = document.getElementById('agents-count-badge');
            if (badge) badge.innerText = `${allAgentsData.length} Agents Terdaftar`;
            const hqLive = document.getElementById('hq-live-agents-text');
            if (hqLive) hqLive.innerText = `${allAgentsData.length} AGENTS ONLINE`;
            renderAgentsGrid();
            renderHqRoundtablePods();
            renderMeetingParticipantsSelector();
        }
    } catch (err) {
        console.error('Fetch agents error:', err);
    }
}

// ==================== VIRTUAL AI HEADQUARTERS & 3D WAR ROOM ====================
let hqViewMode = 'war-room'; // 'war-room' or 'office'
let hqSfxEnabled = true;
let hqSpeedMultiplier = 1; // 1, 1.5, 2, or 99 (instant)
// AudioContext and Cyber SFX synthesized effects modularized into /static/js/modules/audio.js

function setHqViewMode(mode) {
    if (!document.getElementById('ai-virtual-hq')) return;
    hqViewMode = mode;
    const btnWar = document.getElementById('btn-mode-war-room');
    const btnOff = document.getElementById('btn-mode-office');
    const viewWar = document.getElementById('hq-roundtable-view');
    const viewOff = document.getElementById('hq-office-view');

    if (mode === 'war-room') {
        btnWar.className = 'px-3 py-1 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-bold transition-all flex items-center gap-1.5';
        btnOff.className = 'px-3 py-1 rounded-lg text-slate-400 hover:text-white transition-all flex items-center gap-1.5';
        viewWar.classList.remove('hidden');
        viewOff.classList.add('hidden');
        renderHqRoundtablePods();
    } else {
        btnOff.className = 'px-3 py-1 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-bold transition-all flex items-center gap-1.5';
        btnWar.className = 'px-3 py-1 rounded-lg text-slate-400 hover:text-white transition-all flex items-center gap-1.5';
        viewOff.classList.remove('hidden');
        viewWar.classList.add('hidden');
        renderHqOfficeDesks();
    }
    playCyberBeep(600, 'sine', 0.05, 0.07);
}

function renderHqRoundtablePods() {
    const container = document.getElementById('hq-agent-pods-container');
    if (!container) return;
    const activeAgents = allAgentsData.filter(a => a.is_enabled !== 0);

    const accessories = {
        1: { icon: '👑', label: 'Baton Conductor', tag: 'Alpha Orchestrator' },
        2: { icon: '💻', label: 'Matrix Terminal', tag: 'Fast 30B Coder' },
        3: { icon: '🛡️', label: 'Radar Scanner', tag: '550B Ultra Critic' },
        4: { icon: '🌐', label: 'Knowledge Globe', tag: '120B MoE Researcher' },
        5: { icon: '🎯', label: 'Roadmap Flow', tag: 'MiniMax M3 Strategist' },
        6: { icon: '🌊', label: 'Triage Radar', tag: 'Laguna XS 2.1 Co-Pilot' }
    };

    container.innerHTML = activeAgents.map((a, idx) => {
        const acc = accessories[a.id] || { icon: a.avatar_emoji || '🤖', label: a.role, tag: a.provider };
        const colTheme = a.color_theme || 'cyan';
        const auraGlow = {
            cyan: 'border-cyan-500/30 bg-cyan-500/10 hover:border-cyan-400 text-cyan-400',
            emerald: 'border-emerald-500/30 bg-emerald-500/10 hover:border-emerald-400 text-emerald-400',
            violet: 'border-violet-500/30 bg-violet-500/10 hover:border-violet-400 text-violet-400',
            amber: 'border-amber-500/30 bg-amber-500/10 hover:border-amber-400 text-amber-400',
            rose: 'border-rose-500/30 bg-rose-500/10 hover:border-rose-400 text-rose-400',
            blue: 'border-blue-500/30 bg-blue-500/10 hover:border-blue-400 text-blue-400',
            indigo: 'border-indigo-500/30 bg-indigo-500/10 hover:border-indigo-400 text-indigo-400'
        }[colTheme] || 'border-cyan-500/30 bg-cyan-500/10 text-cyan-400';

        return `
            <div id="hq-pod-${a.id}" onclick="triggerAgentHqClick(${a.id})" class="p-3.5 rounded-2xl bg-dark-900/90 border ${auraGlow} transition-all duration-300 cursor-pointer flex flex-col items-center justify-between text-center space-y-2 relative group hover:scale-105 hover:bg-dark-900 shadow-lg" title="Klik untuk Chat Uji / Interaksi">

                <!-- Equalizer bars for speaking state -->
                <div id="hq-equalizer-${a.id}" class="hidden absolute -top-3 left-1/2 -translate-x-1/2 flex items-end gap-0.5 px-2 py-0.5 rounded-full bg-dark-950/90 border border-cyan-500/40 z-20">
                    <span class="w-1 bg-cyan-400 rounded-full equalizer-bar" style="animation-delay: 0s;"></span>
                    <span class="w-1 bg-emerald-400 rounded-full equalizer-bar" style="animation-delay: 0.2s;"></span>
                    <span class="w-1 bg-violet-400 rounded-full equalizer-bar" style="animation-delay: 0.4s;"></span>
                    <span class="w-1 bg-cyan-400 rounded-full equalizer-bar" style="animation-delay: 0.1s;"></span>
                </div>

                <!-- Top Pod Accessory Badge -->
                <div class="w-full flex items-center justify-between text-xs font-bold text-slate-400">
                    <span class="truncate max-w-[80px]">${a.provider.toUpperCase()}</span>
                    <span class="text-sm float-anim">${acc.icon}</span>
                </div>

                <!-- Agent Avatar Circle with Glowing Ring -->
                <div id="hq-avatar-ring-${a.id}" class="w-14 h-14 rounded-2xl bg-dark-950 border-2 border-white/10 flex items-center justify-center text-2xl relative shadow-inner group-hover:border-cyan-400 transition-all">
                    <span>${a.avatar_emoji || '🤖'}</span>
                    <span id="hq-status-dot-${a.id}" class="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-400 border-2 border-dark-950 pulse-dot"></span>
                </div>

                <!-- Agent Identity & Role -->
                <div class="space-y-0.5 w-full">
                    <div class="text-sm font-bold text-white truncate">${a.name}</div>
                    <div class="text-xs text-slate-300 truncate leading-snug font-medium">${a.role}</div>
                </div>

                <!-- Live Pod State Badge -->
                <div id="hq-pod-state-${a.id}" class="w-full py-1 px-2 rounded-lg bg-white/5 border border-white/10 text-xs font-bold text-slate-200 truncate">
                    🟢 IDLE / SIAP
                </div>
            </div>
        `;
    }).join('');
}

function renderHqOfficeDesks() {
    const container = document.getElementById('hq-office-view');
    if (!container) return;
    const activeAgents = allAgentsData.filter(a => a.is_enabled !== 0);

    const deskTasks = {
        1: { task: 'Mengoordinasikan Swarm Queue', action: '👑 Reviewing Workflow' },
        2: { task: 'Optimasi Async Kernel & Refactor', action: '💻 Coding (Nemotron 30B)' },
        3: { task: 'Audit Kriptografi & VRAM Check', action: '🛡️ Scanning (Ultra 550B)' },
        4: { task: 'Sintesis Benchmark Lintas Domain', action: '🔍 Querying MoE 120B' },
        5: { task: 'Penyelarasan UX & Roadmap Rapat', action: '🎯 Mapping (MiniMax M3)' },
        6: { task: 'Triage Tiket & First-Response', action: '🌊 Support Co-Pilot' }
    };

    container.innerHTML = activeAgents.map(a => {
        const dt = deskTasks[a.id] || { task: 'Proses Tugas Otonom', action: '🤖 Standby' };
        return `
            <div onclick="triggerAgentHqClick(${a.id})" class="p-4 rounded-2xl bg-dark-900/90 border border-white/10 hover:border-cyan-500/40 transition-all cursor-pointer space-y-3 relative group hover:bg-dark-900 shadow-xl" title="Klik untuk Chat Uji / Interaksi">

                <!-- Desk Header -->
                <div class="flex items-center justify-between border-b border-white/5 pb-2">
                    <div class="flex items-center gap-2">
                        <span class="text-xl">${a.avatar_emoji || '🤖'}</span>
                        <div>
                            <h4 class="text-xs font-bold text-white font-mono">${a.name}</h4>
                            <span class="text-[10px] text-slate-400 font-mono">${a.role}</span>
                        </div>
                    </div>
                    <span class="px-2 py-0.5 text-[9px] font-mono rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-bold flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-dot"></span> MEJA AKTIF
                    </span>
                </div>

                <!-- 3D Isometric Desk Simulation Visual -->
                <div class="p-3 rounded-xl bg-dark-950 border border-white/5 flex items-center justify-between text-xs font-mono relative overflow-hidden">
                    <!-- Dual Monitor Screens -->
                    <div class="flex items-center gap-2">
                        <div class="w-12 h-9 rounded bg-slate-900 border border-cyan-500/40 p-1 flex flex-col justify-between shadow-inner">
                            <div class="w-full h-1 bg-cyan-400/60 rounded"></div>
                            <div class="w-3/4 h-1 bg-emerald-400/60 rounded"></div>
                            <div class="w-1/2 h-1 bg-cyan-400/40 rounded"></div>
                        </div>
                        <div class="w-12 h-9 rounded bg-slate-900 border border-violet-500/40 p-1 flex flex-col justify-between shadow-inner">
                            <div class="w-full h-1 bg-violet-400/60 rounded"></div>
                            <div class="w-2/3 h-1 bg-violet-400/40 rounded"></div>
                            <div class="w-4/5 h-1 bg-emerald-400/50 rounded"></div>
                        </div>
                    </div>

                    <!-- Steaming Coffee Cup -->
                    <div class="flex flex-col items-center relative">
                        <span class="text-xs text-amber-300/80 coffee-steam select-none">~</span>
                        <span class="text-sm">☕</span>
                    </div>

                    <!-- CPU Tower Indicator -->
                    <div class="px-2 py-1 rounded bg-dark-900 border border-white/10 text-[10px] text-right space-y-0.5">
                        <div class="text-cyan-400 font-bold">${a.provider}</div>
                        <div class="text-slate-500 text-[9px] truncate max-w-[80px]">${a.model.split('/').pop()}</div>
                    </div>
                </div>

                <!-- Desk Current Activity -->
                <div class="flex items-center justify-between text-[11px] font-mono text-slate-300 pt-1">
                    <span class="text-slate-400 truncate max-w-[170px]">${dt.task}</span>
                    <span class="text-cyan-400 font-bold">${dt.action}</span>
                </div>
            </div>
        `;
    }).join('');
}

function triggerAgentHqClick(agentId) {
    playCyberBeep(850, 'sine', 0.08, 0.1);
    openAgentTestModal(agentId);
}

function triggerCentralHoloClick() {
    playCyberBeep(520, 'triangle', 0.1, 0.1);
    scrollToMeetingRoom();
}

function simulateOfficeBreak() {
    const quotes = [
        { id: 1, text: "☕ Waktunya mereview alur kerja tim sambil menikmati secangkir kopi!" },
        { id: 2, text: "⚡ Menjalankan garbage collection dan kompilasi benchmark mikro." },
        { id: 3, text: "🛡️ Memeriksa integritas enkripsi Vault, semua firewall dalam kondisi 100% aman." },
        { id: 4, text: "🔍 Menarik data tren model AI terbaru dari HuggingFace dan arXiv." },
        { id: 5, text: "🎯 Merancang draft roadmap interaksi AI Swarm untuk sprint berikutnya." }
    ];
    const rand = quotes[Math.floor(Math.random() * quotes.length)];
    const agent = allAgentsData.find(a => a.id === rand.id) || allAgentsData[0];
    if (!agent) return;

    const bubble = document.getElementById('hq-active-speech-bubble');
    const bubbleAvatar = document.getElementById('speech-bubble-avatar');
    const bubbleName = document.getElementById('speech-bubble-name');
    const bubbleModel = document.getElementById('speech-bubble-model');
    const bubbleText = document.getElementById('speech-bubble-text');

    if (bubble && bubbleAvatar) {
        bubbleAvatar.innerText = agent.avatar_emoji || '🤖';
        bubbleName.innerText = `${agent.name} (Break Time)`;
        bubbleModel.innerText = `${agent.provider}/${agent.model.split('/').pop()}`;
        bubbleText.innerHTML = `<em>"${rand.text}"</em>`;
        bubble.classList.remove('hidden');

        playCyberBeep(750, 'triangle', 0.15, 0.1);
        showToast(`${agent.avatar_emoji} ${agent.name}: ${rand.text}`, 'info');

        setTimeout(() => {
            if (!isMeetingAnimationPlaying) bubble.classList.add('hidden');
        }, 4500);
    }
}

function replayLastMeeting() {
    if (!allMeetingsData || allMeetingsData.length === 0) {
        showToast('Belum ada riwayat rapat yang tersimpan untuk diputar ulang.', 'info');
        return;
    }
    const lastM = allMeetingsData[0];
    const transcript = typeof lastM.dialogue_transcript === 'string' ? JSON.parse(lastM.dialogue_transcript || '[]') : (lastM.dialogue_transcript || []);
    if (transcript.length === 0) {
        showToast('Transkrip rapat kosong.', 'error');
        return;
    }
    showToast(`Memutar ulang animasi rapat: "${lastM.title || lastM.topic}"`, 'info');
    document.getElementById('meeting-dialogue-container').classList.remove('hidden');
    document.getElementById('ai-virtual-hq').scrollIntoView({ behavior: 'smooth' });
    playHqMeetingAnimation(transcript, lastM.consensus, lastM.action_plan, lastM.topic || lastM.title);
}

async function playHqMeetingAnimation(transcript, consensus, actionPlan, topic) {
    // War Room animasi sudah dihapus - aktivitas live ada di Live Terminal.
    if (!document.getElementById('ai-virtual-hq')) return;
    // War Room animasi sudah dinonaktifkan - aktivitas live ada di Live Terminal.
    if (!document.getElementById('ai-virtual-hq')) return;
    if (!transcript || transcript.length === 0) return;
    isMeetingAnimationPlaying = true;

    const bubble = document.getElementById('hq-active-speech-bubble');
    const bubbleAvatar = document.getElementById('speech-bubble-avatar');
    const bubbleName = document.getElementById('speech-bubble-name');
    const bubbleModel = document.getElementById('speech-bubble-model');
    const bubbleText = document.getElementById('speech-bubble-text');
    const holoStage = document.getElementById('hq-holo-stage');
    const holoTopic = document.getElementById('hq-holo-topic');
    const ticker = document.getElementById('hq-bottom-ticker');
    const turnCounter = document.getElementById('hq-turn-counter');
    const modelTag = document.getElementById('hq-active-model-tag');
    const feed = document.getElementById('meeting-transcript-feed');

    if (feed) feed.innerHTML = '';
    if (holoStage) {
        holoStage.innerText = '🔴 KONFERENSI AI BERLANGSUNG';
        holoStage.className = 'text-[10px] font-mono text-rose-400 font-bold tracking-wider animate-pulse';
    }
    if (holoTopic) holoTopic.innerText = topic || 'Diskusi Antar AI Agent Spesialis';

    playTurnStartSfx();

    for (let i = 0; i < transcript.length; i++) {
        const turn = transcript[i];
        const agentObj = allAgentsData.find(a => a.name === turn.agent_name) || {
            id: 1, name: turn.agent_name, role: turn.role, avatar_emoji: turn.avatar_emoji || '🤖',
            model: 'Active LLM', provider: 'AI'
        };

        // Reset all pods to listening state
        allAgentsData.forEach(a => {
            const podState = document.getElementById(`hq-pod-state-${a.id}`);
            const eq = document.getElementById(`hq-equalizer-${a.id}`);
            const pod = document.getElementById(`hq-pod-${a.id}`);
            if (podState) podState.innerText = '✍️ MENCATAT...';
            if (eq) eq.classList.add('hidden');
            if (pod) pod.classList.remove('speaking-aura', 'scale-105');
        });

        // Highlight active speaker pod
        const activePod = document.getElementById(`hq-pod-${agentObj.id}`);
        const activePodState = document.getElementById(`hq-pod-state-${agentObj.id}`);
        const activeEq = document.getElementById(`hq-equalizer-${agentObj.id}`);

        if (activePod) {
            activePod.classList.add('speaking-aura', 'scale-105');
        }
        if (activePodState) {
            activePodState.innerText = `🗣️ BERBICARA (R${turn.round})`;
            activePodState.className = 'w-full py-0.5 px-1.5 rounded-lg bg-cyan-500/20 border border-cyan-400 text-[9px] font-mono font-bold text-cyan-300 truncate';
        }
        if (activeEq) activeEq.classList.remove('hidden');

        // Update bottom ticker and counter
        if (turnCounter) turnCounter.innerText = `Putaran: ${turn.round} • Giliran: ${i + 1}/${transcript.length}`;
        if (modelTag) modelTag.innerText = `${agentObj.name} (${agentObj.provider}/${(agentObj.model || '').split('/').pop()})`;
        if (ticker) ticker.innerText = `Sedang berbicara: ${agentObj.name} - ${agentObj.role}...`;

        // Show Speech Bubble
        if (bubble && bubbleAvatar) {
            bubbleAvatar.innerText = turn.avatar_emoji || '🤖';
            bubbleName.innerText = `${turn.agent_name} (${turn.role})`;
            bubbleModel.innerText = `${agentObj.provider}/${(agentObj.model || '').split('/').pop()}`;
            bubble.classList.remove('hidden');
        }

        playTurnStartSfx();

        // Append card to transcript feed
        if (feed) {
            const parsedMsg = marked.parse(turn.message || '');
            const newEntry = document.createElement('div');
            newEntry.className = 'p-4 rounded-2xl bg-dark-900/90 border border-white/5 space-y-2 group hover:border-white/10 transition-all hq-speech-bubble';
            newEntry.innerHTML = `
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2.5">
                        <div class="w-8 h-8 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 flex items-center justify-center text-sm">
                            ${turn.avatar_emoji || '🤖'}
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-bold text-white font-mono">${turn.agent_name}</span>
                                <span class="px-2 py-0.2 rounded text-[9px] font-mono font-semibold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">${turn.role}</span>
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 text-[10px] font-mono text-slate-500">
                        <span>Putaran ${turn.round}</span>
                        <span>•</span>
                        <span>${turn.timestamp || ''}</span>
                    </div>
                </div>
                <div class="text-xs text-slate-200 leading-relaxed font-sans prose prose-invert max-w-none pt-1">
                    ${parsedMsg}
                </div>
            `;
            feed.appendChild(newEntry);
            feed.scrollTop = feed.scrollHeight;
        }

        // Typewriter effect in speech bubble
        const fullText = turn.message || '';
        const baseDelay = hqSpeedMultiplier === 99 ? 0 : Math.max(8, 20 / hqSpeedMultiplier);

        if (hqSpeedMultiplier === 99) {
            if (bubbleText) bubbleText.innerHTML = marked.parse(fullText);
        } else if (bubbleText) {
            bubbleText.innerHTML = '';
            const stepSize = Math.max(1, Math.floor(fullText.length / 40));
            for (let c = 0; c < fullText.length; c += stepSize) {
                bubbleText.innerText = fullText.slice(0, c + stepSize);
                if (c % (stepSize * 4) === 0) playCyberBeep(900, 'sine', 0.02, 0.02);
                await new Promise(r => setTimeout(r, baseDelay));
            }
            bubbleText.innerHTML = marked.parse(fullText);
        }

        // Pause for reading
        const readingPause = (hqSpeedMultiplier === 99) ? 100 : Math.max(800, 2200 / hqSpeedMultiplier);
        await new Promise(r => setTimeout(r, readingPause));
    }

    // Meeting Completed: Victory Consensus Phase
    allAgentsData.forEach(a => {
        const podState = document.getElementById(`hq-pod-state-${a.id}`);
        const eq = document.getElementById(`hq-equalizer-${a.id}`);
        const pod = document.getElementById(`hq-pod-${a.id}`);
        if (podState) podState.innerText = '✅ SEPAKAT';
        if (eq) eq.classList.add('hidden');
        if (pod) pod.classList.remove('speaking-aura');
    });

    if (bubble) bubble.classList.add('hidden');
    if (holoStage) {
        holoStage.innerText = '🎉 KONSENSUS TERCAPAI';
        holoStage.className = 'text-[10px] font-mono text-emerald-400 font-bold tracking-wider';
    }
    if (ticker) ticker.innerText = 'Rapat otonom selesai. Seluruh agen menyepakati Action Plan terstruktur!';
    playConsensusSfx();

    isMeetingAnimationPlaying = false;
}

function renderAgentsGrid() {
    const grid = document.getElementById('agents-grid');
    if (!grid) return;
    if (allAgentsData.length === 0) {
        grid.innerHTML = '<div class="col-span-full text-center py-12 text-slate-500 font-mono text-xs glass-card rounded-2xl">Belum ada agent. Klik tombol <b>+ Tambah Agent</b> di atas untuk membuat agent baru.</div>';
        return;
    }

    const colorMaps = {
        cyan: 'border-cyan-500/30 text-cyan-400 bg-cyan-500/10 shadow-glow-cyan',
        emerald: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10 shadow-glow-emerald',
        violet: 'border-violet-500/30 text-violet-400 bg-violet-500/10 shadow-glow-violet',
        amber: 'border-amber-500/30 text-amber-400 bg-amber-500/10',
        rose: 'border-rose-500/30 text-rose-400 bg-rose-500/10',
        blue: 'border-blue-500/30 text-blue-400 bg-blue-500/10'
    };

    const providerBadges = {
        nvidia: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
        gemini: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
        openai: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
        groq: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
        openrouter: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
        anthropic: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
        ollama: 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    };

    grid.innerHTML = allAgentsData.map(a => {
        const isAct = a.is_enabled !== 0;
        const hasTools = a.enable_tools === 1 || a.enable_tools === true;
        const dot = isAct ? 'bg-emerald-400' : 'bg-slate-600';
        return `
            <div class="flex items-center gap-2 p-2 rounded-xl bg-dark-950/60 border ${isAct ? 'border-white/10' : 'border-white/5 opacity-50'} hover:border-cyan-500/30 transition-all group min-w-0">
                <div class="w-8 h-8 rounded-lg bg-cyan-500/15 text-base flex items-center justify-center shrink-0">${a.avatar_emoji || '🤖'}</div>
                <div class="min-w-0 flex-1 leading-tight">
                    <div class="flex items-center gap-1.5">
                        <span class="text-xs font-bold text-white truncate group-hover:text-cyan-300 transition-colors">${a.name}</span>
                        <span class="w-1.5 h-1.5 rounded-full ${dot} shrink-0"></span>
                    </div>
                    <div class="text-[9px] font-mono text-slate-500 truncate">${escAttr(a.provider || '')} · ${escAttr(a.model || '')} · ${escAttr(a.role || '')}</div>
                </div>
                <button onclick="toggleAgentTools(${a.id})" title="${hasTools ? 'Tools AKTIF (10 tools aman: web, file, sandbox). Klik utk matikan.' : 'Tools MATI (teks saja). Klik utk aktifkan.'}" class="p-1 rounded-md ${hasTools ? 'bg-amber-500/15 text-amber-400' : 'bg-dark-900 text-slate-600'} transition-all shrink-0"><i data-lucide="wrench" class="w-3 h-3"></i></button>
                <button onclick="openAgentModal(${a.id})" title="Edit & model" class="p-1 rounded-md bg-white/5 text-slate-400 hover:text-cyan-300 transition-all shrink-0"><i data-lucide="edit-3" class="w-3 h-3"></i></button>
                <button onclick="toggleAgent(${a.id})" title="${isAct ? 'Nonaktifkan' : 'Aktifkan'}" class="p-1 rounded-md ${isAct ? 'bg-emerald-500/10 text-emerald-400' : 'bg-dark-900 text-slate-600'} transition-all shrink-0"><i data-lucide="${isAct ? 'check-circle' : 'circle-off'}" class="w-3 h-3"></i></button>
            </div>`;
    }).join('');
    lucide.createIcons();
}

async function toggleAgentTools(id) {
    const a = (allAgentsData || []).find(x => x.id === id);
    if (!a) return;
    const next = !(a.enable_tools === 1 || a.enable_tools === true);
    try {
        const res = await fetch(`/api/agents/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable_tools: next ? 1 : 0 })
        });
        const d = await res.json();
        if (d.status === 'success') {
            a.enable_tools = next ? 1 : 0;
            showToast(`Tools agen "${a.name}" ${next ? 'diaktifkan (subset aman)' : 'dimatikan'}.`, 'success');
            renderAgentsGrid();
        } else { showToast(d.message || 'Gagal mengubah status tools.', 'error'); }
    } catch (e) { showToast('Gagal terhubung ke server.', 'error'); }
}

function renderMeetingParticipantsSelector() {
    const container = document.getElementById('meeting-participants-selector');
    if (!container) return;
    container.innerHTML = allAgentsData.filter(a => a.is_enabled !== 0).map(a => `
        <label class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-dark-900 border border-white/5 cursor-pointer hover:border-cyan-500/30 text-slate-300 text-xs font-mono">
            <input type="checkbox" name="meeting-agent" value="${a.name}" checked class="w-3.5 h-3.5 rounded bg-dark-950 text-violet-500 focus:ring-0">
            <span>${a.avatar_emoji || '🤖'} ${a.name}</span>
        </label>
    `).join('');
}

function setMeetingTopic(topic) {
    const input = document.getElementById('meeting-topic-input');
    if (input) {
        input.value = topic;
        input.focus();
    }
}

function toggleAllParticipants(shouldSelect) {
    document.querySelectorAll('input[name="meeting-agent"]').forEach(cb => cb.checked = shouldSelect);
}

function populateModelSelect(selectEl, customEl, provider, selectedModel = '') {
    if (!selectEl) return;
    const models = modelsCatalog[provider] || [];
    let optionsHtml = '';

    // Group models by category
    const grouped = {};
    models.forEach(m => {
        const cat = m.category || 'Daftar Model';
        if (!grouped[cat]) grouped[cat] = [];
        grouped[cat].push(m);
    });

    let foundMatch = false;
    for (const [catName, catModels] of Object.entries(grouped)) {
        optionsHtml += `<optgroup label="📂 ${catName}">`;
        catModels.forEach(m => {
            const isSel = (m.id === selectedModel);
            if (isSel) foundMatch = true;
            const pLabel = m.pricing_label ? `[${m.pricing_label}] ` : '';
            optionsHtml += `<option value="${m.id}" ${isSel ? 'selected' : ''}>${pLabel}${m.name}</option>`;
        });
        optionsHtml += `</optgroup>`;
    }

    optionsHtml += `<optgroup label="⚙️ Model Kustom">`;
    optionsHtml += `<option value="__custom__" ${(!foundMatch && selectedModel) ? 'selected' : ''}>⚙️ Ketik Model Kustom / Manual...</option>`;
    optionsHtml += `</optgroup>`;
    selectEl.innerHTML = optionsHtml;

    if (!foundMatch && selectedModel) {
        if (customEl) {
            customEl.classList.remove('hidden');
            customEl.value = selectedModel;
        }
    } else {
        if (customEl) customEl.classList.add('hidden');
    }
}

async function populateAgentKeySources(selectedKeyId = null) {
    const sel = document.getElementById('agent-key-source-select');
    if (!sel) return;
    // Muat daftar kunci bila belum ada (bug: sebelumnya kosong bila
    // user langsung ke tab Swarm tanpa membuka tab API Keys dulu)
    if (!allKeysData.length) {
        try {
            const res = await fetch('/api/keys');
            const data = await res.json();
            if (data.status === 'success') allKeysData = data.keys || [];
        } catch (e) { console.warn('gagal muat keys', e); }
    }
    let html = '<option value="default">🌐 Gunakan Default Aktif Provider</option>';
    allKeysData.forEach(k => {
        const isSel = (Number(selectedKeyId) === Number(k.id));
        html += `<option value="${k.id}" ${isSel ? 'selected' : ''}>🔑 [${k.provider.toUpperCase()}] ${k.name} (${k.masked_key})</option>`;
    });
    sel.innerHTML = html;
}

function onAgentKeySourceChange() {
    const keySourceVal = document.getElementById('agent-key-source-select').value;
    if (keySourceVal !== 'default') {
        const keyObj = allKeysData.find(k => Number(k.id) === Number(keySourceVal));
        if (keyObj) {
            document.getElementById('agent-provider-input').value = keyObj.provider;
            onAgentProviderChange(keyObj.default_model);
        }
    }
}

function onAgentProviderChange(targetModel = '') {
    const prov = document.getElementById('agent-provider-input').value;
    const modelSelect = document.getElementById('agent-model-select');
    const customInput = document.getElementById('agent-model-custom');
    populateModelSelect(modelSelect, customInput, prov, targetModel);
}

function onAgentModelSelectChange() {
    const sel = document.getElementById('agent-model-select');
    const custom = document.getElementById('agent-model-custom');
    if (sel.value === '__custom__') {
        custom.classList.remove('hidden');
        custom.focus();
    } else {
        custom.classList.add('hidden');
    }
}

function openAgentModal(agentId = null) {
    populateAgentKeySources();
    const titleEl = document.getElementById('agent-modal-title');
    const editIdEl = document.getElementById('agent-edit-id');

    if (agentId) {
        const a = allAgentsData.find(x => x.id === agentId);
        if (a) {
            editIdEl.value = a.id;
            titleEl.innerText = `✏️ EDIT KONFIGURASI AGENT: ${a.name}`;
            document.getElementById('agent-name-input').value = a.name;
            document.getElementById('agent-role-input').value = a.role;
            document.getElementById('agent-emoji-input').value = a.avatar_emoji || '🤖';
            document.getElementById('agent-color-input').value = a.color_theme || 'cyan';
            document.getElementById('agent-persona-input').value = a.persona || '';
            document.getElementById('agent-sysprompt-input').value = a.system_instruction || '';

            populateAgentKeySources(a.api_key_id);
            document.getElementById('agent-provider-input').value = a.provider || 'gemini';
            onAgentProviderChange(a.model);
        }
    } else {
        editIdEl.value = '';
        titleEl.innerText = 'KONFIGURASI AI AGENT BARU';
        document.getElementById('agent-name-input').value = '';
        document.getElementById('agent-role-input').value = '';
        document.getElementById('agent-emoji-input').value = '🤖';
        document.getElementById('agent-color-input').value = 'cyan';
        document.getElementById('agent-persona-input').value = '';
        document.getElementById('agent-sysprompt-input').value = '';
        document.getElementById('agent-provider-input').value = 'nvidia';
        onAgentProviderChange();
    }

    document.getElementById('agent-modal').classList.remove('hidden');
    document.getElementById('agent-modal').classList.add('flex');
    lucide.createIcons();
}

function closeAgentModal() {
    document.getElementById('agent-modal').classList.add('hidden');
    document.getElementById('agent-modal').classList.remove('flex');
}

async function saveCustomAgentForm(e) {
    e.preventDefault();
    const editId = document.getElementById('agent-edit-id').value;
    const modelSel = document.getElementById('agent-model-select').value;
    const customModel = document.getElementById('agent-model-custom').value.trim();
    const finalModel = (modelSel === '__custom__') ? customModel : modelSel;
    const keySourceVal = document.getElementById('agent-key-source-select').value;
    const apiKeyId = (keySourceVal === 'default') ? null : Number(keySourceVal);

    const payload = {
        name: document.getElementById('agent-name-input').value.trim(),
        role: document.getElementById('agent-role-input').value.trim(),
        avatar_emoji: document.getElementById('agent-emoji-input').value.trim() || '🤖',
        color_theme: document.getElementById('agent-color-input').value,
        provider: document.getElementById('agent-provider-input').value,
        model: finalModel,
        api_key_id: apiKeyId,
        persona: document.getElementById('agent-persona-input').value.trim(),
        system_instruction: document.getElementById('agent-sysprompt-input').value.trim()
    };

    try {
        const url = editId ? `/api/agents/${editId}` : '/api/agents';
        const method = editId ? 'PUT' : 'POST';

        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(editId ? `Konfigurasi Agent '${payload.name}' diperbarui!` : `Agent '${payload.name}' berhasil dibuat!`, 'success');
            closeAgentModal();
            fetchAgents();
        } else {
            showToast(`Gagal menyimpan agent: ${data.message || 'Error'}`, 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function toggleAgent(id) {
    try {
        const res = await fetch(`/api/agents/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_enabled: 0 })
        });
        fetchAgents();
    } catch (err) {
        showToast(`Toggle gagal: ${err.message}`, 'error');
    }
}

async function deleteAgent(id, name) {
    if (!confirm(`Hapus agent '${name}' dari AI Workforce?`)) return;
    try {
        const res = await fetch(`/api/agents/${id}`, { method: 'DELETE' });
        showToast(`Agent '${name}' dihapus`, 'info');
        fetchAgents();
    } catch (err) {
        showToast(`Hapus gagal: ${err.message}`, 'error');
    }
}

function viewAgentPrompt(id) {
    const agent = allAgentsData.find(a => a.id === id);
    if (!agent) return;
    document.getElementById('prompt-modal-agent-name').innerText = `${agent.avatar_emoji || '🤖'} System Instruction: ${agent.name}`;
    document.getElementById('prompt-modal-text').innerText = agent.system_instruction || '(Tidak ada system prompt kustom)';
    document.getElementById('agent-prompt-modal').classList.remove('hidden');
    document.getElementById('agent-prompt-modal').classList.add('flex');
    lucide.createIcons();
}

function closeAgentPromptModal() {
    document.getElementById('agent-prompt-modal').classList.add('hidden');
    document.getElementById('agent-prompt-modal').classList.remove('flex');
}

function openAgentTestModal(id) {
    const agent = allAgentsData.find(a => a.id === id);
    if (!agent) return;
    activeTestingAgentId = id;
    document.getElementById('test-agent-avatar').innerText = agent.avatar_emoji || '🤖';
    document.getElementById('test-agent-name').innerText = `Test Direct Chat: ${agent.name}`;
    document.getElementById('test-agent-role').innerText = `${agent.role} • ${agent.provider}/${agent.model}`;
    document.getElementById('test-chat-history').innerHTML = `
        <div class="text-slate-500 text-center py-6 font-mono text-[11px]">
            Koneksi ke <b>${agent.name}</b> (${agent.provider}/${agent.model}) siap.<br>Ketik pesan di bawah untuk menguji responsnya.
        </div>
    `;
    document.getElementById('agent-test-modal').classList.remove('hidden');
    document.getElementById('agent-test-modal').classList.add('flex');
    document.getElementById('test-chat-input').focus();
    lucide.createIcons();
}

function closeAgentTestModal() {
    document.getElementById('agent-test-modal').classList.add('hidden');
    document.getElementById('agent-test-modal').classList.remove('flex');
    activeTestingAgentId = null;
}

async function sendAgentTestMessage(e) {
    e.preventDefault();
    if (!activeTestingAgentId) return;
    const input = document.getElementById('test-chat-input');
    const message = input.value.trim();
    if (!message) return;

    const history = document.getElementById('test-chat-history');
    const btn = document.getElementById('btn-send-test-agent');

    // User bubble
    history.innerHTML += `
        <div class="flex justify-end">
            <div class="max-w-[85%] p-3 rounded-2xl bg-cyan-500/20 text-cyan-200 border border-cyan-500/30 text-xs">
                ${message.replace(/</g, '&lt;')}
            </div>
        </div>
    `;
    input.value = '';

    // Loading bubble
    const loadingId = 'loading-' + Date.now();
    history.innerHTML += `
        <div id="${loadingId}" class="flex justify-start">
            <div class="p-3 rounded-2xl bg-dark-900 border border-white/5 text-slate-400 text-xs font-mono flex items-center gap-2">
                <i data-lucide="loader" class="w-3.5 h-3.5 animate-spin text-cyan-400"></i> Sedang berpikir...
            </div>
        </div>
    `;
    history.scrollTop = history.scrollHeight;
    lucide.createIcons();
    btn.disabled = true;

    try {
        const res = await fetch(`/api/agents/${activeTestingAgentId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });
        const data = await res.json();
        document.getElementById(loadingId)?.remove();

        if (data.status === 'success') {
            const parsedReply = marked.parse(data.reply || '');
            history.innerHTML += `
                <div class="flex justify-start">
                    <div class="max-w-[90%] p-3.5 rounded-2xl bg-dark-900/95 border border-white/10 text-slate-200 text-xs leading-relaxed space-y-1">
                        <div class="flex items-center gap-2 text-[10px] font-mono text-cyan-400 pb-1 border-b border-white/5">
                            <span>${data.agent_name}</span>
                            <span>•</span>
                            <span>${data.duration_ms}ms</span>
                        </div>
                        <div class="prose prose-invert max-w-none">${parsedReply}</div>
                    </div>
                </div>
            `;
        } else {
            history.innerHTML += `<div class="p-2 rounded bg-rose-500/10 text-rose-400 text-xs font-mono">Error: ${data.message || 'Gagal'}</div>`;
        }
    } catch (err) {
        document.getElementById(loadingId)?.remove();
        history.innerHTML += `<div class="p-2 rounded bg-rose-500/10 text-rose-400 text-xs font-mono">Connection error: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        history.scrollTop = history.scrollHeight;
        lucide.createIcons();
    }
}

function scrollToMeetingRoom() {
    document.getElementById('meeting-room-panel').scrollIntoView({ behavior: 'smooth' });
}

// ==================== AI MEETING & SWARM WORKSPACE CONTROLLER ====================
let currentMeetingMode = 'execute';

async function loadMeetingFolders() {
    const sel = document.getElementById('meeting-folder-select');
    if (!sel) return;
    try {
        const res = await fetch('/api/swarm/folders');
        const data = await res.json();
        const cur = sel.value;
        sel.innerHTML = '<option value="">🌐 Bebas — agen pilih lokasi sendiri</option>';
        for (const f of (data.folders || [])) {
            const opt = document.createElement('option');
            opt.value = f.path;
            opt.textContent = `${f.label} — ${f.path}`;
            sel.appendChild(opt);
        }
        if (cur) sel.value = cur;
    } catch (e) { console.warn('gagal muat folder', e); }
}

function onMeetingFolderChange() {
    const sel = document.getElementById('meeting-folder-select');
    const custom = document.getElementById('meeting-folder-custom');
    if (!sel || !custom) return;
    custom.classList.toggle('hidden', sel.value !== '__custom__');
}

function getMeetingFolder() {
    const sel = document.getElementById('meeting-folder-select')?.value || '';
    if (sel === '__custom__') {
        return (document.getElementById('meeting-folder-custom')?.value || '').trim();
    }
    return sel;
}

function setMeetingFolder(path) {
    const sel = document.getElementById('meeting-folder-select');
    if (sel && path) { sel.value = path; onMeetingFolderChange(); }
}

function setMeetingMode(mode) {
    currentMeetingMode = 'execute';
    const topicLabel = document.getElementById('meeting-topic-label');
    const topicInput = document.getElementById('meeting-topic-input');
    const roundsLabel = document.getElementById('meeting-rounds-label');
    const roundsSelect = document.getElementById('meeting-rounds-select');
    const btnStart = document.getElementById('btn-start-meeting');
    const statusBadge = document.getElementById('meeting-status-badge');

    {

        if (topicLabel) topicLabel.innerText = 'Perintah / Tugas Nyata untuk Dikerjakan Bersama oleh Tim Swarm:';
        if (topicInput) topicInput.placeholder = 'Contoh: Buatkan script Python monitoring server, scrape data lowongan AI, audit keamanan port, dan buatkan laporan analitik lengkap...';
        if (roundsLabel) roundsLabel.innerText = 'Alur Koordinasi & Eksekusi:';
        if (roundsSelect) {
            roundsSelect.innerHTML = `
                <option value="1" selected>⚡ Eksekusi Cepat + Live Tool Actions (Rekomendasi)</option>
                <option value="2">⚡ Eksekusi Mendalam + Validasi Multi-Tahap</option>
            `;
        }
        if (btnStart) {
            btnStart.className = 'w-full mt-3 py-3 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white font-bold rounded-xl text-xs font-mono flex items-center justify-center gap-2 shadow-glow-amber transition-all';
            btnStart.innerHTML = '<i data-lucide="zap" class="w-4 h-4 text-amber-200"></i> Jalankan Swarm & Eksekusi Langsung Sekarang!';
        }
        if (statusBadge) {
            statusBadge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 self-start sm:self-auto font-bold';
            statusBadge.innerText = 'SWARM WORK STANDBY';
        }
    }
    lucide.createIcons();
}

async function startAiMeeting() {
    const topic = document.getElementById('meeting-topic-input').value.trim();
    if (!topic) {
        showToast('Masukkan topik atau perintah tugas terlebih dahulu.', 'error');
        return;
    }

    const checkedNodes = document.querySelectorAll('input[name="meeting-agent"]:checked');
    const participants = Array.from(checkedNodes).map(n => n.value);
    if (participants.length === 0) {
        showToast('Pilih minimal 1 agent peserta.', 'error');
        return;
    }

    const rounds = Number(document.getElementById('meeting-rounds-select').value) || 2;
    const btn = document.getElementById('btn-start-meeting');
    const btnCancel = document.getElementById('btn-cancel-meeting');
    const statusBadge = document.getElementById('meeting-status-badge');
    const dialogueContainer = document.getElementById('meeting-dialogue-container');
    const transcriptFeed = document.getElementById('meeting-transcript-feed');
    const consensusBox = document.getElementById('meeting-consensus-box');
    const execContainer = document.getElementById('meeting-execution-results-container');
    const execFeed = document.getElementById('meeting-execution-steps-feed');

    btn.disabled = true;
    if (btnCancel) { btnCancel.style.display = 'flex'; btnCancel.disabled = false; }
    if (currentMeetingMode === 'execute') {
        btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Swarm Sedang Bekerja & Mengeksekusi Tugas...';
        statusBadge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold animate-pulse';
        statusBadge.innerText = 'SWARM WORKING & EXECUTING...';
    } else {
        btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Rapat Sedang Berlangsung...';
        statusBadge.className = 'px-3 py-1 text-xs font-mono rounded-lg bg-violet-500/20 text-violet-300 border border-violet-500/30 font-bold animate-pulse';
        statusBadge.innerText = 'DISCUSSING & DEBATING...';
    }

    dialogueContainer.classList.remove('hidden');
    consensusBox.classList.add('hidden');
    if (execContainer) execContainer.classList.add('hidden');

    transcriptFeed.innerHTML = `
        <div class="p-6 flex flex-col items-center justify-center space-y-2 text-violet-300 text-xs font-mono">
            <i data-lucide="loader" class="w-6 h-6 animate-spin text-violet-400"></i>
            <span>${currentMeetingMode === 'execute' ? 'Membangunkan swarm agent dan mendistribusikan eksekusi tugas...' : 'Memanggil agent peserta rapat dan memulai perdebatan round-table...'}</span>
        </div>
    `;
    lucide.createIcons();

    try {
        const res = await fetch('/api/meetings/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                topic, 
                participants, 
                rounds, 
                mode: 'execute',
                folder: getMeetingFolder()
            })
        });
        const data = await res.json();
        if (data.status === 'cancelled') {
            // Render hasil parsial lalu tandai sesi dibatalkan
            renderMeetingDialogue(data.dialogue_transcript || []);
            document.getElementById('meeting-dialogue-count').innerText = `${(data.dialogue_transcript || []).length} Aksi Terkoordinasi`;
            if (data.execution_results && data.execution_results.length > 0) {
                renderSwarmExecutionResults(data.execution_results);
                if (execContainer) execContainer.classList.remove('hidden');
            }
            const markedConsensusC = marked.parse(data.consensus || 'Eksekusi dibatalkan.');
            document.getElementById('meeting-consensus-text').innerHTML = markedConsensusC;
            document.getElementById('meeting-action-plan-text').innerHTML = '';
            consensusBox.classList.remove('hidden');
            statusBadge.className = 'px-3.5 py-1 text-xs font-mono rounded-xl bg-slate-500/20 text-slate-300 border border-slate-400/40 font-black';
            statusBadge.innerText = 'DIBATALKAN ⏹';
            showToast('Eksekusi swarm dibatalkan. Hasil parsial tetap tersimpan.', 'warning');
        } else if (data.status === 'success') {
            renderMeetingDialogue(data.dialogue_transcript || []);
            document.getElementById('meeting-dialogue-count').innerText = `${(data.dialogue_transcript || []).length} Aksi Terkoordinasi`;

            // Render Live Execution Results if in Execution Mode
            if (data.mode === 'execute' && data.execution_results && data.execution_results.length > 0) {
                renderSwarmExecutionResults(data.execution_results);
                if (execContainer) execContainer.classList.remove('hidden');
            }

            // Render Consensus / Deliverable Result Box
            const headerEl = document.getElementById('meeting-consensus-header');
            if (headerEl) {
                headerEl.innerHTML = data.mode === 'execute' 
                    ? '<i data-lucide="award" class="w-5 h-5 text-amber-400"></i> 🏆 LAPORAN HASIL EKSEKUSI NYATA SWARM' 
                    : '<i data-lucide="award" class="w-5 h-5 text-emerald-400"></i> LAPORAN HASIL EKSEKUSI SWARM';
            }

            const markedConsensus = marked.parse(data.consensus || 'Tidak ada konsensus.');
            const markedAction = marked.parse(data.action_plan || '');
            document.getElementById('meeting-consensus-text').innerHTML = markedConsensus;
            document.getElementById('meeting-action-plan-text').innerHTML = markedAction;
            consensusBox.classList.remove('hidden');

            statusBadge.className = 'px-3.5 py-1 text-xs font-mono rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-black shadow-glow-emerald';
            statusBadge.innerText = data.mode === 'execute' ? 'EKSEKUSI SUKSES ⚡' : 'KONSENSUS TERCAPAI ✅';

            showToast(data.mode === 'execute' ? 'Swarm selesai mengeksekusi semua tugas langsung!' : 'Konferensi AI selesai & Action Plan berhasil dirumuskan!', 'success');

            // Scroll to visual virtual HQ
            document.getElementById('ai-virtual-hq')?.scrollIntoView({ behavior: 'smooth' });
            playHqMeetingAnimation(data.dialogue_transcript || [], data.consensus, data.action_plan, topic);
        } else {
            transcriptFeed.innerHTML = `<div class="p-4 text-rose-400 font-mono text-xs">Error: ${data.message || 'Gagal'}</div>`;
            statusBadge.innerText = 'SESI ERROR';
        }
    } catch (err) {
        transcriptFeed.innerHTML = `<div class="p-4 text-rose-400 font-mono text-xs">Connection error: ${err.message}</div>`;
        statusBadge.innerText = 'SESI ERROR';
    } finally {
        btn.disabled = false;
        if (btnCancel) btnCancel.style.display = 'none';
        setMeetingMode(currentMeetingMode);
        lucide.createIcons();
    }
}

async function cancelSwarmMeeting() {
    const btnCancel = document.getElementById('btn-cancel-meeting');
    try {
        if (btnCancel) {
            btnCancel.disabled = true;
            btnCancel.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menghentikan...';
            lucide.createIcons();
        }
        const res = await fetch('/api/meetings/cancel', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || (data.status === 'success' ? 'Sinyal pembatalan terkirim.' : 'Tidak ada sesi aktif.'), data.status === 'success' ? 'success' : 'error');
    } catch (err) {
        showToast(`Gagal mengirim sinyal batal: ${err.message}`, 'error');
    } finally {
        if (btnCancel) setTimeout(() => { btnCancel.disabled = false; }, 1500);
    }
}

function renderSwarmExecutionResults(steps) {
    const feed = document.getElementById('meeting-execution-steps-feed');
    if (!feed) return;

    feed.innerHTML = steps.map((s, idx) => {
        const parsedGen = marked.parse(s.generated_content || '');
        return `
            <div class="p-4 rounded-2xl bg-dark-900/90 border border-amber-500/30 hover:border-amber-500/50 space-y-3 transition-all shadow-md">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2.5">
                        <span class="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-sm shadow-sm">${s.avatar_emoji || '🤖'}</span>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-black text-white font-mono">${s.agent_name}</span>
                                <span class="px-2 py-0.2 rounded-md text-[9px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase">${s.role}</span>
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 text-[10px] font-mono">
                        <span class="px-2.5 py-0.5 rounded-lg bg-dark-950 border border-white/10 text-cyan-300">Tool: ${s.tool_used}</span>
                        <span class="px-2 py-0.5 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold">✅ ${s.duration_ms}ms</span>
                    </div>
                </div>

                <div class="p-3 rounded-xl bg-dark-950/90 border border-white/5 font-mono text-[11px] text-slate-200 space-y-1.5 shadow-inner">
                    <div class="text-slate-400 font-bold flex items-center gap-1.5">
                        <span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                        <span>Tugas Otonom: ${s.task_assigned}</span>
                    </div>
                    <div class="text-amber-200/95 whitespace-pre-wrap leading-relaxed">${s.execution_summary}</div>
                </div>

                ${s.deliverable_file ? `
                    <div class="flex items-center justify-between gap-2 text-xs font-mono text-emerald-300 p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 shadow-sm">
                        <div class="flex items-center gap-2 truncate">
                            <i data-lucide="file-check" class="w-4 h-4 text-emerald-400 flex-shrink-0"></i>
                            <span class="truncate">File Output: <b class="text-white">${s.deliverable_file}</b></span>
                        </div>
                        <button onclick="navigator.clipboard.writeText('${s.deliverable_file}'); showToast('Path file disalin!', 'success');" class="px-2 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-[10px] font-bold text-white whitespace-nowrap transition-all">
                            Copy Path
                        </button>
                    </div>
                ` : ''}

                <details class="text-xs font-mono text-slate-400 pt-1">
                    <summary class="cursor-pointer hover:text-white transition-colors flex items-center gap-1">
                        <span>▶️ Detail Solusi Teknis / Output Lengkap</span>
                    </summary>
                    <div class="mt-2.5 p-3.5 rounded-xl bg-dark-950 border border-white/10 text-slate-200 prose prose-invert max-w-none text-xs font-sans shadow-inner">
                        ${parsedGen}
                    </div>
                </details>
            </div>
        `;
    }).join('');
    lucide.createIcons();
}

function renderMeetingDialogue(transcript) {
    const feed = document.getElementById('meeting-transcript-feed');
    if (!feed) return;
    const colorMaps = {
        cyan: 'border-cyan-500/30 text-cyan-400 bg-cyan-500/10',
        emerald: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10',
        violet: 'border-violet-500/30 text-violet-400 bg-violet-500/10',
        amber: 'border-amber-500/30 text-amber-400 bg-amber-500/10',
        rose: 'border-rose-500/30 text-rose-400 bg-rose-500/10',
        blue: 'border-blue-500/30 text-blue-400 bg-blue-500/10'
    };

    feed.innerHTML = transcript.map(d => {
        const col = colorMaps[d.color_theme] || colorMaps.cyan;
        const parsedMsg = marked.parse(d.message || '');
        return `
            <div class="p-4 rounded-2xl bg-dark-900/90 border border-white/5 space-y-2 group hover:border-white/10 transition-all">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2.5">
                        <div class="w-8 h-8 rounded-xl ${col} flex items-center justify-center text-sm">
                            ${d.avatar_emoji || '🤖'}
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-bold text-white font-mono">${d.agent_name}</span>
                                <span class="px-2 py-0.2 rounded text-[9px] font-mono font-semibold uppercase ${col}">${d.role}</span>
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 text-[10px] font-mono text-slate-500">
                        <span>Putaran ${d.round}</span>
                        <span>•</span>
                        <span>${d.timestamp}</span>
                    </div>
                </div>
                <div class="text-xs text-slate-200 leading-relaxed font-sans prose prose-invert max-w-none pl-10">
                    ${parsedMsg}
                </div>
            </div>
        `;
    }).join('');
    lucide.createIcons();
}

async function fetchMeetings() {
    try {
        const res = await fetch('/api/meetings');
        const data = await res.json();
        if (data.status === 'success') {
            allMeetingsData = data.meetings || [];
            const tbody = document.getElementById('meetings-history-tbody');
            if (!tbody) return;
            if (allMeetingsData.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="p-6 text-center text-slate-500 font-mono text-xs">Belum ada riwayat rapat yang tersimpan.</td></tr>';
                return;
            }
            tbody.innerHTML = allMeetingsData.map(m => `
                <tr class="hover:bg-white/[0.02] transition-colors">
                    <td class="py-3 font-mono text-[11px] text-slate-400 whitespace-nowrap">${m.created_at}</td>
                    <td class="py-3">
                        <div class="flex items-center gap-2">
                            ${m.mode === 'execute' 
                                ? '<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">⚡ EKSEKUSI</span>'
                                : '<span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-violet-500/20 text-violet-300 border border-violet-500/30">📋 PLAN</span>'}
                            <span class="font-medium text-white max-w-xs truncate" title="${m.topic}">${m.topic}</span>
                        </div>
                    </td>
                    <td class="py-3">
                        <div class="flex flex-wrap gap-1">
                            ${(m.participants || []).map(p => `<span class="px-1.5 py-0.2 rounded bg-dark-900 border border-white/5 text-[10px] font-mono text-slate-300">${p}</span>`).join('')}
                        </div>
                    </td>
                    <td class="py-3 whitespace-nowrap">
                        <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${m.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}">${m.status}</span>
                    </td>
                    <td class="py-3 text-right whitespace-nowrap flex items-center justify-end gap-1.5">
                        <button onclick="replaySpecificMeeting(${m.id})" class="px-2.5 py-1 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-mono font-bold flex items-center gap-1 inline-flex transition-all" title="Putar Animasi di Meja Rapat">
                            <i data-lucide="play" class="w-3 h-3"></i> Animasi
                        </button>
                        <button onclick="viewMeetingDetails(${m.id})" class="px-2.5 py-1 rounded-lg bg-violet-500/10 hover:bg-violet-500/20 text-violet-300 border border-violet-500/30 text-xs font-mono font-bold flex items-center gap-1 inline-flex transition-all">
                            <i data-lucide="eye" class="w-3.5 h-3.5"></i> Detail
                        </button>
                    </td>
                </tr>
            `).join('');
            lucide.createIcons();
        }
    } catch (err) {
        console.error('Fetch meetings error:', err);
    }
}

let currentActiveModalMeeting = null;

async function viewMeetingDetails(id) {
    try {
        const res = await fetch(`/api/meetings/${id}`);
        const data = await res.json();
        if (data.status === 'success' && data.meeting) {
            const m = data.meeting;
            currentActiveModalMeeting = m;
            document.getElementById('m-modal-title').innerText = m.title;
            document.getElementById('m-modal-topic').innerText = `Agenda: ${m.topic}`;

            const box = document.getElementById('m-modal-transcript-box');
            box.innerHTML = (m.dialogue_transcript || []).map(d => `
                <div class="p-3 rounded-xl bg-dark-900 border border-white/5 space-y-1.5">
                    <div class="flex items-center justify-between text-xs font-mono">
                        <span class="font-bold text-cyan-400">${d.avatar_emoji || '🤖'} ${d.agent_name} (${d.role})</span>
                        <span class="text-slate-500 text-[10px]">R${d.round} • ${d.timestamp}</span>
                    </div>
                    <div class="text-xs text-slate-200 leading-relaxed font-sans">${marked.parse(d.message || '')}</div>
                </div>
            `).join('');

            if (m.execution_results && Array.isArray(m.execution_results) && m.execution_results.length > 0) {
                const execCards = m.execution_results.map(s => `
                    <div class="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs font-mono space-y-1 my-2">
                        <div class="flex items-center justify-between text-amber-300 font-bold">
                            <span>${s.avatar_emoji || '🤖'} ${s.agent_name} (${s.role})</span>
                            <span class="text-[10px] text-cyan-400">Tool: ${s.tool_used} • ${s.duration_ms}ms</span>
                        </div>
                        <div class="text-slate-300 text-[11px] whitespace-pre-wrap">${s.execution_summary}</div>
                        ${s.deliverable_file ? `<div class="text-emerald-400 text-[10px]">📁 Output: ${s.deliverable_file}</div>` : ''}
                    </div>
                `).join('');
                document.getElementById('m-modal-consensus-text').innerHTML = 
                    '<h4 class="text-xs font-bold text-amber-400 font-mono mb-2">⚡ HASIL EKSEKUSI LANGSUNG OLEH TIM SWARM:</h4>' +
                    execCards + '<div class="border-t border-white/10 my-3 pt-3"></div>' + 
                    marked.parse(m.consensus + '\n\n' + (m.action_plan || ''));
            } else {
                document.getElementById('m-modal-consensus-text').innerHTML = marked.parse(m.consensus + '\n\n' + (m.action_plan || ''));
            }

            document.getElementById('meeting-modal').classList.remove('hidden');
            document.getElementById('meeting-modal').classList.add('flex');
            lucide.createIcons();
        }
    } catch (err) {
        showToast(`Gagal memuat transkrip: ${err.message}`, 'error');
    }
}

function playCurrentModalMeetingAnimation() {
    if (!currentActiveModalMeeting) return;
    closeMeetingModal();
    const transcript = typeof currentActiveModalMeeting.dialogue_transcript === 'string' ? JSON.parse(currentActiveModalMeeting.dialogue_transcript || '[]') : (currentActiveModalMeeting.dialogue_transcript || []);
    document.getElementById('meeting-dialogue-container').classList.remove('hidden');
    document.getElementById('ai-virtual-hq').scrollIntoView({ behavior: 'smooth' });
    playHqMeetingAnimation(transcript, currentActiveModalMeeting.consensus, currentActiveModalMeeting.action_plan, currentActiveModalMeeting.topic || currentActiveModalMeeting.title);
}

function replaySpecificMeeting(id) {
    const m = allMeetingsData.find(x => x.id === id);
    if (!m) return;
    const transcript = typeof m.dialogue_transcript === 'string' ? JSON.parse(m.dialogue_transcript || '[]') : (m.dialogue_transcript || []);
    document.getElementById('meeting-dialogue-container').classList.remove('hidden');
    document.getElementById('ai-virtual-hq').scrollIntoView({ behavior: 'smooth' });
    playHqMeetingAnimation(transcript, m.consensus, m.action_plan, m.topic || m.title);
}

function closeMeetingModal() {
    document.getElementById('meeting-modal').classList.add('hidden');
    document.getElementById('meeting-modal').classList.remove('flex');
}

function copyConsensus() {
    const txt = document.getElementById('meeting-consensus-text').innerText + '\n\n' + document.getElementById('meeting-action-plan-text').innerText;
    navigator.clipboard.writeText(txt);
    showToast('Konsensus rapat disalin ke clipboard!', 'success');
}

// ==========================================
// WA SHEETS REPORT FORMAT EDITOR
// ==========================================
let _waFormats = [];
const WA_DYN_SOURCES = ['timestamp', 'sender', 'group', 'body'];

async function fetchWaFormats() {
    try {
        const res = await fetch('/api/wa/formats');
        const data = await res.json();
        _waFormats = Array.isArray(data.formats) ? data.formats : [];
        renderWaFormats();
        updateWaPreview();
    } catch (err) {
        document.getElementById('wa-formats-list').innerHTML =
            '<p class="text-center text-rose-400 font-mono text-xs py-6">Gagal memuat format: ' + err.message + '</p>';
    }
}

function renderWaFormats() {
    const wrap = document.getElementById('wa-formats-list');
    if (!wrap) return;
    const cnt = document.getElementById('wa-fmt-count');
    if (cnt) cnt.innerText = _waFormats.length ? `(${_waFormats.length})` : '';
    if (_waFormats.length === 0) {
        wrap.innerHTML = '<p class="text-center text-slate-600 font-mono text-xs py-6">Belum ada format. Klik "Tambah Format" untuk membuat.</p>';
        return;
    }
    wrap.innerHTML = _waFormats.map((f, i) => `
        <details class="rounded-xl bg-dark-950/70 border border-white/10 overflow-hidden" data-wa-f="${i}" ${i === 0 ? 'open' : ''}>
            <summary class="cursor-pointer select-none px-3 py-2 flex items-center gap-2 hover:bg-white/5 list-none">
                <i data-lucide="chevron-right" class="w-3 h-3 text-slate-500 transition-transform group-open:rotate-90"></i>
                <span class="text-xs font-bold text-white truncate" id="wa-sum-name-${i}">${escAttr(f.name)}</span>
                <span class="text-[9px] font-mono text-cyan-300/80 truncate max-w-[30%]" id="wa-sum-kw-${i}">${escAttr(f.keywords.join(', '))}</span>
                <span class="ml-auto text-[9px] font-mono text-amber-300/80 shrink-0" id="wa-sum-tab-${i}">${escAttr(f.tab)} · ${f.columns.length} kolom</span>
            </summary>
            <div class="px-3 pb-3 pt-1 space-y-2.5 border-t border-white/5">
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                        <label class="text-[9px] font-mono text-slate-500">Nama</label>
                        <input value="${escAttr(f.name)}" oninput="waSetF(${i},'name',this.value)" placeholder="Nama laporan"
                            class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-white font-bold focus:outline-none focus:border-emerald-500">
                    </div>
                    <div>
                        <label class="text-[9px] font-mono text-slate-500">Tab Sheets</label>
                        <input value="${escAttr(f.tab)}" oninput="waSetF(${i},'tab',this.value)" placeholder="Laporan"
                            class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-amber-300 font-mono focus:outline-none focus:border-emerald-500">
                    </div>
                </div>
                <div>
                    <label class="text-[9px] font-mono text-slate-500">Kata pemicu (pisah koma)</label>
                    <input value="${escAttr(f.keywords.join(', '))}" oninput="waSetKeywords(${i}, this.value)" placeholder="laporan, harian"
                        class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-cyan-300 font-mono focus:outline-none focus:border-emerald-500">
                </div>
                <div class="space-y-1">
                    <div class="flex items-center justify-between">
                        <label class="text-[9px] font-mono text-slate-500">Kolom (urut kiri→kanan): Judul | Sumber</label>
                        <button onclick="addWaCol(${i})" class="text-[10px] font-bold text-cyan-300 hover:text-cyan-200 flex items-center gap-0.5">
                            <i data-lucide="plus" class="w-3 h-3"></i> kolom
                        </button>
                    </div>
                    ${f.columns.map((c, j) => `
                        <div class="flex items-center gap-1">
                            <button onclick="moveWaCol(${i},${j},-1)" class="p-0.5 text-slate-600 hover:text-white" title="Geser kiri"><i data-lucide="chevron-left" class="w-3 h-3"></i></button>
                            <span class="text-[8px] font-mono text-slate-600 w-3">${j + 1}</span>
                            <input value="${escAttr(c.title)}" oninput="waSetCol(${i},${j},'title',this.value)" placeholder="Judul"
                                class="flex-1 min-w-0 bg-dark-900 border border-white/10 rounded-md px-1.5 py-1 text-[10px] text-white focus:outline-none focus:border-emerald-500">
                            <input value="${escAttr(c.source)}" list="wa-src-list" oninput="waSetCol(${i},${j},'source',this.value)" placeholder="sumber"
                                class="flex-1 min-w-0 bg-dark-900 border border-white/10 rounded-md px-1.5 py-1 text-[10px] text-violet-300 font-mono focus:outline-none focus:border-emerald-500">
                            <button onclick="delWaCol(${i},${j})" class="p-0.5 text-rose-400/60 hover:text-rose-300" title="Hapus"><i data-lucide="x" class="w-3 h-3"></i></button>
                            <button onclick="moveWaCol(${i},${j},1)" class="p-0.5 text-slate-600 hover:text-white" title="Geser kanan"><i data-lucide="chevron-right" class="w-3 h-3"></i></button>
                        </div>
                    `).join('')}
                </div>
                <div class="flex justify-end">
                    <button onclick="delWaFormat(${i})" class="text-[10px] font-bold text-rose-400/80 hover:text-rose-300 flex items-center gap-1">
                        <i data-lucide="trash-2" class="w-3 h-3"></i> Hapus format ini
                    </button>
                </div>
            </div>
        </details>
    `).join('');
    lucide.createIcons();
}

// Perbarui ringkasan lipatan tanpa re-render (agar fokus input tetap)
function waUpdateSummary(i) {
    const f = _waFormats[i];
    if (!f) return;
    const n = document.getElementById(`wa-sum-name-${i}`);
    const k = document.getElementById(`wa-sum-kw-${i}`);
    const t = document.getElementById(`wa-sum-tab-${i}`);
    if (n) n.innerText = f.name || '(tanpa nama)';
    if (k) k.innerText = f.keywords.join(', ');
    if (t) t.innerText = `${f.tab || '?'} · ${f.columns.length} kolom`;
}

// Mutators: update model WITHOUT full re-render so typing keeps focus
function waSetF(i, key, val) { if (_waFormats[i]) { _waFormats[i][key] = val; waUpdateSummary(i); } waMarkDirty('formats'); updateWaPreview(); }
function waSetKeywords(i, val) {
    if (!_waFormats[i]) return;
    _waFormats[i].keywords = val.split(',').map(k => k.trim()).filter(Boolean);
    waMarkDirty('formats');
    waUpdateSummary(i);
    updateWaPreview();
}
function waSetCol(i, j, key, val) {
    if (_waFormats[i] && _waFormats[i].columns[j]) _waFormats[i].columns[j][key] = val;
    waMarkDirty('formats');
    updateWaPreview();
}

function escAttr(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

function addWaFormat() {
    waMarkDirty('formats');
    let n = _waFormats.length + 1, name = `Format Baru ${n}`;
    const existing = new Set(_waFormats.map(f => f.name.toLowerCase()));
    while (existing.has(name.toLowerCase())) { n++; name = `Format Baru ${n}`; }
    _waFormats.push({
        name: name,
        keywords: ['kata-pemicu'],
        tab: 'Tab Baru',
        columns: [
            { title: 'Waktu', source: 'timestamp' },
            { title: 'Pengirim', source: 'sender' },
            { title: 'Isi', source: 'body' }
        ]
    });
    renderWaFormats();
    updateWaPreview();
}

function delWaFormat(i) {
    waMarkDirty('formats');
    if (!confirm(`Hapus format "${_waFormats[i]?.name}"? (Belum tersimpan sampai klik Simpan)`)) return;
    _waFormats.splice(i, 1);
    renderWaFormats();
    updateWaPreview();
}

function addWaCol(i) {
    if (_waFormats[i]) { waMarkDirty('formats'); _waFormats[i].columns.push({ title: '', source: 'body' }); renderWaFormats(); waUpdateSummary(i); updateWaPreview(); }
}
function delWaCol(i, j) {
    if (_waFormats[i]) { waMarkDirty('formats'); _waFormats[i].columns.splice(j, 1); renderWaFormats(); waUpdateSummary(i); updateWaPreview(); }
}
function moveWaCol(i, j, dir) {
    const cols = _waFormats[i]?.columns;
    if (!cols) return;
    const t = j + dir;
    if (t < 0 || t >= cols.length) return;
    [cols[j], cols[t]] = [cols[t], cols[j]];
    waMarkDirty('formats');
    renderWaFormats();
    waUpdateSummary(i);
    updateWaPreview();
}

// Client-side simulation of wa-sheets-bot/src/formats.js logic
function waSimulate(msg) {
    const lower = String(msg || '').toLowerCase();
    for (const f of _waFormats) {
        if ((f.keywords || []).some(k => lower.includes(String(k).toLowerCase()))) {
            const now = new Date();
            const ts = now.toLocaleDateString('id-ID') + ' ' + now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
            const ctx = { timestamp: ts, sender: '+62xxxxxxxxxx', group: 'Grup Contoh', body: msg };
            const headers = f.columns.map(c => c.title);
            const values = f.columns.map(c => {
                const s = c.source ?? c.value ?? '';
                return Object.prototype.hasOwnProperty.call(ctx, s) ? ctx[s] : String(s);
            });
            return { format: f, headers, values };
        }
    }
    return null;
}

function updateWaPreview() {
    const box = document.getElementById('wa-preview-result');
    const msg = document.getElementById('wa-preview-msg')?.value || '';
    if (!msg.trim()) { box.innerHTML = '<span class="text-slate-600">Ketik pesan contoh untuk melihat format mana yang cocok...</span>'; return; }
    const hit = waSimulate(msg);
    if (!hit) {
        box.innerHTML = '<span class="text-rose-400">❌ Tidak ada kata pemicu yang cocok — pesan akan diabaikan bot.</span>';
        return;
    }
    box.innerHTML =
        `<span class="text-emerald-400 font-bold">✅ Cocok: ${escAttr(hit.format.name)}</span> → tab Sheets <b class="text-amber-300">${escAttr(hit.format.tab)}</b><br>` +
        `<span class="text-slate-500">Header :</span> ${hit.headers.map(h => escAttr(h)).join(' | ')}<br>` +
        `<span class="text-slate-500">Isi bar:</span> ${hit.values.map(v => escAttr(v)).join(' | ')}`;
}

// ── Aturan media Drive (independen dari format teks) ──
let _waRules = [];
const WA_TYPE_LABELS = {
    foto: 'Foto', video: 'Video', pdf: 'PDF',
    excel: 'Excel/CSV', dokumen: 'Dokumen', audio: 'Audio'
};

async function fetchWaMediaRules() {
    try {
        const res = await fetch('/api/wa/media-rules');
        const data = await res.json();
        _waRules = Array.isArray(data.rules) ? data.rules : [];
        renderWaRules();
    } catch (err) {
        document.getElementById('wa-rules-list').innerHTML =
            '<p class="text-center text-rose-400 font-mono text-xs py-4">Gagal memuat aturan.</p>';
    }
}

function renderWaRules() {
    const wrap = document.getElementById('wa-rules-list');
    if (!wrap) return;
    const cnt = document.getElementById('wa-rule-count');
    if (cnt) {
        const on = _waRules.filter(r => r.enabled).length;
        cnt.innerText = _waRules.length ? `(${on}/${_waRules.length} aktif)` : '';
    }
    if (_waRules.length === 0) {
        wrap.innerHTML = '<p class="text-center text-slate-600 font-mono text-xs py-3">Belum ada aturan. Berkas tanpa teks akan diabaikan sampai Anda membuat aturan.</p>';
        return;
    }
    wrap.innerHTML = _waRules.map((r, i) => `
        <div class="p-3 rounded-xl bg-dark-950/70 border border-violet-500/20 space-y-2.5">
            <div class="flex items-center gap-2">
                <label class="flex items-center gap-1.5 cursor-pointer shrink-0" title="Aktif/nonaktif">
                    <input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="waRuleSet(${i},'enabled',this.checked)" class="accent-violet-500">
                    <span class="text-[10px] font-mono ${r.enabled ? 'text-emerald-400' : 'text-slate-500'}">${r.enabled ? 'ON' : 'OFF'}</span>
                </label>
                <input value="${escAttr(r.name)}" oninput="waRuleSet(${i},'name',this.value)" placeholder="Nama aturan"
                    class="flex-1 min-w-0 bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-xs text-white font-bold focus:outline-none focus:border-violet-500">
                <button onclick="delWaRule(${i})" class="p-1 rounded-lg bg-rose-500/15 text-rose-300 border border-rose-500/30 hover:bg-rose-500/25 shrink-0">
                    <i data-lucide="trash-2" class="w-3 h-3"></i>
                </button>
            </div>
            <div>
                <label class="text-[10px] font-mono text-slate-400">Jenis berkas:</label>
                <div class="flex flex-wrap gap-1 mt-1">
                    ${Object.entries(WA_TYPE_LABELS).map(([k, label]) => `
                        <button onclick="waRuleToggleType(${i},'${k}')" class="px-2 py-0.5 rounded-lg text-[10px] font-bold border transition-all ${(r.types || []).includes(k)
                            ? 'bg-violet-500/25 text-violet-200 border-violet-500/50'
                            : 'bg-dark-900 text-slate-500 border-white/10 hover:text-slate-300'}">${label}</button>
                    `).join('')}
                </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                    <label class="text-[10px] font-mono text-slate-400">Kata kunci opsional</label>
                    <input value="${escAttr(r.keyword)}" oninput="waRuleSet(${i},'keyword',this.value)" placeholder="(kosong = semua berkas)"
                        class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-cyan-300 font-mono focus:outline-none focus:border-violet-500">
                </div>
                <div>
                    <label class="text-[10px] font-mono text-slate-400">Subfolder Drive ("WA Media / …")</label>
                    <input value="${escAttr(r.folder)}" oninput="waRuleSet(${i},'folder',this.value)" placeholder="Dokumen"
                        class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-amber-300 font-mono focus:outline-none focus:border-violet-500">
                </div>
            </div>
            <div>
                <label class="text-[10px] font-mono text-slate-400">Pola nama file tersimpan</label>
                <input value="${escAttr(r.naming)}" oninput="waRuleSet(${i},'naming',this.value)" placeholder="{date}_{file}"
                    class="w-full bg-dark-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-white font-mono focus:outline-none focus:border-violet-500">
            </div>
        </div>
    `).join('');
    lucide.createIcons();
}

function waRuleSet(i, key, val) { if (_waRules[i]) { _waRules[i][key] = val; waMarkDirty('rules'); } }
function waRuleToggleType(i, type) {
    if (!_waRules[i]) return;
    const t = _waRules[i].types || [];
    const idx = t.indexOf(type);
    if (idx >= 0) t.splice(idx, 1); else t.push(type);
    waMarkDirty('rules');
    renderWaRules();
}
function addWaRule() {
    waMarkDirty('rules');
    // Nama default unik agar tidak kena validasi duplikat
    let n = _waRules.length + 1, name = `Aturan ${n}`;
    const existing = new Set(_waRules.map(r => r.name.toLowerCase()));
    while (existing.has(name.toLowerCase())) { n++; name = `Aturan ${n}`; }
    _waRules.push({ name, enabled: true, types: ['pdf'], keyword: '', folder: 'Dokumen', naming: '{date}_{file}' });
    renderWaRules();
}
function delWaRule(i) {
    waMarkDirty('rules');
    if (!confirm(`Hapus aturan "${_waRules[i]?.name}"?`)) return;
    _waRules.splice(i, 1);
    renderWaRules();
}

async function saveWaMediaRules(silent = false) {
    const btn = document.getElementById('btn-save-wa-rules');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3 h-3 animate-spin"></i> ...';
    let result = null;
    try {
        const res = await fetch('/api/wa/media-rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rules: _waRules })
        });
        const data = await res.json();
        result = data;
        if (data.status === 'success') {
            waClearDirty('rules');
            if (!silent) showToast(data.message, 'success');
        } else if (data.validation_errors) {
            showToast('Validasi gagal', 'error');
            alert('Perbaiki:\n\n• ' + data.validation_errors.join('\n• '));
        } else showToast(data.message || 'Gagal.', 'error');
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="save" class="w-3 h-3"></i> Simpan';
    }
    return result;
}

async function saveWaFormats(silent = false) {
    const btn = document.getElementById('btn-save-wa-formats');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menyimpan...';
    lucide.createIcons();
    let result = null;
    try {
        const res = await fetch('/api/wa/formats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ formats: _waFormats })
        });
        const data = await res.json();
        result = data;
        if (data.status === 'success') {
            waClearDirty('formats');
            if (!silent) showToast(data.message, 'success');
        } else if (data.validation_errors) {
            showToast('Validasi gagal: ' + data.message, 'error');
            alert('Perbaiki dulu:\n\n• ' + data.validation_errors.join('\n• '));
        } else {
            showToast(data.message || 'Gagal menyimpan.', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="save" class="w-3.5 h-3.5"></i> Simpan Format';
        lucide.createIcons();
    }
    return result;
}

// ==========================================
// API KEY VAULT CONTROLLER
// ==========================================
function fmtTokens(n) {
    n = Number(n) || 0;
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
}

let _tuTimer = null;
async function fetchTokenUsage() {
    try {
        const hours = document.getElementById('tu-window')?.value || 24;
        const res = await fetch(`/api/keys/usage?hours=${hours}`);
        const data = await res.json();
        if (data.status !== 'success') return;

        document.getElementById('tu-today').innerText = fmtTokens(data.tokens_today);
        document.getElementById('tu-calls').innerText = fmtTokens(data.calls_today);
        document.getElementById('tu-alltime').innerText = fmtTokens(data.total_all_time);

        // Hourly bar chart (last 12 buckets shown, height relative to max)
        const chart = document.getElementById('tu-chart');
        const buckets = (data.hourly || []).slice(-12);
        const maxTok = Math.max(1, ...buckets.map(b => b.tokens));
        if (buckets.length === 0) {
            chart.innerHTML = '<p class="w-full text-center text-slate-600 font-mono text-[10px] pb-1">Belum ada aktivitas pada rentang ini</p>';
        } else {
            chart.innerHTML = buckets.map(b => {
                const h = Math.max(6, Math.round(b.tokens / maxTok * 100));
                const label = b.bucket.slice(11, 16);
                return `<div class="flex-1 flex flex-col items-center justify-end group relative" title="${b.bucket} — ${b.tokens.toLocaleString('id-ID')} token (${b.calls} call)">
                    <div class="w-full rounded-t bg-gradient-to-t from-cyan-600/60 to-emerald-400/80" style="height:${h}%"></div>
                    <span class="text-[8px] text-slate-500 font-mono mt-0.5">${label}</span>
                </div>`;
            }).join('');
        }

        // Per-key rows with proportional bars
        const wrap = document.getElementById('tu-perkey');
        const rows = data.per_key || [];
        if (rows.length === 0) {
            wrap.innerHTML = '<p class="text-center text-slate-600 font-mono text-xs py-4">Belum ada pemakaian tercatat. Data muncul otomatis saat bot/agent bekerja.</p>';
            return;
        }
        const maxRow = Math.max(...rows.map(r => r.total_tokens || 0), 1);
        wrap.innerHTML = rows.map(r => {
            const pct = Math.max(4, Math.round((r.total_tokens || 0) / maxRow * 100));
            const nm = r.key_name || r.key_label || '(env)';
            return `<div class="p-2 rounded-lg bg-dark-950/60 border border-white/5">
                <div class="flex items-center justify-between text-xs mb-1">
                    <span class="font-bold text-slate-200 truncate max-w-[55%]" title="${nm} — ${r.provider}">${nm}</span>
                    <span class="font-mono text-cyan-300">${fmtTokens(r.total_tokens)} <span class="text-slate-500 text-[10px]">(${fmtTokens(r.prompt_tokens)}+${fmtTokens(r.completion_tokens)})</span></span>
                </div>
                <div class="h-1.5 w-full rounded-full bg-white/5 overflow-hidden">
                    <div class="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-400" style="width:${pct}%"></div>
                </div>
                <div class="flex justify-between text-[9px] text-slate-500 font-mono mt-1">
                    <span>${r.provider}${r.model ? ' · ' + r.model : ''}</span>
                    <span>${r.calls} call · ${r.last_used ? r.last_used.slice(11,16) : ''}</span>
                </div>
            </div>`;
        }).join('');
    } catch (err) {
        console.error('Token usage fetch error:', err);
    }
}

function startTokenUsagePolling() {
    if (_tuTimer) clearInterval(_tuTimer);
    fetchTokenUsage();
    _tuTimer = setInterval(fetchTokenUsage, 10000);
}

async function fetchKeys() {
    try {
        const res = await fetch('/api/keys');
        const data = await res.json();
        if (data.status === 'success') {
            allKeysData = data.keys || [];
            renderKeysGrid(allKeysData);
        }
    } catch (err) {
        console.error('Fetch keys error:', err);
    }
}

function renderKeysGrid(keys) {
    const grid = document.getElementById('keys-grid');
    if (!grid) return;
    if (keys.length === 0) {
        grid.innerHTML = '<div class="col-span-full text-center py-12 text-slate-500 font-mono text-xs glass-card rounded-2xl">Belum ada API Key tersimpan. Tambahkan kunci baru melalui formulir di atas.</div>';
        return;
    }

    const providerBadges = {
        nvidia: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        gemini: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
        openai: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
        groq: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
        openrouter: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
        anthropic: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
        ollama: 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    };

    grid.innerHTML = keys.map(k => {
        const provBadge = providerBadges[k.provider] || 'bg-dark-900 text-slate-400 border-white/5';
        return `
            <div class="glass-card p-5 rounded-2xl flex flex-col justify-between space-y-4 border ${k.is_active ? 'border-emerald-500/40 shadow-glow-emerald' : 'border-white/5'} group">
                <div class="space-y-2.5">
                    <div class="flex items-center justify-between">
                        <span class="px-2.5 py-0.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border ${provBadge}">
                            ${k.provider}
                        </span>
                        ${k.is_active 
                            ? '<span class="text-[10px] font-mono text-emerald-400 font-bold flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 pulse-dot"></span> ACTIVE DEFAULT</span>' 
                            : `<button onclick="activateKey(${k.id})" class="px-2 py-0.5 rounded bg-white/5 hover:bg-emerald-500/20 text-slate-400 hover:text-emerald-300 text-[10px] font-mono transition-all">Set Aktif</button>`}
                    </div>
                    <h4 class="text-sm font-bold text-white font-mono">${k.name}</h4>
                    <div class="p-2.5 bg-dark-950 rounded-xl border border-white/5 font-mono text-xs text-cyan-300 flex items-center justify-between">
                        <span>${k.masked_key}</span>
                        <i data-lucide="key" class="w-3.5 h-3.5 text-slate-500"></i>
                    </div>
                    <p class="text-[11px] text-slate-400 font-mono">Model: <span class="text-slate-200 font-semibold">${k.default_model}</span></p>
                    ${k.base_url ? `<p class="text-[10px] text-slate-500 font-mono truncate" title="${k.base_url}">URL: ${k.base_url}</p>` : ''}

                    <div id="key-ping-badge-${k.id}" class="hidden p-2 rounded-xl text-[10px] font-mono"></div>
                </div>

                <div class="pt-3 border-t border-white/5 flex items-center justify-between text-xs font-mono">
                    <button onclick="testKeyPing(${k.id})" id="btn-ping-${k.id}" class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-cyan-500/20 text-slate-300 hover:text-cyan-300 text-[10px] font-mono font-bold flex items-center gap-1 border border-white/5 transition-all">
                        <i data-lucide="zap" class="w-3 h-3 text-cyan-400"></i> Test Ping
                    </button>
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-slate-500">${k.created_at}</span>
                        <button onclick="deleteKey(${k.id}, '${k.name}')" class="text-slate-500 hover:text-rose-400 transition-colors p-1" title="Hapus Key">
                            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    lucide.createIcons();
}

async function testKeyPing(keyId) {
    const btn = document.getElementById(`btn-ping-${keyId}`);
    const badge = document.getElementById(`key-ping-badge-${keyId}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader" class="w-3 h-3 animate-spin"></i> Ping...';
        lucide.createIcons();
    }

    try {
        const res = await fetch(`/api/keys/${keyId}/test`, { method: 'POST' });
        const data = await res.json();
        badge.classList.remove('hidden');

        if (data.status === 'success') {
            badge.className = 'p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-mono text-[10px] flex items-center justify-between';
            badge.innerHTML = `<span>🟢 Connected (${data.duration_ms}ms)</span><span>${data.response.substring(0, 20)}...</span>`;
            showToast('Koneksi API Key terverifikasi aktif!', 'success');
        } else {
            badge.className = 'p-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 font-mono text-[10px]';
            badge.innerHTML = `<span>🔴 Error: ${data.response || 'Gagal'}</span>`;
            showToast('Gagal memvalidasi API key.', 'error');
        }
    } catch (err) {
        badge.classList.remove('hidden');
        badge.className = 'p-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 font-mono text-[10px]';
        badge.innerHTML = `<span>🔴 Network Error: ${err.message}</span>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="zap" class="w-3 h-3 text-cyan-400"></i> Test Ping';
            lucide.createIcons();
        }
    }
}

async function validateFormKey() {
    const prov = document.getElementById('key-provider-select').value;
    const key = document.getElementById('key-secret-input').value.trim();
    const modelSel = document.getElementById('key-model-select').value;
    const customModel = document.getElementById('key-model-custom').value.trim();
    const model = (modelSel === '__custom__') ? customModel : modelSel;
    const baseUrl = document.getElementById('key-baseurl-input').value.trim();
    const badge = document.getElementById('key-form-validate-badge');
    const btn = document.getElementById('btn-validate-form-key');

    if (!key) {
        showToast('Masukkan Secret API Key terlebih dahulu untuk diuji.', 'error');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menguji Validitas...';
    lucide.createIcons();
    badge.classList.remove('hidden');
    badge.className = 'p-3 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-300 font-mono text-xs flex items-center gap-2';
    badge.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin text-cyan-400"></i> Menghubungi endpoint provider dan menguji API key...';
    lucide.createIcons();

    try {
        const res = await fetch('/api/keys/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: prov, api_key: key, model: model, base_url: baseUrl })
        });
        const data = await res.json();
        if (data.status === 'success') {
            badge.className = 'p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 font-mono text-xs flex items-center justify-between';
            badge.innerHTML = `<span>✅ <b>VALID!</b> ${data.message}</span><span>${data.duration_ms}ms</span>`;
            showToast('API Key dan Model valid & siap digunakan!', 'success');
        } else {
            badge.className = 'p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono text-xs space-y-1';
            badge.innerHTML = `<div>❌ <b>TIDAK VALID / KONEKSI GAGAL</b></div><div class="text-[11px] text-slate-300 font-sans">${data.message || 'Cek kembali API key atau model'}</div>`;
            showToast('Validasi gagal: Kunci atau model tidak valid.', 'error');
        }
    } catch (err) {
        badge.className = 'p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono text-xs';
        badge.innerHTML = `❌ Network Error: ${err.message}`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="zap" class="w-3.5 h-3.5"></i> Test Validitas Key';
        lucide.createIcons();
    }
}

async function addApiKeyForm(e) {
    e.preventDefault();
    const modelSel = document.getElementById('key-model-select').value;
    const customModel = document.getElementById('key-model-custom').value.trim();
    const model = (modelSel === '__custom__') ? customModel : modelSel;

    const payload = {
        provider: document.getElementById('key-provider-select').value,
        name: document.getElementById('key-name-input').value.trim(),
        default_model: model,
        api_key: document.getElementById('key-secret-input').value.trim(),
        base_url: document.getElementById('key-baseurl-input').value.trim(),
        set_active: document.getElementById('key-set-active-check').checked
    };

    try {
        const res = await fetch('/api/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`API Key '${payload.name}' tersimpan ke Vault!`, 'success');
            document.getElementById('key-secret-input').value = '';
            document.getElementById('key-name-input').value = '';
            document.getElementById('key-form-validate-badge').classList.add('hidden');
            fetchKeys();
        } else {
            showToast(`Gagal menyimpan key: ${data.message || 'Error'}`, 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function activateKey(id) {
    try {
        const res = await fetch(`/api/keys/${id}/activate`, { method: 'POST' });
        showToast('API Key diaktifkan sebagai default provider!', 'success');
        fetchKeys();
    } catch (err) {
        showToast(`Gagal aktivasi: ${err.message}`, 'error');
    }
}

async function deleteKey(id, name) {
    if (!confirm(`Hapus API Key '${name}' dari Vault?`)) return;
    try {
        const res = await fetch(`/api/keys/${id}`, { method: 'DELETE' });
        showToast(`API Key '${name}' dihapus`, 'info');
        fetchKeys();
    } catch (err) {
        showToast(`Gagal hapus: ${err.message}`, 'error');
    }
}

function toggleKeyVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

function onProviderSelectChange() {
    const prov = document.getElementById('key-provider-select').value;
    const modelSelect = document.getElementById('key-model-select');
    const customInput = document.getElementById('key-model-custom');
    const baseInput = document.getElementById('key-baseurl-input');

    populateModelSelect(modelSelect, customInput, prov);

    if (prov === 'gemini') {
        baseInput.value = '';
    } else if (prov === 'nvidia') {
        baseInput.value = 'https://integrate.api.nvidia.com/v1';
    } else if (prov === 'deepseek') {
        baseInput.value = 'https://api.deepseek.com/v1';
    } else if (prov === 'minimax') {
        baseInput.value = 'https://api.minimax.chat/v1';
    } else if (prov === 'moonshot') {
        baseInput.value = 'https://api.moonshot.cn/v1';
    } else if (prov === 'qwen') {
        baseInput.value = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1';
    } else if (prov === 'openai') {
        baseInput.value = 'https://api.openai.com/v1';
    } else if (prov === 'groq') {
        baseInput.value = 'https://api.groq.com/openai/v1';
    } else if (prov === 'openrouter') {
        baseInput.value = 'https://openrouter.ai/api/v1';
    } else if (prov === '9router') {
        baseInput.value = 'http://127.0.0.1:20128/v1';
    } else if (prov === 'anthropic') {
        baseInput.value = '';
    } else if (prov === 'antigravity') {
        baseInput.value = 'http://127.0.0.1:8890/v1';
        baseInput.placeholder = 'http://127.0.0.1:8890/v1 (multi-account router)';
        alert("Pastikan minimal 1 akun sudah login:\n  bash ~/antigravity-gateway/tambah_akun_agy.sh <nama>");
    } else if (prov === 'custom') {
        // Provider apa pun yang OpenAI-compatible: isi Base URL-nya sendiri
        baseInput.value = '';
        baseInput.placeholder = 'https://api.oxalpha.com/v1 (Base URL provider Anda)';
        baseInput.focus();
    } else if (prov === 'ollama') {
        baseInput.value = 'http://localhost:11434/v1';
    }
}

function onKeyModelSelectChange() {
    const sel = document.getElementById('key-model-select');
    const custom = document.getElementById('key-model-custom');
    if (sel.value === '__custom__') {
        custom.classList.remove('hidden');
        custom.focus();
    } else {
        custom.classList.add('hidden');
    }
}

// ==================== AFFILIATE SALES SWARM FUNCTIONS ====================
let currentAffiliateCampaign = null;
let latestScrapedProducts = [];

// Live Scraper Integration
async function runLiveProductScrape(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-run-scraper');
    const target = document.getElementById('scraper-input-target').value.trim();
    const platform = document.getElementById('scraper-platform').value;
    const engine = document.getElementById('scraper-engine').value;

    if (!target) return;

    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Sedang Scrape...';
    lucide.createIcons();

    const isUrl = target.startsWith('http://') || target.startsWith('https://');

    try {
        let res;
        if (isUrl) {
            res = await fetch('/api/tools/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tool_name: 'scrape_real_product_data',
                    args: { url: target, engine }
                })
            });
        } else {
            res = await fetch('/api/tools/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tool_name: 'marketplace_search_products',
                    args: { query: target, platform, max_items: 12 }
                })
            });
        }

        const data = await res.json();
        const container = document.getElementById('scraped-results-container');
        const grid = document.getElementById('scraped-cards-grid');
        const countBadge = document.getElementById('scraped-count-badge');

        if (data.status === 'success' && data.result) {
            container.classList.remove('hidden');
            if (isUrl) {
                const d = data.result.data || {};
                latestScrapedProducts = [{
                    title: d.title || data.result.page_title || 'Produk Scraped',
                    price: d.price || 'Rp 49.000',
                    snippet: d.description || 'Data berhasil discrape via ' + data.result.method,
                    url: data.result.url || target,
                    platform: d.platform || platform,
                    rating: 4.9
                }];
            } else {
                latestScrapedProducts = data.result.products || [];
            }

            countBadge.innerText = `Hasil Scraping: ${latestScrapedProducts.length} produk ditemukan (${data.duration_ms || 0}ms)`;

            if (latestScrapedProducts.length === 0) {
                grid.innerHTML = '<div class="col-span-full p-4 text-center text-slate-500 italic">Tidak ada produk ditemukan untuk kata kunci ini.</div>';
            } else {
                grid.innerHTML = latestScrapedProducts.map((p, idx) => `
                    <div class="p-3 bg-dark-950 rounded-xl border border-cyan-500/20 flex flex-col justify-between space-y-2 hover:border-cyan-500/50 transition-all">
                        <div class="space-y-1">
                            <div class="flex items-center justify-between text-[10px] font-mono">
                                <span class="text-cyan-400 uppercase font-bold">${p.platform}</span>
                                <span class="text-amber-400 font-bold">⭐ ${p.rating || 4.9}</span>
                            </div>
                            <h4 class="text-xs font-semibold text-white line-clamp-2">${p.title}</h4>
                            <div class="text-xs font-mono font-bold text-emerald-400">${p.price}</div>
                        </div>
                        <button onclick="selectScrapedProduct(${idx})" class="w-full py-1.5 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 rounded-lg text-[10px] font-mono font-bold flex items-center justify-center gap-1">
                            <i data-lucide="arrow-down-right" class="w-3 h-3"></i> Gunakan Produk Ini
                        </button>
                    </div>
                `).join('');
            }

            showToast(`Berhasil scrape ${latestScrapedProducts.length} produk!`, 'success');
        } else {
            showToast(`Scrape gagal: ${data.message || 'Error'}`, 'error');
        }
    } catch (err) {
        showToast(`Scraper error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="search" class="w-4 h-4"></i> Scrape Real Data';
        lucide.createIcons();
    }
}

function selectScrapedProduct(idx) {
    const p = latestScrapedProducts[idx];
    if (!p) return;

    document.getElementById('aff-product-name').value = p.title;
    document.getElementById('aff-features').value = p.snippet ? p.snippet.replace(/\n/g, ' ') : 'Kualitas terjamin, rating tinggi bintang 5, diskon resmi';
    document.getElementById('aff-disc-price').value = p.price || 'Rp 49.000';
    document.getElementById('aff-orig-price').value = 'Rp 120.000';
    document.getElementById('aff-link').value = p.url || 'https://shopee.co.id';

    showToast(`Produk '${p.title.substring(0, 25)}...' dimuat ke generator!`, 'info');
}

function setAffiliatePreset(type) {
    if (type === 'powerbank') {
        document.getElementById('aff-product-name').value = 'Mini Powerbank Kapsul Fast Charging 5000mAh';
        document.getElementById('aff-features').value = 'Ukuran saku 100g, fast charge 20W, kabel built-in Type-C & Lightning, garansi 1 tahun';
        document.getElementById('aff-orig-price').value = 'Rp 149.000';
        document.getElementById('aff-disc-price').value = 'Rp 49.900';
        document.getElementById('aff-link').value = 'https://shope.ee/powerbank-kapsul-deals';
        document.getElementById('aff-audience').value = 'Anak Muda, Pekerja Mobile & Pemburu Gadget Unik';
    } else if (type === 'lampu') {
        document.getElementById('aff-product-name').value = 'Lampu Tidur Akrilik Memo Board LED Estetik';
        document.getElementById('aff-features').value = 'Bisa ditulis note glow in the dark, warm light estetik kamar, free spidol & penghapus, USB powered';
        document.getElementById('aff-orig-price').value = 'Rp 89.000';
        document.getElementById('aff-disc-price').value = 'Rp 29.500';
        document.getElementById('aff-link').value = 'https://shope.ee/lampu-akrilik-estetik';
        document.getElementById('aff-audience').value = 'Mahasiswa, Cewek Estetik, Dekor Kamar Tidur';
    } else if (type === 'mic') {
        document.getElementById('aff-product-name').value = 'Mic Wireless Clip-On Type-C & iPhone Noise Cancelling';
        document.getElementById('aff-features').value = 'Plug & play tanpa bluetooth, jangkauan 20 meter, suara jernih no delay, batere 10 jam nonstop';
        document.getElementById('aff-orig-price').value = 'Rp 120.000';
        document.getElementById('aff-disc-price').value = 'Rp 38.000';
        document.getElementById('aff-link').value = 'https://shope.ee/mic-wireless-deals';
        document.getElementById('aff-audience').value = 'Content Creator Pemula, Guru/Dosen, Penjual Live Streaming';
    }
    showToast(`Preset produk '${type}' berhasil dimuat!`, 'info');
}

function switchAffTab(subTab) {
    document.querySelectorAll('.aff-subview').forEach(el => el.classList.add('hidden'));
    ['tiktok', 'video', 'telegram', 'whatsapp', 'spill'].forEach(t => {
        const btn = document.getElementById(`aff-tab-btn-${t}`);
        if (btn) {
            btn.classList.remove('bg-emerald-500/20', 'text-emerald-300', 'border', 'border-emerald-500/30', 'font-bold');
            btn.classList.add('text-slate-400');
        }
    });

    const targetView = document.getElementById(`aff-view-${subTab}`);
    const targetBtn = document.getElementById(`aff-tab-btn-${subTab}`);
    if (targetView) targetView.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.remove('text-slate-400');
        targetBtn.classList.add('bg-emerald-500/20', 'text-emerald-300', 'border', 'border-emerald-500/30', 'font-bold');
    }
    lucide.createIcons();
}

function toggleVideoEngineConfig() {
    const engine = document.getElementById('video-engine-select').value;
    const keyInput = document.getElementById('video-api-key-input');
    if (engine === 'local_pro') {
        keyInput.classList.add('hidden');
    } else if (engine.startsWith('google_veo')) {
        keyInput.classList.remove('hidden');
        keyInput.placeholder = 'Kosongkan = otomatis pakai Gemini API Key dari Vault';
    } else {
        keyInput.classList.remove('hidden');
        keyInput.placeholder = `Masukkan API Key ${engine.toUpperCase()}...`;
    }
}

async function renderAffiliateVideoNow() {
    const btn = document.getElementById('btn-render-video');
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Rendering Video H.264 (Animasi + Dubbing AI)...';
    lucide.createIcons();

    const imgVal = document.getElementById('video-input-images').value.trim();
    const images = imgVal ? imgVal.split(',').map(s => s.trim()) : [];
    const productName = document.getElementById('aff-product-name').value.trim() || 'Produk Pilihan';
    const origPrice = document.getElementById('aff-orig-price').value.trim() || 'Rp 149.000';
    const discPrice = document.getElementById('aff-disc-price').value.trim() || 'Rp 49.900';
    const voice = document.getElementById('video-voice-select').value;
    const theme = document.getElementById('video-theme-select').value;
    const motion = document.getElementById('video-motion-select').value;
    const badgeText = document.getElementById('video-badge-text').value.trim() || 'FLASH SALE DISKON SPESIAL';
    const ctaText = document.getElementById('video-cta-text') ? document.getElementById('video-cta-text').value.trim() : 'KLIK KERANJANG KUNING / BIO SEBELUM HABIS';
    const visualPrompt = document.getElementById('video-visual-prompt').value.trim();
    const engine = document.getElementById('video-engine-select') ? document.getElementById('video-engine-select').value : 'local_pro';
    const apiKey = document.getElementById('video-api-key-input') ? document.getElementById('video-api-key-input').value.trim() : '';
    let voiceText = document.getElementById('video-voiceover-text').value.trim();

    if (!voiceText) {
        voiceText = `Jangan beli dulu sebelum nonton ini! Promo spesial ${productName}, harga normal ${origPrice} sekarang lagi drop cuma ${discPrice}! Klik keranjang kuning sekarang sebelum kuponnya habis ya!`;
        document.getElementById('video-voiceover-text').value = voiceText;
    }

    try {
        const res = await fetch('/api/video/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image_paths: images,
                product_name: productName,
                voiceover_text: voiceText,
                orig_price: origPrice,
                disc_price: discPrice,
                voice: voice,
                theme: theme,
                motion_style: motion,
                badge_text: badgeText,
                call_to_action: ctaText,
                visual_prompt: visualPrompt,
                engine: engine,
                api_key: apiKey
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            const playerBox = document.getElementById('video-player-container');
            const player = document.getElementById('video-preview-player');
            const dlBtn = document.getElementById('video-download-btn');

            player.src = data.download_url;
            player.load();
            dlBtn.href = data.download_url;
            dlBtn.download = data.video_filename;
            playerBox.classList.remove('hidden');
            player.play().catch(() => {});

            showToast(`Video promosi '${data.video_filename}' sukses dirender (${data.file_size_mb} MB)!`, 'success');
        } else {
            showToast(`Render video gagal: ${data.message || 'Error'}`, 'error');
        }
    } catch (err) {
        showToast(`Video render error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="clapperboard" class="w-4 h-4"></i> 🎬 Render Video Promosi MP4 Sekarang';
        lucide.createIcons();
    }
}

async function runAffiliateGenerator(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-run-affiliate');
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Swarm AI Sedang Bekerja...';
    lucide.createIcons();

    const payload = {
        product_name: document.getElementById('aff-product-name').value.trim(),
        key_features: document.getElementById('aff-features').value.trim(),
        original_price: document.getElementById('aff-orig-price').value.trim(),
        discount_price: document.getElementById('aff-disc-price').value.trim(),
        affiliate_link: document.getElementById('aff-link').value.trim(),
        target_audience: document.getElementById('aff-audience').value.trim()
    };

    try {
        const res = await fetch('/api/affiliate/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            currentAffiliateCampaign = data.result;
            renderAffiliateResults(data.result);
            showToast('Paket Penjualan Affiliate Berhasil Digenerate!', 'success');
            fetchAffiliateCampaigns();
        } else {
            showToast(`Gagal: ${data.detail || data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i> 🚀 Eksekusi Tim Penjualan Swarm';
        lucide.createIcons();
    }
}

function renderAffiliateResults(c) {
    document.getElementById('aff-text-tiktok').innerText = c.tiktok_script || 'N/A';
    document.getElementById('aff-text-telegram').innerText = c.telegram_card || 'N/A';
    document.getElementById('aff-text-whatsapp').innerText = c.wa_broadcast || 'N/A';

    // Video Prompts & Storyboard
    const masterPromptEl = document.getElementById('aff-text-videoprompt');
    if (masterPromptEl) masterPromptEl.innerText = c.ai_video_master_prompt || 'N/A';

    const negPromptEl = document.getElementById('aff-text-negativeprompt');
    if (negPromptEl && c.negative_prompt) negPromptEl.innerText = c.negative_prompt;

    const storyTextEl = document.getElementById('aff-text-storyboard');
    if (storyTextEl) storyTextEl.innerText = c.visual_storyboard_text || '';

    // Scenes grid
    const scenesGrid = document.getElementById('aff-scenes-grid');
    if (scenesGrid && c.scene_breakdown && c.scene_breakdown.length > 0) {
        scenesGrid.innerHTML = c.scene_breakdown.map((sc) => `
            <div class="p-3 bg-dark-950 rounded-xl border border-white/10 space-y-1.5 group hover:border-cyan-500/40 transition-colors">
                <div class="flex items-center justify-between">
                    <span class="text-[10px] font-mono font-bold text-cyan-400">Scene #${sc.scene} (${sc.timestamp})</span>
                    <span class="text-[10px] font-mono px-2 py-0.5 bg-cyan-500/10 text-cyan-300 rounded border border-cyan-500/20">${sc.shot_type}</span>
                </div>
                <div class="text-xs text-slate-200 font-sans leading-relaxed">${sc.visual_prompt}</div>
                <div class="pt-1 border-t border-white/5 text-[10px] font-mono text-slate-400 space-y-0.5">
                    <div><span class="text-slate-500">Camera:</span> ${sc.camera_angle}</div>
                    <div><span class="text-slate-500">Lighting:</span> ${sc.lighting}</div>
                </div>
            </div>
        `).join('');
    }

    // Sync visual prompt to video maker form
    const vVisualPrompt = document.getElementById('video-visual-prompt');
    if (vVisualPrompt && c.ai_video_master_prompt) {
        vVisualPrompt.value = c.ai_video_master_prompt;
    }

    const vText = document.getElementById('video-voiceover-text');
    if (vText) {
        vText.value = `Jangan beli dulu sebelum nonton ini! Promo spesial ${c.product_name}, harga normal ${c.original_price} sekarang lagi drop cuma ${c.discount_price}! Fitur unggulan: ${c.key_features}. Langsung klik link sekarang ya!`;
    }

    const spillBox = document.getElementById('aff-spill-list');
    if (c.spill_replies && c.spill_replies.length > 0) {
        spillBox.innerHTML = c.spill_replies.map((reply, idx) => `
            <div class="p-3 bg-dark-950 rounded-xl border border-white/5 font-sans text-xs text-slate-200 flex items-start justify-between gap-3 group">
                <div>
                    <span class="text-[10px] font-mono text-cyan-400 font-bold block mb-0.5">Varian #${idx + 1}:</span>
                    ${reply}
                </div>
                <button onclick="navigator.clipboard.writeText('${reply.replace(/'/g, "\\'")}'); showToast('Varian auto-reply disalin!', 'success');" class="p-1.5 bg-white/5 hover:bg-white/10 text-cyan-300 rounded-lg shrink-0" title="Salin">
                    <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                </button>
            </div>
        `).join('');
    }
    lucide.createIcons();
}

function copyAffiliateContent(elemId) {
    const el = document.getElementById(elemId);
    if (el) {
        navigator.clipboard.writeText(el.innerText);
        showToast('Konten berhasil disalin ke clipboard!', 'success');
    }
}

async function broadcastCurrentAffiliate(channel) {
    if (!currentAffiliateCampaign) {
        showToast('Generate campaign terlebih dahulu sebelum broadcast!', 'warning');
        return;
    }
    showToast(`Mengirim promo ke ${channel}...`, 'info');
    try {
        const res = await fetch('/api/affiliate/broadcast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                product_name: currentAffiliateCampaign.product_name,
                message_text: currentAffiliateCampaign.telegram_card,
                affiliate_link: currentAffiliateCampaign.affiliate_link,
                channels: [channel]
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Promo ${currentAffiliateCampaign.product_name} berhasil dikirim ke ${channel}!`, 'success');
        } else {
            showToast(`Gagal broadcast: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Broadcast error: ${err.message}`, 'error');
    }
}

async function fetchAffiliateCampaigns() {
    try {
        const res = await fetch('/api/affiliate/campaigns?limit=15');
        const data = await res.json();
        const tbody = document.getElementById('affiliate-campaigns-tbody');
        if (!tbody) return;

        if (!data.campaigns || data.campaigns.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="p-4 text-center text-slate-500 italic">Belum ada campaign affiliate yang tersimpan. Klik tombol eksekusi di atas untuk membuat yang pertama.</td></tr>';
            return;
        }

        tbody.innerHTML = data.campaigns.map(c => `
            <tr class="hover:bg-white/[0.02] transition-colors">
                <td class="p-3 text-cyan-400 font-bold">#${c.id}</td>
                <td class="p-3 font-semibold text-white">${c.product_name}</td>
                <td class="p-3 text-slate-300 uppercase text-[10px]">${c.platform || 'shopee/tiktok'}</td>
                <td class="p-3 text-slate-400 truncate max-w-xs">${c.target_audience || 'All Audience'}</td>
                <td class="p-3">
                    <span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[9px] font-bold">
                        ${c.status || 'Active'}
                    </span>
                </td>
                <td class="p-3 text-slate-500 text-[11px]">${(c.created_at || '').substring(0, 16)}</td>
                <td class="p-3 text-right">
                    <button onclick="loadCampaignDetail(${c.id})" class="px-2.5 py-1 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/30 rounded-lg text-[10px] font-bold">
                        Buka
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Fetch affiliate campaigns error:', err);
    }
}

async function loadCampaignDetail(cid) {
    try {
        const res = await fetch(`/api/affiliate/campaigns/${cid}`);
        const data = await res.json();
        if (data.status === 'success' && data.campaign) {
            currentAffiliateCampaign = data.campaign;
            renderAffiliateResults(data.campaign);
            showToast(`Memuat campaign #${cid}: ${data.campaign.product_name}`, 'info');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    } catch (err) {
        showToast(`Gagal memuat detail campaign: ${err.message}`, 'error');
    }
}

// ==================== ALFA SECURE VAULT & CYBER SENTRY JS ====================
let currentVaultCategory = 'all';
let allVaultSecretsData = [];

function switchVaultSubTab(sub) {
    document.querySelectorAll('.vault-subview').forEach(el => el.classList.add('hidden'));
    ['secrets', 'scanner', 'settings'].forEach(s => {
        const btn = document.getElementById(`vault-subtab-btn-${s}`);
        if (btn) {
            btn.classList.remove('bg-amber-500/20', 'text-amber-300', 'border', 'border-amber-500/30', 'font-bold');
            btn.classList.add('text-slate-400');
        }
    });

    const targetView = document.getElementById(`vault-subview-${sub}`);
    const targetBtn = document.getElementById(`vault-subtab-btn-${sub}`);
    if (targetView) targetView.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.remove('text-slate-400');
        targetBtn.classList.add('bg-amber-500/20', 'text-amber-300', 'border', 'border-amber-500/30', 'font-bold');
    }
    lucide.createIcons();
}

async function fetchVaultSecrets(category = null) {
    if (category) currentVaultCategory = category;
    try {
        const res = await fetch(`/api/vault/list?category=${currentVaultCategory}`);
        const data = await res.json();
        if (data.status === 'success') {
            allVaultSecretsData = data.items || [];
            renderVaultSecretsList();
            const badge = document.getElementById('vault-total-count-badge');
            if (badge) badge.innerText = `${allVaultSecretsData.length} Items`;
        }
    } catch (err) {
        console.error('Fetch vault secrets error:', err);
    }
}

function filterVaultSecrets(cat) {
    currentVaultCategory = cat;
    ['all', 'api_key', 'affiliate', 'password', 'note'].forEach(c => {
        const btn = document.getElementById(`vfilter-btn-${c}`);
        if (btn) {
            btn.className = (c === cat)
                ? 'px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold'
                : 'px-2.5 py-1 rounded-lg bg-white/5 text-slate-400 hover:text-white';
        }
    });
    fetchVaultSecrets(cat);
}

function renderVaultSecretsList() {
    const grid = document.getElementById('vault-secrets-grid');
    if (!grid) return;

    if (allVaultSecretsData.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full p-8 text-center bg-dark-950/60 rounded-xl border border-white/5 space-y-2">
                <i data-lucide="shield-check" class="w-8 h-8 text-amber-400/50 mx-auto"></i>
                <p class="text-xs text-slate-400 font-mono">Belum ada secret tersimpan di kategori ini.</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    grid.innerHTML = allVaultSecretsData.map(sec => {
        let catBadge = '';
        let catIcon = 'key';
        if (sec.category === 'api_key') {
            catBadge = '<span class="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[10px] font-mono border border-cyan-500/20">API Key</span>';
            catIcon = 'key';
        } else if (sec.category === 'affiliate') {
            catBadge = '<span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono border border-emerald-500/20">Affiliate</span>';
            catIcon = 'shopping-bag';
        } else if (sec.category === 'password') {
            catBadge = '<span class="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 text-[10px] font-mono border border-rose-500/20">Password</span>';
            catIcon = 'lock';
        } else {
            catBadge = '<span class="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 text-[10px] font-mono border border-purple-500/20">Note</span>';
            catIcon = 'file-text';
        }

        return `
            <div class="p-4 rounded-xl bg-dark-950/80 border border-white/10 hover:border-amber-500/30 transition-all space-y-3">
                <div class="flex items-start justify-between gap-2">
                    <div class="space-y-0.5">
                        <div class="font-bold text-xs text-white font-mono flex items-center gap-1.5 truncate">
                            <i data-lucide="${catIcon}" class="w-3.5 h-3.5 text-amber-400 flex-shrink-0"></i>
                            <span class="truncate">${sec.name}</span>
                        </div>
                        <div class="text-[10px] text-slate-400 truncate">${sec.notes || 'Enkripsi AES-256-GCM'}</div>
                    </div>
                    ${catBadge}
                </div>

                <!-- Masked Value & Actions -->
                <div class="p-2.5 rounded-lg bg-dark-900 border border-white/5 flex items-center justify-between gap-2 font-mono text-xs">
                    <span id="vault-val-${sec.id}" class="text-amber-300 font-mono tracking-widest truncate">••••••••••••••••</span>
                    <div class="flex items-center gap-1 flex-shrink-0">
                        <button onclick="revealVaultSecret(${sec.id})" title="Dekripsi & Lihat Nilai" class="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-amber-300">
                            <i data-lucide="eye" class="w-3.5 h-3.5"></i>
                        </button>
                        <button onclick="copyVaultSecret(${sec.id})" title="Salin ke Clipboard" class="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-cyan-300">
                            <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                </div>

                <div class="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1 border-t border-white/5">
                    <span>Tersimpan: ${new Date(sec.updated_at).toLocaleDateString('id-ID')}</span>
                    <button onclick="deleteVaultSecret(${sec.id}, '${sec.name}')" class="text-rose-400 hover:text-rose-300 flex items-center gap-1">
                        <i data-lucide="trash-2" class="w-3 h-3"></i> Hapus
                    </button>
                </div>
            </div>
        `;
    }).join('');
    lucide.createIcons();
}

async function storeVaultSecretForm(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-store-vault');
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Mengenkripsi (AES-256-GCM)...';
    lucide.createIcons();

    const name = document.getElementById('vault-input-name').value.trim();
    const category = document.getElementById('vault-input-category').value;
    const notes = document.getElementById('vault-input-notes').value.trim();
    const value = document.getElementById('vault-input-value').value.trim();

    try {
        const res = await fetch('/api/vault/store', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, category, notes, value })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            document.getElementById('vault-input-name').value = '';
            document.getElementById('vault-input-notes').value = '';
            document.getElementById('vault-input-value').value = '';
            fetchVaultSecrets();
        } else {
            showToast(`Gagal: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Vault error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="lock" class="w-4 h-4"></i> 🔒 Enkripsi & Kunci ke Vault Sekarang';
        lucide.createIcons();
    }
}

async function revealVaultSecret(id) {
    const valSpan = document.getElementById(`vault-val-${id}`);
    if (valSpan && valSpan.dataset.revealed === 'true') {
        valSpan.innerText = '••••••••••••••••';
        valSpan.dataset.revealed = 'false';
        return;
    }

    try {
        const res = await fetch('/api/vault/reveal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        const data = await res.json();
        if (data.status === 'success') {
            if (valSpan) {
                valSpan.innerText = data.value;
                valSpan.dataset.revealed = 'true';
                valSpan.dataset.raw = data.value;
            }
        } else {
            showToast(data.message || 'Gagal mendekripsi', 'error');
        }
    } catch (err) {
        showToast(`Reveal error: ${err.message}`, 'error');
    }
}

async function copyVaultSecret(id) {
    const valSpan = document.getElementById(`vault-val-${id}`);
    if (valSpan && valSpan.dataset.raw) {
        navigator.clipboard.writeText(valSpan.dataset.raw);
        showToast('Nilai secret disalin ke clipboard!', 'success');
        return;
    }
    try {
        const res = await fetch('/api/vault/reveal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        const data = await res.json();
        if (data.status === 'success') {
            navigator.clipboard.writeText(data.value);
            showToast(`Secret '${data.name}' berhasil disalin ke clipboard!`, 'success');
        }
    } catch (err) {
        showToast(`Copy error: ${err.message}`, 'error');
    }
}

async function deleteVaultSecret(id, name) {
    if (!confirm(`Hapus permanen secret '${name}' dari αlfa Secure Vault?`)) return;
    try {
        const res = await fetch(`/api/vault/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'info');
            fetchVaultSecrets();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        showToast(`Delete error: ${err.message}`, 'error');
    }
}

// ==================== CYBER SENTRY SECURITY AUDITOR JS ====================
async function runCyberSentryAudit(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-run-sentry');
    const targetUrl = document.getElementById('sentry-target-url').value.trim();
    if (!targetUrl) return;

    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Memindai SSL & Security Headers...';
    lucide.createIcons();

    try {
        const res = await fetch('/api/security/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: targetUrl })
        });
        const data = await res.json();
        if (data.status === 'success') {
            renderCyberSentryResults(data);
            showToast(`Audit keamanan untuk '${data.hostname}' selesai! Grade: ${data.grade}`, 'success');
        } else {
            showToast(`Audit gagal: ${data.error || data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Scan error: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="search-check" class="w-4 h-4"></i> 🛡️ Jalankan Security Audit';
        lucide.createIcons();
    }
}

function renderCyberSentryResults(data) {
    const container = document.getElementById('sentry-results-container');
    if (!container) return;
    container.classList.remove('hidden');

    // Grade Card
    const gradeCard = document.getElementById('sentry-grade-card');
    const gradeVal = document.getElementById('sentry-grade-val');
    const scoreVal = document.getElementById('sentry-score-val');

    gradeVal.innerText = data.grade;
    gradeVal.style.color = data.grade_color;
    scoreVal.innerText = `Score: ${data.score} / 100 (${data.latency_ms} ms)`;
    gradeCard.style.borderColor = `${data.grade_color}40`;

    // SSL Info
    document.getElementById('sentry-ssl-proto').innerText = data.ssl_info.tls_version || 'N/A';
    document.getElementById('sentry-ssl-status').innerText = data.is_https ? 'HTTPS Terenkripsi' : 'HTTP Polos (Tidak Aman)';
    document.getElementById('sentry-ssl-issuer').innerText = data.ssl_info.issuer || '-';
    document.getElementById('sentry-ssl-exp').innerText = data.ssl_info.expires_on || '-';

    // Checks Matrix
    const checksGrid = document.getElementById('sentry-checks-grid');
    const checkKeys = Object.keys(data.checks || {});
    checksGrid.innerHTML = checkKeys.map(k => {
        const c = data.checks[k];
        let badge = '';
        if (c.status === 'PASS') {
            badge = '<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px] font-bold">PASS</span>';
        } else if (c.status === 'WARN') {
            badge = '<span class="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px] font-bold">WARN</span>';
        } else {
            badge = '<span class="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[10px] font-bold">FAIL</span>';
        }

        return `
            <div class="p-3 rounded-xl bg-dark-950 border border-white/5 space-y-1.5">
                <div class="flex items-center justify-between">
                    <span class="font-bold text-xs text-white font-mono uppercase">${k.replace(/_/g, ' ')}</span>
                    ${badge}
                </div>
                <p class="text-[11px] text-slate-400 font-sans">${c.desc}</p>
                ${c.value ? `<div class="text-[10px] font-mono text-slate-500 truncate bg-dark-900 p-1 rounded">${c.value}</div>` : ''}
            </div>
        `;
    }).join('');

    // Findings List
    const findingsList = document.getElementById('sentry-findings-list');
    if (!data.findings || data.findings.length === 0) {
        findingsList.innerHTML = `
            <div class="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs font-mono flex items-center gap-2">
                <i data-lucide="check-circle" class="w-4 h-4"></i> Website ini memiliki konfigurasi keamanan header yang sangat baik!
            </div>
        `;
    } else {
        findingsList.innerHTML = data.findings.map(f => {
            let sevBadge = (f.severity === 'HIGH')
                ? '<span class="px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 text-[10px] font-bold font-mono">HIGH RISK</span>'
                : '<span class="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-[10px] font-bold font-mono">MEDIUM</span>';

            return `
                <div class="p-3.5 rounded-xl bg-dark-950 border border-white/5 space-y-1.5 text-xs">
                    <div class="flex items-center justify-between">
                        <span class="font-bold text-white font-mono">${f.header}</span>
                        ${sevBadge}
                    </div>
                    <p class="text-slate-300">${f.issue}</p>
                    <div class="text-[11px] font-mono text-cyan-300 bg-cyan-500/10 p-2 rounded-lg border border-cyan-500/20">
                        💡 Solusi: ${f.recommendation}
                    </div>
                </div>
            `;
        }).join('');
    }
    lucide.createIcons();
}

// ==================== PASSKEY & SECURITY SETTINGS JS ====================
async function fetchPasskeyStatus() {
    try {
        const res = await fetch('/api/vault/passkey/status');
        const data = await res.json();
        const toggle = document.getElementById('passkey-lock-toggle');
        const txt = document.getElementById('passkey-lock-status-text');
        if (toggle) toggle.checked = data.enabled;
        if (txt) txt.innerText = data.enabled ? 'Status: AKTIF (Terkunci Biometrik/PIN)' : 'Status: Tidak Aktif (Akses Bebas Lokal)';
    } catch (err) {
        console.error('Fetch passkey status error:', err);
    }
}

async function togglePasskeySwitch() {
    const toggle = document.getElementById('passkey-lock-toggle');
    const enabled = toggle.checked;
    try {
        const res = await fetch('/api/vault/passkey/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        const data = await res.json();
        showToast(data.message, 'info');
        fetchPasskeyStatus();
    } catch (err) {
        showToast(`Toggle passkey error: ${err.message}`, 'error');
    }
}

// ==================== MASTER SCRAPER PRO JS ====================
let currentScraperCategory = 'all_marketplace';
let currentScraperData = [];

function switchScraperSubTab(sub) {
    document.querySelectorAll('.scraper-subview').forEach(el => el.classList.add('hidden'));
    ['keyword', 'modern', 'urls', 'history'].forEach(s => {
        const btn = document.getElementById(`scraper-subtab-btn-${s}`);
        if (btn) {
            btn.classList.remove('bg-orange-500/20', 'text-orange-300', 'border', 'border-orange-500/30', 'font-bold', 'bg-cyan-500/20', 'text-cyan-300', 'border-cyan-500/30');
            btn.classList.add('text-slate-400');
        }
    });

    const targetView = document.getElementById(`scraper-subview-${sub}`);
    const targetBtn = document.getElementById(`scraper-subtab-btn-${sub}`);
    if (targetView) targetView.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.remove('text-slate-400');
        if (sub === 'modern') {
            targetBtn.classList.add('bg-cyan-500/20', 'text-cyan-300', 'border', 'border-cyan-500/30', 'font-bold');
        } else {
            targetBtn.classList.add('bg-orange-500/20', 'text-orange-300', 'border', 'border-orange-500/30', 'font-bold');
        }
    }
    if (sub === 'history') fetchScraperBatches();
    lucide.createIcons();
}

let modernScraperLastResult = '';

function setModernPreset(presetKey, selectorValue, labelText) {
    const presets = ['all', 'titles', 'prices', 'articles', 'links', 'images', 'tables', 'custom'];
    presets.forEach(p => {
        const btn = document.getElementById(`preset-btn-${p}`);
        if (btn) {
            if (p === presetKey) {
                btn.className = 'modern-preset-btn p-2.5 rounded-xl bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-xs font-mono font-bold text-center transition-all';
            } else {
                btn.className = 'modern-preset-btn p-2.5 rounded-xl bg-white/5 text-slate-400 hover:text-white border border-transparent text-xs font-mono text-center transition-all';
            }
        }
    });

    const inputSelector = document.getElementById('modern-scraper-selector');
    const badge = document.getElementById('preset-badge-active');
    if (badge) badge.innerText = `Target: ${labelText}`;

    if (presetKey === 'custom') {
        if (inputSelector) {
            inputSelector.focus();
            if (!inputSelector.value) inputSelector.placeholder = 'Ketik CSS selector kustom (contoh: .product-title, span.price)...';
        }
    } else {
        if (inputSelector) inputSelector.value = selectorValue;
    }
}

function fillModernSampleUrl(url, selector) {
    const inputUrl = document.getElementById('modern-scraper-url');
    if (inputUrl) {
        inputUrl.value = url;
        inputUrl.classList.add('ring-2', 'ring-cyan-400');
        setTimeout(() => inputUrl.classList.remove('ring-2', 'ring-cyan-400'), 1000);
    }
    if (selector) {
        const inputSelector = document.getElementById('modern-scraper-selector');
        if (inputSelector) inputSelector.value = selector;
    }
    showToast(`Contoh URL & Preset dimuat!`, 'info');
}

async function runModernScraperLab(e) {
    e.preventDefault();
    const url = document.getElementById('modern-scraper-url').value.trim();
    const engine = document.getElementById('modern-scraper-engine').value;
    const selector = document.getElementById('modern-scraper-selector').value.trim();
    const maxPages = parseInt(document.getElementById('modern-scraper-maxpages').value) || 3;
    const autoIngest = document.getElementById('modern-scraper-autoingest').checked;

    const btn = document.getElementById('btn-run-modern-scraper');
    const statusText = document.getElementById('modern-scraper-status-text');
    const resultCard = document.getElementById('modern-scraper-result-card');
    const outputView = document.getElementById('modern-scraper-output-view');

    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block animate-spin mr-2">⚙️</span> Mengekstrak data...`;
    statusText.innerText = `Menjalankan engine ${engine}...`;

    try {
        const res = await fetch('/api/scraper/modern-lab', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                engine: engine,
                css_selector: selector,
                max_pages: maxPages,
                auto_ingest_vector: autoIngest
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            resultCard.classList.remove('hidden');
            document.getElementById('modern-res-engine-tag').innerText = `Engine: ${data.engine}`;
            document.getElementById('modern-res-meta').innerText = `Durasi: ${data.duration_ms} ms | Panjang: ${data.extracted_text ? data.extracted_text.length : 0} karakter ${data.vector_ingest ? '• ⚡ Tersimpan di Second Brain' : ''}`;
            modernScraperLastResult = data.markdown || data.extracted_text || JSON.stringify(data.raw_data, null, 2);
            outputView.innerText = modernScraperLastResult;
            showToast(`Scraping berhasil (${data.duration_ms} ms)!`, 'success');
            statusText.innerText = `Selesai dalam ${data.duration_ms} ms.`;
        } else {
            showToast(`Gagal: ${data.message}`, 'error');
            statusText.innerText = `Error: ${data.message}`;
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
        statusText.innerText = `Error: ${err.message}`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="play" class="w-4 h-4"></i> 🚀 Eksekusi Scraper Sekarang`;
        lucide.createIcons();
    }
}

function copyModernScraperOutput() {
    if (!modernScraperLastResult) return;
    navigator.clipboard.writeText(modernScraperLastResult);
    showToast('Hasil scraping berhasil disalin ke clipboard!', 'info');
}

function downloadModernScraperOutput() {
    if (!modernScraperLastResult) return;
    const blob = new Blob([modernScraperLastResult], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ALFA_Scrape_${Date.now()}.md`;
    a.click();
    showToast('File hasil scraping (.md) diunduh!', 'success');
}

function setScraperCategory(cat) {
    currentScraperCategory = cat;
    const categories = ['all_marketplace', 'jobs_career', 'leads_contacts', 'news_media', 'property_realestate', 'google_general'];
    categories.forEach(c => {
        const btn = document.getElementById(`cat-btn-${c}`);
        if (btn) {
            if (c === cat) {
                btn.className = 'scraper-cat-btn p-3 rounded-xl bg-orange-500/20 text-orange-300 border border-orange-500/30 font-bold text-xs text-center transition-all';
            } else {
                btn.className = 'scraper-cat-btn p-3 rounded-xl bg-white/5 text-slate-400 hover:text-white border border-transparent text-xs text-center transition-all';
            }
        }
    });
}

async function runUniversalScraper(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-run-universal-scraper');
    const query = document.getElementById('scraper-input-query').value.trim();
    const limit = parseInt(document.getElementById('scraper-input-limit').value, 10);
    if (!query) return;

    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Mengekstrak Data Skala Besar...';
    btn.disabled = true;
    lucide.createIcons();

    try {
        const res = await fetch('/api/scraper/universal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, category: currentScraperCategory, limit })
        });
        const data = await res.json();
        if (data.status === 'success') {
            renderScraperResults(data);
            showToast(`Berhasil mengekstrak ${data.total_scraped} data dalam ${data.duration_seconds} detik!`, 'success');
        } else {
            showToast(`Scraper error: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Koneksi scraper gagal: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i> 🚀 Mulai Scraping Massal Sekarang';
        btn.disabled = false;
        lucide.createIcons();
    }
}

function renderScraperResults(data) {
    const container = document.getElementById('scraper-results-container');
    if (!container) return;
    container.classList.remove('hidden');

    document.getElementById('scraper-res-title').innerText = `${data.query} (${data.category})`;
    document.getElementById('scraper-res-meta').innerText = `Total: ${data.total_scraped} data diekstrak dalam ${data.duration_seconds}s`;

    const btnCsv = document.getElementById('btn-download-csv');
    const btnJson = document.getElementById('btn-download-json');
    if (btnCsv) btnCsv.href = data.csv_download_url;
    if (btnJson) btnJson.href = data.json_download_url;

    currentScraperData = data.items || [];
    renderScraperTableRows(currentScraperData);

    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderScraperTableRows(items) {
    const tbody = document.getElementById('scraper-table-body');
    if (!tbody) return;

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="p-6 text-center text-slate-500 font-mono">Tidak ada data ditemukan.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map((it, idx) => `
        <tr class="hover:bg-white/5 transition-all">
            <td class="p-3 text-center text-slate-500 font-mono text-[11px]">${it.no || (idx + 1)}</td>
            <td class="p-3">
                <div class="font-bold text-white font-sans text-xs line-clamp-1">${it.title}</div>
                <div class="text-[10px] text-slate-400 font-sans line-clamp-1 mt-0.5">${it.snippet || '-'}</div>
            </td>
            <td class="p-3">
                <span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[11px] font-mono border border-emerald-500/20 font-bold whitespace-nowrap">
                    ${it.price || 'N/A'}
                </span>
            </td>
            <td class="p-3">
                <span class="px-2 py-0.5 rounded bg-dark-900 text-slate-300 text-[10px] font-mono border border-white/5">
                    ${it.domain || 'web'}
                </span>
            </td>
            <td class="p-3 font-mono text-[11px]">
                ${it.phone_wa !== 'N/A' ? `<span class="text-cyan-400 block truncate">📱 ${it.phone_wa}</span>` : ''}
                ${it.email !== 'N/A' ? `<span class="text-amber-300 block truncate">✉️ ${it.email}</span>` : ''}
                ${it.phone_wa === 'N/A' && it.email === 'N/A' ? '<span class="text-slate-600">-</span>' : ''}
            </td>
            <td class="p-3 text-right whitespace-nowrap space-x-1">
                <a href="${it.url}" target="_blank" class="px-2 py-1 rounded bg-white/5 hover:bg-orange-500/20 text-slate-300 hover:text-orange-300 text-[10px] font-mono inline-flex items-center gap-1 transition-all">
                    <i data-lucide="external-link" class="w-3 h-3"></i> Buka
                </a>
                <button onclick="sendItemToAffiliate('${it.title.replace(/'/g, "\\'")}', '${it.price}', '${it.url}')" title="Kirim ke Affiliate War Room" class="px-2 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 text-[10px] font-mono inline-flex items-center gap-1 transition-all">
                    <i data-lucide="shopping-bag" class="w-3 h-3"></i> Buat Naskah
                </button>
            </td>
        </tr>
    `).join('');
    lucide.createIcons();
}

function filterScraperTable() {
    const q = document.getElementById('scraper-table-search').value.toLowerCase();
    if (!q) {
        renderScraperTableRows(currentScraperData);
        return;
    }
    const filtered = currentScraperData.filter(it => 
        (it.title && it.title.toLowerCase().includes(q)) ||
        (it.snippet && it.snippet.toLowerCase().includes(q)) ||
        (it.domain && it.domain.toLowerCase().includes(q)) ||
        (it.phone_wa && it.phone_wa.toLowerCase().includes(q)) ||
        (it.email && it.email.toLowerCase().includes(q))
    );
    renderScraperTableRows(filtered);
}

function sendItemToAffiliate(title, price, url) {
    switchTab('affiliate');
    const nameInput = document.getElementById('affiliate-product-name');
    const priceInput = document.getElementById('affiliate-price-drop');
    const urlInput = document.getElementById('affiliate-product-url');
    if (nameInput) nameInput.value = title;
    if (priceInput) priceInput.value = price;
    if (urlInput) urlInput.value = url;
    showToast(`Data produk '${title.slice(0, 30)}...' dikirim ke Affiliate War Room!`, 'info');
}

async function runCustomUrlScraper(e) {
    if (e && e.preventDefault) e.preventDefault();
    const btn = document.getElementById('btn-run-batch-url-scraper');
    const rawUrls = document.getElementById('scraper-input-urls').value.trim();
    const engine = document.getElementById('scraper-engine-type').value;
    const concurrency = parseInt(document.getElementById('scraper-concurrency-val').value, 10);

    const urls = rawUrls.split('\n').map(u => u.trim()).filter(u => u.length > 5);
    if (urls.length === 0) {
        showToast('Mohon masukkan minimal 1 URL valid.', 'error');
        return;
    }

    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Mengekstrak URL...';
    btn.disabled = true;
    lucide.createIcons();

    try {
        const res = await fetch('/api/scraper/custom-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls, concurrency, use_camoufox: (engine === 'camoufox') })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Sukses mengekstrak ${data.total_successful} dari ${data.total_requested} URL!`, 'success');
            switchScraperSubTab('keyword');
            renderScraperResults({
                query: `Custom Batch (${data.total_requested} URLs)`,
                category: 'custom_urls',
                total_scraped: data.total_successful,
                duration_seconds: data.duration_seconds,
                items: data.items,
                csv_download_url: data.csv_download_url,
                json_download_url: data.json_download_url
            });
        } else {
            showToast(`Batch error: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Batch scraping gagal: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="zap" class="w-4 h-4"></i> Ekstrak Semua URL Sekarang';
        btn.disabled = false;
        lucide.createIcons();
    }
}

async function fetchScraperBatches() {
    try {
        const res = await fetch('/api/scraper/batches');
        const data = await res.json();
        const list = document.getElementById('scraper-history-list');
        if (!list) return;

        if (!data.batches || data.batches.length === 0) {
            list.innerHTML = '<div class="p-6 text-center text-xs text-slate-500 font-mono">Belum ada riwayat batch scraping tersimpan.</div>';
            return;
        }

        list.innerHTML = data.batches.map(b => `
            <div class="p-3.5 rounded-xl bg-dark-950/80 border border-white/5 hover:border-orange-500/30 flex items-center justify-between gap-3 transition-all font-mono text-xs">
                <div class="space-y-0.5 truncate">
                    <div class="font-bold text-white flex items-center gap-2 truncate">
                        <span class="px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-300 text-[10px]">${b.mode}</span>
                        <span class="truncate">${b.name}</span>
                    </div>
                    <div class="text-[10px] text-slate-400">Target: ${b.target} • ${b.total_items} items • ${new Date(b.created_at).toLocaleString('id-ID')}</div>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    <a href="${b.csv_download_url}" download class="px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 text-[10px] font-bold hover:bg-emerald-500/30">
                        📥 CSV
                    </a>
                    <a href="${b.json_download_url}" download class="px-2.5 py-1 rounded bg-cyan-500/20 text-cyan-300 text-[10px] font-bold hover:bg-cyan-500/30">
                        📥 JSON
                    </a>
                </div>
            </div>
        `).join('');
        lucide.createIcons();
    } catch (err) {
        console.error('Fetch scraper batches error:', err);
    }
}

// ==================== GOOGLE DRIVE & GOOGLE CLOUD SUITE LOGIC ====================
let selectedGdriveFile = null;

function handleGdriveFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        selectedGdriveFile = file;
        const preview = document.getElementById('gdrive-filename-preview');
        if (preview) {
            preview.innerHTML = `File terpilih: <span class="text-emerald-400 font-bold font-mono">${file.name}</span> (${Math.round(file.size / 1024)} KB)`;
        }
    }
}

async function fetchGdriveStatus() {
    const pill = document.getElementById('gdrive-status-pill');
    const pillText = document.getElementById('gdrive-status-pill-text');
    const badge = document.getElementById('nav-gdrive-badge');
    const authInd = document.getElementById('gdrive-auth-indicator');
    const connInfo = document.getElementById('gdrive-connected-info');
    const refreshIcon = document.getElementById('gdrive-refresh-icon');

    if (refreshIcon) refreshIcon.classList.add('animate-spin');

    try {
        const res = await fetch('/api/gdrive/status');
        const data = await res.json();

        if (data.status === 'success' && data.connected) {
            if (pill) pill.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5';
            if (pillText) pillText.innerText = 'TERHUBUNG (G-DRIVE)';
            if (badge) badge.className = 'px-2 py-0.5 bg-emerald-500/20 text-[10px] rounded text-emerald-300 border border-emerald-500/30 font-bold';
            const isOauth = data.auth_mode === 'oauth';
            if (authInd) {
                if (isOauth) {
                    authInd.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-violet-500/20 text-violet-300 border border-violet-500/30';
                    authInd.innerText = 'OAUTH AKUN PRIBADI 🟢';
                } else if (data.auth_mode === 'service_account') {
                    authInd.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30';
                    authInd.innerText = 'SERVICE ACCOUNT ⚠️ KUOTA 0';
                } else {
                    authInd.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
                    authInd.innerText = 'TERHUBUNG 🟢';
                }
            }
            // Show logout only when OAuth active; hint secret file when SA active
            const lgBtn = document.getElementById('btn-gdrive-oauth-logout');
            if (lgBtn) lgBtn.classList.toggle('hidden', !isOauth);
            // "Hapus Kredensial" only makes sense for service-account mode
            const delCredBtn = document.getElementById('btn-delete-gdrive-cred');
            if (delCredBtn) delCredBtn.classList.toggle('hidden', isOauth);
            const helpBox = document.getElementById('gdrive-oauth-secret-help');
            if (helpBox && data.auth_mode === 'service_account') {
                fetch('/api/gdrive/oauth/secret-check').then(r => r.json()).then(sc => {
                    helpBox.classList.toggle('hidden', !!sc.exists);
                }).catch(() => {});
            } else if (helpBox) {
                helpBox.classList.add('hidden');
            }
            if (connInfo) {
                connInfo.classList.remove('hidden');
                document.getElementById('gdrive-email-val').innerText = data.client_email || 'Service Account';
                document.getElementById('gdrive-project-val').innerText = data.project_id || '-';
                if (document.getElementById('gdrive-folder-val')) {
                    document.getElementById('gdrive-folder-val').innerText = data.default_folder_name || 'alfa agent';
                }
                if (document.getElementById('gdrive-folder-link') && data.default_folder_url) {
                    document.getElementById('gdrive-folder-link').href = data.default_folder_url;
                }
                if (document.getElementById('gdrive-target-folder-id') && !document.getElementById('gdrive-target-folder-id').value) {
                    document.getElementById('gdrive-target-folder-id').placeholder = `Default: ${data.default_folder_name || 'alfa agent'}`;
                }
            }
        } else {
            if (pill) pill.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1.5';
            if (pillText) pillText.innerText = 'BELUM TERHUBUNG';
            if (badge) badge.className = 'px-2 py-0.5 bg-blue-500/20 text-[10px] rounded text-blue-300 border border-blue-500/30 font-bold';
            if (authInd) {
                authInd.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30';
                authInd.innerText = 'BELUM TERHUBUNG';
            }
            if (connInfo) connInfo.classList.add('hidden');
        }
    } catch (err) {
        console.error('Fetch gdrive status error:', err);
    } finally {
        if (refreshIcon) refreshIcon.classList.remove('animate-spin');
    }
}

// ── Indikator perubahan belum disimpan ──
let _waFmtDirty = false, _waRulesDirty = false;
function waMarkDirty(which) {
    if (which === 'formats') _waFmtDirty = true; else _waRulesDirty = true;
    const dot = document.getElementById('wa-dirty-dot');
    if (dot) dot.classList.remove('hidden');
    const btn = document.getElementById(which === 'formats' ? 'btn-save-wa-formats' : 'btn-save-wa-rules');
    if (btn) btn.classList.add('ring-2', 'ring-amber-400/70');
}
function waClearDirty(which) {
    if (which === 'formats') _waFmtDirty = false; else _waRulesDirty = false;
    if (!_waFmtDirty && !_waRulesDirty) {
        const dot = document.getElementById('wa-dirty-dot');
        if (dot) dot.classList.add('hidden');
    }
    const btn = document.getElementById(which === 'formats' ? 'btn-save-wa-formats' : 'btn-save-wa-rules');
    if (btn) btn.classList.remove('ring-2', 'ring-amber-400/70');
}

async function saveAllWaSettings() {
    // Simpan dua-duanya sekali klik; aman walau salah satu kosong.
    const r1 = await saveWaFormats(true);
    const r2 = await saveWaMediaRules(true);
    const okCount = [r1, r2].filter(r => r && r.status === 'success').length;
    if (okCount === 2) showToast('Format & aturan Drive tersimpan.', 'success');
}

async function handleGdriveOauthSecretUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const preview = document.getElementById('gdrive-oauth-secret-preview');
    if (preview) preview.innerText = `Mengunggah ${file.name}...`;

    try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch('/api/gdrive/oauth/upload-secret', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('OAuth Client Secret berhasil disimpan! Silakan klik "Login dengan Akun Google".', 'success');
            if (preview) preview.innerHTML = `✅ <span class="text-emerald-400 font-bold">${file.name}</span> siap!`;
            const helpBox = document.getElementById('gdrive-oauth-secret-help');
            if (helpBox) helpBox.classList.add('hidden');
        } else {
            showToast(data.message || 'Gagal menyimpan client secret', 'error');
            if (preview) preview.innerHTML = `❌ <span class="text-rose-400 font-bold">Gagal</span>`;
        }
    } catch (err) {
        showToast(`Upload error: ${err.message}`, 'error');
    }
}

async function startGdriveOauth() {
    const btn = document.getElementById('btn-gdrive-oauth');
    const statusBox = document.getElementById('gdrive-oauth-status');

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menunggu konfirmasi di browser...';
    lucide.createIcons();
    if (statusBox) {
        statusBox.classList.remove('hidden');
        statusBox.innerHTML = '⏳ Browser akan terbuka di laptop ini. Silakan pilih akun Google Anda dan klik <b>Allow</b>. Halaman ini menunggu sampai selesai (maks 5 menit)...';
    }

    try {
        const res = await fetch('/api/gdrive/oauth/start', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'success') {
            showToast('Login OAuth berhasil! Upload kini pakai kuota akun Anda.', 'success');
            if (statusBox) statusBox.innerHTML = '✅ <b class="text-emerald-400">Login berhasil.</b> Semua upload Drive sekarang memakai akun pribadi Anda.';
            setTimeout(() => fetchGdriveStatus(), 800);
        } else if (data.needs_client_secret) {
            showToast('Client secret belum ada - ikuti langkah persiapannya.', 'warning');
            const helpBox = document.getElementById('gdrive-oauth-secret-help');
            if (helpBox) helpBox.classList.remove('hidden');
            if (statusBox) {
                statusBox.innerHTML = '❌ <b class="text-amber-400">Client secret belum ada.</b> Ikuti 4 langkah di kotak kuning di atas, lalu klik Login lagi.';
            }
        } else {
            showToast('Login OAuth gagal/dibatalkan.', 'error');
            if (statusBox) statusBox.innerHTML = '❌ Gagal: ' + (data.message || 'dibatalkan') + '. Coba lagi.';
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
        if (statusBox) statusBox.innerHTML = '❌ Error koneksi: ' + err.message;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="log-in" class="w-3.5 h-3.5"></i> Login dengan Akun Google';
        lucide.createIcons();
    }
}

async function gdriveOauthLogout() {
    if (!confirm('Hapus token OAuth dan kembali ke service account?')) return;
    try {
        const res = await fetch('/api/gdrive/oauth/logout', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'Token OAuth dihapus.', data.status === 'success' ? 'success' : 'error');
        document.getElementById('btn-gdrive-oauth-logout').classList.add('hidden');
        fetchGdriveStatus();
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function saveGdriveCredentials() {
    const jsonText = document.getElementById('gdrive-json-text').value.trim();
    const btn = document.getElementById('btn-save-gdrive-cred');

    if (!selectedGdriveFile && !jsonText) {
        showToast('Pilih file credentials.json atau tempel isi JSON terlebih dahulu!', 'error');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Memverifikasi Kredensial...';
    lucide.createIcons();

    try {
        const formData = new FormData();
        if (selectedGdriveFile) {
            formData.append('file', selectedGdriveFile);
        } else {
            formData.append('raw_json', jsonText);
        }

        const res = await fetch('/api/gdrive/credentials', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast(data.message || 'Kredensial Google Cloud berhasil diverifikasi!', 'success');
            selectedGdriveFile = null;
            document.getElementById('gdrive-json-text').value = '';
            fetchGdriveStatus();
            fetchGdriveFiles();
        } else {
            showToast(`Gagal: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Gagal menyimpan: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="check-circle" class="w-4 h-4"></i> Simpan & Verifikasi Kredensial';
        lucide.createIcons();
    }
}

async function deleteGdriveCredentials() {
    if (!confirm('Apakah Anda yakin ingin menghapus kredensial Google Drive dari sistem?')) return;
    try {
        const res = await fetch('/api/gdrive/credentials', { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Kredensial Google Drive berhasil dihapus.', 'info');
            fetchGdriveStatus();
            fetchGdriveFiles();
        }
    } catch (err) {
        showToast(`Gagal: ${err.message}`, 'error');
    }
}

async function fetchGdriveFiles() {
    const container = document.getElementById('gdrive-files-container');
    const countBadge = document.getElementById('gdrive-files-count');
    const query = document.getElementById('gdrive-search-input')?.value.trim() || '';

    if (!container) return;
    container.innerHTML = '<div class="text-center py-12 text-slate-400 text-xs"><i data-lucide="loader" class="w-6 h-6 animate-spin mx-auto mb-2 text-blue-400"></i>Memuat file dari Google Drive...</div>';
    lucide.createIcons();

    try {
        const res = await fetch(`/api/gdrive/files?query=${encodeURIComponent(query)}&limit=40`);
        const data = await res.json();

        if (data.status === 'success') {
            const files = data.files || [];
            if (countBadge) countBadge.innerText = `${files.length} File`;

            if (files.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-12 text-slate-400 text-xs">
                        <i data-lucide="folder-open" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
                        Tidak ada file ditemukan di Google Drive ${query ? `untuk kata kunci "${query}"` : ''}.
                    </div>
                `;
                lucide.createIcons();
                return;
            }

            container.innerHTML = files.map(f => {
                const isFolder = f.mimeType && f.mimeType.includes('folder');
                const icon = isFolder ? '📁' : f.name.endsWith('.pdf') ? '📄' : f.name.endsWith('.xlsx') ? '📊' : f.name.endsWith('.docx') ? '📝' : f.name.match(/\.(png|jpg|jpeg|webp)$/i) ? '🖼️' : '📎';
                const sizeStr = f.size ? `${Math.round(f.size / 1024)} KB` : (isFolder ? 'Folder' : '-');
                const modDate = f.modifiedTime ? new Date(f.modifiedTime).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' }) : '-';

                return `
                    <div class="p-3 rounded-xl bg-dark-950/80 border border-white/5 hover:border-blue-500/30 flex items-center justify-between gap-3 transition-all">
                        <div class="flex items-center gap-3 min-w-0">
                            <span class="text-xl flex-shrink-0">${icon}</span>
                            <div class="truncate">
                                <a href="${f.webViewLink || '#'}" target="_blank" class="text-xs font-bold text-white hover:text-blue-400 transition-colors truncate block">
                                    ${f.name}
                                </a>
                                <div class="text-[10px] text-slate-400 flex items-center gap-2 mt-0.5">
                                    <span>${sizeStr}</span>
                                    <span>•</span>
                                    <span>${modDate}</span>
                                    ${isFolder ? '<span class="px-1.5 py-0.2 bg-blue-500/20 text-blue-300 rounded font-bold">FOLDER</span>' : ''}
                                </div>
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 flex-shrink-0">
                            ${f.webViewLink ? `
                                <a href="${f.webViewLink}" target="_blank" class="px-2.5 py-1 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 text-xs font-bold transition-all flex items-center gap-1">
                                    <i data-lucide="external-link" class="w-3.5 h-3.5"></i> Buka
                                </a>
                            ` : ''}
                        </div>
                    </div>
                `;
            }).join('');
            lucide.createIcons();
        } else {
            container.innerHTML = `
                <div class="text-center py-12 text-rose-300 text-xs">
                    <i data-lucide="alert-circle" class="w-8 h-8 text-rose-400 mx-auto mb-2"></i>
                    ${data.message || 'Gagal memuat file Google Drive.'}
                </div>
            `;
            lucide.createIcons();
        }
    } catch (err) {
        container.innerHTML = `<div class="text-center py-12 text-rose-400 text-xs">Error: ${err.message}</div>`;
    }
}

async function promptCreateGdriveFolder() {
    const name = prompt('Masukkan nama folder baru untuk Google Drive:');
    if (!name) return;

    try {
        const res = await fetch('/api/gdrive/create-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Folder '${name}' berhasil dibuat di Google Drive!`, 'success');
            fetchGdriveFiles();
        } else {
            showToast(`Gagal: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Gagal membuat folder: ${err.message}`, 'error');
    }
}

async function syncGdriveToBrain() {
    const btn = document.getElementById('btn-gdrive-sync-brain');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menyinkronkan...';
    lucide.createIcons();

    try {
        const res = await fetch('/api/gdrive/sync-brain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ limit: 15 })
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast(`Berhasil menyinkronkan ${data.total_ingested} dokumen Drive ke Second Brain!`, 'success');
            if (typeof fetchMemory === 'function') fetchMemory();
        } else {
            showToast(`Gagal sinkronisasi: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Gagal: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="brain" class="w-3.5 h-3.5"></i> Sync Second Brain';
        lucide.createIcons();
    }
}

async function uploadDirectToGdrive() {
    const fileInput = document.getElementById('gdrive-upload-file-input');
    const folderIdInput = document.getElementById('gdrive-target-folder-id');
    const btn = document.getElementById('btn-upload-direct-gdrive');

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('Pilih file yang ingin diunggah terlebih dahulu!', 'error');
        return;
    }

    const file = fileInput.files[0];
    const folderId = folderIdInput ? folderIdInput.value.trim() : '';

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Mengunggah...';
    lucide.createIcons();

    try {
        const formData = new FormData();
        formData.append('file', file);
        if (folderId) formData.append('folder_id', folderId);

        const res = await fetch('/api/gdrive/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (data.status === 'success') {
            showToast(`File '${file.name}' berhasil diunggah ke Google Drive!`, 'success');
            fileInput.value = '';
            fetchGdriveFiles();
        } else {
            showToast(`Gagal mengunggah: ${data.message}`, 'error');
        }
    } catch (err) {
        showToast(`Gagal upload: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="arrow-up" class="w-3.5 h-3.5"></i> Upload';
        lucide.createIcons();
    }
}

// Master Application Orchestrator Initialization
window.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize State, Theme & Active Tab
    if (typeof initTheme === 'function') initTheme();
    if (typeof restoreActiveTab === 'function') restoreActiveTab();
    if (typeof initAlpineState === 'function') initAlpineState();

    // 2. Initialize Telemetry Chart & Polling
    if (typeof initTelemetryChart === 'function') initTelemetryChart();
    if (typeof startTelemetryPolling === 'function') {
        startTelemetryPolling(2000);
    } else if (typeof fetchStats === 'function') {
        fetchStats();
        setInterval(fetchStats, 2000);
    }

    // 3. Initialize Global Hotkeys
    if (typeof initHotkeys === 'function') initHotkeys();

    // 4. Initialize Domain Data & Services
    if (typeof fetchTools === 'function') fetchTools();
    if (typeof fetchGdriveStatus === 'function') fetchGdriveStatus();
    if (typeof fetchVaultSecrets === 'function') fetchVaultSecrets();
    if (typeof fetchPasskeyStatus === 'function') fetchPasskeyStatus();
    if (typeof fetchWaQr === 'function') fetchWaQr();
    if (typeof fetchWaReports === 'function') fetchWaReports();
    if (typeof fetchModelsCatalog === 'function') fetchModelsCatalog();
    if (typeof fetchAgents === 'function') fetchAgents();
    if (typeof fetchKeys === 'function') fetchKeys();
    if (typeof startTokenUsagePolling === 'function') startTokenUsagePolling();
    if (typeof fetchAntigravityAccounts === 'function') fetchAntigravityAccounts();
    if (typeof fetchSettings === 'function') fetchSettings();

    // Periodic Background Timers
    setInterval(fetchWaQr, 4000);
    setInterval(fetchWaReports, 8000);
    if (typeof fetchWaDriveUploads === 'function') {
        fetchWaDriveUploads();
        setInterval(fetchWaDriveUploads, 8000);
    }
    if (typeof fetchSwarmLive === 'function') {
        setInterval(fetchSwarmLive, 2500);
    }

    // Refresh Lucide Icons
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
});

// ==================== PIPELINE CANVAS STUDIO ====================
const cvState = { nodes: [], edges: [], seq: 1, dragging: null, linking: null, view: 'canvas', toolNames: [],
                  trigger: { enabled: false, minutes: 60 } };
const cvTypeMeta = {
    prompt:   { color: 'violet',  label: '🧠 Prompt',      verb: 'Tanya AI' },
    tool:     { color: 'cyan',    label: '🛠 Tool',       verb: 'Jalankan tool' },
    template: { color: 'amber',   label: '📝 Template',   verb: 'Susun teks' },
    set:      { color: 'emerald', label: '📌 Set Var',    verb: 'Set nilai' },
    http:     { color: 'sky',     label: '🌐 HTTP',       verb: 'Panggil API' },
    foreach:  { color: 'orange',  label: '🔁 Ulangi Item', verb: 'Ulangi per item' },
};
const cvPresets = {
    riset: { id: 'riset_dan_ringkas', nodes: [
        { id: 'cari',    type: 'tool',     x: 40,  y: 60,  config: { tool: 'web_search', args: '{"query": "berita {{topik}} terbaru"}' } },
        { id: 'rangkum', type: 'prompt',   x: 330, y: 60,  config: { text: 'Ringkas hasil pencarian ini menjadi 3 poin utama:\n{{cari}}' } },
        { id: 'simpan',  type: 'tool',     x: 620, y: 60,  config: { tool: 'write_local_file', args: '{"file_path": "/dev/shm/alfa_sandbox/pipeline_out/ringkasan.md", "content": "# Ringkasan\\n\\n{{rangkum}}"}' } },
    ], edges: [ { from: 'cari', to: 'rangkum' }, { from: 'rangkum', to: 'simpan' } ] },
    tulis: { id: 'ai_tulis_file', nodes: [
        { id: 'tulisd', type: 'prompt', x: 40, y: 60,
          config: { text: 'Tulis puisi pendek 4 baris tentang teknologi AI.' } },
        { id: 'simpsn', type: 'tool',   x: 330, y: 60,
          config: { tool: 'write_local_file', args: '{"file_path": "/dev/shm/alfa_sandbox/pipeline_out/puisi.txt", "content": "{{tulisd}}"}' } },
    ], edges: [ { from: 'tulisd', to: 'simpsn' } ] },
    cek_status: { id: 'cek_sistem', nodes: [
        { id: 'cek',   type: 'tool',   x: 40,  y: 60,  config: { tool: 'get_system_stats', args: '{}' } },
        { id: 'lapor', type: 'prompt', x: 330, y: 60,
          config: { text: 'Berdasarkan data sistem ini, buat laporan kesehatan 2 kalimat:\n{{cek}}' } },
    ], edges: [ { from: 'cek', to: 'lapor' } ] },
};

function cvSetView(mode) {
    cvState.view = mode;
    document.getElementById('cv-canvas-wrap').classList.toggle('hidden', mode !== 'canvas');
    document.getElementById('cv-list-wrap').classList.toggle('hidden', mode !== 'list');
    const on = 'px-2.5 py-1 rounded-md bg-white/10 text-slate-200 text-[11px] font-bold';
    const off = 'px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 text-[11px] font-bold';
    document.getElementById('cv-view-canvas').className = mode === 'canvas' ? on : off;
    document.getElementById('cv-view-list').className = mode === 'list' ? on : off;
    if (mode === 'list') cvRenderList();
}

function cvStepSummary(n) {
    if (n.type === 'prompt') return `Tanya AI: "${(n.config.text || '(kosong)').slice(0, 70)}"`;
    if (n.type === 'template') return `Susun teks: "${(n.config.text || '').slice(0, 70)}"`;
    if (n.type === 'set') return `Set variabel "${n.id}" = ${(n.config.value || '').slice(0, 50)}`;
    if (n.type === 'http') return `${(n.config.method || 'GET')} ${(n.config.url || '(url kosong)').slice(0, 60)}`;
    if (n.type === 'foreach') return `Ulangi tiap item dari {{${(n.config.over || '?').replace(/[{}]/g, '')}}}: "${(n.config.text || '').slice(0, 50)}"`;
    let a = '';
    try { a = Object.values(JSON.parse(n.config.args || '{}')).map(v => String(v).slice(0, 30)).join(', '); } catch {}
    return `Jalankan tool ${n.config.tool || '?'}${a ? ` (${a})` : ''}`;
}

function cvRenderList() {
    const wrap = document.getElementById('cv-list-wrap');
    if (!cvState.nodes.length) {
        wrap.innerHTML = '<p class="text-slate-500 text-sm font-mono text-center py-10">Belum ada langkah. Kembali ke Kanvas atau pilih ✨ contoh siap pakai.</p>';
        return;
    }
    // urutkan berdasar dependensi (sederhana: BFS dari yang tanpa input)
    const order = [];
    const done = new Set();
    while (order.length < cvState.nodes.length) {
        const ready = cvState.nodes.filter(n => !done.has(n.id) &&
            cvState.edges.filter(e => e.to === n.id).every(e => done.has(e.from)));
        if (!ready.length) { cvState.nodes.filter(n => !done.has(n.id)).forEach(n => order.push(n)); break; }
        ready.forEach(n => { order.push(n); done.add(n.id); });
    }
    wrap.innerHTML = '<p class="text-[11px] text-slate-500 mb-1">Alur kerja dibaca dari atas ke bawah:</p>' + order.map((n, i) => {
        const meta = cvTypeMeta[n.type];
        const deps = cvState.edges.filter(e => e.to === n.id).map(e => order.indexOf(cvState.nodes.find(x => x.id === e.from)) + 1);
        const after = deps.length ? `<span class="text-[10px] text-slate-500">setelah langkah ${deps.join(', ')}</span>` : '';
        return `<div class="flex items-start gap-3 p-2.5 rounded-xl bg-dark-900/80 border border-white/5">
            <span class="w-6 h-6 shrink-0 rounded-full bg-fuchsia-500/20 text-fuchsia-300 text-xs font-bold flex items-center justify-center">${i + 1}</span>
            <div class="text-xs"><span class="font-bold text-slate-300">${meta.verb}</span>
                <span class="text-slate-400">— ${cvStepSummary(n).replace(/</g, '&lt;')}</span>
                <div>${after}</div></div>
        </div>`;
    }).join('');
}

async function cvEnsureToolNames() {
    if (cvState.toolNames.length) return;
    try {
        const res = await fetch('/api/tools');
        const d = await res.json();
        cvState.toolNames = (d.tools || []).map(t => t.name || t.function?.name).filter(Boolean);
    } catch { cvState.toolNames = []; }
}

function cvValidate() {
    const issues = [];
    if (!cvState.nodes.length) issues.push('Kanvas masih kosong.');
    cvState.nodes.forEach(n => {
        if (n.type === 'tool' && !(n.config.tool || '').trim())
            issues.push(`Step "${n.id}": nama tool belum diisi.`);
        if ((n.type === 'prompt' || n.type === 'template') && !(n.config.text || '').trim())
            issues.push(`Step "${n.id}": teks masih kosong.`);
        if (n.type === 'http' && !/^https?:\/\//.test((n.config.url || '').trim()))
            issues.push(`Step "${n.id}": URL HTTP harus diawali http:// atau https://`);
        if (n.type === 'foreach' && !(n.config.over || '').includes('{{'))
            issues.push(`Step "${n.id}": isi daftar dengan variabel, contoh {{hasil_sebelumnya}}`);
    });
    // variabel {{x}} dipakai tapi tidak pernah dibuat oleh step manapun
    const defined = new Set([...cvState.nodes.map(n => n.id)]);
    cvState.nodes.forEach(n => {
        const blob = JSON.stringify(n.config || {});
        (blob.match(/\{\{\s*(\w+)\s*\}\}/g) || []).forEach(m => {
            const v = m.replace(/[{}]/g, '').trim();
            if (!defined.has(v)) issues.push(`Step "${n.id}" memakai variabel {{${v}}} yang tidak ada sumbernya.`);
        });
    });
    return issues;
}

function cvLoadPreset(key) {
    const p = cvPresets[key];
    if (!p) return;
    cvState.nodes = JSON.parse(JSON.stringify(p.nodes));
    cvState.edges = JSON.parse(JSON.stringify(p.edges));
    document.getElementById('cv-pid').value = p.id;
    cvRender(); cvRenderList();
    cvStatus(`Contoh "${key}" dimuat — klik ▶ Jalankan untuk mencoba!`);
    if (cvState.view === 'canvas') setTimeout(() => cvSetView('list'), 150), setTimeout(() => cvSetView('canvas'), 1400);
}

function initCanvas() {
    const sel = document.getElementById('cv-load');
    if (!sel || sel.options.length > 1) return;
    fetch('/api/pipelines').then(r => r.json()).then(d => {
        (d.pipelines || []).forEach(p => {
            const o = document.createElement('option');
            o.value = p.id; o.textContent = `${p.name} (${p.steps} step)`;
            sel.appendChild(o);
        });
    }).catch(() => {});
    cvEnsureToolNames();
}

function cvStatus(msg, isErr = false) {
    const el = document.getElementById('cv-status');
    el.innerText = msg;
    el.className = isErr ? 'text-xs text-rose-400 ml-auto font-mono' : 'text-xs text-emerald-400 ml-auto font-mono';
}

function cvNew() {
    cvState.nodes = []; cvState.edges = []; cvState.seq = 1; cvState.loadedId = '';
    document.getElementById('cv-pid').value = 'my_pipeline';
    cvRender();
    cvStatus('Kanvas baru dibuat');
}

async function cvLoad(pid) {
    if (!pid) return;
    try {
        const res = await fetch('/api/pipelines/' + encodeURIComponent(pid));
        const d = await res.json();
        if (d.status !== 'success') throw new Error('tidak ditemukan');
        const p = d.pipeline;
        document.getElementById('cv-pid').value = p.id;
        cvState.nodes = []; cvState.edges = []; cvState.seq = 0;
        cvState.trigger = Object.assign({ enabled: false, minutes: 60 }, p.trigger || {});
        document.getElementById('cv-trig-en').checked = !!cvState.trigger.enabled;
        document.getElementById('cv-trig-min').value = cvState.trigger.minutes;
        (p.steps || []).forEach((s, i) => {
            cvState.seq++;
            const cfg = {};
            if (s.type === 'prompt') { cfg.text = s.text || ''; cfg.system = s.system || ''; }
            if (s.type === 'tool') { cfg.tool = s.tool || ''; cfg.args = JSON.stringify(s.args || {}); }
            if (s.type === 'template') cfg.text = s.text || '';
            if (s.type === 'set') cfg.value = s.value == null ? '' : String(s.value);
            if (s.type === 'http') { cfg.method = s.method || 'GET'; cfg.url = s.url || ''; cfg.body = s.body || ''; }
            if (s.type === 'foreach') { cfg.over = s.over || ''; cfg.item_var = s.item_var || 'item'; cfg.text = s.text || ''; }
            if (s.if) { const c = s.if; const opLbl = ({ contains: 'mengandung', not_contains: 'tidak mengandung', eq: '==', neq: '!=', empty: 'kosong', not_empty: 'tidak kosong', gt: '>', lt: '<', regex: '~' })[c.op] || c.op; cfg.if_expr = `${c.left || ''} ${opLbl} ${c.right || ''}`.trim(); }
            cvState.nodes.push({ id: s.id, type: s.type, x: 60 + (i % 3) * 240, y: 40 + Math.floor(i / 3) * 170, config: cfg });
            (s.depends_on || []).forEach(dep => cvState.edges.push({ from: dep, to: s.id }));
        });
        cvRender();
        cvTriggerChanged();
        cvStatus(`Dimuat: ${p.id}`);
    } catch (e) { cvStatus('Gagal muat: ' + e.message, true); }
}

async function cvSave(silent = false) {
    const pid = document.getElementById('cv-pid').value.trim();
    if (!pid) return cvStatus('Beri nama pipeline dulu! (kolom kiri atas)', true);
    if (!cvState.nodes.length) return cvStatus('Kanvas masih kosong — tambah step atau pilih ✨ contoh.', true);
    const issues = cvValidate();
    if (issues.length) {
        if (!silent) return cvStatus('⚠ ' + issues[0], true);
        issues.forEach(i => console.warn('[Canvas]', i));
    }
    try {
        const steps = cvSerialize();
        const body = { id: pid, name: pid.replace(/_/g, ' '), steps,
                       trigger: cvState.trigger };
        const res = await fetch('/api/pipelines/' + encodeURIComponent(pid), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await res.json();
        if (d.status !== 'success') throw new Error(d.detail || 'gagal');
        cvStatus('💾 Tersimpan sebagai ' + pid);
        initCanvas._done = false;
    } catch (e) { if (!silent) cvStatus('Simpan gagal: ' + e.message, true); }
}

async function cvRun() {
    const pid = document.getElementById('cv-pid').value.trim();
    if (!pid) return cvStatus('Beri nama pipeline dulu!', true);
    const issues = cvValidate();
    if (issues.length) {
        document.getElementById('cv-result').classList.remove('hidden');
        document.getElementById('cv-result-body').innerText =
            '⚠ Periksa dulu sebelum menjalankan:\n' + issues.map(i => '  • ' + i).join('\n');
        return cvStatus(`⚠ ${issues.length} masalah perlu diperbaiki`, true);
    }
    const btn = document.getElementById('cv-run-btn');
    btn.disabled = true; btn.innerText = '⏳ Menjalankan...'; cvStatus('Eksekusi pipeline...');
    try {
        // auto-save sebelum run agar server memakai versi terbaru
        await cvSave(true);
        const res = await fetch(`/api/pipelines/${encodeURIComponent(pid)}/run`, { method: 'POST' });
        const d = await res.json();
        document.getElementById('cv-result').classList.remove('hidden');
        let txt = `STATUS : ${d.status} (${d.duration_ms} ms)\n`;
        (d.trace || []).forEach(t => { txt += `  • ${t.step}: ${t.status}${t.detail ? ' — ' + t.detail : ''}\n`; });
        txt += '\n--- OUTPUT ---\n' + Object.entries(d.outputs || {}).map(([k, v]) => `[${k}]\n${v}`).join('\n\n');
        if (d.error) txt += `\n\nERROR: ${d.error}`;
        document.getElementById('cv-result-body').innerText = txt;
        cvStatus(d.status === 'success' ? '✅ Pipeline sukses' : '❌ Pipeline gagal', d.status !== 'success');
    } catch (e) { cvStatus('Run gagal: ' + e.message, true); }
    btn.disabled = false; btn.innerText = '▶ Jalankan';
}

function cvAddNode(type) {
    if (cvState.view !== 'canvas') cvSetView('canvas');
    cvState.seq++;
    const n = { id: `step_${cvState.seq}`, type,
                x: 40 + Math.random() * 420, y: 30 + Math.random() * 300, config: {} };
    if (type === 'tool') n.config.args = '{}';
    cvState.nodes.push(n);
    document.getElementById('cv-empty')?.classList.add('hidden');
    cvRender();
}

function cvDeleteNode(id) {
    cvState.nodes = cvState.nodes.filter(n => n.id !== id);
    cvState.edges = cvState.edges.filter(e => e.from !== id && e.to !== id);
    cvRender();
}

function cvNodeHtml(n) {
    const meta = cvTypeMeta[n.type];
    const cfg = n.config;
    let body = '';
    if (n.type === 'prompt') body = `
        <textarea data-f="text" rows="2" placeholder="instruksi... gunakan {{var}}">${cfg.text || ''}</textarea>
        <textarea data-f="system" rows="1" placeholder="system (opsional)" class="mt-1 opacity-80">${cfg.system || ''}</textarea>`;
    if (n.type === 'tool') {
        const sorted = [...new Set([...cvState.toolNames].sort((a, b) => a.localeCompare(b)))]
            .filter(tn => tn !== cfg.tool);
        const opts = (cfg.tool ? [cfg.tool] : []).concat(sorted)
            .map(tn => `<option value="${tn}" ${tn === cfg.tool ? 'selected' : ''} style="background:#0f172a;color:#e2e8f0;font-size:13px">${tn}</option>`).join('');
        body = `
        <select data-f="tool" class="font-mono">
            <option value="" style="background:#0f172a;color:#94a3b8">— pilih tool (${cvState.toolNames.length + 1}) —</option>
            ${opts}
            ${!cfg.tool || cvState.toolNames.includes(cfg.tool) ? '' : ''}
        </select>
        <textarea data-f="args" rows="2" placeholder='{"query": "{{topik}}"}' class="mt-1 font-mono text-[10px]">${cfg.args || '{}'}</textarea>
        <p class="text-[9px] text-slate-500 leading-tight">Isi {{nama_step}} untuk memakai hasil langkah lain.</p>`;
    }
    if (n.type === 'template') body = `<textarea data-f="text" rows="2" placeholder="teks dengan {{var}}">${cfg.text || ''}</textarea>`;
    if (n.type === 'set') body = `<input data-f="value" value="${(cfg.value || '').replace(/"/g, '&quot;')}" placeholder="nilai">`;
    if (n.type === 'http') body = `
        <div class="flex gap-1">
            <select data-f="method" class="w-20 font-mono">
                ${['GET','POST','PUT','DELETE'].map(m => `<option ${m === (cfg.method || 'GET') ? 'selected' : ''}>${m}</option>`).join('')}
            </select>
            <input data-f="url" value="${(cfg.url || '').replace(/"/g, '&quot;')}" placeholder="https://api..." class="font-mono">
        </div>
        <textarea data-f="body" rows="1" placeholder='body (opsional) {"q": "{{var}}"}' class="mt-1 font-mono text-[10px]">${cfg.body || ''}</textarea>`;
    if (n.type === 'foreach') body = `
        <input data-f="over" value="${(cfg.over || '').replace(/"/g, '&quot;')}" placeholder="{{daftar_var}}" class="font-mono">
        <input data-f="item_var" value="${(cfg.item_var || 'item').replace(/"/g, '&quot;')}" placeholder="nama item" class="font-mono mt-1">
        <textarea data-f="text" rows="2" placeholder="proses tiap item: ringkas {{item}}" class="mt-1">${cfg.text || ''}</textarea>`;

    const cond = cfg.if_expr || '';
    const condHtml = `
        <input data-f="if_expr" value="${cond.replace(/"/g, '&quot;')}"
               placeholder="Jika... contoh: {{cari}} mengandung AI"
               title="Step dijalankan HANYA bila kondisi terpenuhi. Operator: mengandung, ==, !=, kosong, tidak kosong, >, <"
               class="mt-1 border-amber-500/30">`;

    const border = { prompt: 'border-violet-500/40', tool: 'border-cyan-500/40', template: 'border-amber-500/40',
                     set: 'border-emerald-500/40', http: 'border-sky-500/40', foreach: 'border-orange-500/40' }[n.type];
    return `
    <div class="cv-node absolute w-52 bg-dark-900/95 rounded-xl border ${border} shadow-lg select-none"
         style="left:${n.x}px; top:${n.y}px" data-id="${n.id}">
        <div class="cv-drag flex items-center justify-between px-2.5 py-1.5 cursor-move rounded-t-xl bg-white/5">
            <span class="text-[11px] font-bold ${meta.color === 'violet' ? 'text-violet-300' : meta.color === 'cyan' ? 'text-cyan-300' : meta.color === 'amber' ? 'text-amber-300' : 'text-emerald-300'}">
                ${meta.label} · <span class="opacity-60 font-mono">${n.id}</span></span>
            <button onclick="cvDeleteNode('${n.id}')" class="text-slate-500 hover:text-rose-400 text-[11px] leading-none">✕</button>
        </div>
        <div class="p-2 space-y-1">
            ${body}
            ${condHtml}
        </div>
        <div class="cv-in"  data-node="${n.id}" title="input"></div>
        <div class="cv-out" data-node="${n.id}" title="tarik ke node lain"></div>
    </div>`;
}

function cvRender() {
    const wrap = document.getElementById('cv-nodes');
    wrap.innerHTML = cvState.nodes.map(cvNodeHtml).join('');
    // pasang event
    wrap.querySelectorAll('.cv-node').forEach(el => {
        const id = el.dataset.id;
        el.querySelector('.cv-drag').addEventListener('mousedown', ev => cvStartDrag(ev, id));
        el.querySelectorAll('[data-f]').forEach(inp => {
            inp.addEventListener('change', () => {
                const n = cvState.nodes.find(x => x.id === id);
                n.config[inp.dataset.f] = inp.value;
            });
        });
        const inP = el.querySelector('.cv-in'), outP = el.querySelector('.cv-out');
        outP.addEventListener('mousedown', ev => { ev.stopPropagation(); cvState.linking = { from: id }; ev.preventDefault(); });
        inP.addEventListener('mouseup', () => {
            if (cvState.linking && cvState.linking.from && cvState.linking.from !== id) {
                if (!cvState.edges.some(e => e.from === cvState.linking.from && e.to === id))
                    cvState.edges.push({ from: cvState.linking.from, to: id });
            }
            cvState.linking = null; cvDrawEdges();
        });
    });
    cvDrawEdges();
    if (cvState.nodes.length) document.getElementById('cv-empty')?.classList.add('hidden');
    if (cvState.view === 'list') cvRenderList();
}

function cvDrawEdges(tempLine) {
    const svg = document.getElementById('cv-svg');
    const wrapEl = document.getElementById('cv-canvas-wrap');
    if (!svg || !wrapEl) return;
    const wRect = wrapEl.getBoundingClientRect();
    svg.innerHTML = '';
    const posOf = (nodeId, side) => {
        const el = wrapEl.querySelector(`.cv-node[data-id="${nodeId}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {
            x: (side === 'out' ? r.right : r.left) - wRect.left,
            y: r.top - wRect.top + r.height / 2,
        };
    };
    cvState.edges.forEach(e => {
        const a = posOf(e.from, 'out'); if (!a) return;
        const b = posOf(e.to, 'in');    if (!b) return;
        cvAddEdgePath(svg, a.x, a.y, b.x, b.y, e);
    });
    if (tempLine) cvAddEdgePath(svg, tempLine.x1, tempLine.y1, tempLine.x2, tempLine.y2, null, true);
}

function cvAddEdgePath(svg, x1, y1, x2, y2, edge, temp = false) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const mx = (x1 + x2) / 2;
    path.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', temp ? '#64748b' : '#22d3ee');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('stroke-dasharray', temp ? '5,4' : '');
    if (edge) {
        path.style.pointerEvents = 'stroke'; path.style.cursor = 'pointer';
        path.addEventListener('click', () => {
            cvState.edges = cvState.edges.filter(e2 => e2 !== edge); cvDrawEdges();
        });
    }
    svg.appendChild(path);
}

function cvStartDrag(ev, id) {
    if (ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'INPUT') return;
    const n = cvState.nodes.find(x => x.id === id);
    const wrapRect = document.getElementById('cv-canvas-wrap').getBoundingClientRect();
    cvState.dragging = { id, dx: ev.clientX - (wrapRect.left + n.x), dy: ev.clientY - (wrapRect.top + n.y) };
    ev.preventDefault();
}

document.addEventListener('mousemove', ev => {
    if (cvState.dragging) {
        const n = cvState.nodes.find(x => x.id === cvState.dragging.id);
        const wr = document.getElementById('cv-canvas-wrap').getBoundingClientRect();
        n.x = Math.max(0, ev.clientX - cvState.dragging.dx - wr.left);
        n.y = Math.max(0, ev.clientY - cvState.dragging.dy - wr.top);
        const el = document.querySelector(`.cv-node[data-id="${n.id}"]`);
        if (el) { el.style.left = n.x + 'px'; el.style.top = n.y + 'px'; }
        cvDrawEdges();
    } else if (cvState.linking) {
        const wr = document.getElementById('cv-canvas-wrap').getBoundingClientRect();
        cvDrawEdges({ x1: ev.clientX - wr.left, y1: ev.clientY - wr.top,
                      x2: ev.clientX - wr.left + 1, y2: ev.clientY - wr.top + 1 });
    }
});

document.addEventListener('mouseup', () => { cvState.dragging = null; setTimeout(() => { if (cvState.linking) { cvState.linking = null; cvDrawEdges(); } }, 50); });

function cvParseCond(s) {
    s = (s || '').trim();
    if (!s) return null;
    const ops = [['tidak mengandung', 'not_contains'], ['mengandung', 'contains'],
                 ['==', 'eq'], ['!=', 'neq'], ['tidak kosong', 'not_empty'],
                 ['kosong', 'empty'], ['>', 'gt'], ['<', 'lt']];
    for (const [lbl, op] of ops) {
        const idx = s.indexOf(lbl);
        if (idx >= 0) return { left: s.slice(0, idx).trim(), op, right: s.slice(idx + lbl.length).trim() };
    }
    return { left: s, op: 'not_empty', right: '' };
}

function cvSerialize() {
    return cvState.nodes.map(n => {
        const step = { id: n.id, type: n.type };
        step.depends_on = cvState.edges.filter(e => e.to === n.id).map(e => e.from);
        if (n.type === 'prompt') { step.text = n.config.text || ''; if (n.config.system) step.system = n.config.system; }
        if (n.type === 'tool') { step.tool = n.config.tool || ''; try { step.args = JSON.parse(n.config.args || '{}'); } catch { step.args = {}; } }
        if (n.type === 'template') step.text = n.config.text || '';
        if (n.type === 'set') step.value = n.config.value || '';
        if (n.type === 'http') { step.method = n.config.method || 'GET'; step.url = n.config.url || ''; if (n.config.body) step.body = n.config.body; }
        if (n.type === 'foreach') { step.over = n.config.over || ''; step.item_var = n.config.item_var || 'item'; step.inner_type = 'template'; step.text = n.config.text || ''; }
        const cond = cvParseCond(n.config.if_expr);
        if (cond) step.if = cond;
        return step;
    });
}

function cvTriggerChanged() {
    const en = document.getElementById('cv-trig-en').checked;
    const min = parseInt(document.getElementById('cv-trig-min').value) || 60;
    cvState.trigger = { enabled: en, minutes: Math.max(5, min) };
    const pid = document.getElementById('cv-pid').value.trim() || '<pipeline_id>';
    document.getElementById('cv-webhook-hint').innerText =
        `Webhook: POST /api/pipelines/${pid}/webhook`;
}

async function cvShowRuns() {
    const pid = document.getElementById('cv-pid').value.trim();
    if (!pid) return cvStatus('Beri nama pipeline dulu!', true);
    try {
        const res = await fetch(`/api/pipelines/${encodeURIComponent(pid)}/runs?limit=10`);
        const d = await res.json();
        document.getElementById('cv-result').classList.remove('hidden');
        if (!(d.runs || []).length) {
            document.getElementById('cv-result-body').innerText = 'Belum ada riwayat eksekusi.';
            return;
        }
        let txt = `🕘 ${d.runs.length} run terakhir:\n`;
        d.runs.forEach(r => {
            txt += `  • ${new Date(r.ts * 1000).toLocaleString()} — ${r.status} (${r.duration_ms} ms, ${r.steps} langkah)\n`;
        });
    } catch (e) { cvStatus('Gagal ambil riwayat: ' + e.message, true); }
}
// ==================== /PIPELINE CANVAS STUDIO ====================


// Fetch home dir from server so artifact path detection works on any username
fetch("/api/system/home-dir").then(r => r.json()).then(d => {
    if (d && d.home_dir) window._alfaHomeDir = d.home_dir;
}).catch(() => {});

