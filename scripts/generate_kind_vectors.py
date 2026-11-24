"""Write the generic-kind, preset-check and verdict vectors from the cases here.

Writes ``views/vectors/kinds-models.v1.json`` (each case's model, from the
Python reference ``neuroschema.views.build_model``),
``views/vectors/preset-checks.v1.json`` (each preset case's outcome, from
``neuroschema.views.presets.check_preset``) and
``views/vectors/kinds-verdicts.v1.json`` (each instance's verdict, from
jsonschema, on the binary64 reading). ``docs/views/generic-kinds.md`` and
``docs/views/presets.md`` say how a renderer replays them.

Usage::

    uv run python scripts/generate_kind_vectors.py           # write the three files
    uv run python scripts/generate_kind_vectors.py --check   # fail if any differs
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

from neuroschema.ijson import FORBIDDEN
from neuroschema.views import load_registry
from neuroschema.views.models import (
    MODELS_FORMAT,
    ViewRefused,
    build_model,
    content_validator,
    data_quality_validator,
    histogram_content_validator,
    locate_bin,
    snap_row,
    view_validator,
)
from neuroschema.views.presets import PRESET_CHECKS_FORMAT, check_preset

ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = ROOT / "views" / "vectors" / "kinds-models.v1.json"
VERDICTS_PATH = ROOT / "views" / "vectors" / "kinds-verdicts.v1.json"
VERDICTS_FORMAT = "nemar.kinds-verdicts.v1"
PRESET_CHECKS_PATH = ROOT / "views" / "vectors" / "preset-checks.v1.json"
SPEC = "docs/views/generic-kinds.md"
HISTOGRAM_CONTENT = "content.nemar.histogram.v1.schema.json"
IC_CLASSES_CONTENT = "content.nemar.ic-classes.v1.schema.json"
PRESET_EXAMPLE = ROOT / "examples" / "views" / "dataquality-record-nemar-ica.json"

PLUGIN = {"plugin": {"name": "nemar-quality", "version": "0.1.0"}}
RECIPE = {"recipe": {"name": "nemar-ica", "version": "1.0.0"}}
PREFIX = "sub-01/eeg/sub-01_task-rest_desc-nemarica"
REGISTRY = load_registry()
HUGE = "1" + "0" * 400  # an integer literal beyond binary64 range


# ── Building declarations and files ───────────────────────────────────────


def tsv(*rows: str) -> bytes:
    """A TSV file from rows whose cells are separated by single spaces."""
    return "".join(row.replace(" ", "\t") + "\n" for row in rows).encode()


def data_entry(role: str, location: str, data: bytes, **fields) -> dict:
    """One data entry, with the size and SHA-256 of the bytes."""
    return {
        "role": role,
        "location": location,
        "format": location.rsplit(".", 1)[1],
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    } | fields


def col(name: str, kind: str = "number", unit: str | None = None) -> dict:
    return {"name": name, "type": kind} | ({"unit": unit} if unit else {})


def dim(name: str, axis: str, kind: str, coords: dict, unit: str | None = None):
    fields = {"name": name, "axis": axis, "type": kind}
    return fields | ({"unit": unit} if unit else {}) | {"coords": coords}


def view(key: str, kind: str, caption: str, data: list, **fields) -> dict:
    return (
        {
            "key": key,
            "kind": kind,
            "kind_version": 1,
            "caption": caption,
            "source": copy.deepcopy(PLUGIN),
        }
        | fields
        | {"data": data}
    )


class Case:
    """A view, its files, the caps it runs under, and the queries it answers."""

    def __init__(
        self,
        name: str,
        covers: str,
        view: dict,
        files: dict,
        caps: dict | None = None,
        **queries,
    ):
        self.name, self.covers, self.view, self.files = name, covers, view, files
        self.caps = caps or {}
        self.queries = queries

    def registry(self) -> dict:
        """The registry with this case's caps in place of the registered ones."""
        return REGISTRY | {"caps": REGISTRY["caps"] | self.caps}


def _encoded(files: dict[str, bytes]) -> dict:
    out = {}
    for location, data in files.items():
        try:
            out[location] = {"text": data.decode("utf-8")}
        except UnicodeDecodeError:
            out[location] = {"base64": base64.b64encode(data).decode("ascii")}
    return out


# ── nemar.table ───────────────────────────────────────────────────────────


CHANNELS = tsv(
    "name type status status_description",
    "Fp1 EEG good n/a",
    "Fp2 EEG bad flat",
    "Cz EEG good n/a",
)
CHANNELS_AT = f"{PREFIX}_channels.tsv"
CHANNEL_COLUMNS = [col("name", "string"), col("status", "string")]


def table_view(data: bytes, columns=None, location=CHANNELS_AT, **fields) -> dict:
    columns = CHANNEL_COLUMNS if columns is None else columns
    return view(
        "channels",
        "nemar.table",
        "Channels and the floor's decisions.",
        [data_entry("table", location, data, columns=columns)],
        **fields,
    )


SEGMENTS = tsv(
    "onset duration samples",
    "1.5 0.25 64",
    "12 1e-3 1",
    "-0 2E2 9007199254740991",
)
SEGMENTS_AT = f"{PREFIX}_badsegments.tsv"
SEGMENT_COLUMNS = [
    col("onset", unit="s"),
    col("duration", unit="s"),
    col("samples", "integer"),
]

# Texts that a lenient number parser accepts and the JSON grammar does not.
NOT_NUMBERS = ["", " 1", "+1", "01", "1.", ".5", "1e", "0x10", "1_0", "NaN", "Infinity"]


def table_cases() -> list[Case]:
    cases = [
        Case(
            "table_channels",
            "A table reads its declared columns in declared order and keeps "
            "every cell's text; the undeclared column type is not shown.",
            table_view(CHANNELS, [col("status", "string"), *CHANNEL_COLUMNS[:1]]),
            {CHANNELS_AT: CHANNELS},
        ),
        Case(
            "table_numbers",
            "Number and integer columns keep their text (-0, 1e-3, 2E2), and an "
            "integer may reach 2^53 - 1.",
            table_view(SEGMENTS, SEGMENT_COLUMNS, SEGMENTS_AT),
            {SEGMENTS_AT: SEGMENTS},
        ),
        Case(
            "table_no_rows",
            "A table with a header and no rows is valid and has no rows.",
            table_view(tsv("name status"), location=CHANNELS_AT),
            {CHANNELS_AT: tsv("name status")},
        ),
        Case(
            "table_column_missing",
            "A declared column the header lacks refuses the table: column_missing.",
            table_view(CHANNELS, [col("name", "string"), col("impedance", "string")]),
            {CHANNELS_AT: CHANNELS},
        ),
        Case(
            "table_column_repeated",
            "A column declared twice refuses the table: column_repeated.",
            table_view(CHANNELS, [col("name", "string"), col("name", "string")]),
            {CHANNELS_AT: CHANNELS},
        ),
        Case(
            "table_n_a_in_a_number_column",
            "n/a is not a number: cell_not_number; the fallback still shows it.",
            table_view(CHANNELS, [col("name", "string"), col("status_description")]),
            {CHANNELS_AT: CHANNELS},
        ),
    ]
    for index, text in enumerate(NOT_NUMBERS):
        data = tsv("x").replace(b"\n", b"\n" + text.encode() + b"\n", 1)
        cases.append(
            Case(
                f"table_not_a_number_{index}",
                f"The cell {text!r} does not match the JSON number grammar: "
                "cell_not_number.",
                table_view(data, [col("x")]),
                {CHANNELS_AT: data},
            )
        )
    for name, text, word in [
        ("table_not_finite", "1e400", "cell_not_finite"),
        ("table_integer_with_fraction", "2.0", "cell_not_integer"),
        ("table_integer_with_exponent", "2e0", "cell_not_integer"),
        ("table_integer_beyond_2_53", "9007199254740992", "cell_not_integer"),
        ("table_integer_leading_zero", "007", "cell_not_integer"),
    ]:
        kind = "number" if word == "cell_not_finite" else "integer"
        data = tsv("x", text)
        cases.append(
            Case(
                name,
                f"The {kind} cell {text!r} is refused: {word}.",
                table_view(data, [col("x", kind)]),
                {CHANNELS_AT: data},
            )
        )
    for name, data, word in [
        ("table_crlf", CHANNELS.replace(b"\n", b"\r\n"), "tsv_line_endings"),
        ("table_no_final_lf", CHANNELS[:-1], "tsv_line_endings"),
        ("table_ragged", CHANNELS + b"O1\tEEG\n", "tsv_ragged"),
        ("table_header_repeated", tsv("name name", "a b"), "tsv_header_repeated"),
        ("table_byte_order_mark", b"\xef\xbb\xbf" + CHANNELS, "tsv_encoding"),
        ("table_not_utf8", CHANNELS.replace(b"Cz", b"C\xff"), "tsv_encoding"),
    ]:
        cases.append(
            Case(
                name,
                f"The file breaks the TSV grammar: {word}; the fallback offers it "
                "for download only.",
                table_view(data),
                {CHANNELS_AT: data},
            )
        )
    return cases


# ── nemar.lines ───────────────────────────────────────────────────────────


SPECTRUM = tsv(
    "freq_hz Fp1 Fp2 O1 Cz",
    "0 12.5 -3.25 7 1.25e1",
    "0.5 8 -2 6 0",
    "1 4.75 -1.5 5 -0",
    "1.5 3 0.125 4 -7E-1",
    "2 1 2 3 -1",
)
SPECTRUM_AT = f"{PREFIX}_spectrum.tsv"
FREQ = dim("freq", "rows", "number", {"column": "freq_hz"}, unit="Hz")
SENSOR = dim("sensor", "columns", "string", {"header": True})


def spectrum_entry(data=SPECTRUM, columns=None, dims=None) -> dict:
    columns = (
        [col("freq_hz", unit="Hz")] + [col(n, unit="dB") for n in ("Fp1", "Fp2", "Cz")]
        if columns is None
        else columns
    )
    return data_entry(
        "values",
        SPECTRUM_AT,
        data,
        columns=columns,
        dims=[FREQ, SENSOR] if dims is None else dims,
    )


def lines_view(entry=None, **fields) -> dict:
    return view(
        "spectrum",
        "nemar.lines",
        "Power spectral density per sensor.",
        [spectrum_entry() if entry is None else entry],
        **fields,
    )


SNAPS = [-1, 0, 0.1, 0.25, 0.26, 0.74, 0.75, 0.76, 1.9, 2, 10]
PAIR = tsv("x y", "0.1 1", "0.3 2")

LAYOUT = tsv(
    "name theta_deg radius sensor_type",
    "Fp1 -18 0.51 EEG",
    "Fp2 18 0.51 EEG",
    "Cz 0 0 EEG",
)
LAYOUT_AT = f"{PREFIX}_chanlocs.tsv"
NUMBERED = tsv(
    "freq_hz ch1 ch2 ch3",
    "0 1 2 3",
    "1 2 3 4",
)


def preset_spectrum(
    layout: bytes = LAYOUT,
    layout_role: str = "layout",
    name_type: str = "string",
    values: bytes = NUMBERED,
) -> dict:
    """An unknown kind over nemar.lines whose sensors are named by its layout."""
    sensor = dim("sensor", "columns", "string", {"role": "layout", "column": "name"})
    values = data_entry(
        "values",
        f"{PREFIX}_numbered.tsv",
        values,
        columns=[col("freq_hz", unit="Hz")]
        + [col(n, unit="dB") for n in ("ch1", "ch2", "ch3")],
        dims=[FREQ, sensor],
    )
    layout_entry = data_entry(
        layout_role,
        LAYOUT_AT,
        layout,
        columns=[col("name", name_type), col("theta_deg", unit="deg"), col("radius")],
    )
    return view(
        "spectrum",
        "acme.spectrum",
        "Power spectral density per sensor, named by the layout.",
        [values, layout_entry],
        base="nemar.lines",
        base_version=1,
        parameters={"method": "welch"},
    )


def _shared_location(first: str) -> dict:
    """A preset over nemar.lines whose layout names the values' own file, with
    the values' size and another digest (probe p2: one entry hides another)."""
    spectrum = preset_spectrum()
    values, layout = spectrum["data"]
    layout = layout | {
        "location": values["location"],
        "size": values["size"],
        "sha256": "0" * 64,
        "columns": [col("freq_hz", "string")],
    }
    spectrum["data"] = [values, layout] if first == "values" else [layout, values]
    return spectrum


def lines_cases() -> list[Case]:
    files = {SPECTRUM_AT: SPECTRUM}
    epochs = tsv("epoch power", "1 10", "2 12", "4 9")
    epochs_at = f"{PREFIX}_epochs.tsv"
    epochs_entry = data_entry(
        "values",
        epochs_at,
        epochs,
        columns=[col("epoch", "integer"), col("power", "integer", "uV^2")],
        dims=[
            dim("epoch", "rows", "integer", {"column": "epoch"}),
            dim("measure", "columns", "string", {"header": True}),
        ],
    )
    reordered = spectrum_entry(
        columns=[col(n, unit="dB") for n in ("Cz", "Fp1")] + [col("freq_hz", unit="Hz")]
    )
    cases = [
        Case(
            "lines_spectrum",
            "One series per declared value column, in declared order; the "
            "undeclared column O1 is not read; values keep their text (1.25e1, "
            "-0, -7E-1); pointers read the nearest stored row, the lower on a tie.",
            lines_view(),
            files,
            snaps=SNAPS,
        ),
        Case(
            "lines_declared_order",
            "The x column may be declared last; series follow declared order.",
            lines_view(reordered),
            files,
            snaps=[0.6],
        ),
        Case(
            "lines_integer_epochs",
            "An integer x dimension and one integer series; the series label is "
            "the column name.",
            view(
                "epochs",
                "nemar.lines",
                "Power per epoch.",
                [epochs_entry],
                source=copy.deepcopy(RECIPE),
            ),
            {epochs_at: epochs},
            snaps=[2.9, 3, 3.1],
        ),
        Case(
            "lines_preset_by_base",
            "An unknown kind over nemar.lines draws as lines: the sensor labels "
            "come by position from its layout role, its parameters are ignored, "
            "and both files are offered for download.",
            preset_spectrum(),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: LAYOUT},
            snaps=[0.5],
        ),
        Case(
            "lines_x_column_without_unit",
            "The x column declares no unit, so its dimension's unit (Hz) holds: "
            "only a declared unit must match.",
            lines_view(
                spectrum_entry(
                    columns=[
                        col("freq_hz"),
                        *(col(n, unit="dB") for n in ("Fp1", "Cz")),
                    ]
                )
            ),
            files,
        ),
        Case(
            "lines_snap_binary64",
            "x 0.1 and 0.3, pointer 0.2: in binary64, 0.3 - 0.2 < 0.2 - 0.1, so "
            "the pointer reads row 1, though 0.2 is the decimal midpoint.",
            view(
                "pair",
                "nemar.lines",
                "Two rows.",
                [
                    data_entry(
                        "values",
                        f"{PREFIX}_pair.tsv",
                        PAIR,
                        columns=[col("x"), col("y")],
                        dims=[dim("x", "rows", "number", {"column": "x"}), SENSOR],
                    )
                ],
            ),
            {f"{PREFIX}_pair.tsv": PAIR},
            snaps=[0.2],
        ),
        Case(
            "lines_unknown_version",
            "A version of nemar.lines the registry does not list shows as a table.",
            lines_view(kind_version=2),
            files,
        ),
    ]
    two_series = [col("freq_hz", unit="Hz"), col("Fp1", unit="dB")]
    for name, covers, data, columns in [
        (
            "lines_x_not_increasing",
            "Two equal x values: x_not_increasing.",
            tsv("freq_hz Fp1 Fp2 Cz", "0 1 2 3", "0 1 2 3"),
            None,
        ),
        (
            "lines_x_decreasing",
            "Decreasing x values: x_not_increasing.",
            tsv("freq_hz Fp1 Fp2 Cz", "1 1 2 3", "0 1 2 3"),
            None,
        ),
        (
            "lines_value_units_differ",
            "Series in dB and in uV^2/Hz cannot share a y axis: value_units_differ.",
            SPECTRUM,
            [*two_series, col("Fp2", unit="uV^2/Hz")],
        ),
        (
            "lines_value_unit_missing",
            "One series without a unit and one in dB: value_units_differ.",
            SPECTRUM,
            [*two_series, col("Fp2")],
        ),
        (
            "lines_coords_mismatch",
            "The x column says kHz and its dimension Hz: coords_mismatch.",
            SPECTRUM,
            [col("freq_hz", unit="kHz"), col("Fp1", unit="dB")],
        ),
        (
            "lines_coords_unresolved",
            "The x dimension names a column the role does not declare: "
            "coords_unresolved.",
            SPECTRUM,
            [col("Fp1", unit="dB"), col("Fp2", unit="dB")],
        ),
        (
            "lines_empty",
            "A header and no rows: empty.",
            tsv("freq_hz Fp1 Fp2 Cz"),
            None,
        ),
        (
            "lines_cell_not_number",
            "A value cell n/a: cell_not_number.",
            tsv("freq_hz Fp1 Fp2 Cz", "0 1 n/a 3"),
            None,
        ),
    ]:
        entry = spectrum_entry(data, columns)
        cases.append(Case(name, covers, lines_view(entry), {SPECTRUM_AT: data}))
    short = tsv("name theta_deg radius", "Fp1 -18 0.51", "Fp2 18 0.51")
    unnamed = LAYOUT.replace(b"name\t", b"label\t", 1)
    cases += [
        Case(
            "lines_preset_coords_length",
            "The layout names two sensors for three series: coords_length.",
            preset_spectrum(short),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: short},
        ),
        Case(
            "lines_preset_coords_role_absent",
            "The sensor labels name the role layout, which the view lacks: "
            "coords_unresolved.",
            preset_spectrum(layout_role="positions"),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: LAYOUT},
        ),
        Case(
            "lines_preset_coords_column_missing",
            "The layout declares name, but its header calls the column label: "
            "column_missing.",
            preset_spectrum(unnamed),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: unnamed},
        ),
        Case(
            "lines_preset_coords_mismatch",
            "The layout's name column is declared integer, its dimension "
            "string: coords_mismatch.",
            preset_spectrum(name_type="integer"),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: LAYOUT},
        ),
    ]
    return cases


