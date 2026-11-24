"""Write the generic-kind vectors from the cases defined here.

Writes ``views/vectors/kinds-models.v1.json`` (each case's model, from the
Python reference ``neuroschema.views.build_model``) and
``views/vectors/kinds-verdicts.v1.json`` (each instance's verdict, from
jsonschema). ``docs/views/generic-kinds.md`` says how a renderer replays them.

Usage::

    uv run python scripts/generate_kind_vectors.py           # write both files
    uv run python scripts/generate_kind_vectors.py --check   # fail if either differs
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

from neuroschema.views import load_registry
from neuroschema.views.models import (
    MODELS_FORMAT,
    ViewRefused,
    build_model,
    content_validator,
    histogram_content_validator,
    locate_bin,
    snap_row,
    view_validator,
)

ROOT = Path(__file__).resolve().parent.parent
MODELS_PATH = ROOT / "views" / "vectors" / "kinds-models.v1.json"
VERDICTS_PATH = ROOT / "views" / "vectors" / "kinds-verdicts.v1.json"
VERDICTS_FORMAT = "nemar.kinds-verdicts.v1"
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
    cases = [
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
            "histogram_byte_order_mark",
            b"\xef\xbb\xbf" + ICLABEL,
            "A byte order mark: json_invalid.",
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
            "order_declaration_before_files",
            "An invalid declaration and no files: declaration_invalid, and no "
            "file is offered, since the declaration that names them is not valid.",
            lines_view(base="nemar.table", base_version=1),
            {},
        ),
        (
            "order_digest_before_bytes_cap",
            "Other bytes of the declared size, over the byte cap: "
            "file_digest_mismatch.",
            lines_view(),
            {SPECTRUM_AT: wrong},
            {"bytes_per_role": 10},
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
        ("envelope_dims_valid", "An unknown kind with a dimension.", dims),
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


def content_verdicts() -> list[tuple[str, str, object]]:
    edges = json.loads(EDGES)
    cats = json.loads(ICLABEL)
    return [
        ("content_edges", "Bins by edges.", edges),
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
    out["transform"]["parameters"] = {"match": "label", "unit": "uV"}
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
    signal_only = _set(window, "inputs", window["inputs"][:1])
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
            "ic_activity_store_row_without_rows",
            "Matching by row names the rows.",
            _set(activity, "transform/parameters/rows", DROP),
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
                archive,
                "transform/parameters",
                {"match": "store_row", "rows": [0], "unit": "uV"},
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
            _set(
                _set(archive, f"inputs/{signal}", activity["inputs"][signal]),
                "transform/parameters",
                {"match": "label", "unit": "uV"},
            ),
        ),
        (
            "ic_activity_types_without_digest",
            "channel_types comes with its digest.",
            _set(activity, "parameters/decomposition_input/channel_types_sha256", DROP),
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
        ("signal_window_signal_only", "The floor's tables are optional.", signal_only),
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
            counts | {"classifier": "iclabel"},
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


def _errors(validator, instance) -> list[list[str]]:
    pairs = {
        (e.validator, "/".join(str(p) for p in e.absolute_path))
        for e in validator.iter_errors(instance)
    }
    return [list(pair) for pair in sorted(pairs)]


def verdicts() -> dict:
    cases = []
    for schema, validator, items in [
        ("view", view_validator(), [*view_verdicts(), *preset_verdicts()]),
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
            "that checks them without a JSON Schema engine. schema view means "
            "schema/definitions/view.schema.json#/$defs/view; any other schema is "
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
            f"{inner}{json.dumps(k, ensure_ascii=False)}: {dump(v, depth + 1)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(members) + f"\n{pad}}}"
    if isinstance(value, list) and any(isinstance(v, dict | list) for v in value):
        items = [f"{inner}{dump(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def render() -> dict[Path, str]:
    """The text of each vectors file."""
    return {
        path: dump(document) + "\n"
        for path, document in ((MODELS_PATH, models()), (VERDICTS_PATH, verdicts()))
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
