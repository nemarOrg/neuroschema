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
    layout: bytes = LAYOUT, layout_role: str = "layout", name_type: str = "string"
) -> dict:
    """An unknown kind over nemar.lines whose sensors are named by its layout."""
    sensor = dim("sensor", "columns", "string", {"role": "layout", "column": "name"})
    values = data_entry(
        "values",
        f"{PREFIX}_numbered.tsv",
        NUMBERED,
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
    printing = b'{"edges": [-1E-7, 0, 0.1, 0.25, 1e21], "counts": [1, 2, 3, 4],' + (
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
            "Edge labels print numbers as ECMAScript String(x): -1e-7, 0.1, 1e+21.",
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


def _errors(validator, instance) -> list[list[str]]:
    pairs = {
        (e.validator, "/".join(str(p) for p in e.absolute_path))
        for e in validator.iter_errors(instance)
    }
    return [list(pair) for pair in sorted(pairs)]


def verdicts() -> dict:
    cases = []
    for schema, validator, items in [
        ("view", view_validator(), view_verdicts()),
        (HISTOGRAM_CONTENT, histogram_content_validator(), content_verdicts()),
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
            "and compare it with model: numbers by binary64 equality, texts "
            "exactly. snaps give the row a pointer at x reads, and locates the bin "
            "that holds a value (-1 underflow, the bin count overflow). Each "
            "refusal's view is refused with word, nothing is drawn, and downloads "
            "lists the files still offered."
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
