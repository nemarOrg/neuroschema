"""The presets nemar.spectrum, nemar.ic-maps, nemar.ic-classes, nemar.ic-activity
and nemar.signal-window (version 1), and the content nemar.ic-classes.v1.

Real schemas, registry, example and verdict corpus; no mocks. Failures are
asserted as (validator, path) pairs, and a constraint inside a role's branch
is checked against that branch, so a negative test cannot pass for the wrong
reason.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema
from neuroschema.views import (
    Drawing,
    build_model,
    draw_as,
    draw_by_base,
    known_kinds,
    load_registry,
    meets_role_contract,
    optional_roles,
    role_schemas,
)
from neuroschema.views.models import content_validator, histogram_content_validator
from tests.helpers import failures

ROOT = Path(__file__).resolve().parent.parent
VIEWS = ROOT / "schema" / "views"
VIEW_SCHEMA = ROOT / "schema" / "definitions" / "view.schema.json"
REGISTRY = load_registry()
KINDS = known_kinds(REGISTRY)
EXAMPLE = ROOT / "examples" / "views" / "dataquality-record-nemar-ica.json"
VERDICTS = json.loads(
    (ROOT / "views" / "vectors" / "kinds-verdicts.v1.json").read_text()
)
IC_CLASSES = "content.nemar.ic-classes.v1.schema.json"

BASES = {
    "nemar.spectrum": "nemar.lines",
    "nemar.ic-maps": "nemar.sensor-field",
    "nemar.ic-classes": "nemar.histogram",
    "nemar.ic-activity": "nemar.lines",
    "nemar.signal-window": "nemar.lines",
}
STORED = ["nemar.spectrum", "nemar.ic-maps", "nemar.ic-classes"]
COMPUTED = ["nemar.ic-activity", "nemar.signal-window"]
# The registry as a renderer that knows only the generic kinds has it.
GENERIC_ONLY = REGISTRY | {"kinds": [k for k in REGISTRY["kinds"] if k["base"] is None]}


def example_views() -> dict[str, dict]:
    document = json.loads(EXAMPLE.read_text())
    return {v["key"]: v for v in document["recipes"]["nemar-ica"]["views"]}


def view(key: str) -> dict:
    return copy.deepcopy(example_views()[key])


def view_errors(instance) -> set[tuple[str, str]]:
    _schema, resolver = load_schema(VIEW_SCHEMA)
    validator = Draft202012Validator(
        {"$ref": f"file://{VIEW_SCHEMA}#/$defs/view"}, resolver=resolver
    )
    return failures(validator.iter_errors(instance))


def role_errors(kind: str, entry: dict) -> set[tuple[str, str]]:
    """Failures of one data entry against the preset's branch for its role."""
    path = VIEWS / f"kind.{kind}.v1.schema.json"
    _schema, resolver = load_schema(path)
    branch = role_schemas(KINDS[(kind, 1)])[entry["role"]]
    return failures(Draft202012Validator(branch, resolver=resolver).iter_errors(entry))


def _pointer(document: dict, pointer: str):
    node = document
    for part in pointer.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


# ── The registry and the bases ─────────────────────────────────────────────


