"""Tests for neuroschema schema validation.

Uses real example documents from the examples/ directory and validates
against the actual JSON Schema files. No mocks.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from neuroschema.validate import validate_document, validate_file

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
EXAMPLES_DIR = ROOT / "examples"


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def record_schema_path():
    return SCHEMA_DIR / "core" / "record.schema.json"


@pytest.fixture
def dataset_schema_path():
    return SCHEMA_DIR / "core" / "dataset.schema.json"


ROOT_ONLY_KEYS = ("schema_version", "doc_type")


def _load_example(name: str) -> dict:
    """Load an example JSON file, stripping root-only envelope keys."""
    with open(EXAMPLES_DIR / name) as f:
        doc = json.load(f)
    return {k: v for k, v in doc.items() if k not in ROOT_ONLY_KEYS}


@pytest.fixture
def schema1():
    return _load_example("schema1.json")


@pytest.fixture
def schema2():
    return _load_example("schema2.json")


@pytest.fixture
def minimal_record():
    return {
        "dataset": "ds000001",
        "bids_relpath": "sub-01/eeg/sub-01_task-rest_eeg.set",
        "modality": "EEG",
    }


@pytest.fixture
def minimal_dataset():
    return {
        "dataset_id": "ds000001",
        "name": "Test Dataset",
        "source": "openneuro",
        "recording_modality": ["EEG"],
    }


# ── Positive Validation Tests ─────────────────────────────────────────────


class TestPositiveValidation:
    """Example documents should validate against their schemas."""

    def test_schema1_validates_against_record(self, schema1, record_schema_path):
        """schema1.json (ds002718 record) passes record schema validation."""
        errors = validate_document(schema1, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_schema2_validates_against_record(self, schema2, record_schema_path):
        """schema2.json (ds005514 record) passes record schema validation."""
        errors = validate_document(schema2, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_minimal_record_validates(self, minimal_record, record_schema_path):
        """A record with only required fields should validate."""
        errors = validate_document(minimal_record, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_minimal_dataset_validates(self, minimal_dataset, dataset_schema_path):
        """A dataset with only required fields should validate."""
        errors = validate_document(minimal_dataset, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_dataset_with_structured_authors(
        self, minimal_dataset, dataset_schema_path
    ):
        """Dataset with structured person authors should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["authors"] = [
            {
                "name": "Jane A. Smith",
                "given_name": "Jane",
                "family_name": "Smith",
                "orcid": "https://orcid.org/0000-0002-1234-5678",
                "affiliations": [
                    {
                        "name": "MIT",
                        "identifier": "https://ror.org/042nb2s44",
                        "scheme": "ROR",
                    }
                ],
            }
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_dataset_with_structured_funding(
        self, minimal_dataset, dataset_schema_path
    ):
        """Dataset with structured funding should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["funding"] = [
            {
                "funder_name": "NIH",
                "award_number": "R01-MH123456",
                "award_title": "Neural Dynamics Study",
            }
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_record_with_signal_properties(self, minimal_record, record_schema_path):
        """Record with inheritable signal properties should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["signal_properties"] = {
            "sampling_frequency": 256,
            "power_line_frequency": 60,
            "reference": "average",
            "recording_type": "continuous",
            "channel_system": "10-20",
            "placement_scheme": "standard 10-20",
        }
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_record_with_file_format_fields(self, minimal_record, record_schema_path):
        """Record with datatype, suffix, file_extension should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["datatype"] = "eeg"
        doc["suffix"] = "eeg"
        doc["file_extension"] = ".set"
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_record_with_provenance(self, minimal_record, record_schema_path):
        """Record with provenance timestamps should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["provenance"] = {
            "digested_at": "2026-01-15T10:30:00Z",
            "created_at": "2025-12-01T00:00:00Z",
            "modified_at": None,
        }
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]


# ── Negative Validation Tests ─────────────────────────────────────────────


