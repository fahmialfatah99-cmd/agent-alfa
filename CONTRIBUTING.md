# Contributing to ALFA Agent

First off, thank you for considering contributing to ALFA Agent! It's people like you that make ALFA Agent such a great AI agent ecosystem.

## Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible:

* **Use a clear and descriptive title**
* **Describe the exact steps which reproduce the problem**
* **Provide specific examples to demonstrate the steps**
* **Describe the behavior you observed after following the steps**
* **Explain which behavior you expected to see instead and why**
* **Include screenshots if possible**
* **Include environment details**: OS, Python version, installed packages

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, please include:

* **Use a clear and descriptive title**
* **Provide a detailed description of the suggested enhancement**
* **Explain why this enhancement would be useful**
* **List some examples of how this enhancement would be used**

### Pull Requests

* Fill in the required template
* Follow the Python style guide (PEP 8)
* Include tests for new features
* Update documentation as needed
* Ensure all tests pass before submitting

## Development Setup

### Prerequisites

- Python 3.10+
- Git
- pip or poetry

### Setting Up Your Environment

1. **Fork the repository**
2. **Clone your fork:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/alfa-agent.git
   cd alfa-agent
   ```

3. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -e .  # Install in development mode
   ```

5. **Install development dependencies:**
   ```bash
   pip install pytest pytest-cov black flake8 mypy
   ```

## Coding Guidelines

### Python Style Guide

* Follow [PEP 8](https://pep8.org/) for Python code style
* Use type hints where possible
* Keep functions small and focused (max 50 lines recommended)
* Write docstrings for public functions and classes

### Type Hints

```python
from typing import Optional, List, Dict, Any

def process_data(
    items: List[str],
    config: Optional[Dict[str, Any]] = None
) -> bool:
    """Process a list of items with optional configuration."""
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def calculate_score(value: float, threshold: float = 0.5) -> bool:
    """Calculate whether a value exceeds the threshold.
    
    Args:
        value: The numeric value to evaluate
        threshold: The threshold for comparison (default: 0.5)
    
    Returns:
        True if value exceeds threshold, False otherwise
    
    Raises:
        ValueError: If value is not a valid number
    """
    pass
```

### Testing

* Write unit tests for new features
* Maintain or improve test coverage
* Run tests before submitting PR:
  ```bash
  pytest tests/ -v --cov=alfa --cov-report=html
  ```

### Security Considerations

* Never commit credentials or API keys
* Use environment variables for sensitive data
* Follow security best practices in code
* Report security vulnerabilities privately

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
feat: add new swarm coordination algorithm
fix: resolve memory leak in vector store
docs: update installation instructions
style: format code with black
refactor: extract tool validation logic
test: add unit tests for permission gate
chore: update dependencies
```

## Code Review Process

1. Submit a pull request
2. Automated CI checks will run
3. Maintainers will review the code
4. Address any feedback or requested changes
5. Once approved, your PR will be merged

## Questions?

Feel free to open an issue with the "question" label for any queries.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
