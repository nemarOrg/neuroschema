# neuroschema Instructions

## Project Context
**Purpose:** Extensible JSON Schema for FAIR neuroimaging metadata. Defines a platform-neutral core schema for dataset discovery, interoperability, and reuse, with namespace-based extensions for downstream platforms (NEMAR, EEGDash, signalJourney, DataCite, etc.).
**Tech Stack:** JSON Schema (draft 2020-12), Python 3.11+ (validation tooling), UV package manager, Ruff linter
**Architecture:** Core + Extensions pattern (modeled after signalJourney's extension system). Core fields are stable/frozen and platform-neutral; extensions use namespaced containers for platform-specific or domain-specific metadata.

## Related Projects
- **eegdash** (`../eegdash/`): Visualization dashboard; consumes this schema for its MongoDB. See `eegdash/schemas.py` for current Pydantic/TypedDict models.
- **signalJourney** (`../../signalJourney/`): Processing pipeline schema; uses a similar core + extensions pattern. See `schema/` directory.
- **NEMAR API** (`nemar.org`): REST API serving dataset metadata; see `examples/nemar-api.md` for response format. One of several consumers of neuroschema.

## Environment Setup
```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest  # Real tests only, NO MOCKS
```

## Schema Design Principles
1. **Core is frozen:** Required fields in the core schema should rarely change. Breaking changes bump MINOR while the schema is pre-1.0 and MAJOR from 1.0.0 (see `.rules/schema-design.md`).
2. **Extensions are namespaced:** Each platform/domain gets its own namespace (e.g., `extensions.signalJourney`, `extensions.dataCite`).
3. **Summaries over raw data:** The core stores summaries (channel count, modality list) rather than raw arrays (individual channel names/types).
4. **Two levels:** Dataset-level metadata (study info) and Record-level metadata (per-file info).
5. **BIDS-aligned:** Field names and structures align with Brain Imaging Data Structure (BIDS) conventions where applicable.
6. **FAIR-aligned:** Core fields support DataCite DOI registration; structured authors and funding enable proper scholarly citation.
7. **BIDS inheritance:** Dataset-level signal defaults propagate to records unless overridden (see `docs/inheritance.md`).

## Development Workflow
1. **Check context:** Review plan.md for current tasks
2. **Branch:** `git checkout -b feature/short-description`
3. **Edit schemas:** Follow JSON Schema draft 2020-12 conventions
4. **Validate:** Run `pytest` to test schema validation
5. **Commit:** Atomic, concise messages, no emojis
6. **PR:** Reference context and issue

## Quick Commands
```bash
# Run tests
pytest tests/ --cov

# Format/lint Python
ruff check --fix . && ruff format .

# Validate a JSON file against schema
python -m neuroschema.validate examples/schema1.json
```

## Key Files
- `schema/neuroschema.schema.json` - Root schema definition
- `schema/core/` - Core field definitions (dataset + record level)
- `schema/definitions/` - Shared type definitions (demographics, BIDS entities, person, inheritable signal properties, etc.)
- `schema/extensions/` - Extension namespace definitions (dataCite, dataCategories, eegdash, nemar, signalJourney, dataQuality, rawDetail)
- `examples/` - Example JSON documents and API responses
- `docs/` - Adapter mappings, inheritance rules, extension topology

## Rules & Context (tracked in git)
- `.rules/schema-design.md` - Core vs extension rules, versioning policy
- `.rules/testing.md` - No-mocks policy, test data sources
- `.rules/git.md` - Commit and branching conventions
- `.rules/python.md` - Python style and tooling
- `.context/plan.md` - Current tasks and phases
- `.context/ideas.md` - Future extension ideas
- `.context/research.md` - Analysis of existing schemas
- `.context/scratch_history.md` - Decision log
