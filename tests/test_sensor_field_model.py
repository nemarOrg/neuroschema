"""The scalp map's model (``nemar.sensor-field``) against its vectors.

``docs/views/sensor-field.md`` (The model, The order of checks) is the
normative text. The scalp-map cases of ``views/vectors/kinds-models.v1.json``,
and the spectrum's maps, come from ``scripts/generate_kind_vectors.py``; these
tests replay them with the Python reference, hold the words of the
specification to the reference, and show that each rule is one the vectors
catch: replacing it with a wrong one makes a case fail. No mocks.

Needs numpy, the ``views`` extra: ``uv run --extra views pytest``.
"""

from __future__ import annotations

import base64
import importlib.util
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
from neuroschema.views.presets import check_preset, spectrum_maps  # noqa: E402

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
SPECTRA = [c for c in MODELS["cases"] if "maps" in c]
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


def maps_of(case: dict) -> dict:
    hz = case["maps"]["hz"]
    got = spectrum_maps(case["view"], decode(case["files"]), hz, registry_for(case))
    return {"hz": hz} | (got or dict.fromkeys(("rows", "refused", "model")))


def failing() -> list[str]:
    """The scalp-map and spectrum cases the reference misses, as it stands."""
    out = [c["name"] for c in FIELD_CASES if not same(model_of(c), c["model"])]
    return out + [c["name"] for c in SPECTRA if not same(maps_of(c), c["maps"])]


# ── Replay ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", SPECTRA, ids=[c["name"] for c in SPECTRA])
def test_spectrum_maps_replay(case):
    assert same(maps_of(case), case["maps"])


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
    spectra = {
        c["maps"]["model"]["placement"]["source"] for c in SPECTRA if c["maps"]["model"]
    }
    assert spectra == {"layout", "names"}


# ── The words ─────────────────────────────────────────────────────────────


def _doc_table(header: str) -> set[str]:
    """The first cells of the Refusals section's tables whose header is this."""
    section = SPEC.read_text().split("\n## Refusals\n", 1)[1].split("\n## ", 1)[0]
    names = set()
    for table in section.split("\n\n"):
        if table.startswith(f"| {header} |"):
            names |= set(re.findall(r"^\| `([a-z_]+)` \|", table, re.M))
    return names


def _doc_words() -> set[str]:
    return _doc_table("Word")


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
    for case in SPECTRA:
        if case["maps"]["model"]:
            seen |= {i["word"] for i in case["maps"]["model"]["maps"]["items"]}
    seen |= {c["refused"] for c in FIELD["cases"] if "refused" in c}
    words = _doc_words()
    assert words <= seen
    assert seen - words - {None} <= set(sensor_labels.REASONS)
    assert seen & set(sensor_labels.REASONS), "a sensor-labels word in a map's place"


def test_notes_table_matches_the_reference_and_the_vectors():
    """flat_field and near_flat are the notes; maps of the model vectors carry
    each."""
    assert _doc_table("Note") == {sf.FLAT_FIELD, sf.NEAR_FLAT_NOTE}
    notes = {
        note
        for case in DRAWN
        for item in case["model"]["model"]["maps"]["items"]
        for note in item["notes"]
    }
    assert notes == {sf.FLAT_FIELD, sf.NEAR_FLAT_NOTE}
    items = BY_NAME["sensor_field_flat_map"]["model"]["model"]["maps"]["items"]
    assert [item["notes"] for item in items] == [
        [],
        [sf.FLAT_FIELD],
        [sf.NEAR_FLAT_NOTE],
    ]


GENERIC = ROOT / "docs" / "views" / "generic-kinds.md"
# The generic kinds' words a scalp map's files cannot give: a JSON file's and
# a line chart's x column's.
NOT_A_SCALP_MAP_WORD = {
    "json_invalid",
    "content_invalid",
    "edges_not_increasing",
    "counts_length",
    "x_not_increasing",
}


