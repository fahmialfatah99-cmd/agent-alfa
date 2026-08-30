# DevCLI - AI Coding Assistant CLI

CLI tool seperti Cursor/OpenCode untuk membantu coding langsung dari terminal.

## Fitur
- 🤖 Chat interaktif dengan AI untuk bantuan coding
- 📁 Bisa membaca konteks file untuk analisis kode
- ⚡ Perintah cepat untuk tanya jawab singkat
- 🛠️ Eksekusi perintah shell dengan aman
- 🔌 Support multiple AI providers (OpenAI, Anthropic, Ollama offline)

## Instalasi

1. Masuk ke direktori project:
```bash
cd /workspace/devcli
```

2. Install dependencies:
```bash
npm install
```

3. Setup API Key (pilih salah satu):

**Option A: OpenAI (Online)**
```bash
export OPENAI_API_KEY=sk-your-actual-api-key-here
```

**Option B: Ollama (Offline/Local - Gratis)**
```bash
# Install Ollama terlebih dahulu
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
export AI_PROVIDER=ollama
```

4. Link CLI agar bisa dipanggil dari mana saja:
```bash
npm link
```

5. Jalankan:
```bash
# Mode interaktif
devcli chat

# Atau jalankan langsung tanpa link
node index.js chat
```

## Cara Penggunaan

### 1. Mode Interaktif (Chat)
```bash
devcli chat
```
Ketik pertanyaan coding, minta buat file, atau debug error.

### 2. Sertakan Konteks File
```bash
devcli chat -f app.py -f utils.js
```
AI akan membaca isi file tersebut untuk memberikan jawaban yang lebih akurat.

### 3. Tanya Cepat (Satu Kali)
```bash
devcli ask "Bagaimana cara membuat async function di Python?"
devcli ask "Fix bug di file ini" -f main.py
```

### 4. Jalankan Perintah Shell
```bash
devcli run "ls -la"
devcli run "npm test"
```

### 5. Cek Konfigurasi
```bash
devcli config
```

## Environment Variables

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `AI_PROVIDER` | `openai` | Provider AI: `openai`, `anthropic`, `ollama` |
| `OPENAI_API_KEY` | - | API key OpenAI |
| `ANTHROPIC_API_KEY` | - | API key Anthropic |
| `API_BASE_URL` | `https://api.openai.com/v1` | Base URL API (untuk custom endpoint) |

## Contoh Sesi

```
$ devcli chat

🚀 DevCLI Mode Interaktif Aktif
Provider: OPENAI | Model: gpt-4o-mini
Ketik 'exit' untuk keluar, 'clear' untuk reset chat.

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

You: exit
```

## Tips
- Gunakan **Ollama** untuk coding offline tanpa biaya API
- Untuk production, pertimbangkan rate limiting dan error handling yang lebih robust
- Simpan API key di `.env` file untuk keamanan
