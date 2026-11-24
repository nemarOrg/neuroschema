"""Schemas for the kind nemar.sensor-field v1 and the transform nemar.sensor-layout.v1.

Real schema files, no mocks. Failures are asserted as (validator, path) pairs,
and a constraint inside a role's branch is checked against that branch, so a
negative test cannot pass for the wrong reason.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema
from neuroschema.views import (
    Drawing,
    draw_as,
    known_kinds,
    load_registry,
    meets_role_contract,
    optional_roles,
    role_schemas,
)
from tests.helpers import failures

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
VIEW_SCHEMA = SCHEMA_DIR / "definitions" / "view.schema.json"
VIEWS = SCHEMA_DIR / "views"
KIND = VIEWS / "kind.nemar.sensor-field.v1.schema.json"
REGISTRY = load_registry()
FIELD = known_kinds(REGISTRY)[("nemar.sensor-field", 1)]
SHA = "a" * 64
SHA2 = "b" * 64


def view_errors(view) -> set[tuple[str, str]]:
    _schema, resolver = load_schema(VIEW_SCHEMA)
    validator = Draft202012Validator(
        {"$ref": f"file://{VIEW_SCHEMA}#/$defs/view"}, resolver=resolver
    )
    return failures(validator.iter_errors(view))


def role_errors(entry: dict, role: str) -> set[tuple[str, str]]:
    """Failures of one data entry against the kind's branch for a role."""
    _schema, resolver = load_schema(KIND)
    branch = role_schemas(FIELD)[role]
    return failures(Draft202012Validator(branch, resolver=resolver).iter_errors(entry))


def values_entry() -> dict:
    """An independent component analysis mixing matrix: sensors along the rows,
    one map per component column, sensors from the layout by position."""
    return {
        "role": "values",
        "location": "views/sub-01_task-rest_desc-nemarica_mixing.tsv",
        "format": "tsv",
        "size": 18733,
        "sha256": SHA,
        "columns": [
            {"name": "IC1", "type": "number", "unit": "uV"},
            {"name": "IC2", "type": "number", "unit": "uV"},
        ],
        "dims": [
            {
                "name": "sensor",
                "axis": "rows",
                "type": "string",
                "coords": {"role": "layout", "column": "name"},
            },
            {
                "name": "component",
                "axis": "columns",
                "type": "string",
                "coords": {"header": True},
            },
        ],
    }


def layout_entry() -> dict:
    return {
        "role": "layout",
        "location": "views/sub-01_task-rest_desc-nemarica_chanlocs.tsv",
        "format": "tsv",
        "size": 2204,
        "sha256": SHA2,
        "columns": [
            {"name": "name", "type": "string"},
            {"name": "theta_deg", "type": "number", "unit": "deg"},
            {"name": "radius", "type": "number"},
            {"name": "sensor_type", "type": "string"},
        ],
        "dims": [
            {
                "name": "sensor",
                "axis": "rows",
                "type": "string",
                "coords": {"column": "name"},
            }
        ],
        "coordinate_system": "CapTrak",
        "position_source": "measured",
    }


def positions_entry() -> dict:
    """A recording's measured electrode positions, in centimeters."""
    return {
        "role": "positions",
        "location": "views/sub-01_task-rest_desc-nemarica_chanlocs.tsv",
        "format": "tsv",
        "size": 2911,
        "sha256": SHA2,
        "columns": [
            {"name": "name", "type": "string"},
            {"name": "x", "type": "number", "unit": "cm"},
            {"name": "y", "type": "number", "unit": "cm"},
            {"name": "z", "type": "number", "unit": "cm"},
        ],
        "dims": [
            {
                "name": "sensor",
                "axis": "rows",
                "type": "string",
                "coords": {"column": "name"},
            }
        ],
        "coordinate_system": "CapTrak",
        "position_source": "measured",
    }


