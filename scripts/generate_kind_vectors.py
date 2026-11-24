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
from collections.abc import Callable
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
from neuroschema.views.presets import (
    PRESET_CHECKS_FORMAT,
    check_preset,
    spectrum_maps,
)

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
    maps, files = field_view(mixing(), chanlocs())
    changed = _replace(chanlocs(), "\t-54\t", "\t-55\t")
    positioned, positions = field_view(mixing(), electrodes(), "positions")
    icmaps = ic_maps_by_base_cases()[0]
    ieeg = json.loads(IEEG_INPUTS.read_text(encoding="utf-8"))
    untyped_implant = text_tsv(
        ["name", "x", "y", "z"], [[n, x, y, z] for n, x, y, z, _t in ieeg["rows"]]
    )
    implant_view, implant_files = field_view(
        mixing(len(ieeg["rows"])),
        untyped_implant,
        "positions",
        sensor_columns=[col("name", "string")] + [col(a, unit="mm") for a in "xyz"],
        positions={"coordinate_system": "Talairach"},
    )
    cases += [
        (
            "refusal_sensor_field_size_mismatch",
            "A scalp map's layout one byte longer than declared: file_size_mismatch.",
            maps,
            {FIELD_AT: files[FIELD_AT], CHANLOCS_AT: files[CHANLOCS_AT] + b"\n"},
        ),
        (
            "refusal_ieeg_talairach_without_types",
            "The real ECoG implant in Talairach as measured positions with no "
            "sensor_type column: the schema refuses measured positions that do not "
            "carry their types (declaration_invalid), and nothing is offered.",
            implant_view,
            implant_files,
        ),
        (
            "refusal_sensor_field_layout_digest",
            "A scalp map's layout is not the recorded file: file_digest_mismatch, "
            "and the values are still offered.",
            maps,
            {FIELD_AT: files[FIELD_AT], CHANLOCS_AT: changed},
        ),
        (
            "refusal_sensor_field_positions_missing",
            "A scalp map's positions are not there: file_missing.",
            positioned,
            {FIELD_AT: positions[FIELD_AT]},
        ),
        (
            "refusal_ic_maps_values_missing",
            "nemar.ic-maps by its base without its mixing matrix: file_missing; "
            "the layout and the components table are still offered.",
            icmaps.view,
            {
                k: v
                for k, v in icmaps.files.items()
                if k != _location(icmaps.view, "values")
            },
        ),
    ]
    return [Case(*fields) for fields in cases]


# ── nemar.sensor-field ────────────────────────────────────────────────────

# The 19 electrodes of the 10-20 system, with a layout's theta (degrees) and
# radius as stored text.
TEN_TWENTY = [
    ("Fp1", "-18", "0.511"),
    ("Fp2", "18", "0.511"),
    ("F7", "-54", "0.511"),
    ("F3", "-39.9", "0.333"),
    ("Fz", "0", "0.256"),
    ("F4", "39.9", "0.333"),
    ("F8", "54", "0.511"),
    ("T7", "-90", "0.511"),
    ("C3", "-90", "0.256"),
    ("Cz", "0", "0"),
    ("C4", "90", "0.256"),
    ("T8", "90", "0.511"),
    ("P7", "-126", "0.511"),
    ("P3", "-140.1", "0.333"),
    ("Pz", "180", "0.256"),
    ("P4", "140.1", "0.333"),
    ("P8", "126", "0.511"),
    ("O1", "-162", "0.511"),
    ("O2", "162", "0.511"),
]
NAMES_1020 = [name for name, _theta, _radius in TEN_TWENTY]
# Their positions in standard_1005, right-anterior-superior meters.
POSITIONS_1005 = {
    e[0]: e[1:4]
    for e in json.loads(
        (ROOT / "views" / "montages" / "standard_1005.json").read_text("utf-8")
    )["electrodes"]
}
# An intracranial implant in millimeters (ACPC): two depth shafts (SEEG), a
# strip on the left temporal lobe (ECOG) and a deep brain stimulation lead
# (DBS), named as clinicians name them, some like scalp electrodes.
IMPLANT = [
    *((f"LA{i}", -18 - 4 * i, -4, -18, "SEEG") for i in range(1, 9)),
    *((f"LH{i}", -22 - 4 * i, -20, -12, "SEEG") for i in range(1, 9)),
    *((f"C{i}", -62, -40 + 8 * i, -6 + 3 * i, "ECOG") for i in range(1, 7)),
    *((f"DBS{i}", 12, -13, -5 + 2 * i, "DBS") for i in range(1, 5)),
]
# Real intracranial positions (bids-examples, PDDL), frozen with their source.
IEEG_INPUTS = ROOT / "scripts" / "ieeg_vector_inputs.json"
FIELD_AT = f"{PREFIX}_field.tsv"
CHANLOCS_AT = f"{PREFIX}_chanlocs.tsv"
ELECTRODES_AT = f"{PREFIX}_electrodes.tsv"
COMPONENTS_AT = f"{PREFIX}_components.tsv"
SENSOR_ROWS = dim("sensor", "rows", "string", {"role": "layout", "column": "name"})
MAPS_HEADER = dim("component", "columns", "string", {"header": True})
LAYOUT_COLUMNS = [col("name", "string"), col("theta_deg", unit="deg"), col("radius")]
TYPED_LAYOUT_COLUMNS = [*LAYOUT_COLUMNS, col("sensor_type", "string")]
POSITION_COLUMNS = [col("name", "string")] + [col(a, unit="m") for a in "xyz"]
TYPED_POSITION_COLUMNS = [*POSITION_COLUMNS, col("sensor_type", "string")]
NAME_ROWS = dim("sensor", "rows", "string", {"column": "name"})


def text_tsv(header: list[str], rows: list[list[str]]) -> bytes:
    """A TSV file from a header and rows of cell texts (no spaces in cells)."""
    return tsv(" ".join(header), *(" ".join(row) for row in rows))


def pattern(k: int, m: int) -> str:
    """A value for sensor k of map m, from -2 to 2 in steps of 0.25: exact."""
    return repr(((7 * k + 11 * m) % 17 - 8) / 4)


def mixing(count: int = 19, maps: int = 3, at: Callable | None = None) -> bytes:
    """Sensors along the rows, one value column per map (IC001, IC002, ...)."""
    at = at or pattern
    header = [f"IC{m + 1:03d}" for m in range(maps)]
    return text_tsv(header, [[at(k, m) for m in range(maps)] for k in range(count)])


def map_columns(maps: int = 3, kind: str = "number", unit: str | None = "uV"):
    return [col(f"IC{m + 1:03d}", kind, unit) for m in range(maps)]


def chanlocs(rows=TEN_TWENTY, types="EEG") -> bytes:
    """A layout file: name, theta_deg, radius and, with types, sensor_type
    (each row EEG by default; None for no sensor_type column)."""
    if types == "EEG":
        types = ["EEG"] * len(rows)
    typed = types is not None
    header = ["name", "theta_deg", "radius"] + (["sensor_type"] if typed else [])
    body = [
        [name, theta, radius] + ([types[i]] if typed else [])
        for i, (name, theta, radius) in enumerate(rows)
    ]
    return text_tsv(header, body)


