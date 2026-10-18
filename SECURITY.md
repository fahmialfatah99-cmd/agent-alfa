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

### 3. Sandboxed Execution
- Git operations run in isolated sandboxes
- File system access is restricted
- Network calls are monitored and logged

### 4. Secure Configuration
- Environment variables for secrets (never hardcode)
- `.env.example` provided for safe configuration
- Sensitive data encrypted at rest

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
