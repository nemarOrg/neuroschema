# EEGDash Adapter Mapping

Maps fields between the current EEGDash MongoDB documents and neuroschema v0.2.0.

## Record-Level Mapping (EEGDash -> Neuroschema)

| EEGDash Field | Neuroschema Path | Notes |
|---|---|---|
| `_id` | (MongoDB internal) | Not part of schema |
| `data_name` | `data_name` | Direct mapping |
| `dataset` | `dataset` | Direct mapping |
| `bidspath` | `bids_relpath` | Strip dataset prefix |
| `subject` | `entities.subject` | Moved into entities |
| `task` | `entities.task` | Moved into entities |
| `session` | `entities.session` | Moved into entities |
| `run` | `entities.run` | Moved into entities |
| `modality` | `modality` | Now required per record |
| `sampling_frequency` | `signal_properties.sampling_frequency` | Moved to inheritable |
| `nchans` | `signal_summary.nchans` | Stays in summary |
| `ntimes` | `signal_summary.ntimes` | Stays in summary |
| `channel_types` | `extensions.rawDetail.channel_types` | Moved to extension |
| `channel_names` | `extensions.rawDetail.channel_names` | Moved to extension |
| `channel_tsv` | `extensions.rawDetail.channel_tsv` | Moved to extension |
| `eeg_json` | `extensions.rawDetail.eeg_json` | Moved to extension |
| `participant_tsv` | `extensions.rawDetail.participant_tsv` | Moved to extension |
| `rawdatainfo` | (decomposed) | Split into signal_summary + rawDetail |
| `bidsdependencies` | `extensions.rawDetail.bids_dependencies` | Moved to extension |
| `participantinfo` | `extensions.rawDetail.participant_tsv` | Merged with participant_tsv |

## New Fields in v0.2.0

Fields added to neuroschema that have no direct EEGDash source:

| Neuroschema Path | Source | Notes |
|---|---|---|
| `datatype` | Derived from bids_relpath | Parse BIDS path for datatype dir |
| `suffix` | Derived from filename | Parse BIDS filename |
| `file_extension` | Derived from filename | Extract extension |
| `signal_properties.power_line_frequency` | `eeg_json.PowerLineFrequency` | Extract from sidecar |
| `signal_properties.reference` | `eeg_json.EEGReference` | Extract from sidecar |
| `signal_properties.recording_type` | `eeg_json.RecordingType` | Extract from sidecar |
| `signal_summary.recording_duration` | `eeg_json.RecordingDuration` | Extract from sidecar |
| `signal_summary.channel_type_counts` | Computed from `channel_types` | Count by type |

## EEGDash Extension Fields

Fields specific to the EEGDash dashboard that live in `extensions.eegdash`:

| EEGDash Extension Field | Description |
|---|---|
| `storage.backend` | Storage backend type (s3, https, local) |
| `storage.base` | Base URI |
| `storage.raw_key` | Path to raw data file |
| `storage.dep_keys` | Dependency file paths |
| `tags.pathology` | Pathology classification tags |
| `tags.modality` | Modality classification tags |
| `tags.type` | Type classification tags |
| `repository_stats` | GitHub stars/forks/watchers |
| `senior_author` | Senior author name (v0.2.0) |
| `contact_info` | Contact email/URL (v0.2.0) |
| `ages` | Raw age array (v0.2.0) |

## Migration Strategy

1. Read existing MongoDB document
2. Map flat fields to nested neuroschema structure
3. Move per-channel arrays to `extensions.rawDetail`
4. Extract signal properties from `eeg_json` sidecar
5. Compute `channel_type_counts` from `channel_types` array
6. Parse `bids_relpath` for datatype, suffix, file_extension
7. Write core fields to `records` collection, extension fields to `ext_rawDetail`
