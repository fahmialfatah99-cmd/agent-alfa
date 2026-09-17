/* ==========================================================================
   ALFA DASHBOARD — Live AI Chat Engine & SSE EventSource Streaming
   ========================================================================== */
// ==================== MULTIMODAL LIVE AI CONSOLE CONTROLLER ====================
let attachedChatFiles = [];

async function clearWebChatHistory() {
    if (!confirm('Apakah kamu yakin ingin menghapus seluruh riwayat percakapan dari layar dan database memori?')) return;
    try {
        const res = await fetch('/api/chat/history', { method: 'DELETE' });
        const data = await res.json();
        const box = document.getElementById('chat-messages-box');
        if (box) {
            box.innerHTML = `
                <div class="p-3.5 bg-dark-900 border border-white/5 rounded-xl text-slate-300 leading-relaxed">
                    <span class="text-cyan-400 font-bold font-mono">ALFA:</span> Riwayat percakapan berhasil dihapus dari memori &amp; layar. Silakan ajukan tugas atau unggah berkas baru! 🚀
                </div>
            `;
        }
        showToast(data.message || 'Riwayat chat berhasil dibersihkan!', 'success');
    } catch (err) {
        showToast('Gagal menghapus riwayat: ' + err.message, 'error');
    }
}

function handleChatFilesSelected(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    processIncomingChatFiles(files);
    e.target.value = '';
}

function processIncomingChatFiles(files) {
    files.forEach(file => {
        if (file.size > 50 * 1024 * 1024) {
            showToast(`File ${file.name} terlalu besar (>50MB).`, 'warning');
            return;
        }
        const relPath = file.webkitRelativePath || file.name;
        const isFolderItem = relPath && relPath.includes('/');
        const reader = new FileReader();
        const isImage = file.type.startsWith('image/');
        reader.onload = (event) => {
            attachedChatFiles.push({
                name: relPath,
                fileName: file.name,
                type: file.type || 'application/octet-stream',
                size: file.size,
                base64: event.target.result,
                isImage: isImage,
                isFolderItem: isFolderItem
            });
            renderChatAttachmentsPreview();
        };
        reader.readAsDataURL(file);
    });
}

function renderChatAttachmentsPreview() {
    const tray = document.getElementById('chat-attachments-preview');
    if (!tray) return;
    if (!attachedChatFiles.length) {
        tray.classList.add('hidden');
        tray.innerHTML = '';
        return;
    }
    tray.classList.remove('hidden');
    tray.innerHTML = attachedChatFiles.map((f, idx) => {
        const sizeKB = (f.size / 1024).toFixed(1);
        if (f.isImage) {
            return `
                <div class="relative group flex items-center gap-2 p-1.5 bg-dark-950/80 border border-cyan-500/30 rounded-lg">
                    <img src="${f.base64}" class="w-10 h-10 object-cover rounded border border-white/10" alt="${f.name}">
                    <div class="max-w-[140px] truncate text-[11px] text-slate-300">
                        <p class="truncate font-mono" title="${f.name}">${f.name}</p>
                        <span class="text-[10px] text-slate-500">${sizeKB} KB</span>
                    </div>
                    <button type="button" onclick="removeChatAttachment(${idx})" class="p-1 text-slate-400 hover:text-rose-400 rounded-full hover:bg-rose-500/10 transition-all" title="Hapus lampiran">
                        <i data-lucide="x" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
        } else if (f.isFolderItem) {
            return `
                <div class="flex items-center gap-2 p-2 bg-dark-950/80 border border-amber-500/40 rounded-lg text-[11px] text-slate-300">
                    <div class="w-8 h-8 rounded bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 flex-shrink-0">
                        <i data-lucide="folder" class="w-4 h-4"></i>
                    </div>
                    <div class="max-w-[160px] truncate">
                        <p class="truncate font-mono font-medium text-amber-200" title="${f.name}">${f.name}</p>
                        <span class="text-[10px] text-slate-400">${sizeKB} KB</span>
                    </div>
                    <button type="button" onclick="removeChatAttachment(${idx})" class="p-1 text-slate-400 hover:text-rose-400 rounded-full hover:bg-rose-500/10 transition-all" title="Hapus berkas folder">
                        <i data-lucide="x" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
        } else {
            return `
                <div class="flex items-center gap-2 p-2 bg-dark-950/80 border border-cyan-500/30 rounded-lg text-[11px] text-slate-300">
                    <div class="w-8 h-8 rounded bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 flex-shrink-0">
                        <i data-lucide="file-text" class="w-4 h-4"></i>
                    </div>
                    <div class="max-w-[150px] truncate">
                        <p class="truncate font-mono font-medium" title="${f.name}">${f.name}</p>
                        <span class="text-[10px] text-slate-500">${sizeKB} KB</span>
                    </div>
                    <button type="button" onclick="removeChatAttachment(${idx})" class="p-1 text-slate-400 hover:text-rose-400 rounded-full hover:bg-rose-500/10 transition-all" title="Hapus lampiran">
                        <i data-lucide="x" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            `;
        }
    }).join('');
    lucide.createIcons();
}

function removeChatAttachment(index) {
    attachedChatFiles.splice(index, 1);
    renderChatAttachmentsPreview();
}

