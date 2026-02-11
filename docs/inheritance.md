# BIDS Inheritance Pattern

Neuroschema follows the [BIDS inheritance principle](https://bids-specification.readthedocs.io/en/stable/common-principles.html#the-inheritance-principle): metadata defined at a higher level (dataset) applies to all lower levels (records), unless overridden.

## Inheritable Fields

The following fields are defined in `schema/definitions/inheritable.schema.json` and can appear in both `dataset.signal_defaults` and `record.signal_properties`:

| Field | Type | Description |
|---|---|---|
| `sampling_frequency` | number or null | Sampling frequency in Hz |
| `power_line_frequency` | 50, 60, or null | Power line frequency |
| `reference` | string or null | EEG reference (e.g., "nose", "Cz") |
| `recording_type` | string or null | "continuous" or "epoched" |
| `channel_system` | string or null | Electrode placement system |
| `placement_scheme` | string or null | Detailed placement scheme |

## Merge Rules

When resolving the effective signal properties for a record:

1. Start with `dataset.signal_defaults` as the base
2. Overlay `record.signal_properties`: only fields that are **present and non-null** override the base. A field set to `null` (or absent) in the record means "inherit the dataset default."
3. The result is the effective signal configuration for that record

> **Note:** JSON cannot distinguish "field absent" from "field set to null" once the document is parsed. Both are treated as "no override; use dataset default." To explicitly clear a dataset default at the record level, use an empty string for string fields or 0 for numeric fields.

### Example

```json
// Dataset signal_defaults
{
  "sampling_frequency": 250,
  "power_line_frequency": 50,
  "reference": "Cz",
  "recording_type": "continuous",
  "channel_system": "10-20",
  "placement_scheme": null
}

// Record signal_properties (overrides sampling_frequency only)
{
  "sampling_frequency": 500,
  "reference": null
}

// Effective (merged) signal properties for this record
{
  "sampling_frequency": 500,
  "power_line_frequency": 50,
  "reference": "Cz",
  "recording_type": "continuous",
  "channel_system": "10-20",
  "placement_scheme": null
}
```

## Record-Only Fields

These fields do NOT follow inheritance; they exist only at the record level:

- `modality` (required): Each record must declare its own modality
- `datatype`: BIDS datatype directory (e.g., "eeg", "meg")
- `suffix`: BIDS filename suffix
- `file_extension`: File extension with leading dot
- `signal_summary`: Per-recording aggregates (nchans, ntimes, etc.)

## Implementation Notes

The merge is a shallow merge at the field level. Nested objects are replaced entirely, not deep-merged. Application code should implement this merge when querying records to present the effective configuration.