class TestRegistry:
    def test_the_presets_and_their_bases(self):
        presets = {e["kind"]: e["base"] for e in REGISTRY["kinds"] if e["base"]}
        assert presets == BASES
        for kind in BASES:
            assert KINDS[(kind, 1)]["base_version"] == 1

    @pytest.mark.parametrize("kind", list(BASES))
    def test_each_preset_schema_fixes_its_base(self, kind):
        schema = json.loads((VIEWS / f"kind.{kind}.v1.schema.json").read_text())
        assert {"base", "base_version"} <= set(schema["required"])
        assert schema["properties"]["base"]["const"] == BASES[kind]
        assert schema["properties"]["base_version"]["const"] == 1

    @pytest.mark.parametrize("kind", STORED)
    def test_each_role_the_base_reads_takes_the_base_subschema(self, kind):
        """A preset's branch for a role its base admits refers to the base's
        branch for that role, so each entry meets the base's subschema."""
        base = KINDS[(BASES[kind], 1)]
        base_schema = json.loads((ROOT / base["schema"]).read_text())
        base_roles = role_schemas(base)
        shared = set(role_schemas(KINDS[(kind, 1)])) & set(base_roles)
        assert shared == set(base_roles) - {"positions"}
        for role in shared:
            branch = role_schemas(KINDS[(kind, 1)])[role]
            (ref,) = [part["$ref"] for part in branch["allOf"] if "$ref" in part]
            file, pointer = ref.split("#")
            assert file == f"../views/kind.{BASES[kind]}.v1.schema.json"
            assert _pointer(base_schema, pointer) == base_roles[role]

    @pytest.mark.parametrize("kind", COMPUTED)
    def test_a_computed_preset_has_no_data_roles(self, kind):
        entry = KINDS[(kind, 1)]
        assert entry["roles"] == {} and role_schemas(entry) == {}
        schema = json.loads((ROOT / entry["schema"]).read_text())
        assert schema["properties"]["data"] == {
            "not": {},
            "description": schema["properties"]["data"]["description"],
        }
        assert "signal" in entry["inputs"]

    def test_optional_roles(self):
        assert optional_roles(KINDS[("nemar.spectrum", 1)]) == {"layout"}
        assert optional_roles(KINDS[("nemar.ic-maps", 1)]) == set()
        assert optional_roles(KINDS[("nemar.ic-classes", 1)]) == set()

    def test_the_ic_classes_role_names_its_content(self):
        role = KINDS[("nemar.ic-classes", 1)]["roles"]["histogram"]
        assert role["content"] == f"schema/views/{IC_CLASSES}"
        kind = json.loads((VIEWS / "kind.nemar.ic-classes.v1.schema.json").read_text())
        assert kind["$defs"]["content"]["$ref"] == f"../views/{IC_CLASSES}"


# ── The example and the renderer rule ──────────────────────────────────────


class TestExample:
    def test_one_view_of_each_preset(self):
        kinds = sorted(v["kind"] for v in example_views().values())
        assert kinds == sorted(BASES)

    @pytest.mark.parametrize("key", list(example_views()))
    def test_each_view_is_valid(self, key):
        assert view_errors(view(key)) == set()

    @pytest.mark.parametrize("key", list(example_views()))
    def test_a_renderer_that_knows_the_preset_draws_it(self, key):
        instance = view(key)
        assert draw_as(instance, REGISTRY) == Drawing("kind", instance["kind"], 1)

    @pytest.mark.parametrize("key", list(example_views()))
    def test_a_renderer_that_knows_only_the_bases(self, key):
        """A stored preset draws by its base; a computed one shows as a table."""
        instance = view(key)
        drawing = draw_as(instance, GENERIC_ONLY)
        if instance["kind"] in STORED:
            assert drawing == Drawing("base", BASES[instance["kind"]], 1)
        else:
            assert drawing == Drawing("table", None, None)
        assert draw_by_base(instance, REGISTRY) == drawing

    def test_every_valid_stored_preset_in_the_corpus_meets_its_base_contract(self):
        """Fails if a preset schema admits data its base would refuse."""
        checked = []
        for case in VERDICTS["cases"]:
            instance = case["instance"]
            if case["schema"] != "view" or not case["valid"]:
                continue
            if instance.get("kind") in STORED:
                base = KINDS[(BASES[instance["kind"]], 1)]
                assert meets_role_contract(instance, base), case["name"]
                checked.append(instance["kind"])
        assert sorted(set(checked)) == sorted(STORED)


# ── nemar.spectrum ─────────────────────────────────────────────────────────


def bare_spectrum() -> dict:
    """The example's spectrum without its layout: sensors by header name."""
    out = view("spectrum")
    out["data"] = out["data"][:1]
    out["data"][0]["dims"][1]["coords"] = {"header": True}
    return out


