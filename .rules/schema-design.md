# Schema Design Rules

## Core Principles

1. **Core is frozen**: Once a field is added to `schema/core/`, removing or renaming it is a breaking change requiring a major version bump.

2. **Summaries over arrays**: The core stores aggregate summaries (counts, ranges, type distributions) rather than per-element arrays. Per-channel arrays like `channel_names` and `channel_types` belong in `extensions/rawDetail`.

3. **Extensions are namespaced**: Each project gets its own namespace under `extensions/`. New namespaces require a minor version bump and an entry in `extensionsContainer.schema.json`.

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
- MAJOR: Breaking changes to core fields (removals, renames, type changes)
- MINOR: New core fields, new extension namespaces
- PATCH: Documentation fixes, extension-only changes

## JSON Schema Conventions

- Use draft 2020-12
- Every schema file must have `$schema`, `$id`, `title`, and `description`
- Use `$ref` for shared definitions
- Prefer `type: ["string", "null"]` over `oneOf` for nullable fields
