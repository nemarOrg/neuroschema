# neuroschema

An extensible JSON Schema for neuroimaging metadata, designed for FAIR (Findable, Accessible, Interoperable, Reusable) data sharing and reuse.

## What is neuroschema?

Neuroschema defines a standardized metadata format for neuroimaging datasets and recordings. It provides:

- **Core schema** with stable, frozen fields for dataset discovery and interoperability
- **Extension namespaces** for platform-specific or domain-specific metadata
- **BIDS alignment** following Brain Imaging Data Structure conventions
- **DataCite compatibility** for DOI registration and scholarly citation
- **Two document levels**: dataset (study-level) and record (per-file)

The core schema captures what every neuroimaging data registry needs: dataset identity, modalities, demographics, signal properties, provenance, and external links. Extensions allow individual platforms (EEGDash, NEMAR, signalJourney, etc.) to add their own fields without polluting the shared core.

## Design Principles

1. **Core is frozen** -- required fields rarely change; breaking changes bump MINOR while pre-1.0 and MAJOR from 1.0.0
2. **Summaries over raw data** -- core stores channel counts and frequency ranges, not per-channel arrays
3. **Extensions are namespaced** -- each platform or domain gets its own container
4. **BIDS inheritance** -- dataset-level signal defaults propagate to records unless overridden
5. **Nullable over absent** -- optional fields use `type: ["string", "null"]` so consumers can distinguish "not provided" from "not applicable"

## Schema Structure

```
schema/
  neuroschema.schema.json          # Root schema with doc_type discriminator
  core/
    dataset.schema.json            # Study-level metadata
    record.schema.json             # Per-file metadata
  definitions/
    inheritable.schema.json        # Signal properties (BIDS inheritance)
    person.schema.json             # Structured author/contributor
    demographics.schema.json       # Subject demographics summary
    signalSummary.schema.json      # Per-recording signal aggregates
    bidsEntities.schema.json       # BIDS path entities
    dataSummary.schema.json        # Dataset-level aggregates
    externalLinks.schema.json      # DOIs, URLs, references
    provenance.schema.json         # Dataset provenance (timestamps, version, uploader)
    recordProvenance.schema.json   # Record timestamps
    processingTypes.schema.json    # Shared processing types ($defs library)
    view.schema.json               # View declaration ($defs library)
    checkpointCounts.schema.json   # Recordings passed, failed, skipped, total
    qualityMetric.schema.json      # One metric (value, unit, bounds, producer)
  extensions/
    extensionsContainer.schema.json  # Namespace registry
    dataCite.schema.json           # DOI registration fields
    dataCategories.schema.json     # Study classification
    eegdash.schema.json            # EEGDash platform
    nemar.schema.json              # NEMAR platform
    signalJourney.schema.json      # Links to signalJourney records, per recipe
    dataQuality.schema.json        # Quality metrics and views, per recipe
    processing.schema.json         # Checkpoint outcomes, per recipe
    rawDetail.schema.json          # Per-channel arrays, BIDS sidecars
  views/
    kind.<kind>.v<N>.schema.json   # One schema per registered view kind and version (generic kinds and presets)
    content.<kind>.v<N>.schema.json  # Content of a JSON role, per content kind and version
    transform.<name>.schema.json   # One schema per registered transform (sensor-layout, ic-activity)
views/
  registry.json                    # View kinds, transforms, algorithms, formats, reserved dimensions, caps
  montages/                        # Standard montages for nemar.sensor-labels.v1, with PROVENANCE.json
  vectors/                         # Test vectors for the view algorithms, models, preset checks and verdicts
src/neuroschema/
  validate.py                      # The validator and CLI (schemas resolved from schema/, nothing fetched)
  ijson.py                         # The I-JSON reader every JSON text goes through
  records.py                       # The record checks a dataQuality entry's cross-field rules need
  views/                           # Python references: registry, digest, models, presets, sensor maps, activations
scripts/
  generate_kind_vectors.py         # Writes the generic-kind model, preset-check and verdict vectors
  generate_view_vectors.py         # Writes the sensor-field and sensor-layout vectors from eegprep
  generate_ic_activity_vectors.py  # Writes the nemar.ic-activity.v1 vectors from frozen inputs
  generate_montages.py             # Writes views/montages from MNE-Python
  ajv/check.ts                     # Compiles every schema with ajv in strict mode (CI job ajv)
```

## Quick Start

```bash
# Install, with the reference renderers' numpy (the extra views: the scalp maps, and so the full suite, need it)
uv sync --extra dev --extra views

# Validate a document (read as I-JSON; exit code 1 when invalid, 2 when unreadable)
uv run python -m neuroschema.validate examples/schema1.json

# Run tests (without the views extra, the tests that draw scalp maps are skipped)
uv run pytest tests/

# Regenerate or check the vectors (the group vectors holds eegprep, MNE-Python and scipy)
uv run python scripts/generate_kind_vectors.py --check
uv run --python 3.12 --extra views --group vectors python scripts/generate_ic_activity_vectors.py --check

# Compile the schemas with ajv, as the CI job ajv does
bun install --frozen-lockfile --cwd scripts/ajv && bun scripts/ajv/check.ts
```

## Documentation

- [BIDS Inheritance](docs/inheritance.md) -- how dataset defaults propagate to records
- [Extension Managers](docs/extension-managers.md) -- MongoDB collection topology and access control
- [Processing Extensions](docs/processing-extensions.md) -- dataQuality, processing and signalJourney: levels, invariants, checkpoints
- [Quality Views](docs/views.md) -- view declarations, kinds, the renderer rule, data roles, formats and digests
- [Generic Kinds](docs/views/generic-kinds.md) -- the models a renderer builds for tables, line charts, heatmaps and histograms
- [Presets](docs/views/presets.md) -- spectrum, component maps, component classes, activations and the signal window, each over a generic kind
- [Component Activations](docs/views/ic-activity.md) -- the transform `nemar.ic-activity.v1` and its display filter
- [Scalp Maps](docs/views/sensor-field.md) -- the algorithm `nemar.sensor-field.v1` and the kind that draws it
- [Sensor Labels](docs/views/sensor-labels.md) -- `nemar.sensor-labels.v1`: positions from channel names and standard montages
- [Sensor Layout](docs/views/sensor-layout.md) -- the transform `nemar.sensor-layout.v1`: three-dimensional positions to a layout
- [View Digest](docs/views/view-digest.md) -- `nemar.view-digest.v1`, the SHA-256 of a declaration's canonical JSON
- [EEGDash Adapter](docs/adapter-eegdash.md) -- field mapping for EEGDash migration
- [DataCite Adapter](docs/adapter-datacite.md) -- field mapping for DOI registration

## Version

Current: **0.6.0** (pre-1.0: a MINOR bump marks a breaking change or a new extension namespace; a PATCH bump marks an additive optional field or a doc fix; 1.0.0 only when the schema is completely stable)

JSON Schema draft: **2020-12**

Changes: [CHANGELOG.md](CHANGELOG.md)

## License

BSD-3-Clause
