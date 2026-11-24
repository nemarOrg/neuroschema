"""The scalp map's model (``nemar.sensor-field``) against its vectors.

``docs/views/sensor-field.md`` (The model, The order of checks) is the
normative text. The scalp-map cases of ``views/vectors/kinds-models.v1.json``
come from ``scripts/generate_kind_vectors.py``; these tests replay them with
the Python reference, hold the words of the specification to the reference,
and show that each rule is one the vectors catch: replacing it with a wrong
one makes a case fail. No mocks.

Needs numpy, the ``views`` extra: ``uv run --extra views pytest``.
"""

from __future__ import annotations

import base64
import json
import math
import re
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from neuroschema.views import (  # noqa: E402
    build_model,
    load_registry,
    models,
    sensor_labels,
)
from neuroschema.views import sensor_field as sf  # noqa: E402
from neuroschema.views.presets import check_preset  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "views" / "sensor-field.md"
VECTORS = ROOT / "views" / "vectors"
MODELS = json.loads((VECTORS / "kinds-models.v1.json").read_text(encoding="utf-8"))
CHECKS = json.loads((VECTORS / "preset-checks.v1.json").read_text(encoding="utf-8"))
FIELD = json.loads((VECTORS / "sensor-field.v1.json").read_text(encoding="utf-8"))
REGISTRY = load_registry()
KIND = "nemar.sensor-field"


def _is_field(case: dict) -> bool:
    model = case["model"]
    return KIND in (model["drawing"]["kind"], (model["refused"] or {}).get("kind"))


FIELD_CASES = [c for c in MODELS["cases"] if _is_field(c)]
DRAWN = [c for c in FIELD_CASES if c["model"]["model"]["type"] == "sensor-field"]
BY_NAME = {c["name"]: c for c in MODELS["cases"]}


def decode(files: dict) -> dict[str, bytes]:
    return {
        location: (
            body["text"].encode("utf-8")
            if "text" in body
            else base64.b64decode(body["base64"])
        )
        for location, body in files.items()
    }


def registry_for(case: dict) -> dict:
    return REGISTRY | {"caps": REGISTRY["caps"] | case.get("caps", {})}


def same(a, b) -> bool:
    """Equal JSON values, telling -0 from 0 as JavaScript's Object.is does."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def model_of(case: dict) -> dict:
    return build_model(case["view"], decode(case["files"]), registry_for(case))


def failing() -> list[str]:
    """The scalp-map cases the reference misses, as it stands."""
    return [c["name"] for c in FIELD_CASES if not same(model_of(c), c["model"])]


# ── Replay ────────────────────────────────────────────────────────────────


def test_the_reference_matches_every_case():
    assert failing() == []


def test_every_source_and_drawing_is_covered():
    placed = {
        (c["model"]["drawing"]["via"], c["model"]["model"]["placement"]["source"])
        for c in DRAWN
    }
    assert placed >= {
        ("kind", "layout"),
        ("kind", "positions"),
        ("kind", "names"),
        ("base", "layout"),
    }
    unused = {c["model"]["model"]["placement"]["unused_positions"] for c in DRAWN}
    assert unused >= {"frame_unknown", "positions_flat"}


# ── The words ─────────────────────────────────────────────────────────────


def _doc_words() -> set[str]:
    section = SPEC.read_text().split("\n## Refusals\n", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z_]+)` \|", section, re.M))


def _reference_words() -> set[str]:
    source = (ROOT / "src" / "neuroschema" / "views" / "sensor_field.py").read_text()
    words = set(re.findall(r'SensorFieldRefusal\(\s*"([a-z_]+)"', source))
    source = (ROOT / "src" / "neuroschema" / "views" / "models.py").read_text()
    words |= set(re.findall(r'placement\["word"\] = "([a-z_]+)"', source))
    source = (ROOT / "src" / "neuroschema" / "views" / "sensor_layout.py").read_text()
    words |= set(re.findall(r'SensorLayoutRefusal\(\s*"([a-z_]+)"', source))
    return words


def test_words_table_matches_the_reference():
    """The Refusals tables list every word that can take or explain a map's
    place: the algorithm's, the placement's and the projection's."""
    assert _doc_words() == _reference_words()


def test_every_word_has_a_vector():
    seen = set()
    for case in DRAWN:
        model = case["model"]["model"]
        seen.add(model["placement"]["unused_positions"])
        seen |= {item["word"] for item in model["maps"]["items"]}
    seen |= {c["refused"] for c in FIELD["cases"] if "refused" in c}
    words = _doc_words()
    assert words <= seen
    assert seen - words - {None} <= set(sensor_labels.REASONS)
    assert seen & set(sensor_labels.REASONS), "a sensor-labels word in a map's place"