def positioned() -> dict:
    """A scalp map placed by three-dimensional positions, projected in the browser."""
    view = field()
    view["data"][1] = positions_entry()
    view["data"][0]["dims"][0]["coords"] = {"role": "positions", "column": "name"}
    view["transform"] = {"name": "nemar.sensor-layout.v1", "parameters": {}}
    return view


def field(*, layout: bool = True) -> dict:
    view = {
        "key": "icmaps",
        "kind": "nemar.sensor-field",
        "kind_version": 1,
        "caption": "Scalp maps of the independent components.",
        "source": {"recipe": {"name": "nemar-ica", "version": "1.0.0"}},
        "parameters": {"limits": "absmax"},
        "data": [values_entry()],
    }
    if layout:
        view["data"].append(layout_entry())
    else:
        values = view["data"][0]
        values["columns"].insert(0, {"name": "channel", "type": "string"})
        values["dims"][0]["coords"] = {"column": "channel"}
    return view


def sensors_on_columns(*, layout: bool) -> dict:
    """A spectrum-like file: one map per row, sensors in the header."""
    view = field(layout=layout)
    values = view["data"][0]
    values["columns"] = [
        {"name": "freq_hz", "type": "number", "unit": "Hz"},
        {"name": "Fz", "type": "number"},
        {"name": "Cz", "type": "number"},
    ]
    sensor = {"name": "sensor", "axis": "columns", "type": "string"}
    sensor["coords"] = (
        {"role": "layout", "column": "name"} if layout else {"header": True}
    )
    values["dims"] = [
        {
            "name": "freq",
            "axis": "rows",
            "type": "number",
            "unit": "Hz",
            "coords": {"column": "freq_hz"},
        },
        sensor,
    ]
    return view


class TestKindDeclaration:
    @pytest.mark.parametrize("layout", [True, False])
    def test_sensors_along_rows_are_valid(self, layout):
        assert view_errors(field(layout=layout)) == set()

    @pytest.mark.parametrize("layout", [True, False])
    def test_sensors_along_columns_are_valid(self, layout):
        assert view_errors(sensors_on_columns(layout=layout)) == set()

    def test_one_map_with_no_second_dimension(self):
        view = field()
        values = view["data"][0]
        values["columns"] = values["columns"][:1]
        values["dims"] = values["dims"][:1]
        assert view_errors(view) == set()

    def test_layout_may_come_first(self):
        view = field()
        view["data"].reverse()
        assert view_errors(view) == set()

    def test_values_are_required(self):
        view = field()
        del view["data"][0]
        assert view_errors(view) == {("contains", "data")}

    def test_values_at_most_once(self):
        view = field(layout=False)
        view["data"].append(copy.deepcopy(view["data"][0]))
        assert view_errors(view) == {("maxContains", "data")}

    def test_layout_at_most_once(self):
        """Fails if the layout's maxContains is dropped."""
        view = field()
        view["data"].append(layout_entry())
        assert view_errors(view) == {("maxContains", "data")}

    def test_data_is_not_empty(self):
        view = field()
        view["data"] = []
        assert ("contains", "data") in view_errors(view)

    def test_unknown_role_fails(self):
        """The kind admits only values, layout and positions: a view of the kind
        itself with any other role fails. (A preset drawn by this base may carry
        other roles; the role contract ignores them.)"""
        view = field(layout=False)
        view["data"].append(layout_entry() | {"role": "names"})
        assert view_errors(view) == {("oneOf", "data/1")}

    @pytest.mark.parametrize("field_name", ["base", "inputs", "transform"])
    def test_generic_and_stored(self, field_name):
        view = field()
        value = {
            "base": "nemar.lines",
            "inputs": [
                {
                    "role": "positions",
                    "file": {"location": "views/p.tsv", "sha256": SHA, "size": 9},
                }
            ],
            "transform": {"name": "acme.project.v1", "parameters": {}},
        }[field_name]
        view[field_name] = value
        if field_name == "base":
            view["base_version"] = 1
            assert view_errors(view) == {("not", "base"), ("not", "base_version")}
        elif field_name == "transform":
            assert view_errors(view) == {
                ("const", "transform/name"),
                ("not", "transform"),
            }
        else:
            assert view_errors(view) == {("not", field_name)}

    @pytest.mark.parametrize(
        ("parameters", "expected"),
        [
            ({}, set()),
            ({"limits": "minmax"}, set()),
            ({"limits": "auto"}, {("enum", "parameters/limits")}),
            ({"plotrad": 0.6}, {("additionalProperties", "parameters")}),
        ],
    )
    def test_parameters(self, parameters, expected):
        view = field()
        view["parameters"] = parameters
        assert view_errors(view) == expected

    def test_with_a_layout_sensors_come_from_it(self):
        """Fails if the cross-role rule (layout present) is dropped."""
        view = field()
        view["data"][0]["dims"][0]["coords"] = {"column": "IC1"}
        assert view_errors(view) == {
            ("required", "data/0/dims/0/coords"),
            ("const", "data/0/dims/0/coords/column"),
        }
        view["data"][0]["dims"][0]["coords"] = {"role": "layout", "column": "label"}
        assert view_errors(view) == {("const", "data/0/dims/0/coords/column")}

    def test_without_a_layout_sensors_are_named_here(self):
        """Fails if the cross-role rule (no layout) is dropped."""
        view = field()
        del view["data"][1]
        assert view_errors(view) == {("not", "data/0/dims/0/coords")}

    def test_a_sensors_from_another_role_fail_on_columns(self):
        view = sensors_on_columns(layout=False)
        view["data"][0]["dims"][1]["coords"] = {"role": "names", "column": "name"}
        assert view_errors(view) == {("not", "data/0/dims/1/coords")}


