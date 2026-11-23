"""Tests for the generic kinds: table, lines, heatmap and histogram (version 1).

The model and verdict vectors are replayed against the Python reference and
jsonschema; independent checks pin the bin rule, the readout rule and the
number grammar, and show that the vectors catch a renderer that gets them
wrong. Real schemas, registry and vectors; no mocks.
"""

from __future__ import annotations

import base64
import bisect
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.views import (
    MODELS_FORMAT,
    Drawing,
    KindRefused,
    ViewRefused,
    build_model,
    cell_value,
    draw_as,
    known_kinds,
    load_registry,
    locate_bin,
    meets_role_contract,
    read_json,
    read_tsv,
    role_schemas,
    snap_row,
)
from neuroschema.views.models import (
    histogram_content_validator,
    number_text,
    view_validator,
)

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "views" / "vectors"
MODELS = json.loads((VECTORS / "kinds-models.v1.json").read_text(encoding="utf-8"))
VERDICTS = json.loads((VECTORS / "kinds-verdicts.v1.json").read_text(encoding="utf-8"))
SPEC = ROOT / "docs" / "views" / "generic-kinds.md"
REGISTRY = load_registry()
GENERIC = ["nemar.table", "nemar.lines", "nemar.heatmap", "nemar.histogram"]

CASES = MODELS["cases"]
REFUSALS = MODELS["refusals"]


def by_name(name: str) -> dict:
    return copy.deepcopy(next(c for c in CASES if c["name"] == name))


def decode(files: dict) -> dict[str, bytes]:
    return {
        location: (
            body["text"].encode("utf-8")
            if "text" in body
            else base64.b64decode(body["base64"])
        )
        for location, body in files.items()
    }


def _load_generator():
    path = ROOT / "scripts" / "generate_kind_vectors.py"
    spec = importlib.util.spec_from_file_location("generate_kind_vectors", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_for(case: dict) -> dict:
    """The registry with the case's caps in place of the registered ones."""
    return REGISTRY | {"caps": REGISTRY["caps"] | case.get("caps", {})}


# ── The model vectors ─────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_model_vectors_replay(case):
    model = build_model(case["view"], decode(case["files"]), registry_for(case))
    assert model == case["model"]


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r["name"] for r in REFUSALS])
def test_refusal_vectors_replay(refusal):
    with pytest.raises(ViewRefused) as raised:
        build_model(refusal["view"], decode(refusal["files"]), registry_for(refusal))
    assert raised.value.word == refusal["word"]
    assert raised.value.downloads == refusal["downloads"]


def _all_downloads(view: dict) -> list[str]:
    locations = [e["location"] for e in view.get("data", [])]
    return locations + [
        i["file"]["location"] for i in view.get("inputs", []) if "file" in i
    ]


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r["name"] for r in REFUSALS])
def test_a_refused_view_still_offers_its_other_files(refusal):
    """No view hides data: a refusal offers every file but the one that failed.

    An invalid declaration offers none.
    """
    offered = [d["location"] for d in refusal["downloads"]]
    every = _all_downloads(refusal["view"])
    if refusal["word"] == "declaration_invalid":
        assert offered == []
    else:
        failed = set(every) - set(offered)
        assert len(failed) == 1
        assert offered == [location for location in every if location not in failed]


def test_a_refused_view_offers_files_it_has_not_read():
    """The npy file of an unknown kind is never read, and is still offered."""
    refusal = next(r for r in REFUSALS if r["name"].startswith("refusal_fallback"))
    assert any(d["location"].endswith(".npy") for d in refusal["downloads"])


SNAP_CASES = [c for c in CASES if "snaps" in c]
LOCATE_CASES = [c for c in CASES if "locates" in c]


@pytest.mark.parametrize("case", SNAP_CASES, ids=[c["name"] for c in SNAP_CASES])
def test_snap_vectors_replay(case):
    xs = case["model"]["model"]["x"]["values"]
    assert [snap_row(xs, q["x"]) for q in case["snaps"]] == [
        q["row"] for q in case["snaps"]
    ]