class TestSpectrum:
    def test_without_a_layout_the_sensors_are_header_names(self):
        assert view_errors(bare_spectrum()) == set()
        assert draw_as(bare_spectrum(), GENERIC_ONLY) == Drawing(
            "base", "nemar.lines", 1
        )

    @pytest.mark.parametrize("unit", ["kHz", "hz", None])
    def test_the_freq_dimension_is_in_hertz(self, unit):
        """Only the unit changes, so the failing contains clause is freq's."""
        instance = view("spectrum")
        freq = instance["data"][0]["dims"][0]
        if unit is None:
            del freq["unit"]
        else:
            freq["unit"] = unit
        assert view_errors(instance) == {("oneOf", "data/0")}
        assert role_errors("nemar.spectrum", instance["data"][0]) == {
            ("contains", "dims")
        }

    def test_the_freq_column_is_in_hertz_and_sensors_in_decibels(self):
        instance = view("spectrum")
        instance["data"][0]["columns"][2]["unit"] = "uV^2/Hz"
        assert role_errors("nemar.spectrum", instance["data"][0]) == {
            ("const", "columns/2/unit")
        }
        instance = view("spectrum")
        del instance["data"][0]["columns"][0]["unit"]
        assert role_errors("nemar.spectrum", instance["data"][0]) == {
            ("required", "columns/0")
        }

    @pytest.mark.parametrize(
        "name", ["upper_hz", "method", "window", "window_s", "overlap", "unit"]
    )
    def test_each_recorded_parameter_is_required(self, name):
        instance = view("spectrum")
        del instance["parameters"][name]
        assert view_errors(instance) == {("required", "parameters")}

    @pytest.mark.parametrize(
        ("name", "value", "validator"),
        [
            ("upper_hz", 0, "exclusiveMinimum"),
            ("window_s", 0, "exclusiveMinimum"),
            ("overlap", 1, "exclusiveMaximum"),
            ("overlap", -0.1, "minimum"),
            ("unit", "uV^2/Hz", "const"),
            ("method", "multitaper", "const"),
            ("window", "Hamming", "pattern"),
            ("initial_maps_hz", [10, 10], "uniqueItems"),
            ("smoothing", 3, "additionalProperties"),
        ],
    )
    def test_parameter_bounds(self, name, value, validator):
        instance = view("spectrum")
        instance["parameters"][name] = value
        where = (
            "parameters"
            if validator == "additionalProperties"
            else f"parameters/{name}"
        )
        assert view_errors(instance) == {(validator, where)}

    def test_with_a_layout_the_sensors_are_its_rows(self):
        instance = view("spectrum")
        instance["data"][0]["dims"][1]["coords"] = {"header": True}
        assert view_errors(instance) == {("required", "data/0/dims/1/coords")}

    def test_without_a_layout_sensors_from_one_are_refused(self):
        instance = bare_spectrum()
        instance["data"][0]["dims"][1]["coords"] = {"role": "layout", "column": "name"}
        assert view_errors(instance) == {("required", "data/0/dims/1/coords")}

    @pytest.mark.parametrize("field", ["coordinate_system", "columns"])
    def test_the_layout_is_a_sensor_field_layout(self, field):
        """The layout branch takes nemar.sensor-field's, which spectrum's base
        (nemar.lines) does not read; without it any TSV would pass as a layout."""
        instance = view("spectrum")
        layout = instance["data"][1]
        if field == "columns":
            layout["columns"] = layout["columns"][:1]
        else:
            del layout[field]
        assert view_errors(instance) == {("oneOf", "data/1")}
        assert role_errors("nemar.spectrum", layout)

    def test_a_spectrum_is_stored_data_only(self):
        instance = view("spectrum")
        instance["inputs"] = view("icactivity")["inputs"][:1]
        assert ("not", "inputs") in view_errors(instance)


# ── nemar.ic-maps ──────────────────────────────────────────────────────────


