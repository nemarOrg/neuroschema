# Extension Managers and MongoDB Topology

Each extension namespace in neuroschema maps to a separate MongoDB collection. This enables fine-grained access control where each service writes only to its own collection.

## Collection Mapping

| Namespace | Manager Service | MongoDB Collection | Document Key |
|---|---|---|---|
| core (dataset) | nemar-api | `datasets` | `dataset_id` |
| core (record) | nemar-api | `records` | `dataset` + `bids_relpath` |
| eegdash | eegdash | `ext_eegdash` | `dataset` [+ `bids_relpath`] |
| signalJourney | signal-journey | `ext_signalJourney` | `dataset` + `bids_relpath` |
| nemar | nemar-api | `ext_nemar` | `dataset_id` |
| dataQuality | nemar-pipeline | `ext_dataQuality` | `dataset` + `bids_relpath` |
| rawDetail | nemar-api | `ext_rawDetail` | `dataset` + `bids_relpath` |
| dataCite | nemar-tools | `ext_dataCite` | `dataset_id` |
| dataCategories | nemar-api | `ext_dataCategories` | `dataset_id` |

## Access Control

Each manager service has write access only to its own extension collection(s):

- **nemar-api**: Writes core documents and manages nemar, rawDetail, and dataCategories extensions
- **eegdash**: Writes eegdash extension (storage paths, tags, ages)
- **signal-journey**: Writes signalJourney extension (pipeline status)
- **nemar-pipeline**: Writes dataQuality extension (quality scores)
- **nemar-tools**: Writes dataCite extension (DOI registration metadata)

All services have read access to all collections.

## Querying

To assemble a full document with extensions, the application performs a lookup join:

```javascript
// MongoDB aggregation to join core + extensions
db.records.aggregate([
  { $match: { dataset: "ds002718", bids_relpath: "sub-004/eeg/..." } },
  { $lookup: {
      from: "ext_rawDetail",
      localField: "_id",
      foreignField: "record_id",
      as: "extensions.rawDetail"
  }},
  { $unwind: { path: "$extensions.rawDetail", preserveNullAndEmptyArrays: true } }
])
```

## Schema Metadata

The collection mapping is encoded in `extensionsContainer.schema.json` under the `x-extension-managers` property. This is a non-validating metadata annotation; JSON Schema draft 2020-12 implementations ignore unknown keywords, so custom metadata keys like `x-extension-managers` are safe to include without affecting validation.
