"""Tests for the processing extensions (neuroschema 0.5.0; views from 0.6.0).

Validates real example documents and inline mutations against the actual
schema files. No mocks. Expected failures are asserted as (validator, path)
pairs so a negative test cannot pass for the wrong reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import (
    SCHEMA_BASE,
    load_schema,
    schema_id,
    validate_document,
    validate_file,
)
from tests.helpers import (
    cascade_problems,
    count_problems,
    failures,
    histogram_problems,
    quality_problems,
    range_problems,
    total_problems,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
DEFINITIONS = SCHEMA_DIR / "definitions"
EXTENSIONS = SCHEMA_DIR / "extensions"
VIEWS = SCHEMA_DIR / "views"
EXAMPLES_DIR = ROOT / "examples"

SHA = "a" * 64
PLUGIN = {"name": "nemar-dataqual", "version": "0.1.0"}
RECIPE = {"name": "nemar-floor", "version": "1.0.0-b1"}


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

    def test_missing_producer(self):
        doc = self.valid()
        del doc["plugin"]
        assert errors_for(METRIC, doc) == {("oneOf", "")}

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


# ── Schema graph: every $id is absolute and every $ref resolves ────────────


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
def test_id_is_the_base_and_the_path(path):
    """An absolute $id, so a relative $ref resolves by RFC 3986 in every engine."""
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert (
        schema["$id"]
        == schema_id(path)
        == SCHEMA_BASE + str(path.relative_to(SCHEMA_DIR).as_posix())
    )


def test_nothing_is_fetched():
    """A $ref to a schema that is not in schema/ fails; it is never fetched."""
    _schema, resolver = load_schema(DEFINITIONS / "view.schema.json")
    with pytest.raises(Exception, match="nothing is fetched"):
        resolver.resolve(SCHEMA_BASE + "definitions/absent.schema.json")


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
V0 = f"{FLOOR}/views/0"
V0D = f"{V0}/data/0"


def metric(value, unit, description):
    return {
        "value": value,
        "unit": unit,
        "description": description,
        "recipe": dict(RECIPE),
    }


def table_view(key, location, caption):
    return {
        "key": key,
        "kind": "nemar.table",
        "kind_version": 1,
        "caption": caption,
        "source": {"recipe": dict(RECIPE)},
        "data": [
            {
                "role": "table",
                "location": location,
                "format": "tsv",
                "size": 2214,
                "sha256": SHA,
                "columns": [
                    {"name": "name", "type": "string"},
                    {"name": "status", "type": "string"},
                ],
            }
        ],
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
                    "percentGoodSamples": metric(93.6, "%", "Share of samples kept."),
                    "lineNoiseAfterDb": metric(2.8, "dB", "Line noise after removal."),
                },
                "views": [
                    table_view("channels", "views/channels.tsv", "Channels."),
                    table_view("segments", "views/badsegments.tsv", "Bad segments."),
                ],
            }
        },
    }


def distribution():
    return {
        "n": 17,
        "unit": "%",
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
                "distributions": {"percentGoodSamples": distribution()},
                "observed_range": {"percentGoodChannels": {"min": 85.1, "max": 100.0}},
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
        metrics["line.noise"] = metrics.pop("lineNoiseAfterDb")
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{FLOOR}/metrics")}

    def _data(self, doc):
        return doc["recipes"]["nemar-floor"]["views"][0]["data"][0]

    def test_zero_size(self):
        doc = dq_record()
        self._data(doc)["size"] = 0
        assert errors_for(DATA_QUALITY, doc) == {("minimum", f"{V0D}/size")}

    def test_uppercase_sha(self):
        doc = dq_record()
        self._data(doc)["sha256"] = "A" * 64
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{V0D}/sha256")}

    def test_missing_caption(self):
        doc = dq_record()
        del doc["recipes"]["nemar-floor"]["views"][0]["caption"]
        assert errors_for(DATA_QUALITY, doc) == {("required", V0)}

    def test_format_must_match_extension(self):
        doc = dq_record()
        self._data(doc)["location"] = "views/channels.json"
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{V0D}/location")}

    @pytest.mark.parametrize(
        "location",
        ["/a.tsv", "../a.tsv", "a/../b.tsv", "https://h/a.tsv", "a\\b.tsv"],
    )
    def test_bad_location(self, location):
        doc = dq_record()
        self._data(doc)["location"] = location
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{V0D}/location")}

    def test_empty_location(self):
        doc = dq_record()
        self._data(doc)["location"] = ""
        assert errors_for(DATA_QUALITY, doc) == {
            ("minLength", f"{V0D}/location"),
            ("pattern", f"{V0D}/location"),
        }

    def test_zarr_needs_serving(self):
        doc = dq_record()
        doc["recipes"]["nemar-floor"]["profile"] = "archive"
        assert errors_for(DATA_QUALITY, doc) == {("const", f"{FLOOR}/profile")}

    def test_unknown_key_in_recipe(self):
        doc = dq_record()
        doc["recipes"]["nemar-floor"]["quality_score"] = 0.9
        assert errors_for(DATA_QUALITY, doc) == {("additionalProperties", FLOOR)}

    def test_metric_without_producer(self):
        doc = dq_record()
        del doc["recipes"]["nemar-floor"]["metrics"]["lineNoiseAfterDb"]["recipe"]
        assert errors_for(DATA_QUALITY, doc) == {
            ("oneOf", f"{FLOOR}/metrics/lineNoiseAfterDb"),
            ("required", f"{FLOOR}/metrics/lineNoiseAfterDb"),
        }


PLUGIN_PRODUCER = {"name": "nemar-quality", "version": "0.1.0"}


class TestMetricNames:
    """A recipe's metric has a bare name, a plugin's is <plugin>:<name>."""

    def _metrics(self, doc):
        return doc["recipes"]["nemar-floor"]["metrics"]

    def _plugin_metric(self):
        out = metric(50.0, "%", "Share of brain components.")
        del out["recipe"]
        return out | {"plugin": dict(PLUGIN_PRODUCER)}

    def test_a_plugin_metric_named_by_its_plugin(self):
        doc = dq_record()
        self._metrics(doc)["nemar-quality:percentBrainComponents"] = (
            self._plugin_metric()
        )
        assert errors_for(DATA_QUALITY, doc) == set()

    def test_a_bare_name_is_a_recipe_metric(self):
        """Fails if the bare pattern stops requiring the recipe producer."""
        doc = dq_record()
        self._metrics(doc)["percentBrainComponents"] = self._plugin_metric()
        assert errors_for(DATA_QUALITY, doc) == {
            ("required", f"{FLOOR}/metrics/percentBrainComponents")
        }

    def test_a_prefixed_name_is_a_plugin_metric(self):
        """Fails if the prefixed pattern stops requiring the plugin producer."""
        doc = dq_record()
        metrics = self._metrics(doc)
        metrics["nemar-floor:lineNoiseAfterDb"] = metrics.pop("lineNoiseAfterDb")
        assert errors_for(DATA_QUALITY, doc) == {
            ("required", f"{FLOOR}/metrics/nemar-floor:lineNoiseAfterDb")
        }

    @pytest.mark.parametrize(
        "name",
        [
            "nemar-quality:a:b",
            "nemar-quality:",
            "nemar-quality:9x",
            "nemar-quality:_x",
            "nemar-quality:x\n",
        ],
    )
    def test_the_part_after_the_colon_is_a_name(self, name):
        """One colon, then a letter: a name the manifest rule accepts."""
        doc = dq_record()
        self._metrics(doc)[name] = self._plugin_metric()
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{FLOOR}/metrics")}

    @pytest.mark.parametrize("name", ["nemar-quality:a:b", "nemar-quality:9x"])
    @pytest.mark.parametrize("member", ["distributions", "observed_range"])
    def test_dataset_level_keys_share_the_grammar(self, name, member):
        """A distribution's and an observed range's key is a metric name too."""
        doc = dq_dataset()
        entry = doc["recipes"]["nemar-floor"]
        values = entry[member]
        values[name] = values.pop(next(iter(values)))
        assert errors_for(DATA_QUALITY, doc) == {("pattern", f"{FLOOR}/{member}")}
        values["nemar-quality:percentBrainComponents"] = values.pop(name)
        assert errors_for(DATA_QUALITY, doc) == set()

    def test_the_example_names_its_producers(self):
        """The presets example carries one metric of each producer."""
        path = EXAMPLES_DIR / "views" / "dataquality-record-nemar-ica.json"
        doc = json.loads(path.read_text())
        assert errors_for(DATA_QUALITY, doc) == set()
        metrics = doc["recipes"]["nemar-ica"]["metrics"]
        assert {name: "plugin" in m for name, m in metrics.items()} == {
            "icaRank": False,
            "nemar-quality:percentBrainComponents": True,
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
        hist = doc["recipes"]["nemar-floor"]["distributions"]["percentGoodSamples"]
        hist["histogram"]["edges"] = [0]
        assert errors_for(DATA_QUALITY, doc) == {
            ("minItems", f"{FLOOR}/distributions/percentGoodSamples/histogram/edges")
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


# ── processing ────────────────────────────────────────────────────────────


PROCESSING = EXTENSIONS / "processing.schema.json"
ICA = "recipes/nemar-ica"


def proc_record():
    passed = {"status": "passed", "code": None, "step": None}
    failed = {"status": "failed", "code": "ica_degenerate", "step": "ica"}
    skipped = {"status": "skipped", "code": "ica_degenerate", "step": "ica"}
    return {
        "level": "record",
        "recipes": {
            "nemar-ica": {
                "recipe_version": "1.0.0-b1",
                "checkpoints": {
                    "import": dict(passed),
                    "preprocess": dict(passed),
                    "ica": failed,
                    "iclabel": dict(skipped),
                    "stored": dict(skipped),
                },
            }
        },
    }


def proc_dataset():
    def c(p, f, s):
        return {"passed": p, "failed": f, "skipped": s, "total": 18}

    return {
        "level": "dataset",
        "recipes": {
            "nemar-floor": {
                "recipe_version": "1.0.0-b1",
                "declared_checkpoints": ["import", "preprocess", "quality", "stored"],
                "counts": {
                    "import": c(17, 1, 0),
                    "preprocess": c(17, 0, 1),
                    "quality": c(17, 0, 1),
                    "stored": c(17, 0, 1),
                },
            }
        },
    }


class TestProcessingRecord:
    def _cp(self, doc, name):
        return doc["recipes"]["nemar-ica"]["checkpoints"][name]

    def test_valid(self):
        assert errors_for(PROCESSING, proc_record()) == set()

    def test_unknown_status(self):
        doc = proc_record()
        self._cp(doc, "import")["status"] = "ok"
        # A status that is not "passed" takes the else branch, so the null code
        # of this formerly passed checkpoint is also reported.
        assert errors_for(PROCESSING, doc) == {
            ("enum", f"{ICA}/checkpoints/import/status"),
            ("type", f"{ICA}/checkpoints/import/code"),
        }

    def test_passed_with_code(self):
        doc = proc_record()
        self._cp(doc, "import")["code"] = "load_failed"
        assert errors_for(PROCESSING, doc) == {
            ("type", f"{ICA}/checkpoints/import/code")
        }

    def test_failed_without_code(self):
        doc = proc_record()
        del self._cp(doc, "ica")["code"]
        assert errors_for(PROCESSING, doc) == {("required", f"{ICA}/checkpoints/ica")}

    def test_skipped_with_null_code(self):
        doc = proc_record()
        self._cp(doc, "iclabel")["code"] = None
        assert errors_for(PROCESSING, doc) == {
            ("type", f"{ICA}/checkpoints/iclabel/code")
        }

    def test_bad_checkpoint_name(self):
        doc = proc_record()
        cps = doc["recipes"]["nemar-ica"]["checkpoints"]
        cps["Import"] = cps.pop("import")
        assert errors_for(PROCESSING, doc) == {("pattern", f"{ICA}/checkpoints")}

    def test_empty_checkpoints(self):
        doc = proc_record()
        doc["recipes"]["nemar-ica"]["checkpoints"] = {}
        assert errors_for(PROCESSING, doc) == {("minProperties", f"{ICA}/checkpoints")}


class TestProcessingDataset:
    def _entry(self, doc):
        return doc["recipes"]["nemar-floor"]

    def test_valid(self):
        assert errors_for(PROCESSING, proc_dataset()) == set()

    def test_duplicate_declared(self):
        doc = proc_dataset()
        self._entry(doc)["declared_checkpoints"].append("import")
        assert errors_for(PROCESSING, doc) == {
            ("uniqueItems", f"{FLOOR}/declared_checkpoints")
        }

    def test_empty_declared(self):
        doc = proc_dataset()
        self._entry(doc)["declared_checkpoints"] = []
        assert errors_for(PROCESSING, doc) == {
            ("minItems", f"{FLOOR}/declared_checkpoints")
        }

    def test_negative_count(self):
        doc = proc_dataset()
        self._entry(doc)["counts"]["import"]["failed"] = -1
        assert errors_for(PROCESSING, doc) == {
            ("minimum", f"{FLOOR}/counts/import/failed")
        }

    def test_extra_count_key(self):
        doc = proc_dataset()
        self._entry(doc)["counts"]["import"]["remaining"] = 0
        assert errors_for(PROCESSING, doc) == {
            ("additionalProperties", f"{FLOOR}/counts/import")
        }


# ── signalJourney ─────────────────────────────────────────────────────────


SIGNAL_JOURNEY = EXTENSIONS / "signalJourney.schema.json"


def sj_links():
    return {
        "recipes": {
            "nemar-floor": {
                "recipe_version": "1.0.0-b1",
                "processing_status": "completed",
                "location": "sub-013/eeg/sub-013_desc-nemarfloor_signalJourney.json",
                "sha256": SHA,
                "sj_version": "0.1.0",
            }
        }
    }


class TestSignalJourney:
    def _link(self, doc):
        return doc["recipes"]["nemar-floor"]

    def test_valid(self):
        assert errors_for(SIGNAL_JOURNEY, sj_links()) == set()

    def test_in_progress_all_null(self):
        doc = sj_links()
        self._link(doc).update(
            processing_status="in_progress", location=None, sha256=None, sj_version=None
        )
        assert errors_for(SIGNAL_JOURNEY, doc) == set()

    def test_completed_without_sha(self):
        doc = sj_links()
        self._link(doc)["sha256"] = None
        assert errors_for(SIGNAL_JOURNEY, doc) == {("type", f"{FLOOR}/sha256")}

    def test_in_progress_with_location(self):
        doc = sj_links()
        self._link(doc).update(
            processing_status="in_progress", sha256=None, sj_version=None
        )
        assert errors_for(SIGNAL_JOURNEY, doc) == {("type", f"{FLOOR}/location")}

    def test_pending_is_gone(self):
        doc = sj_links()
        self._link(doc)["processing_status"] = "pending"
        assert errors_for(SIGNAL_JOURNEY, doc) == {
            ("enum", f"{FLOOR}/processing_status")
        }

    def test_bad_sj_version(self):
        doc = sj_links()
        self._link(doc)["sj_version"] = "0.1"
        assert errors_for(SIGNAL_JOURNEY, doc) == {("pattern", f"{FLOOR}/sj_version")}

    def test_missing_recipe_version(self):
        doc = sj_links()
        del self._link(doc)["recipe_version"]
        assert errors_for(SIGNAL_JOURNEY, doc) == {("required", FLOOR)}

    def test_missing_recipes(self):
        assert errors_for(SIGNAL_JOURNEY, {}) == {("required", "")}

    def test_open_root_keeps_legacy_key(self):
        doc = sj_links() | {"pipeline_id": "legacy"}
        assert errors_for(SIGNAL_JOURNEY, doc) == set()


# ── Ref convention: every $ref is a path from the schema's subfolder ──────


@pytest.mark.parametrize(
    "path",
    [p for p in ALL_SCHEMAS if p.parent != SCHEMA_DIR],
    ids=lambda p: p.name,
)
def test_refs_are_folder_qualified(path):
    """jsonschema's legacy RefResolver pushes a resolution scope for every
    schema with an $id it enters and never pops it (Validator.evolve), so a
    bare or fragment-only $ref can resolve against the wrong file. A ref that
    names its folder (../definitions/x, ../extensions/x, ../core/x, ../views/x)
    resolves the same from any subfolder, so every ref below the root takes
    that form.
    """
    assert folder_ref_problems(path) == []


FOLDER_REF = re.compile(
    r"^\.\./(?:(?:core|definitions|extensions)/[A-Za-z]+"
    r"|views/(?:kind|content|transform)(?:\.[a-z0-9-]+)+\.v[0-9]+)"
    r"\.schema\.json(?:#.*)?$"
)


def folder_ref_problems(path: Path) -> list[str]:
    return [
        ref for ref in _refs(json.loads(path.read_text())) if not FOLDER_REF.match(ref)
    ]


def test_folder_ref_check_catches_a_bare_view_ref(tmp_path):
    schema = json.loads((DEFINITIONS / "view.schema.json").read_text())
    schema["$defs"]["view"]["allOf"][1]["then"]["$ref"] = (
        "kind.nemar.table.v1.schema.json"
    )
    path = tmp_path / "view.schema.json"
    path.write_text(json.dumps(schema))
    assert folder_ref_problems(path) == ["kind.nemar.table.v1.schema.json"]


# ── Examples: embedded in full documents ──────────────────────────────────


DATASET_EXAMPLE = EXAMPLES_DIR / "dataset-ds002718-processing.json"
RECORD_EXAMPLE = EXAMPLES_DIR / "record-ds002718-processing.json"
ROOT_ONLY_KEYS = ("schema_version", "doc_type")


def _example(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.json")), ids=str)
def test_every_example_validates_against_root(path):
    assert validate_file(path) == []


@pytest.mark.parametrize(
    ("path", "core"),
    [(DATASET_EXAMPLE, "dataset"), (RECORD_EXAMPLE, "record")],
    ids=["dataset", "record"],
)
def test_example_validates_against_core(path, core):
    doc = {k: v for k, v in _example(path).items() if k not in ROOT_ONLY_KEYS}
    assert validate_document(doc, SCHEMA_DIR / "core" / f"{core}.schema.json") == []


def test_embedded_extension_error_is_reported_at_its_path():
    doc = _example(RECORD_EXAMPLE)
    doc["extensions"]["processing"]["recipes"]["nemar-floor"]["checkpoints"]["import"][
        "status"
    ] = "ok"
    path = "extensions/processing/recipes/nemar-floor/checkpoints/import"
    assert failures(validate_document(doc)) == {
        ("enum", f"{path}/status"),
        ("type", f"{path}/code"),
    }


# ── Invariants the schema cannot express ──────────────────────────────────


DECLARED = {
    "nemar-floor": ["import", "preprocess", "quality", "stored"],
    "nemar-ica": ["import", "preprocess", "ica", "iclabel", "stored"],
}


def _ext(path, ns):
    return _example(path)["extensions"][ns]


class TestInvariants:
    def test_examples_hold(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        assert count_problems(proc) == []
        assert total_problems(quality, proc) == []
        assert cascade_problems(_ext(RECORD_EXAMPLE, "processing"), DECLARED) == []
        for entry in quality["recipes"].values():
            for dist in entry["distributions"].values():
                assert histogram_problems(dist) == []

    def test_column_sum_mismatch(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        proc["recipes"]["nemar-floor"]["counts"]["quality"]["passed"] = 16
        problems = count_problems(proc)
        assert "nemar-floor/quality: passed+failed+skipped != total" in problems

    def test_unequal_totals(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        counts = proc["recipes"]["nemar-floor"]["counts"]["stored"]
        counts.update(skipped=2, total=19)
        assert "nemar-floor: checkpoints have unequal totals" in count_problems(proc)

    def test_count_keys_differ_from_declared(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        del proc["recipes"]["nemar-ica"]["counts"]["iclabel"]
        assert (
            "nemar-ica: count keys differ from declared checkpoints"
            in count_problems(proc)
        )

    def test_broken_cascade(self):
        proc = _ext(RECORD_EXAMPLE, "processing")
        proc["recipes"]["nemar-ica"]["checkpoints"]["stored"] = {
            "status": "passed",
            "code": None,
            "step": None,
        }
        assert cascade_problems(proc, DECLARED) == [
            "nemar-ica/stored: breaks the skip cascade"
        ]

    def test_bad_histogram_length(self):
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        dist = quality["recipes"]["nemar-floor"]["distributions"]["percentGoodSamples"]
        dist["histogram"]["counts"].append(0)
        assert "len(counts) != len(edges) - 1" in histogram_problems(dist)

    def test_quality_total_differs(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        quality["recipes"]["nemar-ica"]["counts"]["total"] = 19
        assert total_problems(quality, proc) == [
            "nemar-ica: dataQuality total differs from processing"
        ]


# ── Reachability: what nemar-cli's vendor script bundles ──────────────────


VENDOR_REF = re.compile(r'"\$ref":\s*"([^"#]+)(#[^"]*)?"')
NEW_OR_CHANGED = {
    "view.schema.json",
    "kind.nemar.table.v1.schema.json",
    "kind.nemar.lines.v1.schema.json",
    "kind.nemar.heatmap.v1.schema.json",
    "kind.nemar.histogram.v1.schema.json",
    "content.nemar.histogram.v1.schema.json",
    "processingTypes.schema.json",
    "checkpointCounts.schema.json",
    "qualityMetric.schema.json",
    "dataQuality.schema.json",
    "processing.schema.json",
    "signalJourney.schema.json",
}


def _reachable(start: Path) -> set[str]:
    seen: set[Path] = set()
    todo = [start.resolve()]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for match in VENDOR_REF.finditer(path.read_text()):
            todo.append((path.parent / match.group(1)).resolve())
    return {p.name for p in seen}


@pytest.mark.parametrize("core", ["dataset", "record"])
def test_new_files_reachable_from_core(core):
    reachable = _reachable(SCHEMA_DIR / "core" / f"{core}.schema.json")
    assert reachable >= NEW_OR_CHANGED


# ── Manager table: docs and x-extension-managers agree ────────────────────


def test_manager_table_matches_container():
    container = json.loads((EXTENSIONS / "extensionsContainer.schema.json").read_text())
    managers = {
        ns: (entry["manager"], entry["collection"])
        for ns, entry in container["x-extension-managers"].items()
        if ns not in ("description", "core")
    }
    rows = re.findall(
        r"^\| (\w+) \| ([\w-]+) \| `(\w+)` \|",
        (ROOT / "docs" / "extension-managers.md").read_text(),
        flags=re.MULTILINE,
    )
    table = {ns: (manager, collection) for ns, manager, collection in rows}
    assert table == managers
    for ns in ("dataQuality", "processing", "signalJourney"):
        assert managers[ns][0] == "nemar-api"


# ── Anchors: a trailing newline never passes (Python's $ allows one) ──────


PT_FILE = DEFINITIONS / "processingTypes.schema.json"
VALID_BY_DEF = {
    "recipeId": "nemar-floor",
    "version": "1.0.0-b1",
    "sha256": SHA,
    "checkpointName": "preprocess",
    "stepId": "bad_windows",
    "failureCode": "load_failed",
    "metricName": "percentGoodSamples",
    "relativeLocation": "views/channels.tsv",
    "viewKey": "icmaps",
    "kindName": "nemar.sensor-field",
    "transformName": "nemar.ic-activity.v1",
    "roleName": "values",
    "dimName": "freq",
    "formatName": "tsv",
}


def _def_errors(name: str, value) -> list:
    _schema, resolver = load_schema(PT_FILE)
    validator = Draft202012Validator(
        {"$ref": f"file://{PT_FILE}#/$defs/{name}"}, resolver=resolver
    )
    return list(validator.iter_errors(value))


@pytest.mark.parametrize(("name", "value"), sorted(VALID_BY_DEF.items()))
def test_def_accepts_valid_value(name, value):
    assert _def_errors(name, value) == []


@pytest.mark.parametrize(("name", "value"), sorted(VALID_BY_DEF.items()))
def test_def_rejects_trailing_newline(name, value):
    assert [e.validator for e in _def_errors(name, value + "\n")] == ["pattern"]


def test_plugin_name_rejects_trailing_newline():
    assert [e.validator for e in _def_errors("plugin", PLUGIN | {"name": "x\n"})] == [
        "pattern"
    ]


def test_sj_version_rejects_trailing_newline():
    doc = sj_links()
    doc["recipes"]["nemar-floor"]["sj_version"] = "0.1.0\n"
    assert errors_for(SIGNAL_JOURNEY, doc) == {
        ("pattern", "recipes/nemar-floor/sj_version")
    }


@pytest.mark.parametrize("field", ["location", "sha256", "sj_version"])
def test_failed_link_has_no_record(field):
    doc = sj_links()
    link = doc["recipes"]["nemar-floor"]
    link.update(processing_status="failed", location=None, sha256=None, sj_version=None)
    assert errors_for(SIGNAL_JOURNEY, doc) == set()
    link[field] = sj_links()["recipes"]["nemar-floor"][field]
    assert errors_for(SIGNAL_JOURNEY, doc) == {("type", f"recipes/nemar-floor/{field}")}


# ── Invariant helpers: each check fails on its own mutation ───────────────


def _floor_dist(name="percentGoodSamples"):
    quality = _ext(DATASET_EXAMPLE, "dataQuality")
    return quality["recipes"]["nemar-floor"]["distributions"][name]


class TestHelperMutations:
    def test_quality_examples_hold(self):
        assert quality_problems(_ext(DATASET_EXAMPLE, "dataQuality")) == []

    def test_edges_not_increasing(self):
        dist = _floor_dist()
        dist["histogram"]["edges"][3] = dist["histogram"]["edges"][2]
        assert histogram_problems(dist) == ["edges not strictly increasing"]

    def test_min_outside_first_bin(self):
        dist = _floor_dist()
        dist["min"] = 91.0  # first non-empty bin is [80, 90)
        assert "min is not in the first non-empty bin" in histogram_problems(dist)

    def test_max_outside_last_bin(self):
        dist = _floor_dist("lineNoiseBeforeDb")
        dist["max"] = 31.0  # last non-empty bin is [20, 30)
        assert "max is not in the last non-empty bin" in histogram_problems(dist)

    def test_median_order(self):
        dist = _floor_dist()
        dist["median"] = dist["max"] + 1
        assert "not min <= median <= max" in histogram_problems(dist)

    def test_median_bin(self):
        dist = _floor_dist("lineNoiseBeforeDb")
        dist["median"] = 21.0  # cumulative counts put the median in [10, 15)
        assert histogram_problems(dist) == [
            "median is not in the bin the cumulative counts give"
        ]

    def test_undeclared_checkpoint(self):
        proc = _ext(RECORD_EXAMPLE, "processing")
        proc["recipes"]["nemar-floor"]["checkpoints"]["figures"] = {
            "status": "passed",
            "code": None,
            "step": None,
        }
        assert cascade_problems(proc, DECLARED) == [
            "nemar-floor: undeclared checkpoints ['figures']"
        ]

    def test_skipped_drops_along_order(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        proc["recipes"]["nemar-ica"]["counts"]["iclabel"].update(passed=17, skipped=1)
        problems = count_problems(proc)
        assert "nemar-ica/iclabel: skipped below earlier failed+skipped" in problems
        assert "nemar-ica/iclabel: passed above the earlier checkpoint" in problems

    def test_quality_counts_sum(self):
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        quality["recipes"]["nemar-ica"]["counts"]["passed"] = 15
        assert "nemar-ica: passed+failed+skipped != total" in quality_problems(quality)

    def test_not_processed_coverage(self):
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        quality["recipes"]["nemar-ica"]["not_processed"].pop()
        assert quality_problems(quality) == [
            "nemar-ica: not_processed does not cover failed+skipped"
        ]


# ── Coverage tables: every closed object, every required key ──────────────


def _at(doc, path: str):
    node = doc
    for part in path.split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


PGS = f"{FLOOR}/distributions/percentGoodSamples"
CLOSED = [
    (DATA_QUALITY, dq_record, FLOOR),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples"),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples/recipe"),
    (DATA_QUALITY, dq_record, V0),
    (DATA_QUALITY, dq_record, f"{V0}/source"),
    (DATA_QUALITY, dq_record, f"{V0}/source/recipe"),
    (DATA_QUALITY, dq_record, V0D),
    (DATA_QUALITY, dq_record, f"{V0D}/columns/0"),
    (DATA_QUALITY, dq_dataset, FLOOR),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/counts"),
    (DATA_QUALITY, dq_dataset, PGS),
    (DATA_QUALITY, dq_dataset, f"{PGS}/histogram"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/observed_range/percentGoodChannels"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/not_processed/0"),
    (PROCESSING, proc_record, ICA),
    (PROCESSING, proc_record, f"{ICA}/checkpoints/ica"),
    (PROCESSING, proc_dataset, FLOOR),
    (PROCESSING, proc_dataset, f"{FLOOR}/counts/import"),
    (SIGNAL_JOURNEY, sj_links, FLOOR),
]


@pytest.mark.parametrize(
    ("schema", "builder", "path"),
    CLOSED,
    ids=[f"{b.__name__}:{p}" for _, b, p in CLOSED],
)
def test_every_closed_object_refuses_unknown_key(schema, builder, path):
    doc = builder()
    _at(doc, path)["unexpected_key"] = 1
    assert errors_for(schema, doc) == {("additionalProperties", path)}


REQUIRED_KEYS = [
    (DATA_QUALITY, dq_record, FLOOR, "recipe_version input_kind profile"),
    (DATA_QUALITY, dq_record, FLOOR, "record_sha256 metrics views"),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples", "value unit"),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples", "description"),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples/recipe", "name"),
    (DATA_QUALITY, dq_record, f"{FLOOR}/metrics/percentGoodSamples/recipe", "version"),
    (DATA_QUALITY, dq_record, V0, "key kind kind_version caption source"),
    (DATA_QUALITY, dq_record, V0D, "role location format size sha256 columns"),
    (DATA_QUALITY, dq_record, f"{V0D}/columns/0", "name type"),
    (DATA_QUALITY, dq_dataset, FLOOR, "recipe_version dataset_version input_kind"),
    (DATA_QUALITY, dq_dataset, FLOOR, "profile record_sha256 counts distributions"),
    (DATA_QUALITY, dq_dataset, FLOOR, "observed_range not_processed"),
    (DATA_QUALITY, dq_dataset, FLOOR, "not_processed_truncated"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/counts", "passed failed skipped total"),
    (DATA_QUALITY, dq_dataset, PGS, "n unit min median max histogram"),
    (DATA_QUALITY, dq_dataset, f"{PGS}/histogram", "edges counts underflow overflow"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/observed_range/percentGoodChannels", "min"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/observed_range/percentGoodChannels", "max"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/not_processed/0", "path status code"),
    (PROCESSING, proc_record, ICA, "recipe_version checkpoints"),
    (PROCESSING, proc_record, f"{ICA}/checkpoints/ica", "status code"),
    (PROCESSING, proc_dataset, FLOOR, "recipe_version declared_checkpoints counts"),
    (PROCESSING, proc_dataset, f"{FLOOR}/counts/import", "passed failed skipped"),
    (PROCESSING, proc_dataset, f"{FLOOR}/counts/import", "total"),
    (SIGNAL_JOURNEY, sj_links, FLOOR, "recipe_version processing_status location"),
    (SIGNAL_JOURNEY, sj_links, FLOOR, "sha256 sj_version"),
]
REQUIRED = [
    (schema, builder, path, key)
    for schema, builder, path, keys in REQUIRED_KEYS
    for key in keys.split()
]


@pytest.mark.parametrize(
    ("schema", "builder", "path", "key"),
    REQUIRED,
    ids=[f"{b.__name__}:{p}:{k}" for _, b, p, k in REQUIRED],
)
def test_every_required_key_is_required(schema, builder, path, key):
    doc = builder()
    del _at(doc, path)[key]
    assert errors_for(schema, doc) == {("required", path)}


# ── Explicit edge cases ───────────────────────────────────────────────────


def _set(builder, path, value):
    doc = builder()
    parent, _, key = path.rpartition("/")
    target = _at(doc, parent) if parent else doc
    if isinstance(target, list):
        target[int(key)] = value
    else:
        target[key] = value
    return doc


CASES = [
    # (schema, builder, path set, value, expected failures)
    (PROCESSING, proc_record, f"{ICA}/checkpoints/import/step", "load", "type"),
    (DATA_QUALITY, dq_record, f"{V0D}/location", "views/channels.json", "pattern"),
    # A nullable shared type is anyOf[pattern, null], so a bad value reports anyOf.
    (PROCESSING, proc_record, f"{ICA}/checkpoints/ica/step", "-ica", "anyOf"),
    (PROCESSING, proc_record, f"{ICA}/checkpoints/ica/code", "Bad", "anyOf"),
    (DATA_QUALITY, dq_record, f"{V0}/source/recipe/name", "Nemar", "pattern"),
    (DATA_QUALITY, dq_record, f"{V0D}/location", "tab\x01.tsv", "pattern"),
    (DATA_QUALITY, dq_record, f"{V0}/caption", "c" * 501, "maxLength"),
    (DATA_QUALITY, dq_record, f"{V0D}/location", "a" * 1021 + ".tsv", "maxLength"),
    (
        DATA_QUALITY,
        dq_record,
        f"{FLOOR}/metrics/percentGoodSamples/unit",
        "u" * 33,
        "maxLength",
    ),
    (
        DATA_QUALITY,
        dq_record,
        f"{FLOOR}/metrics/percentGoodSamples/description",
        "d" * 501,
        "maxLength",
    ),
    (DATA_QUALITY, dq_dataset, f"{PGS}/histogram/counts/0", -1, "minimum"),
    (DATA_QUALITY, dq_dataset, f"{FLOOR}/not_processed_truncated", -1, "minimum"),
    (PROCESSING, proc_dataset, f"{FLOOR}/counts", {}, "minProperties"),
    (SIGNAL_JOURNEY, sj_links, f"{FLOOR}/location", None, "type"),
    (SIGNAL_JOURNEY, sj_links, f"{FLOOR}/sj_version", None, "type"),
]


@pytest.mark.parametrize(
    ("schema", "builder", "path", "value", "expected"),
    CASES,
    ids=[f"{b.__name__}:{p.rsplit('/', 1)[-1]}:{e}" for _, b, p, _, e in CASES],
)
def test_edge_case(schema, builder, path, value, expected):
    doc = _set(builder, path, value)
    validator, _, at = expected.partition("@")
    where = path.rsplit("/", 1)[0] + "/" + at if at else path
    assert errors_for(schema, doc) == {(validator, where)}


def test_bids_needs_archive():
    doc = dq_record()
    _at(doc, FLOOR)["input_kind"] = "bids"
    assert errors_for(DATA_QUALITY, doc) == {("const", f"{FLOOR}/profile")}


@pytest.mark.parametrize("field", ["sha256", "sj_version"])
def test_in_progress_with_value(field):
    doc = sj_links()
    link = _at(doc, FLOOR)
    value = link[field]
    link.update(
        processing_status="in_progress", location=None, sha256=None, sj_version=None
    )
    link[field] = value
    assert errors_for(SIGNAL_JOURNEY, doc) == {("type", f"{FLOOR}/{field}")}


def test_processing_missing_level():
    doc = proc_record()
    del doc["level"]
    assert errors_for(PROCESSING, doc) == {("required", "")}


def test_null_dataset_version_and_range_min_are_allowed():
    doc = dq_dataset()
    _at(doc, FLOOR)["dataset_version"] = None
    _at(doc, f"{FLOOR}/observed_range/percentGoodChannels")["min"] = None
    assert errors_for(DATA_QUALITY, doc) == set()


# ── Every anchored pattern in extensions and definitions closes the gap ───


# Older patterns with a bare $, tracked in nemarOrg/neuroschema#20.
NEWLINE_GAP_ALLOWLIST = {("dataPaper.schema.json", "^10\\.\\d{4,9}/\\S+$")}


def _patterns(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                yield value
            else:
                yield from _patterns(value)
    elif isinstance(node, list):
        for item in node:
            yield from _patterns(item)


def anchor_problems(paths) -> list[str]:
    problems = []
    for path in paths:
        for pattern in _patterns(json.loads(path.read_text())):
            if (path.name, pattern) in NEWLINE_GAP_ALLOWLIST:
                continue
            if "$" in pattern and not pattern.endswith("$(?!\n)"):
                problems.append(f"{path.name}: {pattern!r}")
    return problems


def test_anchored_patterns_close_the_newline_gap():
    paths = sorted(
        [
            *EXTENSIONS.glob("*.schema.json"),
            *DEFINITIONS.glob("*.schema.json"),
            *VIEWS.glob("*.schema.json"),
        ]
    )
    assert VIEWS.is_dir() and any(p.parent == VIEWS for p in paths)
    assert anchor_problems(paths) == []


def test_anchor_check_catches_a_bare_dollar(tmp_path):
    schema = json.loads((DEFINITIONS / "processingTypes.schema.json").read_text())
    schema["$defs"]["sha256"]["pattern"] = "^[0-9a-f]{64}$"
    path = tmp_path / "processingTypes.schema.json"
    path.write_text(json.dumps(schema))
    assert anchor_problems([path]) == ["processingTypes.schema.json: '^[0-9a-f]{64}$'"]


class TestOrderMessages:
    def test_order_message_names_the_right_checkpoint(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        entry = proc["recipes"]["nemar-ica"]
        del entry["counts"]["preprocess"]
        entry["counts"]["ica"].update(passed=18, failed=0, skipped=0)
        problems = count_problems(proc)
        assert "nemar-ica/ica: passed above the earlier checkpoint" in problems
        assert not any("nemar-ica/iclabel: passed" in p for p in problems)


class TestLastCheckpointTotals:
    def test_quality_passed_matches_last_checkpoint(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        quality["recipes"]["nemar-ica"]["counts"].update(passed=17, failed=1)
        assert total_problems(quality, proc) == [
            "nemar-ica: dataQuality passed differs from the last checkpoint",
            "nemar-ica: dataQuality failed+skipped differs from the last checkpoint",
        ]

    def test_quality_not_processed_matches_last_checkpoint(self):
        proc = _ext(DATASET_EXAMPLE, "processing")
        quality = _ext(DATASET_EXAMPLE, "dataQuality")
        proc["recipes"]["nemar-floor"]["counts"]["stored"].update(passed=16, skipped=2)
        problems = total_problems(quality, proc)
        assert (
            "nemar-floor: dataQuality passed differs from the last checkpoint"
            in problems
        )
        assert (
            "nemar-floor: dataQuality failed+skipped differs from the last checkpoint"
            in problems
        )


class TestRanges:
    def test_examples_hold(self):
        for path in (DATASET_EXAMPLE, RECORD_EXAMPLE):
            assert range_problems(_example(path)) == []

    def test_metric_bounds_order(self):
        doc = _example(RECORD_EXAMPLE)
        metric = doc["extensions"]["dataQuality"]["recipes"]["nemar-floor"]["metrics"][
            "percentGoodSamples"
        ]
        metric["bounds"] = {"min": 100, "max": 0}
        assert range_problems(doc) == [
            "nemar-floor/metrics/percentGoodSamples/bounds: min > max"
        ]

    def test_observed_range_order(self):
        doc = _example(DATASET_EXAMPLE)
        entry = doc["extensions"]["dataQuality"]["recipes"]["nemar-ica"]
        entry["observed_range"]["icaRank"] = {"min": 64, "max": 55}
        problems = range_problems(doc)
        assert "nemar-ica/observed_range/icaRank: min > max" in problems

    def test_observed_range_matches_distribution(self):
        doc = _example(DATASET_EXAMPLE)
        entry = doc["extensions"]["dataQuality"]["recipes"]["nemar-floor"]
        entry["observed_range"]["percentGoodSamples"]["max"] = 99.0
        where = "nemar-floor/observed_range/percentGoodSamples"
        assert range_problems(doc) == [f"{where}: differs from its distribution"]

    def test_null_end_is_not_ordered(self):
        doc = _example(DATASET_EXAMPLE)
        entry = doc["extensions"]["dataQuality"]["recipes"]["nemar-floor"]
        entry["observed_range"]["snrDb"] = {"min": None, "max": -50}
        assert range_problems(doc) == []