class TestIcMaps:
    def test_the_layout_is_required(self):
        instance = view("icmaps")
        del instance["data"][1]
        assert view_errors(instance) == {("contains", "data")}

    def test_the_components_table_is_required(self):
        instance = view("icmaps")
        del instance["data"][2]
        assert view_errors(instance) == {("contains", "data")}

    def test_positions_in_place_of_the_layout_are_refused(self):
        instance = view("icmaps")
        layout = instance["data"][1]
        layout.update(role="positions")
        assert ("oneOf", "data/1") in view_errors(instance)

    def test_the_sensors_are_the_layout_rows(self):
        instance = view("icmaps")
        instance["data"][0]["dims"][0]["coords"] = {"column": "IC001"}
        assert role_errors("nemar.ic-maps", instance["data"][0]) == {
            ("contains", "dims")
        }

    def test_the_components_table_names_its_rows(self):
        instance = view("icmaps")
        table = instance["data"][2]
        table["dims"][0]["coords"] = {"column": "variance_pct"}
        assert role_errors("nemar.ic-maps", table) == {
            ("const", "dims/0/coords/column")
        }
        table = view("icmaps")["data"][2]
        table["columns"] = table["columns"][1:]
        assert role_errors("nemar.ic-maps", table) == {("contains", "columns")}

    def test_no_parameters(self):
        instance = view("icmaps")
        instance["parameters"] = {"limits": "minmax"}
        assert view_errors(instance) == {("maxProperties", "parameters")}


# ── nemar.ic-classes and its content ───────────────────────────────────────


# The browser_transform members a decomposition of the archive writes.
LABEL_MATCH = {
    "applies_to": (
        "serving_copy channels matched by label, in microvolts: the view converts "
        "by the store's unit field and refuses an unknown unit or any channel it "
        "cannot match"
    ),
    "match": "label",
    "rows": None,
    "unit": "uV",
    "caption": "not checked against the decomposition input",
}

CONTENT = {
    "classifier": "ICLabel",
    "categories": [
        "Brain",
        "Muscle",
        "Eye",
        "Heart",
        "Line Noise",
        "Channel Noise",
        "Other",
    ],
    "counts": [12, 3, 2, 0, 1, 0, 4],
    "summed_variance_pct": [61.25, 9.5, 14.75, 0, 0.5, 0, 6.125],
    "n_components": 22,
}


