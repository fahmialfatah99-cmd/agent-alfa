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


// ==================== GALERI SITUS & KUOTA ====================
function _escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function fetchSites(isManual = false) {
    const grid = document.getElementById('sites-grid');
    try {
        const res = await fetch('/api/sites');
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.detail || 'gagal');
        const rows = data.sites || [];
        if (!rows.length) {
            grid.innerHTML = '<div class="text-slate-500 text-center py-12 col-span-full font-mono text-xs">Belum ada situs terdaftar.</div>';
            return;
        }
        grid.innerHTML = rows.map(s => {
            const on = s.backend_on || s.frontend_on;
            const dot = on ? 'bg-emerald-400' : 'bg-slate-500';
            const st = s.stack || {};
            const tags = [
                st.has_backend ? 'backend' : null,
                st.has_frontend ? 'frontend' : null,
                st.has_php ? 'php' : null,
                st.has_static ? 'statis' : null,
            ].filter(Boolean).join(' · ') || 'skrip';
            const ports = [s.backend_port ? `BE:${s.backend_port}` : null, s.frontend_port ? `FE:${s.frontend_port}` : null].filter(Boolean).join(' ');
            const runnable = st.has_backend || st.has_frontend || st.has_php;
            return `
                <div class="glass-card p-4 rounded-2xl flex flex-col justify-between space-y-3">
                    <div>
                        <div class="flex items-center gap-2 mb-2">
                            <span class="w-2 h-2 rounded-full ${dot}"></span>
                            <h4 class="text-xs font-bold text-white font-mono truncate" title="${_escHtml(s.slug)}">${_escHtml(s.title || s.slug)}</h4>
                        </div>
                        <p class="text-[10px] text-slate-500 font-mono">${_escHtml(s.category || '')} · ${tags} ${ports ? '· ' + ports : ''}</p>
                    </div>
                    ${runnable ? `
                    <div class="flex gap-2">
                        <button onclick="siteAction('${_escHtml(s.slug)}','start')" class="flex-1 py-2 min-h-[44px] bg-emerald-500/15 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 rounded-xl text-xs font-semibold transition-all">▶ Hidupkan</button>
                        <button onclick="siteAction('${_escHtml(s.slug)}','stop')" class="flex-1 py-2 min-h-[44px] bg-rose-500/15 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 rounded-xl text-xs font-semibold transition-all">⏹ Matikan</button>
                    </div>` : `
                    <p class="text-[10px] text-slate-500 font-mono">Proyek non-server — tanpa tombol start/stop.</p>`}
                </div>`;
        }).join('');
        lucide.createIcons();
    } catch (err) {
        grid.innerHTML = `<div class="text-rose-400 text-center py-6 col-span-full font-mono text-xs">Galeri error: ${_escHtml(err.message)}</div>`;
    }
}

async function siteAction(slug, action) {
    try {
        const res = await fetch(`/api/sites/${encodeURIComponent(slug)}/${action}`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'gagal');
        showToast(`Situs ${action === 'start' ? 'dihidupkan' : 'dimatikan'}: ${slug}`, 'success');
    } catch (err) {
        showToast(`Aksi situs gagal: ${err.message}`, 'error');
    }
    fetchSites();
}

async function fetchBudget(isManual = false) {
    const box = document.getElementById('budget-box');
    const bar = document.getElementById('budget-bar');
    try {
        const res = await fetch('/api/budget/today');
        const d = await res.json();
        if (d.status !== 'ok') throw new Error('data kosong');
        const pct = Math.min(100, (d.pct || 0) * 100);
        box.innerHTML = `Terpakai <b class="text-white">${Number(d.total_tokens || 0).toLocaleString('id-ID')}</b> / ${Number(d.budget_limit || 0).toLocaleString('id-ID')} token &nbsp;•&nbsp; sisa <b class="text-white">${Number(d.remaining || 0).toLocaleString('id-ID')}</b> &nbsp;•&nbsp; ${d.total_calls || 0} panggilan`;
        bar.style.width = pct + '%';
        bar.className = 'h-full rounded-full transition-all ' + (pct >= 100 ? 'bg-rose-500' : pct >= 80 ? 'bg-amber-400' : 'bg-cyan-500');
    } catch (err) {
        box.textContent = 'Kuota error: ' + err.message;
    }
}
