# Changelog

All notable changes to neuroschema are recorded here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
While the schema is pre-1.0, a MINOR bump marks a breaking change or a new extension namespace (`.rules/schema-design.md`).

## [Unreleased]

Quality views replace figures: a view is data a browser draws, declared with a namespaced, versioned kind (nemarOrg/neuroschema#21, part of nemarOrg/nemar-cli#2324).

### Added

- `schema/definitions/view.schema.json`: the view declaration (`$defs/view`): key, namespaced `kind` and `kind_version`, optional `base`, caption, source (a plugin or a recipe), scope (`recording`; `subject`, `dataset` and `collection` reserved, with `sources`), parameters, stored `data[]` (role, location, format, size, SHA-256, columns, dimensions, coordinate system, position source) and computed `inputs[]` (a product file or a serving store, each by digest) with a named, versioned `transform`. A kind the registry does not list passes on this envelope; a listed kind is also checked against its own schema.
- `schema/views/kind.nemar.table.v1.schema.json`: the generic table kind (one TSV file in role `table`, with columns and no dimensions).
- `schema/views/kind.nemar.lines.v1.schema.json`, `kind.nemar.heatmap.v1.schema.json` and `kind.nemar.histogram.v1.schema.json`: the generic line chart (one TSV file in role `values`: a strictly increasing x column along the rows and one numeric series per value column), heatmap (one TSV file in role `values`: one flat cell per stored value, row and column labels, `minmax` or `absmax` limits) and histogram (one JSON file in role `histogram`) kinds, dispatched from `view.schema.json` and registered with open dimension names (`dims: null`).
- `schema/views/content.nemar.histogram.v1.schema.json`: a histogram's content, binned by numeric edges (`edges`, `counts`, `underflow`, `overflow`, optional `unit`; the shape of a `dataQuality` distribution's histogram) or by category (`categories`, `counts`), open for a preset's own members. The registry names it in the role's new `content` member.
- `docs/views/generic-kinds.md`: the model a renderer builds for `nemar.table`, `nemar.lines`, `nemar.heatmap` and `nemar.histogram` version 1 and for the fallback (how TSV and JSON files and their cells are read, coordinates, value columns, the readout that snaps to a stored row, the bin rule `[e_i, e_i+1)` with the last bin closed, color limits, caps), with the words a renderer refuses with and the order of its checks.
- `nemar.kinds-models.v1` and `nemar.kinds-verdicts.v1`: `views/vectors/kinds-models.v1.json` (models, readouts, bins and refusals every renderer reproduces) and `views/vectors/kinds-verdicts.v1.json` (declarations and contents with the schemas' verdicts, for a renderer without a JSON Schema engine), written by `scripts/generate_kind_vectors.py` (`--check` in the test suite), and the Python reference `neuroschema.views.build_model`.
- `views/registry.json` (`neuroschema.views-registry.v1`): kinds, transforms, algorithms, formats (`tsv`, `json`), reserved dimension names and caps.
- `nemar.view-digest.v1`, the SHA-256 of a declaration's RFC 8785 canonical JSON over I-JSON input (no duplicate member names): `docs/views/view-digest.md`, vectors in `views/vectors/view-digest.v1.json`, and the Python reference `neuroschema.views.view_digest` with `parse_declaration`, which reads strict UTF-8 text and refuses duplicate member names.
- `neuroschema.views`: the registry reader and the renderer rule (`draw_as`), which draws an unknown kind by its base only when each of the base's roles is valid under the base kind's schema (`meets_role_contract`, `role_schemas`), offering the other files for download, and otherwise shows a table.
- `processingTypes`: `viewKey`, `kindName`, `transformName`, `roleName`, `dimName`, `formatName` and `recipe`.
- `docs/views.md`: the view vocabulary, the renderer rule, data roles, dimensions, inputs, scope, formats, caps, versioning and what digests prove.

### Changed (breaking)

- `dataQuality` record level: `figures` is replaced by the required `views` (at most 32 view declarations), and `$defs/figure` is removed.
- `dataQuality` dataset level: each distribution requires `unit` and may carry `description`.

### Changed

- `qualityMetric`: the producer is exactly one of `plugin` and `recipe`, so a recipe's own metric names its recipe.
- `processingTypes`: `figures` leaves the `checkpointName` examples.
- CI and the typo check run on pull requests into `feature/**` branches.

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
