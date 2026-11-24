"""Write the nemar.ic-activity.v1 vectors from the cases defined here.

Writes ``views/vectors/ic-activity.v1.json``: the transform's cases (a view
declaration, its files, a store and a window, with the activations before and
after the display filter, or the word that refuses them), the store digest
states, the display filter's coefficients and its cases (windows shorter than
the padding among them). ``docs/views/ic-activity.md`` says how a renderer
replays them.

The expected values come from the Python reference
(``neuroschema.views.ic_activity``), which follows the specification's order of
operations. The cases' inputs (each unmixing matrix, each store's digital
values, each filter input) are frozen in ``scripts/ic_activity_vector_inputs.json``
and read from there, so a platform's sine or a random generator's version
cannot move them; ``--refresh-inputs`` recomputes them and rewrites that file.

With ``--check`` it writes nothing: it regenerates the vectors in memory and
fails if they differ from the committed file beyond the regeneration tolerance
(the filter's coefficients start from a tangent, which a platform's library may
round differently in the last bit; everything else must match exactly). When
scipy is installed (the ``vectors`` group) it also holds the reference to scipy:
the filter to ``filtfilt(*butter(2, f, 'highpass', fs=rate), padlen=p)`` and the
multiply to numpy's matrix product. Run it with the ``vectors`` group::

    uv run --group vectors --extra views \
        python scripts/generate_ic_activity_vectors.py --check
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from neuroschema.views import ic_activity as ia
from neuroschema.views.digest import canonicalize

ROOT = Path(__file__).resolve().parent.parent
VECTORS_PATH = ROOT / "views" / "vectors" / "ic-activity.v1.json"
INPUTS = Path(__file__).resolve().parent / "ic_activity_vector_inputs.json"
SPEC = "docs/views/ic-activity.md"

# Regeneration tolerance for --check, relative to each component's (or filter
# input's) largest magnitude: far inside the parity tolerance, wide enough for
# a tangent rounded differently in the last bit.
CHECK = 1e-10
# The reference against scipy and numpy's matrix product, relative likewise.
SCIPY = 1e-9
# The parity tolerance a renderer is held to (ic-activity.md, Parity).
PARITY = 1e-6

FROZEN: dict | None = None  # the stored inputs; None while refreshing them
FRESH: dict = {"cases": {}, "filters": {}}


def frozen(family: str, name: str, compute):
    """A case's inputs: the stored ones, or, while refreshing, freshly computed."""
    if FROZEN is None:
        FRESH[family][name] = compute()
        return FRESH[family][name]
    stored = FROZEN[family].get(name)
    if stored is None:
        sys.exit(f"no frozen inputs for {family} {name}: run --refresh-inputs")
    FRESH[family][name] = stored
    return stored


# ── Building cases ────────────────────────────────────────────────────────


PREFIX = "sub-01/eeg/sub-01_task-rest_desc-nemarica"
RECORDING = "sub-01/eeg/sub-01_task-rest_eeg.set"
STORE_PATH = "sub-01/eeg/sub-01_task-rest_eeg.zarr"
UNMIXING_AT = f"{PREFIX}_servingunmixing.tsv"
COMPONENTS_AT = f"{PREFIX}_components.tsv"
SEGMENTS_AT = f"{PREFIX}_badsegments.tsv"
# The sentences nemar-process writes in browser_transform (nemar_ica/steps.py,
# nemarOrg/nemar-process#81), mirrored so the declarations are the ones P5 writes.
APPLIES_TO = "serving_copy channels listed, physical unit"
APPLIES_TO_LABELS = (
    "serving_copy channels matched by label, in microvolts: the view converts by the "
    "store's unit field and refuses an unknown unit or any channel it cannot match"
)
NOTE = "no preprocessing; activations approximate the decomposition input"
CAPTION_UNCHECKED = "not checked against the decomposition input"
CLASSES = ["brain", "muscle", "eye", "heart", "line_noise", "channel_noise", "other"]
PREPROCESSING = [
    {"step": "select", "function": "eegprep.pop_select"},
    {"step": "flatline", "function": "eegprep.clean_flatlines"},
    {"step": "drift", "function": "eegprep.pop_eegfiltnew"},
    {"step": "bad_channels", "function": "eegprep.clean_channels"},
    {"step": "asr", "function": "eegprep.clean_asr"},
    {"step": "reref", "function": "eegprep.pop_reref"},
]


def tsv_text(*rows: str) -> bytes:
    """A TSV file from rows whose cells are separated by single spaces."""
    return "".join(row.replace(" ", "\t") + "\n" for row in rows).encode()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def cell(value: float) -> str:
    """A number as the recipes write it: ``.17g``, read back to the same float."""
    return format(value, ".17g")


def matrix_text(header: list[str], rows) -> bytes:
    lines = ["\t".join(header)] + ["\t".join(cell(v) for v in row) for row in rows]
    return ("\n".join(lines) + "\n").encode()


def components_text(count: int) -> bytes:
    lines = ["\t".join(["component", "variance_pct", *CLASSES])]
    for i in range(count):
        share = round(30.0 / (i + 1), 4)
        probabilities = ["0.125000"] * len(CLASSES)
        lines.append("\t".join([f"IC{i + 1:03d}", cell(share), *probabilities]))
    return ("\n".join(lines) + "\n").encode()


# The floor's bad segments: ASR's repaired spans (burst, flagged, never removed)
# and the floor's bad windows; a view shades the burst rows only.
SEGMENTS = tsv_text(
    "onset duration label nemar_reason",
    "0.100000 0.040000 burst asr_repaired",
    "0.200000 0.120000 bad_window clean_windows",
    "0.360000 0.200000 burst asr_repaired",
)
NO_LABEL = tsv_text(
    "onset duration nemar_reason",
    "0.100000 0.040000 asr_repaired",
)
ONSET_TEXT = tsv_text(
    "onset duration label nemar_reason",
    "n/a 0.040000 burst asr_repaired",
)
# Columns are found by name, in any position.
REORDERED = tsv_text(
    "label nemar_reason onset duration",
    "burst asr_repaired 0.100000 0.040000",
    "bad_window clean_windows 0.200000 0.120000",
    "burst asr_repaired 0.360000 0.200000",
)
# The floor's segments with the label spelled another way: no row is "burst".
MISSPELLED = tsv_text(
    "onset duration label nemar_reason",
    "0.100000 0.040000 Burst asr_repaired",
    "0.200000 0.120000 bad_window clean_windows",
)
# Bad windows only: ASR repaired nothing the floor recorded.
WINDOWS_ONLY = tsv_text(
    "onset duration label nemar_reason",
    "0.200000 0.120000 bad_window clean_windows",
)
# Two faults in one table: the onset column is read before the duration.
ONSET_AND_DURATION = tsv_text(
    "onset duration label nemar_reason",
    "n/a 1e400 burst asr_repaired",
)


def corrupt_cell(text: bytes) -> bytes:
    """The matrix with its first data cell replaced by text that is no number."""
    header, first, rest = text.split(b"\n", 2)
    cells = first.split(b"\t")
    return b"\n".join([header, b"\t".join([b"x1", *cells[1:]]), rest])


def file_input(role: str, location: str, data: bytes) -> dict:
    return {
        "role": role,
        "file": {
            "location": location,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        },
    }