def _generic_words() -> dict[str, str]:
    rows = re.findall(
        r"^\| `([a-z0-9_]+)` \| (nothing drawn|fallback) \|",
        GENERIC.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return dict(rows)


FILE_WORDS = {
    word for word, outcome in _generic_words().items() if outcome == "fallback"
} - NOT_A_SCALP_MAP_WORD
NOTHING_DRAWN = {
    word for word, outcome in _generic_words().items() if outcome == "nothing drawn"
}


def test_every_file_word_has_a_scalp_map_vector():
    """Each fault of the files a scalp map reads, taken from the generic kinds'
    words table, falls the map back to its tables; each file that is not the
    one recorded, and an invalid declaration, draws nothing."""
    assert "sensors_mismatch" in FILE_WORDS
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
    assert nothing == NOTHING_DRAWN


def _generator():
    path = ROOT / "scripts" / "generate_kind_vectors.py"
    spec = importlib.util.spec_from_file_location("generate_kind_vectors", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORDER_PAIRS = [
    (name, first, second)
    for name, _covers, _both, _alone, first, second, *_caps in (
        _generator().sensor_field_order_pairs()
    )
]


def signature(model: dict) -> set[str]:
    """Every word a model shows: the files' word, the placement's, why the
    positions were not used, and each map's."""
    words = set()
    if model["refused"]:
        words.add(model["refused"]["word"])
    inner = model["model"]
    if inner["type"] == "sensor-field":
        words |= {inner["placement"]["word"], inner["placement"]["unused_positions"]}
        words |= {item["word"] for item in inner["maps"]["items"]}
    return words - {None}


@pytest.mark.parametrize(
    ("name", "first", "second"), ORDER_PAIRS, ids=[n for n, *_ in ORDER_PAIRS]
)
def test_each_neighboring_pair_has_two_faults_and_the_earlier_word(name, first, second):
    """The case gives the earlier check's word; its sibling, with the later
    fault alone, shows that fault is there."""
    both, alone = BY_NAME[name]["model"], BY_NAME[f"{name}_alone"]["model"]
    assert first in signature(both), name
    assert second in signature(alone), name
    assert first not in signature(alone), name


def test_the_order_pairs_cover_the_checks_a_scalp_map_adds():
    names = {name for name, *_ in ORDER_PAIRS}
    assert {
        "order_sensor_dimension_before_maps_dimension",
        "order_sensor_coordinate_cells_before_values",
        "order_sensor_layout_missing_before_mismatch",
        "order_sensor_layout_mismatch_before_length",
        "order_sensor_cells_before_names",
        "order_sensor_map_too_few_before_grid",
        "order_sensor_names_keep_their_types",
    } <= names
    refused = BY_NAME["sensor_field_positions_flat_names_refused"]["model"]["model"]
    assert refused["placement"]["unused_positions"] == "positions_flat"
    assert refused["placement"]["word"] == "labels_unrecognized"


# ── Sensor types and frames ───────────────────────────────────────────────


TYPES = ["EEG", "eeg", "Eeg", " EEG\t", "SEEG", "ECOG", "DBS", "EOG", "ECG", "EMG"]
TYPES += ["n/a", "N/A", "", "  ", "MEGMAG", "eeg2", "\u00a0EEG", "\uff25EG", None]


@pytest.mark.parametrize("text", TYPES)
def test_a_type_is_read_as_sensor_labels_reads_it(text):
    assert models.sensor_type_class(text) == sensor_labels.type_class(text)


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


def _all_untyped(types, count, measured=False):
    return [True] * count


def _exact_eeg(text):
    if text is None or text in ("", "n/a"):
        return "untyped"
    return "eeg" if text == "EEG" else "other"


def _strict_place(text):
    return models.cell_value(text, "number")


def _never_refused(theta, radius, values):
    return None, []


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
    "maps never refused": ("_map_outcome", _never_refused),
    "integer columns not maps": ("_value_columns", _values_number_only),
}


@pytest.mark.parametrize("mutation", list(MUTATIONS))
def test_the_vectors_catch_a_wrong_rule(monkeypatch, mutation):
    name, value = MUTATIONS[mutation]
    monkeypatch.setattr(models, name, value)
    assert failing(), mutation


def _variant(func, old, new):
    """``func`` with one piece of its source replaced: a wrong rule to plant."""
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(func))
    assert old in source, old
    namespace = dict(func.__globals__)
    exec(source.replace(old, new), namespace)
    return namespace[func.__name__]