def electrodes(names=NAMES_1020, types="EEG", flat=False, at=None) -> bytes:
    """A positions file of standard_1005 positions for the names (z = 0 when
    flat), or of the given (name, x, y, z) rows, with sensor_type (each row EEG
    by default; None for no sensor_type column)."""
    rows = at or [(n, *POSITIONS_1005[n]) for n in names]
    if types == "EEG":
        types = ["EEG"] * len(rows)
    typed = types is not None
    header = ["name", "x", "y", "z"] + (["sensor_type"] if typed else [])
    body = [
        [name, repr(x), repr(y), "0" if flat else repr(z)]
        + ([types[i]] if typed else [])
        for i, (name, x, y, z) in enumerate(rows)
    ]
    return text_tsv(header, body)


def field_view(
    values: bytes,
    sensors: bytes | None = None,
    role: str = "layout",
    *,
    columns=None,
    dims=None,
    sensor_columns=None,
    kind: str = "nemar.sensor-field",
    extra: list | None = None,
    **fields,
) -> tuple[dict, dict]:
    """A scalp map view and its files: values, and a layout or positions role."""
    entry = data_entry(
        "values",
        FIELD_AT,
        values,
        columns=map_columns() if columns is None else columns,
        dims=dims
        or [
            dim("sensor", "rows", "string", {"role": role, "column": "name"}),
            MAPS_HEADER,
        ],
    )
    data, files = [entry], {FIELD_AT: values}
    if sensors is not None:
        at = CHANLOCS_AT if role == "layout" else ELECTRODES_AT
        if sensor_columns is None:
            typed = b"sensor_type" in sensors.split(b"\n", 1)[0]
            if role == "layout":
                sensor_columns = TYPED_LAYOUT_COLUMNS if typed else LAYOUT_COLUMNS
            else:
                sensor_columns = TYPED_POSITION_COLUMNS if typed else POSITION_COLUMNS
        sensor_fields = {
            "coordinate_system": "CapTrak",
            "position_source": "measured",
        } | fields.pop(role, {})
        data.append(
            data_entry(
                role,
                at,
                sensors,
                columns=sensor_columns,
                dims=[NAME_ROWS],
                **sensor_fields,
            )
        )
        files[at] = sensors
        if role == "positions":
            fields["transform"] = {"name": "nemar.sensor-layout.v1", "parameters": {}}
    for extra_entry, extra_data in extra or []:
        data.append(extra_entry)
        files[extra_entry["location"]] = extra_data
    built = view(
        "maps",
        kind,
        "Scalp maps.",
        data,
        source=copy.deepcopy(RECIPE),
        **fields,
    )
    return built, files


def names_view(values: bytes, columns, dims, **fields) -> tuple[dict, dict]:
    """A scalp map whose sensors are named in the values file (no sensor role)."""
    return field_view(values, None, columns=columns, dims=dims, **fields)


def named_values(names=NAMES_1020, maps: int = 3) -> bytes:
    """A name column, then one value column per map."""
    header = ["name"] + [f"IC{m + 1:03d}" for m in range(maps)]
    rows = [[n] + [pattern(k, m) for m in range(maps)] for k, n in enumerate(names)]
    return text_tsv(header, rows)


NAMED_COLUMNS = [col("name", "string"), *map_columns()]