# ── nemar.heatmap ─────────────────────────────────────────────────────────


CLASSES = tsv(
    "component brain eye muscle",
    "IC1 91.5 2 6.5",
    "IC2 4.25 88 7.75",
    "IC3 30 30 40",
)
CLASSES_AT = f"{PREFIX}_icprobabilities.tsv"
CLASS_COLUMNS = [col("component", "string")] + [
    col(n, unit="%") for n in ("brain", "eye", "muscle")
]
COMPONENT = dim("component", "rows", "string", {"column": "component"})
CLASS = dim("class", "columns", "string", {"header": True})


def heatmap_view(data=CLASSES, columns=None, dims=None, location=CLASSES_AT, **kw):
    entry = data_entry(
        "values",
        location,
        data,
        columns=CLASS_COLUMNS if columns is None else columns,
        dims=[COMPONENT, CLASS] if dims is None else dims,
    )
    return view(
        "icprobabilities",
        "nemar.heatmap",
        "Class probabilities per component.",
        [entry],
        **kw,
    )


def heatmap_cases() -> list[Case]:
    files = {CLASSES_AT: CLASSES}
    corr = tsv("sensor Fp1 Fp2", "Fp1 1 -0.75", "Fp2 -0.75 1")
    corr_cols = [col("sensor", "string"), col("Fp1"), col("Fp2")]
    corr_dims = [
        dim("sensor", "rows", "string", {"column": "sensor"}),
        dim("sensor_pair", "columns", "string", {"header": True}),
    ]
    zeros = tsv("sensor Fp1 Fp2", "Fp1 0 -0", "Fp2 0 0")
    negative = tsv("sensor Fp1 Fp2", "Fp1 -3 1", "Fp2 0.5 -2")
    fives = tsv("sensor Fp1 Fp2", "Fp1 5 5", "Fp2 5 5.0")
    epochs = tsv("epoch Fp1 Fp2", "1 0.5 0.25", "2 0.75 1")
    epoch_dims = [dim("epoch", "rows", "integer", {"column": "epoch"}), corr_dims[1]]
    components = tsv("label class", "IC1 brain", "IC2 eye", "IC3 other")
    probabilities = tsv("brain eye muscle", "91.5 2 6.5", "4.25 88 7.75", "30 30 40")
    not_a_number = CLASSES.replace(b"88", b"8_8")
    preset = view(
        "icprobabilities",
        "acme.ic-probabilities",
        "Class probabilities per component, labeled by the components table.",
        [
            data_entry(
                "values",
                f"{PREFIX}_probabilities.tsv",
                probabilities,
                columns=CLASS_COLUMNS[1:],
                dims=[
                    dim(
                        "component",
                        "rows",
                        "string",
                        {"role": "components", "column": "label"},
                    ),
                    CLASS,
                ],
            ),
            data_entry(
                "components",
                f"{PREFIX}_components.tsv",
                components,
                columns=[col("label", "string")],
            ),
        ],
        base="nemar.heatmap",
        base_version=1,
        parameters={"limits": "absmax"},
    )
    undeclared = copy.deepcopy(preset)

    def numbered_rows(numbers: bytes) -> dict:
        """The preset, its rows labeled by an integer column of a numbers role."""
        out = copy.deepcopy(preset)
        out["data"][0]["dims"][0] = dim(
            "component", "rows", "integer", {"role": "numbers", "column": "number"}
        )
        out["data"][1] = data_entry(
            "numbers",
            f"{PREFIX}_numbers.tsv",
            numbers,
            columns=[col("number", "integer")],
        )
        return out

    undeclared["data"][1]["columns"] = [col("class", "string")]
    coded = tsv("component c1 c2 c3", "IC1 91.5 2 6.5", "IC2 4.25 88 7.75")
    names = tsv("name description", "brain Brain", "eye Eye", "muscle Muscle")
    by_classes = view(
        "icprobabilities",
        "acme.ic-probabilities",
        "Class probabilities per component, the classes named by a table.",
        [
            data_entry(
                "values",
                CLASSES_AT,
                coded,
                columns=[col("component", "string")]
                + [col(n, unit="%") for n in ("c1", "c2", "c3")],
                dims=[
                    COMPONENT,
                    dim(
                        "class",
                        "columns",
                        "string",
                        {"role": "classes", "column": "name"},
                    ),
                ],
            ),
            data_entry(
                "classes",
                f"{PREFIX}_classes.tsv",
                names,
                columns=[col("name", "string")],
            ),
        ],
        base="nemar.heatmap",
        base_version=1,
    )
    return [
        Case(
            "heatmap_classes",
            "Row labels from a column, column labels from the header, minmax limits.",
            heatmap_view(),
            files,
        ),
        Case(
            "heatmap_absmax",
            "absmax limits are minus and plus the largest absolute cell.",
            heatmap_view(corr, corr_cols, corr_dims, parameters={"limits": "absmax"}),
            {CLASSES_AT: corr},
        ),
        Case(
            "heatmap_absmax_negative",
            "The most negative cell (-3) has the largest magnitude, so absmax "
            "limits are -3 and 3, not minus and plus the largest cell.",
            heatmap_view(
                negative, corr_cols, corr_dims, parameters={"limits": "absmax"}
            ),
            {CLASSES_AT: negative},
        ),
        Case(
            "heatmap_absmax_all_zero",
            "Every cell zero (one written -0): absmax limits are 0 and 0, and -0 "
            "reads as 0.",
            heatmap_view(zeros, corr_cols, corr_dims, parameters={"limits": "absmax"}),
            {CLASSES_AT: zeros},
        ),
        Case(
            "heatmap_constant",
            "Every cell 5 (one written 5.0): minmax limits are equal.",
            heatmap_view(fives, corr_cols, corr_dims, parameters={"limits": "minmax"}),
            {CLASSES_AT: fives},
        ),
        Case(
            "heatmap_integer_rows",
            "Integer row coordinates label the rows with their text.",
            heatmap_view(
                epochs,
                [col("epoch", "integer"), col("Fp1"), col("Fp2")],
                epoch_dims,
            ),
            {CLASSES_AT: epochs},
        ),
        Case(
            "heatmap_preset_by_base",
            "An unknown kind over nemar.heatmap: row labels by position from its "
            "components role, and the base ignores its absmax parameter.",
            preset,
            {
                f"{PREFIX}_probabilities.tsv": probabilities,
                f"{PREFIX}_components.tsv": components,
            },
        ),
        Case(
            "heatmap_value_type",
            "A text column among the values: value_type.",
            heatmap_view(columns=[*CLASS_COLUMNS[:2], col("eye", "string")]),
            files,
        ),
        Case(
            "heatmap_cell_not_number",
            "A value cell that is not a number: cell_not_number.",
            heatmap_view(not_a_number),
            {CLASSES_AT: not_a_number},
        ),
        Case(
            "heatmap_label_column_only",
            "Only the label column declared: no value column, empty.",
            heatmap_view(columns=CLASS_COLUMNS[:1]),
            files,
        ),
        Case(
            "heatmap_preset_columns_from_role",
            "An unknown kind over nemar.heatmap whose column labels come by "
            "position from its classes role.",
            by_classes,
            {CLASSES_AT: coded, f"{PREFIX}_classes.tsv": names},
        ),
        Case(
            "heatmap_preset_coords_cell_not_integer",
            "Row labels from another role's integer column, one of whose cells "
            "is 2.5: cell_not_integer.",
            numbered_rows(tsv("number", "1", "2", "2.5")),
            {
                f"{PREFIX}_probabilities.tsv": probabilities,
                f"{PREFIX}_numbers.tsv": tsv("number", "1", "2", "2.5"),
            },
        ),
        Case(
            "heatmap_preset_coords_column_undeclared",
            "The components role does not declare the column its labels name: "
            "coords_unresolved.",
            undeclared,
            {
                f"{PREFIX}_probabilities.tsv": probabilities,
                f"{PREFIX}_components.tsv": components,
            },
        ),
    ]


# ── nemar.histogram ───────────────────────────────────────────────────────


HIST_AT = f"{PREFIX}_hist.json"


def histogram_view(data: bytes, kind="nemar.histogram", **fields) -> dict:
    return view(
        "hist",
        kind,
        "Recordings by share of good samples.",
        [data_entry("histogram", HIST_AT, data)],
        **fields,
    )


def content(**members) -> bytes:
    return (json.dumps(members, indent=1) + "\n").encode()