RULES = {
    "the sensor role's coordinate type not checked": (
        models,
        "_sensor_role",
        "    _match(dim, column)\n",
        "",
    ),
    "the sensor role's cap counts the place columns only": (
        models,
        "_sensor_role",
        "len(tsv.rows) * len(declared) >",
        "len(tsv.rows) * len(PLACE_COLUMNS[role]) >",
    ),
    "the sensors' names never compared": (
        models,
        "_sensor_role",
        "if names is not None and tsv.cells(name) != list(names):",
        "if False:",
    ),
    "measured rows drawn untyped": (
        models,
        "sensor_field_model",
        "drawn = drawn_rows(sensors.types, count, measured)",
        "drawn = drawn_rows(sensors.types, count)",
    ),
    "names tried after any refused projection": (
        models,
        "sensor_field_model",
        '            if not named_eeg:\n                placement["word"] = exc.word\n',
        "",
    ),
    "the projection's refusal never recorded": (
        models,
        "sensor_field_model",
        'placement["unused_positions"] = exc.word',
        "pass",
    ),
    "the maps' dimension checked before the sensors'": (
        models,
        "_sensor_field",
        "label_column = _label_column(dims, declared)",
        "label_column = _label_column(dims[::-1], declared)",
    ),
    "the value cells read before the coordinate column": (
        models,
        "_sensor_field",
        "    label_texts = None\n    if label_column is not None:\n"
        "        _values, label_texts = _parse_column(tsv, label_column)\n"
        "    columns = [_parse_column(tsv, column) for column in value_columns]\n",
        "    columns = [_parse_column(tsv, column) for column in value_columns]\n"
        "    label_texts = None\n    if label_column is not None:\n"
        "        _values, label_texts = _parse_column(tsv, label_column)\n",
    ),
}


@pytest.mark.parametrize("rule", list(RULES))
def test_the_vectors_catch_a_wrong_ordering_or_check(monkeypatch, rule):
    module, name, old, new = RULES[rule]
    original = getattr(module, name)
    planted = _variant(original, old, new)
    monkeypatch.setattr(module, name, planted)
    for pair, builder in list(models.BUILDERS.items()):
        if builder is original:  # build_model finds a kind's builder here
            monkeypatch.setitem(models.BUILDERS, pair, planted)
    assert failing(), rule


def test_the_vectors_catch_names_placed_without_their_types(monkeypatch):
    infer = sensor_labels.infer_positions

    def untyped(channels, *args, **kwargs):
        return infer([(name, None) for name, _type in channels], *args, **kwargs)

    monkeypatch.setattr(sensor_labels, "infer_positions", untyped)
    assert "order_sensor_names_keep_their_types" in failing()


def test_the_vectors_catch_a_grid_checked_before_the_sensor_count(monkeypatch):
    drawn = sf.sensor_field

    def grid_first(theta, radius, values):
        try:
            return drawn(theta, radius, values)
        except sf.SensorFieldRefusal as exc:
            if exc.word != "too_few_sensors":
                raise
            monkeypatch.setattr(sf, "MIN_SENSORS", 1)
            try:
                drawn(theta, radius, values)
            except sf.SensorFieldRefusal as other:
                if other.word == "head_outside_grid":
                    raise other from exc
            finally:
                monkeypatch.setattr(sf, "MIN_SENSORS", 8)
            raise

    monkeypatch.setattr(sf, "sensor_field", grid_first)
    assert "order_sensor_map_too_few_before_grid" in failing()


def test_the_vectors_catch_a_spectrum_snapped_up_on_a_tie(monkeypatch):
    from neuroschema.views import presets

    snap = presets.snap_row

    def upper(xs, x):
        row = snap(xs, x)
        if row + 1 < len(xs) and xs[row + 1] - x == x - xs[row]:
            return row + 1
        return row

    monkeypatch.setattr(presets, "snap_row", upper)
    assert "spectrum_maps_snap" in failing()


SPECTRUM_RULES = {
    "a layout fault drops the lines too": (
        'return {"rows": rows, "refused": exc.word, "model": None}',
        "return None",
    ),
    "absmax maps": ('sensors, maps, "minmax",', 'sensors, maps, "absmax",'),
    "maps labeled by the request": (
        'lines["x"]["text"][row],',
        "str(frequencies[rows.index(row)]),",
    ),
}


@pytest.mark.parametrize("rule", list(SPECTRUM_RULES))
def test_the_vectors_catch_a_wrong_spectrum_rule(monkeypatch, rule):
    import sys

    old, new = SPECTRUM_RULES[rule]
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "spectrum_maps", _variant(spectrum_maps, old, new))
    assert failing(), rule


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


