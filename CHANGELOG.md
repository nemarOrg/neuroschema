# Changelog

All notable changes to neuroschema are recorded here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
While the schema is pre-1.0, a MINOR bump marks a breaking change or a new extension namespace (`.rules/schema-design.md`).

## [0.5.0] - 2026-11-22

Processing metadata for NEMAR's pipeline checkpoints, live progress and quality plugins (nemarOrg/neuroschema#18).

### Added

- `processing` extension namespace: per recording and recipe, each checkpoint's outcome (`passed`, `failed`, `skipped`, with failure code and step); per dataset and recipe, the declared checkpoints and reconciled counts.
- `schema/definitions/checkpointCounts.schema.json`: the counts shape (passed, failed, skipped, total), reused by nemar-cli's live progress object.
- `schema/definitions/qualityMetric.schema.json`: one plugin metric (value, unit, description, optional `bounds` as the plugin-declared valid range, producing plugin).
- `schema/definitions/processingTypes.schema.json`: shared identifier, digest, location and plugin types.
- Examples `examples/dataset-ds002718-processing.json` and `examples/record-ds002718-processing.json`.

### Changed (breaking)

- `dataQuality`: the placeholder fields `quality_score`, `quality_flags` and `assessed_at` are removed. The namespace now requires `level` (`record` or `dataset`) and `recipes`: at record level, typed metrics and figures (PNG, SVG or WebP, with size, SHA-256 and caption) per recipe; at dataset level, the quality control summary per recipe (counts, distributions, `observed_range`, not-processed list), which replaces nemar-process `qc-summary.v1`. Each entry carries the SHA-256 of the signalJourney record it came from.
- `signalJourney`: the placeholder fields `pipeline_id`, `processing_status` and `sj_version` at the namespace root are removed. The namespace now requires `recipes`, one link per recipe with `recipe_version`, `processing_status` (`in_progress`, `completed`, `failed`; `pending` is gone), `location`, `sha256` and `sj_version`.

### Changed

- Every `$ref` below the root schema names its folder (for example `../extensions/dataQuality.schema.json`); resolution targets are unchanged.
- `x-extension-managers`: `dataQuality` and `signalJourney` move from `nemar-pipeline` and `signal-journey` to `nemar-api`, which also writes the new `processing` namespace. `dataQuality` and `signalJourney` now also appear on dataset documents, not only on records.
- Every anchored pattern in the new and changed files ends with `$(?!\n)`, so a trailing newline fails in Python as it does in ajv.

### Documentation

- `docs/extension-managers.md`: the NEMAR backend (`nemar-api`) writes `dataQuality`, `processing` and `signalJourney`.
- New `docs/processing-extensions.md`: levels, writer-enforced invariants, checkpoints, digest and location rules, and the mapping from `qc-summary.v1`.

## Earlier versions

See the git tags and history.