class Case:
    """One view over one store and window, and what it gives or the word."""

    def __init__(
        self,
        name: str,
        covers: str,
        view: dict,
        files: dict,
        store: dict,
        window: tuple[int, int],
        caps: dict | None = None,
        bursts_repaired: bool | None = None,
    ):
        self.name, self.covers, self.view = name, covers, view
        self.files, self.store, self.window = files, store, window
        self.caps = caps or {}
        self.bursts_repaired = bursts_repaired


def declaration(
    header: list[str],
    weights,
    count: int,
    *,
    match: str,
    unit: str,
    rows=None,
    profile: str = "serving",
    declared: str | None,
    highpass_hz: float = 1.0,
    segments: bool | bytes = False,
    unmixing: bytes | None = None,
    components: bytes | None = None,
    columns: list[str] | None = None,
) -> tuple[dict, dict]:
    """A nemar.ic-activity view as nemar-ica declares it, and its files: the
    transform's parameters are the record's browser_transform block."""
    unmixing = matrix_text(header, weights) if unmixing is None else unmixing
    components = components_text(count) if components is None else components
    files = {UNMIXING_AT: unmixing, COMPONENTS_AT: components}
    inputs = [
        file_input("unmixing", UNMIXING_AT, unmixing),
        {
            "role": "signal",
            "store": {
                "recording": RECORDING,
                "path": STORE_PATH,
                "group": "eeg",
                "content_sha256": declared,
                "profile": profile,
            },
        },
        file_input("components", COMPONENTS_AT, components),
    ]
    if segments:
        table = SEGMENTS if segments is True else segments
        files[SEGMENTS_AT] = table
        inputs.append(file_input("badsegments", SEGMENTS_AT, table))
    serving = profile == "serving"
    transform = {
        "matrix": UNMIXING_AT,
        "applies_to": APPLIES_TO if match == "store_row" else APPLIES_TO_LABELS,
        "note": NOTE,
        "match": match,
        "rows": None if rows is None else list(rows),
        "columns": list(header) if columns is None else columns,
        "unit": unit,
        "caption": None if match == "store_row" else CAPTION_UNCHECKED,
        "shaded": {
            "label": "burst",
            "files": [SEGMENTS_AT] if segments else None,
        },
    }
    typed = [[label, "EEG"] for label in header]
    decomposition = {
        "source": "serving_copy" if serving else "archive",
        "preprocessing": PREPROCESSING,
        "channels": list(header),
        "channel_types": typed,
        "channel_types_sha256": ia.channel_types_sha256(typed),
        "reference": "average",
        "unit": "uV",
    }
    if serving:
        decomposition["store"] = {
            "path": STORE_PATH,
            "group": "eeg",
            "content_sha256": declared,
        }
    view = {
        "key": "icactivity",
        "kind": "nemar.ic-activity",
        "kind_version": 1,
        "base": "nemar.lines",
        "base_version": 1,
        "caption": (
            "Component activations computed in your browser from the serving copy, "
            "with no preprocessing; they approximate the decomposition's input."
        ),
        "source": {"recipe": {"name": "nemar-ica", "version": "1.0.0-b1"}},
        "inputs": inputs,
        "transform": {"name": ia.IC_ACTIVITY, "parameters": transform},
        "parameters": {
            "display_filter": {"highpass_hz": highpass_hz, "order": 2},
            "max_window_s": 30,
            "decomposition_input": decomposition,
        },
    }
    return view, files


def store(labels, units, scale, offset, digital, rate=250.0, published=None) -> dict:
    return {
        "labels": list(labels),
        "units": list(units),
        "scale": list(scale),
        "offset": list(offset),
        "rate": rate,
        "published_sha256": published,
        "digital": digital,
    }


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def synthetic_digital(seed: int, rows: int, samples: int, rate: float = 250.0):
    """Stored integers of a plausible recording: rhythms, drift, noise, int16."""
    rng = _rng(seed)
    t = np.arange(samples) / rate
    out = []
    for r in range(rows):
        alpha = 400 * math.sin(r) * np.sin(2 * np.pi * 10 * t + r)
        drift = 2000 * np.sin(2 * np.pi * 0.05 * t + 0.3 * r)
        line = 150 * np.sin(2 * np.pi * 50 * t)
        noise = rng.normal(0, 120, samples)
        values = np.clip(
            np.round(alpha + drift + line + noise + 300 * r), -32768, 32767
        )
        out.append([int(v) for v in values])
    return out


def serving_weights(seed: int, components: int, channels: int, factor: float):
    """A browser's matrix: unmixing less each row's mean, times the factor."""
    rng = _rng(seed)
    weights = rng.normal(0, 1, (components, channels)) / math.sqrt(channels)
    referenced = weights - weights.mean(axis=1, keepdims=True)
    return [[float(v) for v in row] for row in referenced * factor]


def plain_weights(seed: int, components: int, channels: int):
    """A matrix whose rows do not sum to zero: no reference folded in."""
    rng = _rng(seed)
    return [
        [float(v) for v in row] for row in rng.normal(0.1, 1, (components, channels))
    ]


# Stores: labels, units, scale and offset per row.
LABELS_32 = [f"E{i}" for i in range(1, 31)] + ["ECG", "STATUS"]
SMALL = ["Fp1", "Fp2", "Cz", "Pz", "O1", "O2"]