class TestPositionsSource:
    def test_valid(self):
        assert view_errors(positioned()) == set()

    def test_positions_need_the_transform(self):
        """Fails if the kind's rule (positions -> transform) is dropped."""
        view = positioned()
        del view["transform"]
        assert view_errors(view) == {("required", "")}

    def test_no_transform_without_positions(self):
        """Fails if the kind's else (no positions -> no transform) is dropped."""
        view = field()
        view["transform"] = {"name": "nemar.sensor-layout.v1", "parameters": {}}
        assert view_errors(view) == {
            ("not", "transform"),
            ("required", ""),
            ("required", "transform/parameters"),
        }

    def test_stored_positions_name_their_own_frame(self):
        """The frame is declared once: on the role, not in the parameters."""
        view = positioned()
        view["transform"]["parameters"] = {"coordinate_system": "CapTrak"}
        assert view_errors(view) == {("maxProperties", "transform/parameters")}

    def test_stored_positions_are_not_also_an_input(self):
        view = positioned()
        view["inputs"] = layout_transform_view()["inputs"]
        assert view_errors(view) == {("not", "inputs")}

    def test_at_most_one_of_layout_and_positions(self):
        """Fails if the one-source rule is dropped."""
        view = positioned()
        view["data"].append(layout_entry())
        assert ("not", "data") in view_errors(view)

    def test_positions_at_most_once(self):
        view = positioned()
        view["data"].append(positions_entry())
        assert view_errors(view) == {("maxContains", "data")}

    def test_with_positions_sensors_come_from_them(self):
        """Fails if the cross-role rule for positions is dropped."""
        view = positioned()
        view["data"][0]["dims"][0]["coords"] = {"role": "layout", "column": "name"}
        assert view_errors(view) == {("const", "data/0/dims/0/coords/role")}

    def test_a_preset_with_positions_draws_as_its_base(self):
        view = preset(positioned())
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.sensor-field", 1)
        view["data"].append(layout_entry())
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)


