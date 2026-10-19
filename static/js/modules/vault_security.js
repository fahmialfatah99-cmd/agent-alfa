
/* ==== ES MODULE BRIDGE ==== */
import { escHtml, showToast } from './state.js';
// ==================== ALFA SECURE VAULT & CYBER SENTRY JS ====================
let currentVaultCategory = 'all';
let allVaultSecretsData = [];

export function switchVaultSubTab(sub) {
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

export async function fetchVaultSecrets(category = null) {
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

export function filterVaultSecrets(cat) {
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
                            <span class="truncate">${escHtml(sec.name)}</span>
                        </div>
                        <div class="text-[10px] text-slate-400 truncate">${escHtml(sec.notes || 'Enkripsi AES-256-GCM')}</div>
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

export async function storeVaultSecretForm(e) {
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

export async function revealVaultSecret(id) {
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

export async function copyVaultSecret(id) {
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

export async function deleteVaultSecret(id, name) {
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
export async function runCyberSentryAudit(e) {
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
                    <span class="font-bold text-xs text-white font-mono uppercase">${escHtml(k.replace(/_/g, ' '))}</span>
                    ${badge}
                </div>
                <p class="text-[11px] text-slate-400 font-sans">${escHtml(c.desc)}</p>
                ${c.value ? `<div class="text-[10px] font-mono text-slate-500 truncate bg-dark-900 p-1 rounded">${escHtml(c.value)}</div>` : ''}
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
                        <span class="font-bold text-white font-mono">${escHtml(f.header)}</span>
                        ${sevBadge}
                    </div>
                    <p class="text-slate-300">${escHtml(f.issue)}</p>
                    <div class="text-[11px] font-mono text-cyan-300 bg-cyan-500/10 p-2 rounded-lg border border-cyan-500/20">
                        💡 Solusi: ${escHtml(f.recommendation)}
                    </div>
                </div>
            `;
        }).join('');
    }
    lucide.createIcons();
}

// ==================== PASSKEY & SECURITY SETTINGS JS ====================
export async function fetchPasskeyStatus() {
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

export async function togglePasskeySwitch() {
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


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.copyVaultSecret = copyVaultSecret;
window.deleteVaultSecret = deleteVaultSecret;
window.fetchVaultSecrets = fetchVaultSecrets;
window.filterVaultSecrets = filterVaultSecrets;
window.revealVaultSecret = revealVaultSecret;
window.runCyberSentryAudit = runCyberSentryAudit;
window.storeVaultSecretForm = storeVaultSecretForm;
window.switchVaultSubTab = switchVaultSubTab;
window.togglePasskeySwitch = togglePasskeySwitch;