def transform_cases() -> list[Case]:
    cases = []

    # A decomposition of the serving copy: 32 store rows (30 EEG, ECG, a status
    # channel), 28 kept (E5 and E17 bad), rank 27, the store in microvolts with
    # the micro sign; the matrix takes the store's unit, so every factor is 1.
    kept = [r for r in range(30) if r not in (4, 16)]
    header = [LABELS_32[r] for r in kept]
    digital = frozen(
        "cases",
        "serving_32",
        lambda: {
            "digital": synthetic_digital(32, 32, 145),
            "weights": serving_weights(1032, 27, 28, 1.0),
        },
    )
    scale = [0.0390625 + 0.001 * r for r in range(30)] + [0.5, 1.0]
    offset = [0.0] * 10 + [-12.5] * 10 + [3.25] * 10 + [0.0, 0.0]
    units = ["µV"] * 31 + [None]
    sha = digest("serving_32")
    view, files = declaration(
        header,
        digital["weights"],
        27,
        match="store_row",
        unit="µV",
        rows=kept,
        declared=sha,
        segments=True,
    )
    cases.append(
        Case(
            "serving_32",
            "A decomposition of the serving copy: 28 of 32 store rows by their rows, "
            "rank 27, factors 1, the digest published and matching.",
            view,
            files,
            store(LABELS_32, units, scale, offset, digital["digital"], published=sha),
            (20, 125),
        )
    )

    # The serving copy in millivolts: the matrix takes millivolts (the factor to
    # microvolts folded in), so the factors are 1 again; the store publishes no
    # digest, so the state is not_checked.
    small = frozen(
        "cases",
        "serving_millivolts",
        lambda: {
            "digital": synthetic_digital(6, 6, 60),
            "weights": serving_weights(1006, 4, 5, 1e3),
        },
    )
    rows = [0, 1, 2, 4, 5]
    view, files = declaration(
        [SMALL[r] for r in rows],
        small["weights"],
        4,
        match="store_row",
        unit="mV",
        rows=rows,
        declared=digest("serving_millivolts"),
    )
    cases.append(
        Case(
            "serving_millivolts_not_checked",
            "A store in millivolts (factor 1, the unit folded in); the serving copy "
            "publishes no digest, so the activations are drawn not_checked.",
            view,
            files,
            store(
                SMALL,
                ["mV"] * 6,
                [0.000125] * 6,
                [0.0, 0.5, -0.5, 0.0, 1.25, 0.0],
                small["digital"],
            ),
            (5, 40),
        )
    )

    # A decomposition of the archive: the matrix takes microvolts, its columns
    # are matched by label to a store in volts whose rows are in another order,
    # with a channel the decomposition did not keep; each factor is 1e6.
    archive = frozen(
        "cases",
        "archive_label_volts",
        lambda: {
            "digital": synthetic_digital(7, 7, 50),
            "weights": serving_weights(1007, 4, 5, 1.0),
        },
    )
    store_labels = ["O2", "Cz", "Fp2", "EOG", "Fp1", "O1", "Pz"]
    header = ["Fp1", "Fp2", "Cz", "Pz", "O2"]
    view, files = declaration(
        header,
        archive["weights"],
        4,
        match="label",
        unit="uV",
        profile="archive",
        declared=None,
    )
    cases.append(
        Case(
            "archive_label_volts",
            "A decomposition of the archive: columns matched by label, in another "
            "order than the store's rows; the store in volts, the matrix in "
            "microvolts, so each factor is 1e6; no digest declared.",
            view,
            files,
            store(
                store_labels,
                ["V"] * 7,
                [1e-7] * 7,
                [0.0, 0.0, 2e-6, 0.0, 0.0, -1e-6, 0.0],
                archive["digital"],
                published=digest("published"),
            ),
            (10, 30),
        )
    )

    # Units row by row: microvolts in three spellings, millivolts and volts.
    mixed = frozen(
        "cases",
        "archive_label_mixed_units",
        lambda: {
            "digital": synthetic_digital(5, 5, 30),
            "weights": serving_weights(1005, 3, 5, 1.0),
        },
    )
    header = ["Fp1", "Fp2", "Cz", "Pz", "O1"]
    view, files = declaration(
        header,
        mixed["weights"],
        3,
        match="label",
        unit="uV",
        profile="archive",
        declared=None,
    )
    cases.append(
        Case(
            "archive_label_mixed_units",
            "Each column's factor from its own row's unit: uV, U+00B5, U+03BC, mV, V.",
            view,
            files,
            store(
                header,
                ["uV", "µV", "μV", "mV", "V"],
                [0.1, 0.1, 0.1, 1e-4, 1e-7],
                [0.0] * 5,
                mixed["digital"],
            ),
            (0, 30),
        )
    )

    # A matrix whose rows do not sum to zero: a renderer that average-references
    # the store's values again changes the result.
    plain = frozen(
        "cases",
        "rows_not_zero_sum",
        lambda: {
            "digital": synthetic_digital(4, 4, 40),
            "weights": plain_weights(1004, 3, 4),
        },
    )
    header = SMALL[:4]
    sha = digest("rows_not_zero_sum")
    view, files = declaration(
        header,
        plain["weights"],
        3,
        match="store_row",
        unit="uV",
        rows=[0, 1, 2, 3],
        declared=sha,
    )
    cases.append(
        Case(
            "rows_not_zero_sum",
            "No reference is applied: the matrix's rows do not sum to zero here, so "
            "re-referencing the store's values would change the activations.",
            view,
            files,
            store(
                header,
                ["uV"] * 4,
                [0.25] * 4,
                [10.0, -10.0, 5.0, 0.0],
                plain["digital"],
                published=sha,
            ),
            (3, 37),
        )
    )

    # A duplicate label in the store: by rows it is no fault.
    dup = frozen(
        "cases",
        "store_row_duplicate_label",
        lambda: {
            "digital": synthetic_digital(3, 4, 20),
            "weights": serving_weights(1003, 2, 3, 1.0),
        },
    )
    labels = ["Cz", "Pz", "Cz", "Oz"]
    sha = digest("store_row_duplicate_label")
    view, files = declaration(
        ["Pz", "Cz", "Oz"],
        dup["weights"],
        2,
        match="store_row",
        unit="uV",
        rows=[1, 2, 3],
        declared=sha,
    )
    cases.append(
        Case(
            "store_row_duplicate_label",
            "A label twice in the store: matching by rows reads row 2, the row the "
            "decomposition read, where matching by label would refuse.",
            view,
            files,
            store(
                labels, ["uV"] * 4, [0.5] * 4, [0.0] * 4, dup["digital"], published=sha
            ),
            (0, 20),
        )
    )

    # Short windows and the last samples of a recording.
    for count in (1, 2, 9, 10):
        cases.append(_short(count))
    cases.append(
        Case(
            "last_window",
            "A window that ends at the recording's last sample.",
            *_small_view(),
            _small_store(),
            (45, 15),
        )
    )
    cases.append(
        Case(
            "no_bad_segment_table",
            "The floor wrote no bad-segment table (shaded.files null): the view "
            "declares none, draws, shades nothing and says so (no_bad_segment_table).",
            *_small_view(),
            _small_store(),
            (0, 60),
        )
    )
    cases.append(
        Case(
            "segments_columns_reordered",
            "The bad segments' columns in another order: found by name, the same "
            "spans shaded.",
            *_small_view(segments=REORDERED),
            _small_store(),
            (0, 60),
        )
    )
    cases.append(
        Case(
            "shaded_burst_rows",
            "Bad segments of two labels: the view shades exactly the rows whose "
            "label is shaded.label (burst), in file order.",
            *_small_view(segments=True),
            _small_store(),
            (0, 60),
        )
    )
    view, files = _small_view()
    rows = view["transform"]["parameters"]["rows"]
    view["transform"]["parameters"]["rows"] = [float(row) for row in rows]
    cases.append(
        Case(
            "rows_written_as_floats",
            "Store rows written 0.0, 1.0 and so on: JSON reads them as the "
            "integers 0, 1 and so on in every reader (JavaScript cannot tell them "
            "apart), so the activations are those of integer rows (probe p7).",
            view,
            files,
            _small_store(),
            (0, 60),
        )
    )
    cases.append(
        Case(
            "shaded_bursts_repaired",
            "The record says ASR repaired spans (bursts_repaired true) and the "
            "table has burst rows: those rows are shaded, with no note.",
            *_small_view(segments=True),
            _small_store(),
            (0, 60),
            bursts_repaired=True,
        )
    )
    cases.append(
        Case(
            "segments_label_unmatched_unknown",
            "No row is labeled burst (the table says Burst) and the renderer does "
            "not know whether ASR repaired a span: drawn, nothing shaded, and the "
            "note no_shaded_rows says so (probe p7).",
            *_small_view(segments=MISSPELLED),
            _small_store(),
            (0, 60),
        )
    )
    cases.append(
        Case(
            "segments_none_repaired",
            "The record says ASR repaired nothing (bursts_repaired false) and the "
            "table holds bad windows only: drawn with the note no_shaded_rows.",
            *_small_view(segments=WINDOWS_ONLY),
            _small_store(),
            (0, 60),
            bursts_repaired=False,
        )
    )
    cases.append(
        Case(
            "highpass_40_hz",
            "A display cutoff of 40 Hz at 250 Hz, where the prewarped tangent and its "
            "argument differ by a tenth.",
            *_small_view(highpass_hz=40.0),
            _small_store(),
            (0, 60),
        )
    )
    return cases