def sensor_field_cases() -> list[Case]:
    """Each source, the fallback from positions to names, types and frames,
    integer maps, map labels, every fault word, and per-map words."""
    cases = []

    def case(name, covers, built, caps=None):
        cases.append(Case(name, covers, built[0], built[1], caps))

    values = mixing()
    case(
        "sensor_field_layout",
        "Three maps over a stored layout of the 19 10-20 electrodes (measured, "
        "CapTrak): the sensors are the layout's rows, each map a value column, "
        "labeled by its header name; absmax by default.",
        field_view(values, chanlocs()),
    )
    case(
        "sensor_field_layout_minmax",
        "parameters.limits minmax: the model names the rule.",
        field_view(values, chanlocs(), parameters={"limits": "minmax"}),
    )
    case(
        "sensor_field_layout_template",
        "A layout of template positions names its montage and n/a; it may be "
        "untyped, and every row is drawn.",
        field_view(
            values,
            chanlocs(types=None),
            layout={
                "coordinate_system": "n/a",
                "position_source": "template",
                "montage": "standard_1005",
            },
        ),
    )
    holes = chanlocs(
        [
            *TEN_TWENTY[:4],
            ("Fz", "n/a", "0.256"),
            *TEN_TWENTY[5:9],
            ("Cz", "0", "n/a"),
            *TEN_TWENTY[10:],
        ]
    )
    case(
        "sensor_field_layout_no_place",
        "n/a in a layout's theta or radius: that sensor has no place (null), is "
        "dropped from the maps, and the others are drawn.",
        field_view(values, holes),
    )
    integers = text_tsv(
        ["IC001", "IC002"], [[str(k - 9), str((5 * k) % 7)] for k in range(19)]
    )
    case(
        "sensor_field_integer_maps",
        "Integer value columns are maps too, read under the integer grammar.",
        field_view(integers, chanlocs(), columns=map_columns(2, "integer", None)),
    )
    eeg_types = ["EEG"] * 19
    mixed = [*eeg_types[:16], "EOG", "ECG", "n/a"]
    case(
        "sensor_field_types_eeg_only",
        "Rows typed EEG, EOG and ECG and one untyped: with any row typed, only "
        "the EEG rows are drawn (16 of 19).",
        field_view(values, chanlocs(types=mixed), sensor_columns=TYPED_LAYOUT_COLUMNS),
    )
    case(
        "sensor_field_types_folded",
        "A type's letters are folded as sensor-labels folds them: eeg, Eeg and "
        "EEG are all EEG, and every row is drawn.",
        field_view(
            values,
            chanlocs(types=["eeg"] * 9 + ["Eeg"] * 9 + ["EEG"]),
            sensor_columns=TYPED_LAYOUT_COLUMNS,
        ),
    )
    case(
        "sensor_field_untyped",
        "Measured positions whose sensor_type cells are n/a or empty: no row "
        "says it is EEG, so no row is drawn (no_eeg_sensors).",
        field_view(
            values,
            chanlocs(types=["n/a"] * 10 + [""] * 9),
            sensor_columns=TYPED_LAYOUT_COLUMNS,
        ),
    )
    case(
        "sensor_field_no_eeg_sensors",
        "Every row typed, none EEG (EMG): no_eeg_sensors in every map's place.",
        field_view(
            values, chanlocs(types=["EMG"] * 19), sensor_columns=TYPED_LAYOUT_COLUMNS
        ),
    )
    # Positions.
    case(
        "sensor_field_positions",
        "Measured positions (CapTrak, meters) projected by "
        "nemar.sensor-layout.v1: the model holds the stored x, y and z.",
        field_view(values, electrodes(), "positions"),
    )
    hole_rows = [
        (n, *(("n/a" if n == "T8" and i == 0 else v) for i, v in enumerate(p)))
        for n, p in ((n, POSITIONS_1005[n]) for n in NAMES_1020)
    ]
    case(
        "sensor_field_positions_no_place",
        "n/a in a position's x: that row has no place, and the rest are fitted "
        "and drawn.",
        field_view(
            values,
            text_tsv(
                ["name", "x", "y", "z", "sensor_type"],
                [
                    [n, *(v if v == "n/a" else repr(v) for v in p), "EEG"]
                    for n, *p in hole_rows
                ],
            ),
            "positions",
        ),
    )
    case(
        "sensor_field_positions_template",
        "Template positions from standard_1005 (n/a, montage), untyped: "
        "projected about the montage's own center, every row drawn.",
        field_view(
            values,
            electrodes(types=None),
            "positions",
            positions={
                "coordinate_system": "n/a",
                "position_source": "template",
                "montage": "standard_1005",
            },
        ),
    )
    scalp_and_depth = [(n, *POSITIONS_1005[n]) for n in NAMES_1020] + [
        (n, x / 1000, y / 1000, z / 1000) for n, x, y, z, _t in IMPLANT[:8]
    ]
    case(
        "sensor_field_positions_eeg_and_seeg",
        "Scalp EEG beside a depth shaft (SEEG) in one positions file: the SEEG "
        "rows are never drawn, and the projection fits the EEG rows alone.",
        field_view(
            mixing(27),
            electrodes(types=["EEG"] * 19 + ["SEEG"] * 8, at=scalp_and_depth),
            "positions",
            sensor_columns=TYPED_POSITION_COLUMNS,
        ),
    )
    flat_scalp = [(n, *POSITIONS_1005[n][:2], 0.0) for n in NAMES_1020]
    depth = [(n, x / 1000, y / 1000, z / 1000) for n, x, y, z, _t in IMPLANT]
    case(
        "sensor_field_positions_fit_eeg_rows",
        "Flat scalp positions (z = 0) beside depth contacts typed SEEG that lie "
        "off their plane: the projection fits the EEG rows alone, which are "
        "flat, so the sensors are placed by name (a fit through every row would "
        "have found a sphere).",
        field_view(
            mixing(45),
            electrodes(types=["EEG"] * 19 + ["SEEG"] * 26, at=flat_scalp + depth),
            "positions",
            sensor_columns=TYPED_POSITION_COLUMNS,
        ),
    )
    case(
        "sensor_field_positions_flat_names",
        "Measured positions on one plane (z = 0): positions_flat, so the "
        "sensors are placed by name on standard_1005 instead, and the model "
        "says why the positions were not used.",
        field_view(values, electrodes(flat=True), "positions"),
    )
    case(
        "sensor_field_positions_frame_unknown_names",
        "Positions in the coordinate system Other: frame_unknown, placed by name.",
        field_view(
            values,
            electrodes(),
            "positions",
            positions={"coordinate_system": "Other"},
        ),
    )
    channels = [f"Ch{k + 1}" for k in range(19)]
    case(
        "sensor_field_positions_flat_names_refused",
        "Flat positions whose names match no montage: the names are refused "
        "(labels_unrecognized), and that is every map's word.",
        field_view(
            values,
            electrodes(
                at=[
                    (
                        c,
                        *POSITIONS_1005[n],
                    )
                    for c, n in zip(channels, NAMES_1020, strict=True)
                ],
                flat=True,
            ),
            "positions",
        ),
    )
    implant = text_tsv(
        ["name", "x", "y", "z", "sensor_type"],
        [[n, str(x), str(y), str(z), t] for n, x, y, z, t in IMPLANT],
    )
    implant_columns = [col("name", "string")] + [col(a, unit="mm") for a in "xyz"]
    implant_columns.append(col("sensor_type", "string"))
    for frame in ("ACPC", "ScanRAS"):
        case(
            f"sensor_field_implant_{frame.lower()}",
            f"An intracranial implant (SEEG shafts, an ECOG strip named C1 to "
            f"C6, a DBS lead) in {frame}: frame_not_scalp, never drawn as a "
            "scalp map and never placed by its names.",
            field_view(
                mixing(26),
                implant,
                "positions",
                sensor_columns=implant_columns,
                positions={"coordinate_system": frame},
            ),
        )
    case(
        "sensor_field_implant_untyped_acpc",
        "The implant in ACPC with every sensor_type n/a: the frame alone "
        "refuses it (frame_not_scalp), though C1 to C6 are scalp names.",
        field_view(
            mixing(26),
            text_tsv(
                ["name", "x", "y", "z", "sensor_type"],
                [[n, str(x), str(y), str(z), "n/a"] for n, x, y, z, _t in IMPLANT],
            ),
            "positions",
            sensor_columns=implant_columns,
            positions={"coordinate_system": "ACPC"},
        ),
    )
    case(
        "sensor_field_implant_typed_in_a_scalp_frame",
        "The implant's types in a frame a scalp map may use (CapTrak): every "
        "row typed SEEG, ECOG or DBS, so no_eeg_sensors.",
        field_view(
            mixing(26),
            implant,
            "positions",
            sensor_columns=implant_columns,
        ),
    )
    pixels = text_tsv(
        ["name", "x", "y", "z", "sensor_type"],
        [
            [n, str(100 + 9 * k), str(40 + 5 * k), "n/a", "n/a"]
            for k, n in enumerate(NAMES_1020)
        ],
    )
    case(
        "sensor_field_pixels",
        "Positions in Pixels (a photograph of a grid, z n/a): frame_not_scalp.",
        field_view(
            values,
            pixels,
            "positions",
            sensor_columns=[col("name", "string")]
            + [col(a) for a in "xyz"]
            + [col("sensor_type", "string")],
            positions={"coordinate_system": "Pixels"},
        ),
    )
    # Real intracranial positions, and a strip named like scalp electrodes.
    ieeg = json.loads(IEEG_INPUTS.read_text(encoding="utf-8"))
    contacts = ieeg["rows"]

    def implant_file(types):
        header = ["name", "x", "y", "z"] + (["sensor_type"] if types else [])
        return text_tsv(
            header,
            [
                [n, x, y, z] + ([types[i]] if types else [])
                for i, (n, x, y, z, _t) in enumerate(contacts)
            ],
        )

    mm_columns = [col("name", "string")] + [col(a, unit="mm") for a in "xyz"]
    mm_typed = [*mm_columns, col("sensor_type", "string")]
    for name, covers, frame, types in [
        (
            "ieeg_talairach_untyped",
            "A real ECoG implant (bids-examples ieeg_motorMiller2007, sub-bp, "
            "Talairach, 47 contacts) with every sensor_type n/a: measured "
            "positions that do not say they are EEG are never drawn "
            "(no_eeg_sensors), though Talairach is a frame a scalp map may use.",
            "Talairach",
            ["n/a"] * len(contacts),
        ),
        (
            "ieeg_talairach_electrode_type",
            "The same implant typed by its electrodes.tsv type (surface): not "
            "EEG, so no_eeg_sensors.",
            "Talairach",
            [t for *_rest, t in contacts],
        ),
        (
            "ieeg_ixi549space_untyped",
            "The same contacts in IXI549Space, the template space of the BIDS "
            "examples' other implants: untyped, so no_eeg_sensors.",
            "IXI549Space",
            ["n/a"] * len(contacts),
        ),
    ]:
        case(
            name,
            covers,
            field_view(
                mixing(len(contacts)),
                implant_file(types),
                "positions",
                sensor_columns=mm_typed,
                positions={"coordinate_system": frame},
            ),
        )
    strip_names = [f"F{i}" for i in range(1, 9)] + [f"C{i}" for i in range(1, 7)]
    strip_names += ["Fz", "Cz"]
    strip = [(n, -40 + 3 * i, 30, 40 - i) for i, n in enumerate(strip_names)]

    def strip_file(types):
        return text_tsv(
            ["name", "x", "y", "z", "sensor_type"],
            [
                [n, str(x), str(y), str(z), t]
                for (n, x, y, z), t in zip(strip, types, strict=True)
            ],
        )

    for name, covers, types in [
        (
            "strip_other_untyped",
            "An ECoG strip named F1 to F8, C1 to C6, Fz and Cz in the frame Other, "
            "every sensor_type n/a: no row says it is EEG, so no_eeg_sensors, and "
            "the names are never tried on a scalp.",
            ["n/a"] * 16,
        ),
        (
            "strip_other_ecog",
            "The strip typed ECOG: no_eeg_sensors.",
            ["ECOG"] * 16,
        ),
        (
            "strip_other_typed_eeg",
            "The strip typed EEG: a writer's claim the renderer believes, so after "
            "frame_unknown the rows are placed by name on standard_1005.",
            ["EEG"] * 16,
        ),
    ]:
        case(
            name,
            covers,
            field_view(
                mixing(16),
                strip_file(types),
                "positions",
                sensor_columns=mm_typed,
                positions={"coordinate_system": "Other"},
            ),
        )
    unknown_cap = {
        "coordinate_system": "n/a",
        "position_source": "template",
        "montage": "acme-cap-19",
    }
    case(
        "template_unknown_montage_untyped",
        "Untyped template positions from a montage views/montages does not "
        "hold: frame_unknown, and since no row says it is EEG, it takes every "
        "map's place rather than a placement by name.",
        field_view(values, electrodes(types=None), "positions", positions=unknown_cap),
    )
    case(
        "template_unknown_montage_typed_eeg",
        "The same positions typed EEG: frame_unknown, then placed by name.",
        field_view(values, electrodes(), "positions", positions=unknown_cap),
    )
    # Names.
    case(
        "sensor_field_names",
        "No sensor role: the names in the values file are placed by "
        "nemar.sensor-labels.v1 on standard_1005 (template positions).",
        names_view(named_values(), NAMED_COLUMNS, [NAME_ROWS, MAPS_HEADER]),
    )
    bands = text_tsv(
        ["band", *NAMES_1020],
        [
            [band] + [pattern(k, m) for k in range(19)]
            for m, band in enumerate(("delta", "theta", "alpha"))
        ],
    )
    case(
        "sensor_field_names_on_columns",
        "Sensors along the columns, named by the header; one map per row, "
        "labeled by the column band.",
        names_view(
            bands,
            [col("band", "string")] + [col(n) for n in NAMES_1020],
            [
                dim("band", "rows", "string", {"column": "band"}),
                dim("sensor", "columns", "string", {"header": True}),
            ],
        ),
    )
    case(
        "sensor_field_maps_by_row_number",
        "Sensors along the columns and no second dimension: each map is "
        "labeled by its row number, from 1.",
        names_view(
            text_tsv(
                NAMES_1020, [[pattern(k, m) for k in range(19)] for m in range(2)]
            ),
            [col(n) for n in NAMES_1020],
            [dim("sensor", "columns", "string", {"header": True})],
        ),
    )
    case(
        "sensor_field_names_some_unplaced",
        "Names with an EOG and a trigger channel among them: sensor-labels "
        "places the 19 scalp names, and the two it leaves unplaced are not "
        "drawn.",
        names_view(
            named_values([*NAMES_1020[:10], "EOG1", *NAMES_1020[10:], "Status"]),
            NAMED_COLUMNS,
            [NAME_ROWS, MAPS_HEADER],
        ),
    )
    case(
        "sensor_field_names_refused",
        "Names that match no montage: labels_unrecognized in every map's place.",
        names_view(named_values(channels), NAMED_COLUMNS, [NAME_ROWS, MAPS_HEADER]),
    )
    case(
        "sensor_field_names_too_few",
        "Seven names: sensor-labels refuses them first (too_few_channels).",
        names_view(
            named_values(NAMES_1020[:7]), NAMED_COLUMNS, [NAME_ROWS, MAPS_HEADER]
        ),
    )
    # Per-map words and notes.
    flat = mixing(at=lambda k, m: "1.5" if m == 1 else pattern(k, m))
    case(
        "sensor_field_flat_map",
        "Three maps; every sensor of the second has the value 1.5: a flat field, "
        "drawn at 1.5 with the note flat_field, and the others interpolated.",
        field_view(flat, chanlocs()),
    )
    overflow = mixing(at=lambda k, m: "1e308" if m == 1 and k % 2 else pattern(k, m))
    case(
        "sensor_field_one_map_overflows",
        "Three maps on one layout; the second's values overflow the "
        "interpolation (interpolation_failed) and the others are drawn.",
        field_view(overflow, chanlocs()),
    )
    case(
        "sensor_field_too_few_sensors",
        "A layout of seven sensors: every map too_few_sensors (a map needs 8).",
        field_view(mixing(7), chanlocs(TEN_TWENTY[:7])),
    )
    far = [*TEN_TWENTY[:18], ("O2", "-135", "1e10")]
    case(
        "sensor_field_head_outside_grid",
        "A sensor at radius 1e10 stretches the grid past the head: "
        "head_outside_grid in every map's place.",
        field_view(values, chanlocs(far)),
    )
    return cases


