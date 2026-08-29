# Code Quality Guidelines for ALFA AI Agent

## 📋 Table of Contents

1. [Code Style](#code-style)
2. [Error Handling](#error-handling)
3. [Type Hints](#type-hints)
4. [Documentation](#documentation)
5. [Testing](#testing)
6. [Performance](#performance)
7. [Security](#security)

---

## 🎨 Code Style

### Formatting Standards
- **Line Length**: Maximum 200 characters (configured in `pyproject.toml`)
- **Indentation**: 4 spaces (no tabs)
- **Imports**: Sorted automatically by Ruff/Isort
- **Quotes**: Use double quotes for strings

### Tools
```bash
# Auto-format code
ruff format .

# Lint and fix issues
ruff check . --fix

# Run all checks
pre-commit run --all-files
```

### Naming Conventions
```python
# Classes: PascalCase
class SystemStats(TypedDict):
    pass

# Functions/Methods: snake_case
def get_system_stats() -> Dict[str, Any]:
    pass

# Constants: UPPER_SNAKE_CASE
MAX_RETRY_ATTEMPTS = 5
DEFAULT_TIMEOUT = 300

# Private/Internal: _prefix
def _internal_helper():
    pass
```

---

## ⚠️ Error Handling

### Standard Pattern
All tools should follow this error handling pattern:

```python
def some_tool(param: str) -> Dict[str, Any]:
    """Tool description with docstring."""
    try:
        # Main logic here
        result = perform_operation(param)
        return {
            'status': 'success',
            'data': result
        }
    except SpecificKnownError as e:
        logger.warning(f"Expected error: {e}")
        return {
            'status': 'error',
            'message': f'Operation failed: {str(e)}'
        }
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return {
            'status': 'error',
            'message': f'Internal error: {str(e)}'
        }
```

### Error Response Structure
```python
# Success response
{
    'status': 'success',
    'data': {...}
}

# Error response
{
    'status': 'error',
    'message': 'Human-readable error message',
    'error_code': 'OPTIONAL_ERROR_CODE'
}
```

### Logging Levels
- **DEBUG**: Detailed internal execution details
- **INFO**: Successful operations, state changes
- **WARNING**: Recoverable issues, deprecated usage
- **ERROR**: Operation failures, system continues
- **CRITICAL**: System cannot continue

---

## 🔤 Type Hints

### Required Type Annotations
All public functions MUST have type hints:

```python
from typing import Any, Dict, List, Optional, TypedDict

# Define custom types
class ToolResult(TypedDict, total=False):
    status: str
    message: str
    data: Optional[Any]
    error: Optional[str]

# Function with full type hints
def process_data(
    items: List[str],
    max_count: int = 10,
    filter_empty: bool = True
) -> ToolResult:
    pass
```

### Common Types
```python
from typing import Any, Dict, List, Optional, Union, Callable

# Generic dict with string keys
Dict[str, Any]

# Optional value
Optional[str]  # Same as Union[str, None]

# Multiple possible types
Union[int, str, None]

# Function signature
Callable[[str, int], bool]
```

---

## 📖 Documentation

### Docstring Format
Use Google-style docstrings:

```python
def fetch_web_page(url: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Fetch and extract content from a web page.
    
    Args:
        url: The URL to fetch content from
        timeout: Request timeout in seconds (default: 10)
    
    Returns:
        Dictionary containing:
        - status: 'success' or 'error'
        - data: Extracted content (if successful)
        - message: Error message (if failed)
    
    Raises:
        ValueError: If URL is invalid
        TimeoutError: If request times out
    
    Example:
        >>> result = fetch_web_page("https://example.com")
        >>> print(result['data'])
    """
    pass
```

### Module Docstrings
Every module should start with a descriptive docstring:

```python
"""
System Monitoring Tools Module

Provides comprehensive system statistics including CPU, RAM, disk usage,
process monitoring, and system information gathering.
"""
```

---

## 🧪 Testing

### Test Structure
```python
# tests/test_module_name.py
import pytest
from module_name import function_to_test

class TestFunctionName:
    """Test suite for specific function."""
    
    def test_success_case(self):
        """Test normal operation."""
        result = function_to_test(valid_input)
        assert result['status'] == 'success'
    
    def test_error_case(self):
        """Test error handling."""
        result = function_to_test(invalid_input)
        assert result['status'] == 'error'
    
    @pytest.mark.asyncio
    async def test_async_function(self):
        """Test async functions."""
        result = await async_function()
        assert result is not None
```

### Running Tests
```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_tools_unit.py -v

# Run specific test function
pytest tests/test_tools_unit.py::test_execute_bash_command -v
```

---

## ⚡ Performance

### Best Practices

1. **Lazy Loading**: Import heavy modules inside functions
```python
def heavy_operation():
    import tensorflow as tf  # Only import when needed
    # ...
```

2. **Caching**: Use `@lru_cache` for expensive operations
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_config_value(key: str) -> Any:
    # Expensive lookup
    pass
```

3. **Database Connections**: Always use context managers
```python
with database.get_sync_db() as conn:
    cursor = conn.execute(query)
    results = cursor.fetchall()
```

4. **Batch Operations**: Minimize N+1 queries
```python
# ❌ Bad: N+1 queries
for item in items:
    db.query(item.id)

# ✅ Good: Single batch query
db.query_all([item.id for item in items])
```

---

## 🔒 Security

### Security Checklist

- [ ] Never log sensitive data (API keys, passwords, tokens)
- [ ] Validate all user inputs
- [ ] Use parameterized queries for SQL
- [ ] Implement rate limiting for external APIs
- [ ] Sanitize file paths to prevent directory traversal
- [ ] Use HTTPS for all external requests
- [ ] Store secrets in vault, not in code
- [ ] Regular dependency security audits

### Secret Management
```python
# ❌ Never do this
API_KEY = "sk-1234567890"

# ✅ Do this instead
from vault_engine import vault_get_secret

api_key = vault_get_secret("openai_api_key")
```

### Input Validation
```python
def safe_file_read(file_path: str) -> Dict[str, Any]:
    """Read file with security checks."""
    # Validate path doesn't escape workspace
    if '..' in file_path:
        return {'status': 'error', 'message': 'Invalid path'}
    
    # Resolve to absolute path
    abs_path = os.path.abspath(file_path)
    
    # Ensure within allowed directory
    if not abs_path.startswith(WORKSPACE_ROOT):
        return {'status': 'error', 'message': 'Access denied'}
    
    # Safe to read
    with open(abs_path, 'r') as f:
        return {'status': 'success', 'data': f.read()}
```

---

## 📊 Code Review Checklist

Before submitting code:

- [ ] Code formatted with `ruff format .`
- [ ] No linting errors (`ruff check .`)
- [ ] All functions have type hints
- [ ] All public functions have docstrings
- [ ] Error handling follows standard pattern
- [ ] Tests added/updated
- [ ] No hardcoded secrets
- [ ] Logging at appropriate levels
- [ ] Constants extracted from magic numbers
- [ ] No unused imports or variables

---

## 🛠️ Quick Reference Commands

```bash
# Setup pre-commit hooks
pip install pre-commit
pre-commit install

# Format and lint
ruff format .
ruff check . --fix

# Run tests
pytest tests/ -v --tb=short

# Check dependencies
pip list --outdated
safety check -r requirements.txt

# Generate coverage report
pytest --cov=. --cov-report=html
# Open browser: firefox htmlcov/index.html
```