def _small_inputs() -> dict:
    return frozen(
        "cases",
        "small",
        lambda: {
            "digital": synthetic_digital(11, 6, 60),
            "weights": serving_weights(1011, 4, 6, 1.0),
        },
    )


def _small_view(**fields) -> tuple[dict, dict]:
    sha = fields.pop("declared", digest("small"))
    return declaration(
        SMALL,
        _small_inputs()["weights"],
        4,
        match="store_row",
        unit="uV",
        rows=list(range(6)),
        declared=sha,
        **fields,
    )


def _small_store(**fields) -> dict:
    values = {
        "labels": SMALL,
        "units": ["uV"] * 6,
        "scale": [0.1] * 6,
        "offset": [0.0] * 6,
        "digital": _small_inputs()["digital"],
        "published": digest("small"),
    }
    values.update(fields)
    return store(**values)


def _short(count: int) -> Case:
    padding = ia.padding(count)
    return Case(
        f"short_window_{count}",
        f"A window of {count} sample{'s' if count > 1 else ''}: the odd extension "
        f"is {padding} sample{'s' if padding != 1 else ''} at each end.",
        *_small_view(),
        _small_store(),
        (30, count),
    )


def refusals() -> list[Case]:
    out = []

    def refused(
        name,
        covers,
        view_files=None,
        store_=None,
        window=(0, 20),
        caps=None,
        bursts_repaired=None,
    ):
        view, files = view_files or _small_view()
        store_ = store_ or _small_store()
        out.append(
            Case(name, covers, view, files, store_, window, caps, bursts_repaired)
        )

    def without_segments(view: dict) -> dict:
        return view | {
            "inputs": [i for i in view["inputs"] if i["role"] != "badsegments"]
        }

    view, files = _small_view(segments=True)
    refused(
        "segments_named_not_declared",
        "The record names the floor's bad-segment table (shaded.files) and the "
        "view does not declare it: declaration_invalid, never drawn unshaded.",
        (without_segments(view), files),
    )
    view, files = _small_view(segments=True)
    view["transform"]["parameters"]["shaded"]["files"] = None
    refused(
        "segments_declared_not_named",
        "A bad-segments input when shaded.files is null: declaration_invalid.",
        (view, files),
    )
    view, files = _small_view(segments=True)
    refused(
        "kind_reusing_the_transform_drops_segments",
        "A kind the registry does not list that reuses the transform and drops "
        "the bad segments the record names: the transform's schema holds the "
        "rule, so declaration_invalid, not a note that there is no table "
        "(probe p14).",
        (without_segments(view) | {"kind": "acme.activity"}, files),
    )
    view, files = _small_view(segments=True)
    del files[UNMIXING_AT]
    refused(
        "order_declaration_before_files",
        "An invalid declaration and a missing matrix: the declaration comes first.",
        (without_segments(view), files),
    )
    # The record's names for the inputs, and the decomposition's store.
    decoy = tsv_text("onset duration label nemar_reason")
    decoy_at = "sub-01/eeg/other_badsegments.tsv"
    view, files = _small_view(segments=True)
    files[decoy_at] = decoy
    for given in view["inputs"]:
        if given["role"] == "badsegments":
            given["file"] = file_input("badsegments", decoy_at, decoy)["file"]
    refused(
        "segments_location_differs",
        "The badsegments input reads a decoy table with no rows where "
        "shaded.files names the floor's: table_location_mismatch, never drawn "
        "with nothing shaded (probe p7).",
        (view, files),
    )
    view, files = _small_view(segments=True)
    other = "sub-01/eeg/sub-01_task-rest_run-2_desc-nemarica"
    for given in view["inputs"]:
        if "file" in given:
            role, old = given["role"], given["file"]["location"]
            moved = other + old.removeprefix(PREFIX)
            files[moved] = files.pop(old)
            given["file"]["location"] = moved
            if role == "unmixing":
                view["transform"]["parameters"]["matrix"] = moved
            if role == "badsegments":
                view["transform"]["parameters"]["shaded"]["files"] = [moved]
    refused(
        "tables_of_another_recording",
        "The matrix, the components and the bad segments of run 2, named for it "
        "and consistent with matrix and shaded.files: not the recording's, so "
        "table_location_mismatch (review r29).",
        (view, files),
    )
    view, files = _small_view()
    moved = "sub-01/eeg/sub-01_task-rest_desc-nemarfloor_components.tsv"
    files[moved] = files.pop(COMPONENTS_AT)
    for given in view["inputs"]:
        if given["role"] == "components":
            given["file"]["location"] = moved
    refused(
        "tables_two_stems",
        "The components table under another stem (desc-nemarfloor) than the "
        "matrix's (desc-nemarica): table_location_mismatch.",
        (view, files),
    )
    view, files = _small_view()
    view["transform"]["parameters"]["matrix"] = f"{PREFIX}_unmixing.tsv"
    refused(
        "matrix_location_differs",
        "The unmixing input is not the file the record's matrix names: "
        "table_location_mismatch.",
        (view, files),
    )
    for name, member, value, covers in [
        (
            "decomposition_store_digest_differs",
            "content_sha256",
            "f" * 64,
            "The decomposition's store names another digest than the signal "
            "store: store_mismatch, so a state of matches would be about another "
            "store (probe p7).",
        ),
        (
            "decomposition_store_path_differs",
            "path",
            "sub-01/eeg/sub-01_task-other_eeg.zarr",
            "The decomposition's store is another path than the signal store's.",
        ),
        (
            "decomposition_store_group_differs",
            "group",
            "meg",
            "The decomposition read another channel group than the signal's.",
        ),
    ]:
        view, files = _small_view()
        view["parameters"]["decomposition_input"]["store"][member] = value
        refused(name, covers, (view, files))
    view, files = _small_view(segments=True)
    view["transform"]["parameters"]["matrix"] = f"{PREFIX}_unmixing.tsv"
    refused(
        "order_declaration_before_locations",
        "An invalid declaration (the bad segments named and not declared) and a "
        "matrix at another location: the declaration comes first.",
        (without_segments(view), files),
    )
    view, files = _small_view()
    view["transform"]["parameters"]["matrix"] = f"{PREFIX}_unmixing.tsv"
    view["parameters"]["decomposition_input"]["store"]["content_sha256"] = "f" * 64
    refused(
        "order_locations_before_store",
        "A matrix at another location and a decomposition store of another "
        "digest: the locations come first.",
        (view, files),
    )
    view, files = _small_view()
    view["parameters"]["decomposition_input"]["store"]["content_sha256"] = "f" * 64
    del files[UNMIXING_AT]
    refused(
        "order_store_before_files",
        "A decomposition store of another digest and a missing matrix: the "
        "store comes first.",
        (view, files),
    )
    view, files = _small_view()
    del files[UNMIXING_AT]
    refused("unmixing_missing", "The matrix's file is absent.", (view, files))
    view, files = _small_view()
    files[UNMIXING_AT] += b"\n"
    refused(
        "unmixing_size",
        "The matrix's file is a byte longer than declared.",
        (view, files),
    )
    view, files = _small_view()
    data = bytearray(files[UNMIXING_AT])
    data[-2] = ord("1") if data[-2] != ord("1") else ord("2")
    files[UNMIXING_AT] = bytes(data)
    refused(
        "unmixing_digest",
        "One digit of the matrix differs from the bytes recorded.",
        (view, files),
    )
    view, files = _small_view()
    data = bytearray(files[COMPONENTS_AT])
    data[-2] = ord("1") if data[-2] != ord("1") else ord("2")
    files[COMPONENTS_AT] = bytes(data)
    refused(
        "components_digest",
        "The components table differs from the bytes recorded.",
        (view, files),
    )
    refused(
        "store_digest_mismatch",
        "The serving copy publishes a digest other than the one the view declares.",
        store_=_small_store(published=digest("another store")),
    )

    weights = _small_inputs()["weights"]
    for name, covers, text in [
        (
            "unmixing_not_a_number",
            "A matrix cell that is not a JSON number.",
            corrupt_cell(matrix_text(SMALL, weights)),
        ),
        (
            "unmixing_not_finite",
            "A matrix cell beyond binary64 range.",
            b"\t".join(SMALL[i].encode() for i in range(6))
            + b"\n"
            + b"\t".join([b"1e400"] + [b"0"] * 5)
            + b"\n",
        ),
        (
            "unmixing_empty",
            "A matrix with a header and no row.",
            ("\t".join(SMALL) + "\n").encode(),
        ),
        (
            "unmixing_ragged",
            "A matrix row with fewer cells than the header.",
            ("\t".join(SMALL) + "\n" + "\t".join(["0"] * 5) + "\n").encode(),
        ),
        (
            "unmixing_header_repeated",
            "A channel named twice in the header.",
            (
                "\t".join([*SMALL[:5], "Fp1"]) + "\n" + "\t".join(["0"] * 6) + "\n"
            ).encode(),
        ),
        (
            "unmixing_byte_order_mark",
            "A matrix that begins with a byte order mark.",
            b"\xef\xbb\xbf" + matrix_text(SMALL, weights),
        ),
        (
            "unmixing_crlf",
            "A matrix whose lines end in CR LF.",
            matrix_text(SMALL, weights).replace(b"\n", b"\r\n"),
        ),
    ]:
        refused(
            name,
            covers,
            declaration(
                SMALL,
                weights,
                4,
                match="store_row",
                unit="uV",
                rows=list(range(6)),
                declared=digest("small"),
                unmixing=text,
            ),
        )
    refused(
        "unmixing_too_many_bytes",
        "A matrix file longer than the cap on bytes per role (lowered to 100).",
        caps={"bytes_per_role": 100},
    )
    refused(
        "components_too_many_cells",
        "A components table of 36 cells under a cap of 30 (lowered), which the "
        "matrix's 24 meet.",
        caps={"cells_per_role": 30},
    )
    refused(
        "unmixing_too_many_rows",
        "More components than the cap on entries per dimension (lowered to 3).",
        caps={"entries_per_dim": 3},
    )
    refused(
        "components_no_column",
        "The components table has no column component.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            components=b"name\tvariance_pct\nIC001\t1\n",
        ),
    )
    refused(
        "components_length",
        "Three component rows for four matrix rows.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            components=components_text(3),
        ),
    )
    refused(
        "components_too_many_rows",
        "Five component rows for four matrix rows.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            components=components_text(5),
        ),
    )

    def rows_view(rows, header=SMALL, match="store_row"):
        """By row, a decomposition of the serving copy; by label, one of the
        archive, which read no store (the serving copy is never matched by label)."""
        by_row = match == "store_row"
        return declaration(
            header,
            weights,
            4,
            match=match,
            unit="uV",
            rows=rows if by_row else None,
            profile="serving" if by_row else "archive",
            declared=digest("small") if by_row else None,
        )

    refused(
        "store_row_label_differs",
        "Rows 0 and 1 swapped: each row's label differs from its column's.",
        rows_view([1, 0, 2, 3, 4, 5]),
    )
    refused(
        "store_row_out_of_range",
        "A row past the store's last.",
        rows_view([0, 1, 2, 3, 4, 6]),
    )
    refused("store_row_count", "Five rows for six columns.", rows_view([0, 1, 2, 3, 4]))
    refused(
        "columns_differ",
        "The record's columns name the matrix's channels in another order.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            columns=[*SMALL[1:], SMALL[0]],
        ),
    )
    refused(
        "channel_label_unmatched",
        "A column whose label no store row has.",
        rows_view(None, header=[*SMALL[:5], "Oz"], match="label"),
    )
    refused(
        "label_case",
        "FP1 is not Fp1: labels compare as exact strings.",
        rows_view(None, header=["FP1", *SMALL[1:]], match="label"),
    )
    refused(
        "label_duplicate",
        "A column's label at two store rows, every other column's at one.",
        rows_view(None, match="label"),
        _small_store(
            labels=[*SMALL, "Cz"],
            units=["uV"] * 7,
            scale=[0.1] * 7,
            offset=[0.0] * 7,
            digital=[*_small_inputs()["digital"], _small_inputs()["digital"][0]],
        ),
    )
    refused(
        "store_unlabeled",
        "A store whose rows have no labels.",
        store_=_small_store(labels=[None] * 6),
    )
    refused(
        "unit_unknown",
        "A store row in nanovolts.",
        store_=_small_store(units=["uV"] * 5 + ["nV"]),
    )
    refused(
        "unit_absent",
        "A store row with no unit.",
        store_=_small_store(units=["uV"] * 5 + [None]),
    )
    refused(
        "filter_out_of_range",
        "A display cutoff at half the rate.",
        _small_view(highpass_hz=125.0),
    )
    refused(
        "store_rate_zero",
        "A store whose rate is 0: rate_invalid, not a division by zero.",
        store_=_small_store(rate=0.0),
    )
    refused(
        "store_rate_negative",
        "A store whose rate is below 0: rate_invalid.",
        store_=_small_store(rate=-250.0),
    )
    refused(
        "window_outside_store",
        "A window that runs past the store's last sample: window_outside_store, "
        "not an error of the renderer's own (probe p12).",
        window=(50, 20),
    )
    refused(
        "window_before_store",
        "A window that starts before the store's first sample.",
        window=(-1, 10),
    )
    refused("window_empty", "A window of no sample.", window=(10, 0))
    refused(
        "window_too_long",
        "A window longer than max_window_s (30 s at 1 Hz: 30 samples).",
        store_=_small_store(rate=1.0),
        window=(0, 31),
    )
    refused(
        "segments_label_unmatched",
        "The record says ASR repaired spans and no row of the table is labeled "
        "burst (it says Burst): label_unmatched, never drawn with the bursts "
        "unshaded (probe p7).",
        _small_view(segments=MISSPELLED),
        bursts_repaired=True,
    )
    refused(
        "segments_label_uppercase",
        "The same with BURST.",
        _small_view(segments=MISSPELLED.replace(b"Burst", b"BURST")),
        bursts_repaired=True,
    )
    refused(
        "order_label_before_match",
        "No burst row where ASR repaired spans, and a column no store row has: "
        "the bad segments come first.",
        declaration(
            [*SMALL[:5], "Oz"],
            weights,
            4,
            match="label",
            unit="uV",
            profile="archive",
            declared=None,
            segments=MISSPELLED,
        ),
        bursts_repaired=True,
    )
    refused(
        "badsegments_duration_negative",
        "A bad segment of negative duration: duration_not_positive.",
        _small_view(
            segments=tsv_text(
                "onset duration label nemar_reason",
                "0.100000 -0.040000 burst asr_repaired",
            )
        ),
    )
    refused(
        "badsegments_duration_zero",
        "A bad segment of no duration: duration_not_positive.",
        _small_view(
            segments=tsv_text(
                "onset duration label nemar_reason", "0.100000 0 burst asr_repaired"
            )
        ),
    )
    refused(
        "order_digest_before_rate",
        "A store digest mismatch and a rate of 0: the digest comes first.",
        store_=_small_store(published=digest("another store"), rate=0.0),
    )
    refused(
        "order_rate_before_window",
        "A rate of 0 and a window past the store's end: the rate comes first.",
        store_=_small_store(rate=0.0),
        window=(50, 20),
    )
    refused(
        "order_window_before_matrix",
        "A window past the store's end and a matrix cell that is not a number: "
        "the window comes first.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            unmixing=corrupt_cell(matrix_text(SMALL, weights)),
        ),
        window=(50, 20),
    )

    # Two faults each: the first check in the specification's order gives the word.
    view, files = _small_view()
    files[COMPONENTS_AT] += b"\n"
    refused(
        "order_file_before_digest",
        "A components file of the wrong size and a "
        "store digest mismatch: the files come first.",
        (view, files),
        _small_store(published=digest("another store")),
    )
    refused(
        "order_digest_before_matrix",
        "A store digest mismatch and a matrix cell "
        "that is not a number: the digest comes first.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            unmixing=corrupt_cell(matrix_text(SMALL, weights)),
        ),
        _small_store(published=digest("another store")),
    )
    refused(
        "order_matrix_before_components",
        "A matrix cell that is not a number and "
        "too few component rows: the matrix comes first.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            unmixing=corrupt_cell(matrix_text(SMALL, weights)),
            components=components_text(3),
        ),
    )
    refused(
        "order_components_before_match",
        "Too few component rows and a row whose "
        "label differs: the components come first.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=[1, 0, 2, 3, 4, 5],
            declared=digest("small"),
            components=components_text(3),
        ),
    )
    view, files = _small_view(segments=True)
    files[SEGMENTS_AT] = SEGMENTS.replace(b"0.120000", b"0.130000", 1)
    refused(
        "badsegments_digest",
        "The bad segments file is not the one recorded: the whole view is refused, "
        "never drawn unshaded.",
        (view, files),
    )
    refused(
        "badsegments_too_many_cells",
        "A bad segments table of 44 cells under a cap of 40 (lowered), which the "
        "matrix's 24 and the components' 36 meet.",
        _small_view(
            segments=tsv_text(
                "onset duration label nemar_reason",
                *[f"{k}.000000 0.010000 burst asr_repaired" for k in range(11)],
            )
        ),
        caps={"cells_per_role": 40},
    )
    refused(
        "badsegments_onset_before_duration",
        "An onset that is no number and a duration beyond binary64: the onset "
        "column is read first.",
        _small_view(segments=ONSET_AND_DURATION),
    )
    view, files = _small_view(segments=True)
    files[COMPONENTS_AT] += b"\n"
    files[SEGMENTS_AT] = SEGMENTS.replace(b"0.120000", b"0.130000", 1)
    refused(
        "order_components_file_before_segments_file",
        "A components file of the wrong size and a bad segments file of the wrong "
        "digest: the components file is checked first.",
        (view, files),
    )
    refused(
        "badsegments_no_label",
        "The bad segments table has no column label.",
        _small_view(segments=NO_LABEL),
    )
    refused(
        "badsegments_onset_not_a_number",
        "A bad segment's onset that is not a number.",
        _small_view(segments=ONSET_TEXT),
    )
    refused(
        "order_components_before_segments",
        "Too few component rows and a bad segments table with no label: the "
        "components come first.",
        declaration(
            SMALL,
            weights,
            4,
            match="store_row",
            unit="uV",
            rows=list(range(6)),
            declared=digest("small"),
            components=components_text(3),
            segments=NO_LABEL,
        ),
    )
    refused(
        "order_segments_before_match",
        "A bad segments table with no label and a column no store row has: the "
        "bad segments come first.",
        declaration(
            [*SMALL[:5], "Oz"],
            weights,
            4,
            match="label",
            unit="uV",
            profile="archive",
            declared=None,
            segments=NO_LABEL,
        ),
    )
    refused(
        "order_match_before_unit",
        "A column no store row has and a row in nanovolts: the match comes first.",
        rows_view(None, header=[*SMALL[:5], "Oz"], match="label"),
        _small_store(units=["nV"] * 6),
    )
    refused(
        "order_unit_before_filter",
        "A row in nanovolts and a cutoff at half the rate: the units come first.",
        _small_view(highpass_hz=125.0),
        _small_store(units=["nV"] * 6),
    )
    return out


