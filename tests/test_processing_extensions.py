"""Tests for the ADR 0134 processing extensions (neuroschema 0.5.0).

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

from neuroschema.validate import load_schema, validate_document, validate_file
from tests.helpers import (
    cascade_problems,
    count_problems,
    failures,
    histogram_problems,
    total_problems,
)

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
    names its folder (../definitions/x, ../extensions/x, ../core/x) resolves
    the same from any subfolder, so every ref below the root takes that form.
    """
    bad = [
        ref
        for ref in _refs(json.loads(path.read_text()))
        if not re.match(
            r"^\.\./(core|definitions|extensions)/[A-Za-z]+\.schema\.json(#.*)?$", ref
        )
    ]
    assert bad == []


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
        dist = quality["recipes"]["nemar-floor"]["distributions"]["pctGoodSamples"]
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
