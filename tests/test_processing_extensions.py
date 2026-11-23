"""Tests for the ADR 0134 processing extensions (neuroschema 0.5.0).

Validates real example documents and inline mutations against the actual
schema files. No mocks. Expected failures are asserted as (validator, path)
pairs so a negative test cannot pass for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema, validate_document
from tests.helpers import failures

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
DEFINITIONS = SCHEMA_DIR / "definitions"
EXTENSIONS = SCHEMA_DIR / "extensions"
EXAMPLES_DIR = ROOT / "examples"

SHA = "a" * 64
PLUGIN = {"name": "nemar-dataqual", "version": "0.1.0"}


def errors_for(schema_path: Path, instance) -> set[tuple[str, str]]:
    return failures(validate_document(instance, schema_path))


# ── Shared definitions ────────────────────────────────────────────────────


COUNTS = DEFINITIONS / "checkpointCounts.schema.json"
METRIC = DEFINITIONS / "qualityMetric.schema.json"


class TestCheckpointCounts:
    def valid(self):
        return {"passed": 17, "failed": 1, "skipped": 0, "total": 18}

    def test_valid(self):
        assert errors_for(COUNTS, self.valid()) == set()

    def test_negative_count(self):
        doc = self.valid() | {"passed": -1}
        assert errors_for(COUNTS, doc) == {("minimum", "passed")}

    def test_missing_total(self):
        doc = self.valid()
        del doc["total"]
        assert errors_for(COUNTS, doc) == {("required", "")}

    def test_extra_key(self):
        doc = self.valid() | {"remaining": 0}
        assert errors_for(COUNTS, doc) == {("additionalProperties", "")}

    @pytest.mark.parametrize("value", [1.5, True])
    def test_non_integer(self, value):
        doc = self.valid() | {"failed": value}
        assert errors_for(COUNTS, doc) == {("type", "failed")}


class TestQualityMetric:
    def valid(self):
        return {
            "value": 93.2,
            "unit": "%",
            "description": "Share of samples kept after bad-window rejection.",
            "bounds": {"min": 0, "max": 100},
            "plugin": dict(PLUGIN),
        }

    def test_valid_full(self):
        assert errors_for(METRIC, self.valid()) == set()

    def test_valid_without_bounds(self):
        doc = self.valid()
        del doc["bounds"]
        assert errors_for(METRIC, doc) == set()

    def test_null_value(self):
        assert errors_for(METRIC, self.valid() | {"value": None}) == set()

    def test_missing_plugin(self):
        doc = self.valid()
        del doc["plugin"]
        assert errors_for(METRIC, doc) == {("required", "")}

    def test_empty_unit(self):
        assert errors_for(METRIC, self.valid() | {"unit": ""}) == {
            ("minLength", "unit")
        }

    def test_string_value(self):
        assert errors_for(METRIC, self.valid() | {"value": "93"}) == {("type", "value")}

    def test_bounds_extra_key(self):
        doc = self.valid()
        doc["bounds"]["step"] = 1
        assert errors_for(METRIC, doc) == {("additionalProperties", "bounds")}

    def test_bad_plugin_version(self):
        doc = self.valid()
        doc["plugin"]["version"] = "1 0"
        assert errors_for(METRIC, doc) == {("pattern", "plugin/version")}


# ── Schema graph: every $id is its file name and every $ref resolves ───────


ALL_SCHEMAS = sorted(SCHEMA_DIR.rglob("*.schema.json"))


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: p.name)
def test_id_is_file_name(path):
    schema = json.loads(path.read_text())
    assert schema["$id"] == path.name


@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: p.name)
def test_every_ref_resolves(path):
    schema, resolver = load_schema(path)
    Draft202012Validator.check_schema(schema)
    for ref in _refs(schema):
        # Resolve relative to the file, the way the validator enters it.
        resolver.push_scope(f"file://{path}")
        try:
            resolved = resolver.resolve(ref)[1]
        finally:
            resolver.pop_scope()
        assert isinstance(resolved, dict), f"{path.name}: {ref}"


# ── dataQuality ───────────────────────────────────────────────────────────


DATA_QUALITY = EXTENSIONS / "dataQuality.schema.json"
FLOOR = "recipes/nemar-floor"


def metric(value, unit, description):
    return {
        "value": value,
        "unit": unit,
        "description": description,
        "plugin": dict(PLUGIN),
    }


def figure(location, fmt, caption):
    return {
        "location": location,
        "format": fmt,
        "size": 48213,
        "sha256": SHA,
        "caption": caption,
        "plugin": dict(PLUGIN),
    }


def dq_record():
    return {
        "level": "record",
        "recipes": {
            "nemar-floor": {
                "recipe_version": "1.0.0-b1",
                "input_kind": "zarr",
                "profile": "serving",
                "record_sha256": SHA,
                "metrics": {
                    "pctGoodSamples": metric(93.2, "%", "Share of samples kept."),
                    "lineNoise": metric(4.1, "dB", "Line-noise magnitude."),
                },
                "figures": [
                    figure("figures/spectrum.svg", "svg", "Power spectrum."),
                    figure(
                        "figures/activations.svg",
                        "svg",
                        "Component activations (time series).",
                    ),
                ],
            }
        },
    }


def distribution():
    return {
        "n": 17,
        "min": 80.0,
        "median": 94.0,
        "max": 99.0,
        "histogram": {
            "edges": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            "counts": [0, 0, 0, 0, 0, 0, 0, 0, 3, 14],
            "underflow": 0,
            "overflow": 0,
        },
    }


def dq_dataset():
    return {
        "level": "dataset",
        "recipes": {
            "nemar-floor": {
                "recipe_version": "1.0.0-b1",
                "dataset_version": "1.0.0",
                "input_kind": "zarr",
                "profile": "serving",
                "record_sha256": SHA,
                "counts": {"passed": 17, "failed": 1, "skipped": 0, "total": 18},
                "distributions": {"pctGoodSamples": distribution()},
                "bounds": {"nGoodChannels": {"min": 58, "max": 64}},
                "not_processed": [
                    {
                        "path": "sub-002/eeg/sub-002_task-FaceRecognition_eeg.set",
                        "status": "failed",
                        "code": "load_failed",
                    }
                ],
                "not_processed_truncated": 0,
            }
        },
    }


class TestDataQualityRecord:
    def test_valid(self):
        assert errors_for(DATA_QUALITY, dq_record()) == set()

    def test_time_series_svg_is_allowed_here(self):
        """The raster-only rule for time series lives in signalJourney's nemar
        namespace, not in neuroschema; the activations figure above is SVG."""
        doc = dq_record()
        assert doc["recipes"]["nemar-floor"]["figures"][1]["format"] == "svg"
        assert errors_for(DATA_QUALITY, doc) == set()

    def test_missing_level(self):
        doc = dq_record()
        del doc["level"]
        assert errors_for(DATA_QUALITY, doc) == {("required", "")}

    def test_unknown_level(self):
        doc = dq_record() | {"level": "recording"}
        assert errors_for(DATA_QUALITY, doc) == {("enum", "level")}

    def test_bad_recipe_key(self):
        doc = dq_record()
        doc["recipes"]["Nemar_Floor"] = doc["recipes"].pop("nemar-floor")
        assert errors_for(DATA_QUALITY, doc) == {("pattern", "recipes")}

    def test_bad_metric_key(self):
        doc = dq_record()
        metrics = doc["recipes"]["nemar-floor"]["metrics"]
        metrics["line.noise"] = metrics.pop("lineNoise")
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{FLOOR}/metrics")}

    def _fig(self, doc):
        return doc["recipes"]["nemar-floor"]["figures"][0]

    def test_bad_format(self):
        doc = dq_record()
        self._fig(doc).update(format="jpg", location="figures/spectrum.jpg")
        assert errors_for(DATA_QUALITY, doc) == {("enum", f"{FLOOR}/figures/0/format")}

    def test_zero_size(self):
        doc = dq_record()
        self._fig(doc)["size"] = 0
        assert errors_for(DATA_QUALITY, doc) == {("minimum", f"{FLOOR}/figures/0/size")}

    def test_uppercase_sha(self):
        doc = dq_record()
        self._fig(doc)["sha256"] = "A" * 64
        assert errors_for(DATA_QUALITY, doc) == {
            ("pattern", f"{FLOOR}/figures/0/sha256")
        }

    def test_missing_caption(self):
        doc = dq_record()
        del self._fig(doc)["caption"]
        assert errors_for(DATA_QUALITY, doc) == {("required", f"{FLOOR}/figures/0")}

    def test_missing_figure_plugin(self):
        doc = dq_record()
        del self._fig(doc)["plugin"]
        assert errors_for(DATA_QUALITY, doc) == {("required", f"{FLOOR}/figures/0")}

    def test_format_must_match_extension(self):
        doc = dq_record()
        self._fig(doc)["location"] = "figures/spectrum.png"
        assert errors_for(DATA_QUALITY, doc) == {
            ("pattern", f"{FLOOR}/figures/0/location")
        }

    @pytest.mark.parametrize(
        "location",
        ["/a.svg", "../a.svg", "a/../b.svg", "https://h/a.svg", "a\\b.svg"],
    )
    def test_bad_location(self, location):
        doc = dq_record()
        self._fig(doc)["location"] = location
        assert errors_for(DATA_QUALITY, doc) == {
            ("pattern", f"{FLOOR}/figures/0/location")
        }

    def test_empty_location(self):
        doc = dq_record()
        self._fig(doc)["location"] = ""
        assert errors_for(DATA_QUALITY, doc) == {
            ("minLength", f"{FLOOR}/figures/0/location"),
            ("pattern", f"{FLOOR}/figures/0/location"),
        }

    def test_zarr_needs_serving(self):
        doc = dq_record()
        doc["recipes"]["nemar-floor"]["profile"] = "archive"
        assert errors_for(DATA_QUALITY, doc) == {("const", f"{FLOOR}/profile")}

    def test_unknown_key_in_recipe(self):
        doc = dq_record()
        doc["recipes"]["nemar-floor"]["quality_score"] = 0.9
        assert errors_for(DATA_QUALITY, doc) == {("additionalProperties", FLOOR)}

    def test_metric_without_plugin(self):
        doc = dq_record()
        del doc["recipes"]["nemar-floor"]["metrics"]["lineNoise"]["plugin"]
        assert errors_for(DATA_QUALITY, doc) == {
            ("required", f"{FLOOR}/metrics/lineNoise")
        }


class TestDataQualityDataset:
    def test_valid(self):
        assert errors_for(DATA_QUALITY, dq_dataset()) == set()

    def test_counts_missing_skipped(self):
        doc = dq_dataset()
        del doc["recipes"]["nemar-floor"]["counts"]["skipped"]
        assert errors_for(DATA_QUALITY, doc) == {("required", f"{FLOOR}/counts")}

    def test_one_edge(self):
        doc = dq_dataset()
        hist = doc["recipes"]["nemar-floor"]["distributions"]["pctGoodSamples"]
        hist["histogram"]["edges"] = [0]
        assert errors_for(DATA_QUALITY, doc) == {
            ("minItems", f"{FLOOR}/distributions/pctGoodSamples/histogram/edges")
        }

    def test_not_processed_passed(self):
        doc = dq_dataset()
        doc["recipes"]["nemar-floor"]["not_processed"][0]["status"] = "passed"
        assert errors_for(DATA_QUALITY, doc) == {
            ("enum", f"{FLOOR}/not_processed/0/status")
        }

    def test_not_processed_cap(self):
        doc = dq_dataset()
        entry = doc["recipes"]["nemar-floor"]["not_processed"][0]
        doc["recipes"]["nemar-floor"]["not_processed"] = [entry] * 201
        assert errors_for(DATA_QUALITY, doc) == {("maxItems", f"{FLOOR}/not_processed")}

    def test_record_shape_under_dataset_level(self):
        doc = dq_record() | {"level": "dataset"}
        found = errors_for(DATA_QUALITY, doc)
        assert ("required", FLOOR) in found
        assert ("additionalProperties", FLOOR) in found
        assert {path for _, path in found} == {FLOOR}
