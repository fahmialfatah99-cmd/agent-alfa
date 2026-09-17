/**
 * ==============================================================================
 * ALFA COMMAND CENTER - SYSTEM TELEMETRY & METRICS MODULE (telemetry.js)
 * ==============================================================================
 * Manages Chart.js real-time CPU & RAM metrics, hardware gauge DOM updates,
 * background telemetry polling, service status badges, and WebSocket live monitors.
 */

// Global Chart instance and sliding history buffer
let telemetryChart = null;
let telemetryTimer = null;

const chartHistory = {
    labels: Array(15).fill(''),
    cpu: Array(15).fill(0),
    ram: Array(15).fill(0)
};

/**
 * Initialize Chart.js hardware telemetry chart.
 */
function initTelemetryChart() {
    const canvas = document.getElementById('telemetryChart');
    if (!canvas || !window.Chart) return null;

    // Destroy existing chart if re-initializing
    if (telemetryChart) {
        try { telemetryChart.destroy(); } catch (e) {}
    }

    const ctx = canvas.getContext('2d');
    telemetryChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartHistory.labels,
            datasets: [
                {
                    label: 'CPU (%)',
                    data: chartHistory.cpu,
                    borderColor: '#06B6D4',
                    backgroundColor: 'rgba(6, 182, 212, 0.12)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0
                },
                {
                    label: 'RAM (%)',
                    data: chartHistory.ram,
                    borderColor: '#8B5CF6',
                    backgroundColor: 'rgba(139, 92, 246, 0.12)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#64748B', font: { family: 'JetBrains Mono', size: 10 } }
                },
                x: {
                    grid: { display: false },
                    ticks: { display: false }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });

    return telemetryChart;
}

/**
 * Apply telemetry data payload to UI gauges, charts, and service status badges.
 */
function applyTelemetryData(data) {
    if (!data) return;

    // 1. CPU Metrics
    if (data.cpu) {
        const cpuPct = document.getElementById('stat-cpu-pct');
        if (cpuPct) cpuPct.innerText = `${data.cpu.percent}%`;
        const cpuCores = document.getElementById('stat-cpu-cores');
        if (cpuCores) cpuCores.innerText = `${data.cpu.cores} Cores (${data.cpu.freq_mhz} MHz)`;
        const cpuBar = document.getElementById('stat-cpu-bar');
        if (cpuBar) cpuBar.style.width = `${data.cpu.percent}%`;
    }

    // 2. RAM Metrics
    if (data.ram) {
        const ramPct = document.getElementById('stat-ram-pct');
        if (ramPct) ramPct.innerText = `${data.ram.percent}%`;
        const ramUsed = document.getElementById('stat-ram-used');
        if (ramUsed) ramUsed.innerText = `${data.ram.used_gb} / ${data.ram.total_gb} GB`;
        const ramBar = document.getElementById('stat-ram-bar');
        if (ramBar) ramBar.style.width = `${data.ram.percent}%`;
    }

    // 3. Disk Metrics
    if (data.disk) {
        const diskPct = document.getElementById('stat-disk-pct');
        if (diskPct) diskPct.innerText = `${data.disk.percent}%`;
        const diskUsed = document.getElementById('stat-disk-used');
        if (diskUsed) diskUsed.innerText = `${data.disk.used_gb} / ${data.disk.total_gb} GB`;
        const diskBar = document.getElementById('stat-disk-bar');
        if (diskBar) diskBar.style.width = `${data.disk.percent}%`;
    }

    // 4. Battery & Uptime
    if (data.battery) {
        const battPct = document.getElementById('stat-batt-pct');
        if (battPct) battPct.innerText = `${Math.round(data.battery.percent)}%`;
        const battStatus = document.getElementById('stat-batt-status');
        if (battStatus) battStatus.innerText = data.battery.status;
    }
    if (data.uptime) {
        const uptime = document.getElementById('stat-uptime');
        if (uptime) uptime.innerText = data.uptime;
    }

    // 5. Update Chart.js Buffer
    if (telemetryChart && data.cpu && data.ram) {
        chartHistory.cpu.shift();
        chartHistory.cpu.push(data.cpu.percent);
        chartHistory.ram.shift();
        chartHistory.ram.push(data.ram.percent);
        telemetryChart.update('none');
    }

    // 6. Update Services Badges
    if (data.services) {
        updateServiceBadge('tb-service', data.services.telegram_bot);
        updateServiceBadge('wa-service', data.services.wa_sheets_bot);
    }

    // 7. Update Top RAM Processes List
    const procBox = document.getElementById('top-processes-list');
    if (procBox && data.top_ram_processes && data.top_ram_processes.length > 0) {
        procBox.innerHTML = data.top_ram_processes.map(p => `
            <div class="flex items-center justify-between p-2.5 bg-dark-950 rounded-xl border border-white/5">
                <span class="text-slate-300 truncate text-[11px]">${p}</span>
                <span class="text-violet-400 text-[10px] font-bold">RAM</span>
            </div>
        `).join('');
    }

    // 8. Store in AlfaStore reactive store
    if (window.AlfaStore) {
        window.AlfaStore.stats = data;
    }
}

/**
 * Update a system service badge element (ACTIVE / STOPPED).
 */
function updateServiceBadge(prefix, isActive) {
    const dot = document.getElementById(`dot-${prefix}`);
    const badge = document.getElementById(`badge-${prefix}`);
    if (dot && badge) {
        if (isActive) {
            dot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 pulse-dot';
            badge.className = 'px-2 py-0.5 text-[10px] font-mono rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
            badge.innerText = 'ACTIVE';
        } else {
            dot.className = 'w-2.5 h-2.5 rounded-full bg-rose-400';
            badge.className = 'px-2 py-0.5 text-[10px] font-mono rounded bg-rose-500/10 text-rose-400 border border-rose-500/20';
            badge.innerText = 'STOPPED';
        }
    }
}

/**
 * Polling function: Fetch system statistics from /api/stats.
 */
async function fetchStats(isManual = false) {
    const icon = document.getElementById('refresh-icon');
    if (icon && isManual) icon.classList.add('animate-spin');

    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        if (data.status === 'success') {
            applyTelemetryData(data);
            if (isManual && typeof showToast === 'function') {
                showToast('Data telemetry diperbarui real-time', 'success');
            }
        }
    } catch (err) {
        console.error('Stats fetch error:', err);
    } finally {
        if (icon && isManual) {
            setTimeout(() => icon.classList.remove('animate-spin'), 500);
        }
    }
}

/**
 * Start periodic telemetry polling.
 */
function startTelemetryPolling(intervalMs = 2000) {
    stopTelemetryPolling();
    fetchStats();
    telemetryTimer = setInterval(fetchStats, intervalMs);
}

/**
 * Stop periodic telemetry polling.
 */
function stopTelemetryPolling() {
    if (telemetryTimer) {
        clearInterval(telemetryTimer);
        telemetryTimer = null;
    }
}

// ==================== GLOBAL & MODULE EXPORTS ====================

window.telemetryChart = telemetryChart;
window.chartHistory = chartHistory;
window.initTelemetryChart = initTelemetryChart;
window.applyTelemetryData = applyTelemetryData;
window.updateServiceBadge = updateServiceBadge;
window.fetchStats = fetchStats;
window.startTelemetryPolling = startTelemetryPolling;
window.stopTelemetryPolling = stopTelemetryPolling;

window.AlfaTelemetry = {
    chart: telemetryChart,
    history: chartHistory,
    initTelemetryChart,
    applyTelemetryData,
    updateServiceBadge,
    fetchStats,
    startTelemetryPolling,
    stopTelemetryPolling
};
