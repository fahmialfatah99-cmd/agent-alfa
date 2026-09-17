# Testing Guide

This guide provides comprehensive instructions for testing the ALFA Agent project.

## Quick Start

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=alfa --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov\\index.html  # Windows
```

## Test Commands

### Basic Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_comprehensive.py

# Run specific test class
pytest tests/test_comprehensive.py::TestCoreAgent

# Run specific test function
pytest tests/test_comprehensive.py::TestCoreAgent::test_agent_initialization
```

### Coverage Reporting

```bash
# Generate terminal coverage report
pytest --cov=alfa --cov=. --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=alfa --cov=. --cov-report=html

# Generate XML coverage report (for CI/CD)
pytest --cov=alfa --cov=. --cov-report=xml

# Generate all formats
pytest --cov=alfa --cov=. --cov-report=term-missing --cov-report=html --cov-report=xml
```

### Test Selection

```bash
# Run only fast tests (exclude slow tests)
pytest -m "not slow"

# Run only integration tests
pytest -m integration

# Run only security tests
pytest -m security

# Run only RAG-related tests
pytest -m rag

# Run only swarm intelligence tests
pytest -m swarm

# Run tests by keyword
pytest -k "agent"
pytest -k "security"
```

### Code Quality

```bash
# Run linting
ruff check .

# Auto-fix linting issues
ruff check . --fix

# Check code formatting
black --check .

# Format code
black .

# Type checking
mypy --ignore-missing-imports alfa/

# Run all quality checks
pre-commit run --all-files
```

## Test Fixtures

The `conftest.py` file provides these fixtures:

- `test_env`: Test environment variables
- `temp_dir`: Temporary directory
- `temp_file`: Temporary file creator
- `mock_llm_response`: Mock LLM response
- `async_mock`: Async mock for async functions
- `sample_tool_config`: Sample tool configuration
- `sample_agent_config`: Sample agent configuration
- `sample_vector_data`: Sample vector data for RAG
- `mock_database_connection`: Mock database connection
- `sample_swarm_agents`: Sample swarm agents
- `security_context`: Security context for permission tests
- `rate_limiter`: Rate limiter for API testing
- `cache_fixture`: Simple cache for testing

## Custom Markers

Use these markers to categorize tests:

- `@pytest.mark.slow`: Long-running tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.security`: Security-related tests
- `@pytest.mark.rag`: RAG functionality tests
- `@pytest.mark.swarm`: Swarm intelligence tests

Example:
```python
@pytest.mark.security
def test_whitelist_enforcement(security_context):
    assert security_context["whitelist_status"] is True
```

## Continuous Integration

Tests are automatically run on GitHub Actions:

1. **CI Workflow** (`ci.yml`): Runs on every push/PR
   - Linting with Ruff
   - Type checking with MyPy
   - Tests with pytest
   - Coverage reporting to Codecov

2. **Code Quality Workflow** (`code-quality.yml`): Enhanced quality checks
   - Coverage reporting
   - Security scanning with Bandit
   - Dependency vulnerability checks with Safety
   - Code formatting checks with Black

## Best Practices

### Writing Tests

1. **Use fixtures**: Leverage provided fixtures in `conftest.py`
2. **Follow naming**: Use `test_` prefix for test functions
3. **Keep tests independent**: Each test should run in isolation
4. **Use appropriate markers**: Mark slow, integration, and security tests
5. **Mock external services**: Never call real APIs in unit tests

### Example Test

```python
import pytest
from unittest.mock import MagicMock

@pytest.mark.security
def test_tool_whitelist_enforcement(sample_tool_config, security_context):
    """Test that tools are properly whitelisted."""
    # Arrange
    tool = sample_tool_config
    context = security_context
    
    # Act & Assert
    assert tool["whitelisted"] is True
    assert context["whitelist_status"] is True
```

### Coverage Goals

- **Overall**: >80% line coverage
- **Core modules**: >90% line coverage
- **Security modules**: 100% branch coverage
- **Integration tests**: Critical path coverage

## Troubleshooting

### Common Issues

**Import errors:**
```bash
# Ensure you're in the project root
cd /workspace

# Install in editable mode
pip install -e ".[dev]"
```

**Test not found:**
```bash
# Check test naming
pytest --collect-only

# Run with pattern matching
pytest -k "pattern"
```

**Coverage not generated:**
```bash
# Ensure pytest-cov is installed
pip install pytest-cov

# Specify source explicitly
pytest --cov=alfa --cov=.
```

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [Coverage.py documentation](https://coverage.readthedocs.io/)
- [Ruff documentation](https://beta.ruff.rs/docs/)
- [MyPy documentation](https://mypy.readthedocs.io/)