EDGES = content(
    edges=[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    counts=[0, 0, 0, 0, 1, 0, 0, 2, 3, 11],
    underflow=1,
    overflow=2,
    unit="%",
)
LOCATES = [-0.5, 0, 9.999, 10, 50, 99.99, 100, 100.5]
ICLABEL = content(
    categories=[
        "Brain",
        "Muscle",
        "Eye",
        "Heart",
        "Line Noise",
        "Channel Noise",
        "Other",
    ],
    counts=[12, 3, 2, 0, 1, 0, 4],
)


def histogram_cases() -> list[Case]:
    printing = b'{"edges": [-1E-7, -0.0, 0.1, 0.25, 1e21], "counts": [1, 2, 3, 4],' + (
        b' "underflow": 0, "overflow": 0}\n'
    )
    overflowing = content(edges=[0, 1, 2], counts=[1, 2], underflow=0, overflow=5)
    preset = content(
        categories=["Brain", "Other"],
        counts=[30, 5],
        summed_variance_pct=[80.5, 19.5],
        n_components=35,
    )
    tenths = content(
        edges=[0, 0.1, 0.2, 0.3], counts=[4, 5, 6], underflow=0, overflow=0
    )
    fractions = content(
        edges=[0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1],
        counts=[40, 22, 18, 9, 6, 3, 1, 1],
        underflow=0,
        overflow=0,
    )
    lacking = content(
        edges=[0, 50, 100], counts=[3, 4], underflow=0, overflow=1, missing=2
    )
    lacking_classes = content(categories=["a", "b"], counts=[3, 4], missing=5)
    tiny = content(edges=[0, 1e-12, 3e-12], counts=[1, 2], underflow=0, overflow=0)
    nested_64 = (
        b'{"categories": ["a"], "counts": [1], "x": ' + b"[" * 63 + b"]" * 63 + b"}\n"
    )
    negative_zeros = (
        b'{"edges": [-0, 1], "counts": [-0.0], "underflow": -0, "overflow": 0}\n'
    )
    cases = [
        Case(
            "histogram_nested_64",
            "A file nested exactly 64 deep, in a member this kind does not read: "
            "drawn.",
            histogram_view(nested_64),
            {HIST_AT: nested_64},
        ),
        Case(
            "histogram_negative_zero_counts",
            "Counts and an edge written -0 and -0.0 read as 0: the model holds no "
            "negative zero, so the total and max_count are 0, not -0.",
            histogram_view(negative_zeros),
            {HIST_AT: negative_zeros},
        ),
        Case(
            "histogram_equal_widths_to_rounding",
            "Edges 0, 0.1, 0.2 and 0.3, whose binary64 widths differ in the last "
            "bit: equal widths, so heights are counts.",
            histogram_view(tenths),
            {HIST_AT: tenths},
        ),
        Case(
            "histogram_unequal_widths",
            "The bins of a dataQuality distribution (0, 0.01, 0.02, 0.05, 0.1, "
            "0.2, 0.3, 0.5, 1): unequal widths, so each bar's height is its "
            "density, count over width, and the model says so (heights density).",
            histogram_view(fractions),
            {HIST_AT: fractions},
            locates=[0.005, 0.05, 1, 1.5],
        ),
        Case(
            "histogram_tiny_unequal_widths",
            "Edges 0, 1e-12 and 3e-12: widths 1e-12 and 2e-12 differ from the "
            "first by far more than 1e-9 times the widest, however small they "
            "are, so heights are densities.",
            histogram_view(tiny),
            {HIST_AT: tiny},
        ),
        Case(
            "histogram_missing_edges",
            "Values missing or not a number, counted apart: shown beside the "
            "bars, outside the total.",
            histogram_view(lacking),
            {HIST_AT: lacking},
        ),
        Case(
            "histogram_missing_categories",
            "A missing count beside bins by category.",
            histogram_view(lacking_classes),
            {HIST_AT: lacking_classes},
        ),
        Case(
            "histogram_edges",
            "Bins [e_i, e_i+1), the last closed; underflow and overflow; labels "
            "and the bin of each located value.",
            histogram_view(EDGES),
            {HIST_AT: EDGES},
            locates=LOCATES,
        ),
        Case(
            "histogram_edge_printing",
            "Edge labels print numbers as ECMAScript String(x): -1e-7, 0.1, "
            "1e+21; the edge -0.0 reads as 0 and prints as 0.",
            histogram_view(printing),
            {HIST_AT: printing},
            locates=[-1e-7, 0.1, 1e21, 2e21],
        ),
        Case(
            "histogram_overflow_largest",
            "The overflow is the largest count, so max_count is the overflow's.",
            histogram_view(overflowing),
            {HIST_AT: overflowing},
            locates=[2, 2.5],
        ),
        Case(
            "histogram_categories",
            "Bins by category, in order; no unit, underflow or overflow.",
            histogram_view(ICLABEL),
            {HIST_AT: ICLABEL},
        ),
        Case(
            "histogram_preset_by_base",
            "An unknown kind over nemar.histogram whose content adds members of "
            "its own draws as a histogram of the members this kind reads.",
            histogram_view(
                preset, kind="acme.ic-classes", base="nemar.histogram", base_version=1
            ),
            {HIST_AT: preset},
        ),
    ]
    for name, data, covers in [
        (
            "histogram_edges_not_increasing",
            content(edges=[0, 10, 10, 20], counts=[1, 2, 3], underflow=0, overflow=0),
            "Equal edges: edges_not_increasing.",
        ),
        (
            "histogram_counts_length",
            content(edges=[0, 10, 20], counts=[1, 2, 3], underflow=0, overflow=0),
            "Three counts for two bins: counts_length.",
        ),
        (
            "histogram_category_counts_length",
            content(categories=["Brain", "Eye"], counts=[1]),
            "One count for two categories: counts_length.",
        ),
        (
            "histogram_both_forms",
            content(
                edges=[0, 1], categories=["a"], counts=[1], underflow=0, overflow=0
            ),
            "Edges and categories together: content_invalid.",
        ),
        (
            "histogram_negative_count",
            content(categories=["a"], counts=[-1]),
            "A negative count: content_invalid.",
        ),
        (
            "histogram_nan_literal",
            b'{"categories": ["a"], "counts": [NaN]}\n',
            "A NaN literal: json_invalid.",
        ),
        (
            "histogram_infinite_edge",
            b'{"edges": [0, 1e400], "counts": [1], "underflow": 0, "overflow": 0}\n',
            "An edge 1e400 reads as infinite: json_invalid.",
        ),
        (
            "histogram_duplicate_member",
            b'{"categories": ["a"], "counts": [1], "counts": [2]}\n',
            "A member named twice: json_invalid.",
        ),
        (
            "histogram_edge_beyond_binary64",
            b'{"edges": [0, ' + HUGE.encode() + b'], "counts": [1], '
            b'"underflow": 0, "overflow": 0}\n',
            "An integer edge of 401 digits: Python reads it exactly, JSON.parse "
            "as Infinity, so it is not finite: json_invalid.",
        ),
        (
            "histogram_member_beyond_binary64",
            b'{"categories": ["a"], "counts": [1], "n_components": '
            + HUGE.encode()
            + b"}\n",
            "A member this kind does not read is still a number past binary64: "
            "json_invalid.",
        ),
        (
            "histogram_total_beyond_2_53",
            content(categories=["a", "b"], counts=[2**53 - 1, 1]),
            "Counts whose total passes 2^53 - 1, which a binary64 sum would not "
            "hold exactly: cap_exceeded.",
        ),
        (
            "histogram_total_with_underflow_beyond_2_53",
            content(edges=[0, 1], counts=[2**53 - 1], underflow=1, overflow=0),
            "The underflow counts in the total: cap_exceeded.",
        ),
        (
            "histogram_bin_too_wide",
            content(edges=[-1.7e308, 1.7e308], counts=[1], underflow=0, overflow=0),
            "A bin from -1.7e308 to 1.7e308, wider than binary64 holds: "
            "cap_exceeded, since its density cannot be computed.",
        ),
        (
            "histogram_density_too_large",
            content(edges=[0, 1e-308], counts=[2], underflow=0, overflow=0),
            "Two values in a bin 1e-308 wide: the density, count over width, "
            "overflows binary64, so cap_exceeded.",
        ),
        (
            "histogram_total_with_missing_beyond_2_53",
            content(categories=["a"], counts=[2**53 - 1], missing=1),
            "The missing count in the sum a renderer may compute: cap_exceeded.",
        ),
        (
            "histogram_byte_order_mark",
            b"\xef\xbb\xbf" + ICLABEL,
            "A byte order mark: json_invalid.",
        ),
        (
            "histogram_not_utf8",
            b'{"categories": ["a\xff"], "counts": [1]}\n',
            "A byte that is not UTF-8 (0xFF): json_invalid, where a decoder "
            "without fatal would read U+FFFD (review r29).",
        ),
        (
            "histogram_escaped_duplicate_member",
            b'{"categories": ["a"], "counts": [1], "\\u0063ounts": [2]}\n',
            "A member named twice, once escaped (counts and \\u0063ounts are one "
            "name): json_invalid.",
        ),
        (
            "histogram_lone_surrogate",
            b'{"categories": ["\\ud800"], "counts": [1]}\n',
            "A category holding an escaped lone surrogate: json_invalid.",
        ),
        (
            "histogram_lone_surrogate_in_name",
            b'{"categories": ["a"], "counts": [1], "\\udc00": 1}\n',
            "A member name holding a lone surrogate, in a member this kind does "
            "not read: json_invalid.",
        ),
        (
            "histogram_noncharacter",
            b'{"categories": ["\\ufdd0"], "counts": [1]}\n',
            "A category holding the noncharacter U+FDD0: json_invalid.",
        ),
        (
            "histogram_noncharacter_raw",
            '{"categories": ["a\uffff"], "counts": [1]}\n'.encode(),
            "A category holding the noncharacter U+FFFF as UTF-8 bytes: json_invalid.",
        ),
        (
            "histogram_noncharacter_astral",
            b'{"categories": ["\\ud83f\\udffe"], "counts": [1]}\n',
            "A category holding U+1FFFE, a noncharacter written as a surrogate "
            "pair: json_invalid.",
        ),
        (
            "histogram_nested_65",
            b'{"categories": ["a"], "counts": [1], "x": '
            + b"[" * 64
            + b"]" * 64
            + b"}\n",
            "A member this kind does not read, nested so the file is 65 deep: "
            "json_invalid.",
        ),
    ]:
        cases.append(Case(name, covers, histogram_view(data), {HIST_AT: data}))
    return cases


# ── Caps, with each case's own caps in place of the registry's ───────────


def cap_cases() -> list[Case]:
    numbered = data_entry(
        "values",
        f"{PREFIX}_numbered.tsv",
        NUMBERED,
        columns=[col("freq_hz", unit="Hz")]
        + [col(n, unit="dB") for n in ("ch1", "ch2", "ch3")],
        dims=[FREQ, SENSOR],
    )
    na = [col("name", "string"), col("status_description")]
    return [
        Case(
            "caps_lines_bytes",
            "A file one byte over caps.bytes_per_role: cap_exceeded, and the "
            "fallback offers it for download only.",
            lines_view(),
            {SPECTRUM_AT: SPECTRUM},
            caps={"bytes_per_role": len(SPECTRUM) - 1},
        ),
        Case(
            "caps_lines_rows",
            "Five rows over caps.entries_per_dim 4: cap_exceeded; the fallback "
            "has no entries cap and shows the table.",
            lines_view(),
            {SPECTRUM_AT: SPECTRUM},
            caps={"entries_per_dim": 4},
        ),
        Case(
            "caps_lines_value_columns",
            "Three value columns over caps.entries_per_dim 2, with two rows: "
            "cap_exceeded.",
            view("numbered", "nemar.lines", "Three series.", [numbered]),
            {f"{PREFIX}_numbered.tsv": NUMBERED},
            caps={"entries_per_dim": 2},
        ),
        Case(
            "caps_lines_cells",
            "Five rows of four declared columns are 20 cells, over 19, though "
            "the value cells are 15: cells count every declared column.",
            lines_view(),
            {SPECTRUM_AT: SPECTRUM},
            caps={"cells_per_role": 19},
        ),
        Case(
            "caps_table_cells",
            "Three rows of two declared columns are 6 cells, over 5: cap_exceeded; "
            "the fallback's 12 header cells are over 5 too.",
            table_view(CHANNELS),
            {CHANNELS_AT: CHANNELS},
            caps={"cells_per_role": 5},
        ),
        Case(
            "caps_table_cells_count_declared_columns",
            "Six declared cells under a cap of 6 draw, though the header holds 12.",
            table_view(CHANNELS),
            {CHANNELS_AT: CHANNELS},
            caps={"cells_per_role": 6},
        ),
        Case(
            "caps_fallback_counts_header_cells",
            "The table refuses n/a (cell_not_number); its fallback counts every "
            "header column, 12 cells over 8, so it shows no table.",
            table_view(CHANNELS, na),
            {CHANNELS_AT: CHANNELS},
            caps={"cells_per_role": 8},
        ),
        Case(
            "caps_histogram_bytes",
            "A histogram file one byte over caps.bytes_per_role: cap_exceeded.",
            histogram_view(EDGES),
            {HIST_AT: EDGES},
            caps={"bytes_per_role": len(EDGES) - 1},
        ),
    ]


# ── The order of checks: two faults, the first check's word ──────────────


def order_cases() -> list[Case]:
    def lines_case(name, covers, data, columns=None, caps=None):
        entry = spectrum_entry(data, columns)
        return Case(name, covers, lines_view(entry), {SPECTRUM_AT: data}, caps)

    def hist_case(name, covers, data, caps=None):
        return Case(name, covers, histogram_view(data), {HIST_AT: data}, caps)

    crlf = SPECTRUM.replace(b"\n", b"\r\n")
    hz, db = col("freq_hz", unit="Hz"), col("Fp1", unit="dB")
    short = tsv("name theta_deg radius", "Fp1 -18 0.51", "Fp2 18 0.51")
    unnamed = LAYOUT.replace(b"name\t", b"label\t", 1)
    ragged_layout = LAYOUT + b"O1\t90\n"
    ragged_unnamed = unnamed + b"O1\t90\n"
    undeclared_layout = preset_spectrum(ragged_layout)
    undeclared_layout["data"][1]["columns"] = [
        col("theta_deg", unit="deg"),
        col("radius"),
    ]
    probabilities = tsv("brain eye muscle", "91.5 2 6.5", "4.25 88 7.75", "30 30 40")
    two_rows = tsv("label", "IC1", "IC2")
    two_numbers = tsv("number", "1", "2.5")
    heat_preset = view(
        "icprobabilities",
        "acme.ic-probabilities",
        "Class probabilities, labeled from other roles.",
        [
            data_entry(
                "values",
                f"{PREFIX}_probabilities.tsv",
                probabilities,
                columns=CLASS_COLUMNS[1:],
                dims=[
                    dim(
                        "component",
                        "rows",
                        "string",
                        {"role": "components", "column": "label"},
                    ),
                    dim(
                        "class",
                        "columns",
                        "string",
                        {"role": "classes", "column": "name"},
                    ),
                ],
            ),
            data_entry(
                "components",
                f"{PREFIX}_components.tsv",
                two_rows,
                columns=[col("label", "string")],
            ),
        ],
        base="nemar.heatmap",
        base_version=1,
    )
    int_rows = copy.deepcopy(heat_preset)
    int_rows["data"][0]["dims"] = [
        dim("component", "rows", "integer", {"role": "numbers", "column": "number"}),
        CLASS,
    ]
    int_rows["data"][1] = data_entry(
        "numbers",
        f"{PREFIX}_numbers.tsv",
        two_numbers,
        columns=[col("number", "integer")],
    )
    return [
        Case(
            "order_bytes_cap_before_fetch",
            "A declared size over the byte cap and no file: cap_exceeded, from the "
            "declaration before the file is fetched, so the view falls back "
            "rather than refusing on file_missing.",
            lines_view(),
            {},
            caps={"bytes_per_role": 10},
        ),
        Case(
            "order_bytes_cap_before_digest",
            "A declared size over the byte cap and other bytes of that size: "
            "cap_exceeded, before the digest is computed.",
            lines_view(),
            {SPECTRUM_AT: SPECTRUM.replace(b"12.5", b"12.6")},
            caps={"bytes_per_role": 10},
        ),
        lines_case(
            "order_bytes_cap_before_grammar",
            "Over the byte cap and CRLF line endings: cap_exceeded.",
            crlf,
            caps={"bytes_per_role": len(crlf) - 1},
        ),
        Case(
            "order_byte_order_mark_before_line_endings",
            "A byte order mark and CRLF line endings: tsv_encoding.",
            table_view(b"\xef\xbb\xbf" + CHANNELS.replace(b"\n", b"\r\n")),
            {CHANNELS_AT: b"\xef\xbb\xbf" + CHANNELS.replace(b"\n", b"\r\n")},
        ),
        Case(
            "order_line_endings_before_header",
            "CRLF line endings and a repeated header name, before the last "
            "column so the CR cannot mask it: tsv_line_endings.",
            table_view(b"name\tname\tx\r\na\tb\tc\r\n"),
            {CHANNELS_AT: b"name\tname\tx\r\na\tb\tc\r\n"},
        ),
        Case(
            "order_header_before_ragged",
            "A repeated header name and a ragged row: tsv_header_repeated.",
            table_view(b"name\tname\na\n"),
            {CHANNELS_AT: b"name\tname\na\n"},
        ),
        lines_case(
            "order_grammar_before_columns",
            "A ragged row and an undeclared header name: tsv_ragged.",
            SPECTRUM + b"3\t1\n",
            [hz, col("nope", unit="dB")],
        ),
        lines_case(
            "order_repeated_before_missing",
            "A missing column declared before a repeated one: column_repeated.",
            SPECTRUM,
            [hz, col("nope", unit="dB"), db, db],
        ),
        lines_case(
            "order_columns_before_coordinate",
            "A missing column and an x column in kHz: column_missing.",
            SPECTRUM,
            [col("freq_hz", unit="kHz"), col("nope", unit="dB")],
        ),
        lines_case(
            "order_coordinate_before_values",
            "An x column in kHz and series in dB and uV: coords_mismatch.",
            SPECTRUM,
            [col("freq_hz", unit="kHz"), db, col("Fp2", unit="uV")],
        ),
        Case(
            "order_value_type_before_units",
            "A text value column among values in % and dB: value_type.",
            heatmap_view(
                columns=[
                    col("component", "string"),
                    col("brain", unit="%"),
                    col("eye", "string"),
                    col("muscle", unit="dB"),
                ]
            ),
            {CLASSES_AT: CLASSES},
        ),
        lines_case(
            "order_units_before_empty",
            "Units that differ and no rows: value_units_differ.",
            tsv("freq_hz Fp1 Fp2"),
            [hz, db, col("Fp2", unit="uV")],
        ),
        lines_case(
            "order_empty_before_caps",
            "No rows and three value columns over a cap of 2: empty.",
            tsv("freq_hz Fp1 Fp2 Cz"),
            caps={"entries_per_dim": 2},
        ),
        lines_case(
            "order_caps_before_cells",
            "Five rows over a cap of 4 and an n/a cell: cap_exceeded.",
            SPECTRUM.replace(b"12.5", b"n/a"),
            caps={"entries_per_dim": 4},
        ),
        lines_case(
            "order_column_by_column",
            "An x cell 1e400 in the last row and a value n/a in the first: the x "
            "column is checked first, column by column, so cell_not_finite.",
            tsv("freq_hz Fp1 Fp2 Cz", "0 n/a 1 1", "1e400 1 1 1"),
        ),
        lines_case(
            "order_declared_column_order",
            "Fp1 holds 1e400 in row 1 and Fp2 n/a in row 2, and Fp2 is declared "
            "first: cell_not_number.",
            tsv("freq_hz Fp1 Fp2 Cz", "0 1e400 1 1", "1 1 n/a 1"),
            [hz, col("Fp2", unit="dB"), db, col("Cz", unit="dB")],
        ),
        lines_case(
            "order_cells_before_x_order",
            "Decreasing x and an n/a cell: cell_not_number.",
            tsv("freq_hz Fp1 Fp2 Cz", "1 1 1 1", "0 n/a 1 1"),
        ),
        Case(
            "order_x_order_before_role_coordinates",
            "Decreasing x and a layout too short for the series: x_not_increasing.",
            preset_spectrum(
                short, values=tsv("freq_hz ch1 ch2 ch3", "1 1 2 3", "0 2 3 4")
            ),
            {
                f"{PREFIX}_numbered.tsv": tsv(
                    "freq_hz ch1 ch2 ch3", "1 1 2 3", "0 2 3 4"
                ),
                LAYOUT_AT: short,
            },
        ),
        Case(
            "order_rows_before_columns",
            "Row labels too few (coords_length) and column labels from an absent "
            "role (coords_unresolved): the rows come first, coords_length.",
            heat_preset,
            {
                f"{PREFIX}_probabilities.tsv": probabilities,
                f"{PREFIX}_components.tsv": two_rows,
            },
        ),
        Case(
            "order_role_unresolved_before_file",
            "The layout does not declare name, and its file has a ragged row: "
            "coords_unresolved, before the layout's file is read. (A changed "
            "file would not tell the orders apart: the fallback reads every TSV "
            "and refuses the view either way.)",
            undeclared_layout,
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: ragged_layout},
        ),
        Case(
            "caps_role_cells",
            "The layout a preset's labels come from holds 12 cells, every header "
            "column counted, over a cap on cells lowered to 10 that the values' 8 "
            "meet: cap_exceeded, the coordinate role held to the caps as every "
            "role is.",
            preset_spectrum(),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: LAYOUT},
            caps={"cells_per_role": 10},
        ),
        Case(
            "order_role_grammar_before_cap",
            "The layout's file has a ragged row and is over the cap on cells: "
            "tsv_ragged.",
            preset_spectrum(ragged_layout),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: ragged_layout},
            caps={"cells_per_role": 10},
        ),
        Case(
            "order_role_cap_before_column_missing",
            "The layout is over the cap on cells and lacks the declared name: "
            "cap_exceeded.",
            preset_spectrum(unnamed),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: unnamed},
            caps={"cells_per_role": 10},
        ),
        Case(
            "order_role_grammar_before_column_missing",
            "The layout's file has a ragged row, and its header lacks the "
            "declared name: tsv_ragged.",
            preset_spectrum(ragged_unnamed),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: ragged_unnamed},
        ),
        Case(
            "order_role_column_missing_before_mismatch",
            "The layout's header lacks name, which is also declared integer: "
            "column_missing.",
            preset_spectrum(unnamed, name_type="integer"),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: unnamed},
        ),
        Case(
            "order_role_mismatch_before_length",
            "The layout's name declared integer and too short: coords_mismatch.",
            preset_spectrum(short, name_type="integer"),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: short},
        ),
        Case(
            "order_role_length_before_cells",
            "Two integer row labels, one 2.5, for three rows: coords_length.",
            int_rows,
            {
                f"{PREFIX}_probabilities.tsv": probabilities,
                f"{PREFIX}_numbers.tsv": two_numbers,
            },
        ),
        Case(
            "order_table_columns_before_cap",
            "A missing column and cells over the cap: column_missing.",
            table_view(CHANNELS, [col("name", "string"), col("impedance", "string")]),
            {CHANNELS_AT: CHANNELS},
            caps={"cells_per_role": 5},
        ),
        Case(
            "order_table_cap_before_cells",
            "Cells over the cap and an n/a number cell: cap_exceeded.",
            table_view(CHANNELS, [col("name", "string"), col("status_description")]),
            {CHANNELS_AT: CHANNELS},
            caps={"cells_per_role": 5},
        ),
        hist_case(
            "order_histogram_bytes_before_json",
            "Over the byte cap and a NaN literal: cap_exceeded.",
            b'{"categories": ["a"], "counts": [NaN]}\n',
            caps={"bytes_per_role": 10},
        ),
        hist_case(
            "order_histogram_json_before_content",
            "A member named twice and a negative count: json_invalid.",
            b'{"categories": ["a"], "counts": [-1], "counts": [-1]}\n',
        ),
        hist_case(
            "order_histogram_content_before_edges",
            "A negative count and equal edges: content_invalid.",
            content(edges=[0, 0], counts=[-1], underflow=0, overflow=0),
        ),
        hist_case(
            "order_histogram_edges_before_counts",
            "Equal edges and one count for two bins: edges_not_increasing.",
            content(edges=[0, 0, 1], counts=[1], underflow=0, overflow=0),
        ),
        hist_case(
            "order_histogram_counts_before_total",
            "Two counts for three categories, totaling 2^53: counts_length.",
            content(categories=["a", "b", "c"], counts=[2**53 - 1, 1]),
        ),
    ]


