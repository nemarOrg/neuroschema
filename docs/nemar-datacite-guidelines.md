# NEMAR DataCite Metadata Guidelines

Guidance for populating DataCite metadata when registering DOIs for NEMAR datasets. Based on the [DataCite Metadata Schema 4.6](https://schema.datacite.org/meta/kernel-4/) and aligned with neuroschema v0.3.0.

## Priority Tiers

### Tier 1: Essential (all datasets must have these)

| Property | Source | Notes |
|---|---|---|
| **Identifier** (DOI) | Auto-generated via EZID | `doi:10.82901/NEMAR.{DATASET_ID}` |
| **Title** | `name` from `dataset_description.json` | Keep the original dataset name |
| **Creators** | `authors[]` with ORCID + affiliations | See [Author Enrichment](#author-enrichment) |
| **Publisher** | Always "NEMAR" | ROR: `https://ror.org/0168r3w48` (UCSD) |
| **PublicationYear** | Year of first DOI registration | Auto from publish date |
| **ResourceType** | "Dataset" + modality-specific type | e.g., "EMG Dataset", "EEG Dataset" |
| **Description** (Abstract) | `description` or README excerpt | First paragraph of README if no description field |

### Tier 2: Recommended (strongly encouraged)

| Property | Source | Notes |
|---|---|---|
| **Subjects** | `keywords[]` | Include modality, technique, controlled vocabulary terms |
| **RelatedIdentifiers** | `related_identifiers[]` | Paper DOI, source datasets, related repos |
| **Contributors** | `contributors[]` | NEMAR auto-added as HostingInstitution |
| **Dates** | `dates[]` | Issued (auto), Collected (from enrichment) |
| **Rights** | `rights[]` + `license` | Machine-readable SPDX identifier + URI |
| **FundingReferences** | `funding[]` | Grant number, funder with Crossref Funder ID |

### Tier 3: Nice-to-Have (when available)

| Property | Source | Notes |
|---|---|---|
| **GeoLocations** | `extensions.dataCite.geo_locations[]` | Lab/institution location with coordinates |
| **Language** | `language` | Usually "en" |
| **Sizes** | `data_summary.size_human` | Computed from S3 |
| **Formats** | Derived from file extensions | BDF, SET, EDF, FDT, TSV, JSON |
| **Version** | `provenance.latest_snapshot` | Semantic version string |
| **AlternateIdentifiers** | `extensions.dataCite.alternate_identifiers[]` | NEMAR ID, OpenNeuro ID |
| **RelatedItems** | `extensions.dataCite.related_items[]` | Full bibliographic citations |

---

## Author Enrichment

Every dataset creator should have, at minimum:
- **Full name** (required)
- **ORCID** (strongly encouraged) -- enables author disambiguation and automatic profile linking
- **Affiliations** with **ROR ID** -- enables institutional analytics

Example:
```json
{
  "name": "Xiangyu Liu",
  "given_name": "Xiangyu",
  "family_name": "Liu",
  "name_type": "Personal",
  "orcid": "https://orcid.org/0000-0001-2345-6789",
  "affiliations": [
    {
      "name": "Fudan University",
      "identifier": "https://ror.org/013q1eq08",
      "scheme": "ROR"
    }
  ]
}
```

For organizational creators (rare for neuroimaging):
```json
{
  "name": "Child Mind Institute",
  "name_type": "Organizational"
}
```

---

## Subjects and Keywords

Use structured keywords with controlled vocabulary references where possible. This significantly improves discoverability.

### Recommended vocabularies for neuroimaging

| Vocabulary | Use For | Scheme URI |
|---|---|---|
| [MeSH](https://meshb.nlm.nih.gov/) | Clinical/medical terms | `https://www.nlm.nih.gov/mesh/` |
| [Cognitive Atlas](https://www.cognitiveatlas.org/) | Cognitive tasks, concepts | `https://www.cognitiveatlas.org/` |
| [LCSH](https://id.loc.gov/authorities/subjects.html) | General academic subjects | `https://id.loc.gov/authorities/subjects` |

### What to include as subjects

1. **Recording modality** -- always include (e.g., "EEG", "EMG", "MEG", "fMRI")
2. **Technique/method** -- if notable (e.g., "high-density surface electromyography", "mobile EEG")
3. **Application domain** -- what the data is about (e.g., "hand gesture recognition", "motor imagery")
4. **Body part or brain region** -- if specific (e.g., "forearm muscles", "visual cortex")
5. **Data standard** -- "BIDS" (always, for NEMAR datasets)

Example:
```json
{
  "keywords": [
    { "term": "EMG" },
    { "term": "high-density surface electromyography" },
    { "term": "hand gesture recognition" },
    {
      "term": "Electromyography",
      "subject_scheme": "MeSH",
      "scheme_uri": "https://www.nlm.nih.gov/mesh/",
      "value_uri": "https://meshb.nlm.nih.gov/record/ui?ui=D004576"
    },
    { "term": "BIDS" }
  ]
}
```

---

## Related Identifiers

Related identifiers are critical for knowledge graph positioning. They create typed links between your dataset and other scholarly resources.

### Key relation types for neuroimaging datasets

| Relation Type | When to Use | Example |
|---|---|---|
| `IsDescribedBy` | Paper that describes this dataset | Published data descriptor paper |
| `IsDerivedFrom` | Source dataset this was derived from | PhysioNet original, OpenNeuro source |
| `IsSupplementTo` | Paper this dataset supplements | Research article using this data |
| `References` | Any referenced resource | Software, protocol, atlas |
| `HasVersion` / `IsVersionOf` | Version chain | Links between dataset versions |
| `IsIdenticalTo` | Same dataset on another platform | OpenNeuro mirror |
| `IsPartOf` | Parent collection | Multi-dataset project |

### Identifier types

Use the most specific identifier type available:
- **DOI** -- preferred for papers, datasets
- **URL** -- for web resources without DOIs
- **PMID** -- for PubMed-indexed papers
- **arXiv** -- for preprints

### BIDS SourceDatasets

The BIDS `SourceDatasets` field in `dataset_description.json` should be automatically parsed into `IsDerivedFrom` relations:

```json
{
  "related_identifiers": [
    {
      "identifier": "10.1038/s41597-021-00883-1",
      "identifier_type": "DOI",
      "relation_type": "IsDescribedBy",
      "resource_type_general": "JournalArticle"
    },
    {
      "identifier": "10.13026/t9wv-d929",
      "identifier_type": "DOI",
      "relation_type": "IsDerivedFrom",
      "resource_type_general": "Dataset"
    }
  ]
}
```

---

## Rights and Licensing

Always provide a machine-readable license entry alongside the simple `license` string.

### Common neuroimaging dataset licenses

| License | SPDX ID | URI |
|---|---|---|
| CC0 1.0 | `CC0-1.0` | `https://creativecommons.org/publicdomain/zero/1.0/` |
| CC-BY 4.0 | `CC-BY-4.0` | `https://creativecommons.org/licenses/by/4.0/` |
| ODC-By 1.0 | `ODC-By-1.0` | `https://opendatacommons.org/licenses/by/1.0/` |
| ODbL 1.0 | `ODbL-1.0` | `https://opendatacommons.org/licenses/odbl/1.0/` |
| PDDL 1.0 | `PDDL-1.0` | `https://opendatacommons.org/licenses/pddl/1.0/` |

Example:
```json
{
  "license": "ODC-By-1.0",
  "rights": [
    {
      "rights": "Open Data Commons Attribution License v1.0",
      "rights_uri": "https://opendatacommons.org/licenses/by/1.0/",
      "rights_identifier": "ODC-By-1.0",
      "rights_identifier_scheme": "SPDX"
    }
  ]
}
```

---

## Funding References

Include the funder's persistent identifier whenever possible. This enables funder reporting and compliance tracking.

### Funder identifier sources

| Source | Type | Example |
|---|---|---|
| [Crossref Funder Registry](https://www.crossref.org/services/funder-registry/) | Crossref Funder ID | `https://doi.org/10.13039/100000001` (NSF) |
| [ROR](https://ror.org/) | ROR | `https://ror.org/021nxhr62` (NSF) |

Example:
```json
{
  "funding": [
    {
      "funder_name": "National Science Foundation",
      "funder_identifier": "https://doi.org/10.13039/100000001",
      "funder_identifier_type": "Crossref Funder ID",
      "award_number": "2030859",
      "award_title": "IUCRC Phase I UCSD: Center for Large-scale Optimization and Networks (CLAN)"
    }
  ]
}
```

---

## Dates

Provide semantically typed dates for temporal context.

| Date Type | When to Use | Auto? |
|---|---|---|
| `Issued` | First DOI registration | Yes (auto-populated) |
| `Collected` | Data collection period | From enrichment; can be a range (ISO 8601) |
| `Created` | Dataset creation/curation date | From enrichment |
| `Updated` | Last modification | Auto from version updates |
| `Available` | Public availability date | Auto on publication |

Date values follow ISO 8601 and can be:
- Full date: `2024-03-15`
- Year-month: `2024-03`
- Year only: `2024`
- Range: `2022-01/2023-06`

---

## Contributors

Contributors are people or organizations with roles beyond primary authorship.

### Auto-populated contributors

NEMAR automatically adds:
```json
{
  "name": "NEMAR",
  "name_type": "Organizational",
  "contributor_type": "HostingInstitution"
}
```

### Common neuroimaging contributor roles

| Role | When to Use |
|---|---|
| `DataCollector` | Person who ran the experiments |
| `DataCurator` | Person who organized/cleaned the data |
| `ProjectLeader` | PI of the study |
| `Researcher` | Research team members not listed as authors |
| `Supervisor` | Thesis advisor, lab director |
| `Other` | With explanation in description |

---

## GeoLocations

Geographic location where the data was collected. Useful for multi-site studies and geographic analyses.

```json
{
  "extensions": {
    "dataCite": {
      "geo_locations": [
        {
          "place": "Fudan University, Shanghai, China",
          "point": {
            "latitude": 31.2983,
            "longitude": 121.5014
          }
        }
      ]
    }
  }
}
```

---

## ResourceType

The `resource_type_general` should always be `"Dataset"`. The free-text `resource_type` should indicate the modality:

| Modality | resource_type |
|---|---|
| EEG | "EEG Dataset" |
| MEG | "MEG Dataset" |
| EMG | "EMG Dataset" |
| fMRI | "fMRI Dataset" |
| iEEG | "iEEG Dataset" |
| Multi-modal | "EEG-fMRI Dataset" or "Multimodal Neuroimaging Dataset" |

Detection is automatic from the BIDS datatype directories (`eeg/`, `meg/`, `emg/`, `func/`, `ieeg/`, etc.).

---

## Complete Example: EMG Dataset (nm000108)

See [`examples/dataset-nm000108.json`](../examples/dataset-nm000108.json) for a fully populated example based on the HySER high-density surface EMG dataset.