def test_a_preset_by_its_base_uses_absmax_and_the_spectrum_minmax():
    """A preset drawn by its base uses the base's default limits; the
    spectrum's own maps use minmax, since decibels are not signed about zero."""
    assert BY_NAME["ic_maps_by_base"]["model"]["model"]["limits"] == "absmax"
    spectra = {c["maps"]["model"]["limits"] for c in SPECTRA if c["maps"]["model"]}
    assert spectra == {"minmax"}


# ── Presets over the scalp map ────────────────────────────────────────────


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


def test_spectrum_maps_follow_the_readout():
    """Each map is the row its frequency snaps to, labeled by its stored text."""
    for case in SPECTRA:
        maps = case["maps"]
        if maps["model"] is None:
            continue
        lines = case["model"]["model"]
        labels = [item["label"] for item in maps["model"]["maps"]["items"]]
        assert labels == [lines["x"]["text"][row] for row in maps["rows"]]
        for item, row in zip(maps["model"]["maps"]["items"], maps["rows"], strict=True):
            assert item["values"] == [
                s["values"][row] for s in lines["series"]["items"]
            ]
    snap = BY_NAME["spectrum_maps_snap"]["maps"]
    assert snap["hz"] == [7, 7.5, 100] and snap["rows"] == [3, 4, 30]
    fault = BY_NAME["spectrum_maps_layout_fault"]
    assert fault["model"]["refused"] is None, "the lines are drawn"
    assert fault["maps"]["refused"] == "cell_not_number"
    assert BY_NAME["spectrum_maps_base_refused"]["maps"]["rows"] is None


def test_spectrum_maps_raise_when_a_file_is_not_the_one_recorded():
    """As build_model does: nothing is drawn, neither the lines nor the maps."""
    case = BY_NAME["spectrum_maps_layout"]
    files = decode(case["files"])
    layout = next(e for e in case["view"]["data"] if e["role"] == "layout")
    del files[layout["location"]]
    with pytest.raises(models.ViewRefused) as raised:
        spectrum_maps(case["view"], files, [10], REGISTRY)
    assert raised.value.word == "file_missing"


def test_measured_positions_without_types_draw_nothing_even_unchecked():
    """The schema refuses measured positions without sensor_type; a renderer
    that never ran the schema still draws no row of them (no_eeg_sensors)."""
    entry = {"position_source": "measured", "coordinate_system": "CapTrak"}
    sensors = models._Sensors(
        ["F3", "F4"], "layout", entry, {"theta_deg": [0.0, 1.0], "radius": [0.1, 0.2]}
    )
    dim = {"name": "sensor", "type": "string", "axis": "rows"}
    model = models.sensor_field_model(
        sensors, [("m", [1.0, 2.0], ["1", "2"])], "absmax", None, dim, None
    )
    assert model["placement"]["word"] == "no_eeg_sensors"
    assert model["sensors"]["drawn"] == [False, False]


def test_untyped_rows_are_drawn_only_from_templates_and_names():
    assert models.drawn_rows(None, 2, measured=True) == [False, False]
    assert models.drawn_rows(["n/a", ""], 2, measured=True) == [False, False]
    assert models.drawn_rows(["EEG", "n/a"], 2, measured=True) == [True, False]
    assert models.drawn_rows(None, 2) == [True, True]
    assert models.drawn_rows(["n/a", ""], 2) == [True, True]
    for name in ("template_unknown_montage_untyped", "strip_other_untyped"):
        placement = BY_NAME[name]["model"]["model"]["placement"]
        assert placement["source"] != "names", name
    typed = BY_NAME["template_unknown_montage_typed_eeg"]["model"]["model"]
    assert typed["placement"]["source"] == "names"


def test_template_positions_name_their_montage():
    """Every row of a template role names an electrode of its montage, compared
    as sensor-labels compares names; the check is by name, never by place."""
    for name in ("template_names_not_in_montage", "template_layout_name_unknown"):
        placement = BY_NAME[name]["model"]["model"]["placement"]
        assert placement["word"] == "template_name_unknown", name
    boundary = BY_NAME["template_strip_named_like_the_montage"]["model"]["model"]
    assert boundary["placement"]["word"] is None
    assert all(boundary["sensors"]["drawn"])


def test_a_row_with_no_place_is_not_drawn():
    """An n/a place cell, or a position the projection gives no layout."""
    for name, row in (
        ("sensor_field_layout_no_place", 4),
        ("sensor_field_positions_no_place", 11),
    ):
        drawn = BY_NAME[name]["model"]["model"]["sensors"]["drawn"]
        assert drawn[row] is False and drawn.count(False) >= 1, name
