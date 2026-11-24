"""``nemar.ic-activity.v1`` and the display filter of the kind ``nemar.ic-activity``.

``docs/views/ic-activity.md`` is the normative text. The transform is one plain
multiply: the browser's unmixing matrix (``_servingunmixing.tsv``, with the
average reference and the store unit's factor to microvolts folded in) times
the serving copy's physical values of the decomposition's channels, with no
preprocessing. The kind then draws each component's activations through a
zero-phase high-pass that is for display only: a Butterworth of order 2, run
forward and backward over an odd extension of at most 9 samples, from the
steady state of its first sample.

The arithmetic follows the specification's order (binary64, each operation
rounded, no fused multiply-add), so the result does not depend on a linear
algebra library. ``views/vectors/ic-activity.v1.json`` holds the cases every
renderer reproduces; ``scripts/generate_ic_activity_vectors.py`` writes them
from this module and checks it against scipy's ``filtfilt``. Needs numpy, the
optional extra ``views``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from neuroschema.views.models import Refusal, Tsv, cell_value, read_tsv

IC_ACTIVITY = "nemar.ic-activity.v1"
ORDER = 2
# scipy's filtfilt pads by 3 * max(len(a), len(b)): 9 samples for order 2.
PADDING = 3 * (ORDER + 1)
SQRT2 = math.sqrt(2.0)
# The factor to microvolts of each unit a store or a matrix may state. Microvolts
# are spelled three ways: ASCII u, the micro sign U+00B5 and the Greek small
# letter mu U+03BC (eegprep-lean's microvolts_per accepts the same five).
MICROVOLTS_PER = {"V": 1e6, "mV": 1e3, "uV": 1.0, "µV": 1.0, "μV": 1.0}
CAPS = {"bytes_per_role": 4194304, "entries_per_dim": 1024, "cells_per_role": 262144}


class IcActivityRefusal(Refusal):
    """The activations cannot be drawn; ``word`` says why (ic-activity.md, Words)."""


@dataclass(frozen=True)
class Store:
    """One channel group of a recording's store in the serving copy.

    ``labels`` and ``units`` hold one entry per store row (``None`` where the
    store states none), ``scale`` and ``offset`` one number per row, and
    ``digital`` the stored integers, rows by samples. ``published_sha256`` is
    the group's ``nemar.store-content.v1`` digest as the serving copy publishes
    it, or ``None`` when it publishes none.
    """

    labels: Sequence[str | None]
    units: Sequence[str | None]
    scale: Sequence[float]
    offset: Sequence[float]
    digital: np.ndarray
    rate: float
    published_sha256: str | None = None


@dataclass(frozen=True)
class Activations:
    """What the transform and the display filter give for one window.

    ``state`` is ``matches`` (the serving copy publishes the digest the view
    declares) or ``not_checked`` (either digest is absent). ``rows`` is the
    store row of each column of the matrix and ``factors`` the factor each
    column's values were multiplied by. ``activations`` and ``filtered`` are
    components by samples.
    """

    state: str
    components: list[str]
    channels: list[str]
    rows: list[int]
    factors: list[float]
    time_s: np.ndarray
    activations: np.ndarray
    filtered: np.ndarray


# ── The checks, in the specification's order ──────────────────────────────


def _input(view: Mapping, role: str) -> Mapping:
    return next(i for i in view["inputs"] if i["role"] == role)


def verified(entry: Mapping, files: Mapping[str, bytes], caps: Mapping) -> bytes:
    """A file input's bytes, checked against its declared size and SHA-256."""
    location = entry["location"]
    if location not in files:
        raise IcActivityRefusal("file_missing", location)
    data = bytes(files[location])
    if len(data) != entry["size"]:
        raise IcActivityRefusal("file_size_mismatch", location)
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise IcActivityRefusal("file_digest_mismatch", location)
    if len(data) > caps["bytes_per_role"]:
        raise IcActivityRefusal("cap_exceeded", f"{location}: bytes")
    return data


def store_check(declared: str | None, published: str | None) -> str:
    """``matches``, ``not_checked``, or the refusal ``store_digest_mismatch``.

    The view declares the digest the run recorded (``None`` for a run that read
    the archive); the serving copy may publish one. Only two digests that are
    both present and differ refuse the view.
    """
    if declared is None or published is None:
        return "not_checked"
    if declared != published:
        raise IcActivityRefusal("store_digest_mismatch")
    return "matches"


def _tsv(data: bytes) -> Tsv:
    try:
        return read_tsv(data)
    except Refusal as exc:
        raise IcActivityRefusal(exc.word, str(exc)) from exc