def _replace(data: bytes, old: str, new: str) -> bytes:
    assert old.encode() in data, old
    return data.replace(old.encode(), new.encode(), 1)


def sensor_field_fault_cases() -> list[Case]:
    """Each file fault of a scalp map: the view falls back to its tables."""
    values, layout = mixing(), chanlocs()
    cases = []

    def case(name, covers, built, caps=None):
        cases.append(Case(name, covers, built[0], built[1], caps))

    case(
        "sensor_field_values_ragged",
        "The values file has a ragged row: tsv_ragged.",
        field_view(values + b"1\n", layout),
    )
    case(
        "sensor_field_values_column_missing",
        "A declared map column the header lacks: column_missing.",
        field_view(values, layout, columns=[*map_columns(), col("IC009", unit="uV")]),
    )
    case(
        "sensor_field_values_value_type",
        "A value column declared string: value_type.",
        field_view(values, layout, columns=[*map_columns(2), col("IC003", "string")]),
    )
    case(
        "sensor_field_values_units_differ",
        "Maps in uV and in dB: value_units_differ.",
        field_view(values, layout, columns=[*map_columns(2), col("IC003", unit="dB")]),
    )
    case(
        "sensor_field_values_empty",
        "A header and no rows (and a layout of none): empty.",
        field_view(text_tsv(["IC001", "IC002", "IC003"], []), chanlocs([])),
    )
    case(
        "sensor_field_values_n_a",
        "n/a in a map's values: cell_not_number (only a place may be n/a).",
        field_view(_replace(values, "\n0.25\t", "\nn/a\t"), layout),
    )
    case(
        "sensor_field_values_not_finite",
        "A value 1e400: cell_not_finite.",
        field_view(_replace(values, "\n0.25\t", "\n1e400\t"), layout),
    )
    case(
        "sensor_field_values_not_integer",
        "2.5 in an integer map: cell_not_integer.",
        field_view(
            text_tsv(["IC001"], [[str(k)] for k in range(18)] + [["2.5"]]),
            layout,
            columns=map_columns(1, "integer", None),
        ),
    )
    case(
        "sensor_field_values_rows_cap",
        "Nineteen sensor rows over caps.entries_per_dim 18: cap_exceeded.",
        field_view(values, layout),
        {"entries_per_dim": 18},
    )
    case(
        "sensor_field_maps_header_on_rows",
        "A maps dimension along the rows that names the header: "
        "coords_unresolved (a header names columns).",
        names_view(
            text_tsv(
                NAMES_1020, [[pattern(k, m) for k in range(19)] for m in range(2)]
            ),
            [col(n) for n in NAMES_1020],
            [
                dim("band", "rows", "string", {"header": True}),
                dim("sensor", "columns", "string", {"header": True}),
            ],
        ),
    )
    case(
        "sensor_field_names_coords_mismatch",
        "The values' name column declared integer, the sensor dimension "
        "string: coords_mismatch.",
        names_view(
            named_values(),
            [col("name", "integer"), *map_columns()],
            [NAME_ROWS, MAPS_HEADER],
        ),
    )
    case(
        "sensor_field_layout_short",
        "A layout of 18 rows for 19 sensor rows: coords_length.",
        field_view(values, chanlocs(TEN_TWENTY[:18])),
    )
    case(
        "sensor_field_layout_long",
        "A layout of 19 rows for 18 sensor rows: coords_length.",
        field_view(mixing(18), layout),
    )
    case(
        "sensor_field_positions_short",
        "Positions of 18 rows for 19 sensor rows: coords_length.",
        field_view(values, electrodes(NAMES_1020[:18]), "positions"),
    )
    bands = text_tsv(
        ["band", *NAMES_1020],
        [[b] + [pattern(k, m) for k in range(19)] for m, b in enumerate(("a", "b"))],
    )
    case(
        "sensor_field_sensors_mismatch",
        "Sensors along the columns, named by the header, and placed by a layout "
        "listed in the other order: the value columns' names are not the "
        "layout's name cells, so sensors_mismatch, never a value drawn at "
        "another sensor's place.",
        field_view(
            bands,
            chanlocs(TEN_TWENTY[::-1]),
            columns=[col("band", "string")] + [col(n) for n in NAMES_1020],
            dims=[
                dim("band", "rows", "string", {"column": "band"}),
                dim(
                    "sensor", "columns", "string", {"role": "layout", "column": "name"}
                ),
            ],
        ),
    )
    case(
        "sensor_field_values_byte_order_mark",
        "The values file begins with a byte order mark: tsv_encoding.",
        field_view(b"\xef\xbb\xbf" + values, layout),
    )
    case(
        "sensor_field_layout_header_repeated",
        "The layout's header names radius twice: tsv_header_repeated.",
        field_view(
            values,
            _replace(layout, "sensor_type", "radius"),
            sensor_columns=TYPED_LAYOUT_COLUMNS,
        ),
    )
    case(
        "sensor_field_layout_line_endings",
        "A layout with CRLF line endings: tsv_line_endings.",
        field_view(values, layout.replace(b"\n", b"\r\n")),
    )
    case(
        "sensor_field_layout_column_missing",
        "The layout declares radius, and its header calls it rad: column_missing.",
        field_view(values, _replace(layout, "radius", "rad")),
    )
    case(
        "sensor_field_layout_column_repeated",
        "The layout declares sensor_type twice: column_repeated.",
        field_view(
            values,
            chanlocs(types=["EEG"] * 19),
            sensor_columns=[*TYPED_LAYOUT_COLUMNS, col("sensor_type", "string")],
        ),
    )
    case(
        "sensor_field_layout_cells_cap",
        "Nineteen layout rows of four declared columns are 76 cells, over 75: "
        "cap_exceeded (the values hold 38).",
        field_view(mixing(19, 2), layout, columns=map_columns(2)),
        {"cells_per_role": 75},
    )
    case(
        "sensor_field_layout_not_a_number",
        "A theta NA (not n/a): cell_not_number.",
        field_view(values, _replace(layout, "\t-54\t", "\tNA\t")),
    )
    case(
        "sensor_field_layout_not_finite",
        "A radius 1e400: cell_not_finite.",
        field_view(values, _replace(layout, "\t0.333\tEEG\n", "\t1e400\tEEG\n")),
    )
    case(
        "sensor_field_positions_not_a_number",
        "A position nan: cell_not_number.",
        field_view(values, _replace(electrodes(), "\t-0.00699", "\tnan"), "positions"),
    )
    return cases


