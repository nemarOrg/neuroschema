# neuroschema Plan

## Phase 1: Schema Foundation (current)
- [x] Define core dataset schema with required fields
- [x] Define core record schema with required fields
- [x] Create definitions for shared types (demographics, BIDS entities, signal summary)
- [x] Create extension container with initial namespaces (eegdash, signalJourney, nemar, dataQuality, rawDetail)
- [ ] Add Python validation tooling (jsonschema-based)
- [ ] Add example documents that conform to the new schema
- [ ] Write tests validating examples against schema

## Phase 2: Migration Mapping
- [ ] Document mapping from current EEGDash MongoDB documents to neuroschema
- [ ] Document mapping from NEMAR API responses to neuroschema
- [ ] Create migration scripts or adapters

## Phase 3: Integration
- [ ] Update EEGDash `schemas.py` to align with neuroschema
- [ ] Add signalJourney cross-references
- [ ] Define data quality extension fields based on quality assessment needs

## Phase 4: Documentation
- [ ] Schema documentation site (MkDocs)
- [ ] Contribution guide for adding new extensions
- [ ] Version changelog

## Design Decisions

### What goes in core vs extensions?
- **Core (frozen):** dataset_id, name, source, recording_modality, BIDS entities, signal summary (counts, rates), demographics summary
- **Extensions:** per-channel arrays (rawDetail), storage backends (eegdash), processing pipeline refs (signalJourney), NEMAR-specific API fields (nemar), quality metrics (dataQuality)

### Why separate rawDetail?
The existing MongoDB documents contain large per-channel arrays (channel_names, channel_types, channel_tsv) that can be 100+ elements. These are useful for detailed queries but not for dataset discovery. Keeping them in an extension means the core document stays small for search/filter operations.