class TestPositionsRole:
    def test_valid(self):
        assert role_errors(positions_entry(), "positions") == set()

    @pytest.mark.parametrize(
        "missing", ["coordinate_system", "position_source", "columns", "dims"]
    )
    def test_required(self, missing):
        entry = positions_entry()
        del entry[missing]
        assert role_errors(entry, "positions") == {("required", "")}

    @pytest.mark.parametrize("column", ["name", "x", "y", "z"])
    def test_required_columns(self, column):
        entry = positions_entry()
        entry["columns"] = [c for c in entry["columns"] if c["name"] != column]
        assert role_errors(entry, "positions") == {("contains", "columns")}

    def test_a_column_twice_fails(self):
        entry = positions_entry()
        entry["columns"].append({"name": "z", "type": "number"})
        assert role_errors(entry, "positions") == {("maxContains", "columns")}

    def test_no_layout_columns(self):
        entry = positions_entry()
        entry["columns"].append({"name": "theta_deg", "type": "number", "unit": "deg"})
        assert role_errors(entry, "positions") == {("enum", "columns/4/name")}

    @pytest.mark.parametrize(
        ("index", "change", "expected"),
        [
            (0, {"type": "number"}, ("const", "columns/0/type")),
            (1, {"type": "string"}, ("const", "columns/1/type")),
            (3, {"type": "integer"}, ("const", "columns/3/type")),
        ],
    )
    def test_column_types(self, index, change, expected):
        entry = positions_entry()
        entry["columns"][index].update(change)
        assert role_errors(entry, "positions") == {expected}

    def test_the_sensor_dimension(self):
        entry = positions_entry()
        entry["dims"][0]["coords"] = {"column": "label"}
        assert role_errors(entry, "positions") == {("const", "dims/0/coords/column")}

    def test_template_positions_in_a_full_view(self):
        """Template positions name their montage and n/a; the envelope's rule for
        a template role (nemar.sensor-labels.v1) refuses a montage beside a named
        frame, never guessed, and a template role without a montage."""
        view = positioned()
        positions = view["data"][1]
        positions.update(
            position_source="template",
            coordinate_system="n/a",
            montage="GSN-HydroCel-32",
        )
        assert view_errors(view) == set()
        positions["coordinate_system"] = "CapTrak"
        assert view_errors(view) == {("const", "data/1/coordinate_system")}
        positions["coordinate_system"] = "n/a"
        del positions["montage"]
        assert view_errors(view) == {("required", "data/1")}
        positions.update(position_source="measured", montage="GSN-HydroCel-32")
        assert view_errors(view) == {("const", "data/1/position_source")}


class TestValuesRole:
    def test_valid(self):
        assert role_errors(values_entry(), "values") == set()

    @pytest.mark.parametrize("missing", ["columns", "dims", "format"])
    def test_required(self, missing):
        entry = values_entry()
        del entry[missing]
        assert role_errors(entry, "values") == {("required", "")}

    def test_tsv_only(self):
        entry = values_entry() | {"format": "json"}
        assert role_errors(entry, "values") == {("const", "format")}

    def test_needs_a_sensor_dimension(self):
        entry = values_entry()
        entry["dims"][0]["name"] = "channel"
        assert role_errors(entry, "values") == {("contains", "dims")}

    def test_one_sensor_dimension(self):
        entry = values_entry()
        entry["dims"][1] = copy.deepcopy(entry["dims"][0]) | {"axis": "columns"}
        entry["dims"][1]["coords"] = {"header": True}
        assert role_errors(entry, "values") == {("maxContains", "dims")}

    def test_at_most_two_dimensions(self):
        entry = values_entry()
        entry["dims"].append(
            {
                "name": "epoch",
                "axis": "rows",
                "type": "integer",
                "coords": {"column": "e"},
            }
        )
        assert role_errors(entry, "values") == {("maxItems", "dims")}

    def test_two_dimensions_on_one_axis_fail(self):
        entry = values_entry()
        entry["dims"][1].update(axis="rows", coords={"column": "IC1"})
        assert role_errors(entry, "values") == {("contains", "dims")}

    def test_sensors_are_named(self):
        entry = values_entry()
        entry["dims"][0]["type"] = "integer"
        assert role_errors(entry, "values") == {("const", "dims/0/type")}

    def test_sensors_along_rows_are_not_header_names(self):
        entry = values_entry()
        entry["dims"][0]["coords"] = {"header": True}
        entry["dims"][1].update(axis="columns")
        assert role_errors(entry, "values") == {("anyOf", "dims/0")}

    def test_sensors_along_columns_are_not_a_column(self):
        entry = values_entry()
        entry["dims"][0].update(axis="columns", coords={"column": "IC1"})
        entry["dims"][1].update(axis="rows", coords={"column": "IC2"})
        assert role_errors(entry, "values") == {("anyOf", "dims/0")}

    def test_the_other_dimension_has_any_name(self):
        entry = values_entry()
        entry["dims"][1]["name"] = "acme_condition"
        assert role_errors(entry, "values") == set()