def _edges(model: dict) -> list[float]:
    items = model["items"]
    return [items[0]["lower"], *(item["upper"] for item in items)]


@pytest.mark.parametrize("case", LOCATE_CASES, ids=[c["name"] for c in LOCATE_CASES])
def test_locate_vectors_replay(case):
    edges = _edges(case["model"]["model"])
    assert [locate_bin(edges, q["value"]) for q in case["locates"]] == [
        q["bin"] for q in case["locates"]
    ]


def test_model_vectors_header():
    assert MODELS["format"] == MODELS_FORMAT == "nemar.kinds-models.v1"
    assert (ROOT / MODELS["spec"]).resolve() == SPEC
    names = [c["name"] for c in [*CASES, *REFUSALS]]
    assert len(names) == len(set(names))


def test_files_hold_the_declared_digests():
    """Every file of a drawn case is the declared bytes; the refusals hold the rest."""
    for case in CASES:
        files = decode(case["files"])
        for entry in case["view"].get("data", []):
            data = files.get(entry["location"])
            if data is not None:
                assert len(data) == entry["size"], case["name"]
                assert hashlib.sha256(data).hexdigest() == entry["sha256"], case["name"]


def test_vectors_are_current():
    """The committed vectors are what the generator writes (its --check)."""
    generator = _load_generator()
    for path, text in generator.render().items():
        assert path.read_text(encoding="utf-8") == text, path.name
    assert generator.main(["--check"]) == 0


def test_check_reports_a_stale_file(tmp_path, monkeypatch, capsys):
    generator = _load_generator()
    stale = tmp_path / "kinds-models.v1.json"
    stale.write_text("{}\n")
    monkeypatch.setattr(generator, "MODELS_PATH", stale)
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    assert generator.main(["--check"]) == 1
    assert "kinds-models.v1.json" in capsys.readouterr().err


def test_every_drawing_and_model_type_is_covered():
    seen = {(c["model"]["drawing"]["via"], c["model"]["model"]["type"]) for c in CASES}
    assert seen >= {
        ("kind", "table"),
        ("kind", "lines"),
        ("kind", "heatmap"),
        ("kind", "histogram"),
        ("base", "lines"),
        ("base", "heatmap"),
        ("base", "histogram"),
        ("table", "fallback"),
    }


# ── The words ─────────────────────────────────────────────────────────────


