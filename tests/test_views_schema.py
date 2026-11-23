"""Tests for the view vocabulary (neuroschema 0.6.0).

Real schema files, examples and vectors; no mocks. Failures are asserted as
(validator, path) pairs so a negative test cannot pass for the wrong reason.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema
from neuroschema.views import (
    REGISTRY_FORMAT,
    CanonicalizationError,
    Drawing,
    canonicalize,
    draw_as,
    kind_schema_path,
    known_kinds,
    load_registry,
    view_digest,
)
from tests.helpers import failures

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "views" / "vectors" / "view-digest.v1.json").read_text())


def vector(name: str) -> dict:
    """A copy of one digest vector's declaration."""
    case = next(c for c in VECTORS["cases"] if c["name"] == name)
    return copy.deepcopy(case["declaration"])


# ── nemar.view-digest.v1 ──────────────────────────────────────────────────


CASES = VECTORS["cases"]
REFUSALS = VECTORS["refusals"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_digest_vectors_replay(case):
    assert canonicalize(case["declaration"]) == case["canonical"].encode("utf-8")
    assert view_digest(case["declaration"]) == case["sha256"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vector_digest_is_the_sha256_of_its_canonical_text(case):
    digest = hashlib.sha256(case["canonical"].encode("utf-8")).hexdigest()
    assert digest == case["sha256"]


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r["name"] for r in REFUSALS])
def test_digest_refusals(refusal):
    with pytest.raises(CanonicalizationError):
        view_digest(json.loads(refusal["json"]))


def test_vector_file_header():
    assert VECTORS["format"] == "nemar.view-digest.v1"
    assert (ROOT / VECTORS["spec"]).is_file()
    names = [c["name"] for c in [*CASES, *REFUSALS]]
    assert len(names) == len(set(names))


def _jcs_like(value, *, sort, ensure_ascii=False):
    """A canonicalizer that differs from RFC 8785 in one way, for the test below."""
    if isinstance(value, dict):
        items = sort(value) if sort else list(value)
        inner = ",".join(
            json.dumps(k, ensure_ascii=ensure_ascii)
            + ":"
            + _jcs_like(value[k], sort=sort, ensure_ascii=ensure_ascii)
            for k in items
        )
        return "{" + inner + "}"
    if isinstance(value, list):
        return (
            "["
            + ",".join(
                _jcs_like(v, sort=sort, ensure_ascii=ensure_ascii) for v in value
            )
            + "]"
        )
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=ensure_ascii)
    return canonicalize(value).decode("utf-8")


@pytest.mark.parametrize(
    "variant",
    [
        {"sort": None},
        {"sort": sorted},
        {
            "sort": lambda d: sorted(d, key=lambda k: k.encode("utf-16-be")),
            "ensure_ascii": True,
        },
    ],
    ids=["unsorted", "code-point-order", "ensure-ascii"],
)
def test_vectors_catch_a_wrong_canonicalization(variant):
    """Each plausible mistake gives different bytes for at least one vector."""
    wrong = [
        c["name"]
        for c in CASES
        if _jcs_like(c["declaration"], **variant) != c["canonical"]
    ]
    assert wrong


def test_python_float_printing_is_caught():
    """json.dumps prints 100.0 and 1e-07; the numbers vector expects 100 and 1e-7."""
    case = next(c for c in CASES if c["name"] == "numbers")
    naive = json.dumps(case["declaration"], separators=(",", ":"), sort_keys=True)
    assert naive != case["canonical"]


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        {"s": {1, 2}},
        {"n": 10**400},
        {"n": float("nan")},
        {"n": float("-inf")},
    ],
    ids=["int-key", "set", "huge-int", "nan", "infinity"],
)
def test_values_with_no_canonical_form(value):
    with pytest.raises(CanonicalizationError):
        view_digest(value)


def test_digest_is_over_the_declaration_as_written():
    """A field a reader adds changes the digest, so readers digest before adding."""
    view = vector("table_view")
    plain = view_digest(view)
    assert view_digest(view | {"url": "https://example.org/v"}) != plain
    reordered = dict(reversed(list(view.items())))
    assert view_digest(reordered) == plain


# ── The view envelope ─────────────────────────────────────────────────────


SCHEMA_DIR = ROOT / "schema"
VIEW_SCHEMA = SCHEMA_DIR / "definitions" / "view.schema.json"
VIEWS = SCHEMA_DIR / "views"
REGISTRY = load_registry()
SHA = "a" * 64


