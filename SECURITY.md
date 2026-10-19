# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 3.5.x   | :white_check_mark: |
| < 3.5   | :x:                |

## Reporting a Vulnerability

We take the security of ALFA Agent seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do NOT report security vulnerabilities through public GitHub issues.**

### How to Report

Send an email to: **security@alfa-agent.dev** (or use GitHub Security Advisory)

You should receive a response within 48 hours acknowledging your report. After the initial reply, we will keep you informed of the progress toward a fix and announcement.

### What to Include

Please include the following information in your report:

- Description of the vulnerability
- Steps to reproduce the issue
- Affected version(s)
- Potential impact
- Any suggested fixes (if applicable)

## Security Features

ALFA Agent implements several security measures:

### 1. Encrypted Credential Vault
- AES-256-GCM vault storage untuk kredensial API/GDrive (master key file 0600)
- Masked listings + endpoint vault admin-gated (require_admin)
- Passkey/WebAuthn login dashboard implementasi SELESAI end-to-end
  (pustaka `python-webauthn`): challenge server-side sekali-pakai,
  verifikasi attestation/assertion kriptografis (ES256/P-256),
  `sign_count` anti-klon (counter tidak maju → kredential dicabut),
  registrasi bind sesi pemanggil; UI di `static/webauthn.html`.
  Batas jujur: RP ID wajib hostname (bukan IP); produksi wajib HTTPS
  (`ALFA_WEBAUTHN_RP_ID`, `ALFA_WEBAUTHN_ORIGIN`).

### 2. Permission Gates
- Whitelist-only tool execution
- User ID verification before operation
- Owner-level controls for sensitive operations
- **Deny-by-default**: setiap jalur pemanggilan tool WAJIB menyambungkan
  permission gate. Tanpa gate, tool ditolak (bukan dijalankan). Gate yang
  melempar error juga menolak (fail-closed).
- **Trust per tier**: skor kepercayaan dihitung per `(chat, tier)`, bukan
  global. Persetujuan tool LOW tidak pernah membuka tool HIGH/CRITICAL, dan
  auto-approve sendiri tidak menambah skor. Auto-approve sebuah tier juga
  mensyaratkan jumlah persetujuan eksplisit manusia minimum
  (`PERMISSION_GATE_MIN_APPROVALS_*`).
- **Risk tier fail-closed**: tool yang belum masuk `TOOL_CLASSIFICATION`
  dianggap tier HIGH. Tool vault/kritis diklasifikasi eksplisit
  (`vault_delete_secret` = CRITICAL, `vault_get_secret`/`vault_store_secret`
  = HIGH).

### 3. Sandboxed Execution
- Git operations run in isolated sandboxes
- File system access is restricted
- Network calls are monitored and logged
- **Containment `working_dir`**: `working_dir` wajib berada di dalam root
  yang diizinkan (`ALFA_SANDBOX_ROOT`, default: folder kerja ALFA saja).
  Root `/`, `$HOME`, dan nenek moyang `$HOME` selalu ditolak — mount
  `host:host` ke path tersebut membuat seluruh host filesystem terbaca
  di dalam "sandbox".
- **Fail-closed tanpa Docker**: `execute_bash_command` DAN
  `execute_python_sandbox` sama-sama menolak eksekusi di host bila Docker
  tidak tersedia, kecuali operator opting-in eksplisit lewat
  `ALFA_ALLOW_HOST_EXEC=true`.
- **Kripto fail-closed**: `encrypt_key` melempar error bila AES-GCM tidak
  tersedia — API key tidak pernah disimpan plaintext diam-diam.

### 4. Secure Configuration
- Environment variables for secrets (never hardcode)
- `.env.example` provided for safe configuration
- Sensitive data encrypted at rest
- **Dashboard fail-closed**: seluruh endpoint `/api/*` wajib memiliki session
  valid atau token. `DASHBOARD_AUTH_TOKEN` kosong TIDAK lagi membuka API
  untuk semua orang. Mode development tanpa login hanya lewat escape hatch
  eksplisit `ALFA_INSECURE_LOCAL=true` (klien lokal saja, dan boot ditolak
  bila `DASHBOARD_HOST` bind ke `0.0.0.0/::`).
- **RBAC default-deny**: seluruh endpoint mutating yang menjalankan aksi
  nyata di host (eksekusi tool/agent/swarm, rapat, antrean misi, broadcast,
  kredensial Drive, WhatsApp, passkey) memerlukan peran admin.
  Pencocokan path publik memakai pencocokan PERSIS — prefix match pernah
  membuat `/docs` dan `/api/v1/*` publik.