# ── The display filter alone ──────────────────────────────────────────────


def filter_inputs() -> dict:
    def compute():
        rng = _rng(77)
        t = np.arange(1000) / 250.0
        wander = np.cumsum(rng.normal(0, 1.5, 1000))
        mains = 20 * np.sin(2 * np.pi * 50 * t)
        alpha = 8 * np.sin(2 * np.pi * 10 * t)
        return {
            "eeg_1000": [float(v) for v in 40 + wander + mains + alpha],
            "offset_1e4": [
                float(v) for v in 1e4 + 0.5 * np.sin(2 * np.pi * 7 * t[:250])
            ],
            "random_short": [float(v) for v in rng.normal(0, 10, 11)],
        }

    return frozen("filters", "inputs", compute)


def filter_cases() -> list[dict]:
    series = filter_inputs()
    ramp = [0.5 * k - 3.0 for k in range(40)]
    step = [0.0] * 20 + [5.0] * 20
    cases = [
        (
            "eeg_250",
            "Four seconds of drift, alpha and mains at 250 Hz, cut at 1 Hz.",
            250.0,
            1.0,
            [series["eeg_1000"]],
        ),
        (
            "eeg_1000_hz",
            "The same samples read at 1000 Hz with a 1 Hz cutoff.",
            1000.0,
            1.0,
            [series["eeg_1000"]],
        ),
        (
            "cutoff_0_1_hz",
            "A cutoff of 0.1 Hz at 500 Hz: a tangent near zero.",
            500.0,
            0.1,
            [series["eeg_1000"][:400]],
        ),
        (
            "cutoff_40_hz",
            "A cutoff of 40 Hz at 250 Hz: the prewarped tangent.",
            250.0,
            40.0,
            [series["eeg_1000"][:200]],
        ),
        (
            "offset_1e4",
            "A large constant offset with a small rhythm.",
            250.0,
            1.0,
            [series["offset_1e4"]],
        ),
        (
            "constant",
            "A constant series filters to zero from its steady state.",
            250.0,
            1.0,
            [[7.25] * 30, [-3.0] * 30],
        ),
        ("zeros", "Zeros stay zeros.", 250.0, 1.0, [[0.0] * 12]),
        ("ramp", "A ramp: the odd extension continues it.", 250.0, 1.0, [ramp]),
        ("step", "A step in the middle of the window.", 250.0, 1.0, [step]),
        (
            "two_rows",
            "Each row filtered on its own.",
            250.0,
            1.0,
            [series["eeg_1000"][:64], series["eeg_1000"][100:164]],
        ),
    ]
    for count in (1, 2, 3, 5, 9, 10, 11):
        cases.append(
            (
                f"window_{count}",
                f"A window of {count} sample{'s' if count > 1 else ''}, odd extension "
                f"of {ia.padding(count)}.",
                250.0,
                1.0,
                [series["random_short"][:count]],
            )
        )
    out = []
    for name, covers, rate, cutoff, rows in cases:
        values = np.array(rows, dtype=np.float64)
        out.append(
            {
                "name": name,
                "covers": covers,
                "rate": rate,
                "highpass_hz": cutoff,
                "padding": ia.padding(values.shape[-1]),
                "input": rows,
                "expected": _floats(ia.display_filter(values, rate, cutoff)),
            }
        )
    return out