// ==================== DYNAMIC AI MODEL SELECTOR CONTROLLER ====================
async function loadChatAvailableModels() {
    const selector = document.getElementById('chat-model-selector');
    if (!selector) return;
    try {
        const res = await fetch('/api/chat/models');
        const data = await res.json();
        if (data.status === 'success' && data.models && data.models.length > 0) {
            const groups = {};
            data.models.forEach(m => {
                const prov = m.provider || 'Other';
                if (!groups[prov]) groups[prov] = [];
                groups[prov].push(m);
            });

            let matchedActive = false;
            let html = '';
            for (const [provName, mList] of Object.entries(groups)) {
                html += `<optgroup label="── ${provName} ──" class="bg-dark-950 text-slate-300 font-bold">`;
                mList.forEach(m => {
                    let isSelected = '';
                    if (!matchedActive) {
                        if (data.active_key_id && m.key_id && String(m.key_id) === String(data.active_key_id) && m.id === data.active_model) {
                            isSelected = 'selected';
                            matchedActive = true;
                        } else if (!data.active_key_id && m.id === data.active_model) {
                            isSelected = 'selected';
                            matchedActive = true;
                        }
                    }
                    html += `<option value="${m.id}" data-key-id="${m.key_id || ''}" ${isSelected} class="bg-dark-900 text-white font-normal">${m.name}</option>`;
                });
                html += `</optgroup>`;
            }
            selector.innerHTML = html;

            if (!matchedActive && data.active_model) {
                for (let i = 0; i < selector.options.length; i++) {
                    if (selector.options[i].value === data.active_model) {
                        selector.selectedIndex = i;
                        break;
                    }
                }
            }
        } else {
            selector.innerHTML = '<option value="gemini-3.6-flash">Gemini 3.6 Flash (Default)</option>';
        }
    } catch (err) {
        selector.innerHTML = '<option value="gemini-3.6-flash">Gemini 3.6 Flash (Default)</option>';
    }
}

async function onChatModelChanged(selectEl) {
    const selectedOpt = selectEl.options[selectEl.selectedIndex];
    const modelId = selectEl.value;
    const keyId = selectedOpt ? selectedOpt.getAttribute('data-key-id') : null;
    try {
        const res = await fetch('/api/chat/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId, key_id: keyId })
        });
        const data = await res.json();
        showToast(`Model AI aktif dialihkan ke: ${selectedOpt.text.replace(/^[✨🌐⚡]\s*/, '')}`, 'success');
    } catch (err) {
        showToast(`Gagal mengubah model: ${err.message}`, 'error');
    }
}

// ==================== ADVANCED CHAT ENGINE (NEXT-GEN EDITION) ====================
let currentExpertMode = 'general';
let lastUserMessage = '';
let lastUserFiles = [];
let speechRecognition = null;
let isRecordingVoice = false;

// Auto-grow textarea smoothly as user types
function autoGrowChatInput(textarea) {
    if (!textarea) return;
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 150);
    textarea.style.height = (newHeight > 36 ? newHeight : 36) + 'px';
}

// Handle Enter to send, Shift+Enter for newline
function handleChatKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const form = document.getElementById('chat-form');
        if (form) form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    } else if (e.key === 'Escape') {
        const popover = document.getElementById('chat-slash-popover');
        if (popover) popover.classList.add('hidden');
    }
}

// Handle slash command popover
function handleSlashCommandInput(textarea) {
    const popover = document.getElementById('chat-slash-popover');
    if (!popover) return;
    const val = textarea.value;
    if (val.startsWith('/') && val.length <= 4) {
        popover.classList.remove('hidden');
    } else {
        popover.classList.add('hidden');
    }
}

function insertSlashCommand(cmd) {
    const input = document.getElementById('chat-input-text');
    const popover = document.getElementById('chat-slash-popover');
    if (input) {
        input.value = cmd;
        input.focus();
        autoGrowChatInput(input);
    }
    if (popover) popover.classList.add('hidden');
}

// Switch Expert Persona Mode
function setChatExpertMode(mode) {
    currentExpertMode = mode;
    document.querySelectorAll('.chat-mode-pill').forEach(pill => {
        pill.classList.remove('bg-cyan-500/20', 'text-cyan-300', 'border-cyan-500/30', 'font-bold');
        pill.classList.add('text-slate-400');
    });
    const activeBtn = document.getElementById(`mode-btn-${mode}`);
    if (activeBtn) {
        activeBtn.classList.remove('text-slate-400');
        activeBtn.classList.add('bg-cyan-500/20', 'text-cyan-300', 'border-cyan-500/30', 'font-bold');
    }
    const modeLabels = {
        'general': 'Super Agent (130+ Tools)',
        'swarm': 'Autonomous Multi-Agent Swarm Orchestrator',
        'coder': 'Senior Software Architect',
        'researcher': 'Deep Web & Academic Researcher',
        'data': 'Data Analyst & PDF Maestro'
    };
    showToast(`Mode Spesialis aktif: ${modeLabels[mode] || mode}`, 'info');
}

