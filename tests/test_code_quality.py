"""
Code Quality Metrics Report for ALFA Agent

This module provides code quality metrics and analysis.
Run with: pytest --cov=alfa --cov=. --cov-report=term-missing
"""

import subprocess
from pathlib import Path


def run_command(cmd):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"


def check_code_metrics():
    """Check various code quality metrics."""
    print("=" * 70)
    print("ALFA AGENT - CODE QUALITY METRICS")
    print("=" * 70)

    # Count Python files
    py_files = list(Path(".").rglob("*.py"))
    py_files = [f for f in py_files if "venv" not in str(f) and ".git" not in str(f)]
    print(f"\n📊 Total Python Files: {len(py_files)}")

    # Count lines of code
    total_lines = 0
    code_lines = 0
    comment_lines = 0
    blank_lines = 0

    for py_file in py_files[:50]:  # Sample first 50 files
        try:
            with open(py_file, encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                total_lines += len(lines)

                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        blank_lines += 1
                    elif stripped.startswith('#'):
                        comment_lines += 1
                    else:
                        code_lines += 1
        except Exception:
            pass

    print(f"📝 Lines of Code (sample): {code_lines:,}")
    print(f"💬 Comment Lines: {comment_lines:,}")
    print(f"⚪ Blank Lines: {blank_lines:,}")

    # Check test coverage
    print("\n" + "=" * 70)
    print("TEST COVERAGE ANALYSIS")
    print("=" * 70)

    returncode, stdout, stderr = run_command(
        "pytest --cov=alfa --cov=. --cov-report=term-missing 2>&1 | head -100"
    )

    if returncode == 0 or "coverage" in stdout.lower():
        print(stdout[:2000])
    else:
        print("Coverage report not available. Run: pytest --cov=alfa --cov=. --cov-report=html")

    # Check linting status
    print("\n" + "=" * 70)
    print("LINTING STATUS (Ruff)")
    print("=" * 70)

    returncode, stdout, stderr = run_command("ruff check . 2>&1 | head -50")

    if returncode == 0:
        print("✅ No linting issues found!")
    else:
        print(stdout[:1000])

    # Check type hints
    print("\n" + "=" * 70)
    print("TYPE CHECKING (MyPy)")
    print("=" * 70)

    returncode, stdout, stderr = run_command(
        "mypy --ignore-missing-imports alfa/ 2>&1 | head -50"
    )

    if returncode == 0:
        print("✅ No type errors found!")
    else:
        print(stdout[:1000])

    # Test count
    print("\n" + "=" * 70)
    print("TEST SUITE STATISTICS")
    print("=" * 70)

    test_files = list(Path("tests").glob("test_*.py"))
    print(f"🧪 Test Files: {len(test_files)}")

    # Count test functions
    test_count = 0
    for test_file in test_files:
        try:
            with open(test_file, encoding='utf-8') as f:
                content = f.read()
                test_count += content.count("def test_")
        except Exception:
            pass

    print(f"🧪 Total Test Functions: {test_count}")

    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    print("""
1. Maintain >80% test coverage for core modules
2. Add type hints to all public functions
3. Keep function length <50 lines
4. Maintain docstrings for all public APIs
5. Run pre-commit hooks before each commit
    """)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    check_code_metrics()
