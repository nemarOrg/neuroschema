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

from neuroschema.validate import load_schema, schema_id, validate_document
from neuroschema.views import (
    REGISTRY_FORMAT,
    CanonicalizationError,
    Drawing,
    canonicalize,
    draw_as,
    kind_schema_path,
    known_kinds,
    load_registry,
    meets_role_contract,
    parse_declaration,
    role_schemas,
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
        view_digest(parse_declaration(refusal["json"]))


STANDARD = [r for r in REFUSALS if "duplicate" not in r["name"]]


@pytest.mark.parametrize("refusal", STANDARD, ids=[r["name"] for r in STANDARD])
def test_the_digest_refuses_what_a_standard_parser_reads(refusal):
    """A JavaScript implementation parses with JSON.parse and applies the
    refusals while it canonicalizes, so the digest of what a standard parser
    returns refuses every refusal but a duplicate name, which only the parse
    can see: a lone surrogate, a noncharacter, a number that is not finite and
    nesting deeper than 64 alike."""
    value = json.loads(refusal["json"])
    with pytest.raises(CanonicalizationError):
        view_digest(value)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_digest_from_text_matches_the_vector(case):
    text = json.dumps(case["declaration"], indent=1)
    assert view_digest(parse_declaration(text)) == case["sha256"]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_parse_declaration_refuses_non_json_literals(literal):
    """Python's json.loads accepts these; parse_declaration reads I-JSON only."""
    with pytest.raises(CanonicalizationError, match="not a JSON number"):
        parse_declaration('{"x":' + literal + "}")


DECLARATION = '{"unit":"µV"}'


@pytest.mark.parametrize(
    "text",
    [DECLARATION, DECLARATION.encode(), bytearray(DECLARATION.encode())],
    ids=["str", "utf-8-bytes", "utf-8-bytearray"],
)
def test_parse_declaration_reads_str_and_utf8(text):
    assert parse_declaration(text) == {"unit": "µV"}


@pytest.mark.parametrize(
    "text",
    [
        b"\xef\xbb\xbf" + DECLARATION.encode(),
        "\ufeff" + DECLARATION,
        DECLARATION.encode("utf-16"),
        DECLARATION.encode("utf-16-le"),
        DECLARATION.encode("utf-16-be"),
        DECLARATION.encode("utf-32"),
        DECLARATION.encode("utf-32-le"),
        b'{"unit":"\xff"}',
    ],
    ids=[
        "utf-8-bom-bytes",
        "bom-str",
        "utf-16-bom",
        "utf-16-le",
        "utf-16-be",
        "utf-32-bom",
        "utf-32-le",
        "invalid-utf-8",
    ],
)
def test_parse_declaration_refuses_other_encodings(text):
    """I-JSON text is UTF-8 with no byte order mark; json.loads detects the rest."""
    with pytest.raises(CanonicalizationError):
        parse_declaration(text)


@pytest.mark.parametrize("text", [{"unit": "V"}, 7, None, '{"unit":'])
def test_parse_declaration_refuses_non_text_and_non_json(text):
    with pytest.raises(CanonicalizationError):
        parse_declaration(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"k":1,"k":1}', "duplicate member name 'k'"),
        ('{"x":NaN}', "NaN is not a JSON number"),
    ],
)
def test_refusals_raised_while_parsing_keep_their_message(text, message):
    """parse_declaration re-raises its own refusals rather than wrapping them."""
    with pytest.raises(CanonicalizationError) as raised:
        parse_declaration(text)
    assert str(raised.value) == message


def test_an_integer_past_python_int_digits_is_refused():
    """json.loads raises a bare ValueError past int_max_str_digits (4,300)."""
    with pytest.raises(CanonicalizationError, match="integer literal too long"):
        parse_declaration('{"n":1' + "0" * 5000 + "}")


def test_duplicate_member_name_is_refused_at_any_depth():
    with pytest.raises(CanonicalizationError, match="duplicate member name 'k'"):
        parse_declaration('{"k":1,"k":1}')
    with pytest.raises(CanonicalizationError, match="duplicate member name 'name'"):
        parse_declaration('{"a":[{"b":{"name":"x","name":"x"}}]}')


