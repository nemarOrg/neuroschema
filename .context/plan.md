# neuroschema Plan

## Phase 1: Schema Foundation
- [x] Define core dataset schema with required fields
- [x] Define core record schema with required fields
- [x] Create definitions for shared types (demographics, BIDS entities, signal summary)
- [x] Create extension container with initial namespaces (eegdash, signalJourney, nemar, dataQuality, rawDetail)
- [x] Add Python validation tooling (jsonschema-based)
- [x] Add example documents that conform to the new schema
- [x] Write tests validating examples against schema

## Phase 2: Schema Redesign (v0.2.0) -- Issues #4, #5, #6
- [x] Core restructuring: inheritable signal properties, record provenance, BIDS inheritance pattern
- [x] Record completeness: required modality, datatype/suffix/file_extension, signal_properties
- [x] Dataset enrichment: structured authors (person.schema.json), structured funding, datatypes, sessions, description
- [x] New extensions: dataCite (DOI registration), dataCategories (study classification)
- [x] Existing extension updates: eegdash (senior_author, contact_info, ages), rawDetail (electrode_tsv, events_tsv)
- [x] Extension managers: x-extension-managers metadata for MongoDB collection mapping
- [x] Updated examples (schema1.json, schema2.json) conforming to v0.2.0
- [x] Adapter docs: inheritance.md, extension-managers.md, adapter-eegdash.md, adapter-datacite.md
- [x] Validation tests: 30 tests covering positive, negative, extension isolation, BIDS entities, dataset enrichment
- [ ] Update validate.py to use `referencing` library (RefResolver deprecated)

## Phase 3: Migration Mapping
- [ ] Document mapping from current EEGDash MongoDB documents to neuroschema
- [ ] Document mapping from NEMAR API responses to neuroschema
- [ ] Create migration scripts or adapters

## Phase 4: Integration
- [ ] Update EEGDash `schemas.py` to align with neuroschema
- [ ] Add signalJourney cross-references
- [ ] Define data quality extension fields based on quality assessment needs

## Phase 5: Documentation
- [ ] Schema documentation site (MkDocs)
- [ ] Contribution guide for adding new extensions
- [ ] Version changelog

## Design Decisions

### What goes in core vs extensions?
- **Core (frozen, platform-neutral):** dataset_id, name, description, source, recording_modality, structured authors/funding, BIDS entities, inheritable signal properties, signal summary (counts, rates), demographics summary, external links, provenance
- **Extensions (platform/domain-specific):** per-channel arrays (rawDetail), storage backends (eegdash), processing pipeline refs (signalJourney), NEMAR API fields (nemar), quality metrics (dataQuality), DataCite registration fields (dataCite), study classification (dataCategories)

### Why separate rawDetail?
The existing MongoDB documents contain large per-channel arrays (channel_names, channel_types, channel_tsv) that can be 100+ elements. These are useful for detailed queries but not for dataset discovery. Keeping them in an extension means the core document stays small for search/filter operations.

### FAIR alignment
Core fields are designed to support DataCite DOI registration without requiring the dataCite extension. Structured authors, funding, and external links map directly to DataCite mandatory/recommended properties.
