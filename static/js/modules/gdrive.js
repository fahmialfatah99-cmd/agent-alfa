
/* ==== ES MODULE BRIDGE ==== */
import { fetchMemory, saveWaFormats, saveWaMediaRules } from '../app.js';
import { escAttr, escHtml, showToast } from './state.js';
// ==================== GOOGLE DRIVE & GOOGLE CLOUD SUITE LOGIC ====================
let selectedGdriveFile = null;

export function handleGdriveFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        selectedGdriveFile = file;
        const preview = document.getElementById('gdrive-filename-preview');
        if (preview) {
            preview.innerHTML = `File terpilih: <span class="text-emerald-400 font-bold font-mono">${file.name}</span> (${Math.round(file.size / 1024)} KB)`;
        }
    }
}

export async function fetchGdriveStatus() {
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
        } else if (data.has_local_mounts) {
            if (pill) pill.className = 'px-2.5 py-0.5 text-xs font-bold rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 flex items-center gap-1.5';
            if (pillText) pillText.innerText = 'TERHUBUNG (MOUNT G-DRIVE)';
            if (badge) badge.className = 'px-2 py-0.5 bg-cyan-500/20 text-[10px] rounded text-cyan-300 border border-cyan-500/30 font-bold';
            if (authInd) {
                authInd.className = 'text-[10px] px-2 py-0.5 rounded font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30';
                authInd.innerText = 'LOCAL MOUNT (RCLONE) 🟢';
            }
            if (connInfo) {
                connInfo.classList.remove('hidden');
                const mountInfo = (data.mounted_drives || []).map(m => `${m.name} (${m.items_count} item)`).join(', ');
                document.getElementById('gdrive-email-val').innerText = mountInfo || 'Local Rclone Mount';
                document.getElementById('gdrive-project-val').innerText = 'Local Storage Mount';
                if (document.getElementById('gdrive-folder-val')) {
                    document.getElementById('gdrive-folder-val').innerText = 'GDrive1 / ~/GDrive1';
                }
            }
            const statusBox = document.getElementById('gdrive-oauth-status');
            if (statusBox && data.error && (data.error.includes('kedaluwarsa') || data.error.includes('expired') || data.error.includes('invalid_grant'))) {
                statusBox.classList.remove('hidden');
                statusBox.innerHTML = `ℹ️ <b class="text-cyan-400">Akses Google Drive Aktif via Local Mount.</b> Token REST API Google Cloud kedaluwarsa (7 hari limit mode testing), namun sistem membaca & menulis langsung ke <code>~/GDrive1</code> secara real-time. Klik <i>Login dengan Akun Google</i> jika ingin memperbarui token REST API.`;
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
export function waMarkDirty(which) {
    if (which === 'formats') _waFmtDirty = true; else _waRulesDirty = true;
    const dot = document.getElementById('wa-dirty-dot');
    if (dot) dot.classList.remove('hidden');
    const btn = document.getElementById(which === 'formats' ? 'btn-save-wa-formats' : 'btn-save-wa-rules');
    if (btn) btn.classList.add('ring-2', 'ring-amber-400/70');
}
export function waClearDirty(which) {
    if (which === 'formats') _waFmtDirty = false; else _waRulesDirty = false;
    if (!_waFmtDirty && !_waRulesDirty) {
        const dot = document.getElementById('wa-dirty-dot');
        if (dot) dot.classList.add('hidden');
    }
    const btn = document.getElementById(which === 'formats' ? 'btn-save-wa-formats' : 'btn-save-wa-rules');
    if (btn) btn.classList.remove('ring-2', 'ring-amber-400/70');
}

export async function saveAllWaSettings() {
    // Simpan dua-duanya sekali klik; aman walau salah satu kosong.
    const r1 = await saveWaFormats(true);
    const r2 = await saveWaMediaRules(true);
    const okCount = [r1, r2].filter(r => r && r.status === 'success').length;
    if (okCount === 2) showToast('Format & aturan Drive tersimpan.', 'success');
}

export async function handleGdriveOauthSecretUpload(e) {
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

export async function startGdriveOauth() {
    const btn = document.getElementById('btn-gdrive-oauth');
    const statusBox = document.getElementById('gdrive-oauth-status');

    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menunggu konfirmasi di browser...';
    lucide.createIcons();
    if (statusBox) {
        statusBox.classList.remove('hidden');
        statusBox.innerHTML = '⏳ Menyiapkan otorisasi Google...';
    }

    // Ambil auth URL agar user bisa klik langsung jika browser tidak otomatis terbuka
    fetch('/api/gdrive/oauth/auth-url').then(r => r.json()).then(urlData => {
        if (urlData && urlData.auth_url && statusBox && !statusBox.innerHTML.includes('Login berhasil')) {
            statusBox.innerHTML = `
                <div class="space-y-2">
                    <p class="text-slate-300">⏳ Browser di laptop akan terbuka otomatis. Jika tidak terbuka, klik tombol di bawah:</p>
                    <a href="${escAttr(urlData.auth_url)}" target="_blank" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-bold text-xs transition-all shadow-md">
                        👉 Buka Halaman Login Akun Google ↗
                    </a>
                </div>
            `;
        }
    }).catch(() => {});

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

export async function gdriveOauthLogout() {
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

export async function saveGdriveCredentials() {
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

export async function deleteGdriveCredentials() {
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

export async function fetchGdriveFiles() {
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
                                <a href="${escAttr(f.webViewLink || '#')}" target="_blank" rel="noopener noreferrer" class="text-xs font-bold text-white hover:text-blue-400 transition-colors truncate block">
                                    ${escHtml(f.name)}
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
                                <a href="${escAttr(f.webViewLink)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 text-xs font-bold transition-all flex items-center gap-1">
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

export async function promptCreateGdriveFolder() {
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

export async function syncGdriveToBrain() {
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
            fetchMemory();
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

export async function uploadDirectToGdrive() {
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


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.deleteGdriveCredentials = deleteGdriveCredentials;
window.fetchGdriveFiles = fetchGdriveFiles;
window.fetchGdriveStatus = fetchGdriveStatus;
window.gdriveOauthLogout = gdriveOauthLogout;
window.handleGdriveFileSelect = handleGdriveFileSelect;
window.handleGdriveOauthSecretUpload = handleGdriveOauthSecretUpload;
window.promptCreateGdriveFolder = promptCreateGdriveFolder;
window.saveAllWaSettings = saveAllWaSettings;
window.saveGdriveCredentials = saveGdriveCredentials;
window.startGdriveOauth = startGdriveOauth;
window.syncGdriveToBrain = syncGdriveToBrain;
window.uploadDirectToGdrive = uploadDirectToGdrive;
