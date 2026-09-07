/* ==========================================================================
   ALFA DASHBOARD — Tools Arsenal, Parameter Modal & Runners
   ========================================================================== */

let allToolsData = [];
let activeCategory = all;
let currentModalTool = null;

/**
 * Audio Recorder & Player Helpers for Tools Execution
 */
class ToolAudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
    }

    async start() {
        this.audioChunks = [];
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.mediaRecorder = new MediaRecorder(stream);
        this.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) this.audioChunks.push(e.data);
        };
        this.mediaRecorder.start();
        this.isRecording = true;
    }

    async stop() {
        return new Promise((resolve, reject) => {
            if (!this.mediaRecorder || !this.isRecording) {
                return reject(new Error("AudioRecorder not recording"));
            }
            this.mediaRecorder.onstop = () => {
                const audioBlob = new Blob(this.audioChunks, { type: "audio/webm" });
                this.isRecording = false;
                resolve(audioBlob);
            };
            this.mediaRecorder.stop();
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
        });
    }
}
window.ToolAudioRecorder = ToolAudioRecorder;

function playToolAudio(audioUrl) {
    if (!audioUrl) return;
    const audio = new Audio(audioUrl);
    audio.play().catch(e => {
        console.warn("Tool audio playback failed:", e);
        if (typeof showToast === "function") showToast("Gagal memutar audio: " + e.message, "error");
    });
    return audio;
}
window.playToolAudio = playToolAudio;

// Tools Arsenal
async function fetchTools() {
    try {
        const res = await fetch('/api/tools');
        const data = await res.json();
        if (data.status === 'success') {
            allToolsData = data.tools;
            document.getElementById('nav-tools-badge').innerText = data.total_tools;
            document.getElementById('tool-count-pill').innerText = `${data.total_tools} Tools`;
            renderCategories();
            renderToolsList();
        }
    } catch (err) {
        showToast(`Gagal memuat tools: ${err.message}`, 'error');
    }
}

function renderCategories() {
    const cats = ['all', ...new Set(allToolsData.map(t => t.category))];
    const container = document.getElementById('tool-category-pills');
    container.innerHTML = cats.map(c => `
        <button onclick="setCategory('${c}')" class="px-3 py-1 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${activeCategory === c ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm' : 'bg-dark-950 text-slate-400 hover:text-white border border-white/5'}">
            ${c === 'all' ? `Semua (${allToolsData.length})` : c}
        </button>
    `).join('');
}

function setCategory(cat) {
    activeCategory = cat;
    const labelEl = document.getElementById('active-cat-name');
    if (labelEl) labelEl.innerText = cat === 'all' ? 'Semua' : cat;
    renderCategories();
    filterTools();
}

function filterTools() {
    const query = document.getElementById('tool-search-input').value.toLowerCase();
    const filtered = allToolsData.filter(t => {
        const matchCat = activeCategory === 'all' || t.category === activeCategory;
        const matchQuery = t.name.toLowerCase().includes(query) || t.short_description.toLowerCase().includes(query);
        return matchCat && matchQuery;
    });
    document.getElementById('tool-count-pill').innerText = `${filtered.length} Tools`;
    renderToolsList(filtered);
}

function renderToolsList(toolsToRender = allToolsData) {
    const grid = document.getElementById('tools-grid');
    if (toolsToRender.length === 0) {
        grid.innerHTML = '<div class="text-slate-500 text-center py-12 col-span-full font-mono text-xs">Tidak ada tool yang cocok.</div>';
        return;
    }
    grid.innerHTML = toolsToRender.map(t => `
        <div class="glass-card p-5 rounded-2xl flex flex-col justify-between space-y-4 hover:shadow-glow-cyan group">
            <div>
                <div class="flex items-start justify-between gap-2 mb-2">
                    <span class="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-white/5 text-cyan-400 border border-cyan-500/20">
                        ${t.category}
                    </span>
                    <span class="text-[11px] font-mono text-slate-400">${t.parameters.length} params</span>
                </div>
                <h3 class="text-xs font-bold text-white font-mono group-hover:text-cyan-300 transition-colors">${t.name}()</h3>
                <p class="text-[11px] text-slate-400 mt-1 line-clamp-2 leading-relaxed">${t.short_description}</p>
            </div>
            <button onclick="openToolModal('${t.name}')" class="w-full py-2.5 bg-dark-950 hover:bg-cyan-500/20 text-slate-300 hover:text-cyan-300 border border-white/5 hover:border-cyan-500/30 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all">
                <i data-lucide="play" class="w-3.5 h-3.5"></i> Test / Jalankan Tool
            </button>
        </div>
    `).join('');
    lucide.createIcons();
}

