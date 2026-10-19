
/* ==== ES MODULE BRIDGE ==== */
import { escAttr, escHtml, showToast, switchTab } from './state.js';
// ==================== MASTER SCRAPER PRO JS ====================
let currentScraperCategory = 'all_marketplace';
let currentScraperData = [];

export function switchScraperSubTab(sub) {
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

export function setModernPreset(presetKey, selectorValue, labelText) {
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

export function fillModernSampleUrl(url, selector) {
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

export async function runModernScraperLab(e) {
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

export function copyModernScraperOutput() {
    if (!modernScraperLastResult) return;
    navigator.clipboard.writeText(modernScraperLastResult);
    showToast('Hasil scraping berhasil disalin ke clipboard!', 'info');
}

export function downloadModernScraperOutput() {
    if (!modernScraperLastResult) return;
    const blob = new Blob([modernScraperLastResult], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ALFA_Scrape_${Date.now()}.md`;
    a.click();
    showToast('File hasil scraping (.md) diunduh!', 'success');
}

export function setScraperCategory(cat) {
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

export async function runUniversalScraper(e) {
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
                <div class="font-bold text-white font-sans text-xs line-clamp-1">${escHtml(it.title)}</div>
                <div class="text-[10px] text-slate-400 font-sans line-clamp-1 mt-0.5">${escHtml(it.snippet || '-')}</div>
            </td>
            <td class="p-3">
                <span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[11px] font-mono border border-emerald-500/20 font-bold whitespace-nowrap">
                    ${escHtml(it.price || 'N/A')}
                </span>
            </td>
            <td class="p-3">
                <span class="px-2 py-0.5 rounded bg-dark-900 text-slate-300 text-[10px] font-mono border border-white/5">
                    ${escHtml(it.domain || 'web')}
                </span>
            </td>
            <td class="p-3 font-mono text-[11px]">
                ${it.phone_wa !== 'N/A' ? `<span class="text-cyan-400 block truncate">📱 ${escHtml(it.phone_wa)}</span>` : ''}
                ${it.email !== 'N/A' ? `<span class="text-amber-300 block truncate">✉️ ${escHtml(it.email)}</span>` : ''}
                ${it.phone_wa === 'N/A' && it.email === 'N/A' ? '<span class="text-slate-600">-</span>' : ''}
            </td>
            <td class="p-3 text-right whitespace-nowrap space-x-1">
                <a href="${escAttr(it.url)}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 rounded bg-white/5 hover:bg-orange-500/20 text-slate-300 hover:text-orange-300 text-[10px] font-mono inline-flex items-center gap-1 transition-all">
                    <i data-lucide="external-link" class="w-3 h-3"></i> Buka
                </a>
                <button onclick="sendItemToAffiliate('${String(it.title || '').replace(/'/g, "\\'")}', '${escAttr(it.price || '')}', '${escAttr(it.url || '')}')" title="Kirim ke Affiliate War Room" class="px-2 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 text-[10px] font-mono inline-flex items-center gap-1 transition-all">
                    <i data-lucide="shopping-bag" class="w-3 h-3"></i> Buat Naskah
                </button>
            </td>
        </tr>
    `).join('');
    lucide.createIcons();
}

export function filterScraperTable() {
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

export function sendItemToAffiliate(title, price, url) {
    switchTab('affiliate');
    const nameInput = document.getElementById('aff-product-name') || document.getElementById('affiliate-product-name');
    const priceInput = document.getElementById('aff-disc-price') || document.getElementById('affiliate-price-drop');
    const urlInput = document.getElementById('aff-link') || document.getElementById('affiliate-product-url');
    if (nameInput) nameInput.value = title || '';
    if (priceInput) priceInput.value = price || '';
    if (urlInput) urlInput.value = url || '';
    showToast(`Data produk '${(title || '').slice(0, 30)}...' dikirim ke Affiliate War Room!`, 'info');
}

export async function runCustomUrlScraper(e) {
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

export async function fetchScraperBatches() {
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


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.copyModernScraperOutput = copyModernScraperOutput;
window.downloadModernScraperOutput = downloadModernScraperOutput;
window.fetchScraperBatches = fetchScraperBatches;
window.fillModernSampleUrl = fillModernSampleUrl;
window.filterScraperTable = filterScraperTable;
window.runCustomUrlScraper = runCustomUrlScraper;
window.runModernScraperLab = runModernScraperLab;
window.runUniversalScraper = runUniversalScraper;
window.sendItemToAffiliate = sendItemToAffiliate;
window.setModernPreset = setModernPreset;
window.setScraperCategory = setScraperCategory;
window.switchScraperSubTab = switchScraperSubTab;
