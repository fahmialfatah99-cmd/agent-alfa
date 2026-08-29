"""Security & Audit Tools for ALFA Agent."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def audit_network_security(
    target_host: str = "127.0.0.1", 
    scan_type: str = "quick_ports"
) -> Dict[str, Any]:
    """Audit network security by scanning open ports and services."""
    try:
        import subprocess
        
        results = {
            "target": target_host,
            "scan_type": scan_type,
            "open_ports": [],
            "services": []
        }
        
        if scan_type == "quick_ports":
            # Quick port scan using netstat or ss
            cmd = ["ss", "-tlnp"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if target_host in line or "0.0.0.0" in line or "*:" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            addr = parts[4]
                            port = addr.split(':')[-1]
                            if port.isdigit():
                                results["open_ports"].append(int(port))
                                results["services"].append({
                                    "port": int(port),
                                    "address": addr,
                                    "process": parts[-1] if len(parts) > 5 else "unknown"
                                })
        
        return {
            "status": "success",
            "message": f"Scanned {target_host}, found {len(results['open_ports'])} open ports",
            "results": results
        }
    except Exception as e:
        logger.error(f"Network audit error: {e}")
        return {"status": "error", "error": str(e)}


def audit_website_security(target_url: str) -> Dict[str, Any]:
    """Audit website security headers and basic vulnerabilities."""
    try:
        import httpx
        
        response = httpx.get(target_url, timeout=15, follow_redirects=True)
        
        # Check security headers
        security_headers = {
            "Strict-Transport-Security": "HSTS not configured",
            "Content-Security-Policy": "CSP not configured",
            "X-Frame-Options": "Clickjacking protection missing",
            "X-Content-Type-Options": "MIME sniffing protection missing",
            "X-XSS-Protection": "XSS protection missing",
            "Referrer-Policy": "Referrer policy not configured"
        }
        
        findings = []
        for header, issue in security_headers.items():
            if header not in response.headers:
                findings.append({"severity": "medium", "issue": issue, "header": header})
            else:
                findings.append({
                    "severity": "info",
                    "issue": f"{header} configured",
                    "value": response.headers[header][:50]
                })
        
        # Check SSL/TLS
        ssl_info = "N/A"
        if target_url.startswith("https"):
            ssl_info = "HTTPS enabled"
        else:
            findings.append({
                "severity": "high",
                "issue": "Website not using HTTPS"
            })
        
        return {
            "status": "success",
            "message": f"Audited {target_url}",
            "url": target_url,
            "status_code": response.status_code,
            "ssl": ssl_info,
            "findings": findings,
            "security_score": max(0, 100 - len([f for f in findings if f["severity"] in ["high", "medium"]]) * 10)
        }
    except Exception as e:
        logger.error(f"Website audit error: {e}")
        return {"status": "error", "error": str(e)}
