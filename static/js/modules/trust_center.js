/* ==== ES MODULE BRIDGE ==== */
import { escHtml } from './state.js';

/**
 * Trust Center & Observability (P2) — read-only panel.
 *
 * Mengonsumsi endpoint read-only:
 *   /api/v1/trust/summary, /evidence, /capabilities, /tasks, /skills
 * Tidak ada mutasi; semua fetch same-origin (cookie sesi otomatis).
 */

const ENDPOINTS = {
    summary: '/api/v1/trust/summary',
    evidence: '/api/v1/trust/evidence',
    capabilities: '/api/v1/trust/capabilities',
    tasks: '/api/v1/trust/tasks',
    skills: '/api/v1/trust/skills',
};

function _el(id) {
    return document.getElementById(id);
}

function _setHTML(id, html) {
    const node = _el(id);
    if (node) node.innerHTML = html;
}

function _num(value) {
    return new Intl.NumberFormat('id-ID').format(Number(value) || 0);
}

function _short(text, limit = 72) {
    const str = String(text ?? '').replace(/\s+/g, ' ').trim();
    return str.length > limit ? str.slice(0, limit - 1) + '…' : str;
}

const TONE_CLASS = {
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    rose: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    cyan: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
    violet: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    slate: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
};

const TONE_TEXT = {
    emerald: 'text-emerald-300',
    amber: 'text-amber-300',
    rose: 'text-rose-300',
    cyan: 'text-cyan-300',
    violet: 'text-violet-300',
    slate: 'text-slate-300',
};

function _badge(value, tone = 'slate') {
    const cls = TONE_CLASS[tone] || TONE_CLASS.slate;
    return `<span class="text-[10px] px-2 py-0.5 rounded-full border font-bold ${cls}">${escHtml(value)}</span>`;
}

function _statusTone(status) {
    const key = String(status || '').toLowerCase();
    if (key.includes('success') || key.includes('ok') || key === 'completed') return 'emerald';
    if (key.includes('preview') || key.includes('shadow')) return 'amber';
    if (key.includes('fail') || key.includes('error') || key.includes('deny')) return 'rose';
    return 'slate';
}

function _emptyRow(cols, text = 'Belum ada data.') {
    return `<tr><td colspan="${cols}" class="px-3 py-4 text-center text-slate-500">${escHtml(text)}</td></tr>`;
}

async function _fetchJSON(url) {
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (res.status === 401) {
        throw new Error('Sesi dashboard tidak valid. Login ulang untuk melihat Trust Center.');
    }
    if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
    }
    return res.json();
}

function _card(label, value, hint, tone = 'cyan') {
    const textCls = TONE_TEXT[tone] || TONE_TEXT.cyan;
    return `
        <div class="p-4 rounded-xl bg-dark-950 border border-white/5 space-y-1">
            <div class="text-[10px] uppercase tracking-wider text-slate-500 font-bold">${escHtml(label)}</div>
            <div class="text-2xl font-bold ${textCls} font-mono">${escHtml(value)}</div>
            <div class="text-[10px] text-slate-500">${escHtml(hint || '')}</div>
        </div>`;
}