# Each row of a loaded recording as [label, type]; the labels outside ASCII are
# written as themselves in RFC 8785, where Python's json.dumps would escape them.
CHANNEL_TYPES = [
    (
        "ascii",
        "Labels and types in ASCII, and an untyped row.",
        [["Fp1", "EEG"], ["Fp2", "EEG"], ["ECG", "ECG"], ["Status", None]],
    ),
    (
        "outside_ascii",
        "Labels outside ASCII: a micro sign, a diaeresis, a CJK label "
        "and a character beyond the Basic Multilingual Plane, each written as itself.",
        [
            ["\u00b5-ref", "EEG"],
            ["\u00d6z", "EEG"],
            ["\u96fb\u6975", None],
            ["\U0001d6fc", "EEG"],
        ],
    ),
    (
        "escapes",
        "A quote, a backslash and a tab in labels: the only escapes RFC 8785 writes.",
        [['Fp1 "a"', "EEG"], ["C\\z", "EEG"], ["P\tz", None]],
    ),
]


def channel_types_digests() -> list[dict]:
    return [
        {
            "name": name,
            "covers": covers,
            "channel_types": typed,
            "canonical": canonicalize({"channel_types": typed}).decode("utf-8"),
            "sha256": ia.channel_types_sha256(typed),
        }
        for name, covers, typed in CHANNEL_TYPES
    ]


