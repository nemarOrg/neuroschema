# Testing Rules

## No Mocks Policy

All tests must validate against real data. No mock data, mock classes, or artificial fixtures.

## Test Data

- Use the example JSON files in `examples/` as test fixtures.
- The `schema1.json` and `schema2.json` are real MongoDB exports from EEGDash.
- The `nemar-api.md` contains a real NEMAR API response.

## Validation Tests

- Every schema file must have at least one positive (valid) and one negative (invalid) test case.
- Test that required fields are enforced.
- Test that `additionalProperties` constraints work as expected.
- Test extension loading in isolation and as part of the full schema.

## Running Tests

```bash
pytest tests/ --cov
```