def view_errors(view) -> set[tuple[str, str]]:
    _schema, resolver = load_schema(VIEW_SCHEMA)
    validator = Draft202012Validator(
        {"$ref": f"file://{VIEW_SCHEMA}#/$defs/view"}, resolver=resolver
    )
    return failures(validator.iter_errors(view))


def table() -> dict:
    """A nemar.table view as a recipe writes it (the table_view digest vector)."""
    return vector("table_view")


def computed() -> dict:
    """A computed view of a kind neuroschema does not know."""
    return vector("computed_view")


def unknown_kind() -> dict:
    view = table()
    view.update(kind="acme.scalp-movie", kind_version=7, parameters={"fps": 30})
    view["data"][0].update(role="frames", format="npy", location="views/frames.npy")
    del view["data"][0]["columns"]
    return view


class TestEnvelope:
    def test_table_view_is_valid(self):
        assert view_errors(table()) == set()

    def test_computed_view_is_valid(self):
        assert view_errors(computed()) == set()

    def test_unknown_kind_passes_on_the_envelope(self):
        """Fails if kind is closed to the known kinds (an enum)."""
        assert view_errors(unknown_kind()) == set()

    def test_unknown_version_of_a_known_kind_passes_on_the_envelope(self):
        view = table()
        view["kind_version"] = 2
        view["data"][0]["role"] = "values"
        assert view_errors(view) == set()

    def test_known_kind_with_a_wrong_role_fails(self):
        """Fails if the kind dispatch (if/then) is dropped."""
        view = table()
        view["data"][0]["role"] = "values"
        assert view_errors(view) == {("const", "data/0/role")}

    def test_neither_data_nor_inputs_fails(self):
        view = computed()
        del view["inputs"]
        assert view_errors(view) == {("anyOf", "")}

    def test_empty_data_and_empty_inputs_fail(self):
        view = computed()
        view.update(inputs=[], data=[])
        assert view_errors(view) == {("anyOf", "")}

    @pytest.mark.parametrize("scope", ["subject", "dataset", "collection"])
    def test_reserved_scope_needs_sources(self, scope):
        view = computed()
        view["scope"] = scope
        assert view_errors(view) == {("required", "")}
        view["sources"] = [{"record_sha256": SHA}]
        assert view_errors(view) == set()

    def test_reserved_scope_sources_not_empty(self):
        view = computed()
        view.update(scope="dataset", sources=[])
        assert view_errors(view) == {("minItems", "sources")}

    @pytest.mark.parametrize("scope", [None, "recording"])
    def test_recording_view_has_no_sources(self, scope):
        view = computed()
        if scope:
            view["scope"] = scope
        assert view_errors(view) == set()
        view["sources"] = [{"record_sha256": SHA}]
        assert view_errors(view) == {("not", "sources")}

    def test_unknown_scope(self):
        view = computed()
        view["scope"] = "session"
        assert view_errors(view) == {("enum", "scope")}

    @pytest.mark.parametrize("field", ["base", "base_version"])
    def test_base_and_base_version_come_together(self, field):
        view = computed()
        view.update(base="nemar.lines", base_version=1)
        assert view_errors(view) == set()
        del view[field]
        assert view_errors(view) == {("dependentRequired", "")}

    @pytest.mark.parametrize("producers", [("plugin", "recipe"), ()])
    def test_source_names_exactly_one_producer(self, producers):
        view = table()
        view["source"] = {
            "plugin": {"name": "nemar-quality", "version": "0.1.0"},
            "recipe": {"name": "nemar-ica", "version": "1.0.0"},
        }
        view["source"] = {k: v for k, v in view["source"].items() if k in producers}
        assert view_errors(view) == {("oneOf", "source")}

    @pytest.mark.parametrize(
        "kind",
        ["table", "Nemar.table", "nemar.Table", "nemar..table", "nemar.-x", "1x.y"],
    )
    def test_bad_kind_name(self, kind):
        view = unknown_kind()
        view["kind"] = kind
        assert view_errors(view) == {("pattern", "kind")}

    def test_kind_name_length(self):
        view = unknown_kind()
        view["kind"] = "a." + "b" * 127
        assert view_errors(view) == {("maxLength", "kind")}

    @pytest.mark.parametrize(
        ("version", "validator"), [(0, "minimum"), (1000, "maximum"), (1.5, "type")]
    )
    def test_kind_version_bounds(self, version, validator):
        view = unknown_kind()
        view["kind_version"] = version
        assert view_errors(view) == {(validator, "kind_version")}

    @pytest.mark.parametrize("key", ["Channels", "1x", "a-b", "", "a" * 65])
    def test_bad_key(self, key):
        view = table()
        view["key"] = key
        assert view_errors(view) == {("pattern", "key")}

    @pytest.mark.parametrize(
        ("caption", "validator"), [("", "minLength"), ("c" * 501, "maxLength")]
    )
    def test_caption_length(self, caption, validator):
        view = table()
        view["caption"] = caption
        assert view_errors(view) == {(validator, "caption")}

    def test_closed_envelope(self):
        view = unknown_kind()
        view["figure"] = "x.png"
        assert view_errors(view) == {("additionalProperties", "")}