// Tool Modal Runner
function openToolModal(toolName) {
    currentModalTool = allToolsData.find(t => t.name === toolName);
    if (!currentModalTool) {
        showToast(`Membuka tool: ${toolName}...`, 'info');
        return;
    }

    document.getElementById('modal-tool-name').innerText = `${currentModalTool.name}()`;
    document.getElementById('modal-tool-desc').innerHTML = `
        <div class="space-y-1">
            <div>${currentModalTool.full_docstring}</div>
            <div class="text-[11px] font-mono text-cyan-400/90 pt-1 border-t border-white/5 flex items-center gap-1.5">
                <i data-lucide="folder" class="w-3.5 h-3.5"></i> Output otomatis disimpan rapi di: <span class="text-emerald-300 font-bold">~/Dokumen/ALFA_PDF_TOOLS/</span>
            </div>
        </div>
    `;
    document.getElementById('modal-result-box').classList.add('hidden');
    const dlBox = document.getElementById('modal-file-download-box');
    if (dlBox) dlBox.classList.add('hidden');

    const paramsBox = document.getElementById('modal-params-container');
    if (currentModalTool.parameters.length === 0) {
        paramsBox.innerHTML = '<div class="text-slate-400 italic">Tool ini tidak memerlukan parameter input. Langsung klik eksekusi di bawah.</div>';
    } else {
        paramsBox.innerHTML = currentModalTool.parameters.map(p => {
            const isFileParam = ['pdf_path', 'pdf_paths', 'image_paths', 'source_file', 'file_path', 'document_path', 'input_pdf'].includes(p.name) || p.name.includes('path') || p.name.includes('file');
            const isMultiple = p.name.includes('paths') || p.name.includes('files') || p.type.includes('List');
            const acceptType = p.name.includes('image') ? 'image/*' : (p.name.includes('pdf') ? '.pdf,application/pdf' : '*');

            if (isFileParam) {
                return `
                    <div class="space-y-1.5 p-3 rounded-xl bg-dark-950/90 border border-cyan-500/20">
                        <div class="flex items-center justify-between">
                            <label class="block font-semibold text-slate-200 font-mono text-[11px]">
                                ${p.name} <span class="text-slate-500">(${p.type})</span> ${p.required ? '<span class="text-rose-400">*</span>' : ''}
                            </label>
                            <span class="text-[10px] font-mono text-cyan-400 flex items-center gap-1">
                                <i data-lucide="hard-drive" class="w-3 h-3"></i> Pilih dari Komputer
                            </span>
                        </div>
                        <div class="flex items-center gap-2">
                            <input type="text" id="param-${p.name}" value="${p.default !== 'None' && p.default !== null ? p.default.replace(/['"]/g, '') : ''}" placeholder="${isMultiple ? 'Klik Pilih Files atau ketik path...' : 'Klik Pilih File atau ketik path...'}" class="flex-1 p-2.5 bg-dark-900 border border-white/10 rounded-xl text-white focus:outline-none focus:border-cyan-500 font-mono text-xs">
                            <label class="cursor-pointer px-3.5 py-2.5 bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 text-cyan-300 border border-cyan-500/40 rounded-xl text-xs font-semibold font-mono flex items-center gap-1.5 whitespace-nowrap transition-all shadow-sm">
                                <i data-lucide="upload" class="w-3.5 h-3.5"></i> ${isMultiple ? 'Pilih Files' : 'Pilih File'}
                                <input type="file" ${isMultiple ? 'multiple' : ''} onchange="handleToolFileUpload(event, 'param-${p.name}', ${isMultiple})" class="hidden" accept="${acceptType}">
                            </label>
                        </div>
                        <div id="file-badge-param-${p.name}" class="text-[10px] font-mono text-slate-400"></div>
                    </div>
                `;
            }

            return `
                <div class="space-y-1">
                    <label class="block font-semibold text-slate-300 font-mono text-[11px]">${p.name} <span class="text-slate-500">(${p.type})</span> ${p.required ? '<span class="text-rose-400">*</span>' : ''}</label>
                    <input type="text" id="param-${p.name}" value="${p.default !== 'None' && p.default !== null ? p.default.replace(/['"]/g, '') : ''}" placeholder="${p.name} (${p.type})" class="w-full p-2.5 bg-dark-950 border border-white/10 rounded-xl text-white focus:outline-none focus:border-cyan-500 font-mono text-xs">
                </div>
            `;
        }).join('');
    }

    document.getElementById('tool-modal').classList.remove('hidden');
    document.getElementById('tool-modal').classList.add('flex');
    lucide.createIcons();
}