// Speech-to-Text Voice Recording (Web Speech API)
function toggleVoiceRecording() {
    const micBtn = document.getElementById('chat-mic-btn');
    const micLabel = document.getElementById('chat-mic-label');
    const input = document.getElementById('chat-input-text');

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
        showToast('Browser ini belum mendukung Web Speech API. Disarankan menggunakan Google Chrome, Edge, atau Safari.', 'warning');
        return;
    }

    if (isRecordingVoice) {
        if (speechRecognition) {
            try { speechRecognition.stop(); } catch (e) {}
        }
        isRecordingVoice = false;
        if (micBtn) micBtn.classList.remove('bg-rose-500/20', 'text-rose-400', 'border-rose-500/40');
        if (micLabel) micLabel.innerText = 'Suara';
        showToast('Perekaman suara dihentikan.', 'info');
        return;
    }

    try {
        speechRecognition = new SpeechRec();
        speechRecognition.continuous = false;
        speechRecognition.interimResults = true;
        speechRecognition.lang = 'id-ID'; // Bahasa Indonesia

        speechRecognition.onstart = () => {
            isRecordingVoice = true;
            if (micBtn) micBtn.classList.add('bg-rose-500/20', 'text-rose-400', 'border-rose-500/40');
            if (micLabel) micLabel.innerText = 'Mendengarkan...';
            showToast('🎙️ Mikrofon aktif. Silakan bicara sekarang...', 'info');
        };

        speechRecognition.onresult = (event) => {
            let transcript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                transcript += event.results[i][0].transcript;
            }
            if (input && transcript) {
                input.value = transcript;
                autoGrowChatInput(input);
            }
        };

        speechRecognition.onerror = (event) => {
            isRecordingVoice = false;
            if (micBtn) micBtn.classList.remove('bg-rose-500/20', 'text-rose-400', 'border-rose-500/40');
            if (micLabel) micLabel.innerText = 'Suara';

            const err = event.error;
            if (err === 'not-allowed' || err === 'service-not-allowed') {
                showToast('Izin mikrofon belum aktif. Izinkan akses mikrofon di pengaturan browser.', 'warning');
            } else if (err === 'no-speech') {
                showToast('Tidak ada suara terdeteksi. Silakan coba bicara kembali.', 'info');
            } else if (err === 'audio-capture') {
                showToast('Perangkat mikrofon tidak ditemukan atau sedang dipakai aplikasi lain.', 'error');
            } else {
                showToast(`Status suara: ${err}`, 'info');
            }
        };

        speechRecognition.onend = () => {
            isRecordingVoice = false;
            if (micBtn) micBtn.classList.remove('bg-rose-500/20', 'text-rose-400', 'border-rose-500/40');
            if (micLabel) micLabel.innerText = 'Suara';
        };

        speechRecognition.start();
    } catch (err) {
        console.error('Failed to start speech recognition:', err);
        showToast('Gagal mengaktifkan mikrofon: ' + err.message, 'error');
    }
}

// Text-to-Speech (Voice Readout with Natural Voice Selection)
function speakTextMessage(text) {
    if (!('speechSynthesis' in window)) {
        showToast('Browser Anda tidak mendukung Text-to-Speech.', 'warning');
        return;
    }
    try {
        window.speechSynthesis.cancel();
        if (!text || !text.trim()) {
            showToast('Tidak ada teks untuk dibacakan.', 'info');
            return;
        }

        // Clean markdown symbols, code blocks, URLs for natural pronunciation
        const cleanText = text
            .replace(/```[\s\S]*?```/g, ' [cuplikan kode] ')
            .replace(/`[^`]*`/g, ' ')
            .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
            .replace(/https?:\/\/\S+/g, ' ')
            .replace(/[#*`_\[\]\(\)>~|\\]/g, ' ')
            .replace(/\n+/g, '. ')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, 900);

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'id-ID';
        utterance.rate = 1.05;
        utterance.pitch = 1.0;

        // Pick best natural voice if available
        const voices = window.speechSynthesis.getVoices();
        const idVoice = voices.find(v => v.lang.startsWith('id') || v.name.toLowerCase().includes('indonesia'));
        if (idVoice) utterance.voice = idVoice;

        utterance.onstart = () => showToast('🔊 Membacakan jawaban AI...', 'info');
        utterance.onerror = (e) => console.warn('Speech synthesis error:', e);

        window.speechSynthesis.speak(utterance);
    } catch (err) {
        console.error('TTS error:', err);
        showToast('Gagal memutar audio: ' + err.message, 'error');
    }
}

// Copy Text with Toast
function copyTextMessage(text, btnEl = null) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Teks berhasil disalin ke clipboard! 📋', 'success');
        if (btnEl) {
            const origHtml = btnEl.innerHTML;
            btnEl.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-400"></i>';
            lucide.createIcons();
            setTimeout(() => { btnEl.innerHTML = origHtml; lucide.createIcons(); }, 1800);
        }
    }).catch(() => {
        showToast('Gagal menyalin teks.', 'error');
    });
}

// Export Conversation to Markdown or JSON
async function exportCurrentChat(format = 'markdown') {
    try {
        showToast('Menyiapkan berkas ekspor percakapan...', 'info');
        window.location.href = `/api/chat/export?format=${format}`;
    } catch (err) {
        showToast('Gagal mengekspor: ' + err.message, 'error');
    }
}

