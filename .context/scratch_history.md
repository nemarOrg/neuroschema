# Scratch History

## 2026-02-09: Initial project setup
- Created schema structure based on analysis of eegdash, signalJourney, and NEMAR API
- Key decision: rawDetail extension to hold verbose per-channel arrays
- Key decision: core uses summaries (channel_type_counts) instead of arrays (channel_types)

## 2026-02-10: v0.2.0 redesign (issues #4, #5, #6)
- Restructured core: inheritable signal properties replace signalDefaults, BIDS inheritance pattern
- Record completeness: modality now required, added datatype/suffix/file_extension, signal_properties, recordProvenance
- Dataset enrichment: structured authors (person.schema.json), structured funding objects, datatypes/sessions arrays, description field
- New extensions: dataCite (DOI registration), dataCategories (study classification)
- Extension updates: eegdash (senior_author, contact_info, ages), rawDetail (electrode_tsv, events_tsv)
- Added x-extension-managers metadata to extensionsContainer for MongoDB topology
- Updated examples to conform to v0.2.0 schema
- Created adapter docs for EEGDash and DataCite migration
- 30 tests passing: positive, negative, extension isolation, BIDS entities, dataset enrichment
- Reframed project scope: neuroschema is for FAIR data reuse broadly, not just NEMAR; NEMAR is one consumer via its extension namespace