# ── The fallback ──────────────────────────────────────────────────────────


def fallback_cases() -> list[Case]:
    frames = b"\x93NUMPY\x01\x00"
    movie = view(
        "movie",
        "acme.scalp-movie",
        "A kind no renderer knows.",
        [
            data_entry("frames", f"{PREFIX}_frames.npy", frames),
            data_entry("labels", f"{PREFIX}_labels.tsv", LAYOUT),
            data_entry("broken", f"{PREFIX}_broken.tsv", CHANNELS + b"x\n"),
        ],
        parameters={"fps": 30},
    )
    computed = view(
        "activity",
        "acme.activity",
        "A computed view of a kind no renderer knows.",
        [],
        inputs=[
            {
                "role": "unmixing",
                "file": {
                    "location": f"{PREFIX}_unmixing.tsv",
                    "sha256": hashlib.sha256(NUMBERED).hexdigest(),
                    "size": len(NUMBERED),
                },
            },
            {
                "role": "signal",
                "store": {
                    "recording": "sub-01/eeg/sub-01_task-rest_eeg.edf",
                    "group": "eeg",
                    "content_sha256": "c" * 64,
                    "profile": "serving",
                },
            },
        ],
        transform={"name": "acme.activity.v1", "parameters": {}},
    )
    del computed["data"]
    missed = preset_spectrum()
    del missed["data"][0]["dims"]
    return [
        Case(
            "fallback_unknown_kind",
            "An unknown kind with no base: each TSV that meets the grammar is a "
            "table; the npy file and the broken TSV are offered for download only.",
            movie,
            {
                f"{PREFIX}_frames.npy": frames,
                f"{PREFIX}_labels.tsv": LAYOUT,
                f"{PREFIX}_broken.tsv": CHANNELS + b"x\n",
            },
        ),
        Case(
            "fallback_computed",
            "An unknown computed kind has no data to tabulate; its file input is "
            "offered for download, its store input is not a file.",
            computed,
            {},
        ),
        Case(
            "fallback_base_contract_missed",
            "An unknown kind over nemar.lines whose values carry no dims misses "
            "the base's role contract and shows as tables.",
            missed,
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: LAYOUT},
        ),
    ]


# ── Refusals: nothing drawn ───────────────────────────────────────────────


def refusals() -> list[Case]:
    wrong = SPECTRUM.replace(b"12.5", b"12.6")
    bad_layout = LAYOUT.replace(b"Cz", b"CZ")
    cases = [
        (
            "refusal_declaration_invalid",
            "A nemar.lines view with a base fails its kind schema: "
            "declaration_invalid.",
            lines_view(base="nemar.table", base_version=1),
            {SPECTRUM_AT: SPECTRUM},
        ),
        (
            "refusal_file_missing",
            "The values file is not there: file_missing.",
            lines_view(),
            {},
        ),
        (
            "refusal_file_size_mismatch",
            "One byte more than the declared size: file_size_mismatch.",
            lines_view(),
            {SPECTRUM_AT: SPECTRUM + b"\n"},
        ),
        (
            "refusal_file_digest_mismatch",
            "Same size, other bytes: file_digest_mismatch.",
            lines_view(),
            {SPECTRUM_AT: wrong},
        ),
        (
            "refusal_coordinate_file_digest_mismatch",
            "The layout a preset's labels come from is not the recorded file: "
            "file_digest_mismatch.",
            preset_spectrum(),
            {f"{PREFIX}_numbered.tsv": NUMBERED, LAYOUT_AT: bad_layout},
        ),
        (
            "refusal_fallback_file_digest_mismatch",
            "The fallback reads each TSV file, and a changed one refuses the view.",
            fallback_cases()[0].view,
            {
                f"{PREFIX}_frames.npy": b"",
                f"{PREFIX}_labels.tsv": bad_layout,
                f"{PREFIX}_broken.tsv": CHANNELS + b"x\n",
            },
        ),
        (
            "refusal_shared_location_digest",
            "The layout a preset's labels come from shares its location with the "
            "values and declares other bytes of their size: each entry is "
            "verified, so file_digest_mismatch (probe p2).",
            _shared_location(first="values"),
            {f"{PREFIX}_numbered.tsv": NUMBERED},
        ),
        (
            "refusal_shared_location_digest_first",
            "The same, with the entry that declares other bytes listed first: "
            "file_digest_mismatch.",
            _shared_location(first="layout"),
            {f"{PREFIX}_numbered.tsv": NUMBERED},
        ),
        (
            "refusal_caption_lone_surrogate",
            "A caption holding a lone surrogate meets the schema but has no "
            "digest: declaration_invalid.",
            lines_view() | {"caption": "Spectrum \ud800"},
            {SPECTRUM_AT: SPECTRUM},
        ),
        (
            "refusal_caption_noncharacter",
            "A caption holding the noncharacter U+FFFE: declaration_invalid.",
            lines_view() | {"caption": "Spectrum \ufffe"},
            {SPECTRUM_AT: SPECTRUM},
        ),
        (
            "refusal_preset_as_base",
            "An unknown kind over the preset nemar.spectrum: a preset is no base, "
            "so declaration_invalid (probe p2).",
            lines_view()
            | {"kind": "acme.spectrum2", "base": "nemar.spectrum", "base_version": 1},
            {SPECTRUM_AT: SPECTRUM},
        ),
        (
            "order_declaration_before_files",
            "An invalid declaration and no files: declaration_invalid, and no "
            "file is offered, since the declaration that names them is not valid.",
            lines_view(base="nemar.table", base_version=1),
            {},
        ),
    ]
    return [Case(*fields) for fields in cases]


# ── The verdict corpus ────────────────────────────────────────────────────


def _set(instance: dict, path: str, value) -> dict:
    """A copy with the value at a slash path set, or removed when value is DROP."""
    out = copy.deepcopy(instance)
    *parents, last = path.split("/")
    node = out
    for part in parents:
        node = node[int(part)] if isinstance(node, list) else node[part]
    key = int(last) if isinstance(node, list) else last
    if value is DROP:
        del node[key]
    else:
        node[key] = value
    return out


DROP = object()


def view_verdicts() -> list[tuple[str, str, dict]]:
    table = table_view(CHANNELS)
    lines = lines_view()
    heatmap = heatmap_view()
    hist = histogram_view(EDGES)
    unknown = fallback_cases()[0].view
    x_dim = "data/0/dims/0"
    dims = _set(
        unknown,
        "data/1/dims",
        [dim("sensor", "rows", "string", {"column": "name"})],
    )
    series_dim = "data/0/dims/1"
    return [
        ("envelope_unknown_kind", "An unknown kind passes on the envelope.", unknown),
        (
            "envelope_computed",
            "A computed view of an unknown kind, with inputs only.",
            fallback_cases()[1].view,
        ),
        ("envelope_no_caption", "caption is required.", _set(table, "caption", DROP)),
        ("envelope_key_pattern", "A key with a capital.", _set(table, "key", "Chan")),
        (
            "envelope_kind_pattern",
            "A kind with no namespace.",
            _set(unknown, "kind", "movie"),
        ),
        ("envelope_no_data", "Neither data nor inputs.", _set(unknown, "data", [])),
        (
            "envelope_reserved_scope",
            "A dataset scope without sources.",
            _set(unknown, "scope", "dataset"),
        ),
        (
            "envelope_recording_sources",
            "A recording view with sources.",
            _set(unknown, "sources", [{"record_sha256": "a" * 64}]),
        ),
        (
            "envelope_two_producers",
            "A source with both a plugin and a recipe.",
            _set(table, "source", PLUGIN | RECIPE),
        ),
        (
            "envelope_half_a_base",
            "A base without base_version.",
            _set(unknown, "base", "nemar.lines"),
        ),
        (
            "envelope_tsv_location",
            "A tsv file whose location ends .json.",
            _set(table, "data/0/location", "x/channels.json"),
        ),
        (
            "envelope_tsv_location_uppercase",
            "A tsv file whose location ends .TSV.",
            _set(table, "data/0/location", "x/channels.TSV"),
        ),
        (
            "envelope_tsv_extension_other_format",
            "A file named .tsv declared in another format (html): the extension "
            "names the format, in both directions.",
            _set(_set(unknown, "data/0/format", "html"), "data/0/location", "x/a.tsv"),
        ),
        (
            "envelope_json_extension_other_format",
            "A file named .JSON declared as csv.",
            _set(_set(unknown, "data/0/format", "csv"), "data/0/location", "x/a.JSON"),
        ),
        (
            "envelope_base_is_a_preset",
            "An unknown kind over the preset nemar.ic-classes: a preset is no base.",
            unknown | {"base": "nemar.ic-classes", "base_version": 1},
        ),
        (
            "envelope_unregistered_format",
            "A format the registry does not list, under its own extension, is "
            "valid: a renderer offers it for download only.",
            _set(_set(unknown, "data/0/format", "html"), "data/0/location", "x/a.html"),
        ),
        (
            "envelope_time_in_ms",
            "A time dimension in ms.",
            _set(lines, x_dim, FREQ | {"name": "time", "unit": "ms"}),
        ),
        (
            "envelope_column_with_tab",
            "A column name with a TAB.",
            _set(table, "data/0/columns/0/name", "a\tb"),
        ),
        (
            "envelope_serving_store_digest",
            "A serving-copy store input with no digest.",
            _set(fallback_cases()[1].view, "inputs/1/store/content_sha256", None),
        ),
        (
            "envelope_coords_two_forms",
            "Coordinates naming a column and the header at once.",
            _set(dims, "data/1/dims/0/coords", {"column": "name", "header": True}),
        ),
        (
            "envelope_coords_header_false",
            "header is only ever true.",
            _set(dims, "data/1/dims/0/coords", {"header": False}),
        ),
        (
            "envelope_axis",
            "An axis other than rows and columns.",
            _set(dims, "data/1/dims/0/axis", "depth"),
        ),
        (
            "envelope_location_percent",
            "A location with a percent escape, which a URL parser decodes: "
            "%2e%2e is ..",
            _set(table, "data/0/location", "%2e%2e/secret.tsv"),
        ),
        (
            "envelope_location_leading_space",
            "A location with a leading space, which a URL parser strips before "
            "it resolves ..",
            _set(table, "data/0/location", " ../x.tsv"),
        ),
        (
            "envelope_location_query",
            "A location with a ?, which would end the URL's path.",
            _set(table, "data/0/location", "x/t.tsv?x=1.tsv"),
        ),
        (
            "envelope_location_fragment",
            "A location with a #, which would end the URL's path.",
            _set(table, "data/0/location", "x/#t.tsv"),
        ),
        (
            "envelope_location_dot_segment",
            "A location with a . segment, another name for a file.",
            _set(table, "data/0/location", "x/./t.tsv"),
        ),
        (
            "envelope_location_empty_segment",
            "A location with an empty segment (//).",
            _set(table, "data/0/location", "x//t.tsv"),
        ),
        (
            "envelope_location_bidi",
            "A location with U+202E, which shows the name reversed.",
            _set(table, "data/0/location", "x/t\u202eqsv.tsv"),
        ),
        (
            "envelope_location_c1",
            "A location with the C1 control U+0085.",
            _set(table, "data/0/location", "x/t\u0085.tsv"),
        ),
        (
            "envelope_location_del",
            "A location with DEL, U+007F.",
            _set(table, "data/0/location", "x/t\u007f.tsv"),
        ),
        (
            "envelope_location_line_separator_dot_segment",
            "A line separator (U+2028) before a .. segment: a JavaScript . stops "
            "at it, so a lookahead written with . would not see the segment.",
            _set(table, "data/0/location", "x/a\u2028/../t.tsv"),
        ),
        (
            "envelope_location_line_separator_double_slash",
            "A line separator before an empty segment.",
            _set(table, "data/0/location", "x/a\u2028//t.tsv"),
        ),
        (
            "envelope_location_paragraph_separator",
            "A paragraph separator (U+2029) in a name.",
            _set(table, "data/0/location", "x/t\u2029.tsv"),
        ),
        (
            "envelope_location_space_inside",
            "A space inside a name, and dots that are no dot segment, are one "
            "file: valid.",
            _set(table, "data/0/location", "x/.. a/t b.tsv"),
        ),
        ("envelope_dims_valid", "An unknown kind with a dimension.", dims),
        (
            "envelope_plugin_name_with_dot",
            "A plugin named with a dot: plugin names take a metric prefix's "
            "grammar, so every plugin can name its metrics.",
            _set(
                unknown,
                "source",
                {"plugin": {"name": "org.nemar.quality", "version": "1.0.0"}},
            ),
        ),
        (
            "envelope_plugin_name_64",
            "A plugin name of 64 characters, the most.",
            _set(unknown, "source", {"plugin": {"name": "p" * 64, "version": "1.0.0"}}),
        ),
        (
            "envelope_plugin_name_65",
            "A plugin name of 65 characters.",
            _set(unknown, "source", {"plugin": {"name": "p" * 65, "version": "1.0.0"}}),
        ),
        (
            "envelope_kind_version_0",
            "kind_version starts at 1.",
            _set(unknown, "kind_version", 0),
        ),
        (
            "envelope_kind_version_1000",
            "kind_version is at most 999.",
            _set(unknown, "kind_version", 1000),
        ),
        (
            "envelope_kind_version_text",
            "kind_version is an integer, not text.",
            _set(unknown, "kind_version", "1"),
        ),
        (
            "envelope_size_0",
            "A file has at least one byte.",
            _set(table, "data/0/size", 0),
        ),
        (
            "envelope_size_at_cap",
            "A declared size of caps.bytes_per_role, 4,194,304 bytes.",
            _set(table, "data/0/size", 4194304),
        ),
        (
            "envelope_size_over_cap",
            "A declared size one byte over caps.bytes_per_role: a renderer never "
            "fetches it.",
            _set(table, "data/0/size", 4194305),
        ),
        (
            "envelope_sha256_uppercase",
            "A SHA-256 in capitals.",
            _set(table, "data/0/sha256", table["data"][0]["sha256"].upper()),
        ),
        (
            "envelope_sha256_short",
            "A SHA-256 of 63 digits.",
            _set(table, "data/0/sha256", table["data"][0]["sha256"][:63]),
        ),
        (
            "envelope_unit_empty",
            "An empty unit.",
            _set(table, "data/0/columns/0/unit", ""),
        ),
        (
            "envelope_column_type",
            "A column type other than number, integer and string.",
            _set(table, "data/0/columns/0/type", "float"),
        ),
        (
            "envelope_closed",
            "A member the envelope does not define.",
            table | {"figure": "x.png"},
        ),
        ("table_valid", "A nemar.table view.", table),
        (
            "table_wrong_role",
            "A table role named values.",
            _set(table, "data/0/role", "values"),
        ),
        (
            "table_json",
            "A table file in JSON.",
            _set(_set(table, "data/0/format", "json"), "data/0/location", "x/t.json"),
        ),
        (
            "table_no_columns",
            "A table role without columns.",
            _set(table, "data/0/columns", DROP),
        ),
        (
            "table_dims",
            "A table role with dims.",
            _set(table, "data/0/dims", [SENSOR]),
        ),
        (
            "table_parameters",
            "A table with a parameter.",
            _set(table, "parameters", {"sort": "name"}),
        ),
        ("lines_valid", "A nemar.lines view.", lines),
        (
            "lines_valid_empty_parameters",
            "Empty parameters are allowed.",
            _set(lines, "parameters", {}),
        ),
        (
            "lines_valid_time",
            "A time x dimension in seconds.",
            _set(
                _set(lines, x_dim, FREQ | {"name": "time", "unit": "s"}),
                "data/0/columns/0/unit",
                "s",
            ),
        ),
        (
            "lines_base",
            "A generic kind has no base.",
            lines | {"base": "nemar.table", "base_version": 1},
        ),
        (
            "lines_transform",
            "A generic kind has no transform.",
            lines | {"transform": {"name": "acme.x.v1", "parameters": {}}},
        ),
        (
            "lines_parameters",
            "Version 1 takes no parameters.",
            _set(lines, "parameters", {"log": True}),
        ),
        ("lines_one_dim", "Only the x dimension.", _set(lines, "data/0/dims", [FREQ])),
        (
            "lines_three_dims",
            "A third dimension.",
            _set(lines, "data/0/dims", [FREQ, SENSOR, SENSOR | {"name": "band"}]),
        ),
        (
            "lines_two_x_dims",
            "Two dimensions along the rows.",
            _set(lines, series_dim, FREQ | {"name": "band"}),
        ),
        (
            "lines_x_from_header",
            "x coordinates from the header.",
            _set(lines, x_dim, FREQ | {"coords": {"header": True}, "type": "string"}),
        ),
        (
            "lines_x_from_header_numeric",
            "Numeric x coordinates from the header.",
            _set(lines, f"{x_dim}/coords", {"header": True}),
        ),
        (
            "lines_x_from_role",
            "x coordinates from another role.",
            _set(lines, f"{x_dim}/coords", {"role": "layout", "column": "freq_hz"}),
        ),
        ("lines_x_text", "A text x dimension.", _set(lines, f"{x_dim}/type", "string")),
        (
            "lines_series_from_column",
            "Series coordinates from a column.",
            _set(lines, f"{series_dim}/coords", {"column": "freq_hz"}),
        ),
        (
            "lines_series_from_role",
            "A nemar.lines view has no other role to take series labels from.",
            _set(lines, f"{series_dim}/coords", {"role": "layout", "column": "name"}),
        ),
        (
            "lines_header_number",
            "Header coordinates typed number.",
            _set(lines, f"{series_dim}/type", "number"),
        ),
        (
            "lines_text_column",
            "A text value column.",
            _set(lines, "data/0/columns/1/type", "string"),
        ),
        (
            "lines_no_columns",
            "Columns are required.",
            _set(lines, "data/0/columns", DROP),
        ),
        (
            "lines_one_column",
            "At least an x column and one series.",
            _set(lines, "data/0/columns", [col("freq_hz", unit="Hz")]),
        ),
        ("lines_no_dims", "dims are required.", _set(lines, "data/0/dims", DROP)),
        ("lines_role", "The role is values.", _set(lines, "data/0/role", "series")),
        (
            "lines_two_files",
            "Exactly one file.",
            _set(
                lines,
                "data",
                [lines["data"][0], {**lines["data"][0], "role": "layout"}],
            ),
        ),
        ("heatmap_valid", "A nemar.heatmap view.", heatmap),
        (
            "heatmap_valid_absmax",
            "absmax limits.",
            _set(heatmap, "parameters", {"limits": "absmax"}),
        ),
        (
            "heatmap_limits",
            "An unknown limits rule.",
            _set(heatmap, "parameters", {"limits": "symmetric"}),
        ),
        (
            "heatmap_parameter",
            "A parameter heatmap does not define.",
            _set(heatmap, "parameters", {"colormap": "turbo"}),
        ),
        (
            "heatmap_rows_from_header",
            "Row coordinates from the header.",
            _set(heatmap, "data/0/dims/0/coords", {"header": True}),
        ),
        (
            "heatmap_columns_from_column",
            "Column coordinates from a column.",
            _set(heatmap, "data/0/dims/1/coords", {"column": "component"}),
        ),
        (
            "heatmap_rows_from_role",
            "A nemar.heatmap view has no other role to take row labels from.",
            _set(
                heatmap,
                "data/0/dims/0/coords",
                {"role": "components", "column": "label"},
            ),
        ),
        (
            "heatmap_one_dim",
            "One dimension.",
            _set(heatmap, "data/0/dims", [COMPONENT]),
        ),
        (
            "heatmap_inputs",
            "A heatmap is stored data only.",
            heatmap | {"inputs": fallback_cases()[1].view["inputs"]},
        ),
        ("histogram_valid", "A nemar.histogram view.", hist),
        (
            "histogram_tsv",
            "A histogram file in TSV.",
            _set(_set(hist, "data/0/format", "tsv"), "data/0/location", "x/h.tsv"),
        ),
        (
            "histogram_role",
            "The role is histogram.",
            _set(hist, "data/0/role", "values"),
        ),
        (
            "histogram_columns",
            "A JSON role has no columns.",
            _set(hist, "data/0/columns", [col("count", "integer")]),
        ),
        (
            "histogram_dims",
            "A histogram role has no dims.",
            _set(hist, "data/0/dims", [SENSOR]),
        ),
        (
            "histogram_parameters",
            "Version 1 takes no parameters.",
            _set(hist, "parameters", {"log": True}),
        ),
    ]