def test_a_declared_size_is_within_the_cap_on_bytes():
    """A file's size is capped at the registry's caps.bytes_per_role, so a
    renderer can refuse a file before it fetches it (L3)."""
    view = ROOT / "schema" / "definitions" / "view.schema.json"
    defs = json.loads(view.read_text())
    cap = load_registry()["caps"]["bytes_per_role"]
    for name in ("viewData", "fileInput"):
        assert defs["$defs"][name]["properties"]["size"]["maximum"] == cap


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

    def test_table_role_carries_no_dims(self):
        view = table()
        view["data"][0]["dims"] = [_dim(coords={"column": "name"})]
        assert view_errors(view) == {("not", "data/0/dims")}

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
        """Both directions fail: the format's extension, and the extension's format."""
        view = unknown_kind()
        view["data"][0].update(format=fmt, location=location)
        assert view_errors(view) == {
            ("pattern", "data/0/location"),
            ("const", "data/0/format"),
        }

    @pytest.mark.parametrize(
        ("fmt", "location", "names"),
        [
            ("html", "views/a.tsv", "tsv"),
            ("csv", "views/a.json", "json"),
            ("html", "views/a.TsV", "tsv"),
            ("svg", "views/a.JSON", "json"),
        ],
    )
    def test_extension_names_the_format(self, fmt, location, names):
        """A .tsv or .json file, in any case, is of that format (L4, probe p18)."""
        view = unknown_kind()
        view["data"][0].update(format=fmt, location=location)
        assert view_errors(view) == {("const", "data/0/format")}

    @pytest.mark.parametrize(
        ("fmt", "location"), [("html", "views/index.html"), ("npy", "views/a.npy")]
    )
    def test_unregistered_format_under_its_own_extension(self, fmt, location):
        view = unknown_kind()
        view["data"][0].update(format=fmt, location=location)
        assert view_errors(view) == set()

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
        view = unknown_kind()
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
        view = unknown_kind()
        view["data"][0]["dims"] = [_dim(coords=coords)]
        assert view_errors(view) == {("oneOf", "data/0/dims/0/coords")}

    def test_time_is_in_seconds(self):
        view = unknown_kind()
        view["data"][0]["dims"] = [_dim(name="time", unit="s", coords={"column": "t"})]
        assert view_errors(view) == set()
        view["data"][0]["dims"][0]["unit"] = "ms"
        assert view_errors(view) == {("const", "data/0/dims/0/unit")}
        del view["data"][0]["dims"][0]["unit"]
        assert view_errors(view) == {("required", "data/0/dims/0")}

    def test_bad_axis(self):
        view = unknown_kind()
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


def _allowed(node: dict) -> set:
    """The values a const or enum admits."""
    return {node["const"]} if "const" in node else set(node["enum"])


def _schema_roles(schema: dict) -> dict[str, dict[str, set | None]]:
    """Each role a kind schema admits in data, with its formats and its dims.

    Reads data.items, or each branch of its oneOf or anyOf for a kind with
    several roles. A role's dims must be constrained: {"not": {}} admits none;
    otherwise dims.items.properties.name lists the admitted names, and a dims
    array whose items leave the name open admits any name (None, the
    registry's null).
    """
    data = schema["properties"]["data"]
    if data.get("not") == {}:
        return {}  # a computed kind: no stored data
    items = data["items"]
    roles: dict[str, dict[str, set | None]] = {}
    for branch in items.get("oneOf") or items.get("anyOf") or [items]:
        props = branch["properties"]
        dims = props["dims"]
        if dims.get("not") == {}:
            names = set()
        else:
            name = dims["items"].get("properties", {}).get("name")
            names = None if name is None else _allowed(name)
        for role in _allowed(props["role"]):
            assert role not in roles, role
            roles[role] = {"formats": _allowed(props["format"]), "dims": names}
    return roles