FILE_WORDS = {
    "tsv_ragged",
    "tsv_line_endings",
    "column_repeated",
    "column_missing",
    "coords_unresolved",
    "coords_mismatch",
    "coords_length",
    "value_type",
    "value_units_differ",
    "empty",
    "cell_not_number",
    "cell_not_finite",
    "cell_not_integer",
    "cap_exceeded",
}


def test_every_file_word_has_a_scalp_map_vector():
    """Each fault of the files falls a scalp map back to its tables."""
    refused = {
        c["model"]["refused"]["word"] for c in FIELD_CASES if c["model"]["refused"]
    }
    assert refused == FILE_WORDS
    for case in FIELD_CASES:
        if case["model"]["refused"]:
            assert case["model"]["model"]["type"] == "fallback"
    nothing = {
        r["word"]
        for r in MODELS["refusals"]
        if r["view"]["kind"] in (KIND, "nemar.ic-maps")
    }
    assert nothing >= {"file_missing", "file_digest_mismatch"}


ORDER = {
    "order_sensor_coordinate_before_values": "coords_mismatch",
    "order_sensor_values_cells_before_layout": "cell_not_number",
    "order_sensor_layout_grammar_before_columns": "tsv_ragged",
    "order_sensor_layout_repeated_before_missing": "column_repeated",
    "order_sensor_layout_missing_before_length": "column_missing",
    "order_sensor_layout_length_before_cap": "coords_length",
    "order_sensor_layout_cap_before_cells": "cap_exceeded",
    "order_sensor_layout_column_by_column": "cell_not_finite",
    "order_sensor_files_before_frame": "cell_not_number",
    "order_sensor_rows_before_columns": "tsv_ragged",
}
MAP_ORDER = {
    "order_sensor_frame_before_types": "frame_not_scalp",
    "order_sensor_types_before_projection": "no_eeg_sensors",
    "order_sensor_frame_before_maps": "frame_not_scalp",
    "order_sensor_map_too_few_before_overflow": "too_few_sensors",
    "order_sensor_map_grid_before_overflow": "head_outside_grid",
    "sensor_field_positions_flat_names_refused": "labels_unrecognized",
}


def test_neighboring_checks_have_two_fault_vectors():
    """Each case holds two faults of different words; the earlier check's word
    is the one recorded."""
    for name, word in ORDER.items():
        assert BY_NAME[name]["model"]["refused"]["word"] == word, name
    for name, word in MAP_ORDER.items():
        items = BY_NAME[name]["model"]["model"]["maps"]["items"]
        assert {item["word"] for item in items} == {word}, name
    refused = BY_NAME["sensor_field_positions_flat_names_refused"]["model"]["model"]
    assert refused["placement"]["unused_positions"] == "positions_flat"


# ── Sensor types and frames ───────────────────────────────────────────────


TYPES = ["EEG", "eeg", "Eeg", " EEG\t", "SEEG", "ECOG", "DBS", "EOG", "ECG", "EMG"]
TYPES += ["n/a", "N/A", "", "  ", "MEGMAG", "eeg2", "\u00a0EEG", "\uff25EG", None]


@pytest.mark.parametrize("text", TYPES)
def test_a_type_is_read_as_sensor_labels_reads_it(text):
    assert models.sensor_type_class(text) == sensor_labels._type_class(text)


@pytest.mark.parametrize(
    ("types", "drawn"),
    [
        (None, [True, True, True]),
        (["n/a", "", "N/A"], [True, True, True]),
        (["EEG", "n/a", "EOG"], [True, False, False]),
        (["SEEG", "ECOG", "DBS"], [False, False, False]),
        (["eeg", "EEG", "SEEG"], [True, True, False]),
    ],
)
def test_a_map_draws_eeg_rows_or_every_untyped_row(types, drawn):
    assert models.drawn_rows(types, 3) == drawn


def test_no_scalp_map_in_an_intracranial_frame():
    """Pixels, ACPC and ScanRAS are BIDS's iEEG-only coordinate systems. Without
    the rule, ACPC and ScanRAS would be projected as RAS and Pixels would fall
    back to names, so an implant would be drawn on a scalp."""
    from neuroschema.views import sensor_layout as sl

    assert {"Pixels", "ACPC", "ScanRAS"} == models.NOT_SCALP_FRAMES
    assert {"ACPC", "ScanRAS"} <= sl.RAS_FRAMES
    assert "Pixels" not in sl.RAS_FRAMES | sl.ALS_FRAMES
    implants = [c for c in DRAWN if c["name"].startswith("sensor_field_implant_")]
    assert len(implants) == 4
    for case in implants:
        placement = case["model"]["model"]["placement"]
        assert placement["word"] in {"frame_not_scalp", "no_eeg_sensors"}
        assert not any(case["model"]["model"]["sensors"]["drawn"])


# ── The model holds stored numbers ────────────────────────────────────────


