# Processing extensions: dataQuality, processing and signalJourney

These three namespaces (neuroschema 0.5.0) carry what the NEMAR backend indexes from its recipe runs.
The signalJourney record a run writes stays the source of every step, parameter and metric; these documents are projections of those records, each carrying the SHA-256 of the record it came from.
The NEMAR backend (`nemar-api`) is the only writer of all three.

## Levels and keys

| Namespace | Levels | Shape selector | Keyed by |
|---|---|---|---|
| `dataQuality` | record and dataset | `level`: `record` or `dataset` | `recipes.<recipe id>` |
| `processing` | record and dataset | `level`: `record` or `dataset` | `recipes.<recipe id>` |
| `signalJourney` | record and dataset (same shape) | none | `recipes.<recipe id>` |

One entry per recipe: a recording processed by `nemar-floor` and `nemar-ica` has two entries.
Each `dataQuality` entry records its `input_kind` (`bids` or `zarr`) and `profile` (`archive` or `serving`); a `zarr` input always describes the serving copy.

## What the schema checks and what the writer must check

The schema checks types, closed objects, identifier patterns, the figure format list and its match with the file extension, and the status rules (a passed checkpoint has no code; a completed link has a location, digest and signalJourney version).
JSON Schema cannot compare one value with another, so the writer enforces:

- every checkpoint's counts satisfy passed + failed + skipped = total once reconciled (at most total while a run reports live);
- every checkpoint of one run has the same total, and the `dataQuality` dataset `counts.total` equals it;
- the keys of a dataset `processing` entry's `counts` equal its `declared_checkpoints`;
- after a recording's first non-passed checkpoint, every later declared checkpoint is `skipped` with the same `code` and `step`;
- each checkpoint name is one the recipe version declares in the registry;
- a histogram has one count fewer than its edges, its edges strictly increase, and `n` = sum(counts) + underflow + overflow;
- every range (a metric's `bounds`, each `observed_range` entry) has min <= max when both are set.

`tests/helpers.py` checks the examples against these rules; the package does not ship them.

## Checkpoints

The standard checkpoints, in order: `import`, `preprocess`, `ica`, `iclabel`, `quality`, `figures`, then `stored`, which the backend sets when the derivatives are copied.
A recipe declares the subset it runs; the names are an open vocabulary (`^[a-z][a-z0-9_]{0,31}$`) so a new checkpoint needs no schema release.

## Digests and locations

Every digest is the SHA-256 of a file's bytes.
Every `location` is a relative POSIX path inside the run's product (the same string as the signalJourney `outputTargets` location): no leading slash, no `..` segment, no URI scheme, no backslash, no control characters.
Paths are not normalized: `./a`, `a//b` and a trailing `/` are accepted, so the writer emits the canonical form.
Figure size caps and the rule that a time-series figure is raster only (PNG or WebP) belong to signalJourney's `nemar` namespace, not here.

## From qc-summary.v1 to the dataQuality dataset level

| qc-summary.v1 | dataQuality dataset entry |
|---|---|
| `format` | dropped (the namespace is the format) |
| `dataset_id` | the core document's `dataset_id` |
| `recipe` (fixed `nemar-floor`) | the `recipes` map key (any recipe) |
| `recipe_version`, `dataset_version`, `input_kind`, `profile` | same names |
| `describes` | dropped (follows from `profile`) |
| `record_sha256` | same name |
| `discovered`, `succeeded`, `failed`, `skipped` | `counts.total`, `counts.passed`, `counts.failed`, `counts.skipped` |
| `distributions` | same, keyed by metric name, numeric edges |
| (none) | `observed_range`: lowest and highest value per metric observed across recordings (a metric's `bounds` is instead the valid range its plugin declares) |
| `not_processed`, `not_processed_truncated` | same names |

## Reusable definitions

Other schemas reference these by path (`../definitions/...`, `../extensions/...`); in nemar-cli's vendored bundle they become `nsc:/definitions/...` and `nsc:/extensions/...`:

- `checkpointCounts.schema.json`: the counts shape nemar-cli's live progress object reuses;
- `qualityMetric.schema.json`: the metric shape a plugin manifest declares for each metric output;
- `dataQuality.schema.json#/$defs/datasetRecipeSummary`: the dataset quality summary the backend projects from a recipe run.