// Enhance Interactive Code Blocks inside AI Messages
function enhanceCodeBlocks(container) {
    if (!container) return;
    const pres = container.querySelectorAll('pre');
    pres.forEach((pre, idx) => {
        if (pre.dataset.enhanced) return;
        pre.dataset.enhanced = 'true';

        const codeEl = pre.querySelector('code');
        const rawCode = codeEl ? codeEl.innerText : pre.innerText;
        const classList = codeEl ? codeEl.className : '';
        const matchLang = classList.match(/language-([a-zA-Z0-9_\-]+)/);
        let lang = matchLang ? matchLang[1] : 'code';

        // Detect language if not specified
        if (lang === 'code') {
            if (rawCode.includes('import ') || rawCode.includes('def ') || rawCode.includes('print(')) lang = 'python';
            else if (rawCode.includes('const ') || rawCode.includes('function ') || rawCode.includes('=>')) lang = 'javascript';
            else if (rawCode.includes('curl ') || rawCode.includes('grep ') || rawCode.includes('systemctl')) lang = 'bash';
            else if (rawCode.includes('<html') || rawCode.includes('<div')) lang = 'html';
        }

        const blockId = 'code-blk-' + Date.now() + '-' + idx;
        const outputId = blockId + '-out';

        const isExecutable = ['python', 'py', 'bash', 'sh', 'shell', 'javascript', 'js', 'node'].includes(lang.toLowerCase());
        const isHtml = ['html', 'svg'].includes(lang.toLowerCase());

        const wrapper = document.createElement('div');
        wrapper.className = 'my-3 rounded-xl border border-white/10 overflow-hidden shadow-lg bg-dark-950';

        const topBar = document.createElement('div');
        topBar.className = 'flex items-center justify-between px-3.5 py-1.5 bg-dark-900 border-b border-white/10 text-xs font-mono';
        topBar.innerHTML = `
            <span class="text-cyan-400 font-bold uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                <i data-lucide="code" class="w-3.5 h-3.5 text-cyan-400"></i> ${lang}
            </span>
            <div class="flex items-center gap-2">
                ${isExecutable ? `
                    <button type="button" onclick="executeInteractiveCode(this, '${blockId}', '${lang}', '${outputId}')" class="px-2.5 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 text-[11px] font-bold transition-all flex items-center gap-1 cursor-pointer">
                        <i data-lucide="play" class="w-3 h-3 text-emerald-400"></i> Jalankan Sandbox
                    </button>
                ` : ''}
                <button type="button" onclick="copyCodeSnippet(this, '${blockId}')" class="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-[11px] transition-all flex items-center gap-1 cursor-pointer">
                    <i data-lucide="copy" class="w-3 h-3"></i> Salin
                </button>
            </div>
        `;

        pre.id = blockId;
        pre.className = 'p-3.5 overflow-x-auto custom-scrollbar font-mono text-[12px] text-slate-200 bg-black/40 m-0';

        wrapper.appendChild(topBar);
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);

        if (isExecutable) {
            const outDrawer = document.createElement('div');
            outDrawer.id = outputId;
            outDrawer.className = 'hidden p-3 bg-black/80 border-t border-white/10 font-mono text-[11px] text-emerald-300 space-y-1';
            wrapper.appendChild(outDrawer);
        }
    });
    lucide.createIcons();
}

// Copy Code Helper
function copyCodeSnippet(btn, preId) {
    const pre = document.getElementById(preId);
    if (!pre) return;
    navigator.clipboard.writeText(pre.innerText).then(() => {
        showToast('Kode berhasil disalin!', 'success');
        const orig = btn.innerHTML;
        btn.innerHTML = '<i data-lucide="check" class="w-3 h-3 text-emerald-400"></i> Disalin!';
        lucide.createIcons();
        setTimeout(() => { btn.innerHTML = orig; lucide.createIcons(); }, 1800);
    });
}

// Execute Code in Native Python/Bash Sandbox from Chat
async function executeInteractiveCode(btn, preId, lang, outputId) {
    const pre = document.getElementById(preId);
    const drawer = document.getElementById(outputId);
    if (!pre || !drawer) return;

    const codeEl = pre.querySelector('code');
    const codeText = (codeEl ? codeEl.innerText : pre.innerText).trim();
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-3 h-3 animate-spin text-emerald-400"></i> Menjalankan...';
    lucide.createIcons();

    drawer.classList.remove('hidden');
    drawer.innerHTML = `
        <div class="flex items-center gap-2 text-slate-400 animate-pulse">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span>Mengeksekusi di Sandbox Sovereign ALFA...</span>
        </div>
    `;

    try {
        const res = await fetch('/api/chat/execute-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: codeText, language: lang })
        });
        const data = await res.json();
        btn.disabled = false;
        btn.innerHTML = origHtml;
        lucide.createIcons();

        const execResult = data.result || {};
        const isSuccess = data.status === 'success' && execResult.status !== 'error' && (execResult.exit_code === 0 || execResult.exit_code === undefined);
        let outputContent = execResult.stdout || execResult.output || execResult.result || '';
        if (execResult.stderr) {
            outputContent = (outputContent ? outputContent + '\n\n' : '') + `[STDERR]: ${execResult.stderr}`;
        }
        if (!outputContent && typeof execResult === 'object') {
            outputContent = JSON.stringify(execResult, null, 2);
        }

        drawer.innerHTML = `
            <div class="flex items-center justify-between pb-1 mb-1 border-b border-white/10 text-[10px] text-slate-400">
                <span class="flex items-center gap-1 font-bold ${isSuccess ? 'text-emerald-400' : 'text-rose-400'}">
                    <i data-lucide="${isSuccess ? 'check-circle' : 'alert-triangle'}" class="w-3 h-3"></i>
                    ${isSuccess ? 'Eksekusi Berhasil' : 'Eksekusi Error'}
                </span>
                <span class="text-slate-400">⏱️ ${data.execution_time_ms} ms</span>
            </div>
            <pre class="whitespace-pre-wrap font-mono text-[11px] ${isSuccess ? 'text-slate-200' : 'text-rose-300'} max-h-60 overflow-y-auto custom-scrollbar">${outputContent || '(Tanpa output terminal)'}</pre>
        `;
        lucide.createIcons();
        showToast(`Eksekusi selesai dalam ${data.execution_time_ms} ms!`, isSuccess ? 'success' : 'error');
    } catch (err) {
        btn.disabled = false;
        btn.innerHTML = origHtml;
        drawer.innerHTML = `<span class="text-rose-400">❌ Error: ${err.message}</span>`;
        lucide.createIcons();
        showToast('Gagal menjalankan sandbox: ' + err.message, 'error');
    }
}