class TestLayoutRole:
    def test_valid(self):
        assert role_errors(layout_entry(), "layout") == set()

    @pytest.mark.parametrize(
        "missing", ["coordinate_system", "position_source", "columns", "dims"]
    )
    def test_required(self, missing):
        entry = layout_entry()
        del entry[missing]
        assert role_errors(entry, "layout") == {("required", "")}

    @pytest.mark.parametrize("column", ["name", "theta_deg", "radius"])
    def test_required_columns(self, column):
        entry = layout_entry()
        entry["columns"] = [c for c in entry["columns"] if c["name"] != column]
        assert role_errors(entry, "layout") == {("contains", "columns")}

    def test_sensor_type_is_optional(self):
        entry = layout_entry()
        entry["columns"] = entry["columns"][:3]
        assert role_errors(entry, "layout") == set()

    def test_a_column_twice_fails(self):
        entry = layout_entry()
        entry["columns"].append({"name": "radius", "type": "number"})
        assert role_errors(entry, "layout") == {("maxContains", "columns")}

    def test_no_other_columns(self):
        entry = layout_entry()
        entry["columns"].append({"name": "x", "type": "number"})
        assert role_errors(entry, "layout") == {("enum", "columns/4/name")}

    @pytest.mark.parametrize(
        ("index", "change", "expected"),
        [
            (0, {"type": "number"}, ("const", "columns/0/type")),
            (1, {"type": "string"}, ("const", "columns/1/type")),
            (1, {"unit": "rad"}, ("const", "columns/1/unit")),
            (2, {"type": "integer"}, ("const", "columns/2/type")),
            (3, {"type": "number"}, ("const", "columns/3/type")),
        ],
    )
    def test_column_types(self, index, change, expected):
        entry = layout_entry()
        entry["columns"][index].update(change)
        assert role_errors(entry, "layout") == {expected}

    def test_theta_states_degrees(self):
        entry = layout_entry()
        del entry["columns"][1]["unit"]
        assert role_errors(entry, "layout") == {("required", "columns/1")}

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ({"name": "channel"}, ("const", "dims/0/name")),
            ({"axis": "columns"}, ("const", "dims/0/axis")),
            ({"type": "integer"}, ("const", "dims/0/type")),
            ({"coords": {"column": "label"}}, ("const", "dims/0/coords/column")),
            ({"coords": {"header": True}}, ("required", "dims/0/coords")),
            (
                {"coords": {"role": "layout", "column": "name"}},
                ("not", "dims/0/coords"),
            ),
        ],
    )
    def test_the_sensor_dimension(self, change, expected):
        entry = layout_entry()
        entry["dims"][0].update(change)
        assert role_errors(entry, "layout") == {expected}

    def test_one_dimension(self):
        entry = layout_entry()
        entry["dims"].append(copy.deepcopy(entry["dims"][0]))
        assert role_errors(entry, "layout") == {("maxItems", "dims")}


# ── The transform nemar.sensor-layout.v1 ──────────────────────────────────