def _schema_inputs(schema: dict) -> dict[str, dict]:
    """Each input role a kind schema admits, with its source and, for a file,
    its format (the extension its location pattern requires)."""
    inputs = schema["properties"].get("inputs", {})
    if inputs.get("not") == {} or "items" not in inputs:
        return {}
    out: dict[str, dict] = {}
    for branch in inputs["items"]["oneOf"]:
        source = "file" if "file" in branch["required"] else "store"
        spec: dict = {"source": source}
        if source == "file":
            pattern = branch["properties"]["file"]["properties"]["location"]["pattern"]
            spec["formats"] = {re.match(r"\\\.(\w+)\$", pattern)[1]}
        for role in _allowed(branch["properties"]["role"]):
            assert role not in out, role
            out[role] = spec
    return out


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
            assert json.loads(path.read_text())["$id"] == schema_id(path)

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
        """Every kind has roles, except a computed kind, which has inputs."""
        for entry in REGISTRY["kinds"]:
            assert bool(entry["roles"]) is not bool(entry.get("inputs")), entry["kind"]
            for role, spec in [
                *entry["roles"].items(),
                *entry.get("inputs", {}).items(),
            ]:
                assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", role)
                assert set(spec.get("formats", [])) <= set(REGISTRY["formats"])
            for role, spec in entry["roles"].items():
                assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", role)
                assert set(spec["formats"]) <= set(REGISTRY["formats"])
                for dim in spec["dims"] or []:
                    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", dim)

    def test_formats_and_their_extension_rules(self):
        assert set(REGISTRY["formats"]) == {"tsv", "json"}
        rules = json.loads(VIEW_SCHEMA.read_text())["$defs"]["viewData"]["allOf"]
        by_format = {
            r["if"]["properties"]["format"]["const"]: r["then"]["properties"][
                "location"
            ]["pattern"]
            for r in rules
            if "format" in r["if"]["properties"]
        }
        by_extension = {
            r["then"]["properties"]["format"]["const"]: r["if"]["properties"][
                "location"
            ]["pattern"]
            for r in rules
            if "location" in r["if"]["properties"]
        }
        assert set(by_format) == set(by_extension) == set(REGISTRY["formats"])
        for name, spec in REGISTRY["formats"].items():
            assert by_format[name] == re.escape(spec["extension"]) + "$(?!\n)"
            any_case = "".join(
                f"[{c.upper()}{c}]" if c.isalpha() else re.escape(c)
                for c in spec["extension"]
            )
            assert by_extension[name] == any_case + "$(?!\n)"

    def test_registry_roles_match_each_kind_schema(self):
        """The registry's roles, formats and dims are what the kind schema admits."""
        for entry in REGISTRY["kinds"]:
            schema = json.loads((ROOT / entry["schema"]).read_text())
            assert _schema_roles(schema) == {
                role: {
                    "formats": set(spec["formats"]),
                    "dims": None if spec["dims"] is None else set(spec["dims"]),
                }
                for role, spec in entry["roles"].items()
            }, entry["kind"]

    def test_registry_inputs_match_each_kind_schema(self):
        """A computed kind's registered inputs are what its schema admits: each
        role, its source (file or store), and a file's format."""
        computed = []
        for entry in REGISTRY["kinds"]:
            schema = json.loads((ROOT / entry["schema"]).read_text())
            registered = {
                role: {"source": spec["source"]}
                | ({"formats": set(spec["formats"])} if "formats" in spec else {})
                for role, spec in entry.get("inputs", {}).items()
            }
            assert _schema_inputs(schema) == registered, entry["kind"]
            if registered:
                computed.append(entry["kind"])
        assert computed == ["nemar.ic-activity", "nemar.signal-window"]

    def test_reserved_dim_units_match_the_schema(self):
        """A reserved dimension's registered unit is the unit the schema requires."""
        rules = json.loads(VIEW_SCHEMA.read_text())["$defs"]["dim"]["allOf"]
        required = {
            r["if"]["properties"]["name"]["const"]: r["then"]["properties"]["unit"][
                "const"
            ]
            for r in rules
        }
        registered = {
            name: dim["unit"]
            for name, dim in REGISTRY["reserved_dims"].items()
            if dim["unit"] is not None
        }
        assert required == registered == {"time": "s"}

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

    def test_missing_registry_is_named(self, tmp_path):
        missing = tmp_path / "views" / "registry.json"
        with pytest.raises(FileNotFoundError, match="View registry not found"):
            load_registry(missing)

    def test_a_kind_listed_twice_is_refused(self):
        twice = REGISTRY | {"kinds": REGISTRY["kinds"] * 2}
        with pytest.raises(ValueError, match="listed twice"):
            known_kinds(twice)

    def test_kind_schema_path(self):
        assert kind_schema_path("nemar.table", 1) == (
            VIEWS / "kind.nemar.table.v1.schema.json"
        )
        assert kind_schema_path("nemar.table", 2, REGISTRY) is None