class TestTableKind:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("base", "nemar.lines"),
            ("transform", {"name": "nemar.x.v1", "parameters": {}}),
        ],
    )
    def test_table_has_no_base_or_transform(self, field, value):
        view = table()
        view[field] = value
        if field == "base":
            view["base_version"] = 1
            assert view_errors(view) == {("not", "base"), ("not", "base_version")}
        else:
            assert view_errors(view) == {("not", "transform")}

    def test_table_has_no_inputs(self):
        view = table()
        view["inputs"] = computed()["inputs"]
        assert view_errors(view) == {("not", "inputs")}

    def test_table_takes_no_parameters(self):
        view = table()
        view["parameters"] = {}
        assert view_errors(view) == set()
        view["parameters"] = {"sort": "name"}
        assert view_errors(view) == {("maxProperties", "parameters")}

    def test_table_is_one_tsv_file_with_columns(self):
        view = table()
        view["data"].append(copy.deepcopy(view["data"][0]))
        assert view_errors(view) == {("maxItems", "data")}
        view = table()
        del view["data"][0]["columns"]
        assert view_errors(view) == {("required", "data/0")}
        view = table()
        view["data"][0].update(format="json", location="views/channels.json")
        assert view_errors(view) == {("const", "data/0/format")}


# ── Data roles, dimensions and inputs ──────────────────────────────────────


def _dim(**fields) -> dict:
    return {"name": "freq", "axis": "rows", "type": "number", "unit": "Hz"} | fields


class TestViewData:
    @pytest.mark.parametrize(
        ("fmt", "location"), [("tsv", "views/a.json"), ("json", "views/a.tsv")]
    )
    def test_known_format_matches_extension(self, fmt, location):
        view = unknown_kind()
        view["data"][0].update(format=fmt, location=location)
        assert view_errors(view) == {("pattern", "data/0/location")}

    @pytest.mark.parametrize("fmt", ["TSV", "t-sv", "x" * 17])
    def test_bad_format_name(self, fmt):
        view = unknown_kind()
        view["data"][0]["format"] = fmt
        assert view_errors(view) == {("pattern", "data/0/format")}

    @pytest.mark.parametrize("name", ["a\tb", "a\nb", "a\rb", "a\n"])
    def test_column_name_has_no_tab_or_newline(self, name):
        view = table()
        view["data"][0]["columns"][0]["name"] = name
        assert view_errors(view) == {("pattern", "data/0/columns/0/name")}

    def test_column_type(self):
        view = table()
        view["data"][0]["columns"][0]["type"] = "float"
        assert view_errors(view) == {("enum", "data/0/columns/0/type")}

    @pytest.mark.parametrize(
        "coords",
        [{"column": "freq_hz"}, {"header": True}, {"role": "layout", "column": "name"}],
    )
    def test_coords_forms(self, coords):
        view = table()
        view["data"][0]["dims"] = [_dim(coords=coords)]
        assert view_errors(view) == set()

    @pytest.mark.parametrize(
        "coords",
        [
            {},
            {"header": False},
            {"column": "a", "header": True},
            {"role": "layout"},
            {"role": "Layout", "column": "name"},
        ],
    )
    def test_bad_coords(self, coords):
        view = table()
        view["data"][0]["dims"] = [_dim(coords=coords)]
        assert view_errors(view) == {("oneOf", "data/0/dims/0/coords")}

    def test_time_is_in_seconds(self):
        view = table()
        view["data"][0]["dims"] = [_dim(name="time", unit="s", coords={"column": "t"})]
        assert view_errors(view) == set()
        view["data"][0]["dims"][0]["unit"] = "ms"
        assert view_errors(view) == {("const", "data/0/dims/0/unit")}
        del view["data"][0]["dims"][0]["unit"]
        assert view_errors(view) == {("required", "data/0/dims/0")}

    def test_bad_axis(self):
        view = table()
        view["data"][0]["dims"] = [_dim(axis="depth", coords={"column": "f"})]
        assert view_errors(view) == {("enum", "data/0/dims/0/axis")}

    @pytest.mark.parametrize("system", ["CTF", "EEGLAB-HJ", "MNI152NLin2009cAsym"])
    def test_coordinate_system(self, system):
        view = table()
        view["data"][0].update(coordinate_system=system, position_source="measured")
        assert view_errors(view) == set()
        view["data"][0]["coordinate_system"] = "n/a"
        assert view_errors(view) == set()
        view["data"][0]["coordinate_system"] = system + "\n"
        assert view_errors(view) == {("pattern", "data/0/coordinate_system")}

    def test_position_source(self):
        view = table()
        view["data"][0]["position_source"] = "guessed"
        assert view_errors(view) == {("enum", "data/0/position_source")}


