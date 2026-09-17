/**
 * ==============================================================================
 * ALFA COMMAND CENTER - AUDIO SUBSYSTEM MODULE (audio.js)
 * ==============================================================================
 * Manages Web Audio API context, UI sound effects synthesizer, real-time
 * audio visualizer (canvas oscilloscope/frequency bars), mic audio recorder,
 * and Text-to-Speech (TTS) natural voice playback.
 */

// Global AudioContext singleton
let audioCtx = null;
let hqSfxEnabled = true;
let hqSpeedMultiplier = 1; // 1, 1.5, 2, or 99 (instant)

/**
 * Lazily retrieve or create the active Web AudioContext.
 * Automatically resumes suspended audio contexts on user interaction.
 */
function getAudioContext() {
    if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) {
            audioCtx = new AudioContextClass();
        }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    return audioCtx;
}

// ==================== CYBER SYNTHESIZER SFX ====================

/**
 * Generate a short synthesized tone for cybernetic UI feedback.
 */
function playCyberBeep(freq = 600, type = 'sine', duration = 0.08, vol = 0.08) {
    if (!hqSfxEnabled) return;
    try {
        const ctx = getAudioContext();
        if (!ctx) return;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, ctx.currentTime);
        gain.gain.setValueAtTime(vol, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + duration);
    } catch (e) {
        // Audio playback may be restricted before user gesture
    }
}

/**
 * SFX for agent turn starting in swarm deliberation.
 */
function playTurnStartSfx() {
    playCyberBeep(520, 'sine', 0.06, 0.06);
    setTimeout(() => playCyberBeep(780, 'triangle', 0.12, 0.08), 60);
}

/**
 * SFX when swarm consensus or debate agreement is reached.
 */
function playConsensusSfx() {
    if (!hqSfxEnabled) return;
    [440, 554.37, 659.25, 880].forEach((freq, idx) => {
        setTimeout(() => playCyberBeep(freq, 'triangle', 0.3, 0.09), idx * 110);
    });
}

/**
 * Toggle HQ SFX sounds on or off.
 */
function toggleHqSfx() {
    hqSfxEnabled = !hqSfxEnabled;
    const sfxIcon = document.getElementById('sfx-icon');
    const sfxText = document.getElementById('sfx-text');
    if (sfxIcon) sfxIcon.innerText = hqSfxEnabled ? '🔊' : '🔇';
    if (sfxText) sfxText.innerText = hqSfxEnabled ? 'SFX ON' : 'SFX OFF';
    if (hqSfxEnabled) playCyberBeep(800, 'sine', 0.1, 0.08);
    if (typeof showToast === 'function') {
        showToast(`Suara Efek UI: ${hqSfxEnabled ? 'AKTIF' : 'NONAKTIF'}`, 'info');
    }
}

/**
 * Cycle simulation speed multiplier (1x, 1.5x, 2x, 99x).
 */
function cycleHqSpeed() {
    const speeds = [1, 1.5, 2, 99];
    const labels = { 1: '⚡ 1x', 1.5: '⚡ 1.5x', 2: '⚡ 2x', 99: '🚀 Kilat' };
    const currIdx = speeds.indexOf(hqSpeedMultiplier);
    const nextIdx = (currIdx + 1) % speeds.length;
    hqSpeedMultiplier = speeds[nextIdx];
    const speedEl = document.getElementById('hq-speed-text') || document.getElementById('hq-speed-btn');
    if (speedEl) speedEl.innerText = labels[hqSpeedMultiplier];
    playCyberBeep(650 + nextIdx * 80, 'sine', 0.05, 0.07);
    if (typeof showToast === 'function') {
        showToast(`Kecepatan Rapat: ${labels[hqSpeedMultiplier]}`, 'info');
    }
}

// ==================== REAL-TIME AUDIO VISUALIZER ====================

/**
 * Real-time Web Audio Visualizer class.
 * Connects an AnalyserNode to a canvas element and animates cybernetic neon waveforms.
 */
class AudioVisualizer {
    constructor(canvasEl) {
        this.canvas = typeof canvasEl === 'string' ? document.getElementById(canvasEl) : canvasEl;
        this.ctx2d = this.canvas ? this.canvas.getContext('2d') : null;
        this.analyser = null;
        this.sourceNode = null;
        this.animationId = null;
        this.dataArray = null;
        this.bufferLength = 0;
        this.mode = 'bars'; // 'bars' | 'oscilloscope'
    }

    /**
     * Connect a MediaStream (e.g. from getUserMedia) to the visualizer.
     */
    connectStream(mediaStream) {
        const actx = getAudioContext();
        if (!actx) return;
        this.analyser = actx.createAnalyser();
        this.analyser.fftSize = 128;
        this.bufferLength = this.analyser.frequencyBinCount;
        this.dataArray = new Uint8Array(this.bufferLength);

        this.sourceNode = actx.createMediaStreamSource(mediaStream);
        this.sourceNode.connect(this.analyser);
    }

    /**
     * Start animation loop on canvas.
     */
    start(mode = 'bars') {
        this.mode = mode;
        if (!this.canvas || !this.analyser) return;
        this.stop();
        this._draw();
    }

    /**
     * Stop drawing and clear canvas.
     */
    stop() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        if (this.ctx2d && this.canvas) {
            this.ctx2d.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
    }