async function handleToolFileUpload(e, inputId, isMultiple) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const badgeEl = document.getElementById(`file-badge-${inputId}`);
    if (badgeEl) badgeEl.innerHTML = `<span class="text-cyan-400 animate-pulse font-mono">⏳ Mengunggah ${files.length} file ke server...</span>`;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    try {
        const res = await fetch('/api/tools/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.status === 'success') {
            const inputEl = document.getElementById(inputId);
            if (isMultiple) {
                inputEl.value = data.all_file_paths.join(', ');
            } else {
                inputEl.value = data.primary_file_path;
            }
            if (badgeEl) {
                const names = data.files.map(f => `${f.filename} (${f.size_kb} KB)`).join(', ');
                badgeEl.innerHTML = `<span class="text-emerald-400 font-mono flex items-center gap-1">✓ Siap: ${names}</span>`;
            }
            showToast(`Berhasil upload ${data.files.length} file!`, 'success');
        } else {
            if (badgeEl) badgeEl.innerHTML = `<span class="text-rose-400 font-mono">Gagal upload: ${data.message}</span>`;
            showToast(`Upload gagal: ${data.message}`, 'error');
        }
    } catch (err) {
        if (badgeEl) badgeEl.innerHTML = `<span class="text-rose-400 font-mono">Error: ${err.message}</span>`;
        showToast(`Upload error: ${err.message}`, 'error');
    }
}

function closeToolModal() {
    document.getElementById('tool-modal').classList.add('hidden');
    document.getElementById('tool-modal').classList.remove('flex');
}

async function executeModalTool(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!currentModalTool) return;
    const btn = document.getElementById('modal-run-btn');
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Menjalankan...';

    const args = {};
    currentModalTool.parameters.forEach(p => {
        const el = document.getElementById(`param-${p.name}`);
        if (el && el.value.trim() !== '') {
            let val = el.value.trim();
            if (val === 'True' || val === 'true') val = true;
            else if (val === 'False' || val === 'false') val = false;
            else if (p.type.includes('List') || p.name.endsWith('paths') || p.name.endsWith('files')) {
                if (val.startsWith('[') && val.endsWith(']')) {
                    try { val = JSON.parse(val); } catch(_) { val = val.slice(1, -1).split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')); }
                } else {
                    val = val.split(',').map(s => s.trim().replace(/^['"]|['"]$/g, ''));
                }
            } else if (!isNaN(val) && val !== '' && !p.type.includes('str')) {
                val = Number(val);
            }
            args[p.name] = val;
        }
    });

    try {
        const res = await fetch('/api/tools/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_name: currentModalTool.name, args })
        });
        const data = await res.json();
        document.getElementById('modal-result-json').innerText = JSON.stringify(data, null, 2);
        document.getElementById('modal-duration-badge').innerText = `${data.duration_ms || 0}ms`;
        document.getElementById('modal-result-box').classList.remove('hidden');

        // Check for downloadable files
        const resObj = data.result || {};
        const filePath = resObj.file_path || (Array.isArray(resObj.files) && resObj.files.length > 0 ? resObj.files[0] : null);
        const dlBox = document.getElementById('modal-file-download-box');
        if (filePath && dlBox) {
            const dlLink = document.getElementById('modal-download-link');
            const dlName = document.getElementById('modal-download-filename');
            dlName.innerText = filePath.split('/').pop();
            dlLink.href = `/api/artifacts/download?path=${encodeURIComponent(filePath)}`;
            dlBox.classList.remove('hidden');
        }

        if (data.status === 'success') {
            showToast(`Tool ${currentModalTool.name} sukses dieksekusi!`, 'success');
        } else {
            showToast(`Tool gagal: ${data.message || 'Error'}`, 'error');
        }
    } catch (err) {
        document.getElementById('modal-result-json').innerText = `Error: ${err.message}`;
        document.getElementById('modal-result-box').classList.remove('hidden');
        showToast(`Eksekusi gagal: ${err.message}`, 'error');
    } finally {
        btn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i> Eksekusi Tool Sekarang';
        lucide.createIcons();
    }
}
