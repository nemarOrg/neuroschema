# DataCite Adapter Mapping

Maps fields between the [DataCite Metadata Schema 4.5](https://schema.datacite.org/meta/kernel-4.5/) and neuroschema v0.2.0.

## Core Fields (DataCite -> Neuroschema Core)

| DataCite Property | Neuroschema Path | Notes |
|---|---|---|
| Identifier (DOI) | `external_links.dataset_doi` | Core field |
| Title | `name` | Core field |
| Creator | `authors[]` | Structured person objects |
| Creator.creatorName | `authors[].name` | Full display name |
| Creator.givenName | `authors[].given_name` | Optional |
| Creator.familyName | `authors[].family_name` | Optional |
| Creator.nameIdentifier (ORCID) | `authors[].orcid` | ORCID URL |
| Creator.affiliation | `authors[].affiliations[]` | Structured with name + identifier |
| Description | `description` | Core field (v0.2.0) |
| Subject | (not mapped) | Consider dataCategories extension |
| FundingReference.funderName | `funding[].funder_name` | Core field |
| FundingReference.awardNumber | `funding[].award_number` | Core field |
| FundingReference.awardTitle | `funding[].award_title` | Core field |
| Rights | `license` | Core field |
| Date | `provenance.publish_date` | Maps dateType=Issued; other dateTypes (Created, Updated) not mapped |
| Version | `provenance.latest_snapshot` | Core provenance |

## Extension Fields (DataCite -> extensions.dataCite)

| DataCite Property | Neuroschema Path | Notes |
|---|---|---|
| Publisher | `extensions.dataCite.publisher` | e.g., "OpenNeuro" |
| PublicationYear | `extensions.dataCite.publication_year` | Integer year |
| ResourceType | `extensions.dataCite.resource_type` | Free text |
| ResourceType.resourceTypeGeneral | `extensions.dataCite.resource_type_general` | Controlled vocabulary |
| Contributor | `extensions.dataCite.contributors[]` | With role types |
| RelatedIdentifier | `extensions.dataCite.related_identifiers[]` | With relation types |
| GeoLocation | `extensions.dataCite.geo_locations[]` | Place + coordinates |
| Language | `extensions.dataCite.language` | BCP 47 tag |
| AlternateIdentifier | `extensions.dataCite.alternate_identifiers[]` | Non-DOI identifiers |

## DataCite Registration Flow

When registering a DOI for a neuroimaging dataset:

1. Read core dataset document for title, authors, funding, license
2. Read `extensions.dataCite` for publisher, resource type, contributors
3. Assemble DataCite XML/JSON payload
4. Submit to DataCite API
5. Store returned DOI in `external_links.dataset_doi`

## Priority Assessment

Fields from issue #5 mapped to priority:

| Priority | Fields | Location |
|---|---|---|
| HIGH | authors (structured), funding (structured), publisher, related_identifiers | Core + dataCite |
| MEDIUM | contributors, geo_locations, resource_type | dataCite extension |
| LOW | language, alternate_identifiers | dataCite extension |
