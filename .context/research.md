# neuroschema Research

## Existing Schema Patterns Analyzed

### EEGDash schemas.py
- Two-level hierarchy: Dataset (study-level) and Record (per-file)
- Pydantic models for API validation, TypedDicts for runtime performance
- Uses `ConfigDict(extra="allow")` for forward compatibility
- Storage abstraction: backend (s3/https/local), base URI, keys
- Demographics, Tags, Clinical, ExternalLinks as nested structures

### signalJourney Schema
- JSON Schema draft 2020-12
- Core + Extensions pattern with namespace-based containers
- Extensions container allows `additionalProperties: true`
- References shared definitions via `$ref`
- Semantic versioning for both spec and schema versions

### Current MongoDB Documents (schema1.json, schema2.json)
- Very verbose: per-channel arrays dominate document size
- Duplicate data: `channel_names` appears both at top level and inside `rawdatainfo`
- `eeg_json` contains BIDS sidecar data (task description, equipment, filter settings)
- `participant_tsv` and `channel_tsv` hold parsed BIDS TSV content
- `bidsdependencies` lists all related BIDS files

### NEMAR API Response
- Dataset-level summary with study metadata
- Includes BrainLife integration flag, HED version, modalities list
- Uses `===NEMAR-SEP===` as a separator in multi-value text fields
- nemar.json adds visualization status, warnings, channel system info

### DataCite Metadata Schema 4.5
- Required: Identifier (DOI), Creator, Title, Publisher, PublicationYear, ResourceType
- Recommended: Subject, Contributor, FundingReference, RelatedIdentifier, Description
- Core neuroschema fields map to most required/recommended DataCite properties
- dataCite extension covers the rest (publisher, contributors, related identifiers, geo locations)

## Key Insight
The current system conflates raw BIDS file content (channel arrays, TSV data) with summary metadata. Neuroschema cleanly separates these: core for discovery/filtering (FAIR-aligned, platform-neutral), extensions for detailed data access (platform-specific).
