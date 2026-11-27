# Schema Design Rules

## Core Principles

1. **Core is frozen**: Once a field is added to `schema/core/`, changing it in a breaking way is costly for every consumer; see Versioning below for what counts as breaking and how it is versioned.

2. **Summaries over arrays**: The core stores aggregate summaries (counts, ranges, type distributions) rather than per-element arrays. Per-channel arrays like `channel_names` and `channel_types` belong in `extensions/rawDetail`.

3. **Extensions are namespaced**: Each project gets its own namespace under `extensions/`. New namespaces require a MINOR version bump and an entry in `extensionsContainer.schema.json`.

4. **BIDS alignment**: Field names should align with BIDS conventions. Use `snake_case` for all field names in JSON schemas.

5. **Two document types**: The schema supports `dataset` (study-level) and `record` (per-file) documents, discriminated by the `doc_type` field.

6. **Nullable over absent**: Optional fields use `["type", "null"]` rather than being omitted, so consumers can distinguish "not provided" from "not applicable".

## Extension Guidelines

- Extensions MUST define `"additionalProperties": true` to allow forward compatibility, except `dataQuality`, which is closed at its root and in every `$defs` entry: it carries the views a browser draws, so a member no schema checks is refused rather than carried along (`test_data_quality_is_closed_everywhere`).
- Extension schemas live in `schema/extensions/`.
- Every schema file's `$id` is the absolute URI `https://raw.githubusercontent.com/nemarOrg/neuroschema/v0.6.1/schema/` plus its path under `schema/` (`neuroschema.validate.SCHEMA_BASE`), so a relative `$ref` resolves by RFC 3986 in every engine, ajv included. The `$id` is an identifier: the validator loads every file from `schema/` and never fetches one.
- Extensions can reference definitions from `schema/definitions/`.
- Objects nested inside an extension may be closed (`additionalProperties: false`); only the namespace root must stay open (`dataQuality` aside).
- Never declare `$id` below a file's root: vendoring rewrites only root `$id`s, and the validator's store maps only root `$id`s.
- Write every `$ref` below the root schema with its folder (`../definitions/x.schema.json`, `../extensions/x.schema.json`, `../core/x.schema.json`), including a ref into the same file (`../extensions/processing.schema.json#/$defs/x`, not `#/$defs/x`). jsonschema's legacy `RefResolver` pushes a resolution scope for every schema with an `$id` it enters and never pops it, so a bare or fragment-only ref can resolve against the wrong file; a folder-qualified ref resolves the same from any subfolder. `tests/test_processing_extensions.py` enforces this.
- In every schema file, end every anchored pattern with `$(?!\n)`, not a bare `$`: Python's `re` lets `$` match before a final newline, so `"x\n"` would pass here and fail in ajv. The lookahead closes that gap in both engines. `test_anchored_patterns_close_the_newline_gap` holds every schema to it, the core and the root included, with no exceptions (the four older patterns of nemarOrg/neuroschema#20 were fixed in 0.6.0).
- Every schema compiles with ajv 8 in strict mode (`strict: true`, `strictRequired: false`, the annotation keyword `x-extension-managers` declared, formats not validated): `scripts/ajv/check.ts`, which CI runs as the job `ajv`, compiles each file and replays the verdict corpus. Give a subschema that uses an array, string, number or object keyword the matching `type`, even inside an `anyOf` branch.
- Every `integer` has a `minimum` and a `maximum` within 2^53 - 1 (9007199254740991) in magnitude: past it, Python reads an integer exactly and JavaScript's `JSON.parse` reads the nearest binary64, so the two engines would give two verdicts. The validator checks the binary64 reading (`neuroschema.ijson.binary64`); `test_every_integer_is_within_2_53` holds the cap.
- Never use a token Python's `re` and JavaScript's `RegExp` read apart: a bare `.` (JavaScript's stops at U+2028 and U+2029), or the shorthand classes `\s`, `\S`, `\d`, `\D`, `\w`, `\W`, `\b` and `\B` (Unicode sets in Python, others in JavaScript). Write an explicit class instead (`[0-9]`, `[!-~]`); to match any character, write `[\s\S]`, which means the same in both. `anchor_problems` flags them in every schema.
- Patterns must be valid JavaScript regular expressions with the `u` flag (no identity escapes such as `\-` or `\_`), because nemar-cli validates with ajv. Use `pattern` rather than `format` when a check must hold in every validator: this repository's validator passes no format checker.

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