COEFFICIENTS = [(250.0, 1.0), (250.0, 40.0), (500.0, 0.1), (1000.0, 1.0), (128.0, 0.5)]


def coefficients() -> list[dict]:
    out = []
    for rate, cutoff in COEFFICIENTS:
        b, a = ia.highpass_coefficients(cutoff, rate)
        out.append(
            {
                "rate": rate,
                "highpass_hz": cutoff,
                "b": list(b),
                "a": list(a),
                "zi": [-b[0], b[2]],
            }
        )
    return out


# ── The documents ─────────────────────────────────────────────────────────


def _floats(array) -> list:
    return [[float(v) + 0.0 for v in row] for row in np.asarray(array)]


def _store_object(spec: dict) -> ia.Store:
    return ia.Store(
        labels=spec["labels"],
        units=spec["units"],
        scale=spec["scale"],
        offset=spec["offset"],
        digital=np.array(spec["digital"], dtype=np.int64),
        rate=spec["rate"],
        published_sha256=spec["published_sha256"],
    )


def _files(files: dict[str, bytes]) -> dict:
    return {
        location: {"text": data.decode("utf-8")} for location, data in files.items()
    }


def _header(case: Case) -> dict:
    out = {
        "name": case.name,
        "covers": case.covers,
        "view": case.view,
        "files": _files(case.files),
        "store": case.store,
        "window": {"start": case.window[0], "count": case.window[1]},
        "bursts_repaired": case.bursts_repaired,
    }
    return out | ({"caps": case.caps} if case.caps else {})


def _run(case: Case) -> ia.Activations:
    caps = ia.CAPS | case.caps
    return ia.ic_activity(
        case.view,
        case.files,
        _store_object(case.store),
        *case.window,
        caps=caps,
        bursts_repaired=case.bursts_repaired,
    )


def _case(case: Case) -> dict:
    result = _run(case)
    return _header(case) | {
        "expected": {
            "state": result.state,
            "components": result.components,
            "rows": result.rows,
            "factors": result.factors,
            "time_s": [float(v) for v in result.time_s],
            "activations": _floats(result.activations),
            "filtered": _floats(result.filtered),
            "shaded": result.shaded,
            "notes": result.notes,
        }
    }


def _refusal(case: Case) -> dict:
    try:
        _run(case)
    except ia.IcActivityRefusal as exc:
        return _header(case) | {"word": exc.word}
    raise AssertionError(f"{case.name}: not refused")


STORE_CHECKS = [
    ("a" * 64, "a" * 64, "matches"),
    ("a" * 64, None, "not_checked"),
    (None, "a" * 64, "not_checked"),
    (None, None, "not_checked"),
    ("a" * 64, "b" * 64, "store_digest_mismatch"),
]


def _store_checks() -> list[dict]:
    out = []
    for declared, published, expected in STORE_CHECKS:
        try:
            got = ia.store_check(declared, published)
        except ia.IcActivityRefusal as exc:
            got = exc.word
        assert got == expected, (declared, published, got)
        out.append({"declared": declared, "published": published, "outcome": got})
    return out


def document() -> dict:
    cases = transform_cases()
    refused = refusals()
    names = [c.name for c in [*cases, *refused]]
    if len(names) != len(set(names)):
        raise AssertionError("case names repeat")
    return {
        "format": ia.IC_ACTIVITY,
        "spec": SPEC,
        "description": (
            "Cases every renderer of nemar.ic-activity reproduces. For each case, "
            "decode files (UTF-8 text), take the store (labels, units, scale and "
            "offset per row, digital values rows by samples, rate, and the digest "
            "the serving copy publishes or null), compute the window's activations "
            "(window.start, window.count samples) with the caps of the registry, or "
            "the case's caps in their place, and compare: state, components, rows "
            "and factors exactly, time_s exactly, and activations and filtered "
            "within tolerance.parity times the component's largest magnitude in "
            "expected.activations. Each refusal is refused with word. store_checks "
            "give the digest states; channel_types_digests give the RFC 8785 text "
            'and SHA-256 of {"channel_types": ...}; coefficients and filter_cases '
            "hold the display filter alone, compared within tolerance.parity times "
            "the largest "
            "magnitude of the input row."
        ),
        "tolerance": {"parity": PARITY},
        "cases": [_case(case) for case in cases],
        "refusals": [_refusal(case) for case in refused],
        "store_checks": _store_checks(),
        "channel_types_digests": channel_types_digests(),
        "coefficients": coefficients(),
        "filter_cases": filter_cases(),
    }


def render() -> str:
    return dumps(document()) + "\n"


def regenerate() -> dict:
    """The vectors as this module writes them from the frozen inputs (no scipy)."""
    global FROZEN
    FROZEN = json.loads(INPUTS.read_text(encoding="utf-8"))
    return json.loads(render())


def dumps(value, depth: int = 0) -> str:
    """JSON with two-space indents and each array of scalars on one line."""
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(value, dict) and value:
        members = [
            f"{inner}{json.dumps(k, ensure_ascii=False)}: {dumps(v, depth + 1)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(members) + f"\n{pad}}}"
    if isinstance(value, list) and any(isinstance(v, dict | list) for v in value):
        items = [f"{inner}{dumps(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(", ", ": ")
    )


