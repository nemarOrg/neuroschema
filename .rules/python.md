# Python Rules

## Style
- Python 3.11+
- Use Ruff for linting and formatting
- Use UV for package management
- Type hints for public APIs

## Pydantic
- Use Pydantic v2 for validation models
- Use `ConfigDict(extra="allow")` for forward compatibility
- Mirror JSON Schema structure in Python models

## Dependencies
- Keep minimal: `jsonschema`, `pydantic`, `pytest`
- Dev dependencies: `ruff`, `coverage`, `pytest-cov`