class TestIcClasses:
    def test_one_json_file(self):
        instance = view("icclasses")
        instance["data"][0].update(format="tsv")
        instance["data"][0]["location"] = instance["data"][0]["location"][:-4] + "tsv"
        assert view_errors(instance) == {("const", "data/0/format")}

    def test_the_content_is_a_histogram_content_by_category(self):
        assert content_validator(IC_CLASSES).is_valid(CONTENT)
        assert histogram_content_validator().is_valid(CONTENT)

    @pytest.mark.parametrize(
        "member", ["classifier", "summed_variance_pct", "n_components"]
    )
    def test_the_presets_members_are_required(self, member):
        content = {k: v for k, v in CONTENT.items() if k != member}
        assert failures(content_validator(IC_CLASSES).iter_errors(content)) == {
            ("required", "")
        }

    @pytest.mark.parametrize(
        "categories",
        [
            ["Muscle", "Brain", "Eye", "Heart", "Line Noise", "Channel Noise", "Other"],
            ["Brain", "Muscle", "Eye", "Heart", "Line noise", "Channel Noise", "Other"],
            ["Brain", "Muscle", "Eye", "Heart", "Line Noise", "Channel Noise"],
        ],
        ids=["order", "spelling", "six"],
    )
    def test_iclabel_fixes_its_seven_classes(self, categories):
        content = CONTENT | {"categories": categories}
        content["counts"] = content["counts"][: len(categories)]
        content["summed_variance_pct"] = content["summed_variance_pct"][
            : len(categories)
        ]
        assert failures(content_validator(IC_CLASSES).iter_errors(content)) == {
            ("const", "categories")
        }

    def test_another_classifier_names_its_own_classes(self):
        content = CONTENT | {
            "classifier": "MARA",
            "categories": ["Artifact", "Brain"],
            "counts": [4, 18],
            "summed_variance_pct": [20.5, 79.5],
        }
        assert content_validator(IC_CLASSES).is_valid(content)

    @pytest.mark.parametrize(
        "name",
        [
            " ICLabel",
            "ICLabel ",
            "MARA\t",
            "",
            "IC\u200bLabel",
            "ICLabel\u200d",
            "\ufeffICLabel",
            "IC\u00adLabel",
            "IC\u00a0Label",
            "ICLabel\U000e0041",
            "\u3000MARA",
        ],
        ids=[
            "leading-space",
            "trailing-space",
            "tab",
            "empty",
            "zero-width-space",
            "zero-width-joiner",
            "byte-order-mark",
            "soft-hyphen",
            "inner-no-break-space",
            "tag-character",
            "ideographic-space",
        ],
    )
    def test_the_classifier_has_no_format_or_edge_white_space(self, name):
        content = CONTENT | {"classifier": name}
        errors = failures(content_validator(IC_CLASSES).iter_errors(content))
        assert ("pattern", "classifier") in errors

    def test_the_classifier_class_holds_every_format_and_space_character(self):
        """The explicit class refuses every Cf character and every character
        Python or JavaScript counts as white space, at the edges; inside, all
        but the space."""
        import re
        import unicodedata

        pattern = json.loads((VIEWS / IC_CLASSES).read_text())["properties"][
            "classifier"
        ]["pattern"]
        regex = re.compile(pattern)
        js_space = {0xFEFF}
        for code in range(0x110000):
            char = chr(code)
            if 0xD800 <= code <= 0xDFFF:
                continue
            fmt = unicodedata.category(char) == "Cf"
            space = char.isspace() or code in js_space
            if fmt or space:
                assert not regex.search(char + "x"), hex(code)
                assert not regex.search("x" + char), hex(code)
            if fmt or (space and code != 0x20):
                assert not regex.search("a" + char + "b"), hex(code)
        assert regex.search("MARA v2")

    @pytest.mark.parametrize("name", ["iclabel", "ICLABEL", "IcLabel"])
    def test_iclabel_is_spelled_iclabel(self, name):
        content = CONTENT | {"classifier": name}
        assert failures(content_validator(IC_CLASSES).iter_errors(content)) == {
            ("const", "classifier")
        }

    def test_classes_are_categories_not_edges(self):
        content = {
            "edges": [0, 1],
            "counts": [1],
            "underflow": 0,
            "overflow": 0,
            "summed_variance_pct": [1.0],
            "n_components": 1,
        }
        assert failures(content_validator(IC_CLASSES).iter_errors(content)) == {
            ("required", "")
        }

    def test_the_example_content_draws_as_a_histogram_by_its_base(self):
        """The reference has no preset model, so it draws a preset by its base."""
        data = (json.dumps(CONTENT, indent=1) + "\n").encode()
        instance = view("icclasses")
        instance["data"][0].update(
            size=len(data), sha256=hashlib.sha256(data).hexdigest()
        )
        model = build_model(instance, {instance["data"][0]["location"]: data})
        assert model["drawing"] == {
            "via": "base",
            "kind": "nemar.histogram",
            "kind_version": 1,
        }
        assert [item["count"] for item in model["model"]["items"]] == CONTENT["counts"]


# ── nemar.ic-activity and nemar.signal-window ──────────────────────────────


