# Code Quality Metrics

This document tracks code quality metrics for the ALFA Agent project.

## Current Status (v3.5.0, 2026-11-19)

### Test Coverage

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Overall Coverage | 80% | **67.84%** (43.331 statement, 13.937 belum tercover) | 🟡 Below target (naik dari 47,65% → 54,23% → 57,00% → 65,20% → 67,84%) |
| Security-critical modules | 90% | 85–95% (perm gate, sandbox, vault, command policy) | 🟢 |
| Integration Tests | Critical paths | Covered | 🟢 OK |

**Note:** Jalankan `pytest --cov=alfa --cov-report=html` untuk laporan lokal.
Gate CI `fail_under` saat ini **55%**; angka 67,84% memberi ruang di atas gate.
Kenaikan terakhir berasal dari suite Phase 3/4 (readiness, tracing, rate limit,
shutdown, retensi sesi, SBOM, a11y), suite Phase 5 (144 tes hermetic), dan
penghapusan versi hardcoded pada tes.

### Phase 5 — coverage hardening modul kritis

Lima modul berisiko tinggi dinaikkan coverage-nya dengan tes hermetic
(SQLite sementara, HTTP/LLM/tool di-mock, subprocess tidak menyentuh layanan):

| Modul | Sebelum | Sesudah | Missing |
|-------|---------|---------|---------|
| `alfa/dashboard/routes/system/settings_admin.py` | 37,2% | **88,6%** | 37 |
| `alfa/swarm/step_executor.py` | 33,1% | **85,9%** | 45 |
| `alfa/bot/proactive.py` | 16,4% | **86,1%** | 72 |
| `alfa/tools/system/sites.py` | 38,1% | **90,9%** | 32 |
| `alfa/integrations/google_sheets.py` | ~60% | **91,2%** | 39 |

Tes Phase 5 juga menemukan bug query `system_settings ... ORDER BY id`
pada pembacaan spreadsheet ID; diperbaiki menjadi `ORDER BY rowid` agar
konfigurasi dari dashboard benar-benar terbaca.

### Gap analysis — area yang masih belum tercover

Target 80% belum tercapai. Berikut area dengan statement belum tercover
terbanyak (diurutkan dari coverage JSON terakhir):

| Area | Missing | Alasan / langkah berikutnya |
|------|---------|------------------------------|
| `alfa/bot/discord_bot.py` | 562 | `main()` butuh klien Discord nyata; helper sudah teruji terpisah |
| `alfa/tools/system/management.py` | 227 | Tool manajemen sistem bergantung host; perlu sandbox mock |
| `alfa/swarm/llm_client.py` | 215 | Panggilan LLM nyata; fokus pada parsing/fallback |
| `alfa/core/cli/chat.py` | 201 | CLI interaktif (Rich/prompt) — butuh PTY palsu |
| `alfa/tools/filesystem/universal_file_extractor.py` | 196 | Ekstraksi dokumen butuh berkas nyata; sebagian sudah diuji |
| `alfa/core/cli/slash/developer.py` | 194 | Slash command developer; butuh harness CLI |
| `alfa/dashboard/routes/chat.py` | 184 | Streaming SSE & turn aktif; butuh event-loop harness |
| `alfa/tools/filesystem/office_convert.py` | 181 | Konversi Office bergantung LibreOffice |
| `alfa/core/cli/basic_commands.py` | 174 | CLI interaktif; butuh PTY palsu |
| `alfa/memory/vector.py` | 170 | Embedding/vektor; perlu model atau fake deterministik |

Modul target Phase 5 sudah keluar dari daftar gap utama: `proactive.py` (72),
`google_sheets.py` (39), `step_executor.py` (45), dan `settings_admin.py` (37)
kini di atas 85%.

### Test Suite Statistics

| Metric | Count |
|--------|-------|
| Test Files | 131 |
| Test Functions | 2.198 (termasuk parameterisasi) |
| Fixtures | 20+ |
| Custom Markers | 5 |

### Linting Status

| Tool | Status | Issues |
|------|--------|--------|
| Ruff | ✅ Clean | 0 errors (alfa + tests) |
| Black | ✅ Configured | Formatted |
| MyPy | ✅ Clean | 0 error / 354 source file |
| Lint budget (TRY/BLE) | ✅ Ratchet | 510 instans di 175 file (tidak boleh bertambah) |

### Security Scanning