def sensor_field_order_pairs() -> list[tuple]:
    """Two faults in neighboring checks, each with its one-fault sibling.

    Each entry is (name, covers, the view with both faults, the view with the
    later check's fault alone, the earlier word, the later word): the case
    gives the earlier check's word, and the sibling shows that the later fault
    is there and gives its own word.
    """
    values, layout = mixing(), chanlocs()
    bands = [col("freq", unit="Hz")] + [col(n) for n in NAMES_1020]
    by_freq = [
        dim("freq", "rows", "number", {"column": "freq"}, unit="Hz"),
        dim("sensor", "columns", "string", {"header": True}),
    ]

    def spectrum_like(freq_cell="2", value_cell="0.25"):
        rows = [["1", *(pattern(k, 0) for k in range(19))]]
        rows.append([freq_cell, value_cell, *(pattern(k, 1) for k in range(1, 19))])
        return text_tsv(["freq", *NAMES_1020], rows)

    named_unit = [
        col("name", "string", "mm"),
        col("theta_deg", unit="deg"),
        col("radius"),
        col("sensor_type", "string"),
    ]
    acpc = {"coordinate_system": "ACPC"}
    far = [*TEN_TWENTY[:18], ("O2", "-135", "1e10")]
    far_seven = [*TEN_TWENTY[:6], ("O2", "-135", "1e10")]

    def huge(k, m):
        return "1e308" if k % 2 else "-1e308"

    overflow = mixing(19, 1, at=huge)
    ragged = chanlocs() + b"O3\t9\tEEG\n"
    components = text_tsv(["label"], [[f"IC{m + 1:03d}"] for m in range(3)])
    labels = data_entry(
        "components", COMPONENTS_AT, components, columns=[col("component", "string")]
    )
    maps_dim = dim(
        "component", "columns", "string", {"role": "components", "column": "component"}
    )
    reversed_layout = chanlocs(TEN_TWENTY[::-1])
    along_columns = [
        dim("band", "rows", "string", {"column": "band"}),
        dim("sensor", "columns", "string", {"role": "layout", "column": "name"}),
    ]
    band_values = text_tsv(
        ["band", *NAMES_1020],
        [[b] + [pattern(k, m) for k in range(19)] for m, b in enumerate(("a", "b"))],
    )
    band_columns = [col("band", "string")] + [col(n) for n in NAMES_1020]
    unmatched = [*NAMES_1020[:8], "Status", "Trig1", "Resp"]
    return [
        (
            "order_sensor_dimension_before_maps_dimension",
            "The sensors' name column declared integer (coords_mismatch) and a "
            "maps dimension along the columns that names a column "
            "(coords_unresolved): the sensor dimension is checked first.",
            names_view(
                named_values(),
                [col("name", "integer"), *map_columns()],
                [NAME_ROWS, dim("component", "columns", "string", {"column": "x"})],
            ),
            names_view(
                named_values(),
                NAMED_COLUMNS,
                [NAME_ROWS, dim("component", "columns", "string", {"column": "x"})],
            ),
            "coords_mismatch",
            "coords_unresolved",
        ),
        (
            "order_sensor_coordinate_before_values",
            "The name column declared integer and a value column declared "
            "string: coords_mismatch.",
            names_view(
                named_values(),
                [col("name", "integer"), *map_columns(2), col("IC003", "string")],
                [NAME_ROWS, MAPS_HEADER],
            ),
            names_view(
                named_values(),
                [col("name", "string"), *map_columns(2), col("IC003", "string")],
                [NAME_ROWS, MAPS_HEADER],
            ),
            "coords_mismatch",
            "value_type",
        ),
        (
            "order_sensor_coordinate_cells_before_values",
            "Sensors along the columns and maps labeled by a number column: a "
            "frequency x in the second row and a value 1e400 in it: the "
            "coordinate column's cells are read first, cell_not_number.",
            names_view(spectrum_like("x", "1e400"), bands, by_freq),
            names_view(spectrum_like("2", "1e400"), bands, by_freq),
            "cell_not_number",
            "cell_not_finite",
        ),
        (
            "order_sensor_values_cells_before_layout",
            "n/a in the values and a layout one row short: the values' cells "
            "come first, cell_not_number.",
            field_view(
                _replace(values, "\n0.25\t", "\nn/a\t"), chanlocs(TEN_TWENTY[:18])
            ),
            field_view(values, chanlocs(TEN_TWENTY[:18])),
            "cell_not_number",
            "coords_length",
        ),
        (
            "order_sensor_layout_grammar_before_columns",
            "A ragged layout whose header calls radius rad: tsv_ragged.",
            field_view(values, _replace(ragged, "radius", "rad")),
            field_view(values, _replace(layout, "radius", "rad")),
            "tsv_ragged",
            "column_missing",
        ),
        (
            "order_sensor_layout_repeated_before_missing",
            "sensor_type declared twice, and radius missing from the header: "
            "column_repeated.",
            field_view(
                values,
                _replace(layout, "radius", "rad"),
                sensor_columns=[*TYPED_LAYOUT_COLUMNS, col("sensor_type", "string")],
            ),
            field_view(values, _replace(layout, "radius", "rad")),
            "column_repeated",
            "column_missing",
        ),
        (
            "order_sensor_layout_missing_before_mismatch",
            "radius missing from the header, and the name column in mm while "
            "the sensor dimension has no unit: column_missing.",
            field_view(
                values, _replace(layout, "radius", "rad"), sensor_columns=named_unit
            ),
            field_view(values, layout, sensor_columns=named_unit),
            "column_missing",
            "coords_mismatch",
        ),
        (
            "order_sensor_layout_mismatch_before_length",
            "The layout's name column in mm, and the layout a row short: "
            "coords_mismatch.",
            field_view(values, chanlocs(TEN_TWENTY[:18]), sensor_columns=named_unit),
            field_view(values, chanlocs(TEN_TWENTY[:18])),
            "coords_mismatch",
            "coords_length",
        ),
        (
            "order_sensor_layout_length_before_cap",
            "The layout a row short, and over the cap on cells: coords_length.",
            field_view(
                mixing(19, 2), chanlocs(TEN_TWENTY[:18]), columns=map_columns(2)
            ),
            field_view(mixing(19, 2), layout, columns=map_columns(2)),
            "coords_length",
            "cap_exceeded",
            ({"cells_per_role": 71}, {"cells_per_role": 71}),
        ),
        (
            "order_sensor_layout_cap_before_cells",
            "The layout over the cap on cells, with a theta NA: cap_exceeded.",
            field_view(
                mixing(19, 2),
                _replace(layout, "\t-54\t", "\tNA\t"),
                columns=map_columns(2),
            ),
            field_view(
                mixing(19, 2),
                _replace(layout, "\t-54\t", "\tNA\t"),
                columns=map_columns(2),
            ),
            "cap_exceeded",
            "cell_not_number",
            ({"cells_per_role": 75}, None),
        ),
        (
            "order_sensor_layout_column_by_column",
            "A theta 1e400 in the last row and a radius x in the first, theta "
            "declared first: the cells are read column by column, "
            "cell_not_finite.",
            field_view(
                values,
                _replace(
                    _replace(layout, "\t162\t", "\t1e400\t"),
                    "\t0.511\tEEG\n",
                    "\tx\tEEG\n",
                ),
            ),
            field_view(values, _replace(layout, "\t0.511\tEEG\n", "\tx\tEEG\n")),
            "cell_not_finite",
            "cell_not_number",
        ),
        (
            "order_sensor_cells_before_names",
            "Sensors along the columns placed by a layout listed in the other "
            "order, with a theta NA: the layout's cells come first, "
            "cell_not_number.",
            field_view(
                band_values,
                _replace(reversed_layout, "\t-54\t", "\tNA\t"),
                columns=band_columns,
                dims=along_columns,
            ),
            field_view(
                band_values, reversed_layout, columns=band_columns, dims=along_columns
            ),
            "cell_not_number",
            "sensors_mismatch",
        ),
        (
            "order_sensor_files_before_frame",
            "A layout in ACPC with a theta NA: the files come first, so the view "
            "falls back with cell_not_number rather than showing "
            "frame_not_scalp.",
            field_view(values, _replace(layout, "\t-54\t", "\tNA\t"), layout=acpc),
            field_view(values, layout, layout=acpc),
            "cell_not_number",
            "frame_not_scalp",
        ),
        (
            "order_sensor_frame_before_types",
            "A layout in ACPC whose rows are all typed SEEG: frame_not_scalp.",
            field_view(values, chanlocs(types=["SEEG"] * 19), layout=acpc),
            field_view(values, chanlocs(types=["SEEG"] * 19)),
            "frame_not_scalp",
            "no_eeg_sensors",
        ),
        (
            "order_sensor_types_before_projection",
            "Flat positions all typed SEEG: no_eeg_sensors, before any projection.",
            field_view(values, electrodes(types=["SEEG"] * 19, flat=True), "positions"),
            field_view(values, electrodes(flat=True), "positions"),
            "no_eeg_sensors",
            "positions_flat",
        ),
        (
            "order_sensor_frame_before_maps",
            "Seven layout rows in ACPC: frame_not_scalp, not too_few_sensors.",
            field_view(mixing(7), chanlocs(TEN_TWENTY[:7]), layout=acpc),
            field_view(mixing(7), chanlocs(TEN_TWENTY[:7])),
            "frame_not_scalp",
            "too_few_sensors",
        ),
        (
            "order_sensor_map_too_few_before_grid",
            "Seven sensors, one at radius 1e10: too_few_sensors (step 5) before "
            "head_outside_grid (step 7).",
            field_view(mixing(7, 1), chanlocs(far_seven), columns=map_columns(1)),
            field_view(mixing(19, 1), chanlocs(far), columns=map_columns(1)),
            "too_few_sensors",
            "head_outside_grid",
        ),
        (
            "order_sensor_map_too_few_before_overflow",
            "Seven sensors and values that overflow: too_few_sensors (step 5) "
            "before interpolation_failed (step 10).",
            field_view(
                mixing(7, 1, at=huge),
                chanlocs(TEN_TWENTY[:7]),
                columns=map_columns(1),
            ),
            field_view(overflow, layout, columns=map_columns(1)),
            "too_few_sensors",
            "interpolation_failed",
        ),
        (
            "order_sensor_map_grid_before_overflow",
            "A sensor at radius 1e10 and values that overflow: head_outside_grid "
            "(step 7) before interpolation_failed (step 10).",
            field_view(overflow, chanlocs(far), columns=map_columns(1)),
            field_view(overflow, layout, columns=map_columns(1)),
            "head_outside_grid",
            "interpolation_failed",
        ),
        (
            "order_sensor_rows_before_columns",
            "An unknown kind over nemar.sensor-field whose maps are labeled by "
            "its components role, which lacks the column component, and whose "
            "layout has a ragged row: the rows' dimension (the sensors) comes "
            "first, tsv_ragged.",
            field_view(
                values,
                ragged,
                dims=[SENSOR_ROWS, maps_dim],
                kind="acme.component-maps",
                base="nemar.sensor-field",
                base_version=1,
                extra=[(labels, components)],
            ),
            field_view(
                values,
                layout,
                dims=[SENSOR_ROWS, maps_dim],
                kind="acme.component-maps",
                base="nemar.sensor-field",
                base_version=1,
                extra=[(labels, components)],
            ),
            "tsv_ragged",
            "column_missing",
        ),
        (
            "order_sensor_names_keep_their_types",
            "Flat positions typed EEG, eight 10-20 names and Status, Trig1 and "
            "Resp: placed by name with their types, the three are EEG channels "
            "no montage holds, so the share is 8 of 11 (share_too_low); without "
            "the types they would be excluded by name, and the eight placed.",
            field_view(
                mixing(11),
                electrodes(
                    at=[(n, *POSITIONS_1005[n][:2], 0.0) for n in NAMES_1020[:8]]
                    + [(n, 0.05 * i, -0.05, 0.0) for i, n in enumerate(unmatched[8:])],
                    flat=True,
                ),
                "positions",
            ),
            field_view(
                mixing(11),
                electrodes(
                    at=[(n, *POSITIONS_1005[n][:2], 0.0) for n in NAMES_1020[:8]]
                    + [(n, 0.05 * i, -0.05, 0.0) for i, n in enumerate(unmatched[8:])],
                    types=["EEG"] * 8 + ["n/a"] * 3,
                    flat=True,
                ),
                "positions",
            ),
            "share_too_low",
            "positions_flat",
        ),
    ]