class TestComputedPresets:
    def test_the_activity_transform_is_required(self):
        instance = view("icactivity")
        del instance["transform"]
        assert view_errors(instance) == {("required", "")}

    def test_activations_are_never_stored(self):
        instance = view("icactivity")
        instance["data"] = view("icclasses")["data"]
        assert ("not", "data") in view_errors(instance)

    @pytest.mark.parametrize("role", ["unmixing", "signal", "components"])
    def test_the_transform_reads_each_of_its_inputs_once(self, role):
        instance = view("icactivity")
        instance["inputs"] = [i for i in instance["inputs"] if i["role"] != role]
        assert ("contains", "inputs") in view_errors(instance)

    def test_badsegments_is_optional(self):
        instance = view("icactivity")
        instance["inputs"] = [
            i for i in instance["inputs"] if i["role"] != "badsegments"
        ]
        assert view_errors(instance) == set()

    @pytest.mark.parametrize(
        "member", ["channel_types", "channel_types_sha256", "channels", "reference"]
    )
    def test_the_decomposition_input_states_what_the_record_does(self, member):
        instance = view("icactivity")
        del instance["parameters"]["decomposition_input"][member]
        assert view_errors(instance) == {("required", "parameters/decomposition_input")}

    @pytest.mark.parametrize(
        "member",
        ["matrix", "applies_to", "note", "columns", "caption", "shaded", "unit"],
    )
    def test_the_browser_transform_block_is_whole(self, member):
        instance = view("icactivity")
        del instance["transform"]["parameters"][member]
        assert view_errors(instance) == {("required", "transform/parameters")}

    @pytest.mark.parametrize(
        ("row", "validator"),
        [(["Fp1"], "minItems"), (["Fp1", "EEG", "extra"], "maxItems")],
    )
    def test_each_channel_type_row_is_a_pair(self, row, validator):
        instance = view("icactivity")
        instance["parameters"]["decomposition_input"]["channel_types"][0] = row
        assert view_errors(instance) == {
            (validator, "parameters/decomposition_input/channel_types/0")
        }

    def test_label_matching_names_null_rows(self):
        instance = view("icactivity")
        signal = instance["inputs"][1]["store"]
        signal.update(profile="archive", content_sha256=None)
        given = instance["parameters"]["decomposition_input"]
        given["source"] = "archive"
        del given["store"]
        instance["transform"]["parameters"] |= LABEL_MATCH | {"rows": [0, 1]}
        assert view_errors(instance) == {("type", "transform/parameters/rows")}

    def test_the_shaded_spans_are_closed(self):
        instance = view("icactivity")
        instance["transform"]["parameters"]["shaded"]["reason"] = "asr_burst_rejection"
        assert view_errors(instance) == {
            ("additionalProperties", "transform/parameters/shaded")
        }

    def test_rows_go_with_store_row(self):
        instance = view("icactivity")
        del instance["transform"]["parameters"]["rows"]
        assert view_errors(instance) == {("required", "transform/parameters")}

    def test_an_archive_decomposition_matches_by_label(self):
        instance = view("icactivity")
        signal = next(i for i in instance["inputs"] if i["role"] == "signal")
        signal["store"].update(profile="archive", content_sha256=None)
        given = instance["parameters"]["decomposition_input"]
        given["source"] = "archive"
        del given["store"]
        assert view_errors(instance) == {("const", "transform/parameters/match")}
        instance["transform"]["parameters"] |= LABEL_MATCH
        assert view_errors(instance) == set()

    def test_the_decomposition_and_the_signal_name_one_profile(self):
        instance = view("icactivity")
        given = instance["parameters"]["decomposition_input"]
        given["source"] = "archive"
        del given["store"]
        assert view_errors(instance) == {("const", "inputs/1/store/profile")}

    def test_a_serving_decomposition_names_its_store(self):
        instance = view("icactivity")
        del instance["parameters"]["decomposition_input"]["store"]
        assert view_errors(instance) == {("required", "parameters/decomposition_input")}

    @pytest.mark.parametrize("unit", ["V", "mV", "uV", "µV", "μV"])
    def test_the_matrix_units(self, unit):
        instance = view("icactivity")
        instance["transform"]["parameters"]["unit"] = unit
        assert view_errors(instance) == set()

    def test_the_display_filter_is_of_order_two(self):
        instance = view("icactivity")
        instance["parameters"]["display_filter"]["order"] = 4
        assert view_errors(instance) == {("const", "parameters/display_filter/order")}

    def test_the_window_is_at_most_30_seconds(self):
        instance = view("icactivity")
        instance["parameters"]["max_window_s"] = 30.5
        assert view_errors(instance) == {("maximum", "parameters/max_window_s")}
        instance = view("midsegment")
        instance["parameters"]["duration_s"] = 30.5
        assert view_errors(instance) == {("maximum", "parameters/duration_s")}

    def test_the_signal_window_reads_only_its_inputs(self):
        instance = view("midsegment")
        instance["inputs"].append(view("icactivity")["inputs"][0])
        assert view_errors(instance) == {("oneOf", "inputs/3")}

    def test_the_bad_segments_are_a_tsv_file_once(self):
        instance = view("icactivity")
        segments = instance["inputs"][3]
        assert segments["role"] == "badsegments"
        instance["inputs"].append(copy.deepcopy(segments))
        assert view_errors(instance) == {("maxContains", "inputs")}
        instance = view("icactivity")
        location = instance["inputs"][3]["file"]["location"]
        instance["inputs"][3]["file"]["location"] = location[:-3] + "json"
        assert view_errors(instance) == {("oneOf", "inputs/3")}

    def test_the_decomposition_input_is_closed(self):
        instance = view("icactivity")
        instance["parameters"]["decomposition_input"]["asr"] = False
        assert view_errors(instance) == {
            ("additionalProperties", "parameters/decomposition_input")
        }

    def test_a_serving_decomposition_reads_a_serving_store(self):
        instance = view("icactivity")
        instance["inputs"][1]["store"]["profile"] = "archive"
        instance["transform"]["parameters"] |= LABEL_MATCH
        assert view_errors(instance) == {("const", "inputs/1/store/profile")}