def _doc_words() -> dict[str, str]:
    rows = re.findall(
        r"^\| `([a-z0-9_]+)` \| (nothing drawn|fallback) \|",
        SPEC.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return dict(rows)


def _raised_words() -> dict[str, str]:
    source = (ROOT / "src" / "neuroschema" / "views" / "models.py").read_text()
    found = re.findall(r'(ViewRefused|KindRefused)\("([a-z0-9_]+)"', source)
    outcome = {"ViewRefused": "nothing drawn", "KindRefused": "fallback"}
    return {word: outcome[cls] for cls, word in found}


def test_words_table_matches_the_reference():
    """The Words table lists exactly the words the reference raises, with outcomes."""
    assert _doc_words() == _raised_words()


def test_every_word_has_a_vector():
    words = {c["model"]["refused"]["word"] for c in CASES if c["model"]["refused"]}
    words |= {r["word"] for r in REFUSALS}
    assert words == set(_doc_words())


# ── The verdict corpus ────────────────────────────────────────────────────


VERDICT_CASES = VERDICTS["cases"]
VALIDATORS = {
    "view": view_validator(),
    "content.nemar.histogram.v1.schema.json": histogram_content_validator(),
}


@pytest.mark.parametrize("case", VERDICT_CASES, ids=[c["name"] for c in VERDICT_CASES])
def test_verdicts_replay(case):
    validator = VALIDATORS[case["schema"]]
    errors = sorted(
        {
            (e.validator, "/".join(str(p) for p in e.absolute_path))
            for e in validator.iter_errors(case["instance"])
        }
    )
    assert [list(e) for e in errors] == case["errors"]
    assert case["valid"] is (not errors)


def test_verdict_corpus_header():
    assert VERDICTS["format"] == "nemar.kinds-verdicts.v1"
    assert (ROOT / VERDICTS["spec"]).resolve() == SPEC
    names = [c["name"] for c in VERDICT_CASES]
    assert len(names) == len(set(names))


def test_verdict_corpus_covers_each_kind_both_ways():
    """Each generic kind and the content schema has valid and invalid cases."""
    groups: dict[str, set[bool]] = {}
    for case in VERDICT_CASES:
        instance = case["instance"]
        if case["schema"] == "view":
            group = instance.get("kind") if instance.get("kind") in GENERIC else "env"
        else:
            group = case["schema"]
        groups.setdefault(group, set()).add(case["valid"])
    for group in [*GENERIC, "env", "content.nemar.histogram.v1.schema.json"]:
        assert groups.get(group) == {True, False}, group


def test_drawn_vector_views_are_valid_declarations():
    """A model is built only from a declaration the schema accepts."""
    for case in CASES:
        assert view_validator().is_valid(case["view"]), case["name"]


# ── The bin rule: [e_i, e_i+1), the last bin closed ──────────────────────


EDGES = [0.0, 10.0, 20.0, 30.0]


@pytest.mark.parametrize(
    ("value", "bin_"),
    [
        (-0.001, -1),
        (0.0, 0),
        (9.999, 0),
        (10.0, 1),
        (29.999, 2),
        (30.0, 2),
        (30.001, 3),
    ],
)
def test_bin_rule(value, bin_):
    assert locate_bin(EDGES, value) == bin_


def _last_bin_open(edges, value):
    if value < edges[0]:
        return -1
    return min(bisect.bisect_right(edges, value) - 1, len(edges) - 1)


def _left_open(edges, value):
    if value <= edges[0]:
        return -1
    if value > edges[-1]:
        return len(edges) - 1
    return bisect.bisect_left(edges, value) - 1


def _underflow_inclusive(edges, value):
    return -1 if value <= edges[0] else locate_bin(edges, value)


@pytest.mark.parametrize(
    "wrong",
    [_last_bin_open, _left_open, _underflow_inclusive],
    ids=lambda f: f.__name__,
)
def test_vectors_catch_a_wrong_bin_rule(wrong):
    """Each plausible mistake puts at least one located value in another bin."""
    misses = [
        (case["name"], q["value"])
        for case in LOCATE_CASES
        for q in case["locates"]
        if wrong(_edges(case["model"]["model"]), q["value"]) != q["bin"]
    ]
    assert misses


def test_vectors_catch_a_wrong_last_bin_label():
    """A half-open last bin would also print [90, 100) for [90, 100]."""
    labels = [
        item["label"]
        for case in CASES
        if case["model"]["model"]["type"] == "histogram"
        for item in case["model"]["model"]["items"]
        if item.get("upper_closed")
    ]
    assert labels and all(label.endswith("]") for label in labels)


# ── The readout rule: a stored row, never an interpolated value ──────────


XS = [0.0, 0.5, 1.0, 2.0]


@pytest.mark.parametrize(
    ("x", "row"),
    [(-5, 0), (0, 0), (0.25, 0), (0.2500001, 1), (0.75, 1), (1.5, 2), (1.6, 3), (9, 3)],
)
def test_snap_rule(x, row):
    assert snap_row(XS, x) == row


def _tie_upper(xs, x):
    i = bisect.bisect_right(xs, x) - 1
    if i < 0:
        return 0
    if i >= len(xs) - 1:
        return len(xs) - 1
    return i + 1 if xs[i + 1] - x <= x - xs[i] else i


def _floor(xs, x):
    return max(bisect.bisect_right(xs, x) - 1, 0)


def _ceil(xs, x):
    return min(bisect.bisect_left(xs, x), len(xs) - 1)


@pytest.mark.parametrize(
    "wrong", [_tie_upper, _floor, _ceil], ids=lambda f: f.__name__.strip("_")
)
def test_vectors_catch_a_wrong_snap_rule(wrong):
    misses = [
        q["x"]
        for case in SNAP_CASES
        for q in case["snaps"]
        if wrong(case["model"]["model"]["x"]["values"], q["x"]) != q["row"]
    ]
    assert misses


def _interpolated(xs, values, x):
    """What a renderer that reads between rows would print."""
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    t = min(max((x - xs[i]) / (xs[i + 1] - xs[i]), 0.0), 1.0)
    return number_text(values[i] + t * (values[i + 1] - values[i]))


def test_vectors_catch_an_interpolated_readout():
    """Reading between rows prints a text that is no stored cell's text."""
    misses = []
    for case in SNAP_CASES:
        model = case["model"]["model"]
        xs = model["x"]["values"]
        for query in case["snaps"]:
            for series in model["series"]["items"]:
                stored = series["text"][query["row"]]
                if _interpolated(xs, series["values"], query["x"]) != stored:
                    misses.append((case["name"], query["x"], series["label"]))
    assert misses


def test_readout_prints_the_stored_text():
    """The text 1.25e1 is printed as written, not as 12.5."""
    model = by_name("lines_spectrum")["model"]["model"]
    cz = next(s for s in model["series"]["items"] if s["label"] == "Cz")
    assert cz["text"][0] == "1.25e1" and cz["values"][0] == 12.5


# ── Cells, TSV and JSON ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("0", "number", 0.0),
        ("-0", "number", 0.0),
        ("1.5e-3", "number", 0.0015),
        ("2E2", "number", 200.0),
        ("-12", "integer", -12.0),
        ("9007199254740991", "integer", 9007199254740991.0),
        ("n/a", "string", "n/a"),
    ],
)
def test_cell_values(text, kind, value):
    result = cell_value(text, kind)
    assert result == value
    if kind != "string":
        assert str(result) != "-0.0"