def sensor_field_order_cases() -> list[Case]:
    out = []
    for name, covers, both, alone, _first, second, *caps in sensor_field_order_pairs():
        both_caps, alone_caps = caps[0] if caps else (None, None)
        out.append(Case(name, covers, both[0], both[1], both_caps))
        out.append(
            Case(
                f"{name}_alone",
                f"The later fault of {name} alone: {second}.",
                alone[0],
                alone[1],
                alone_caps,
            )
        )
    return out


def ic_maps_by_base_cases() -> list[Case]:
    """nemar.ic-maps drawn by its base, with the files its base reads."""
    components = components_table(IC_COMPONENTS)
    short = chanlocs(TEN_TWENTY[:18], types=["EEG"] * 18)
    return [
        Case(
            "ic_maps_by_base",
            "nemar.ic-maps by its base: 18 component maps over the layout, "
            "absmax, and the components table offered for download, not read.",
            *ic_maps_files(components),
        ),
        Case(
            "ic_maps_by_base_layout_short",
            "nemar.ic-maps whose layout is a row short: the base refuses "
            "(coords_length) and the view falls back to its tables.",
            *ic_maps_files(components, short),
        ),
    ]


FREQS = [2.0 * r for r in range(31)]


def spectrum_text(names=NAMES_1020, rows=FREQS, at=None) -> bytes:
    """freq_hz, then one sensor column per name, in decibels (5 to 16 dB)."""
    at = at or (lambda k, r: repr(((7 * k + 3 * r) % 23) / 2 + 5.0))
    body = [
        [repr(f)] + [at(k, r) for k in range(len(names))] for r, f in enumerate(rows)
    ]
    return text_tsv(["freq_hz", *names], body)