def _fixture_registry(tmp_path: Path, kind: str, items: dict) -> dict:
    """The registry plus one throwaway kind whose data.items is the given schema."""
    path = tmp_path / f"kind.{kind}.v1.schema.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": path.name,
                "title": "Fixture kind",
                "description": "A kind that exists only in this test.",
                "type": "object",
                "properties": {"data": {"type": "array", "items": items}},
            }
        )
    )
    entry = {
        "kind": kind,
        "kind_version": 1,
        "base": None,
        "base_version": None,
        "schema": str(path),
        "roles": {},
    }
    return REGISTRY | {"kinds": [*REGISTRY["kinds"], entry]}


class TestRendererRule:
    def test_known_kind_draws_as_itself(self):
        assert draw_as(table(), REGISTRY) == Drawing("kind", "nemar.table", 1)

    def _preset(self, view):
        """An unknown kind over the base nemar.table version 1."""
        return view | {
            "kind": "acme.channel-table",
            "kind_version": 1,
            "base": "nemar.table",
            "base_version": 1,
        }

    def test_unknown_kind_meeting_its_base_contract_draws_as_its_base(self):
        view = self._preset(table())
        assert meets_role_contract(view, known_kinds(REGISTRY)[("nemar.table", 1)])
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.table", 1)

    def test_extra_roles_do_not_break_the_base_contract(self):
        view = self._preset(table())
        view["data"].append(unknown_kind()["data"][0])
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.table", 1)

    def test_unknown_kind_missing_its_base_contract_draws_as_a_table(self):
        """Role frames, format npy, no columns: nothing a table renderer reads."""
        view = self._preset(unknown_kind())
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    @pytest.mark.parametrize(
        "breach", ["format", "twice", "dims", "no-columns", "no-data"]
    )
    def test_each_breach_of_the_base_contract_draws_as_a_table(self, breach):
        view = self._preset(table())
        if breach == "no-columns":
            del view["data"][0]["columns"]
        elif breach == "format":
            view["data"][0].update(format="json", location="views/channels.json")
        elif breach == "twice":
            view["data"].append(copy.deepcopy(view["data"][0]))
        elif breach == "dims":
            view["data"][0]["dims"] = [
                {
                    "name": "sensor",
                    "axis": "rows",
                    "type": "string",
                    "coords": {"column": "name"},
                }
            ]
        else:
            del view["data"]
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    def test_a_base_requiring_a_dim_refuses_a_preset_without_it(self, tmp_path):
        """A throwaway base kind whose one role must carry a freq dimension."""
        registry = _fixture_registry(
            tmp_path,
            "acme.lines",
            {
                "type": "object",
                "required": ["dims"],
                "properties": {
                    "role": {"const": "values"},
                    "format": {"const": "tsv"},
                    "dims": {
                        "type": "array",
                        "items": {"properties": {"name": {"enum": ["freq", "sensor"]}}},
                        "contains": {
                            "properties": {"name": {"const": "freq"}},
                            "required": ["name"],
                        },
                    },
                },
            },
        )
        view = unknown_kind() | {"base": "acme.lines", "base_version": 1}
        view["data"][0].update(role="values", format="tsv", location="v/s.tsv")
        sensor = _dim(name="sensor", axis="columns", coords={"header": True})
        freq = _dim(coords={"column": "freq_hz"})
        view["data"][0]["dims"] = [freq, sensor]
        assert draw_as(view, registry) == Drawing("base", "acme.lines", 1)
        view["data"][0]["dims"] = [sensor]
        assert draw_as(view, registry) == Drawing("table", None, None)
        del view["data"][0]["dims"]
        assert draw_as(view, registry) == Drawing("table", None, None)

    def test_a_base_with_two_roles_checks_each_against_its_branch(self, tmp_path):
        """A throwaway base kind whose data.items has one oneOf branch per role."""
        registry = _fixture_registry(
            tmp_path,
            "acme.maps",
            {
                "type": "object",
                "oneOf": [
                    {
                        "properties": {
                            "role": {"const": "values"},
                            "format": {"const": "tsv"},
                        }
                    },
                    {
                        "required": ["columns"],
                        "properties": {
                            "role": {"const": "layout"},
                            "format": {"const": "tsv"},
                        },
                    },
                ],
            },
        )
        entry = known_kinds(registry)[("acme.maps", 1)]
        assert set(role_schemas(entry)) == {"values", "layout"}
        view = self._preset(table()) | {"base": "acme.maps"}
        values = copy.deepcopy(view["data"][0]) | {"role": "values"}
        layout = copy.deepcopy(view["data"][0]) | {"role": "layout"}
        view["data"] = [values, layout]
        assert draw_as(view, registry) == Drawing("base", "acme.maps", 1)
        del layout["columns"]
        assert draw_as(view, registry) == Drawing("table", None, None)
        view["data"] = [values]
        assert draw_as(view, registry) == Drawing("table", None, None)

    def test_an_enum_role_admits_each_of_its_values(self, tmp_path):
        """A throwaway anyOf base whose first branch admits two roles by enum."""
        registry = _fixture_registry(
            tmp_path,
            "acme.bands",
            {
                "type": "object",
                "anyOf": [
                    {
                        "properties": {
                            "role": {"enum": ["values", "errors"]},
                            "format": {"const": "tsv"},
                        }
                    },
                    {
                        "properties": {
                            "role": {"const": "layout"},
                            "format": {"const": "tsv"},
                        }
                    },
                ],
            },
        )
        entry = known_kinds(registry)[("acme.bands", 1)]
        branches = role_schemas(entry)
        assert set(branches) == {"values", "errors", "layout"}
        assert branches["values"] is branches["errors"]
        view = self._preset(table()) | {"base": "acme.bands"}
        view["data"] = [
            copy.deepcopy(view["data"][0]) | {"role": role}
            for role in ("values", "errors", "layout")
        ]
        assert draw_as(view, registry) == Drawing("base", "acme.bands", 1)
        del view["data"][1]
        assert draw_as(view, registry) == Drawing("table", None, None)

    def test_a_role_that_is_neither_const_nor_enum_is_refused(self, tmp_path):
        registry = _fixture_registry(
            tmp_path,
            "acme.loose",
            {"type": "object", "properties": {"role": {"pattern": "^v"}}},
        )
        entry = known_kinds(registry)[("acme.loose", 1)]
        with pytest.raises(ValueError, match="must be a const or an enum"):
            role_schemas(entry)

    @pytest.mark.parametrize(
        "second", [{"const": "values"}, {"enum": ["layout", "values"]}]
    )
    def test_a_role_in_two_branches_is_refused(self, tmp_path, second):
        registry = _fixture_registry(
            tmp_path,
            "acme.twice",
            {
                "type": "object",
                "oneOf": [
                    {"properties": {"role": {"const": "values"}}},
                    {"properties": {"role": second}},
                ],
            },
        )
        entry = known_kinds(registry)[("acme.twice", 1)]
        with pytest.raises(ValueError, match="role values has two branches"):
            role_schemas(entry)

    @pytest.mark.parametrize("missing", ["base_version", "base"])
    def test_half_a_base_draws_as_a_table(self, missing):
        view = self._preset(table())
        del view[missing]
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    def test_unknown_kind_draws_as_a_table(self):
        assert draw_as(unknown_kind(), REGISTRY) == Drawing("table", None, None)
        view = self._preset(table()) | {"base_version": 9}
        assert draw_as(view) == Drawing("table", None, None)