// Live Chat AI with Multimodal Payload, Expert Modes & Next-Gen Streaming Display
async function sendWebChat(e) {
    e.preventDefault();
    const input = document.getElementById('chat-input-text');
    const msg = input.value.trim();
    const currentFiles = [...attachedChatFiles];

    const modelSelector = document.getElementById('chat-model-selector');
    const selectedModel = modelSelector ? modelSelector.value : '';
    const selectedOpt = modelSelector && modelSelector.selectedIndex >= 0 ? modelSelector.options[modelSelector.selectedIndex] : null;
    const selectedKeyId = selectedOpt ? selectedOpt.getAttribute('data-key-id') : null;
    const modelDisplayName = selectedOpt ? selectedOpt.text.replace(/^[✨🌐⚡]\s*/, '') : 'Gemini';

    if (!msg && currentFiles.length === 0) return;

    // Hide welcome hero on first message
    const welcomeCard = document.getElementById('chat-welcome-card');
    if (welcomeCard) welcomeCard.style.display = 'none';

    lastUserMessage = msg;
    lastUserFiles = [...currentFiles];

    const box = document.getElementById('chat-messages-box');
    const nowTime = new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });

    // Build visual attachments for user bubble
    let attachmentsHTML = '';
    if (currentFiles.length > 0) {
        attachmentsHTML = `
            <div class="flex flex-wrap justify-end gap-2 my-2">
                ${currentFiles.map(f => {
                    if (f.isImage) {
                        return `<img src="${f.base64}" class="max-w-[220px] max-h-[150px] object-cover rounded-xl border border-cyan-500/40 shadow-lg cursor-pointer hover:opacity-95 transition-all" onclick="openMediaPreviewModal('${f.name}', '${f.base64}', 'image')">`;
                    } else {
                        return `
                            <div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-900/50 border border-cyan-500/30 text-[11px] text-cyan-200 font-mono shadow-sm">
                                <i data-lucide="paperclip" class="w-3.5 h-3.5 text-cyan-400"></i>
                                <span class="max-w-[160px] truncate">${f.name}</span>
                            </div>
                        `;
                    }
                }).join('')}
            </div>
        `;
    }

    // USER CHAT BUBBLE
    box.innerHTML += `
        <div class="flex justify-end items-start gap-2.5 my-2">
            <div class="max-w-[85%] sm:max-w-xl p-3.5 rounded-2xl bg-gradient-to-r from-cyan-600 to-blue-700 text-white shadow-md space-y-1">
                <div class="flex items-center justify-between gap-3 text-[10px] text-cyan-200 font-mono">
                    <span class="font-bold">Fahmi</span>
                    <span>${nowTime}</span>
                </div>
                ${msg ? `<div class="text-xs sm:text-[13px] leading-relaxed whitespace-pre-wrap">${msg}</div>` : ''}
                ${attachmentsHTML}
            </div>
            <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold font-mono text-xs flex-shrink-0 shadow-md">
                F
            </div>
        </div>
    `;

    input.value = '';
    autoGrowChatInput(input);
    attachedChatFiles = [];
    renderChatAttachmentsPreview();
    box.scrollTop = box.scrollHeight;

    const sendBtn = document.getElementById('chat-send-btn');
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i>';
    lucide.createIcons();

    // Check if message is a /swarm command or expert mode is swarm
    let isSwarmCmd = false;
    let cleanMsg = msg;
    if (msg.startsWith('/swarm ') || msg === '/swarm') {
        isSwarmCmd = true;
        cleanMsg = msg.replace(/^\/swarm\s*/, '').trim();
        if (!cleanMsg) cleanMsg = 'Orkestrasi dan eksekusi tugas tim swarm secara otonom.';
    }
    const isSwarmMode = currentExpertMode === 'swarm' || isSwarmCmd;
    const effectiveExpertMode = isSwarmMode ? 'swarm' : currentExpertMode;

    // PENDING AGENT REASONING STEPPER
    const pendingId = 'chat-pending-' + Date.now();
    const startTime = Date.now();

    box.innerHTML += `
        <div id="${pendingId}" class="p-4 bg-dark-900 border ${isSwarmMode ? 'border-amber-500/40' : 'border-cyan-500/40'} rounded-xl space-y-3 font-sans text-xs relative overflow-hidden w-full">
            <div class="flex items-center justify-between border-b border-white/10 pb-2.5">
                <div class="flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full ${isSwarmMode ? 'bg-amber-400' : 'bg-cyan-400'} animate-ping"></span>
                    <span class="font-mono font-bold ${isSwarmMode ? 'text-amber-400' : 'text-cyan-400'} flex items-center gap-1.5">
                        <i data-lucide="${isSwarmMode ? 'users' : 'cpu'}" class="w-3.5 h-3.5"></i> ${isSwarmMode ? 'SWARM ORCHESTRATOR //' : ''} ${modelDisplayName}
                    </span>
                </div>
                <div class="flex items-center gap-2 font-mono text-[11px]">
                    <span id="${pendingId}-timer" class="px-2 py-0.5 rounded bg-dark-950 border border-white/10 text-cyan-300 font-bold">0.0s</span>
                    <span class="px-1.5 py-0.5 rounded ${isSwarmMode ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'} text-[10px] font-bold">${isSwarmMode ? 'SWARM EXECUTING' : 'REASONING'}</span>
                </div>
            </div>

            <div class="space-y-2 py-1 font-mono text-[11px]">
                <div id="${pendingId}-step1" class="flex items-center gap-2 ${isSwarmMode ? 'text-amber-300' : 'text-cyan-300'} font-medium">
                    <i data-lucide="check-circle-2" class="w-3.5 h-3.5 ${isSwarmMode ? 'text-amber-400' : 'text-cyan-400'}"></i>
                    <span>${isSwarmMode ? '1. Mempersiapkan tim agen swarm & menganalisis tugas...' : '1. Menyiapkan konteks & memvalidasi berkas...'}</span>
                </div>
                <div id="${pendingId}-step2" class="flex items-center gap-2 text-slate-300">
                    <i id="${pendingId}-step2-icon" data-lucide="loader" class="w-3.5 h-3.5 animate-spin text-amber-400"></i>
                    <span id="${pendingId}-step2-text">${isSwarmMode ? '2. Mengorkestrasi sub-agen & mengeksekusi tools otonom...' : '2. Memanggil engine AI & mengeksekusi tools otonom...'}</span>
                </div>
                <div id="${pendingId}-step3" class="flex items-center gap-2 text-slate-500">
                    <i id="${pendingId}-step3-icon" data-lucide="circle-dashed" class="w-3.5 h-3.5"></i>
                    <span id="${pendingId}-step3-text">${isSwarmMode ? '3. Menggabungkan hasil eksekusi tim ke laporan final...' : '3. Memformat respon & menyusun artefak...'}</span>
                </div>
            </div>

            <div class="w-full bg-dark-950 rounded-full h-1.5 overflow-hidden border border-white/5">
                <div class="bg-gradient-to-r ${isSwarmMode ? 'from-amber-500 via-orange-500 to-emerald-400' : 'from-cyan-500 via-blue-500 to-emerald-400'} h-full w-2/3 animate-pulse rounded-full"></div>
            </div>
        </div>
    `;
    box.scrollTop = box.scrollHeight;
    lucide.createIcons();

    // Live stopwatch
    const timerInterval = setInterval(() => {
        const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);
        const timerEl = document.getElementById(`${pendingId}-timer`);
        if (timerEl) timerEl.innerText = `${elapsedSec}s`;

        if (elapsedSec > 1.2) {
            const s2Icon = document.getElementById(`${pendingId}-step2-icon`);
            const s3Icon = document.getElementById(`${pendingId}-step3-icon`);
            const s3Div = document.getElementById(`${pendingId}-step3`);
            if (s2Icon && s2Icon.getAttribute('data-lucide') === 'loader') {
                s2Icon.setAttribute('data-lucide', 'check-circle-2');
                s2Icon.classList.remove('animate-spin', 'text-amber-400');
                s2Icon.classList.add('text-cyan-400');
            }
            if (s3Div && s3Div.classList.contains('text-slate-500')) {
                s3Div.classList.remove('text-slate-500');
                s3Div.classList.add('text-slate-200');
                if (s3Icon) {
                    s3Icon.setAttribute('data-lucide', 'loader');
                    s3Icon.classList.add('animate-spin', 'text-cyan-400');
                }
            }
            lucide.createIcons();
        }
    }, 100);

    try {
        // Prepend Expert Persona Instruction if set
        let finalPrompt = cleanMsg;
        const personaPrefixes = {
            'swarm': '[MODE SPESIALIS: AUTONOMOUS MULTI-AGENT SWARM ORCHESTRATOR. Anda memimpin tim agen cerdas otonom ALFA. Analisis kebutuhan tugas ini, susun strategi terperinci, lalu delegasikan dan gunakan tools sistem (file writing, web search, sandbox testing, dan visual tools) untuk mengeksekusi seluruh hasil secara tuntas, mandiri, dan terverifikasi.]\n\n',
            'coder': '[MODE SPESIALIS: SENIOR SOFTWARE ARCHITECT. Buat kode rapi, robust, gunakan sandbox bila perlu, dan jelaskan langkah teknis secara presisi.]\n\n',
            'researcher': '[MODE SPESIALIS: DEEP ACADEMIC & WEB RESEARCHER. Lakukan riset menyeluruh, gunakan web search / arXiv, berikan fakta konkret dan sitasi jelas.]\n\n',
            'data': '[MODE SPESIALIS: DATA ANALYST & PDF MAESTRO. Fokus pada analisis data, visualisasi, dan pemrosesan berkas PDF/Excel secara deterministik.]\n\n'
        };
        if (effectiveExpertMode !== 'general' && personaPrefixes[effectiveExpertMode]) {
            finalPrompt = personaPrefixes[effectiveExpertMode] + finalPrompt;
        }

        const res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: finalPrompt,
                attachments: currentFiles,
                selected_model: selectedModel,
                key_id: selectedKeyId,
                expert_mode: effectiveExpertMode
            })
        });

        if (!res.ok) {
            throw new Error(`Server returned HTTP ${res.status}: ${res.statusText}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let streamedText = '';
        let bubbleWrapper = null;
        let responseId = null;
        let bodyEl = null;

        function ensureBubbleWrapper(customModel) {
            if (!bubbleWrapper) {
                clearInterval(timerInterval);
                document.getElementById(pendingId)?.remove();
                bubbleWrapper = document.createElement('div');
                bubbleWrapper.className = "flex justify-start items-start gap-2.5 my-3 w-full";
                responseId = 'ai-resp-' + Date.now();
                const activeDisplayName = customModel || modelDisplayName;
                bubbleWrapper.innerHTML = `
                    <div class="w-8 h-8 rounded-xl bg-cyan-700 flex items-center justify-center text-white font-black font-mono text-xs flex-shrink-0">α</div>
                    <div class="flex-1 min-w-0 space-y-2 w-full">
                        <div id="${responseId}" class="p-4 sm:p-5 rounded-xl bg-dark-900 border border-white/10 text-slate-100 leading-relaxed space-y-2 w-full">
                            <div class="flex items-center justify-between pb-2 mb-2 border-b border-white/10 text-[11px] font-mono text-slate-400">
                                <span class="text-cyan-400 font-bold flex items-center gap-1.5"><i data-lucide="bot" class="w-3.5 h-3.5"></i> ALFA // ${activeDisplayName}</span>
                                <span id="${responseId}-elapsed" class="text-slate-400 font-mono">⚡ Mengetik...</span>
                            </div>
                            <div id="${responseId}-body" class="prose prose-invert max-w-none text-xs sm:text-[13px] space-y-2 leading-relaxed">
                                <span class="animate-pulse text-cyan-300">●</span>
                            </div>
                        </div>
                        <div id="${responseId}-toolbar" class="flex items-center gap-2 text-[11px] font-mono text-slate-400 pl-1 hidden">
                            <button type="button" class="btn-speak px-2 py-1 rounded-lg hover:bg-white/5 hover:text-cyan-300 transition-all flex items-center gap-1" title="Dengarkan Suara (Text to Speech)"><i data-lucide="volume-2" class="w-3.5 h-3.5 text-cyan-400"></i> Suara</button>
                            <button type="button" class="btn-copy px-2 py-1 rounded-lg hover:bg-white/5 hover:text-cyan-300 transition-all flex items-center gap-1" title="Salin Seluruh Jawaban"><i data-lucide="copy" class="w-3.5 h-3.5"></i> Salin</button>
                            <button type="button" onclick="regenerateLastTurn()" class="px-2 py-1 rounded-lg hover:bg-white/5 hover:text-cyan-300 transition-all flex items-center gap-1" title="Generate Ulang Jawaban"><i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i> Ulang</button>
                        </div>
                    </div>
                `;
                box.appendChild(bubbleWrapper);
                bodyEl = document.getElementById(`${responseId}-body`);
                lucide.createIcons();
            }
            return bodyEl;
        }

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // keep partial

            for (const block of lines) {
                if (!block.trim()) continue;
                const line = block.trim();
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'progress') {
                            const s2Text = document.getElementById(`${pendingId}-step2-text`);
                            if (s2Text) s2Text.innerText = data.step;
                        } else if (data.type === 'start') {
                            ensureBubbleWrapper(data.model);
                        } else if (data.type === 'token') {
                            ensureBubbleWrapper();
                            streamedText += data.chunk;
                            if (bodyEl) {
                                bodyEl.innerHTML = marked.parse(streamedText);
                                box.scrollTop = box.scrollHeight;
                            }
                        } else if (data.type === 'done') {
                            ensureBubbleWrapper(data.model_used);
                            clearInterval(timerInterval);
                            document.getElementById(pendingId)?.remove();
                            const finalSec = data.execution_time_ms ? (data.execution_time_ms / 1000).toFixed(2) : ((Date.now() - startTime) / 1000).toFixed(2);
                            const elBadge = document.getElementById(`${responseId}-elapsed`);
                            if (elBadge) elBadge.innerText = `⚡ ${finalSec}s`;

                            const finalReply = streamedText.trim() || data.reply || '';
                            if (bodyEl && finalReply) {
                                bodyEl.innerHTML = marked.parse(finalReply);
                            }

                            const toolbar = document.getElementById(`${responseId}-toolbar`);
                            if (toolbar) {
                                toolbar.classList.remove('hidden');
                                const spkBtn = toolbar.querySelector('.btn-speak');
                                const cpyBtn = toolbar.querySelector('.btn-copy');
                                const textToCopy = finalReply;
                                if (spkBtn) spkBtn.onclick = () => speakTextMessage(textToCopy);
                                if (cpyBtn) cpyBtn.onclick = function() { copyTextMessage(textToCopy, this); };
                            }
                            if (bubbleWrapper) {
                                enhanceCodeBlocks(bubbleWrapper);
                                decorateArtifactCards(bubbleWrapper);
                            }
                            lucide.createIcons();
                            box.scrollTop = box.scrollHeight;
                        } else if (data.type === 'error') {
                            throw new Error(data.message || 'Error dalam streaming jawaban.');
                        }
                    } catch (parseErr) {
                        console.warn('Stream chunk parse error:', parseErr);
                    }
                }
            }
        }
    } catch (err) {
        clearInterval(timerInterval);
        document.getElementById(pendingId)?.remove();
        box.innerHTML += `
            <div class="p-4 bg-rose-950/40 border border-rose-500/40 rounded-xl text-rose-300 space-y-1 shadow-sm max-w-xl">
                <div class="flex items-center gap-2 font-bold font-mono text-xs">
                    <i data-lucide="alert-triangle" class="w-4 h-4 text-rose-400"></i> Gagal Memproses Permintaan
                </div>
                <p class="text-xs">${err.message}</p>
            </div>
        `;
    } finally {
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i data-lucide="send" class="w-3.5 h-3.5"></i> <span>Kirim</span>';
        box.scrollTop = box.scrollHeight;
        lucide.createIcons();
    }
}

// Start New Clean Chat Session
function startNewChatSession() {
    const box = document.getElementById('chat-messages-box');
    if (box) {
        box.innerHTML = `
            <div id="chat-welcome-card" class="p-5 rounded-xl bg-dark-900 border border-cyan-500/30 text-slate-200 space-y-3">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 flex items-center justify-center font-bold font-mono text-lg">
                        🚀
                    </div>
                    <div>
                        <h4 class="text-sm font-bold text-white font-mono">Sesi Obrolan Baru Dimulai</h4>
                        <p class="text-xs text-slate-400">Silakan ajukan tugas baru, jalankan script di sandbox, atau lampirkan berkas!</p>
                    </div>
                </div>
            </div>
        `;
    }
    document.getElementById('chat-input-text').value = '';
    attachedChatFiles = [];
    renderChatAttachmentsPreview();
    showToast('Sesi obrolan baru siap! 🌟', 'info');
    lucide.createIcons();
}

// Regenerate Last Turn
function regenerateLastTurn() {
    if (!lastUserMessage && lastUserFiles.length === 0) {
        showToast('Tidak ada pesan sebelumnya untuk diulang.', 'info');
        return;
    }
    document.getElementById('chat-input-text').value = lastUserMessage;
    attachedChatFiles = [...lastUserFiles];
    renderChatAttachmentsPreview();
    document.getElementById('chat-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
}

function sendPresetChat(text) {
    document.getElementById('chat-input-text').value = text;
    autoGrowChatInput(document.getElementById('chat-input-text'));
    document.getElementById('chat-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
}


// Global Drag & Drop and Clipboard Paste Initializer for Live AI Console
document.addEventListener("DOMContentLoaded", () => {
    const dropzone = document.getElementById("chat-dropzone-container");
    const chatInput = document.getElementById("chat-input-text");

    if (dropzone) {
        ["dragenter", "dragover"].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("border-cyan-500", "shadow-glow-cyan");
            }, false);
        });

        ["dragleave", "drop"].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("border-cyan-500", "shadow-glow-cyan");
            }, false);
        });

        dropzone.addEventListener("drop", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove("border-cyan-500", "shadow-glow-cyan");
            const dt = e.dataTransfer;
            if (!dt) return;

            const allFiles = [];
            if (dt.items && dt.items.length) {
                const entries = [];
                for (let i = 0; i < dt.items.length; i++) {
                    const item = dt.items[i];
                    if (item.webkitGetAsEntry) {
                        const entry = item.webkitGetAsEntry();
                        if (entry) entries.push(entry);
                    }
                }

                async function readEntry(entry, path = "") {
                    if (entry.isFile) {
                        return new Promise((resolve) => {
                            entry.file((file) => {
                                Object.defineProperty(file, "webkitRelativePath", {
                                    value: path ? `${path}/${file.name}` : file.name,
                                    writable: true
                                });
                                allFiles.push(file);
                                resolve();
                            }, () => resolve());
                        });
                    } else if (entry.isDirectory) {
                        const dirReader = entry.createReader();
                        return new Promise((resolve) => {
                            dirReader.readEntries(async (subEntries) => {
                                const subPath = path ? `${path}/${entry.name}` : entry.name;
                                for (const sub of subEntries) {
                                    await readEntry(sub, subPath);
                                }
                                resolve();
                            }, () => resolve());
                        });
                    }
                }

                if (entries.length) {
                    for (const ent of entries) {
                        await readEntry(ent);
                    }
                }
            }

            if (!allFiles.length && dt.files && dt.files.length) {
                for (let i = 0; i < dt.files.length; i++) {
                    allFiles.push(dt.files[i]);
                }
            }

            if (allFiles.length) {
                processIncomingChatFiles(allFiles);
                if (typeof showToast === "function") showToast(`${allFiles.length} berkas/folder berhasil dilampirkan ke chat!`, "success");
            }
        }, false);
    }

    if (chatInput) {
        chatInput.addEventListener("paste", (e) => {
            const items = (e.clipboardData || window.clipboardData).items;
            const pastedFiles = [];
            for (let i = 0; i < items.length; i++) {
                if (items[i].kind === "file") {
                    const file = items[i].getAsFile();
                    if (file) pastedFiles.push(file);
                }
            }
            if (pastedFiles.length) {
                processIncomingChatFiles(pastedFiles);
                if (typeof showToast === "function") showToast("Gambar / file berhasil ditempel dari clipboard!", "info");
            }
        });
    }

    // Load available models for Chat Agent on init
    loadChatAvailableModels();
});

