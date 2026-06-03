# Contributing to llm-scope

Thank you for your interest in contributing! This document covers setup, workflow, and standards.

## Development Setup

```bash
# Clone and enter the repo
git clone https://github.com/yourusername/llm-scope
cd llm-scope

# Install SDK in editable mode with all extras
cd sdk && pip install -e ".[all]"
pip install pytest pytest-asyncio pytest-cov ruff mypy

# Install dashboard dependencies
cd ../dashboard && npm install

# Copy and configure environment
cd .. && cp .env.example .env
# Set POSTGRES_PASSWORD in .env

# Start all services (hot reload for development)
make dev
```

## Running Tests

```bash
# All tests
make test

# SDK only
cd sdk && pytest tests/ -v

# Backend only
cd backend && pytest tests/ -v

# With coverage
cd sdk && pytest tests/ --cov=llmscope --cov-report=html
```

## Branching Strategy

We use a simple flow:

- `main` — stable, tagged releases only. Protected.
- `develop` — integration branch, merged to `main` at release.
- `feature/<name>` — feature branches off `develop`.
- `fix/<name>` — bug fix branches off `develop` (or `main` for hotfixes).

**Workflow:**

1. Fork the repo and create a branch from `develop`
2. Make your changes with tests
3. Open a PR against `develop`
4. After review and CI passing, it gets merged

## PR Checklist

Before submitting a pull request, verify:

- [ ] Tests pass locally (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] New features include tests
- [ ] Docstrings added for public functions
- [ ] Type hints added for all Python code
- [ ] `CHANGELOG.md` updated (if applicable)
- [ ] No secrets or API keys committed

## Code Style

**Python:** We use `ruff` for linting and formatting, `mypy` for type checking.

```bash
ruff check sdk/llmscope backend/app
ruff format sdk/llmscope backend/app
mypy sdk/llmscope --ignore-missing-imports
```

Key conventions:
- Type hints on all public functions and methods
- Docstrings for all public classes and functions (Google style)
- `from __future__ import annotations` at top of all Python files
- Prefer explicit over implicit; avoid magic

**JavaScript/React:** Standard ESLint with react-hooks plugin.

```bash
cd dashboard && npm run lint
```

## Reporting Bugs

Open a GitHub issue with:
- Python/Node version
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs or tracebacks

## Feature Requests

Open a GitHub issue with the `enhancement` label. Describe the use case and proposed API.