class TestInputs:
    def _store(self, view):
        return view["inputs"][1]["store"]

    def test_archive_run_may_have_no_store_digest(self):
        view = computed()
        assert self._store(view)["profile"] == "archive"
        assert self._store(view)["content_sha256"] is None
        assert view_errors(view) == set()

    def test_serving_run_needs_the_store_digest(self):
        view = computed()
        self._store(view)["profile"] = "serving"
        assert view_errors(view) == {("type", "inputs/1/store/content_sha256")}
        self._store(view)["content_sha256"] = SHA
        assert view_errors(view) == set()

    def test_input_is_exactly_one_of_file_and_store(self):
        view = computed()
        view["inputs"][0]["store"] = self._store(view)
        assert view_errors(view) == {("oneOf", "inputs/0")}
        del view["inputs"][0]["store"], view["inputs"][0]["file"]
        assert view_errors(view) == {("oneOf", "inputs/0")}

    def test_store_path_is_relative(self):
        view = computed()
        self._store(view)["path"] = "/abs/path.zarr"
        assert view_errors(view) == {("pattern", "inputs/1/store/path")}

    def test_transform_needs_parameters(self):
        view = computed()
        del view["transform"]["parameters"]
        assert view_errors(view) == {("required", "transform")}

    @pytest.mark.parametrize(
        "name", ["example.computed", "example.v1", "example.computed.v0"]
    )
    def test_transform_name_is_versioned(self, name):
        view = computed()
        view["transform"]["name"] = name
        assert view_errors(view) == {("pattern", "transform/name")}

    @pytest.mark.parametrize(
        "path",
        [
            "inputs/0",
            "inputs/0/file",
            "inputs/1/store",
            "transform",
            "source",
            "source/plugin",
        ],
    )
    def test_closed_objects(self, path):
        view = computed()
        node = view
        for part in path.split("/"):
            node = node[int(part)] if isinstance(node, list) else node[part]
        node["unexpected_key"] = 1
        assert view_errors(view) == {("additionalProperties", path)}


# ── The registry ──────────────────────────────────────────────────────────


KIND_FILE = re.compile(
    r"^kind\.(?P<kind>[a-z][a-z0-9]*(?:\.[a-z][a-z0-9-]*)+)\.v(?P<version>[1-9][0-9]*)"
    r"\.schema\.json$"
)


def _dispatch() -> dict[tuple[str, int], str]:
    """The (kind, kind_version) -> $ref pairs view.schema.json checks."""
    view = json.loads(VIEW_SCHEMA.read_text())["$defs"]["view"]
    pairs = {}
    for rule in view["allOf"]:
        props = rule["if"].get("properties", {})
        if "kind" in props:
            pair = (props["kind"]["const"], props["kind_version"]["const"])
            assert pair not in pairs, pair
            pairs[pair] = rule["then"]["$ref"]
    return pairs