# ── dataQuality: views replace figures ────────────────────────────────────


DATA_QUALITY = SCHEMA_DIR / "extensions" / "dataQuality.schema.json"
RECORD_EXAMPLE = ROOT / "examples" / "record-ds002718-processing.json"
FLOOR = "recipes/nemar-floor"


def _record() -> dict:
    return json.loads(RECORD_EXAMPLE.read_text())


def _floor_quality(record: dict) -> dict:
    return record["extensions"]["dataQuality"]["recipes"]["nemar-floor"]


def _dq_record() -> dict:
    return _record()["extensions"]["dataQuality"]


class TestDataQualityViews:
    def test_record_with_figures_fails(self):
        doc = _dq_record()
        entry = doc["recipes"]["nemar-floor"]
        entry["figures"] = entry.pop("views")
        assert failures(validate_document(doc, DATA_QUALITY)) == {
            ("required", FLOOR),
            ("additionalProperties", FLOOR),
        }

    def test_record_without_views_fails(self):
        doc = _dq_record()
        del doc["recipes"]["nemar-floor"]["views"]
        assert failures(validate_document(doc, DATA_QUALITY)) == {("required", FLOOR)}

    def test_views_may_be_empty(self):
        doc = _dq_record()
        doc["recipes"]["nemar-floor"]["views"] = []
        assert validate_document(doc, DATA_QUALITY) == []

    def test_at_most_32_views(self):
        doc = _dq_record()
        views = doc["recipes"]["nemar-floor"]["views"]
        views[:] = [views[0] | {"key": f"v{i}"} for i in range(32)]
        assert validate_document(doc, DATA_QUALITY) == []
        views.append(views[0] | {"key": "v32"})
        assert failures(validate_document(doc, DATA_QUALITY)) == {
            ("maxItems", f"{FLOOR}/views")
        }

    def test_view_error_is_reported_inside_the_record(self):
        doc = _record()
        _floor_quality(doc)["views"][0]["data"][0]["role"] = "values"
        where = "extensions/dataQuality/recipes/nemar-floor/views/0/data/0/role"
        assert failures(validate_document(doc)) == {("const", where)}

    def test_example_view_is_the_table_vector(self):
        """The record example's view is a digest vector, so its digest is pinned."""
        view = _floor_quality(_record())["views"][0]
        assert view == vector("table_view")
        assert view_errors(view) == set()


