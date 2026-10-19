"""
Modul Security, Logic & Quality Critic (Heuristik & Analisis Statis AST)
Dibuat untuk mengevaluasi kapabilitas dan batasan riil sistem Swarm Agent.
Metode: AST Heuristik, Pattern Regex, Analisis Kontrol Alur (Bukan Neural/AI).
"""

import ast
import json
import re
from typing import Any


class SecurityLogicQualityCritic:
    def __init__(self):
        self.dangerous_functions = {
            'eval', 'exec', 'system', 'popen', 'spawn', 'fork'
        }
        self.sensitive_patterns = [
            (r"""(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|private[_-]?key)\s*=\s*['"][^'"]+['"]""", "Hardcoded Secret / Token Terdeteksi"),
            (r'rm\s+-rf\s+[/~]', "Destructive Shell Command Detected"),
            (r'chmod\s+777', "Insecure File Permission (chmod 777)")
        ]

    def audit_security(self, code_content: str) -> list[dict[str, Any]]:
        findings = []
        # 1. Regex Heuristic
        for pattern, label in self.sensitive_patterns:
            matches = re.finditer(pattern, code_content)
            for m in matches:
                findings.append({
                    "category": "SECURITY_CRITIC",
                    "severity": "HIGH",
                    "rule": "REGEX_HEURISTIC",
                    "detail": label,
                    "matched_sample": m.group(0)[:40] + ("..." if len(m.group(0)) > 40 else "")
                })

        # 2. AST Security Analysis
        try:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in self.dangerous_functions:
                        findings.append({
                            "category": "SECURITY_CRITIC",
                            "severity": "CRITICAL" if name in ['eval', 'exec'] else "HIGH",
                            "rule": "DANGEROUS_CALL_AST",
                            "detail": f"Panggilan fungsi berbahaya terdeteksi: '{name}' pada baris {getattr(node, 'lineno', 'unknown')}",
                            "line": getattr(node, 'lineno', None)
                        })
        except SyntaxError as e:
            findings.append({
                "category": "SECURITY_CRITIC",
                "severity": "BLOCKER",
                "rule": "SYNTAX_ERROR",
                "detail": f"Kode tidak dapat diparsing (SyntaxError: {e})"
            })
        return findings

    def audit_logic(self, code_content: str) -> list[dict[str, Any]]:
        findings = []
        try:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                # Deteksi Infinite Loops (while True tanpa break)
                if isinstance(node, ast.While):
                    is_always_true = False
                    if isinstance(node.test, ast.Constant) and node.test.value is True:
                        is_always_true = True
                    elif isinstance(node.test, ast.NameConstant) and node.test.value is True:
                        is_always_true = True

                    if is_always_true:
                        has_break = any(isinstance(sub, ast.Break) for sub in ast.walk(node))
                        if not has_break:
                            findings.append({
                                "category": "LOGIC_CRITIC",
                                "severity": "HIGH",
                                "rule": "INFINITE_LOOP_RISK",
                                "detail": f"Potensi infinite loop: 'while True' tanpa break ditemukan pada baris {node.lineno}",
                                "line": node.lineno
                            })
                # Deteksi redundant boolean comparison (misal: if x == True)
                if isinstance(node, ast.Compare):
                    for comp in node.comparators:
                        if isinstance(comp, ast.Constant) and isinstance(comp.value, bool):
                            findings.append({
                                "category": "LOGIC_CRITIC",
                                "severity": "LOW",
                                "rule": "REDUNDANT_BOOLEAN_COMPARISON",
                                "detail": f"Perbandingan redundan dengan nilai boolean (baris {node.lineno})",
                                "line": node.lineno
                            })
        except (SyntaxError, ValueError, AttributeError):
            pass
        return findings

    def audit_quality(self, code_content: str) -> list[dict[str, Any]]:
        findings = []
        try:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                # Deteksi bare except
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        findings.append({
                            "category": "QUALITY_CRITIC",
                            "severity": "MEDIUM",
                            "rule": "BARE_EXCEPT",
                            "detail": f"Penggunaan bare 'except:' ditemukan di baris {node.lineno}. Disarankan menangkap Exception spesifik.",
                            "line": node.lineno
                        })
                # Deteksi fungsi tanpa docstring
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not ast.get_docstring(node):
                        findings.append({
                            "category": "QUALITY_CRITIC",
                            "severity": "LOW",
                            "rule": "MISSING_DOCSTRING",
                            "detail": f"Fungsi '{node.name}' pada baris {node.lineno} tidak memiliki docstring dokumentasi.",
                            "line": node.lineno
                        })
        except (SyntaxError, ValueError, AttributeError):
            pass
        return findings

    def evaluate_all(self, code_content: str) -> dict[str, Any]:
        sec = self.audit_security(code_content)
        logic = self.audit_logic(code_content)
        qual = self.audit_quality(code_content)
        total_issues = len(sec) + len(logic) + len(qual)

        # Hitung skor kualitas heuristik (100 - penalti)
        score = 100
        for item in sec:
            score -= 25 if item["severity"] == "CRITICAL" else 15
        for _item in logic:
            score -= 10
        for _item in qual:
            score -= 5
        score = max(0, score)

        return {
            "overall_score": score,
            "security_findings": sec,
            "logic_findings": logic,
            "quality_findings": qual,
            "total_issues": total_issues,
            "methodology": "AST Heuristic & Static Regex Analysis (Deterministic, Non-Neural)"
        }

if __name__ == "__main__":
    sample = """
import os

API_KEY = "sk-live-1234567890abcdef"

def run_worker():
    while True:
        try:
            cmd = "echo ping"
            os.system(cmd)
            eval("1 + 1")
        except:
            pass
"""
    critic = SecurityLogicQualityCritic()
    results = critic.evaluate_all(sample)
    print(json.dumps(results, indent=2))
