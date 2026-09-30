# Schema Design Rules

## Core Principles

1. **Core is frozen**: Once a field is added to `schema/core/`, removing or renaming it is a breaking change (a MINOR bump while the schema is pre-1.0, a MAJOR bump from 1.0.0).

2. **Summaries over arrays**: The core stores aggregate summaries (counts, ranges, type distributions) rather than per-element arrays. Per-channel arrays like `channel_names` and `channel_types` belong in `extensions/rawDetail`.

3. **Extensions are namespaced**: Each project gets its own namespace under `extensions/`. New namespaces require a MINOR version bump and an entry in `extensionsContainer.schema.json`.

4. **BIDS alignment**: Field names should align with BIDS conventions. Use `snake_case` for all field names in JSON schemas.

5. **Two document types**: The schema supports `dataset` (study-level) and `record` (per-file) documents, discriminated by the `doc_type` field.

6. **Nullable over absent**: Optional fields use `["type", "null"]` rather than being omitted, so consumers can distinguish "not provided" from "not applicable".

## Extension Guidelines

- Extensions MUST define `"additionalProperties": true` to allow forward compatibility.
- Extension schemas live in `schema/extensions/`.
- Each extension gets a `$id` matching its filename.
- Extensions can reference definitions from `schema/definitions/`.

## Versioning

- Schema version follows Semantic Versioning: `MAJOR.MINOR.PATCH`
- While the schema is pre-1.0, MINOR is the breaking-change bump:
  - MINOR: any breaking change (removing, renaming, or retyping a field, or making one required) and any new extension namespace
  - PATCH: additive optional fields (in core or inside an existing extension) and documentation fixes
- 1.0.0 is released only when the schema is completely stable.
  From 1.0.0 on, breaking changes require a MAJOR bump.

## JSON Schema Conventions

- Use draft 2020-12
- Every schema file must have `$schema`, `$id`, `title`, and `description`
- Use `$ref` for shared definitions
- Prefer `type: ["string", "null"]` over `oneOf` for nullable fields
