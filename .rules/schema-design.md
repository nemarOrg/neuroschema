# Schema Design Rules

## Core Principles

1. **Core is frozen**: Once a field is added to `schema/core/`, changing it in a breaking way is costly for every consumer; see Versioning below for what counts as breaking and how it is versioned.

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

- Schema version follows Semantic Versioning, using the pre-1.0 `0.y.z` convention (`y` is breaking, `z` is compatible): `MAJOR.MINOR.PATCH`
- While the schema is pre-1.0, MINOR is the breaking-change bump:
  - MINOR: any breaking change and any new extension namespace.
    Breaking changes include, for example, removing, renaming, or retyping a field, making an optional field required, and tightening an existing constraint (a stricter `pattern`, a higher `minimum`, a `minItems`, or any other change that makes a previously valid document invalid).
  - PATCH: any additive change that keeps every previously valid document valid, and documentation fixes.
    Examples: a new optional field (in core or inside an existing extension) and a new `enum` value.
- A PATCH addition still requires consumers to update their schema copy: core and definitions set `additionalProperties: false`, so a document that uses the new field fails against an older copy (nemar-cli vendors a generated bundle and pins `NEUROSCHEMA_VERSION`).
- 1.0.0 is released only when the schema is completely stable.
  From 1.0.0 on, breaking changes require a MAJOR bump.

## JSON Schema Conventions

- Use draft 2020-12
- Every schema file must have `$schema`, `$id`, `title`, and `description`
- Use `$ref` for shared definitions
- Prefer `type: ["string", "null"]` over `oneOf` for nullable fields