# ── Checking ──────────────────────────────────────────────────────────────


def _scaled(new: list, old: list, scales: list[float], path: str) -> list[str]:
    """Rows of numbers compared within CHECK times each row's scale."""
    if len(new) != len(old):
        return [f"{path}: {len(old)} rows -> {len(new)}"]
    out = []
    for i, (a, b, scale) in enumerate(zip(new, old, scales, strict=True)):
        if len(a) != len(b):
            out.append(f"{path}/{i}: length {len(b)} -> {len(a)}")
            continue
        bound = CHECK * scale
        for k, (x, y) in enumerate(zip(a, b, strict=True)):
            if not abs(x - y) <= bound:
                out.append(f"{path}/{i}/{k}: {y!r} -> {x!r}")
    return out


def _row_scales(rows: list) -> list[float]:
    return [max((abs(v) for v in row), default=0.0) for row in rows]


def differences(new, old, path: str = "") -> list[str]:
    """Where two vector documents differ beyond the regeneration tolerance.

    Activations and filtered values are compared within CHECK times each
    component's largest magnitude in the committed activations; a filter case's
    expected values within CHECK times its input row's largest magnitude; a
    coefficient within CHECK of 1 (they are at most 2 in magnitude). Everything
    else must be equal, with its type.
    """
    if isinstance(new, dict) and isinstance(old, dict):
        if set(new) != set(old):
            return [f"{path}: keys {sorted(set(new) ^ set(old))}"]
        out = []
        if "activations" in new and "filtered" in new:
            scales = _row_scales(old["activations"])
            for key in ("activations", "filtered"):
                out += _scaled(new[key], old[key], scales, f"{path}/{key}")
            rest = [k for k in new if k not in ("activations", "filtered")]
        elif "input" in new and "expected" in new:
            scales = _row_scales(old["input"])
            out += _scaled(new["expected"], old["expected"], scales, f"{path}/expected")
            rest = [k for k in new if k != "expected"]
        elif "b" in new and "a" in new:
            for key in ("b", "a", "zi"):
                out += _scaled([new[key]], [old[key]], [1.0], f"{path}/{key}")
            rest = [k for k in new if k not in ("b", "a", "zi")]
        else:
            rest = list(new)
        for key in rest:
            out += differences(new[key], old[key], f"{path}/{key}")
        return out
    if isinstance(new, list) and isinstance(old, list):
        if len(new) != len(old):
            return [f"{path}: length {len(old)} -> {len(new)}"]
        out = []
        for i, (a, b) in enumerate(zip(new, old, strict=True)):
            out += differences(a, b, f"{path}/{i}")
        return out
    if new == old and type(new) is type(old):
        return []
    return [f"{path}: {old!r} -> {new!r}"]


def against_scipy(doc: dict) -> list[str]:
    """Hold the reference to scipy's filtfilt and numpy's matrix product."""
    try:
        from scipy import signal
    except ImportError:
        return ["scipy is not installed: run with `uv run --group vectors`"]
    problems = []

    def compare(name, mine, theirs, scales):
        for i, (a, b, scale) in enumerate(zip(mine, theirs, scales, strict=True)):
            gap = float(np.max(np.abs(np.subtract(a, b)), initial=0.0))
            if not gap <= SCIPY * scale:
                problems.append(f"{name}/{i}: {gap} > {SCIPY} * {scale}")

    for entry in doc["coefficients"]:
        b, a = signal.butter(2, entry["highpass_hz"], "highpass", fs=entry["rate"])
        compare(
            f"coefficients {entry['rate']} {entry['highpass_hz']}",
            [entry["b"], entry["a"]],
            [b, a],
            [1.0, 1.0],
        )
        zi = signal.lfilter_zi(b, a)
        compare("zi", [entry["zi"]], [zi], [1.0])
    for case in doc["filter_cases"]:
        b, a = signal.butter(2, case["highpass_hz"], "highpass", fs=case["rate"])
        rows = np.array(case["input"], dtype=np.float64)
        theirs = signal.filtfilt(b, a, rows, padtype="odd", padlen=case["padding"])
        compare(
            f"filter {case['name']}",
            case["expected"],
            theirs,
            _row_scales(case["input"]),
        )
    for case in doc["cases"]:
        spec, view = case["store"], case["view"]
        expected = case["expected"]
        start, count = case["window"]["start"], case["window"]["count"]
        digital = np.array(spec["digital"], dtype=np.float64)[expected["rows"]]
        scale = np.array(spec["scale"])[expected["rows"]][:, None]
        offset = np.array(spec["offset"])[expected["rows"]][:, None]
        factors = np.array(expected["factors"])[:, None]
        values = (digital[:, start : start + count] * scale + offset) * factors
        unmixing = case["files"][UNMIXING_AT]["text"].encode()
        _header, weights = ia.read_unmixing(unmixing)
        product = weights @ values
        scales = _row_scales(expected["activations"])
        compare(f"multiply {case['name']}", expected["activations"], product, scales)
        cutoff = view["parameters"]["display_filter"]["highpass_hz"]
        b, a = signal.butter(2, cutoff, "highpass", fs=spec["rate"])
        theirs = signal.filtfilt(b, a, product, padtype="odd", padlen=ia.padding(count))
        compare(f"filtfilt {case['name']}", expected["filtered"], theirs, scales)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument(
        "--refresh-inputs",
        action="store_true",
        help=f"recompute the cases' inputs and rewrite {INPUTS.name}",
    )
    args = parser.parse_args(argv)
    if args.check and args.refresh_inputs:
        parser.error("--check compares against frozen inputs; drop --refresh-inputs")
    global FROZEN
    FROZEN = None if args.refresh_inputs else json.loads(INPUTS.read_text())
    FRESH["cases"].clear()
    FRESH["filters"].clear()
    text = render()
    doc = json.loads(text)
    failed = False
    problems = against_scipy(doc)
    if problems:
        failed = True
        print(
            f"the reference differs from scipy: {len(problems)} place(s)",
            file=sys.stderr,
        )
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
    relative = VECTORS_PATH.relative_to(ROOT)
    if args.check:
        if not VECTORS_PATH.is_file():
            print(f"{relative}: missing", file=sys.stderr)
            return 1
        committed = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        found = differences(doc, committed)
        if found:
            failed = True
            print(f"{relative}: {len(found)} difference(s)", file=sys.stderr)
            for line in found[:20]:
                print(f"  {line}", file=sys.stderr)
        else:
            print(f"{relative}: matches")
    else:
        VECTORS_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {relative} ({len(text.encode()):,} bytes)")
    if args.refresh_inputs:
        stored = {
            "description": (
                "The frozen inputs of the nemar.ic-activity.v1 vectors: each case's "
                "unmixing matrix and stored integers, and the display filter's input "
                "series, computed once by `generate_ic_activity_vectors.py "
                "--refresh-inputs`. The generator reads them, so the vectors' inputs "
                "never move with a platform's math; only the expected outputs are "
                "computed."
            ),
            **copy.deepcopy(FRESH),
        }
        INPUTS.write_text(dumps(stored) + "\n", encoding="utf-8")
        print(f"wrote {INPUTS.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