    _draw() {
        if (!this.canvas || !this.ctx2d || !this.analyser) return;

        this.animationId = requestAnimationFrame(() => this._draw());

        const width = this.canvas.width;
        const height = this.canvas.height;
        this.ctx2d.clearRect(0, 0, width, height);

        if (this.mode === 'oscilloscope') {
            this.analyser.getByteTimeDomainData(this.dataArray);
            this.ctx2d.lineWidth = 2;
            this.ctx2d.strokeStyle = '#06B6D4'; // Cyber cyan
            this.ctx2d.beginPath();

            const sliceWidth = width * 1.0 / this.bufferLength;
            let x = 0;
            for (let i = 0; i < this.bufferLength; i++) {
                const v = this.dataArray[i] / 128.0;
                const y = v * height / 2;
                if (i === 0) {
                    this.ctx2d.moveTo(x, y);
                } else {
                    this.ctx2d.lineTo(x, y);
                }
                x += sliceWidth;
            }
            this.ctx2d.lineTo(width, height / 2);
            this.ctx2d.stroke();
        } else {
            // Frequency bars mode
            this.analyser.getByteFrequencyData(this.dataArray);
            const barWidth = (width / this.bufferLength) * 1.8;
            let x = 0;

            for (let i = 0; i < this.bufferLength; i++) {
                const barHeight = (this.dataArray[i] / 255) * height;
                const gradient = this.ctx2d.createLinearGradient(0, height, 0, 0);
                gradient.addColorStop(0, '#06B6D4'); // Cyan
                gradient.addColorStop(1, '#8B5CF6'); // Violet

                this.ctx2d.fillStyle = gradient;
                this.ctx2d.fillRect(x, height - barHeight, barWidth, barHeight);
                x += barWidth + 2;
            }
        }
    }
}

// ==================== TOOL AUDIO RECORDER & PLAYER ====================

/**
 * Helper class for recording audio blobs from microphone.
 */
window.ToolAudioRecorder = window.ToolAudioRecorder || class ToolAudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.stream = null;
    }

    async start() {
        this.audioChunks = [];
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.mediaRecorder = new MediaRecorder(this.stream);
        this.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) this.audioChunks.push(e.data);
        };
        this.mediaRecorder.start();
    }

    async stop() {
        return new Promise((resolve, reject) => {
            if (!this.mediaRecorder) {
                return reject(new Error("AudioRecorder not initialized"));
            }
            this.mediaRecorder.onstop = () => {
                if (this.stream) {
                    this.stream.getTracks().forEach(track => track.stop());
                }
                const audioBlob = new Blob(this.audioChunks, { type: "audio/webm" });
                resolve(audioBlob);
            };
            if (this.mediaRecorder.state !== "inactive") {
                this.mediaRecorder.stop();
            } else {
                reject(new Error("AudioRecorder not recording"));
            }
        });
    }
}

/**
 * Plays an audio file from URL with error handling and toast feedback.
 */
function playToolAudio(audioUrl) {
    if (!audioUrl) return null;
    const audio = new Audio(audioUrl);
    audio.play().catch(e => {
        console.warn("Tool audio playback failed:", e);
        if (typeof showToast === "function") {
            showToast("Gagal memutar audio: " + e.message, "error");
        }
    });
    return audio;
}

// ==================== TEXT-TO-SPEECH (TTS) PLAYBACK ====================

/**
 * Speaks a given text message using Web Speech Synthesis.
 * Automatically strips Markdown symbols, code snippets, and URLs.
 */
function speakTextMessage(text, options = {}) {
    if (!('speechSynthesis' in window)) {
        if (typeof showToast === 'function') {
            showToast('Browser Anda tidak mendukung Text-to-Speech.', 'warning');
        }
        return;
    }

    try {
        window.speechSynthesis.cancel();
        if (!text || !text.trim()) {
            if (typeof showToast === 'function') {
                showToast('Tidak ada teks untuk dibacakan.', 'info');
            }
            return;
        }

        // Clean markdown, code blocks, URLs for natural pronunciation
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
        utterance.lang = options.lang || 'id-ID';
        utterance.rate = options.rate || 1.05;
        utterance.pitch = options.pitch || 1.0;

        // Choose best natural Indonesian voice if available
        const voices = window.speechSynthesis.getVoices();
        const idVoice = voices.find(v => v.lang.startsWith('id') || v.name.toLowerCase().includes('indonesia'));
        if (idVoice) utterance.voice = idVoice;

        utterance.onstart = () => {
            if (typeof showToast === 'function') {
                showToast('🔊 Membacakan jawaban AI...', 'info');
            }
        };
        utterance.onerror = (e) => console.warn('Speech synthesis error:', e);

        window.speechSynthesis.speak(utterance);
    } catch (err) {
        console.error('TTS error:', err);
        if (typeof showToast === 'function') {
            showToast('Gagal memutar audio: ' + err.message, 'error');
        }
    }
}

/**
 * Cancel any currently active speech synthesis.
 */
function stopSpeaking() {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
}

// ==================== GLOBAL & MODULE EXPORTS ====================

window.audioCtx = audioCtx;
window.hqSfxEnabled = hqSfxEnabled;
window.hqSpeedMultiplier = hqSpeedMultiplier;
window.getAudioContext = getAudioContext;
window.playCyberBeep = playCyberBeep;
window.playTurnStartSfx = playTurnStartSfx;
window.playConsensusSfx = playConsensusSfx;
window.toggleHqSfx = toggleHqSfx;
window.cycleHqSpeed = cycleHqSpeed;
window.AudioVisualizer = AudioVisualizer;
window.playToolAudio = playToolAudio;
window.speakTextMessage = speakTextMessage;
window.stopSpeaking = stopSpeaking;

window.AlfaAudio = {
    getAudioContext,
    playCyberBeep,
    playTurnStartSfx,
    playConsensusSfx,
    toggleHqSfx,
    cycleHqSpeed,
    AudioVisualizer,
    ToolAudioRecorder: window.ToolAudioRecorder,
    playToolAudio,
    speakTextMessage,
    stopSpeaking
};
