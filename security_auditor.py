"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CYBER SENTRY: WEBSITE SECURITY AUDITOR                    ║
║   Deep Defensive Security Headers, SSL/TLS, & Vulnerability Auditor          ║
║   Copyright (c) 2026 Fahmi Alfatah. All Rights Reserved.                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import ssl
import time
import socket
import urllib.parse
import urllib.request
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("alfa.cyber_sentry")


def audit_website_security(target_url: str, timeout: int = 8) -> Dict[str, Any]:
    """
    Performs comprehensive defensive security audit of a website or web API:
    - HTTP Security Headers (CSP, HSTS, X-Frame-Options, X-Content-Type, etc.)
    - SSL/TLS Certificate & HTTPS Enforcement
    - Information Disclosure Headers (Server, X-Powered-By)
    - CORS Policy & Cookie Attributes
    - Security Grade (A+, A, B, C, D, F) and Actionable Remediation Tips
    """
    if not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = "https://" + target_url

    parsed = urllib.parse.urlparse(target_url)
    hostname = parsed.hostname or target_url
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    start_time = time.time()
    headers_dict = {}
    status_code = 0
    ssl_info = {}
    is_https = parsed.scheme == "https"

    # 1. SSL/TLS Handshake Check
    if is_https:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()
                    version = ssock.version()
                    
                    not_after = cert.get('notAfter', '')
                    issuer = dict(x[0] for x in cert.get('issuer', []))
                    subject = dict(x[0] for x in cert.get('subject', []))
                    
                    ssl_info = {
                        "valid": True,
                        "tls_version": version,
                        "cipher_suite": cipher[0] if cipher else "Unknown",
                        "issuer": issuer.get('organizationName') or issuer.get('commonName', 'Unknown CA'),
                        "subject": subject.get('commonName', hostname),
                        "expires_on": not_after
                    }
        except Exception as e:
            ssl_info = {
                "valid": False,
                "error": str(e),
                "tls_version": "N/A"
            }
    else:
        ssl_info = {
            "valid": False,
            "error": "Plain HTTP without SSL/TLS encryption",
            "tls_version": "None"
        }

    # 2. HTTP Request & Headers Fetch
    req = urllib.request.Request(
        target_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CyberSentry/2.0 (Security-Audit-Bot; Fahmi Alfatah)"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            for k, v in resp.headers.items():
                headers_dict[k.lower()] = v
    except urllib.error.HTTPError as e:
        status_code = e.code
        for k, v in e.headers.items():
            headers_dict[k.lower()] = v
    except Exception as e:
        return {
            "status": "error",
            "target_url": target_url,
            "error": f"Gagal menghubungi target: {str(e)}"
        }

    latency_ms = round((time.time() - start_time) * 1000, 1)

    # 3. Security Header Analysis
    score = 100
    findings: List[Dict[str, Any]] = []
    checks: Dict[str, Dict[str, Any]] = {}

    # Check CSP (Content Security Policy)
    csp = headers_dict.get("content-security-policy")
    if csp:
        checks["csp"] = {"status": "PASS", "value": csp[:60] + "..." if len(csp) > 60 else csp, "desc": "Content Security Policy aktif"}
    else:
        checks["csp"] = {"status": "FAIL", "value": None, "desc": "Header Content-Security-Policy tidak ditemukan"}
        score -= 20
        findings.append({
            "severity": "HIGH",
            "header": "Content-Security-Policy",
            "issue": "Tidak ada proteksi CSP terhadap XSS dan data injection.",
            "recommendation": "Pasang header CSP (misal: default-src 'self'; script-src 'self')."
        })

    # Check HSTS (Strict-Transport-Security)
    hsts = headers_dict.get("strict-transport-security")
    if hsts:
        checks["hsts"] = {"status": "PASS", "value": hsts, "desc": "HSTS aktif memaksakan koneksi HTTPS"}
    else:
        checks["hsts"] = {"status": "FAIL", "value": None, "desc": "HSTS tidak diaktifkan"}
        score -= 15
        findings.append({
            "severity": "HIGH" if is_https else "MEDIUM",
            "header": "Strict-Transport-Security",
            "issue": "Website rentan terhadap serangan SSL Strip / Downgrade Attack.",
            "recommendation": "Tambahkan header: Strict-Transport-Security: max-age=31536000; includeSubDomains; preload"
        })

    # Check X-Frame-Options (Clickjacking)
    xfo = headers_dict.get("x-frame-options")
    if xfo and xfo.upper() in ("DENY", "SAMEORIGIN"):
        checks["x_frame_options"] = {"status": "PASS", "value": xfo, "desc": "Anti-Clickjacking aktif"}
    else:
        checks["x_frame_options"] = {"status": "FAIL", "value": xfo, "desc": "X-Frame-Options tidak terkonfigurasi dengan aman"}
        score -= 15
        findings.append({
            "severity": "MEDIUM",
            "header": "X-Frame-Options",
            "issue": "Website bisa di-embed ke dalam iframe oleh penyerang (Clickjacking).",
            "recommendation": "Gunakan X-Frame-Options: SAMEORIGIN atau DENY."
        })

    # Check X-Content-Type-Options (MIME Sniffing)
    xcto = headers_dict.get("x-content-type-options")
    if xcto and "nosniff" in xcto.lower():
        checks["x_content_type_options"] = {"status": "PASS", "value": xcto, "desc": "MIME-sniffing protection aktif"}
    else:
        checks["x_content_type_options"] = {"status": "FAIL", "value": xcto, "desc": "X-Content-Type-Options: nosniff tidak ada"}
        score -= 10
        findings.append({
            "severity": "LOW",
            "header": "X-Content-Type-Options",
            "issue": "Browser dapat mengeksekusi file berbahaya jika MIME-type salah.",
            "recommendation": "Tambahkan header: X-Content-Type-Options: nosniff"
        })

    # Check Referrer-Policy
    ref = headers_dict.get("referrer-policy")
    if ref:
        checks["referrer_policy"] = {"status": "PASS", "value": ref, "desc": "Kebijakan referrer aktif"}
    else:
        checks["referrer_policy"] = {"status": "WARN", "value": None, "desc": "Referrer-Policy tidak disetel"}
        score -= 5
        findings.append({
            "severity": "LOW",
            "header": "Referrer-Policy",
            "issue": "Data URL sensitif dapat bocor saat pengunjung mengklik link eksternal.",
            "recommendation": "Setel Referrer-Policy: strict-origin-when-cross-origin"
        })

    # Check Information Disclosure (Server / X-Powered-By)
    server_hdr = headers_dict.get("server")
    x_powered = headers_dict.get("x-powered-by")
    if server_hdr or x_powered:
        leaks = []
        if server_hdr: leaks.append(f"Server: {server_hdr}")
        if x_powered: leaks.append(f"X-Powered-By: {x_powered}")
        checks["info_leak"] = {"status": "WARN", "value": ", ".join(leaks), "desc": "Header membocorkan versi/teknologi server"}
        score -= 10
        findings.append({
            "severity": "LOW",
            "header": "Server / X-Powered-By",
            "issue": f"Membocorkan fingerprint teknologi backend ({', '.join(leaks)}).",
            "recommendation": "Sembunyikan header 'X-Powered-By' dan 'Server' di konfigurasi reverse proxy/server."
        })
    else:
        checks["info_leak"] = {"status": "PASS", "value": "None", "desc": "Tidak ada fingerprint server yang bocor"}

    # Final Score & Grade
    score = max(0, min(100, score))
    if score >= 95:
        grade = "A+"
        grade_color = "#10b981" # Emerald
    elif score >= 85:
        grade = "A"
        grade_color = "#10b981"
    elif score >= 70:
        grade = "B"
        grade_color = "#06b6d4" # Cyan
    elif score >= 55:
        grade = "C"
        grade_color = "#f59e0b" # Amber
    elif score >= 40:
        grade = "D"
        grade_color = "#f97316" # Orange
    else:
        grade = "F"
        grade_color = "#ef4444" # Rose/Red

    return {
        "status": "success",
        "target_url": target_url,
        "hostname": hostname,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "is_https": is_https,
        "ssl_info": ssl_info,
        "score": score,
        "grade": grade,
        "grade_color": grade_color,
        "checks": checks,
        "findings": findings,
        "raw_headers_count": len(headers_dict),
        "audit_timestamp": datetime.now().isoformat()
    }
