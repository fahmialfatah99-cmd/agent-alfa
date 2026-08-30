# DevCLI - AI Coding Assistant CLI

CLI tool seperti Cursor/OpenCode untuk membantu coding langsung dari terminal dengan dukungan **multi-provider AI**.

## ✨ Fitur

- 🤖 **Chat Interaktif** - Diskusi coding dengan AI langsung di terminal
- 📁 **Konteks File** - AI bisa membaca dan menganalisis file kode Anda
- ⚡ **Quick Ask** - Tanya pertanyaan cepat tanpa mode interaktif
- 🛠️ **Shell Commands** - Jalankan perintah shell dengan aman
- 🔌 **Multi-Provider** - Support 5+ provider AI:
  - **OpenAI**: gpt-4o, gpt-4o-mini, o1-preview, dll
  - **Anthropic**: claude-3-5-sonnet (terbaik untuk coding), claude-3-opus, claude-3-haiku
  - **Google Gemini**: gemini-1.5-pro, gemini-1.5-flash
  - **Groq**: llama-3.1-70b, mixtral-8x7b (super cepat)
  - **Ollama**: Model lokal gratis (llama3, codellama, deepseek-coder)
- ⚙️ **Interactive Config** - Setup provider, model, dan API key via menu
- 💾 **Auto Save** - Konfigurasi otomatis tersimpan ke `.env`

## 🚀 Instalasi Cepat

```bash
# 1. Masuk ke direktori
cd /workspace/devcli

# 2. Install dependencies
npm install

# 3. Link CLI (opsional, agar bisa dipanggil dari mana saja)
npm link

# 4. Setup konfigurasi (pilih provider & model)
devcli config

# 5. Mulai coding!
devcli chat
```

## 📖 Cara Penggunaan

### Mode Interaktif (Chat)
```bash
devcli chat
```
Ketik pertanyaan coding, minta buat file, debug error, atau analisis kode.
- `exit` - Keluar dari mode interaktif
- `clear` - Reset history chat
- `config` - Ubah konfigurasi provider/model

### Sertakan Konteks File
```bash
# Analisis satu file
devcli chat -f app.py

# Analisis multiple files
devcli chat -f main.py -f utils.js -f config.json
```

### Tanya Cepat (Satu Kali)
```bash
devcli ask "Bagaimana cara membuat async function di Python?"
devcli ask "Fix bug di file ini" -f main.py
```

### Jalankan Perintah Shell
```bash
devcli run "ls -la"
devcli run "npm test"
devcli run "python3 script.py"
```

### Setup Konfigurasi
```bash
# Menu interaktif (direkomendasikan)
devcli config

# Lihat konfigurasi saat ini
devcli config --show
```

## 🔧 Environment Variables

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `AI_PROVIDER` | `openai` | Provider: `openai`, `anthropic`, `google`, `groq`, `ollama` |
| `AI_MODEL` | `gpt-4o-mini` | Model yang digunakan (sesuai provider) |
| `OPENAI_API_KEY` | - | API key OpenAI |
| `ANTHROPIC_API_KEY` | - | API key Anthropic |
| `GOOGLE_API_KEY` | - | API key Google Gemini |
| `GROQ_API_KEY` | - | API key Groq |
| `API_BASE_URL` | Auto | Base URL API (otomatis sesuai provider) |

### Contoh Setup Manual
```bash
# OpenAI
export AI_PROVIDER=openai
export OPENAI_API_KEY=sk-your-api-key-here
export AI_MODEL=gpt-4o-mini

# Anthropic (Claude 3.5 Sonnet - Terbaik untuk Coding)
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-your-api-key-here
export AI_MODEL=claude-3-5-sonnet-20241022

# Ollama (Gratis, Offline)
export AI_PROVIDER=ollama
export AI_MODEL=llama3.1
# Pastikan Ollama sudah running: ollama serve
```

## 🎯 Daftar Model per Provider

### OpenAI
- `gpt-4o` - Model terbaru & terpintar
- `gpt-4o-mini` - Cepat & hemat (default)
- `gpt-4-turbo` - Versi turbo GPT-4
- `gpt-3.5-turbo` - Legacy, murah
- `o1-preview` - Reasoning tingkat tinggi
- `o1-mini` - Reasoning cepat

### Anthropic (Direkomendasikan untuk Coding)
- `claude-3-5-sonnet-20241022` - ⭐ Terbaik untuk programming
- `claude-3-opus-20240229` - Paling pintar
- `claude-3-haiku-20240307` - Tercepat

### Google Gemini
- `gemini-1.5-pro` - Model pro dengan context besar
- `gemini-1.5-flash` - Cepat & efisien

### Groq (Ultra Fast)
- `llama-3.1-70b-versatile` - Llama 3.1 70B
- `llama-3.1-8b-instant` - Llama 3.1 8B (instant response)
- `mixtral-8x7b-32768` - Mixtral MoE

### Ollama (Local/Offline)
- Otomatis mendeteksi model yang sudah di-pull
- Rekomendasi: `llama3.1`, `codellama`, `deepseek-coder`

## 💡 Tips

1. **Untuk Production Coding**: Gunakan Claude 3.5 Sonnet (`anthropic`) atau GPT-4o (`openai`)
2. **Untuk Eksperimen Murah**: Gunakan `gpt-4o-mini` atau Groq
3. **Untuk Privacy/Offline**: Gunakan Ollama dengan model lokal
4. **Simpan API Key Aman**: Gunakan `devcli config` untuk menyimpan ke `.env`
5. **Context Lebih Akurat**: Selalu sertakan file relevan dengan `-f`

## 📝 Contoh Sesi

```bash
$ devcli chat

🚀 DevCLI Mode Interaktif Aktif
Provider: Anthropic | Model: claude-3-5-sonnet-20241022
Ketik 'exit' untuk keluar, 'clear' untuk reset chat, 'config' untuk ubah pengaturan.

You: Buat fungsi Python untuk quicksort
DevCLI: Berikut implementasi quicksort di Python:

```python
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
```

You: Sekarang tambahkan test unit
DevCLI: Berikut test unit menggunakan pytest:

```python
def test_quicksort():
    assert quicksort([3, 6, 1, 5, 2, 4]) == [1, 2, 3, 4, 5, 6]
    assert quicksort([]) == []
    assert quicksort([1]) == [1]
```

You: exit
```

## 🆘 Troubleshooting

**Error: Module not found**
```bash
npm install
```

**Error: API Key tidak valid**
- Pastikan API key benar
- Cek dengan `devcli config --show`
- Setup ulang dengan `devcli config`

**Ollama tidak terdeteksi**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull llama3.1

# Jalankan service
ollama serve
```

## 📄 License

MIT
