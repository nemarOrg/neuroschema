# neuroschema Ideas

## Extension Ideas for Future Projects

### Data Categories Extension
- For the data categorization project
- Could include: study_domain, cognitive_domain, paradigm_type, stimulus_modality
- Allows filtering datasets by what kind of experiment they represent

### Population Extension
- Clinical vs. healthy populations
- Specific diagnoses or conditions
- Could support multi-label classification

### Electrode Montage Extension
- Detailed channel location information
- Standard montage identification (10-20, 10-10, GSN-HydroCel, etc.)
- Channel-to-region mapping

### Cross-Dataset Linking
- Fields to link datasets that share participants
- Longitudinal study tracking
- Multi-modal dataset groups (same participants, different modalities)

## Open Questions
- Should we version extensions independently from the core? (signalJourney does this)
- How do we handle backward compatibility when migrating existing EEGDash documents?
- Should the schema be published as an npm/pip package for easy consumption?