@pytest.mark.parametrize(
    ("text", "kind", "word"),
    [
        ("12345678901234567", "integer", "cell_not_integer"),
        ("-9007199254740992", "integer", "cell_not_integer"),
        ("1.0", "integer", "cell_not_integer"),
        ("-", "number", "cell_not_number"),
        ("1e400", "number", "cell_not_finite"),
        ("-1e400", "number", "cell_not_finite"),
    ],
)
def test_cell_refusals(text, kind, word):
    with pytest.raises(KindRefused) as raised:
        cell_value(text, kind)
    assert raised.value.word == word


def test_vectors_catch_a_lenient_number_parser():
    """float() accepts texts the JSON grammar refuses; the vectors list them."""
    accepted = []
    for case in CASES:
        if not case["name"].startswith("table_not_a_number_"):
            continue
        text = decode(case["files"])[case["view"]["data"][0]["location"]]
        cell = text.decode().split("\n")[1]
        try:
            float(cell)
        except ValueError:
            continue
        accepted.append(cell)
    assert {" 1", "+1", "01", "1.", ".5", "1_0", "NaN", "Infinity"} <= set(accepted)


def test_read_tsv():
    tsv = read_tsv(b"a\tb\n1\t2\n\t\n")
    assert tsv.header == ("a", "b")
    assert tsv.rows == (("1", "2"), ("", ""))
    assert tsv.cells("b") == ["2", ""]


def test_header_only_and_empty_line():
    assert read_tsv(b"a\n").rows == ()
    assert read_tsv(b"a\n\n").rows == (("",),)


@pytest.mark.parametrize(
    ("data", "word"),
    [
        (b"", "tsv_line_endings"),
        (b"a\r\n", "tsv_line_endings"),
        (b"a\tb\n1\n", "tsv_ragged"),
        (b"\xef\xbb\xbfa\n", "tsv_encoding"),
    ],
)
def test_read_tsv_refusals(data, word):
    with pytest.raises(KindRefused) as raised:
        read_tsv(data)
    assert raised.value.word == word