def spectrum_view(values: bytes, names=NAMES_1020, layout: bytes | None = None):
    """The example's spectrum with these files: a layout, or names in the header."""
    spectrum = copy.deepcopy(preset_views()["spectrum"])
    sensor = (
        {"role": "layout", "column": "name"} if layout is not None else {"header": True}
    )
    entry = data_entry(
        "values",
        _location(spectrum, "values"),
        values,
        columns=[col("freq_hz", unit="Hz")] + [col(n, unit="dB") for n in names],
        dims=[
            dim("freq", "rows", "number", {"column": "freq_hz"}, unit="Hz"),
            dim("sensor", "columns", "string", sensor),
        ],
    )
    files = {entry["location"]: values}
    data = [entry]
    if layout is not None:
        layout_entry = copy.deepcopy(spectrum["data"][1])
        layout_entry.update(size=len(layout), sha256=hashlib.sha256(layout).hexdigest())
        data.append(layout_entry)
        files[layout_entry["location"]] = layout
    spectrum["data"] = data
    return spectrum, files


def spectrum_maps_cases() -> list[Case]:
    """nemar.spectrum drawn by its base, with the maps a renderer that knows
    it draws: at each frequency asked for, the row it snaps to."""
    layout = chanlocs(types=["EEG"] * 19)
    values = spectrum_text()
    out = []
    for name, covers, built, hz in [
        (
            "spectrum_maps_layout",
            "The lines by their base, and maps at initial_maps_hz over the "
            "layout: minmax limits, each map labeled by its row's frequency.",
            spectrum_view(values, layout=layout),
            [6, 10, 22, 50],
        ),
        (
            "spectrum_maps_snap",
            "Frequencies between rows snap as the readout does: 7 is the tie "
            "between 6 and 8 and reads 6; 7.5 reads 8; 100 reads the last row.",
            spectrum_view(values, layout=layout),
            [7, 7.5, 100],
        ),
        (
            "spectrum_maps_names",
            "No layout: the header's sensor names are placed by "
            "nemar.sensor-labels.v1 (standard_1005).",
            spectrum_view(values),
            [10],
        ),
        (
            "spectrum_maps_layout_fault",
            "A layout theta NA: the lines read only the layout's names and are "
            "drawn, and every map shows cell_not_number.",
            spectrum_view(values, layout=_replace(layout, "\t-54\t", "\tNA\t")),
            [10],
        ),
        (
            "spectrum_maps_sensors_mismatch",
            "A layout listed in the other order than the sensor columns: the "
            "lines are drawn, and every map shows sensors_mismatch, never a value "
            "at another sensor's place.",
            spectrum_view(values, layout=chanlocs(TEN_TWENTY[::-1])),
            [10],
        ),
        (
            "spectrum_maps_too_few",
            "Seven sensors: the lines are drawn and every map is too_few_sensors.",
            spectrum_view(
                spectrum_text(NAMES_1020[:7]),
                NAMES_1020[:7],
                chanlocs(TEN_TWENTY[:7], types=["EEG"] * 7),
            ),
            [10, 22],
        ),
        (
            "spectrum_maps_base_refused",
            "Two rows at one frequency: the base refuses (x_not_increasing), "
            "the view falls back to its tables, and there are no maps.",
            spectrum_view(spectrum_text(rows=[0.0, 2.0, 2.0, 4.0]), layout=layout),
            [2],
        ),
    ]:
        out.append(Case(name, covers, built[0], built[1], maps=hz))
    return out


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


IC_COMPONENTS = [f"IC{i:03d}" for i in range(1, 19)]


def components_table(names: list[str], header: str = "component") -> bytes:
    rows = [f"{header} variance_pct brain other"]
    rows += [f"{name} {30 / (i + 1):.4f} 0.9 0.1" for i, name in enumerate(names)]
    return tsv(*rows)


def ic_maps_files(components: bytes, layout: bytes | None = None) -> tuple:
    """The example's component maps with every file its base and it read: the
    mixing matrix (19 sensors, 18 components), the layout and the components
    table. Returns the view and its files by location."""
    files = {
        "values": mixing(19, 18),
        "layout": chanlocs(types=["EEG"] * 19) if layout is None else layout,
        "components": components,
    }
    built = preset_views()["icmaps"]
    for role, data in files.items():
        built = _with_file(built, role, data)
    return built, {_location(built, role): data for role, data in files.items()}


