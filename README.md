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
    checkpointCounts.schema.json   # Recordings passed, failed, skipped, total
    qualityMetric.schema.json      # One plugin metric (value, unit, bounds, plugin)
  extensions/
    extensionsContainer.schema.json  # Namespace registry
    dataCite.schema.json           # DOI registration fields
    dataCategories.schema.json     # Study classification
    eegdash.schema.json            # EEGDash platform
    nemar.schema.json              # NEMAR platform
    signalJourney.schema.json      # Links to signalJourney records, per recipe
    dataQuality.schema.json        # Quality metrics and figures, per recipe
    processing.schema.json         # Checkpoint outcomes, per recipe
    rawDetail.schema.json          # Per-channel arrays, BIDS sidecars
```

## Quick Start

```bash
# Install
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Validate a document
python -m neuroschema.validate examples/schema1.json

# Run tests
pytest tests/
```

## Documentation

- [BIDS Inheritance](docs/inheritance.md) -- how dataset defaults propagate to records
- [Extension Managers](docs/extension-managers.md) -- MongoDB collection topology and access control
- [Processing Extensions](docs/processing-extensions.md) -- dataQuality, processing and signalJourney: levels, invariants, checkpoints
- [EEGDash Adapter](docs/adapter-eegdash.md) -- field mapping for EEGDash migration
- [DataCite Adapter](docs/adapter-datacite.md) -- field mapping for DOI registration

## Version

Current: **0.5.0** (pre-1.0: a MINOR bump marks a breaking change or a new extension namespace; a PATCH bump marks an additive optional field or a doc fix; 1.0.0 only when the schema is completely stable)

JSON Schema draft: **2020-12**

Changes: [CHANGELOG.md](CHANGELOG.md)

## License

BSD-3-Clause
