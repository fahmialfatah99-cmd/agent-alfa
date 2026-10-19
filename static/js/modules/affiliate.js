
/* ==== ES MODULE BRIDGE ==== */
import { escHtml, showToast } from './state.js';
// ==================== AFFILIATE SALES SWARM FUNCTIONS ====================
let currentAffiliateCampaign = null;
let latestScrapedProducts = [];

// Live Scraper Integration
export async function runLiveProductScrape(e) {
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
                                <span class="text-cyan-400 uppercase font-bold">${escHtml(p.platform)}</span>
                                <span class="text-amber-400 font-bold">⭐ ${escHtml(p.rating || 4.9)}</span>
                            </div>
                            <h4 class="text-xs font-semibold text-white line-clamp-2">${escHtml(p.title)}</h4>
                            <div class="text-xs font-mono font-bold text-emerald-400">${escHtml(p.price)}</div>
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

export function selectScrapedProduct(idx) {
    const p = latestScrapedProducts[idx];
    if (!p) return;

    document.getElementById('aff-product-name').value = p.title;
    document.getElementById('aff-features').value = p.snippet ? p.snippet.replace(/\n/g, ' ') : 'Kualitas terjamin, rating tinggi bintang 5, diskon resmi';
    document.getElementById('aff-disc-price').value = p.price || 'Rp 49.000';
    document.getElementById('aff-orig-price').value = 'Rp 120.000';
    document.getElementById('aff-link').value = p.url || 'https://shopee.co.id';

    showToast(`Produk '${p.title.substring(0, 25)}...' dimuat ke generator!`, 'info');
}

export function setAffiliatePreset(type) {
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

export function switchAffTab(subTab) {
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

export function toggleVideoEngineConfig() {
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

export async function renderAffiliateVideoNow() {
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

export async function runAffiliateGenerator(e) {
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

export function copyAffiliateContent(elemId) {
    const el = document.getElementById(elemId);
    if (el) {
        const text = (el.value !== undefined && el.tagName && (el.tagName.toLowerCase() === 'textarea' || el.tagName.toLowerCase() === 'input')) ? el.value : (el.innerText || el.textContent || '');
        navigator.clipboard.writeText(text);
        showToast('Konten berhasil disalin ke clipboard!', 'success');
    }
}

export async function broadcastCurrentAffiliate(channel) {
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

export async function fetchAffiliateCampaigns() {
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
                <td class="p-3 font-semibold text-white">${escHtml(c.product_name)}</td>
                <td class="p-3 text-slate-300 uppercase text-[10px]">${escHtml(c.platform || 'shopee/tiktok')}</td>
                <td class="p-3 text-slate-400 truncate max-w-xs">${escHtml(c.target_audience || 'All Audience')}</td>
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

export async function loadCampaignDetail(cid) {
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


// ==== ES MODULE BRIDGE (global untuk handler inline HTML) ====
window.broadcastCurrentAffiliate = broadcastCurrentAffiliate;
window.copyAffiliateContent = copyAffiliateContent;
window.fetchAffiliateCampaigns = fetchAffiliateCampaigns;
window.loadCampaignDetail = loadCampaignDetail;
window.renderAffiliateVideoNow = renderAffiliateVideoNow;
window.runAffiliateGenerator = runAffiliateGenerator;
window.runLiveProductScrape = runLiveProductScrape;
window.selectScrapedProduct = selectScrapedProduct;
window.setAffiliatePreset = setAffiliatePreset;
window.switchAffTab = switchAffTab;
window.toggleVideoEngineConfig = toggleVideoEngineConfig;