def layout_transform_view() -> dict:
    """A computed view of a kind neuroschema does not know, laid out in the browser."""
    return {
        "key": "electrodes",
        "kind": "acme.electrode-map",
        "kind_version": 1,
        "caption": "Electrode positions laid out from the recording's electrodes file.",
        "source": {"plugin": {"name": "acme-positions", "version": "0.1.0"}},
        "inputs": [
            {
                "role": "positions",
                "file": {
                    "location": "views/positions.tsv",
                    "sha256": SHA,
                    "size": 4096,
                },
            }
        ],
        "transform": {
            "name": "nemar.sensor-layout.v1",
            "parameters": {"coordinate_system": "CapTrak"},
        },
    }


class TestLayoutTransform:
    def test_valid(self):
        assert view_errors(layout_transform_view()) == set()

    @pytest.mark.parametrize("frame", ["n/a", "Other", "EEGLAB-HJ"])
    def test_any_frame_name_passes_the_schema(self, frame):
        """An unknown frame is refused when the transform runs, not here."""
        view = layout_transform_view()
        view["transform"]["parameters"]["coordinate_system"] = frame
        assert view_errors(view) == set()

    def test_frame_is_required(self):
        view = layout_transform_view()
        view["transform"]["parameters"] = {}
        assert view_errors(view) == {("required", "transform/parameters")}

    @pytest.mark.parametrize("frame", ["CapTrak\n", "-x", ""])
    def test_frame_pattern(self, frame):
        view = layout_transform_view()
        view["transform"]["parameters"]["coordinate_system"] = frame
        assert view_errors(view) == {
            ("pattern", "transform/parameters/coordinate_system")
        }

    def test_one_parameter(self):
        view = layout_transform_view()
        view["transform"]["parameters"]["center"] = "fminsearch"
        assert view_errors(view) == {("additionalProperties", "transform/parameters")}

    def test_input_is_positions(self):
        view = layout_transform_view()
        view["inputs"][0]["role"] = "electrodes"
        assert view_errors(view) == {("const", "inputs/0/role")}

    def test_input_is_a_tsv_file(self):
        view = layout_transform_view()
        view["inputs"][0]["file"]["location"] = "views/positions.json"
        assert view_errors(view) == {("pattern", "inputs/0/file/location")}

    def test_input_is_a_file_not_a_store(self):
        view = layout_transform_view()
        view["inputs"][0] = {
            "role": "positions",
            "store": {
                "recording": "sub-01/eeg/sub-01_task-rest_eeg.edf",
                "group": "eeg",
                "content_sha256": SHA,
                "profile": "serving",
            },
        }
        assert view_errors(view) == {("required", "inputs/0")}

    def test_one_input(self):
        view = layout_transform_view()
        view["inputs"].append(copy.deepcopy(view["inputs"][0]))
        assert view_errors(view) == {("maxItems", "inputs")}

    def test_needs_inputs(self):
        """Fails if the transform dispatch in view.schema.json is dropped."""
        view = layout_transform_view()
        view["data"] = field()["data"]
        del view["inputs"]
        assert view_errors(view) == {("required", "")}

    def test_template_positions_name_their_montage(self):
        view = layout_transform_view()
        view["transform"]["parameters"] = {
            "coordinate_system": "n/a",
            "montage": "GSN-HydroCel-32",
        }
        assert view_errors(view) == set()

    def test_a_montage_goes_with_n_a(self):
        """Fails if the montage's dependent rule is dropped."""
        view = layout_transform_view()
        view["transform"]["parameters"]["montage"] = "GSN-HydroCel-32"
        assert view_errors(view) == {
            ("const", "transform/parameters/coordinate_system")
        }

    @pytest.mark.parametrize("montage", ["", "-x", "a/b", "GSN\n"])
    def test_montage_pattern(self, montage):
        view = layout_transform_view()
        parameters = {"coordinate_system": "n/a", "montage": montage}
        view["transform"]["parameters"] = parameters
        assert view_errors(view) == {("pattern", "transform/parameters/montage")}

    def test_stored_positions_in_any_kind(self):
        """The stored form holds for a kind neuroschema does not know: the role
        names the frame, so no parameters and no positions input."""
        view = layout_transform_view()
        view["data"] = [positions_entry()]
        del view["inputs"]
        view["transform"]["parameters"] = {}
        assert view_errors(view) == set()
        view["inputs"] = layout_transform_view()["inputs"]
        assert view_errors(view) == {("not", "inputs")}
        del view["inputs"]
        view["transform"]["parameters"] = {"coordinate_system": "CapTrak"}
        assert view_errors(view) == {("maxProperties", "transform/parameters")}

    def test_another_transform_is_not_checked_here(self):
        view = layout_transform_view()
        view["transform"] = {"name": "acme.layout.v2", "parameters": {"any": 1}}
        assert view_errors(view) == set()


