# DataCite Adapter Mapping

Maps fields between the [DataCite Metadata Schema 4.6](https://schema.datacite.org/meta/kernel-4/) and neuroschema v0.3.0.

Reference: DataCite schema repo cloned at `~/Documents/git/nemar/datacite-schema/`.

## All 20 DataCite Properties

| # | DataCite Property | Obligation | Neuroschema Path | Notes |
|---|---|---|---|---|
| 1 | Identifier (DOI) | **M** | `external_links.dataset_doi` | Core |
| 2 | Creator | **M** | `authors[]` | Core person objects (name, given_name, family_name, orcid, affiliations with ROR) |
| 3 | Title | **M** | `name` | Core |
| 4 | Publisher | **M** | `extensions.dataCite.publisher` | Extension (registration detail) |
| 5 | PublicationYear | **M** | `extensions.dataCite.publication_year` | Extension; core has `provenance.publish_date` |
| 6 | Subject | **R** | `keywords[]` | Core (v0.3.0); structured with term, subject_scheme, scheme_uri, value_uri |
| 7 | Contributor | **R** | `contributors[]` | Core (v0.3.0); person + contributor_type role |
| 8 | Date | **R** | `dates[]` | Core (v0.3.0); date + date_type + date_information |
| 9 | Language | O | `language` | Core (v0.3.0) |
| 10 | ResourceType | **M** | `extensions.dataCite.resource_type` / `resource_type_general` | Extension |
| 11 | AlternateIdentifier | O | `extensions.dataCite.alternate_identifiers[]` | Extension |
| 12 | RelatedIdentifier | **R** | `related_identifiers[]` | Core (v0.3.0); full typed with identifier_type, relation_type, resource_type_general |
| 13 | Size | O | `data_summary.size_human` / `data_summary.size_bytes` | Core (dataSummary) |
| 14 | Format | O | (computed from file extensions) | Not stored; derived at DOI registration time |
| 15 | Version | O | `provenance.latest_snapshot` | Core (provenance) |
| 16 | Rights | O | `rights[]` | Core (v0.3.0); structured with rights_uri, rights_identifier (SPDX). Also `license` for simple string. |
| 17 | Description | **R** | `description` | Core (Abstract); also `readme` for full text |
| 18 | GeoLocation | **R** | `extensions.dataCite.geo_locations[]` | Extension; place + point coordinates |
| 19 | FundingReference | O | `funding[]` | Core; enhanced with funder_identifier, funder_identifier_type, award_uri (v0.3.0) |
| 20 | RelatedItem | O | `extensions.dataCite.related_items[]` | Extension; full bibliographic citations |

**M** = Mandatory, **R** = Recommended, **O** = Optional

## Sub-Property Mapping Detail

### Creator (property 2) -> `authors[]`

| DataCite Sub-property | Neuroschema Path |
|---|---|
| creatorName | `authors[].name` |
| nameType | `authors[].name_type` (v0.3.0) |
| givenName | `authors[].given_name` |
| familyName | `authors[].family_name` |
| nameIdentifier (ORCID) | `authors[].orcid` |
| affiliation | `authors[].affiliations[].name` |
| affiliationIdentifier (ROR) | `authors[].affiliations[].identifier` |
| affiliationIdentifierScheme | `authors[].affiliations[].scheme` |

### Subject (property 6) -> `keywords[]`

| DataCite Sub-property | Neuroschema Path |
|---|---|
| subject (text) | `keywords[].term` |
| subjectScheme | `keywords[].subject_scheme` |
| schemeURI | `keywords[].scheme_uri` |
| valueURI | `keywords[].value_uri` |
| classificationCode | `keywords[].classification_code` |

### FundingReference (property 19) -> `funding[]`

| DataCite Sub-property | Neuroschema Path |
|---|---|
| funderName | `funding[].funder_name` |
| funderIdentifier | `funding[].funder_identifier` |
| funderIdentifierType | `funding[].funder_identifier_type` |
| awardNumber | `funding[].award_number` |
| awardTitle | `funding[].award_title` |
| awardURI | `funding[].award_uri` |

### RelatedIdentifier (property 12) -> `related_identifiers[]`

| DataCite Sub-property | Neuroschema Path |
|---|---|
| relatedIdentifier (value) | `related_identifiers[].identifier` |
| relatedIdentifierType | `related_identifiers[].identifier_type` |
| relationType | `related_identifiers[].relation_type` |
| resourceTypeGeneral | `related_identifiers[].resource_type_general` |
| relatedMetadataScheme | `related_identifiers[].related_metadata_scheme` |

## DataCite Registration Flow

When registering a DOI for a neuroimaging dataset:

1. Read core fields: `name` (title), `authors` (creators), `description` (abstract), `funding`, `license`/`rights`, `keywords` (subjects), `related_identifiers`, `contributors`, `dates`, `language`
2. Read `external_links.dataset_doi` for existing DOI
3. Read `extensions.dataCite` for publisher, resource type, geo_locations, alternate_identifiers
4. Read `data_summary` for sizes
5. Assemble DataCite kernel-4.6 XML
6. Submit to EZID/DataCite API
7. Store returned DOI in `external_links.dataset_doi`

## Changes from v0.2.0

Fields moved from `extensions.dataCite` to core:
- `contributors[]` -> core `contributors[]`
- `related_identifiers[]` -> core `related_identifiers[]`
- `language` -> core `language`

Fields added to core:
- `keywords[]` (structured subjects with controlled vocabulary support)
- `dates[]` (structured dates with semantic types)
- `rights[]` (structured license entries with URIs and SPDX identifiers)

Fields added to `extensions.dataCite`:
- `publisher_identifier`, `publisher_identifier_scheme`
- `related_items[]` (DataCite property 20, full bibliographic citations)

Enums updated to DataCite kernel-4.6:
- `resource_type_general`: added Award, Project, Instrument, StudyRegistration
- `relation_type`: added HasTranslation, IsTranslationOf (core relatedIdentifier enum)
- `contributor_type`: added Translator
- `date_type`: added Coverage (core structuredDate enum)