### 5. XSS & Content Security Policy
- Output LLM (rapat, chat, consensus) disanitasi **dua lapis**:
  1. `safeMarkdown()` → `marked` lalu `DOMPurify.sanitize()` sebelum masuk DOM;
  2. CSP ketat (`default-src 'self'`, `script-src` berbasis nonce tanpa
     `'unsafe-inline'`) sebagai jaring pengaman kedua.
- Semua interpolasi data eksternal (judul rapat, nama agen, ringkasan
  eksekusi, produk marketplace, secret vault, finding keamanan, katalog
  tool) di-escape dengan `escHtml()` lengkap (`& < > " '`).
- SPA dimuat sebagai ES module dengan import/export eksplisit — dependensi
  antar-file bisa dianalisis statis dan diuji, bukan lagi global implisit.

### 6. Proteksi Perintah Shell atas Instruksi LLM
Output LLM bisa dipengaruhi *prompt injection*. Karena itu perintah yang
datang dari LLM **tidak** dieksekusi mentah:

- **Allowlist binary** (`alfa/security/command_policy.py`) — deny-by-default;
  setiap segmen pipeline (`|`, `&&`, `;`) diperiksa sendiri.
- **Binary terlarang** — `sudo`, `su`, `systemctl`, `crontab`, `docker`,
  `ssh`, `useradd`, `iptables`, `mkfs`, `dd`, `kill`, ...
- **Chaining ke shell** — `curl x | sh`, `wget | bash`, `eval`, `python -c`.
- **Path sensitif** — `~/.ssh`, `~/.aws`, `/etc`, `/proc`, `id_rsa`.
- **Pola destruktif** — `rm -rf /`, `chmod 777 /`, `dd of=/dev/`, `git push --force`.
- Diterapkan pada `POST /api/agents/{id}/execute` dan jalur eksekusi
  forced-JSON swarm. Perintah yang ditolak dikembalikan sebagai pesan
  penolakan, bukan dieksekusi.

### 7. OAuth & Endpoint Dashboard
- **State OAuth divalidasi** (`secrets.compare_digest`) di MCP client —
  tanpa ini siapa pun bisa menyelesaikan flow dengan authorization code
  miliknya sendiri (OAuth CSRF / session fixation).
- **Endpoint surface tidak bocor** — `/docs`, `/redoc`, `/openapi.json` dan
  `/api/metrics` (CPU/RAM/disk, RSS proses, thread, connection pool)
  membutuhkan autentikasi.

### 5. Code Quality & Security
- Automated linting with Ruff
- Static type checking with mypy (0 baseline errors)
- Security scanning with Bandit (`bandit -r alfa plugins -ll -q` = 0 Medium/High):
  - `alfa/core/db/tasks.py`: kueri SQL cron job menggunakan tuple statis berparameter (`?`) tanpa interpolasi f-string (bebas B608).
  - `alfa/mcp/client.py` (`_http`, `_post_form`): setiap pemanggilan `urllib.request.urlopen` didahului `_validate_http_url()` yang menolak skema selain `http`/`https` (mencegah SSRF skema `file://`); ditandai `# nosec B310` karena Bandit memindai `urlopen` secara statis.
  - `alfa/tools/system/sites.py` (`_wait_http`): health-check proses lokal memvalidasi `parsed.scheme in ("http", "https")` sebelum `urllib.request.urlopen`; ditandai `# nosec B310`.
- Pre-commit hooks for code review

## Best Practices for Users

### DO:
- ✅ Keep your API keys and credentials secure
- ✅ Use environment variables for sensitive data
- ✅ Regularly update to the latest version
- ✅ Review permissions before granting tool access
- ✅ Enable two-factor authentication where available
- ✅ Use the passkey vault for credential storage

### DON'T:
- ❌ Commit `.env` files or credentials to git
- ❌ Share your passkeys or API tokens
- ❌ Run untrusted tools without review
- ❌ Disable security features unless absolutely necessary
- ❌ Use outdated versions with known vulnerabilities

## Security Audit Trail

All security-relevant operations are logged:
- Tool execution attempts
- Permission gate decisions
- Vault access events
- Authentication failures

Review logs regularly in your dashboard or via CLI:
```bash
alfa logs --level security
```

## Incident Response

In case of a confirmed security incident:

1. **Immediate**: Revoke affected credentials
2. **Short-term**: Patch the vulnerability
3. **Long-term**: Implement additional safeguards

We commit to:
- Transparent communication about security issues
- Timely patches for reported vulnerabilities
- Learning from incidents to improve security

## Third-Party Dependencies

We regularly audit our dependencies for known vulnerabilities:
- Automated checks via GitHub Dependabot
- Regular `pip audit` scans
- Prompt updates for critical security patches

## Contact

For security-related questions:
- Email: security@alfa-agent.dev
- GitHub Security Advisory: Use the "Report a vulnerability" feature

---

*Last updated: October 2026*