function _renderSummary(summary) {
    const evidence = (summary && summary.evidence) || {};
    const governor = (summary && summary.context_governor) || {};
    const cards = [
        _card('Evidence Total', _num(evidence.total), `${_num(evidence.recent)} dalam ${_num(evidence.hours)} jam`),
        _card('Path Unik', _num(evidence.unique_paths), `retensi ${_num(evidence.retention_days)} hari`, 'violet'),
        _card('Evidence Mode', String(summary?.evidence_mode || evidence.mode || '-'), 'ledger deterministik', 'emerald'),
        _card('Context Saved', _num(governor.last_saved_chars), `${_num(governor.compactions)} kompaksi`, 'amber'),
    ];
    _setHTML('trust-summary-cards', cards.join(''));

    const statuses = evidence.by_status && typeof evidence.by_status === 'object'
        ? Object.entries(evidence.by_status)
        : [];
    _setHTML(
        'trust-status-body',
        statuses.length
            ? statuses.map(([status, count]) => `
                <tr class="border-b border-white/5">
                    <td class="px-3 py-2">${_badge(status, _statusTone(status))}</td>
                    <td class="px-3 py-2 text-right font-mono text-slate-200">${_num(count)}</td>
                </tr>`).join('')
            : _emptyRow(2)
    );

    const tools = Array.isArray(evidence.top_tools) ? evidence.top_tools : [];
    _setHTML(
        'trust-tools-list',
        tools.length
            ? tools.map((item, idx) => `
                <div class="flex items-center justify-between gap-2 py-1.5 border-b border-white/5 last:border-0">
                    <span class="text-slate-300 truncate"><span class="text-slate-500 font-mono mr-1">${idx + 1}.</span>${escHtml(item.tool)}</span>
                    <span class="font-mono text-cyan-300">${_num(item.count)}×</span>
                </div>`).join('')
            : '<div class="text-slate-500 py-2">Belum ada tool terekam.</div>'
    );

    _setHTML(
        'trust-context-body',
        [
            ['Mode', governor.mode || '-'],
            ['Calls', _num(governor.calls)],
            ['Compactions', _num(governor.compactions)],
            ['Hard compactions', _num(governor.hard_compactions)],
            ['Last before', _num(governor.last_before_chars)],
            ['Last after', _num(governor.last_after_chars)],
            ['Last saved', _num(governor.last_saved_chars)],
            ['Last budget', _num(governor.last_budget)],
        ].map(([label, value]) => `
            <div class="flex items-center justify-between gap-2 py-1.5 border-b border-white/5 last:border-0">
                <span class="text-slate-400">${escHtml(label)}</span>
                <span class="font-mono text-slate-200">${escHtml(value)}</span>
            </div>`).join('')
    );
}

function _renderEvidence(payload) {
    const rows = Array.isArray(payload?.evidence) ? payload.evidence : [];
    _setHTML(
        'trust-evidence-body',
        rows.length
            ? rows.map((item) => `
                <tr class="border-b border-white/5 hover:bg-white/5">
                    <td class="px-3 py-2 text-slate-500 whitespace-nowrap">${escHtml(_short(item.created_at, 19))}</td>
                    <td class="px-3 py-2 font-mono text-slate-200">${escHtml(item.tool)}</td>
                    <td class="px-3 py-2">${_badge(item.status || '-', _statusTone(item.status))}</td>
                    <td class="px-3 py-2 text-slate-400 max-w-[22rem] truncate" title="${escHtml(item.path || '')}">${escHtml(_short(item.path || '(tanpa path)'))}</td>
                    <td class="px-3 py-2 font-mono text-[10px] text-slate-500">${escHtml(_short(item.turn_id || '-', 12))}</td>
                </tr>`).join('')
            : _emptyRow(5)
    );
}

function _renderCapabilities(payload) {
    const rows = Array.isArray(payload?.capabilities) ? payload.capabilities : [];
    _setHTML(
        'trust-capability-meta',
        `${_badge(`mode ${payload?.mode || '-'}`, payload?.mode === 'on' ? 'emerald' : 'amber')}
         ${_badge(`required ${payload?.required ? 'true' : 'false'}`, payload?.required ? 'rose' : 'slate')}
         ${_badge(`${_num(payload?.valid_count)} valid / ${_num(payload?.count)} total`, 'cyan')}`
    );
    _setHTML(
        'trust-capability-body',
        rows.length
            ? rows.map((item) => {
                const maxUses = Number(item.max_uses) || 0;
                const uses = Number(item.uses) || 0;
                return `
                    <tr class="border-b border-white/5">
                        <td class="px-3 py-2 font-mono text-slate-200">${escHtml(item.tool_name)}</td>
                        <td class="px-3 py-2 font-mono text-[10px] text-slate-500">${escHtml(item.grant_id)}</td>
                        <td class="px-3 py-2 text-right font-mono">${uses}/${maxUses || '∞'}</td>
                        <td class="px-3 py-2 text-right">${_badge(item.valid ? 'valid' : (item.revoked ? 'revoked' : (item.expired ? 'expired' : 'exhausted')), item.valid ? 'emerald' : 'rose')}</td>
                    </tr>`;
            }).join('')
            : _emptyRow(4)
    );
}