def ic_maps_check_cases() -> list[Case]:
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
            components_table([*IC_COMPONENTS, "IC019"]),
        ),
        (
            "ic_maps_renamed",
            "IC1 is not IC001: names compare as text.",
            components_table([f"IC{i}" for i in range(1, 19)]),
        ),
        (
            "ic_maps_no_column",
            "The file has no column component (the generic word).",
            components_table(IC_COMPONENTS, header="name"),
        ),
        (
            "ic_maps_ragged",
            "A row with a cell missing (the generic word).",
            components_table(IC_COMPONENTS) + b"IC019\t1\n",
        ),
    ]:
        out.append(Case(name, covers, *ic_maps_files(data)))
    view, files = ic_maps_files(components_table(IC_COMPONENTS))
    tampered = components_table(IC_COMPONENTS).replace(b"0.9", b"0.8", 1)
    files[_location(view, "components")] = tampered
    out.append(
        Case(
            "ic_maps_digest",
            "The components file is not the one recorded.",
            view,
            files,
        )
    )
    short = chanlocs(TEN_TWENTY[:18], types=["EEG"] * 18)
    out.append(
        Case(
            "ic_maps_base_refuses",
            "The layout a row short of the mixing matrix, and the components out "
            "of order: the base refuses first (coords_length) and the view falls "
            "back, so the preset's check never runs.",
            *ic_maps_files(
                components_table(
                    [IC_COMPONENTS[1], IC_COMPONENTS[0], *IC_COMPONENTS[2:]]
                ),
                short,
            ),
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
                    "good Fp1 EEG",
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
    for case in [*ic_maps_check_cases(), *ic_classes_check_cases()]:
        expected = check_preset(case.view, case.files, REGISTRY)
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
            "fallback (the base itself refused the file first). A case's caps take "
            "the place of the registry's caps of the same names for that case."
        ),
        "cases": cases,
    }


def sensor_field_verdicts() -> list[tuple[str, str, dict]]:
    """Measured positions carry their types; template positions may not."""
    template = {
        "coordinate_system": "n/a",
        "position_source": "template",
        "montage": "standard_1005",
    }
    return [
        (
            "sensor_field_measured_layout_typed",
            "A measured layout that declares sensor_type.",
            field_view(mixing(), chanlocs())[0],
        ),
        (
            "sensor_field_measured_layout_untyped",
            "A measured layout without sensor_type: refused, since a scalp map "
            "draws a measured row only when it is typed EEG.",
            field_view(mixing(), chanlocs(types=None))[0],
        ),
        (
            "sensor_field_template_layout_untyped",
            "A template layout without sensor_type: valid.",
            field_view(mixing(), chanlocs(types=None), layout=template)[0],
        ),
        (
            "sensor_field_measured_positions_untyped",
            "Measured positions without sensor_type: refused.",
            field_view(mixing(), electrodes(types=None), "positions")[0],
        ),
        (
            "sensor_field_template_positions_untyped",
            "Template positions without sensor_type: valid.",
            field_view(
                mixing(), electrodes(types=None), "positions", positions=template
            )[0],
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
        (
            "view",
            view_validator(),
            [*view_verdicts(), *preset_verdicts(), *sensor_field_verdicts()],
        ),
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


# ── The example's product ─────────────────────────────────────────────────

# The files of the presets example's stored views (examples/views), shipped at
# their locations under examples/views/product so that the example draws: a
# recording of the 19 electrodes of the 10-20 system, all good, decomposed
# into 18 components (the rank under the average reference). Every number is
# written by + - * / and round, so the bytes are the same on every platform.
EXAMPLE_PRODUCT = ROOT / "examples" / "views" / "product"
EXAMPLE_COMPONENTS = [f"IC{i:03d}" for i in range(1, 19)]
ICLABEL_CLASSES = ["Brain", "Muscle", "Eye", "Heart", "Line Noise", "Channel Noise"]
ICLABEL_CLASSES.append("Other")
# Each component's most probable class, by its index in ICLABEL_CLASSES.
DOMINANT = [0, 0, 2, 0, 1, 0, 2, 0, 6, 0, 3, 0, 1, 4, 0, 5, 6, 0]


COMPONENT_COLUMNS = ["component", "variance_pct", "brain", "muscle", "eye"]
COMPONENT_COLUMNS += ["heart", "line_noise", "channel_noise", "other"]


def decibels(f: float, k: int) -> str:
    """Sensor k's power at f hertz: falling with frequency, an alpha peak."""
    return repr(round(28 - f / 6 + (6 if 8 <= f <= 12 else 0) + (3 * k % 5) / 2, 2))


def example_product() -> dict[str, bytes]:
    """Each stored file of the presets example, by its location."""
    variance = [round(24 / (m + 1), 2) for m in range(18)]
    probabilities = [
        [("0.82" if c == DOMINANT[m] else "0.03") for c in range(7)] for m in range(18)
    ]
    components = text_tsv(
        COMPONENT_COLUMNS,
        [
            [name, repr(variance[m]), *probabilities[m]]
            for m, name in enumerate(EXAMPLE_COMPONENTS)
        ],
    )
    counts = [DOMINANT.count(c) for c in range(7)]
    summed = [
        round(sum(v for v, d in zip(variance, DOMINANT, strict=True) if d == c), 2)
        for c in range(7)
    ]
    classes = {
        "classifier": "ICLabel",
        "categories": ICLABEL_CLASSES,
        "counts": counts,
        "summed_variance_pct": summed,
        "n_components": 18,
    }
    spectrum = text_tsv(
        ["freq_hz", *NAMES_1020],
        [
            [repr(f)] + [decibels(f, k) for k in range(19)]
            for f in (r / 2 for r in range(251))
        ],
    )
    unmixing = text_tsv(
        NAMES_1020, [[pattern(m, k) for k in range(19)] for m in range(18)]
    )
    return {
        f"{PREFIX}_chanlocs.tsv": chanlocs(types=["EEG"] * 19),
        f"{PREFIX}_mixing.tsv": text_tsv(
            EXAMPLE_COMPONENTS,
            [[pattern(k, m) for m in range(18)] for k in range(19)],
        ),
        f"{PREFIX}_components.tsv": components,
        f"{PREFIX}_icclasses.json": (json.dumps(classes, indent=2) + "\n").encode(),
        f"{PREFIX}_spectrum.tsv": spectrum,
        f"{PREFIX}_servingunmixing.tsv": unmixing,
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
    if "maps" in case.queries:
        frequencies = case.queries["maps"]
        maps = spectrum_maps(case.view, case.files, frequencies, case.registry())
        empty = dict.fromkeys(("rows", "refused", "model"))
        out["maps"] = {"hz": frequencies} | (maps or empty)
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
        *sensor_field_cases(),
        *sensor_field_fault_cases(),
        *sensor_field_order_cases(),
        *ic_maps_by_base_cases(),
        *spectrum_maps_cases(),
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
            "bin count overflow). A nemar.sensor-field model (sensor-field.md) "
            "holds each map's word from the scalp-map algorithm; a nemar.spectrum "
            "case's maps give, for the frequencies hz, the rows they snap to and "
            "the model of the scalp maps at them, or the word that refused them "
            "(presets.md). Each refusal's view is refused with word, nothing is "
            "drawn, and downloads lists the files still offered."
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
    """The text of each vectors file, and of each file of the example's product."""
    out = {
        path: dump(document) + "\n"
        for path, document in (
            (MODELS_PATH, models()),
            (VERDICTS_PATH, verdicts()),
            (PRESET_CHECKS_PATH, preset_checks()),
        )
    }
    for location, data in example_product().items():
        out[EXAMPLE_PRODUCT / location] = data.decode("utf-8")
    return out


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
            path.parent.mkdir(parents=True, exist_ok=True)
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