# ── The registry: transforms, the new kind and algorithm ───────────────────

TRANSFORM_FILE = re.compile(
    r"^transform\.(?P<name>[a-z][a-z0-9]*(?:\.[a-z][a-z0-9-]*)+\.v[1-9][0-9]*)"
    r"\.schema\.json$"
)


def _transform_dispatch() -> dict[str, str]:
    """The transform name -> $ref pairs view.schema.json checks."""
    view = json.loads(VIEW_SCHEMA.read_text())["$defs"]["view"]
    pairs = {}
    for rule in view["allOf"]:
        props = rule["if"].get("properties", {})
        if "transform" in props:
            name = props["transform"]["properties"]["name"]["const"]
            assert name not in pairs, name
            pairs[name] = rule["then"]["$ref"]
    return pairs


def _required_dims(dims: dict) -> set[str]:
    """Dimension names a dims subschema requires with contains (here or in allOf)."""
    names = set()
    for clause in [dims, *dims.get("allOf", [])]:
        name = clause.get("contains", {}).get("properties", {}).get("name", {})
        if "const" in name and clause.get("minContains", 1) > 0:
            names.add(name["const"])
    return names


class TestRegistry:
    def test_transform_files_and_registry_match_one_to_one(self):
        files = sorted(p.name for p in VIEWS.glob("transform.*.schema.json"))
        listed = sorted(Path(t["schema"]).name for t in REGISTRY["transforms"])
        assert files == listed
        assert "transform.nemar.sensor-layout.v1.schema.json" in files

    def test_each_transform_file_is_named_for_its_transform(self):
        for entry in REGISTRY["transforms"]:
            path = ROOT / entry["schema"]
            match = TRANSFORM_FILE.match(path.name)
            assert match, path.name
            assert match["name"] == entry["name"]
            assert json.loads(path.read_text())["$id"] == path.name

    def test_view_schema_checks_exactly_the_registered_transforms(self):
        dispatch = _transform_dispatch()
        assert set(dispatch) == {t["name"] for t in REGISTRY["transforms"]}
        for name, ref in dispatch.items():
            assert ref == f"../views/transform.{name}.schema.json"

    def test_sensor_field_kind_and_algorithm(self):
        assert FIELD["schema"] == "schema/views/kind.nemar.sensor-field.v1.schema.json"
        assert FIELD["base"] is None
        assert set(FIELD["roles"]) == {"values", "layout", "positions"}
        assert FIELD["roles"]["values"]["dims"] is None, "open names"
        assert FIELD["roles"]["layout"]["dims"] == ["sensor"]
        assert FIELD["roles"]["positions"]["dims"] == ["sensor"]
        algorithms = {a["name"]: a for a in REGISTRY["algorithms"]}
        assert algorithms["nemar.sensor-field.v1"] == {
            "name": "nemar.sensor-field.v1",
            "spec": "docs/views/sensor-field.md",
            "vectors": "views/vectors/sensor-field.v1.json",
        }

    def test_dims_a_schema_requires_are_dims_the_registry_allows(self):
        """The registry lists the dims a role may carry (null: any name); the
        kind's schema says which it must carry, with contains. A required name
        the registry does not allow would make the role unwritable."""
        for entry in REGISTRY["kinds"]:
            for role, branch in role_schemas(entry).items():
                allowed = entry["roles"][role]["dims"]
                required = _required_dims(branch["properties"].get("dims", {}))
                if allowed is not None:
                    assert required <= set(allowed), (entry["kind"], role)
        assert _required_dims(role_schemas(FIELD)["values"]["properties"]["dims"]) == {
            "sensor"
        }

    def test_sensor_meaning(self):
        assert REGISTRY["reserved_dims"]["sensor"]["meaning"] == (
            "A sensor, by its name; with a layout or positions role, that role's "
            "name column in row order; with neither, names placed by "
            "nemar.sensor-labels.v1."
        )


