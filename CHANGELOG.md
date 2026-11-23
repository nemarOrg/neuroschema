# Changelog

All notable changes to neuroschema are recorded here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
While the schema is pre-1.0, a MINOR bump marks a breaking change or a new extension namespace (`.rules/schema-design.md`).

## [Unreleased]

Quality views replace figures: a view is data a browser draws, declared with a namespaced, versioned kind (nemarOrg/neuroschema#21, part of nemarOrg/nemar-cli#2324).

### Added

- `schema/definitions/view.schema.json`: the view declaration (`$defs/view`): key, namespaced `kind` and `kind_version`, optional `base`, caption, source (a plugin or a recipe), scope (`recording`; `subject`, `dataset` and `collection` reserved, with `sources`), parameters, stored `data[]` (role, location, format, size, SHA-256, columns, dimensions, coordinate system, position source) and computed `inputs[]` (a product file or a serving store, each by digest) with a named, versioned `transform`. A kind the registry does not list passes on this envelope; a listed kind is also checked against its own schema.
- `schema/views/kind.nemar.table.v1.schema.json`: the generic table kind (one TSV file in role `table`, with columns and no dimensions).
- `views/registry.json` (`neuroschema.views-registry.v1`): kinds, transforms, algorithms, formats (`tsv`, `json`), reserved dimension names and caps.
- `nemar.view-digest.v1`, the SHA-256 of a declaration's RFC 8785 canonical JSON over I-JSON input (no duplicate member names): `docs/views/view-digest.md`, vectors in `views/vectors/view-digest.v1.json`, and the Python reference `neuroschema.views.view_digest` with `parse_declaration`, which reads strict UTF-8 text and refuses duplicate member names.
- `neuroschema.views`: the registry reader and the renderer rule (`draw_as`), which draws an unknown kind by its base only when each of the base's roles is valid under the base kind's schema (`meets_role_contract`, `role_schemas`), offering the other files for download, and otherwise shows a table.
- `processingTypes`: `viewKey`, `kindName`, `transformName`, `roleName`, `dimName`, `formatName` and `recipe`.
- `docs/views.md`: the view vocabulary, the renderer rule, data roles, dimensions, inputs, scope, formats, caps, versioning and what digests prove.
- `nemar.sensor-field.v1`, the scalp map (EEGLAB's topoplot, with eegprep at `edf694c8` as the reference), and the kind `nemar.sensor-field` version 1 that draws with it (`schema/views/kind.nemar.sensor-field.v1.schema.json`: a `values` role of one or more maps over a `sensor` dimension, and an optional `layout` role of name, theta and radius; without a layout, the sensors are names placed by `nemar.sensor-labels.v1`). `docs/views/sensor-field.md` states the algorithm outright, including what eegprep leaves implicit: sensors within 1e-3 merge at their mean value, fewer than 3 interpolated sensors are refused, the interpolation matrix is solved by lower-upper (LU) decomposition with partial pivoting and no regularization, and maps with nothing to draw are refused with a word.
- `nemar.sensor-layout.v1`, three-dimensional positions to a layout: rotation into the anterior-left-superior (ALS) frame from the Brain Imaging Data Structure (BIDS) frame table (no default frame: an unknown one is `frame_unknown`; template positions, `n/a` with a montage, are right-anterior-superior), an algebraic sphere-fit center (the centroid when coplanar), and eegprep's `cart2topo` (`docs/views/sensor-layout.md`, `schema/views/transform.nemar.sensor-layout.v1.schema.json`, which `view.schema.json` applies to every view that names the transform).
- Vectors `views/vectors/sensor-field.v1.json` (32 to 256 sensors, duplicates, near duplicates, sensors outside the head and the interpolation square, values and places that are not finite, constant and refused maps) and `views/vectors/sensor-layout.v1.json`, written from eegprep by `scripts/generate_view_vectors.py`, whose `--check` CI runs on Python 3.12.
- The Python reference renderers `neuroschema.views.sensor_field` and `neuroschema.views.sensor_layout` (with `neuroschema.views.linalg`), numpy only, as the optional extra `views`; the dependency group `vectors` installs eegprep at the reference commit and scipy for the generator.
- `neuroschema.views.optional_roles`: a kind marks a role optional with a `contains` clause whose `minContains` is 0.

### Changed (breaking)

- `dataQuality` record level: `figures` is replaced by the required `views` (at most 32 view declarations), and `$defs/figure` is removed.
- `dataQuality` dataset level: each distribution requires `unit` and may carry `description`.

### Changed

- `qualityMetric`: the producer is exactly one of `plugin` and `recipe`, so a recipe's own metric names its recipe.
- `processingTypes`: `figures` leaves the `checkpointName` examples.
- CI and the typo check run on pull requests into `feature/**` branches.
- The role contract (`meets_role_contract`) requires each role a kind requires exactly once and each optional role at most once, and validates the view's entries in the kind's roles together under the kind schema's `data` subschema, so a rule across roles holds for a preset drawn by its base.
- The reserved dimension `sensor`: without a layout role, its coordinates are names a renderer places with `nemar.sensor-labels.v1`.

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