| Scanner | Frequency | Status |
|---------|-----------|--------|
| Bandit | Every CI run | ✅ Integrated (artifact `security-scan-results`) |
| Safety (lockfile) | Every CI run | ✅ Integrated, deterministik — gagal hanya bila advisory punya fix |
| SBOM CycloneDX | Every CI run | ✅ Artifact `sbom-cyclonedx` |
| Manual audit | Per release | 📋 Scheduled |

Catatan dependency: `requirements-lock.txt` saat ini memiliki 7 advisory
**tanpa versi perbaikan** (browser-use, filelock×3, mako, markitdown, twisted).
Gate sengaja lulus dengan peringatan; advisory yang punya fix akan menggagalkan CI.

## Quality Gates

### Pre-commit Checks

All commits must pass:
- ✅ Ruff linting (no errors)
- ✅ Black formatting (or auto-fix applied)
- ✅ MyPy type checking (warnings allowed)

### CI/CD Checks

All PRs must pass:
- ✅ All unit tests
- ✅ Integration tests (non-slow)
- ✅ Code coverage threshold (gate `fail_under=55`, aktual 67,84%)
- ✅ Security scanning (Bandit, no high/critical)
- ✅ Dependency audit deterministik (gagal hanya bila advisory punya fix)
- ✅ Docs strict (`mkdocs build --strict`)
- ✅ Lint budget & silent-exception check

### Release Criteria

Before each release:
- 🟡 Overall test coverage di atas gate dan tidak turun (target jangka panjang 80%)
- ✅ All security tests passing
- ✅ No critical linting issues
- ✅ All integration tests passing
- ✅ Documentation updated
- ✅ Changelog updated

## Metrics History

### Version 3.5.0 — Phase 5 Coverage Hardening (2026-11-19)

**Improvements:**
- 144 tes hermetic baru untuk settings admin, step executor swarm,
  proactive loops, sites registry, Google Sheets, dan smoke route dashboard.
- Overall coverage 65,20% → **67,84%** (+1.143 statement tercover).
- Lima modul kritis kini 85,9–91,2%.
- Bug `ORDER BY id` pada pembacaan spreadsheet ID diperbaiki (`rowid`).

### Version 2.5.0

**Improvements:**
- Added comprehensive test fixtures (conftest.py)
- Enhanced test suite with 50+ new tests
- Integrated security scanning (Bandit)
- Added dependency vulnerability checking (Safety)
- Created code quality workflow
- Added testing documentation

**Pending:**
- Generate baseline coverage report
- Add type hints to legacy modules
- Increase integration test coverage

### Version 0.1.0 (Initial)

**Baseline:**
- Basic test suite
- Minimal coverage reporting
- Manual security checks

## Tools Configuration

### pytest

```toml
[tool.pytest.ini_options]
minversion = "7.0"
addopts = "-ra -q"
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_functions = ["test_*"]
asyncio_mode = "auto"
```

### Coverage

```toml
[tool.coverage.run]
source = ["alfa", "."]
omit = [
    "*/tests/*",
    "*/__pycache__/*",
    "*/venv/*",
    "test_*.py",
    "*_test.py",
    "conftest.py"
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "@abstractmethod",
    "@overload"
]
show_missing = true
precision = 2
```

### Ruff

```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "B", "W", "I", "N", "UP", "YTT"]
ignore = ["E501", "B006"]
```

### MyPy

```toml
[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true
disallow_untyped_defs = false
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
```

## Continuous Improvement

### Action Items

- [ ] Achieve >80% test coverage
- [ ] Add type hints to all public APIs
- [ ] Create integration test scenarios
- [ ] Implement mutation testing
- [ ] Add performance benchmarks
- [ ] Create load testing suite

### Best Practices

1. **Test-Driven Development**: Write tests before implementing features
2. **Code Review**: All code must be reviewed before merging
3. **Documentation**: Update docs with every feature/change
4. **Security First**: Security tests are mandatory for sensitive operations
5. **Performance**: Profile code regularly, optimize bottlenecks

## Reporting

### Weekly Reports

Automated weekly reports include:
- Test coverage trends
- New test count
- Bug fix rate
- Code quality score

### Dashboard

Access real-time metrics:
- **Coverage**: htmlcov/index.html (local) or Codecov (CI)
- **Linting**: GitHub Actions logs
- **Security**: Bandit/Safety reports in artifacts

## Contact

For questions about code quality metrics:
- Open an issue on GitHub
- Contact: fahmialfatah99@example.com