function _renderTasks(payload) {
    const rows = Array.isArray(payload?.tasks) ? payload.tasks : [];
    _setHTML(
        'trust-task-meta',
        `${_badge(`mode ${payload?.mode || '-'}`, payload?.mode === 'on' ? 'emerald' : 'amber')}
         ${_badge(`${_num(payload?.count)} baris`, 'cyan')}`
    );
    _setHTML(
        'trust-task-body',
        rows.length
            ? rows.map((item) => `
                <tr class="border-b border-white/5">
                    <td class="px-3 py-2 font-mono text-[10px] text-slate-500">${escHtml(_short(item.task_id, 12))}</td>
                    <td class="px-3 py-2">${_badge(item.status || '-', _statusTone(item.status))}</td>
                    <td class="px-3 py-2 text-right font-mono">${_num(item.step_index)}</td>
                    <td class="px-3 py-2 text-slate-400 max-w-[20rem] truncate" title="${escHtml(item.prompt || '')}">${escHtml(_short(item.prompt || ''))}</td>
                </tr>`).join('')
            : _emptyRow(4)
    );
}

function _renderSkills(payload) {
    const rows = Array.isArray(payload?.skills) ? payload.skills : [];
    _setHTML(
        'trust-skill-meta',
        `${_badge(`mode ${payload?.mode || '-'}`, payload?.mode === 'on' ? 'emerald' : 'amber')}
         ${_badge(`${_num(payload?.count)} workflow`, 'violet')}`
    );
    _setHTML(
        'trust-skill-body',
        rows.length
            ? rows.map((item) => `
                <tr class="border-b border-white/5">
                    <td class="px-3 py-2 text-slate-200 max-w-[20rem] truncate" title="${escHtml(item.name || '')}">${escHtml(item.name || '-')}</td>
                    <td class="px-3 py-2">${_badge(item.active ? 'active' : 'shadow', item.active ? 'emerald' : 'amber')}</td>
                    <td class="px-3 py-2 text-right font-mono">${_num(item.support_count)}×</td>
                    <td class="px-3 py-2 text-right font-mono text-slate-500">${_num(item.hit_count)}</td>
                </tr>`).join('')
            : _emptyRow(4)
    );
}

function _showError(message) {
    _setHTML(
        'trust-error',
        `<div class="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">${escHtml(message)}</div>`
    );
}

function _clearError() {
    _setHTML('trust-error', '');
}

/**
 * Muat seluruh data Trust Center. Aman dipanggil berulang.
 */
export async function fetchTrustCenter() {
    const hours = Number(_el('trust-hours')?.value || 24);
    const summaryUrl = `${ENDPOINTS.summary}?hours=${encodeURIComponent(hours)}&top_tools=10`;
    _clearError();
    _setHTML('trust-loading', '<span class="text-cyan-300">Memuat Trust Center…</span>');

    const results = await Promise.allSettled([
        _fetchJSON(summaryUrl),
        _fetchJSON(`${ENDPOINTS.evidence}?limit=50`),
        _fetchJSON(ENDPOINTS.capabilities),
        _fetchJSON(ENDPOINTS.tasks),
        _fetchJSON(ENDPOINTS.skills),
    ]);
    const [summaryR, evidenceR, capabilityR, taskR, skillR] = results;

    if (summaryR.status === 'fulfilled') {
        _renderSummary(summaryR.value);
    } else {
        _showError(summaryR.reason?.message || 'Gagal memuat ringkasan Trust.');
    }
    if (evidenceR.status === 'fulfilled') _renderEvidence(evidenceR.value);
    if (capabilityR.status === 'fulfilled') _renderCapabilities(capabilityR.value);
    if (taskR.status === 'fulfilled') _renderTasks(taskR.value);
    if (skillR.status === 'fulfilled') _renderSkills(skillR.value);

    const failed = results.filter((item) => item.status === 'rejected');
    if (failed.length && summaryR.status === 'fulfilled') {
        _showError(
            `${failed.length} panel Trust gagal dimuat. Periksa sesi/login atau log dashboard.`
        );
    }
    _setHTML('trust-loading', '');
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

window.fetchTrustCenter = fetchTrustCenter;