def data_quality_verdicts() -> list[tuple[str, str, dict]]:
    """A recording's dataQuality entry: the example, and the rules of the
    namespace a renderer that validates with ajv must agree on."""
    entry = json.loads(PRESET_EXAMPLE.read_text(encoding="utf-8"))
    ica = "recipes/nemar-ica"
    views = entry["recipes"]["nemar-ica"]["views"]
    archive = _set(
        _set(entry, f"{ica}/input_kind", "bids"), f"{ica}/profile", "archive"
    )
    metric = "nemar-quality:percentBrainComponents"
    skipped = {
        "key": "icactivity",
        "kind": "nemar.ic-activity",
        "reason": "labels_unusable",
    }
    return [
        ("dataquality_record", "The example's record entry.", entry),
        (
            "dataquality_root_closed",
            "A views list beside recipes at the root, which no schema would "
            "check: the root is closed (probe p11).",
            entry | {"views": copy.deepcopy(views)},
        ),
        (
            "dataquality_record_closed",
            "A member beside level and recipes, refused by the record shape too.",
            entry | {"dataset_level_counts": {"total": 3}},
        ),
        (
            "dataquality_store_profile_pairing",
            "An entry of the archive whose views name stores of the serving copy: "
            "a store's profile is its entry's.",
            archive,
        ),
        (
            "dataquality_views_skipped",
            "A view the run did not write for this recording, with the reason.",
            _set(entry, f"{ica}/views_skipped", [skipped]),
        ),
        (
            "dataquality_views_skipped_closed",
            "A skipped view is {key, kind, reason}, closed.",
            _set(entry, f"{ica}/views_skipped", [skipped | {"note": "x"}]),
        ),
        (
            "dataquality_views_skipped_reason",
            "A reason is a lowercase word.",
            _set(
                entry, f"{ica}/views_skipped", [skipped | {"reason": "Labels Unusable"}]
            ),
        ),
        (
            "dataquality_plugin_name_with_dot",
            "A metric's plugin named with a dot, which no metric name can prefix.",
            _set(entry, f"{ica}/metrics/{metric}/plugin/name", "org.nemar.quality"),
        ),
    ]


def content_verdicts() -> list[tuple[str, str, object]]:
    edges = json.loads(EDGES)
    cats = json.loads(ICLABEL)
    return [
        (
            "content_count_2_53_minus_1",
            "A count of 2^53 - 1, the largest every parser reads exactly.",
            cats | {"counts": [9007199254740991, *cats["counts"][1:]]},
        ),
        (
            "content_count_2_53_plus_1",
            "A count of 2^53 + 1, read as 2^53: over the cap.",
            cats | {"counts": [9007199254740993, *cats["counts"][1:]]},
        ),
        ("content_edges", "Bins by edges.", edges),
        (
            "content_edges_missing",
            "Values missing or not a number, counted apart.",
            edges | {"missing": 3},
        ),
        (
            "content_categories_missing",
            "A missing count beside bins by category.",
            cats | {"missing": 0},
        ),
        (
            "content_missing_negative",
            "A negative missing count.",
            edges | {"missing": -1},
        ),
        (
            "content_edges_no_unit",
            "unit is optional.",
            {k: v for k, v in edges.items() if k != "unit"},
        ),
        ("content_categories", "Bins by category.", cats),
        (
            "content_extra_member",
            "The root is open for presets.",
            cats | {"n_components": 35},
        ),
        (
            "content_no_underflow",
            "Bins by edges need underflow.",
            {k: v for k, v in edges.items() if k != "underflow"},
        ),
        (
            "content_both_forms",
            "Edges and categories together.",
            edges | {"categories": ["a"]},
        ),
        (
            "content_category_underflow",
            "Categories with underflow.",
            cats | {"underflow": 0},
        ),
        ("content_category_unit", "Categories with a unit.", cats | {"unit": "%"}),
        (
            "content_categories_repeated",
            "A category named twice.",
            cats | {"categories": ["a", "a"], "counts": [1, 2]},
        ),
        (
            "content_category_tab",
            "A category with a TAB.",
            cats | {"categories": ["a\tb"], "counts": [1]},
        ),
        (
            "content_category_newline",
            "A category ending in LF.",
            cats | {"categories": ["a\n"], "counts": [1]},
        ),
        (
            "content_category_empty",
            "An empty category.",
            cats | {"categories": [""], "counts": [1]},
        ),
        (
            "content_negative_count",
            "A negative count.",
            cats | {"counts": [-1, 0, 0, 0, 0, 0, 0]},
        ),
        (
            "content_fractional_count",
            "A count of 1.5.",
            cats | {"counts": [1.5, 0, 0, 0, 0, 0, 0]},
        ),
        (
            "content_count_beyond_2_53",
            "A count above 2^53 - 1.",
            cats | {"counts": [2**53, 0, 0, 0, 0, 0, 0]},
        ),
        (
            "content_one_edge",
            "One edge is no bin.",
            edges | {"edges": [0], "counts": [1]},
        ),
        ("content_no_counts", "Empty counts.", cats | {"counts": []}),
        ("content_text_edge", "An edge that is text.", edges | {"edges": ["0", 10]}),
        (
            "content_too_many_edges",
            "1,026 edges are 1,025 bins.",
            edges | {"edges": list(range(1026)), "counts": [0] * 1025},
        ),
        ("content_empty_unit", "An empty unit.", edges | {"unit": ""}),
        ("content_not_an_object", "Content is an object.", [1, 2]),
    ]


# ── The presets' verdicts ─────────────────────────────────────────────────


def preset_views() -> dict[str, dict]:
    """The example's five preset views, by key (examples/views)."""
    document = json.loads(PRESET_EXAMPLE.read_text(encoding="utf-8"))
    views = document["recipes"]["nemar-ica"]["views"]
    return {v["key"]: v for v in views}