def read_unmixing(data: bytes, caps: Mapping = CAPS) -> tuple[list[str], np.ndarray]:
    """The matrix's channel labels (its header) and its values, components by
    channels; every cell a finite JSON number."""
    tsv = _tsv(data)
    columns, rows = len(tsv.header), len(tsv.rows)
    if not rows:
        raise IcActivityRefusal("empty")
    per_dim = caps["entries_per_dim"]
    if rows > per_dim or columns > per_dim or rows * columns > caps["cells_per_role"]:
        raise IcActivityRefusal("cap_exceeded", f"{rows} rows, {columns} columns")
    values = np.empty((rows, columns), dtype=np.float64)
    for j, name in enumerate(tsv.header):
        try:
            values[:, j] = [cell_value(text, "number") for text in tsv.cells(name)]
        except Refusal as exc:
            raise IcActivityRefusal(exc.word, f"{name}: {exc}") from exc
    return list(tsv.header), values


def read_components(data: bytes, count: int, caps: Mapping = CAPS) -> list[str]:
    """The component labels: the column ``component``, one row per matrix row."""
    tsv = _tsv(data)
    if len(tsv.rows) * len(tsv.header) > caps["cells_per_role"]:
        raise IcActivityRefusal("cap_exceeded", f"{len(tsv.rows)} rows")
    if "component" not in tsv.header:
        raise IcActivityRefusal("column_missing", "component")
    labels = tsv.cells("component")
    if len(labels) != count:
        raise IcActivityRefusal("coords_length", f"{len(labels)} != {count}")
    return labels


def match_rows(
    header: Sequence[str],
    labels: Sequence[str | None],
    match: str,
    rows: Sequence[int] | None = None,
) -> list[int]:
    """The store row of each column of the matrix, or ``channel_set_mismatch``.

    ``store_row``: column j is store row ``rows[j]``, whose label must equal the
    column's. ``label``: column j is the one store row whose label equals the
    column's; none, or two, refuse. Labels compare as exact strings.
    """
    if match == "store_row":
        if rows is None or len(rows) != len(header):
            raise IcActivityRefusal("channel_set_mismatch", "rows and columns differ")
        for column, row in zip(header, rows, strict=True):
            if not 0 <= row < len(labels) or labels[row] != column:
                raise IcActivityRefusal("channel_set_mismatch", f"{column} at {row}")
        return list(rows)
    found = []
    for column in header:
        at = [row for row, label in enumerate(labels) if label == column]
        if len(at) != 1:
            raise IcActivityRefusal("channel_set_mismatch", f"{column}: {len(at)}")
        found.append(at[0])
    return found


def unit_factors(
    units: Sequence[str | None], rows: Sequence[int], unit: str
) -> list[float]:
    """Each column's factor from its store row's unit to the matrix's unit."""
    if unit not in MICROVOLTS_PER:
        raise IcActivityRefusal("unit_unknown", repr(unit))
    factors = []
    for row in rows:
        if units[row] not in MICROVOLTS_PER:
            raise IcActivityRefusal("unit_unknown", f"row {row}: {units[row]!r}")
        factors.append(MICROVOLTS_PER[units[row]] / MICROVOLTS_PER[unit])
    return factors


# ── The multiply ──────────────────────────────────────────────────────────


def physical(store: Store, row: int, start: int, count: int) -> np.ndarray:
    """``digital * scale + offset``, two roundings (nemar.store-content.v1)."""
    digital = np.asarray(store.digital[row, start : start + count], dtype=np.float64)
    return digital * float(store.scale[row]) + float(store.offset[row])


def multiply(
    unmixing: np.ndarray,
    store: Store,
    rows: Sequence[int],
    factors: Sequence[float],
    start: int,
    count: int,
) -> np.ndarray:
    """A = W x, summed over the columns in order, each product and sum rounded.

    Column j's values are its store row's physical values times its factor.
    The sum starts from column 0's product and adds the columns in order, so
    the result is the specification's to the last bit (numpy rounds each
    elementwise operation and fuses none).
    """
    total = None
    for j, (row, factor) in enumerate(zip(rows, factors, strict=True)):
        values = physical(store, row, start, count) * factor
        term = unmixing[:, j : j + 1] * values[np.newaxis, :]
        total = term if total is None else total + term
    return total


# ── The display filter ────────────────────────────────────────────────────


