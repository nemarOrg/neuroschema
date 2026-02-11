# neuroschema Ideas

## Extension Ideas for Future Projects

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

### Provenance Chain Extension
- Full processing provenance (which tools, versions, parameters)
- Links between raw and derived datasets
- Reproducibility metadata

### Access Control Extension
- Data use agreements, embargo dates
- License compatibility tracking
- Consent level metadata (open, restricted, controlled)

## Open Questions
- Should we version extensions independently from the core? (signalJourney does this)
- How do we handle backward compatibility when migrating existing EEGDash documents?
- Should the schema be published as an npm/pip package for easy consumption?
- How to handle multi-modal datasets where records span different modalities with different signal property semantics?