def _archive_activity(activity: dict) -> dict:
    """The activations of a decomposition of the archive: matched by label, in
    microvolts, with no store digest and no decomposition store."""
    out = copy.deepcopy(activity)
    signal = next(i for i in out["inputs"] if i["role"] == "signal")
    signal["store"].update(profile="archive", content_sha256=None)
    out["transform"]["parameters"] |= {
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
    given = out["parameters"]["decomposition_input"]
    given["source"] = "archive"
    del given["store"]
    return out


def preset_verdicts() -> list[tuple[str, str, dict]]:
    views = preset_views()
    spectrum, maps = views["spectrum"], views["icmaps"]
    classes, activity, window = (
        views["icclasses"],
        views["icactivity"],
        views["midsegment"],
    )
    by_header = dim("sensor", "columns", "string", {"header": True})
    bare = _set(
        _set(spectrum, "data", spectrum["data"][:1]), "data/0/dims/1", by_header
    )
    archive = _archive_activity(activity)
    signal = next(i for i, x in enumerate(activity["inputs"]) if x["role"] == "signal")
    segments_at = next(
        i for i, x in enumerate(activity["inputs"]) if x["role"] == "badsegments"
    )
    without_segments = _set(
        _set(window, "inputs", window["inputs"][:2]),
        "parameters/bad_segment_table",
        False,
    )
    null_files = _set(
        _set(
            activity,
            "inputs",
            [i for i in activity["inputs"] if i["role"] != "badsegments"],
        ),
        "transform/parameters/shaded/files",
        None,
    )
    return [
        (
            "spectrum",
            "A plugin's spectrum, its sensors the recipe's layout rows.",
            spectrum,
        ),
        (
            "spectrum_without_layout",
            "Without a layout the sensors are the header names.",
            bare,
        ),
        (
            "spectrum_initial_maps_beyond_2_53",
            "Two frequencies, 9007199254740993 and 9007199254740992, which an exact "
            "reader holds distinct and JSON.parse reads as one binary64: on the "
            "binary64 reading they repeat (uniqueItems).",
            _set(
                spectrum,
                "parameters/initial_maps_hz",
                [9007199254740993, 9007199254740992],
            ),
        ),
        (
            "spectrum_freq_unit",
            "The dimension freq in kHz, not Hz.",
            _set(spectrum, "data/0/dims/0/unit", "kHz"),
        ),
        (
            "spectrum_freq_column_unit",
            "The column freq_hz in kHz.",
            _set(spectrum, "data/0/columns/0/unit", "kHz"),
        ),
        (
            "spectrum_sensor_unit",
            "A sensor column in uV^2/Hz, not dB.",
            _set(spectrum, "data/0/columns/1/unit", "uV^2/Hz"),
        ),
        (
            "spectrum_no_upper_hz",
            "upper_hz is required.",
            _set(spectrum, "parameters/upper_hz", DROP),
        ),
        (
            "spectrum_no_window",
            "The window is recorded.",
            _set(spectrum, "parameters/window", DROP),
        ),
        (
            "spectrum_no_overlap",
            "The overlap is recorded.",
            _set(spectrum, "parameters/overlap", DROP),
        ),
        (
            "spectrum_no_unit",
            "The unit is recorded.",
            _set(spectrum, "parameters/unit", DROP),
        ),
        (
            "spectrum_overlap_one",
            "An overlap of 1 is no step.",
            _set(spectrum, "parameters/overlap", 1),
        ),
        (
            "spectrum_method",
            "Version 1 records Welch's method.",
            _set(spectrum, "parameters/method", "multitaper"),
        ),
        (
            "spectrum_header_with_layout",
            "With a layout, the sensors are its rows, not the header.",
            _set(spectrum, "data/0/dims/1", by_header),
        ),
        (
            "spectrum_layout_coords_without_layout",
            "Sensors from a layout the view does not have.",
            _set(bare, "data/0/dims/1/coords", {"role": "layout", "column": "name"}),
        ),
        (
            "spectrum_x_from_a_role",
            "The x axis is the values' own column.",
            _set(
                spectrum, "data/0/dims/0/coords", {"role": "layout", "column": "radius"}
            ),
        ),
        (
            "spectrum_base",
            "A spectrum is drawn over nemar.lines.",
            _set(spectrum, "base", "nemar.heatmap"),
        ),
        (
            "spectrum_no_base",
            "A preset declares its base.",
            _set(_set(spectrum, "base", DROP), "base_version", DROP),
        ),
        (
            "spectrum_two_values",
            "The values once.",
            _set(spectrum, "data", [spectrum["data"][0], *spectrum["data"]]),
        ),
        ("ic_maps", "The recipe's component maps, layout and components table.", maps),
        (
            "ic_maps_no_layout",
            "Component maps need the layout.",
            _set(maps, "data", [maps["data"][0], maps["data"][2]]),
        ),
        (
            "ic_maps_no_components",
            "Component maps need the components table.",
            _set(maps, "data", maps["data"][:2]),
        ),
        (
            "ic_maps_sensors_by_name",
            "The sensors are the layout's rows, not a column of the values.",
            _set(maps, "data/0/dims/0/coords", {"column": "IC001"}),
        ),
        (
            "ic_maps_components_by_header",
            "The components are named by the header.",
            _set(
                maps,
                "data/0/dims/1/coords",
                {"role": "components", "column": "component"},
            ),
        ),
        (
            "ic_maps_components_dim",
            "The components table is named by its column component.",
            _set(maps, "data/2/dims/0/coords", {"column": "variance_pct"}),
        ),
        (
            "ic_maps_no_component_column",
            "The components table declares component.",
            _set(maps, "data/2/columns", maps["data"][2]["columns"][1:]),
        ),
        (
            "ic_maps_parameters",
            "Version 1 takes no parameters.",
            _set(maps, "parameters", {"limits": "minmax"}),
        ),
        ("ic_classes", "A plugin's class counts.", classes),
        (
            "ic_classes_tsv",
            "The class counts are a JSON file.",
            _set(
                _set(classes, "data/0/format", "tsv"),
                "data/0/location",
                classes["data"][0]["location"].replace(".json", ".tsv"),
            ),
        ),
        (
            "ic_classes_parameters",
            "Version 1 takes no parameters.",
            _set(classes, "parameters", {"threshold": 0.9}),
        ),
        (
            "ic_classes_base_version",
            "nemar.histogram version 1.",
            _set(classes, "base_version", 2),
        ),
        (
            "ic_activity",
            "Activations of a decomposition of the serving copy.",
            activity,
        ),
        (
            "ic_activity_archive",
            "Activations of a decomposition of the archive: "
            "matched by label, no digest.",
            archive,
        ),
        (
            "ic_activity_no_transform",
            "The transform is required.",
            _set(activity, "transform", DROP),
        ),
        (
            "ic_activity_other_transform",
            "The transform is nemar.ic-activity.v1.",
            _set(
                activity,
                "transform",
                {"name": "nemar.sensor-layout.v1", "parameters": {}},
            ),
        ),
        (
            "ic_activity_data",
            "Activations are never stored.",
            _set(activity, "data", classes["data"]),
        ),
        (
            "ic_activity_no_components",
            "The components label the rows.",
            _set(
                activity,
                "inputs",
                [i for i in activity["inputs"] if i["role"] != "components"],
            ),
        ),
        (
            "ic_activity_signal_as_file",
            "The signal is a store.",
            _set(
                activity,
                f"inputs/{signal}",
                {"role": "signal", "file": activity["inputs"][0]["file"]},
            ),
        ),
        (
            "ic_activity_rows_beyond_2_53",
            "Store rows of 2^53 + 1 and 2^53: over the cap on integers, and one "
            "binary64 twice (probe p9).",
            _set(
                activity,
                "transform/parameters/rows",
                [9007199254740993, 9007199254740992, *range(2, 7)],
            ),
        ),
        (
            "ic_activity_store_row_without_rows",
            "Matching by row names the rows.",
            _set(activity, "transform/parameters/rows", None),
        ),
        (
            "ic_activity_label_with_rows",
            "Matching by label names no rows.",
            _set(archive, "transform/parameters/rows", [0, 1]),
        ),
        (
            "ic_activity_archive_by_row",
            "A decomposition of the archive read no store rows.",
            _set(
                _set(archive, "transform/parameters/match", "store_row"),
                "transform/parameters/rows",
                [0],
            ),
        ),
        (
            "ic_activity_nanovolts",
            "The matrix's unit is one of the table's.",
            _set(activity, "transform/parameters/unit", "nV"),
        ),
        (
            "ic_activity_no_display_filter",
            "The display filter is declared.",
            _set(activity, "parameters/display_filter", DROP),
        ),
        (
            "ic_activity_filter_order",
            "The display filter is of order 2.",
            _set(activity, "parameters/display_filter/order", 4),
        ),
        (
            "ic_activity_window_60",
            "A window of at most 30 seconds.",
            _set(activity, "parameters/max_window_s", 60),
        ),
        (
            "ic_activity_no_decomposition_input",
            "What the decomposition got is declared.",
            _set(activity, "parameters/decomposition_input", DROP),
        ),
        (
            "ic_activity_serving_without_store",
            "A decomposition of the serving copy names its store.",
            _set(activity, "parameters/decomposition_input/store", DROP),
        ),
        (
            "ic_activity_archive_with_store",
            "A decomposition of the archive names no store.",
            _set(
                archive,
                "parameters/decomposition_input/store",
                activity["parameters"]["decomposition_input"]["store"],
            ),
        ),
        (
            "ic_activity_source_and_profile",
            "A decomposition of the archive with a store of profile serving.",
            _set(archive, f"inputs/{signal}", activity["inputs"][signal]),
        ),
        (
            "ic_activity_types_without_digest",
            "channel_types comes with its digest.",
            _set(activity, "parameters/decomposition_input/channel_types_sha256", DROP),
        ),
        (
            "ic_activity_no_channel_types",
            "The record states every row's type.",
            _set(activity, "parameters/decomposition_input/channel_types", DROP),
        ),
        (
            "ic_activity_no_shaded",
            "The browser_transform block names the shaded spans.",
            _set(activity, "transform/parameters/shaded", DROP),
        ),
        (
            "ic_activity_no_columns",
            "The browser_transform block names the matrix's columns.",
            _set(activity, "transform/parameters/columns", DROP),
        ),
        (
            "ic_activity_caption_empty",
            "A caption is text or null.",
            _set(activity, "transform/parameters/caption", ""),
        ),
        (
            "ic_activity_shaded_closed",
            "The shaded spans are {label, files}.",
            _set(activity, "transform/parameters/shaded/reason", "asr_burst_rejection"),
        ),
        (
            "ic_activity_no_segment_table",
            "The floor wrote no bad-segment table: shaded.files null, no input.",
            null_files,
        ),
        (
            "ic_activity_segments_named_not_declared",
            "The record names the bad-segment tables and the view does not declare "
            "the input.",
            _set(
                activity,
                "inputs",
                [i for i in activity["inputs"] if i["role"] != "badsegments"],
            ),
        ),
        (
            "ic_activity_segments_declared_not_named",
            "A bad-segments input when shaded.files is null.",
            _set(activity, "transform/parameters/shaded/files", None),
        ),
        (
            "ic_activity_shaded_names_the_sample_mask",
            "shaded.files names _samplemask.tsv beside _badsegments.tsv: it names "
            "the bad-segment table alone (nemar-process#81).",
            _set(
                activity,
                "transform/parameters/shaded/files",
                [
                    f"{PREFIX}_badsegments.tsv",
                    f"{PREFIX}_samplemask.tsv",
                ],
            ),
        ),
        (
            "ic_activity_shaded_names_two_tables",
            "shaded.files names two bad-segment tables: it names one, the input's.",
            _set(
                activity,
                "transform/parameters/shaded/files",
                [
                    f"{PREFIX}_badsegments.tsv",
                    "sub-01/eeg/sub-01_task-rest_desc-nemarfloor_badsegments.tsv",
                ],
            ),
        ),
        (
            "ic_activity_shaded_names_another_table",
            "shaded.files names a table that is not a _badsegments.tsv.",
            _set(activity, "transform/parameters/shaded/files", [f"{PREFIX}_mask.tsv"]),
        ),
        (
            "ic_activity_segments_input_another_table",
            "The badsegments input is not a _badsegments.tsv.",
            _set(
                activity,
                f"inputs/{segments_at}/file/location",
                f"{PREFIX}_segments.tsv",
            ),
        ),
        (
            "ic_activity_serving_matched_by_label",
            "A decomposition of the serving copy whose columns are matched by "
            "label: the serving copy is matched by its own rows, never by label.",
            _set(
                _set(
                    _set(activity, "transform/parameters/match", "label"),
                    "transform/parameters/rows",
                    None,
                ),
                "transform/parameters/caption",
                "not checked against the decomposition input",
            ),
        ),
        (
            "ic_activity_label_without_caption",
            "Columns matched by label with a null caption: the view must say "
            "they were not checked against the decomposition's input.",
            _set(archive, "transform/parameters/caption", None),
        ),
        (
            "ic_activity_transform_reused",
            "A kind the registry does not list, computed by nemar.ic-activity.v1: "
            "the envelope and the transform's schema apply.",
            _set(activity, "kind", "acme.activity"),
        ),
        (
            "ic_activity_transform_reused_without_parameters",
            "That kind with no parameters: the transform's schema requires the "
            "ones its computation reads (review r29).",
            _set(_set(activity, "kind", "acme.activity"), "parameters", DROP),
        ),
        (
            "ic_activity_transform_reused_drops_segments",
            "That kind drops the bad segments the record names: the transform's "
            "schema refuses it, whatever the kind (probe p14).",
            _set(
                _set(activity, "kind", "acme.activity"),
                "inputs",
                [i for i in activity["inputs"] if i["role"] != "badsegments"],
            ),
        ),
        (
            "ic_activity_preprocessing_closed",
            "A preprocessing step is {step, function}.",
            _set(
                activity,
                "parameters/decomposition_input/preprocessing/0/parameters",
                {"chans": 7},
            ),
        ),
        ("signal_window", "A recipe's midsegment window.", window),
        (
            "signal_window_without_segments",
            "The floor wrote no bad segments (bad_segment_table false): none declared.",
            without_segments,
        ),
        (
            "signal_window_no_channels",
            "The channels are required: the floor always writes them.",
            _set(window, "inputs", [window["inputs"][0], window["inputs"][2]]),
        ),
        (
            "signal_window_segments_named_not_declared",
            "The record names the bad segments and the view does not declare them.",
            _set(window, "inputs", window["inputs"][:2]),
        ),
        (
            "signal_window_segments_declared_not_named",
            "Bad segments declared when the record names none.",
            _set(window, "parameters/bad_segment_table", False),
        ),
        (
            "signal_window_no_table_flag",
            "Whether the floor wrote the bad segments is stated.",
            _set(window, "parameters/bad_segment_table", DROP),
        ),
        (
            "signal_window_long",
            "A window of at most 30 seconds.",
            _set(window, "parameters/duration_s", 60),
        ),
        (
            "signal_window_no_start",
            "The start is required.",
            _set(window, "parameters/start_s", DROP),
        ),
        (
            "signal_window_transform",
            "Nothing is computed.",
            _set(window, "transform", activity["transform"]),
        ),
        (
            "signal_window_no_signal",
            "The store is required.",
            _set(window, "inputs", window["inputs"][1:]),
        ),
        (
            "signal_window_other_input",
            "Only the store and the floor's tables.",
            _set(window, "inputs", [*window["inputs"], activity["inputs"][0]]),
        ),
    ]


def ic_classes_content_verdicts() -> list[tuple[str, str, object]]:
    counts = {
        "classifier": "ICLabel",
        "categories": json.loads(ICLABEL)["categories"],
        "counts": [12, 3, 2, 0, 1, 0, 4],
        "summed_variance_pct": [61.25, 9.5, 14.75, 0, 0.5, 0, 6.125],
        "n_components": 22,
    }
    edges = json.loads(EDGES)
    return [
        ("ic_classes_content", "Dominant counts with summed variance.", counts),
        (
            "ic_classes_content_negative_variance",
            "A component's variance share may be negative.",
            counts | {"summed_variance_pct": [-1.5, 0, 0, 0, 0, 0, 0]},
        ),
        (
            "ic_classes_content_extra_member",
            "The root is open.",
            counts | {"threshold": 0.9},
        ),
        (
            "ic_classes_content_no_classifier",
            "The classifier is named.",
            {k: v for k, v in counts.items() if k != "classifier"},
        ),
        (
            "ic_classes_content_iclabel_order",
            "With ICLabel, the classes are in ICLabel's order.",
            counts | {"categories": [*counts["categories"][1:], "Brain"]},
        ),
        (
            "ic_classes_content_iclabel_spelling",
            "With ICLabel, Line Noise is spelled as ICLabel spells it.",
            counts
            | {
                "categories": [
                    c.replace("Line Noise", "Line noise") for c in counts["categories"]
                ]
            },
        ),
        (
            "ic_classes_content_iclabel_six",
            "With ICLabel, all seven classes.",
            counts
            | {
                "categories": counts["categories"][:6],
                "counts": counts["counts"][:6],
                "summed_variance_pct": counts["summed_variance_pct"][:6],
            },
        ),
        (
            "ic_classes_content_other_classifier",
            "Another classifier names its own classes.",
            counts
            | {
                "classifier": "MARA",
                "categories": ["Artifact", "Brain"],
                "counts": [4, 18],
                "summed_variance_pct": [20.5, 79.5],
            },
        ),
        (
            "ic_classes_content_iclabel_lowercase",
            "ICLabel is spelled ICLabel, so a change of case cannot open its classes.",
            counts
            | {
                "classifier": "iclabel",
                "categories": ["a", "b", "c", "d", "e", "f", "g"],
            },
        ),
        (
            "ic_classes_content_classifier_cyrillic",
            "A classifier named ICLabel with a Cyrillic small ie (U+0435) for the e: "
            "not printable ASCII.",
            counts | {"classifier": "ICLab\u0435l", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_roman_numeral",
            "A classifier named ICLabel with the Roman numeral fifty (U+217C) "
            "for the l: "
            "not printable ASCII.",
            counts | {"classifier": "ICLabe\u217c", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_variation_selector",
            "A classifier named ICLabel with a variation selector (U+FE0F) after it: "
            "not printable ASCII.",
            counts | {"classifier": "ICLabel\ufe0f", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_fullwidth",
            "A classifier named ICLabel with fullwidth letters: not printable ASCII.",
            counts
            | {
                "classifier": "\uff29\uff23\uff2c\uff41\uff42\uff45\uff4c",
                "categories": list("abcdefg"),
            },
        ),
        (
            "ic_classes_content_classifier_combining",
            "A classifier named ICLabel with a combining grapheme joiner "
            "(U+034F) after it: "
            "not printable ASCII.",
            counts | {"classifier": "ICLabel\u034f", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_capital_i",
            "ICLabeI, a capital I for the last l: it reads as ICLabel, so it is "
            "held to ICLabel's spelling and refused.",
            counts | {"classifier": "ICLabeI", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_small_l",
            "lCLabel, a small l for the first I.",
            counts | {"classifier": "lCLabel", "categories": list("abcdefg")},
        ),
        (
            "ic_classes_content_classifier_ascii_name",
            "Another classifier's name in printable ASCII, with a space inside.",
            counts
            | {
                "classifier": "ICLabel Lite",
                "categories": counts["categories"],
            },
        ),
        (
            "ic_classes_content_category_cyrillic",
            "A category with a Cyrillic capital ve (U+0412) for the B of Brain: "
            "not printable ASCII.",
            counts
            | {
                "classifier": "MARA",
                "categories": ["\u0412rain", "Brain"],
                "counts": [4, 18],
                "summed_variance_pct": [20.5, 79.5],
            },
        ),
        (
            "ic_classes_content_category_padded",
            "A category with a space at its end.",
            counts
            | {
                "classifier": "MARA",
                "categories": ["Brain ", "Brain"],
                "counts": [4, 18],
                "summed_variance_pct": [20.5, 79.5],
            },
        ),
        (
            "ic_classes_content_no_variance",
            "summed_variance_pct is required.",
            {k: v for k, v in counts.items() if k != "summed_variance_pct"},
        ),
        (
            "ic_classes_content_no_n",
            "n_components is required.",
            {k: v for k, v in counts.items() if k != "n_components"},
        ),
        (
            "ic_classes_content_edges",
            "Classes are categories, not edges.",
            edges | {"summed_variance_pct": [1.0], "n_components": 3},
        ),
        (
            "ic_classes_content_unit",
            "Categories carry no unit (the histogram's rule).",
            counts | {"unit": "%"},
        ),
        (
            "ic_classes_content_zero_components",
            "At least one component.",
            counts | {"n_components": 0},
        ),
        (
            "ic_classes_content_text_variance",
            "A variance share is a number.",
            counts | {"summed_variance_pct": ["61.25", 9.5, 14.75, 0, 0.5, 0, 6.125]},
        ),
    ]


# ── The presets' own checks ───────────────────────────────────────────────


def _with_file(view: dict, role: str, data: bytes) -> dict:
    """A copy of the view whose data entry for the role names these bytes."""
    out = copy.deepcopy(view)
    entry = next(e for e in out["data"] if e["role"] == role)
    entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return out


def _location(view: dict, role: str) -> str:
    return next(e for e in view["data"] if e["role"] == role)["location"]


IC_COMPONENTS = [f"IC{i:03d}" for i in range(1, 7)]


def components_table(names: list[str], header: str = "component") -> bytes:
    rows = [f"{header} variance_pct brain other"]
    rows += [f"{name} {30 / (i + 1):.4f} 0.9 0.1" for i, name in enumerate(names)]
    return tsv(*rows)


def ic_maps_check_cases() -> list[Case]:
    maps = preset_views()["icmaps"]
    out = []
    for name, covers, data in [
        (
            "ic_maps",
            "The components table names the maps, in order.",
            components_table(IC_COMPONENTS),
        ),
        (
            "ic_maps_reordered",
            "Two components in the other order.",
            components_table([IC_COMPONENTS[1], IC_COMPONENTS[0], *IC_COMPONENTS[2:]]),
        ),
        (
            "ic_maps_short",
            "One component row fewer than the maps.",
            components_table(IC_COMPONENTS[:5]),
        ),
        (
            "ic_maps_long",
            "One component row more than the maps.",
            components_table([*IC_COMPONENTS, "IC007"]),
        ),
        (
            "ic_maps_renamed",
            "IC1 is not IC001: names compare as text.",
            components_table([f"IC{i}" for i in range(1, 7)]),
        ),
        (
            "ic_maps_no_column",
            "The file has no column component (the generic word).",
            components_table(IC_COMPONENTS, header="name"),
        ),
        (
            "ic_maps_ragged",
            "A row with a cell missing (the generic word).",
            components_table(IC_COMPONENTS) + b"IC007\t1\n",
        ),
    ]:
        view = _with_file(maps, "components", data)
        out.append(Case(name, covers, view, {_location(view, "components"): data}))
    table = components_table(IC_COMPONENTS)
    view = _with_file(maps, "components", table)
    out.append(
        Case(
            "ic_maps_components_too_many_cells",
            "A components table over a cap on cells lowered to 20, every header "
            "column counted: cap_exceeded, drawn by its base.",
            view,
            {_location(view, "components"): table},
            caps={"cells_per_role": 20},
        )
    )
    unnamed = components_table(IC_COMPONENTS, header="name")
    view = _with_file(maps, "components", unnamed)
    out.append(
        Case(
            "ic_maps_order_cap_before_column",
            "Over the cap on cells and no column component: cap_exceeded.",
            view,
            {_location(view, "components"): unnamed},
            caps={"cells_per_role": 20},
        )
    )
    view = _with_file(maps, "components", components_table(IC_COMPONENTS))
    tampered = components_table(IC_COMPONENTS).replace(b"0.9", b"0.8", 1)
    out.append(
        Case(
            "ic_maps_digest",
            "The components file is not the one recorded.",
            view,
            {_location(view, "components"): tampered},
        )
    )
    return out


SPECTRUM_SENSORS = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3"]


def spectrum_values(names: list[str]) -> bytes:
    """A spectrum from 0.5 Hz (the 0 Hz row excluded), one column per sensor."""
    rows = [
        f"{f} " + " ".join(f"{10 - i - k:.1f}" for k in range(len(names)))
        for i, f in enumerate((0.5, 1, 1.5))
    ]
    return tsv(" ".join(["freq_hz", *names]), *rows)


def spectrum_layout(names: list[str]) -> bytes:
    rows = [f"{n} {18 * i - 54} 0.4 EEG" for i, n in enumerate(names)]
    return tsv("name theta_deg radius sensor_type", *rows)


def spectrum_check_cases() -> list[Case]:
    spectrum = preset_views()["spectrum"]
    values = spectrum_values(SPECTRUM_SENSORS)
    out = []
    for name, covers, layout in [
        (
            "spectrum",
            "The values' sensor columns are the layout's names, in order.",
            spectrum_layout(SPECTRUM_SENSORS),
        ),
        (
            "spectrum_sensors_reordered",
            "The layout's rows in another order than the values' columns: each "
            "spectrum would be drawn under another sensor's name, so "
            "sensors_mismatch, shown as the fallback (probe p16).",
            spectrum_layout([*SPECTRUM_SENSORS[1:], SPECTRUM_SENSORS[0]]),
        ),
        (
            "spectrum_sensors_renamed",
            "FP1 in the layout where the values say Fp1: names compare as text.",
            spectrum_layout(["FP1", *SPECTRUM_SENSORS[1:]]),
        ),
    ]:
        view = _with_file(_with_file(spectrum, "values", values), "layout", layout)
        files = {_location(view, "values"): values, _location(view, "layout"): layout}
        out.append(Case(name, covers, view, files))
    bare = copy.deepcopy(spectrum)
    bare["data"] = bare["data"][:1]
    bare["data"][0]["dims"][1]["coords"] = {"header": True}
    view = _with_file(bare, "values", values)
    out.append(
        Case(
            "spectrum_without_layout",
            "No layout: the sensors are the header's names, and there is nothing "
            "to compare.",
            view,
            {_location(view, "values"): values},
        )
    )
    falling = spectrum_values(SPECTRUM_SENSORS).replace(b"\n1\t", b"\n0.25\t", 1)
    layout = spectrum_layout(["FP1", *SPECTRUM_SENSORS[1:]])
    view = _with_file(_with_file(spectrum, "values", falling), "layout", layout)
    out.append(
        Case(
            "spectrum_base_before_sensors",
            "Frequencies that fall (x_not_increasing) and a layout that names "
            "other sensors: the base refuses first, so the base's word, shown as "
            "the fallback.",
            view,
            {_location(view, "values"): falling, _location(view, "layout"): layout},
        )
    )
    return out


def ic_classes_check_cases() -> list[Case]:
    classes = preset_views()["icclasses"]
    good = {
        "classifier": "ICLabel",
        "categories": json.loads(ICLABEL)["categories"],
        "counts": [12, 3, 2, 0, 1, 0, 4],
        "summed_variance_pct": [61.25, 9.5, 14.75, 0, 0.5, 0, 6.125],
        "n_components": 22,
    }
    other = {
        "classifier": "MARA",
        "categories": ["Artifact", "Brain"],
        "counts": [4, 18],
        "summed_variance_pct": [20.5, 79.5],
        "n_components": 22,
    }
    out = []
    for name, covers, members in [
        ("ic_classes", "ICLabel's classes, counts that sum to n_components.", good),
        ("ic_classes_other_classifier", "Another classifier's own classes.", other),
        (
            "ic_classes_iclabel_order",
            "ICLabel's classes out of order: the histogram draws, the preset refuses.",
            good | {"categories": [*good["categories"][1:], "Brain"]},
        ),
        (
            "ic_classes_no_variance",
            "No summed_variance_pct: a histogram content, not this preset's.",
            {k: v for k, v in good.items() if k != "summed_variance_pct"},
        ),
        (
            "ic_classes_variance_length",
            "Six summed variances for seven classes.",
            good | {"summed_variance_pct": good["summed_variance_pct"][:6]},
        ),
        (
            "ic_classes_components_total",
            "Counts that sum to 22 with n_components 21.",
            good | {"n_components": 21},
        ),
        (
            "ic_classes_order_variance_before_total",
            "Both faults: the variance length comes first.",
            good | {"summed_variance_pct": [1.0], "n_components": 21},
        ),
        (
            "ic_classes_order_content_before_variance",
            "Both faults, ICLabel's classes out of order and six summed variances: "
            "the content schema comes first.",
            good
            | {
                "categories": [*good["categories"][1:], "Brain"],
                "summed_variance_pct": good["summed_variance_pct"][:6],
            },
        ),
        (
            "ic_classes_order_content_before_total",
            "Both faults: the content schema comes first.",
            good | {"classifier": "", "n_components": 21},
        ),
        (
            "ic_classes_base_refuses",
            "Six counts for seven classes: the base refuses "
            "first and the view falls back.",
            good | {"counts": good["counts"][:6]},
        ),
    ]:
        data = content(**members)
        view = _with_file(classes, "histogram", data)
        out.append(Case(name, covers, view, {_location(view, "histogram"): data}))
    return out


FLOOR_CHANNELS = tsv(
    "name type status status_description nemar_reason",
    "Fp1 EEG good n/a n/a",
    "Fp2 EEG good n/a n/a",
    "F3 EEG good n/a n/a",
    "F4 EEG good n/a n/a",
    "C3 EEG good n/a n/a",
    "C4 EEG good n/a n/a",
    "P3 EEG good n/a n/a",
    "P4 EEG bad flat flatline",
    "ECG ECG n/a non-signal not_assessed",
)
STORE_LABELS = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "ECG"]
FLOOR_SEGMENTS = tsv(
    "onset duration label nemar_reason",
    "151.700000 0.300000 bad_window clean_windows",
    "152.100000 0.050000 burst asr_repaired",
)


def _with_input(view: dict, role: str, data: bytes) -> dict:
    """A copy of the view whose file input for the role names these bytes."""
    out = copy.deepcopy(view)
    entry = next(i for i in out["inputs"] if i["role"] == role)["file"]
    entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return out


def _input_at(view: dict, role: str) -> str:
    return next(i for i in view["inputs"] if i["role"] == role)["file"]["location"]


def _relocated(case: tuple, role: str, location: str) -> tuple:
    """A signal window case whose table for the role sits at another location."""
    view, files, store, caps = copy.deepcopy(case)
    entry = next(i for i in view["inputs"] if i["role"] == role)["file"]
    files[location] = files.pop(entry["location"])
    entry["location"] = location
    return view, files, store, caps


def _recorded_as(case: tuple, recording: str) -> tuple:
    """A signal window case whose store is that of another recording path."""
    view, files, store, caps = copy.deepcopy(case)
    signal = next(i for i in view["inputs"] if i["role"] == "signal")["store"]
    signal["recording"] = recording
    return view, files, store, caps


def _dropped(case: tuple, role: str) -> tuple:
    """A signal window case that does not declare its table for the role."""
    view, files, store, caps = copy.deepcopy(case)
    view["inputs"] = [i for i in view["inputs"] if i["role"] != role]
    return view, files, store, caps


def signal_window_check_cases() -> list[tuple[str, str, dict, dict, dict]]:
    window = preset_views()["midsegment"]
    declared = next(i for i in window["inputs"] if i["role"] == "signal")["store"][
        "content_sha256"
    ]

    def at(
        start_s,
        duration_s,
        samples=75000,
        rate=250.0,
        published=declared,
        channels=FLOOR_CHANNELS,
        segments=FLOOR_SEGMENTS,
        recorded=None,
        caps=None,
        labels=STORE_LABELS,
    ):
        """A window with the floor's tables; recorded, when given, maps a role
        to the bytes the view declares in place of the bytes served."""
        view = _set(
            _set(
                _set(window, "parameters/start_s", start_s),
                "parameters/duration_s",
                duration_s,
            ),
            "parameters/bad_segment_table",
            segments is not None,
        )
        files = {}
        for role, data in (("channels", channels), ("badsegments", segments)):
            if data is None:
                view["inputs"] = [i for i in view["inputs"] if i["role"] != role]
                continue
            view = _with_input(view, role, (recorded or {}).get(role, data))
            files[_input_at(view, role)] = data
        store = {
            "labels": labels,
            "samples": samples,
            "rate": rate,
            "published_sha256": published,
        }
        return view, files, store, caps or {}

    tampered = FLOOR_SEGMENTS.replace(b"0.300000", b"0.310000", 1)
    no_label = tsv("onset duration nemar_reason", "151.700000 0.300000 clean_windows")
    no_status = tsv("name type", "Fp1 EEG")
    ragged = FLOOR_SEGMENTS + b"153\n"
    return [
        (
            "signal_window",
            "Two seconds at 151.5 s, the digest published and "
            "matching, with the floor's bad channel and both its segments.",
            *at(151.5, 2),
        ),
        (
            "signal_window_not_checked",
            "The serving copy publishes no digest.",
            *at(151.5, 2, published=None),
        ),
        (
            "signal_window_no_bad_segment_table",
            "The floor wrote no bad segments: drawn, the bad channel marked, and "
            "the note that nothing is marked as a bad segment.",
            *at(151.5, 2, segments=None),
        ),
        (
            "signal_window_columns_reordered",
            "Both tables' columns in another order: found by name.",
            *at(
                151.5,
                2,
                channels=tsv(
                    "status name type",
                    *[f"good {n} EEG" for n in ("Fp1", "Fp2", "F3", "F4", "C3")],
                    *[f"good {n} EEG" for n in ("C4", "P3")],
                    "bad P4 EEG",
                    "n/a ECG ECG",
                ),
                segments=tsv(
                    "label onset duration nemar_reason",
                    "bad_window 151.700000 0.300000 clean_windows",
                    "burst 152.100000 0.050000 asr_repaired",
                ),
            ),
        ),
        (
            "signal_window_bad_channel_unknown",
            "A bad channel named p4 where the store has P4: names compare as "
            "exact strings, and an unknown bad channel refuses the view.",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"P4", b"p4", 1)),
        ),
        (
            "signal_window_order_channels_file_before_segments_file",
            "A channels file of the wrong size and bad segments of the wrong "
            "digest: the channels file is checked first.",
            *at(
                151.5,
                2,
                channels=FLOOR_CHANNELS + b"F4\tEEG\tgood\tn/a\tn/a\n",
                segments=tampered,
                recorded={"channels": FLOOR_CHANNELS, "badsegments": FLOOR_SEGMENTS},
            ),
        ),
        (
            "signal_window_order_channels_before_segments",
            "Channels with no status and an onset that is no number: the channels "
            "are read first.",
            *at(
                151.5,
                2,
                channels=no_status,
                segments=tsv("onset duration label", "n/a 0.300000 bad_window"),
            ),
        ),
        (
            "signal_window_onset_before_duration",
            "An onset that is no number and a duration beyond binary64: the onset "
            "column is read first.",
            *at(151.5, 2, segments=tsv("onset duration label", "n/a 1e400 burst")),
        ),
        (
            "signal_window_order_tables_before_bad_channels",
            "Bad segments with no label and an unknown bad channel: the tables "
            "come first.",
            *at(
                151.5,
                2,
                channels=FLOOR_CHANNELS.replace(b"P4", b"p4", 1),
                segments=no_label,
            ),
        ),
        (
            "signal_window_order_bad_channels_before_window",
            "An unknown bad channel and a window outside the recording: the bad "
            "channels come first.",
            *at(300, 2, channels=FLOOR_CHANNELS.replace(b"P4", b"p4", 1)),
        ),
        (
            "signal_window_digest_mismatch",
            "The serving copy publishes another digest.",
            *at(151.5, 2, published="f" * 64),
        ),
        (
            "signal_window_badsegments_digest",
            "The bad segments are not the file "
            "recorded: nothing is drawn, never a window unmarked.",
            *at(151.5, 2, segments=tampered, recorded={"badsegments": FLOOR_SEGMENTS}),
        ),
        (
            "signal_window_channels_digest",
            "The channels table is not the file recorded.",
            *at(
                151.5,
                2,
                channels=FLOOR_CHANNELS.replace(b"bad", b"bed", 1),
                recorded={"channels": FLOOR_CHANNELS},
            ),
        ),
        (
            "signal_window_badsegments_no_label",
            "The bad segments have no column label.",
            *at(151.5, 2, segments=no_label),
        ),
        (
            "signal_window_channels_no_status",
            "The channels table has no column status.",
            *at(151.5, 2, channels=no_status),
        ),
        (
            "signal_window_badsegments_onset_text",
            "A bad segment whose onset is not a number.",
            *at(
                151.5,
                2,
                segments=tsv("onset duration label", "n/a 0.300000 bad_window"),
            ),
        ),
        (
            "signal_window_tables_too_many_bytes",
            "A floor table longer than a cap on bytes lowered to 100.",
            *at(151.5, 2, caps={"bytes_per_role": 100}),
        ),
        (
            "signal_window_tables_too_many_cells",
            "Floor tables over a cap on cells lowered to 12.",
            *at(151.5, 2, caps={"cells_per_role": 12}),
        ),
        (
            "signal_window_badsegments_ragged",
            "A bad segments row with one cell.",
            *at(151.5, 2, segments=ragged),
        ),
        (
            "signal_window_clipped",
            "A window past the recording's end is clipped.",
            *at(299.5, 2),
        ),
        (
            "signal_window_outside",
            "A window that starts at the recording's end.",
            *at(300, 2),
        ),
        (
            "signal_window_between_samples",
            "A window between two samples holds none.",
            *at(0.001, 0.002),
        ),
        (
            "signal_window_odd_rate",
            "Times k / rate at 500/7 Hz, where ceil(start * "
            "rate) would start a sample late and end a sample early.",
            *at(0.098, 0.364, samples=100, rate=500 / 7),
        ),
        (
            "signal_window_tables_elsewhere",
            "The channels table, named for the recording, in another directory: "
            "table_location_mismatch, never a window marked by another "
            "recording's decisions.",
            *_relocated(
                at(151.5, 2),
                "channels",
                "sub-01/meg/sub-01_task-rest_desc-nemarica_channels.tsv",
            ),
        ),
        (
            "signal_window_tables_another_recording",
            "Both tables beside the recording but named for another recording "
            "(task-other): table_location_mismatch.",
            *_relocated(
                _relocated(
                    at(151.5, 2),
                    "channels",
                    "sub-01/eeg/sub-01_task-other_desc-nemarica_channels.tsv",
                ),
                "badsegments",
                "sub-01/eeg/sub-01_task-other_desc-nemarica_badsegments.tsv",
            ),
        ),
        (
            "signal_window_tables_two_stems",
            "A bad segments table under another stem than the channels' "
            "(the floor's beside the decomposition's): table_location_mismatch.",
            *_relocated(
                at(151.5, 2),
                "badsegments",
                "sub-01/eeg/sub-01_task-rest_desc-nemarfloor_badsegments.tsv",
            ),
        ),
        (
            "signal_window_tables_run",
            "Both tables of run 2 (sub-01_task-rest_run-2), whose name begins "
            "with the recording's entities: "
            "after the entities only _desc-<label> may follow, so "
            "table_location_mismatch (review r29).",
            *_relocated(
                _relocated(
                    at(151.5, 2),
                    "channels",
                    "sub-01/eeg/sub-01_task-rest_run-2_desc-nemarica_channels.tsv",
                ),
                "badsegments",
                "sub-01/eeg/sub-01_task-rest_run-2_desc-nemarica_badsegments.tsv",
            ),
        ),
        (
            "signal_window_tables_task_prefix",
            "Both tables of task restingstate, whose name begins with "
            "sub-01_task-rest: "
            "after the entities only _desc-<label> may follow, so "
            "table_location_mismatch (review r29).",
            *_relocated(
                _relocated(
                    at(151.5, 2),
                    "channels",
                    "sub-01/eeg/sub-01_task-restingstate_desc-nemarica_channels.tsv",
                ),
                "badsegments",
                "sub-01/eeg/sub-01_task-restingstate_desc-nemarica_badsegments.tsv",
            ),
        ),
        (
            "signal_window_tables_acq",
            "Both tables of acquisition other (sub-01_task-rest_acq-other): "
            "after the entities only _desc-<label> may follow, so "
            "table_location_mismatch (review r29).",
            *_relocated(
                _relocated(
                    at(151.5, 2),
                    "channels",
                    "sub-01/eeg/sub-01_task-rest_acq-other_desc-nemarica_channels.tsv",
                ),
                "badsegments",
                "sub-01/eeg/sub-01_task-rest_acq-other_desc-nemarica_badsegments.tsv",
            ),
        ),
        (
            "signal_window_tables_desc_recording",
            "A recording whose last entity is a desc (desc-clean): the tables "
            "append the label to its value (desc-cleannemarica), as nemar-process "
            "names them, and are the recording's.",
            *_recorded_as(
                _relocated(
                    _relocated(
                        at(151.5, 2),
                        "channels",
                        "sub-01/eeg/sub-01_task-rest_desc-cleannemarica_channels.tsv",
                    ),
                    "badsegments",
                    "sub-01/eeg/sub-01_task-rest_desc-cleannemarica_badsegments.tsv",
                ),
                "sub-01/eeg/sub-01_task-rest_desc-clean_eeg.set",
            ),
        ),
        (
            "signal_window_channel_row_missing",
            "The store has a row ECG that the channels table does not name: a "
            "floor decision dropped, so channel_row_missing, never a channel "
            "drawn with no decision (review r29).",
            *at(
                151.5,
                2,
                channels=FLOOR_CHANNELS.replace(
                    b"ECG\tECG\tn/a\tnon-signal\tnot_assessed\n", b""
                ),
            ),
        ),
        (
            "signal_window_order_bad_channel_before_row_missing",
            "A bad channel p4 no store row has, and the store's P4 with no row: "
            "bad_channel_unknown comes first.",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"P4", b"p4", 1)),
        ),
        (
            "signal_window_order_row_missing_before_window",
            "The store's ECG with no row and a window at the recording's end: the "
            "channel rows come first.",
            *at(
                300,
                2,
                channels=FLOOR_CHANNELS.replace(
                    b"ECG\tECG\tn/a\tnon-signal\tnot_assessed\n", b""
                ),
            ),
        ),
        (
            "signal_window_declaration_invalid",
            "bad_segment_table true and no bad segments declared: declaration_invalid.",
            *_dropped(at(151.5, 2), "badsegments"),
        ),
        (
            "signal_window_order_declaration_before_locations",
            "An invalid declaration and the channels of another directory: the "
            "declaration comes first.",
            *_dropped(
                _relocated(
                    at(151.5, 2),
                    "channels",
                    "sub-01/meg/sub-01_task-rest_desc-nemarica_channels.tsv",
                ),
                "badsegments",
            ),
        ),
        (
            "signal_window_order_locations_before_files",
            "The channels of another directory and a bad segments file that is not "
            "the one recorded: the locations come first.",
            *_relocated(
                at(
                    151.5,
                    2,
                    segments=tampered,
                    recorded={"badsegments": FLOOR_SEGMENTS},
                ),
                "channels",
                "sub-01/meg/sub-01_task-rest_desc-nemarica_channels.tsv",
            ),
        ),
        (
            "signal_window_status_uppercase",
            "A channel whose status is 'BAD': not good, bad or n/a, so "
            "channel_status_unknown, never read as good (probe p8).",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\tBAD\t")),
        ),
        (
            "signal_window_status_capitalized",
            "A channel whose status is 'Bad': not good, bad or n/a, so "
            "channel_status_unknown, never read as good (probe p8).",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\tBad\t")),
        ),
        (
            "signal_window_status_excluded",
            "A channel whose status is 'excluded': not good, bad or n/a, so "
            "channel_status_unknown, never read as good (probe p8).",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\texcluded\t")),
        ),
        (
            "signal_window_status_padded",
            "A channel whose status is 'bad ': not good, bad or n/a, so "
            "channel_status_unknown, never read as good (probe p8).",
            *at(151.5, 2, channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\tbad \t")),
        ),
        (
            "signal_window_segment_duration_negative",
            "A bad segment of negative duration: duration_not_positive.",
            *at(
                151.5, 2, segments=tsv("onset duration label", "151.7 -0.3 bad_window")
            ),
        ),
        (
            "signal_window_segment_duration_zero",
            "A bad segment of no duration: duration_not_positive.",
            *at(151.5, 2, segments=tsv("onset duration label", "151.7 0 bad_window")),
        ),
        (
            "signal_window_rate_zero",
            "A store whose rate is 0: rate_invalid, not a division by zero (probe p8).",
            *at(151.5, 2, rate=0.0),
        ),
        (
            "signal_window_rate_negative",
            "A store whose rate is below 0: rate_invalid.",
            *at(151.5, 2, rate=-250.0),
        ),
        (
            "signal_window_order_digest_before_rate",
            "A digest mismatch and a rate of 0: the digest comes first.",
            *at(151.5, 2, published="f" * 64, rate=0.0),
        ),
        (
            "signal_window_order_rate_before_tables",
            "A rate of 0 and a channel status BAD: the rate comes first.",
            *at(
                151.5,
                2,
                rate=0.0,
                channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\tBAD\t"),
            ),
        ),
        (
            "signal_window_order_status_before_segments",
            "A channel status BAD and a bad segment of negative duration: the "
            "channels are read first.",
            *at(
                151.5,
                2,
                channels=FLOOR_CHANNELS.replace(b"\tbad\t", b"\tBAD\t"),
                segments=tsv("onset duration label", "151.7 -0.3 bad_window"),
            ),
        ),
        (
            "signal_window_order_files_before_digest",
            "Both faults: the file comes first.",
            *at(
                151.5,
                2,
                published="f" * 64,
                segments=tampered,
                recorded={"badsegments": FLOOR_SEGMENTS},
            ),
        ),
        (
            "signal_window_order_digest_before_tables",
            "Both faults: the digest comes first.",
            *at(151.5, 2, published="f" * 64, segments=no_label),
        ),
        (
            "signal_window_order_tables_before_window",
            "Both faults: the tables come first.",
            *at(300, 2, segments=no_label),
        ),
        (
            "signal_window_order",
            "Both faults: the digest before the window.",
            *at(300, 2, published="f" * 64),
        ),
    ]


def preset_checks() -> dict:
    cases = []
    for case in [
        *spectrum_check_cases(),
        *ic_maps_check_cases(),
        *ic_classes_check_cases(),
    ]:
        expected = check_preset(case.view, case.files, case.registry())
        cases.append(_header(case) | {"expected": expected})
    for name, covers, view, files, store, caps in signal_window_check_cases():
        registry = REGISTRY | {"caps": REGISTRY["caps"] | caps}
        expected = check_preset(view, files, registry, store)
        cases.append(
            {
                "name": name,
                "covers": covers,
                "view": view,
                "files": _encoded(files),
                "store": store,
            }
            | ({"caps": caps} if caps else {})
            | {"expected": expected}
        )
    names = [c["name"] for c in cases]
    if len(names) != len(set(names)):
        raise AssertionError("case names repeat")
    return {
        "format": PRESET_CHECKS_FORMAT,
        "spec": "docs/views/presets.md",
        "description": (
            "The checks a renderer of a preset runs beyond its base. For each case, "
            "decode files (UTF-8 text), run the preset's checks on view (for a "
            "signal window, with store: the recording's samples, its rate and the "
            "digest the serving copy publishes, or null) and compare with expected: "
            "word null when they pass (with the state, the window's first "
            "sample and count, the bad channels and the segments for a signal "
            "window), else the word and its outcome: "
            "base (drawn by its base, with the word), nothing (nothing drawn) or "
            "fallback (shown as the fallback's tables: the base itself refused the "
            "file first, or the base's drawing would mislead). A case's caps take "
            "the place of the registry's caps of the same names for that case."
        ),
        "cases": cases,
    }


def _errors(validator, instance) -> list[list[str]]:
    """jsonschema's errors on the binary64 reading of the instance (the
    validators read it so): what an engine that parses the vectors file with
    JSON.parse checks."""
    pairs = {
        (e.validator, "/".join(str(p) for p in e.absolute_path))
        for e in validator.iter_errors(instance)
    }
    return [list(pair) for pair in sorted(pairs)]


def verdicts() -> dict:
    cases = []
    for schema, validator, items in [
        ("view", view_validator(), [*view_verdicts(), *preset_verdicts()]),
        ("dataQuality", data_quality_validator(), data_quality_verdicts()),
        (HISTOGRAM_CONTENT, histogram_content_validator(), content_verdicts()),
        (
            IC_CLASSES_CONTENT,
            content_validator(IC_CLASSES_CONTENT),
            ic_classes_content_verdicts(),
        ),
    ]:
        for name, covers, instance in items:
            errors = _errors(validator, instance)
            cases.append(
                {
                    "name": name,
                    "covers": covers,
                    "schema": schema,
                    "instance": instance,
                    "valid": not errors,
                    "errors": errors,
                }
            )
    return {
        "format": VERDICTS_FORMAT,
        "spec": SPEC,
        "description": (
            "Declarations and contents with jsonschema's verdicts, for a renderer "
            "that checks them without a JSON Schema engine, or with another one. "
            "Each verdict is on the "
            "binary64 reading of the instance, as JSON.parse reads it, so an integer "
            "beyond 2^53 is checked as the nearest binary64. schema view means "
            "schema/definitions/view.schema.json#/$defs/view, dataQuality "
            "schema/extensions/dataQuality.schema.json; any other schema is "
            "a file in schema/views/. Only valid binds an implementation; errors "
            "list each failing keyword and instance path jsonschema reports."
        ),
        "cases": cases,
    }


# ── The model vectors ─────────────────────────────────────────────────────


def _header(case: Case) -> dict:
    out = {
        "name": case.name,
        "covers": case.covers,
        "view": case.view,
        "files": _encoded(case.files),
    }
    return out | ({"caps": case.caps} if case.caps else {})


def _model_case(case: Case) -> dict:
    model = build_model(case.view, case.files, case.registry())
    out = _header(case) | {"model": model}
    inner = model["model"]
    if "snaps" in case.queries:
        xs = inner["x"]["values"]
        out["snaps"] = [{"x": x, "row": snap_row(xs, x)} for x in case.queries["snaps"]]
    if "locates" in case.queries:
        edges = [inner["items"][0]["lower"], *(i["upper"] for i in inner["items"])]
        out["locates"] = [
            {"value": v, "bin": locate_bin(edges, v)} for v in case.queries["locates"]
        ]
    return out


def _refusal(case: Case) -> dict:
    try:
        build_model(case.view, case.files, case.registry())
    except ViewRefused as exc:
        return _header(case) | {"word": exc.word, "downloads": exc.downloads}
    raise AssertionError(f"{case.name}: not refused")


def models() -> dict:
    cases = [
        *table_cases(),
        *lines_cases(),
        *heatmap_cases(),
        *histogram_cases(),
        *cap_cases(),
        *order_cases(),
        *fallback_cases(),
    ]
    names = [c.name for c in [*cases, *refusals()]]
    if len(names) != len(set(names)):
        raise AssertionError("case names repeat")
    return {
        "format": MODELS_FORMAT,
        "spec": SPEC,
        "description": (
            "Cases every renderer of the generic kinds reproduces. For each case, "
            "decode files (text is UTF-8; base64 is raw bytes), use the registry's "
            "caps with the case's caps in their place, build the model of view, "
            "and compare it with model: numbers by binary64 equality that tells "
            "-0 from 0 (Object.is), texts exactly. snaps give the row a pointer at "
            "x reads, and locates the bin that holds a value (-1 underflow, the "
            "bin count overflow). Each refusal's view is refused with word, "
            "nothing is drawn, and downloads lists the files still offered."
        ),
        "cases": [_model_case(case) for case in cases],
        "refusals": [_refusal(case) for case in refusals()],
    }


def dump(value, depth: int = 0) -> str:
    """JSON with two-space indents and each array of scalars on one line."""
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(value, dict) and value:
        members = [
            f"{inner}{_scalars(k)}: {dump(v, depth + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(members) + f"\n{pad}}}"
    if isinstance(value, list) and any(isinstance(v, dict | list) for v in value):
        items = [f"{inner}{dump(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return _scalars(value)


def _scalars(value) -> str:
    """A scalar or a flat array, as UTF-8 text; a string holding a lone
    surrogate or a noncharacter is escaped, so the file stays I-JSON."""
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    if FORBIDDEN.search(text):
        return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
    return text


def render() -> dict[Path, str]:
    """The text of each vectors file."""
    return {
        path: dump(document) + "\n"
        for path, document in (
            (MODELS_PATH, models()),
            (VERDICTS_PATH, verdicts()),
            (PRESET_CHECKS_PATH, preset_checks()),
        )
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if a committed file differs"
    )
    args = parser.parse_args(argv)
    stale = []
    for path, text in render().items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT))
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print(
            "Out of date; run scripts/generate_kind_vectors.py: "
            + ", ".join(map(str, stale)),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
