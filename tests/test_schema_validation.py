"""Tests for neuroschema schema validation.

Uses real example documents from the examples/ directory and validates
against the actual JSON Schema files. No mocks.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from neuroschema.validate import validate_document

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


@pytest.fixture
def schema1():
    with open(EXAMPLES_DIR / "schema1.json") as f:
        return json.load(f)


@pytest.fixture
def schema2():
    with open(EXAMPLES_DIR / "schema2.json") as f:
        return json.load(f)


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
        root_keys = ("schema_version", "doc_type")
        doc = {k: v for k, v in schema1.items() if k not in root_keys}
        errors = validate_document(doc, record_schema_path)
        assert errors == [], [e.message for e in errors]

    def test_schema2_validates_against_record(self, schema2, record_schema_path):
        """schema2.json (ds005514 record) passes record schema validation."""
        root_keys = ("schema_version", "doc_type")
        doc = {k: v for k, v in schema2.items() if k not in root_keys}
        errors = validate_document(doc, record_schema_path)
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
            "publisher": "OpenNeuro",
            "publication_year": 2025,
            "resource_type": "EEG Dataset",
            "resource_type_general": "Dataset",
            "contributors": [
                {
                    "name": "John Doe",
                    "contributor_type": "DataCurator",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                }
            ],
            "related_identifiers": [
                {
                    "identifier": "10.1234/paper.2025",
                    "identifier_type": "DOI",
                    "relation_type": "IsDescribedBy",
                }
            ],
            "language": "en",
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