class TestRegistry:
    def test_format(self):
        assert REGISTRY["format"] == REGISTRY_FORMAT == "neuroschema.views-registry.v1"

    def test_kind_files_and_registry_match_one_to_one(self):
        files = sorted(p.name for p in VIEWS.glob("kind.*.schema.json"))
        listed = sorted(Path(e["schema"]).name for e in REGISTRY["kinds"])
        assert files == listed
        assert files, "the registry lists at least one kind"

    def test_each_kind_file_is_named_for_its_kind(self):
        for entry in REGISTRY["kinds"]:
            path = ROOT / entry["schema"]
            assert path.parent == VIEWS
            match = KIND_FILE.match(path.name)
            assert match, path.name
            assert match["kind"] == entry["kind"]
            assert int(match["version"]) == entry["kind_version"]
            assert json.loads(path.read_text())["$id"] == path.name

    def test_view_schema_checks_exactly_the_registered_kinds(self):
        dispatch = _dispatch()
        assert set(dispatch) == set(known_kinds(REGISTRY))
        for (kind, version), ref in dispatch.items():
            assert ref == f"../views/kind.{kind}.v{version}.schema.json"

    def test_bases_are_registered_kinds(self):
        kinds = known_kinds(REGISTRY)
        for entry in REGISTRY["kinds"]:
            if entry["base"] is None:
                assert entry["base_version"] is None
            else:
                assert (entry["base"], entry["base_version"]) in kinds

    def test_roles_name_registered_formats(self):
        for entry in REGISTRY["kinds"]:
            assert entry["roles"], entry["kind"]
            for role, spec in entry["roles"].items():
                assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", role)
                assert set(spec["formats"]) <= set(REGISTRY["formats"])
                for dim in spec["dims"]:
                    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", dim)

    def test_formats_and_their_extension_rules(self):
        assert set(REGISTRY["formats"]) == {"tsv", "json"}
        rules = json.loads(VIEW_SCHEMA.read_text())["$defs"]["viewData"]["allOf"]
        by_format = {
            r["if"]["properties"]["format"]["const"]: r["then"]["properties"][
                "location"
            ]["pattern"]
            for r in rules
        }
        for name, spec in REGISTRY["formats"].items():
            assert by_format[name] == re.escape(spec["extension"]) + "$(?!\n)"

    def test_reserved_dims(self):
        reserved = REGISTRY["reserved_dims"]
        assert set(reserved) == {
            "time",
            "epoch",
            "recording",
            "subject",
            "contact",
            "sensor",
        }
        assert reserved["time"]["unit"] == "s"

    def test_caps(self):
        assert REGISTRY["caps"] == {
            "bytes_per_role": 4194304,
            "entries_per_dim": 1024,
            "cells_per_role": 262144,
        }

    def test_spec_and_vector_paths_exist(self):
        entries = [*REGISTRY["transforms"], *REGISTRY["algorithms"]]
        assert "nemar.view-digest.v1" in {e["name"] for e in entries}
        for entry in entries:
            assert (ROOT / entry["spec"]).is_file(), entry["spec"]
            assert (ROOT / entry["vectors"]).is_file(), entry["vectors"]

    def test_wrong_format_is_refused(self, tmp_path):
        path = tmp_path / "registry.json"
        path.write_text(json.dumps(REGISTRY | {"format": "views-registry.v0"}))
        with pytest.raises(ValueError, match=re.escape("views-registry.v0")):
            load_registry(path)

    def test_a_kind_listed_twice_is_refused(self):
        twice = REGISTRY | {"kinds": REGISTRY["kinds"] * 2}
        with pytest.raises(ValueError, match="listed twice"):
            known_kinds(twice)

    def test_kind_schema_path(self):
        assert kind_schema_path("nemar.table", 1) == (
            VIEWS / "kind.nemar.table.v1.schema.json"
        )
        assert kind_schema_path("nemar.table", 2, REGISTRY) is None


class TestRendererRule:
    def test_known_kind_draws_as_itself(self):
        assert draw_as(table(), REGISTRY) == Drawing("kind", "nemar.table", 1)

    def test_unknown_kind_with_a_known_base_draws_as_its_base(self):
        view = unknown_kind() | {"base": "nemar.table", "base_version": 1}
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.table", 1)

    def test_unknown_kind_draws_as_a_table(self):
        assert draw_as(unknown_kind(), REGISTRY) == Drawing("table", None, None)
        view = unknown_kind() | {"base": "nemar.table", "base_version": 9}
        assert draw_as(view) == Drawing("table", None, None)