def highpass_coefficients(
    cutoff_hz: float, rate: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The Butterworth high-pass of order 2 by the bilinear transform with a
    prewarped cutoff: (b0, b1, b2) and (1, a1, a2), in the stated order of
    operations. Refuses a cutoff that is not between 0 and half the rate."""
    if not 0 < cutoff_hz < rate / 2:
        raise IcActivityRefusal("filter_out_of_range", f"{cutoff_hz} Hz at {rate} Hz")
    k = math.tan(math.pi * cutoff_hz / rate)
    kk = k * k
    sk = SQRT2 * k
    norm = 1.0 / (1.0 + sk + kk)
    return (norm, -2.0 * norm, norm), (
        1.0,
        2.0 * (kk - 1.0) * norm,
        (1.0 - sk + kk) * norm,
    )


def _lfilter(b, a, x: np.ndarray, z0: np.ndarray, z1: np.ndarray) -> np.ndarray:
    """Direct form II transposed along the last axis, from the state (z0, z1),
    in scipy's order: y = z0 + b0 x; z0 = (z1 + b1 x) - a1 y; z1 = b2 x - a2 y."""
    out = np.empty_like(x)
    for k in range(x.shape[-1]):
        xk = x[..., k]
        yk = z0 + b[0] * xk
        z0 = (z1 + xk * b[1]) - yk * a[1]
        z1 = xk * b[2] - yk * a[2]
        out[..., k] = yk
    return out


def padding(count: int) -> int:
    """The odd extension's length: 9 samples, or one fewer than the window."""
    return min(PADDING, count - 1)


def display_filter(series: np.ndarray, rate: float, cutoff_hz: float) -> np.ndarray:
    """Each row of ``series`` through the zero-phase high-pass over its own samples.

    The rows are extended at each end by p = min(9, n - 1) samples, the odd
    extension (2 x[0] - x[p], ..., 2 x[0] - x[1] before, and
    2 x[n-1] - x[n-2], ..., 2 x[n-1] - x[n-1-p] after), filtered forward from
    the state (-b0, b2) times the first extended sample, reversed, filtered
    again from that state times the first reversed sample, reversed back, and
    cut to the window.
    """
    b, a = highpass_coefficients(cutoff_hz, rate)
    x = np.asarray(series, dtype=np.float64)
    count = x.shape[-1]
    if count < 1:
        raise ValueError("a window has at least one sample")
    p = padding(count)
    if p:
        before = 2.0 * x[..., :1] - x[..., p:0:-1]
        after = 2.0 * x[..., -1:] - x[..., -2 : -(p + 2) : -1]
        x = np.concatenate([before, x, after], axis=-1)
    zi = (-b[0], b[2])
    forward = _lfilter(b, a, x, zi[0] * x[..., 0], zi[1] * x[..., 0])
    back = forward[..., ::-1]
    back = _lfilter(b, a, back, zi[0] * back[..., 0], zi[1] * back[..., 0])
    return back[..., ::-1][..., p : p + count]


# ── The whole view ────────────────────────────────────────────────────────


def max_samples(max_window_s: float, rate: float) -> int:
    """The most samples one window holds: floor(max_window_s * rate)."""
    return math.floor(max_window_s * rate)


def ic_activity(
    view: Mapping,
    files: Mapping[str, bytes],
    store: Store,
    start: int,
    count: int,
    caps: Mapping = CAPS,
) -> Activations:
    """The activations of a ``nemar.ic-activity`` view over samples
    [start, start + count) of its store, filtered for display.

    Runs the checks in the specification's order and raises
    :class:`IcActivityRefusal` with the word of the first that fails: the two
    files (unmixing, then components), the store digest, the matrix, the
    components table, the channel match, the units, then the filter. The
    window must lie in the recording and hold at most ``max_window_s`` of it.
    """
    parameters = view["parameters"]
    transform = view["transform"]["parameters"]
    unmixing_entry = _input(view, "unmixing")["file"]
    components_entry = _input(view, "components")["file"]
    signal = _input(view, "signal")["store"]
    if not (
        count >= 1
        and start >= 0
        and start + count <= store.digital.shape[-1]
        and count <= max_samples(parameters["max_window_s"], store.rate)
    ):
        raise ValueError(f"window [{start}, {start + count}) is not one to compute")
    unmixing_bytes = verified(unmixing_entry, files, caps)
    components_bytes = verified(components_entry, files, caps)
    state = store_check(signal.get("content_sha256"), store.published_sha256)
    header, weights = read_unmixing(unmixing_bytes, caps)
    labels = read_components(components_bytes, weights.shape[0], caps)
    rows = match_rows(header, store.labels, transform["match"], transform.get("rows"))
    factors = unit_factors(store.units, rows, transform["unit"])
    cutoff = parameters["display_filter"]["highpass_hz"]
    highpass_coefficients(cutoff, store.rate)  # refuses before any multiply
    raw = multiply(weights, store, rows, factors, start, count)
    return Activations(
        state=state,
        components=labels,
        channels=header,
        rows=rows,
        factors=factors,
        time_s=(start + np.arange(count, dtype=np.float64)) / store.rate,
        activations=raw,
        filtered=display_filter(raw, store.rate, cutoff),
    )