def _cells(case: dict, role: str) -> dict[str, list[str]]:
    entry = next(e for e in case["view"]["data"] if e["role"] == role)
    lines = decode(case["files"])[entry["location"]].decode().split("\n")[:-1]
    header = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[1:]]
    return {name: [row[i] for row in rows] for i, name in enumerate(header)}


def _number(text: str):
    return None if text == "n/a" else float(text) + 0.0


@pytest.mark.parametrize("case", DRAWN, ids=[c["name"] for c in DRAWN])
def test_every_place_is_a_stored_number(case):
    """A layout's or positions' places are their cells; a name's place is its
    montage's position, as views/montages stores it."""
    model = case["model"]["model"]
    sensors, placement = model["sensors"], model["placement"]
    if placement["word"] is not None:
        return
    if placement["source"] == "names":
        montage = json.loads(
            (ROOT / "views" / "montages" / f"{placement['montage']}.json").read_text()
        )
        stored = {e[0]: e[1:4] for e in montage["electrodes"]}
        for k, electrode in enumerate(sensors["electrodes"]):
            point = [sensors[a][k] for a in "xyz"]
            assert point == (stored[electrode] if electrode else [None] * 3)
        return
    cells = _cells(case, placement["role"])
    for column in models.PLACE_COLUMNS[placement["role"]]:
        assert sensors[column] == [_number(t) for t in cells[column]], column
    for item in model["maps"]["items"]:
        assert item["values"] == [float(t) + 0.0 for t in item["text"]]


# ── The vectors catch a wrong rule ────────────────────────────────────────


def _all_untyped(types, count):
    return [True] * count


def _exact_eeg(text):
    if text is None or text in ("", "n/a"):
        return "untyped"
    return "eeg" if text == "EEG" else "other"


def _strict_place(text):
    return models.cell_value(text, "number")


def _never_refused(theta, radius, values):
    return None


def _values_number_only(columns):
    for column in columns:
        if column["type"] != "number":
            raise models.KindRefused("value_type", column["name"])
    units = {column.get("unit") for column in columns}
    if len(units) > 1:
        raise models.KindRefused("value_units_differ")
    return next(iter(units), None)


MUTATIONS = {
    "no frame refused": ("NOT_SCALP_FRAMES", frozenset()),
    "untyped rows beside typed ones": ("drawn_rows", _all_untyped),
    "types compared exactly": ("sensor_type_class", _exact_eeg),
    "n/a not a place": ("_place_cell", _strict_place),
    "maps never refused": ("_map_word", _never_refused),
    "integer columns not maps": ("_value_columns", _values_number_only),
}


@pytest.mark.parametrize("mutation", list(MUTATIONS))
def test_the_vectors_catch_a_wrong_rule(monkeypatch, mutation):
    name, value = MUTATIONS[mutation]
    monkeypatch.setattr(models, name, value)
    assert failing(), mutation


def test_the_vectors_catch_a_projection_never_used(monkeypatch):
    from neuroschema.views.sensor_layout import SensorLayoutRefusal

    projected = models._projected

    def refuse(xyz, coordinate_system, montage, rows, count):
        """Measured positions are never projected; templates still are."""
        if montage is None:
            raise SensorLayoutRefusal("positions_flat", "always")
        return projected(xyz, coordinate_system, montage, rows, count)

    monkeypatch.setattr(models, "_projected", refuse)
    assert failing()


def test_the_vectors_catch_names_never_placed(monkeypatch):
    refused = sensor_labels.infer_positions([("X", None)] * 8)
    assert refused.outcome == "refused"
    monkeypatch.setattr(sensor_labels, "infer_positions", lambda *_a, **_k: refused)
    assert failing()


def test_the_vectors_catch_the_wrong_minimum(monkeypatch):
    monkeypatch.setattr(sf, "MIN_SENSORS", 7)
    assert failing()


def test_a_preset_drawn_by_its_base_uses_absmax():
    """A preset drawn by its base uses the base's default limits."""
    assert BY_NAME["ic_maps_by_base"]["model"]["model"]["limits"] == "absmax"


def test_ic_maps_checks_run_on_their_base():
    """The preset-check vectors carry the files the base reads, and the base's
    refusal comes before the preset's own check."""
    for case in CHECKS["cases"]:
        if case["view"]["kind"] == "nemar.ic-maps":
            roles = {e["role"] for e in case["view"]["data"]}
            located = {e["location"] for e in case["view"]["data"]}
            assert roles == {"values", "layout", "components"}
            assert located == set(case["files"]), case["name"]
    case = next(c for c in CHECKS["cases"] if c["name"] == "ic_maps_base_refuses")
    assert case["expected"] == {"word": "coords_length", "outcome": "fallback"}
    files = {k: v["text"].encode() for k, v in case["files"].items()}
    values = next(e for e in case["view"]["data"] if e["role"] == "values")
    del files[values["location"]]
    assert check_preset(case["view"], files, REGISTRY) == {
        "word": "file_missing",
        "outcome": "nothing",
    }
