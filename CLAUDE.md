# neuroschema Instructions

## Project Context
**Purpose:** Extensible JSON Schema for NEMAR neuroimaging metadata. Defines a frozen core schema used by the NEMAR API and EEGDash MongoDB, with namespace-based extensions for downstream projects (signalJourney, data quality, data categories, etc.).
**Tech Stack:** JSON Schema (draft 2020-12), Python 3.11+ (validation tooling), UV package manager, Ruff linter
**Architecture:** Core + Extensions pattern (modeled after signalJourney's extension system). Core fields are stable/frozen; extensions use namespaced containers.

## Related Projects
- **eegdash** (`../eegdash/`): Visualization dashboard; consumes this schema for its MongoDB. See `eegdash/schemas.py` for current Pydantic/TypedDict models.
- **signalJourney** (`../../signalJourney/`): Processing pipeline schema; uses a similar core + extensions pattern. See `schema/` directory.
- **NEMAR API** (`nemar.org`): REST API serving dataset metadata; see `examples/nemar-api.md` for response format.

## Environment Setup
```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate neuroschema  # or use uv venv
uv pip install -e ".[dev]"
pytest  # Real tests only, NO MOCKS
```

## Schema Design Principles
1. **Core is frozen:** Required fields in the core schema should rarely change. Breaking changes require major version bumps.
2. **Extensions are namespaced:** Each project/domain gets its own namespace (e.g., `extensions.signalJourney`, `extensions.dataQuality`).
3. **Summaries over raw data:** The core stores summaries (channel count, modality list) rather than raw arrays (individual channel names/types).
4. **Two levels:** Dataset-level metadata (study info) and Record-level metadata (per-file info), following EEGDash's existing pattern.
5. **BIDS-aligned:** Field names and structures align with Brain Imaging Data Structure (BIDS) conventions where applicable.

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
- `schema/definitions/` - Shared type definitions (demographics, BIDS entities, etc.)
- `schema/extensions/` - Extension namespace definitions
- `examples/` - Example JSON documents and API responses

## Rules & Context (tracked in git)
- `.rules/schema-design.md` - Core vs extension rules, versioning policy
- `.rules/testing.md` - No-mocks policy, test data sources
- `.rules/git.md` - Commit and branching conventions
- `.rules/python.md` - Python style and tooling
- `.context/plan.md` - Current tasks and phases
- `.context/ideas.md` - Future extension ideas
- `.context/research.md` - Analysis of existing schemas
- `.context/scratch_history.md` - Decision log