def test_read_json():
    assert read_json(b'{"a": [1, 2.5, true, null]}') == {"a": [1, 2.5, True, None]}
    with pytest.raises(KindRefused, match="not finite"):
        read_json(b'{"a": {"b": 1e400}}')


@pytest.mark.parametrize(
    "number",
    ["1" + "0" * 400, "-1" + "0" * 400, "1" + "0" * 5000],
    ids=["401-digits", "negative", "5001-digits"],
)
def test_an_integer_beyond_binary64_is_not_finite(number):
    """Python reads these exactly; JSON.parse reads Infinity, so both refuse."""
    with pytest.raises(KindRefused) as raised:
        read_json(b'{"n": ' + number.encode() + b"}")
    assert raised.value.word == "json_invalid"


def test_the_largest_binary64_integer_is_finite():
    largest = int(1.7976931348623157e308)
    assert read_json(b'{"n": ' + str(largest).encode() + b"}") == {"n": largest}


def test_number_text_is_ecmascript():
    assert [number_text(x) for x in (100.0, 0.1, 1e-7, 1e21, -0.0, 5e-324)] == [
        "100",
        "0.1",
        "1e-7",
        "1e+21",
        "0",
        "5e-324",
    ]


# ── Heatmap limits ────────────────────────────────────────────────────────


def test_minmax_and_absmax_limits():
    classes = by_name("heatmap_classes")["model"]["model"]
    assert classes["limits"] == {"rule": "minmax", "min": 2.0, "max": 91.5}
    corr = by_name("heatmap_absmax")["model"]["model"]
    assert corr["limits"] == {"rule": "absmax", "min": -1.0, "max": 1.0}


def test_preset_by_base_ignores_its_parameters():
    case = by_name("heatmap_preset_by_base")
    assert case["view"]["parameters"] == {"limits": "absmax"}
    assert case["model"]["model"]["limits"]["rule"] == "minmax"


def test_heatmap_orientation():
    """values[i][j] is data row i, value column j."""
    model = by_name("heatmap_classes")["model"]["model"]
    assert model["rows"]["labels"][1] == "IC2"
    assert model["columns"]["labels"][1] == "eye"
    assert model["text"][1][1] == "88"


# ── build_model beyond the vectors ────────────────────────────────────────


def test_caps_cases_override_only_their_own_caps():
    """Every cap the vectors override is a registry cap."""
    overridden = {k for c in [*CASES, *REFUSALS] for k in c.get("caps", {})}
    assert overridden == set(REGISTRY["caps"])


def test_a_kind_without_a_reference_model_is_named(tmp_path):
    schema = tmp_path / "kind.acme.map.v1.schema.json"
    schema.write_text(json.dumps({"type": "object"}))
    entry = {
        "kind": "acme.map",
        "kind_version": 1,
        "base": None,
        "base_version": None,
        "schema": str(schema),
        "roles": {},
    }
    registry = REGISTRY | {"kinds": [*REGISTRY["kinds"], entry]}
    view = by_name("fallback_unknown_kind")
    view["view"].update(kind="acme.map", kind_version=1)
    with pytest.raises(LookupError, match=r"no reference model for acme\.map"):
        build_model(view["view"], decode(view["files"]), registry)


def test_every_file_is_offered_for_download():
    """No view hides data: downloads list every data file and file input."""
    for case in CASES:
        view = case["view"]
        expected = [e["location"] for e in view.get("data", [])]
        expected += [
            i["file"]["location"] for i in view.get("inputs", []) if "file" in i
        ]
        assert [d["location"] for d in case["model"]["downloads"]] == expected


# ── Schemas and the registry ──────────────────────────────────────────────


SCHEMAS = ROOT / "schema" / "views"
CONTENT = SCHEMAS / "content.nemar.histogram.v1.schema.json"


def test_generic_kinds_are_registered_without_a_base():
    kinds = known_kinds(REGISTRY)
    for kind in GENERIC:
        entry = kinds[(kind, 1)]
        assert entry["base"] is None and entry["base_version"] is None