def transform_view() -> dict:
    """A kind neuroschema does not know, computed by nemar.ic-activity.v1, so
    only the envelope and the transform's schema apply."""
    instance = view("icactivity")
    for name in ("base", "base_version", "parameters"):
        del instance[name]
    return instance | {"kind": "acme.activity", "kind_version": 2}


class TestTransform:
    def test_any_kind_may_name_it(self):
        assert view_errors(transform_view()) == set()

    @pytest.mark.parametrize(("at", "role"), [(0, "unmixing"), (2, "components")])
    def test_the_matrix_and_the_components_are_tsv_files(self, at, role):
        instance = transform_view()
        assert instance["inputs"][at]["role"] == role
        location = instance["inputs"][at]["file"]["location"]
        instance["inputs"][at]["file"]["location"] = location[:-3] + "json"
        assert view_errors(instance) == {("pattern", f"inputs/{at}/file/location")}

    def test_each_input_once(self):
        instance = transform_view()
        instance["inputs"].append(copy.deepcopy(instance["inputs"][2]))
        assert view_errors(instance) == {("maxContains", "inputs")}

    def test_the_signal_is_a_store(self):
        instance = transform_view()
        instance["inputs"][1] = {
            "role": "signal",
            "file": instance["inputs"][0]["file"],
        }
        assert view_errors(instance) == {("required", "inputs/1")}

    def test_the_match_is_required(self):
        """Without match, rows must be null (the label branch), so the error
        that names the missing match is the required one."""
        instance = transform_view()
        del instance["transform"]["parameters"]["match"]
        instance["transform"]["parameters"]["rows"] = None
        assert view_errors(instance) == {("required", "transform/parameters")}

    def test_rows_are_distinct(self):
        instance = transform_view()
        instance["transform"]["parameters"]["rows"] = [0, 0, 1, 2, 3, 4, 5]
        assert view_errors(instance) == {("anyOf", "transform/parameters/rows")}
        instance["transform"]["parameters"]["rows"] = [0, 1, 2, 3, 4, 5, 6]
        assert view_errors(instance) == set()

    def test_columns_are_distinct(self):
        instance = transform_view()
        columns = instance["transform"]["parameters"]["columns"]
        instance["transform"]["parameters"]["columns"] = [columns[0], *columns[:-1]]
        assert view_errors(instance) == {
            ("uniqueItems", "transform/parameters/columns")
        }

    def test_the_parameters_are_closed(self):
        instance = transform_view()
        instance["transform"]["parameters"]["highpass_hz"] = 1
        assert view_errors(instance) == {
            ("additionalProperties", "transform/parameters")
        }

    def test_build_model_shows_a_computed_preset_as_its_downloads(self):
        """No stored data to draw: the fallback offers every file input."""
        instance = view("icactivity")
        model = build_model(instance, {})
        assert model["drawing"] == {"via": "table", "kind": None, "kind_version": None}
        assert model["model"] == {"type": "fallback", "tables": []}
        assert [d["role"] for d in model["downloads"]] == [
            "unmixing",
            "components",
            "badsegments",
        ]

    def test_build_model_names_a_base_it_has_no_model_for(self):
        with pytest.raises(LookupError, match=r"nemar\.sensor-field"):
            build_model(view("icmaps"), {})