# ── qualityMetric: exactly one producer ───────────────────────────────────


METRIC = SCHEMA_DIR / "definitions" / "qualityMetric.schema.json"


def _metric(**producers) -> dict:
    return {
        "value": 93.2,
        "unit": "%",
        "description": "Share of samples kept after bad-window rejection.",
    } | producers


PLUGIN = {"name": "nemar-quality", "version": "0.1.0"}
RECIPE = {"name": "nemar-floor", "version": "1.0.0-b1"}


class TestMetricProducer:
    @pytest.mark.parametrize("producer", ["plugin", "recipe"])
    def test_one_producer(self, producer):
        metric = _metric(**{producer: PLUGIN if producer == "plugin" else RECIPE})
        assert failures(validate_document(metric, METRIC)) == set()

    def test_both_producers_fail(self):
        """Fails if oneOf becomes anyOf."""
        metric = _metric(plugin=PLUGIN, recipe=RECIPE)
        assert failures(validate_document(metric, METRIC)) == {("oneOf", "")}

    def test_no_producer_fails(self):
        assert failures(validate_document(_metric(), METRIC)) == {("oneOf", "")}

    def test_recipe_name_is_a_recipe_id(self):
        metric = _metric(recipe=RECIPE | {"name": "Nemar Floor"})
        assert failures(validate_document(metric, METRIC)) == {
            ("pattern", "recipe/name")
        }

    def test_recipe_is_closed(self):
        metric = _metric(recipe=RECIPE | {"commit": "abc"})
        assert failures(validate_document(metric, METRIC)) == {
            ("additionalProperties", "recipe")
        }


# ── Distribution: a stated unit ───────────────────────────────────────────


DATASET_EXAMPLE = ROOT / "examples" / "dataset-ds002718-processing.json"


class TestDistributionUnit:
    def _dist(self, doc):
        entry = doc["extensions"]["dataQuality"]["recipes"]["nemar-floor"]
        return entry["distributions"]["percentGoodSamples"]

    WHERE = (
        "extensions/dataQuality/recipes/nemar-floor/distributions/percentGoodSamples"
    )

    def test_example_is_valid(self):
        assert validate_document(json.loads(DATASET_EXAMPLE.read_text())) == []

    def test_distribution_without_unit_fails(self):
        doc = json.loads(DATASET_EXAMPLE.read_text())
        del self._dist(doc)["unit"]
        assert failures(validate_document(doc)) == {("required", self.WHERE)}

    def test_description_is_optional_and_bounded(self):
        doc = json.loads(DATASET_EXAMPLE.read_text())
        del self._dist(doc)["description"]
        assert validate_document(doc) == []
        self._dist(doc)["description"] = "d" * 501
        assert failures(validate_document(doc)) == {
            ("maxLength", f"{self.WHERE}/description")
        }

    def test_empty_unit_fails(self):
        doc = json.loads(DATASET_EXAMPLE.read_text())
        self._dist(doc)["unit"] = ""
        assert failures(validate_document(doc)) == {("minLength", f"{self.WHERE}/unit")}