def test_lines_and_heatmap_leave_dim_names_open():
    kinds = known_kinds(REGISTRY)
    for kind in ("nemar.lines", "nemar.heatmap"):
        assert kinds[(kind, 1)]["roles"] == {
            "values": {"formats": ["tsv"], "dims": None}
        }


def test_json_roles_name_their_content_schema():
    """A JSON role names a content schema, and each content schema has one role."""
    named = []
    for entry in REGISTRY["kinds"]:
        for spec in entry["roles"].values():
            if "json" in spec["formats"]:
                assert (ROOT / spec["content"]).is_file()
                named.append(Path(spec["content"]).name)
            else:
                assert "content" not in spec
    files = sorted(p.name for p in SCHEMAS.glob("content.*.schema.json"))
    assert sorted(named) == files


def test_histogram_kind_references_its_content_schema():
    """The $defs reference lets a bundler that follows $refs reach the content."""
    kind = json.loads((SCHEMAS / "kind.nemar.histogram.v1.schema.json").read_text())
    entry = known_kinds(REGISTRY)[("nemar.histogram", 1)]
    target = (SCHEMAS / kind["$defs"]["content"]["$ref"]).resolve()
    assert target == (ROOT / entry["roles"]["histogram"]["content"]).resolve()


def test_content_caps_match_the_registry():
    content = json.loads(CONTENT.read_text())["properties"]
    per_dim = REGISTRY["caps"]["entries_per_dim"]
    assert content["counts"]["maxItems"] == per_dim
    assert content["categories"]["maxItems"] == per_dim
    assert content["edges"]["maxItems"] == per_dim + 1


def test_vectors_are_registered():
    """Both vector files are registered algorithms with this page as their spec."""
    algorithms = {a["name"]: a for a in REGISTRY["algorithms"]}
    for document, path in [
        (MODELS, "views/vectors/kinds-models.v1.json"),
        (VERDICTS, "views/vectors/kinds-verdicts.v1.json"),
    ]:
        entry = algorithms[document["format"]]
        assert entry == {
            "name": document["format"],
            "spec": document["spec"],
            "vectors": path,
        }


@pytest.mark.parametrize(
    ("case", "kind"),
    [
        ("lines_preset_by_base", "nemar.lines"),
        ("heatmap_preset_by_base", "nemar.heatmap"),
        ("heatmap_preset_columns_from_role", "nemar.heatmap"),
    ],
)
def test_base_data_admits_a_preset_coordinate_role(case, kind):
    """A preset's values entry, with a coordinate from another of its roles, is
    valid under the base's whole data subschema as well as its role subschema;
    only a view of the kind itself refuses such a coordinate (a root rule)."""
    view = by_name(case)["view"]
    values = [e for e in view["data"] if e["role"] == "values"]
    schema = json.loads((SCHEMAS / f"kind.{kind}.v1.schema.json").read_text())
    data = Draft202012Validator(schema["properties"]["data"])
    assert data.is_valid(values)
    assert not Draft202012Validator(schema).is_valid({"data": values})


def test_role_contract_refuses_x_from_another_role():
    """Only the series may come from a preset's role; the x axis is its own column."""
    view = by_name("lines_preset_by_base")["view"]
    view["data"][0]["dims"][0]["coords"] = {"role": "layout", "column": "radius"}
    entry = known_kinds(REGISTRY)[("nemar.lines", 1)]
    assert not meets_role_contract(view, entry)
    assert draw_as(view) == Drawing("table", None, None)


def test_role_contract_admits_coordinates_from_a_preset_role():
    """The values subschema allows {role, column}; a lines view itself does not."""
    entry = known_kinds(REGISTRY)[("nemar.lines", 1)]
    series = role_schemas(entry)["values"]["properties"]["dims"]["allOf"][1]
    assert {"required": ["role"]} in series["contains"]["properties"]["coords"]["anyOf"]
    assert by_name("lines_preset_by_base")["model"]["drawing"]["via"] == "base"