class TestNegativeValidation:
    """Invalid documents should fail validation."""

    def test_record_missing_dataset(self, record_schema_path):
        """Record without required 'dataset' field should fail."""
        doc = {"bids_relpath": "sub-01/eeg/test.set", "modality": "EEG"}
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_record_missing_bids_relpath(self, record_schema_path):
        """Record without required 'bids_relpath' field should fail."""
        doc = {"dataset": "ds000001", "modality": "EEG"}
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_record_missing_modality(self, record_schema_path):
        """Record without required 'modality' field should fail."""
        doc = {"dataset": "ds000001", "bids_relpath": "sub-01/eeg/test.set"}
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_record_invalid_dataset_pattern(self, record_schema_path):
        """Record with invalid dataset_id pattern should fail."""
        doc = {
            "dataset": "invalid-id",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
        }
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_record_additional_property(self, record_schema_path):
        """Record with unknown top-level property should fail."""
        doc = {
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
            "unknown_field": "value",
        }
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_dataset_missing_name(self, dataset_schema_path):
        """Dataset without required 'name' field should fail."""
        doc = {
            "dataset_id": "ds000001",
            "source": "openneuro",
            "recording_modality": ["EEG"],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_dataset_invalid_source(self, dataset_schema_path):
        """Dataset with invalid source enum should fail."""
        doc = {
            "dataset_id": "ds000001",
            "name": "Test",
            "source": "invalid_source",
            "recording_modality": ["EEG"],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_dataset_empty_modality(self, dataset_schema_path):
        """Dataset with empty recording_modality array should fail (minItems: 1)."""
        doc = {
            "dataset_id": "ds000001",
            "name": "Test",
            "source": "openneuro",
            "recording_modality": [],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_invalid_power_line_frequency(self, record_schema_path):
        """Record with invalid power_line_frequency should fail."""
        doc = {
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
            "signal_properties": {
                "power_line_frequency": 75,
            },
        }
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0

    def test_funding_missing_funder_name(self, dataset_schema_path):
        """Funding entry without required funder_name should fail."""
        doc = {
            "dataset_id": "ds000001",
            "name": "Test",
            "source": "openneuro",
            "recording_modality": ["EEG"],
            "funding": [{"award_number": "R01-123"}],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_author_missing_name(self, dataset_schema_path):
        """Author entry without required name should fail."""
        doc = {
            "dataset_id": "ds000001",
            "name": "Test",
            "source": "openneuro",
            "recording_modality": ["EEG"],
            "authors": [{"given_name": "Jane"}],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0


# ── Extension Isolation Tests ─────────────────────────────────────────────


class TestExtensionIsolation:
    """Extensions should validate independently."""

    def test_datacite_extension_validates(self):
        """DataCite extension with all fields should validate."""
        schema_path = SCHEMA_DIR / "extensions" / "dataCite.schema.json"
        doc = {
            "publisher": "NEMAR",
            "publisher_identifier": "https://ror.org/0168r3w48",
            "publisher_identifier_scheme": "ROR",
            "publication_year": 2026,
            "resource_type": "EMG Dataset",
            "resource_type_general": "Dataset",
            "geo_locations": [
                {
                    "place": "Fudan University, Shanghai, China",
                    "point": {"latitude": 31.2983, "longitude": 121.5014},
                }
            ],
            "alternate_identifiers": [
                {"identifier": "nm000108", "identifier_type": "NEMAR"}
            ],
            "related_items": [
                {
                    "relation_type": "IsDescribedBy",
                    "related_item_type": "JournalArticle",
                    "title": "HySER Dataset Paper",
                    "publication_year": 2021,
                    "related_item_identifier": {
                        "identifier": "10.1038/s41597-021-00883-1",
                        "identifier_type": "DOI",
                    },
                }
            ],
        }
        errors = validate_document(doc, schema_path)
        assert errors == [], [e.message for e in errors]

    def test_data_categories_extension_validates(self):
        """DataCategories extension with all fields should validate."""
        schema_path = SCHEMA_DIR / "extensions" / "dataCategories.schema.json"
        doc = {
            "study_domain": "cognitive neuroscience",
            "study_design": "within-subject",
            "paradigm": {
                "type": "event-related",
                "stimulus_modality": "visual",
                "response_type": "button-press",
            },
            "clinical": {
                "is_clinical": False,
                "conditions": [],
                "population": "healthy adults",
            },
            "cognitive_domains": ["attention", "memory"],
        }
        errors = validate_document(doc, schema_path)
        assert errors == [], [e.message for e in errors]

    def test_eegdash_extension_with_new_fields(self):
        """EEGDash extension with new v0.2.0 fields should validate."""
        schema_path = SCHEMA_DIR / "extensions" / "eegdash.schema.json"
        doc = {
            "senior_author": "Dr. Jane Smith",
            "contact_info": "jane.smith@university.edu",
            "ages": [22.5, 25.1, 30.0, 19.8],
            "tags": {
                "pathology": ["healthy"],
                "modality": ["EEG"],
                "type": ["resting-state"],
            },
        }
        errors = validate_document(doc, schema_path)
        assert errors == [], [e.message for e in errors]

    def test_raw_detail_with_new_fields(self):
        """rawDetail extension with new electrode/events fields should validate."""
        schema_path = SCHEMA_DIR / "extensions" / "rawDetail.schema.json"
        doc = {
            "channel_names": ["Fp1", "Fp2", "Fz"],
            "channel_types": ["EEG", "EEG", "EEG"],
            "electrode_tsv": {
                "name": ["Fp1", "Fp2", "Fz"],
                "x": [0.1, -0.1, 0.0],
                "y": [0.9, 0.9, 0.8],
                "z": [0.0, 0.0, 0.1],
            },
            "events_tsv": {
                "onset": [0.5, 1.2, 2.8],
                "duration": [0.1, 0.1, 0.1],
                "trial_type": ["target", "distractor", "target"],
            },
        }
        errors = validate_document(doc, schema_path)
        assert errors == [], [e.message for e in errors]


# ── BIDS Entities Tests ───────────────────────────────────────────────────


class TestBidsEntities:
    """Test new BIDS entity fields."""

    def test_new_entities_validate(self, minimal_record, record_schema_path):
        """Record with acquisition and space entities should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["entities"] = {
            "subject": "01",
            "session": "pre",
            "task": "rest",
            "run": "1",
            "acquisition": "full",
            "space": "MNI152NLin2009cAsym",
        }
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_entities_reject_unknown(self, minimal_record, record_schema_path):
        """BIDS entities with unknown field should fail."""
        doc = copy.deepcopy(minimal_record)
        doc["entities"] = {
            "subject": "01",
            "unknown_entity": "value",
        }
        errors = validate_document(doc, record_schema_path)
        assert len(errors) > 0


# ── Dataset Enrichment Tests ──────────────────────────────────────────────


class TestDatasetEnrichment:
    """Test new dataset-level fields."""

    def test_datatypes_and_sessions(self, minimal_dataset, dataset_schema_path):
        """Dataset with datatypes and sessions arrays should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["datatypes"] = ["eeg", "anat"]
        doc["sessions"] = ["pre", "post"]
        doc["description"] = "A test dataset for validation."
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_data_summary_new_fields(self, minimal_dataset, dataset_schema_path):
        """Dataset with new data_summary fields should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["data_summary"] = {
            "total_files": 100,
            "size_bytes": 5000000000,
            "size_human": "5.0 GB",
            "recording_count": 42,
            "data_processed": False,
        }
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_external_links_new_fields(self, minimal_dataset, dataset_schema_path):
        """Dataset with new external link fields should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["external_links"] = {
            "source_url": "https://openneuro.org/datasets/ds000001",
            "dataset_doi": "10.18112/openneuro.ds000001.v1.0.0",
            "osf_url": "https://osf.io/abc123",
            "github_url": "https://github.com/example/dataset",
            "paper_url": "https://journals.example.com/paper/123",
        }
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_signal_defaults_uses_inheritable(
        self, minimal_dataset, dataset_schema_path
    ):
        """Dataset signal_defaults uses inheritable schema."""
        doc = copy.deepcopy(minimal_dataset)
        doc["signal_defaults"] = {
            "sampling_frequency": 256,
            "power_line_frequency": 60,
            "reference": "Cz",
            "recording_type": "continuous",
            "channel_system": "10-20",
            "placement_scheme": "standard 10-20 system",
        }
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]


# ── Root Schema Dispatch Tests ───────────────────────────────────────────


class TestRootSchemaDispatch:
    """Test the root schema's if/then/else doc_type dispatch."""

    def test_record_through_root_schema(self):
        """Full record with envelope fields validates via root schema."""
        doc = {
            "schema_version": "0.2.0",
            "doc_type": "record",
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/sub-01_task-rest_eeg.set",
            "modality": "EEG",
        }
        errors = validate_document(doc)
        assert errors == [], [e.message for e in errors]

    def test_dataset_through_root_schema(self):
        """Full dataset with envelope fields validates via root schema."""
        doc = {
            "schema_version": "0.2.0",
            "doc_type": "dataset",
            "dataset_id": "ds000001",
            "name": "Test Dataset",
            "source": "openneuro",
            "recording_modality": ["EEG"],
        }
        errors = validate_document(doc)
        assert errors == [], [e.message for e in errors]

    def test_root_schema_requires_schema_version(self):
        """Root schema requires schema_version."""
        doc = {
            "doc_type": "record",
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
        }
        errors = validate_document(doc)
        assert len(errors) > 0

    def test_root_schema_requires_doc_type(self):
        """Root schema requires doc_type."""
        doc = {
            "schema_version": "0.2.0",
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
        }
        errors = validate_document(doc)
        assert len(errors) > 0

    def test_root_schema_rejects_invalid_doc_type(self):
        """Root schema rejects unknown doc_type values."""
        doc = {
            "schema_version": "0.2.0",
            "doc_type": "unknown",
            "dataset": "ds000001",
        }
        errors = validate_document(doc)
        assert len(errors) > 0

    def test_root_schema_rejects_invalid_version_format(self):
        """Root schema rejects non-semver schema_version."""
        doc = {
            "schema_version": "v2",
            "doc_type": "record",
            "dataset": "ds000001",
            "bids_relpath": "sub-01/eeg/test.set",
            "modality": "EEG",
        }
        errors = validate_document(doc)
        assert len(errors) > 0

    def test_example_files_validate_against_root(self):
        """Example files (with envelope) validate against root schema."""
        for name in ("schema1.json", "schema2.json"):
            with open(EXAMPLES_DIR / name) as f:
                doc = json.load(f)
            errors = validate_document(doc)
            assert errors == [], f"{name}: {[e.message for e in errors]}"


# ── Embedded Extension Tests ─────────────────────────────────────────────


class TestEmbeddedExtensions:
    """Extensions embedded in a record/dataset should validate."""

    def test_record_with_extensions(self, minimal_record, record_schema_path):
        """Record with populated extensions block should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["extensions"] = {
            "rawDetail": {
                "channel_names": ["Fp1", "Fp2"],
                "channel_types": ["EEG", "EEG"],
            }
        }
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_dataset_with_extensions(self, minimal_dataset, dataset_schema_path):
        """Dataset with populated extensions block should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["extensions"] = {
            "dataCite": {
                "publisher": "OpenNeuro",
                "publication_year": 2025,
            },
            "dataCategories": {
                "study_domain": "cognitive neuroscience",
            },
        }
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]


# ── File Validation Tests ────────────────────────────────────────────────


class TestFileValidation:
    """Test validate_file function."""

    def test_validate_file_with_example(self):
        """validate_file loads and validates a real JSON file."""
        schema_path = SCHEMA_DIR / "core" / "record.schema.json"
        errors = validate_file(EXAMPLES_DIR / "schema1.json", schema_path)
        assert errors == [], [e.message for e in errors]

    def test_validate_file_against_root(self):
        """validate_file works against root schema (default)."""
        errors = validate_file(EXAMPLES_DIR / "schema1.json")
        assert errors == [], [e.message for e in errors]


# ── Schema Integrity Tests ───────────────────────────────────────────────


class TestSchemaIntegrity:
    """Verify schema files are well-formed."""

    def test_all_schemas_have_id(self):
        """Every schema file should have a $id field."""
        for schema_file in SCHEMA_DIR.rglob("*.schema.json"):
            with open(schema_file) as f:
                schema = json.load(f)
            assert "$id" in schema, f"{schema_file.name} missing $id"

    def test_record_signal_summary_validates(self, minimal_record, record_schema_path):
        """Record with signal_summary should validate."""
        doc = copy.deepcopy(minimal_record)
        doc["signal_summary"] = {
            "nchans": 64,
            "ntimes": 749000,
            "recording_duration": 2925.78,
            "channel_type_counts": {"EEG": 60, "EOG": 2, "EMG": 2},
        }
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_dataset_invalid_id_pattern(self, dataset_schema_path):
        """Dataset with invalid dataset_id pattern should fail."""
        doc = {
            "dataset_id": "invalid-id",
            "name": "Test",
            "source": "openneuro",
            "recording_modality": ["EEG"],
        }
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0


# ── v0.3.0 Core Field Tests ─────────────────────────────────────────────


class TestV030CoreFields:
    """Test new core fields added in v0.3.0."""

    def test_nemar_dataset_id_pattern(self, minimal_dataset, dataset_schema_path):
        """Dataset with nm-prefix ID should validate (relaxed pattern)."""
        doc = copy.deepcopy(minimal_dataset)
        doc["dataset_id"] = "nm000108"
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_keywords_plain(self, minimal_dataset, dataset_schema_path):
        """Dataset with plain keywords (term only) should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["keywords"] = [{"term": "EEG"}, {"term": "resting state"}]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_keywords_structured(self, minimal_dataset, dataset_schema_path):
        """Dataset with structured keywords (scheme + URI) should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["keywords"] = [
            {
                "term": "Electromyography",
                "subject_scheme": "MeSH",
                "scheme_uri": "https://www.nlm.nih.gov/mesh/",
                "value_uri": "https://meshb.nlm.nih.gov/record/ui?ui=D004576",
                "classification_code": "D004576",
            }
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_keywords_missing_term_fails(self, minimal_dataset, dataset_schema_path):
        """Keyword without required term should fail."""
        doc = copy.deepcopy(minimal_dataset)
        doc["keywords"] = [{"subject_scheme": "MeSH"}]
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_related_identifiers(self, minimal_dataset, dataset_schema_path):
        """Dataset with typed related identifiers should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["related_identifiers"] = [
            {
                "identifier": "10.1038/s41597-021-00883-1",
                "identifier_type": "DOI",
                "relation_type": "IsDescribedBy",
                "resource_type_general": "JournalArticle",
            },
            {
                "identifier": "https://physionet.org/content/hd-semg/1.0.0/",
                "identifier_type": "URL",
                "relation_type": "IsDerivedFrom",
                "resource_type_general": "Dataset",
            },
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_related_identifier_missing_relation_type_fails(
        self, minimal_dataset, dataset_schema_path
    ):
        """Related identifier without required relation_type should fail."""
        doc = copy.deepcopy(minimal_dataset)
        doc["related_identifiers"] = [
            {"identifier": "10.1234/test", "identifier_type": "DOI"}
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_contributors(self, minimal_dataset, dataset_schema_path):
        """Dataset with typed contributors should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["contributors"] = [
            {
                "name": "NEMAR",
                "name_type": "Organizational",
                "contributor_type": "HostingInstitution",
            },
            {
                "name": "Jane Smith",
                "given_name": "Jane",
                "family_name": "Smith",
                "contributor_type": "DataCollector",
                "orcid": "https://orcid.org/0000-0002-1234-5678",
            },
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_contributor_missing_type_fails(
        self, minimal_dataset, dataset_schema_path
    ):
        """Contributor without required contributor_type should fail."""
        doc = copy.deepcopy(minimal_dataset)
        doc["contributors"] = [{"name": "John Doe"}]
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_dates(self, minimal_dataset, dataset_schema_path):
        """Dataset with structured dates should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["dates"] = [
            {"date": "2026-02-17", "date_type": "Issued"},
            {
                "date": "2020-01/2021-06",
                "date_type": "Collected",
                "date_information": "Data collection period across two sites",
            },
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_date_missing_type_fails(self, minimal_dataset, dataset_schema_path):
        """Date without required date_type should fail."""
        doc = copy.deepcopy(minimal_dataset)
        doc["dates"] = [{"date": "2026-01-01"}]
        errors = validate_document(doc, dataset_schema_path)
        assert len(errors) > 0

    def test_rights(self, minimal_dataset, dataset_schema_path):
        """Dataset with structured rights entries should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["rights"] = [
            {
                "rights": "Open Data Commons Attribution License v1.0",
                "rights_uri": "https://opendatacommons.org/licenses/by/1.0/",
                "rights_identifier": "ODC-By-1.0",
                "rights_identifier_scheme": "SPDX",
            }
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_language(self, minimal_dataset, dataset_schema_path):
        """Dataset with language field should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["language"] = "en"
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_extended_funding(self, minimal_dataset, dataset_schema_path):
        """Dataset with extended funding fields should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["funding"] = [
            {
                "funder_name": "National Science Foundation",
                "funder_identifier": "https://doi.org/10.13039/100000001",
                "funder_identifier_type": "Crossref Funder ID",
                "award_number": "2030859",
                "award_title": "IUCRC Phase I UCSD: CLAN",
                "award_uri": "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2030859",
            }
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_person_name_type(self, minimal_dataset, dataset_schema_path):
        """Author with name_type enum should validate."""
        doc = copy.deepcopy(minimal_dataset)
        doc["authors"] = [
            {"name": "Jane Smith", "name_type": "Personal"},
            {"name": "Child Mind Institute", "name_type": "Organizational"},
        ]
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_nm000108_example_validates(self, dataset_schema_path):
        """Full nm000108 example with all v0.3.0 fields should validate."""
        doc = _load_example("dataset-nm000108.json")
        errors = validate_document(doc, dataset_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_nm000108_example_validates_root(self):
        """Full nm000108 example validates via root schema dispatch."""
        with open(EXAMPLES_DIR / "dataset-nm000108.json") as f:
            doc = json.load(f)
        errors = validate_document(doc)
        assert errors == [], [e.message for e in errors]