# ── The role contract: an optional role ────────────────────────────────────


TABLE = known_kinds(REGISTRY)[("nemar.table", 1)]


def preset(view: dict) -> dict:
    """An unknown kind drawn over the base nemar.sensor-field version 1."""
    return view | {
        "kind": "acme.ic-maps",
        "kind_version": 3,
        "base": "nemar.sensor-field",
        "base_version": 1,
    }


class TestOptionalRole:
    def test_optional_roles(self):
        assert optional_roles(FIELD) == {"layout", "positions"}
        assert optional_roles(TABLE) == set()

    @pytest.mark.parametrize("layout", [True, False])
    def test_a_preset_draws_as_its_base_with_or_without_a_layout(self, layout):
        """Fails if every admitted role is treated as required."""
        view = preset(field(layout=layout))
        assert meets_role_contract(view, FIELD)
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.sensor-field", 1)

    def test_a_preset_role_the_base_does_not_admit_is_ignored(self):
        view = preset(field())
        components = layout_entry() | {"role": "components", "sha256": "c" * 64}
        view["data"].append(components)
        assert draw_as(view, REGISTRY) == Drawing("base", "nemar.sensor-field", 1)

    def test_an_optional_role_twice_misses_the_contract(self):
        view = preset(field())
        view["data"].append(layout_entry())
        assert not meets_role_contract(view, FIELD)
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    def test_a_required_role_missing_misses_the_contract(self):
        view = preset(field())
        del view["data"][0]
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    def test_a_rule_across_roles_is_part_of_the_contract(self):
        """Fails if the contract checks each entry alone, not the data as a whole:
        each entry is valid on its own, but with a layout present the values'
        sensors must come from it."""
        view = preset(field())
        values = view["data"][0]
        values["columns"].insert(0, {"name": "channel", "type": "string"})
        values["dims"][0]["coords"] = {"column": "channel"}
        _schema, resolver = load_schema(KIND)
        for entry in view["data"]:
            branch = role_schemas(FIELD)[entry["role"]]
            assert Draft202012Validator(branch, resolver=resolver).is_valid(entry)
        assert draw_as(view, REGISTRY) == Drawing("table", None, None)

    def test_a_role_twice_misses_the_contract_whatever_the_schema_says(self, tmp_path):
        """Roles are unique within a view: the contract counts them itself, so
        a kind schema that does not bound a role's count cannot admit two."""
        schema = json.loads(KIND.read_text())
        del schema["properties"]["data"]["allOf"][1]["maxContains"]
        path = tmp_path / KIND.name
        path.write_text(json.dumps(schema))
        entry = FIELD | {"schema": str(path)}
        view = preset(field())
        assert meets_role_contract(view, entry)
        view["data"].append(layout_entry())
        assert not meets_role_contract(view, entry)

    def test_a_contains_clause_without_min_contains_zero_is_not_optional(
        self, tmp_path
    ):
        schema = json.loads(KIND.read_text())
        schema["properties"]["data"]["allOf"][1]["minContains"] = 1
        path = tmp_path / KIND.name
        path.write_text(json.dumps(schema))
        entry = FIELD | {"schema": str(path)}
        assert optional_roles(entry) == {"positions"}
        assert not meets_role_contract(preset(field(layout=False)), entry)
