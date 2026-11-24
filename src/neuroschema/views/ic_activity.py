"""``nemar.ic-activity.v1`` and the display filter of the kind ``nemar.ic-activity``.

``docs/views/ic-activity.md`` is the normative text. The transform is one plain
multiply: the browser's unmixing matrix (``_servingunmixing.tsv``, with the
average reference and the store unit's factor to microvolts folded in) times
the serving copy's physical values of the decomposition's channels, with no
preprocessing. The kind then draws each component's activations through a
zero-phase high-pass that is for display only: a Butterworth of order 2, run
forward and backward from its steady state over the window and up to a second
of real context on each side (:func:`context`), with an odd extension of at
most 9 samples only at the recording's own ends.

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
from types import MappingProxyType

import numpy as np

from neuroschema.views.digest import canonicalize
from neuroschema.views.models import (
    Refusal,
    Tsv,
    cell_value,
    declaration_valid,
    read_tsv,
)
from neuroschema.views.presets import (
    NO_BAD_SEGMENT_TABLE,
    NO_SHADED_ROWS,
    read_segments,
    table_stem,
)
from neuroschema.views.presets import check_rate as _check_rate
from neuroschema.views.registry import load_registry

IC_ACTIVITY = "nemar.ic-activity.v1"
ORDER = 2
# scipy's filtfilt pads by 3 * max(len(a), len(b)): 9 samples for order 2.
PADDING = 3 * (ORDER + 1)
SQRT2 = math.sqrt(2.0)
# The factor to microvolts of each unit a store or a matrix may state. Microvolts
# are spelled three ways: ASCII u, the micro sign U+00B5 and the Greek small
# letter mu U+03BC (eegprep-lean's microvolts_per accepts the same five).
MICROVOLTS_PER = {"V": 1e6, "mV": 1e3, "uV": 1.0, "µV": 1.0, "μV": 1.0}
# The registry's caps, read from views/registry.json: one copy, never two.
CAPS = MappingProxyType(dict(load_registry()["caps"]))


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
    components by samples. ``shaded`` lists, in file order, the bad segments
    whose label is the transform's ``shaded.label``, as ``{onset, duration}``
    in seconds: the spans a renderer shades. ``notes`` holds
    ``no_bad_segment_table`` when the view declares no bad segments, and
    ``no_shaded_rows`` when its table has no row labeled ``shaded.label``, each
    shown with its sentence (presets.md, Notes and states).
    """

    state: str
    components: list[str]
    channels: list[str]
    rows: list[int]
    factors: list[float]
    time_s: np.ndarray
    activations: np.ndarray
    filtered: np.ndarray
    shaded: list[dict]
    notes: list[str]


# ── The checks, in the specification's order ──────────────────────────────


def _input(view: Mapping, role: str) -> Mapping:
    return next(i for i in view["inputs"] if i["role"] == role)


KIND = ("nemar.ic-activity", 1)


def check_declaration(view: Mapping) -> None:
    """The view is one this reference draws, and valid.

    Its kind is ``nemar.ic-activity`` version 1 (``kind_unsupported``): the
    display filter and the window are that kind's, so a view of another kind
    that names the transform is drawn by the renderer rule, never by this
    function (review r29). Then the declaration is valid
    (``declaration_invalid``): it has a digest and meets the envelope, which
    applies the kind's schema and the transform's to it. Among the transform's
    rules: the view declares ``badsegments`` exactly when ``shaded.files`` is
    not null, and carries the parameters the computation reads."""
    if (view.get("kind"), view.get("kind_version")) != KIND:
        raise IcActivityRefusal("kind_unsupported", repr(view.get("kind")))
    if not declaration_valid(view):
        raise IcActivityRefusal("declaration_invalid")


def check_locations(view: Mapping) -> None:
    """Each file input is at the location the record names for it
    (``table_location_mismatch``): the ``unmixing`` input at the transform's
    ``matrix``, and the ``badsegments`` input, when declared, at
    ``shaded.files[0]``; then the three tables are the recording's, beside it
    under one stem (``presets.table_stem``). So a view cannot read one table and
    name another, such as a decoy table with no rows in place of the floor's, or
    another recording's (probes p7, r29)."""
    transform = view["transform"]["parameters"]
    if _input(view, "unmixing")["file"]["location"] != transform["matrix"]:
        raise IcActivityRefusal("table_location_mismatch", "unmixing is not matrix")
    segments = next(
        (i["file"] for i in view["inputs"] if i["role"] == "badsegments"), None
    )
    if segments is not None and segments["location"] != transform["shaded"]["files"][0]:
        raise IcActivityRefusal(
            "table_location_mismatch", "badsegments is not shaded.files[0]"
        )
    recording = _input(view, "signal")["store"]["recording"]
    stems = set()
    for role in ("unmixing", "components", "badsegments"):
        given = next((i["file"] for i in view["inputs"] if i["role"] == role), None)
        if given is None:
            continue
        stem = table_stem(given["location"], recording)
        if stem is None:
            raise IcActivityRefusal(
                "table_location_mismatch", f"{role}: not the recording's"
            )
        stems.add(stem)
    if len(stems) > 1:
        raise IcActivityRefusal("table_location_mismatch", "two stems")


def check_store(view: Mapping) -> None:
    """For a decomposition of the serving copy, ``decomposition_input.store``
    names the ``signal`` store (``store_mismatch``): the same path (the store's
    ``path``, or its ``recording`` when it has none), group and digest. So the
    view's state, ``matches`` or ``not_checked``, is about the store the
    decomposition read (probe p7)."""
    given = view["parameters"]["decomposition_input"].get("store")
    if given is None:
        return
    signal = _input(view, "signal")["store"]
    read = (signal.get("path", signal["recording"]), signal["group"])
    if (given["path"], given["group"]) != read:
        raise IcActivityRefusal("store_mismatch", "path or group")
    if given["content_sha256"] != signal["content_sha256"]:
        raise IcActivityRefusal("store_mismatch", "content_sha256")


def verified(entry: Mapping, files: Mapping[str, bytes], caps: Mapping) -> bytes:
    """A file input's bytes: its declared size within the cap on bytes, checked
    before the file is fetched, then its presence, size and SHA-256."""
    location = entry["location"]
    if entry["size"] > caps["bytes_per_role"]:
        raise IcActivityRefusal("cap_exceeded", f"{location}: {entry['size']} bytes")
    if location not in files:
        raise IcActivityRefusal("file_missing", location)
    data = bytes(files[location])
    if len(data) != entry["size"]:
        raise IcActivityRefusal("file_size_mismatch", location)
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise IcActivityRefusal("file_digest_mismatch", location)
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


def read_shading(data: bytes, label: str, caps: Mapping = CAPS) -> list[dict]:
    """The bad segments a view shades: the rows of the floor's table whose label
    is ``label``, as {onset, duration}, after the table is read as a data file
    (the TSV grammar, the columns onset, duration and label, numbers)."""
    try:
        rows = read_segments(data, caps)
    except Refusal as exc:
        raise IcActivityRefusal(exc.word, str(exc)) from exc
    return [
        {"onset": row["onset"], "duration": row["duration"]}
        for row in rows
        if row["label"] == label
    ]


def check_shaded(
    shaded: Sequence[Mapping] | None, label: str, bursts_repaired: bool | None
) -> list[str]:
    """The notes for the spans a view shades: ``shaded`` holds the rows labeled
    ``label``, or is None when the view declares no bad-segment table.

    When the record says ASR repaired at least one span of the decomposition's
    input (``bursts_repaired`` true), a table with no row of that label cannot
    be the right one, or its labels are misspelled (``Burst``, ``BURST``), and
    no table at all contradicts the record: ``label_unmatched`` refuses the
    view, never drawn with the bursts unshaded (probe p7, review r29).
    Otherwise, false or unknown, the view is drawn with nothing shaded, and the
    note ``no_bad_segment_table`` or ``no_shaded_rows`` says so.
    """
    if shaded:
        return []
    if bursts_repaired:
        found = "no bad-segment table" if shaded is None else "no row"
        raise IcActivityRefusal("label_unmatched", f"{found} labeled {label!r}")
    return [NO_BAD_SEGMENT_TABLE] if shaded is None else [NO_SHADED_ROWS]


def match_rows(
    header: Sequence[str],
    labels: Sequence[str | None],
    match: str,
    rows: Sequence[int] | None = None,
    columns: Sequence[str] | None = None,
) -> list[int]:
    """The store row of each column of the matrix, or ``channel_set_mismatch``.

    The matrix's header must be ``columns``, the record's list of them, when
    given. ``store_row``: column j is store row ``rows[j]``, whose label must
    equal the column's. ``label``: column j is the one store row whose label
    equals the column's; none, or two, refuse. Labels compare as exact strings.
    """
    if columns is not None and list(columns) != list(header):
        raise IcActivityRefusal("channel_set_mismatch", "header is not columns")
    if match == "store_row":
        if rows is None or len(rows) != len(header):
            raise IcActivityRefusal("channel_set_mismatch", "rows and columns differ")
        # A row is the integer its binary64 value is: JSON's 0.0 and 0 are one
        # number (JavaScript reads both as 0), and the schema admits only
        # integers, so 0.0 is row 0 in every reader.
        rows = [int(row) for row in rows]
        for column, row in zip(header, rows, strict=True):
            if not 0 <= row < len(labels) or labels[row] != column:
                raise IcActivityRefusal("channel_set_mismatch", f"{column} at {row}")
        return rows
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


def channel_types_sha256(channel_types: Sequence[Sequence[str | None]]) -> str:
    """The digest ``decomposition_input.channel_types_sha256`` states: SHA-256 of
    the RFC 8785 canonical JSON of ``{"channel_types": [...]}``, as UTF-8, the
    canonicalization of ``nemar.view-digest.v1`` (no ASCII escaping, no final
    line feed), so a renderer in any language can verify it."""
    document = {"channel_types": [list(row) for row in channel_types]}
    return hashlib.sha256(canonicalize(document)).hexdigest()


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


def display_filter(
    series: np.ndarray,
    rate: float,
    cutoff_hz: float,
    pad_start: bool = True,
    pad_end: bool = True,
) -> np.ndarray:
    """Each row of ``series`` through the zero-phase high-pass over its own samples.

    The rows are extended by p = min(9, n - 1) samples, the odd extension, at
    each end the flags name: ``2 x[0] - x[p], ..., 2 x[0] - x[1]`` before, and
    ``2 x[n-1] - x[n-2], ..., 2 x[n-1] - x[n-1-p]`` after. They are filtered
    forward from the state (-b0, b2) times the first extended sample,
    reversed, filtered again from that state times the first reversed sample,
    reversed back, and cut to the series. With both flags this is scipy's
    ``filtfilt(b, a, x, padtype="odd", padlen=p)``; an end without padding is
    one where :func:`context` gave the stretch real samples instead.
    """
    b, a = highpass_coefficients(cutoff_hz, rate)
    x = np.asarray(series, dtype=np.float64)
    count = x.shape[-1]
    if count < 1:
        raise ValueError("a window has at least one sample")
    p = padding(count)
    head = p if pad_start else 0
    if p and pad_start:
        x = np.concatenate([2.0 * x[..., :1] - x[..., p:0:-1], x], axis=-1)
    if p and pad_end:
        x = np.concatenate([x, 2.0 * x[..., -1:] - x[..., -2 : -(p + 2) : -1]], axis=-1)
    zi = (-b[0], b[2])
    forward = _lfilter(b, a, x, zi[0] * x[..., 0], zi[1] * x[..., 0])
    back = forward[..., ::-1]
    back = _lfilter(b, a, back, zi[0] * back[..., 0], zi[1] * back[..., 0])
    return back[..., ::-1][..., head : head + count]


CONTEXT_S = 1.0


def context(start: int, count: int, samples: int, rate: float) -> tuple[int, int]:
    """The samples of real context read on each side of a window, and filtered
    with it: c = ceil(rate), the fewest that span one second, or as many as the
    recording holds before the window and after it."""
    c = math.ceil(CONTEXT_S * rate)
    return min(c, start), min(c, samples - (start + count))


# ── The whole view ────────────────────────────────────────────────────────


def max_samples(max_window_s: float, rate: float) -> int:
    """The most samples one window holds: floor(max_window_s * rate)."""
    return math.floor(max_window_s * rate)


def check_rate(rate: float) -> None:
    """The store's sampling rate is a finite number above 0 (``rate_invalid``)."""
    try:
        _check_rate(rate)
    except Refusal as exc:
        raise IcActivityRefusal(exc.word, str(exc)) from exc


def check_window(start: int, count: int, samples: int, max_window_s, rate) -> None:
    """The window [start, start + count) holds at least one sample and lies in
    the recording (``window_outside_store``), and holds at most
    floor(max_window_s * rate) samples (``window_too_long``)."""
    if not (count >= 1 and start >= 0 and start + count <= samples):
        raise IcActivityRefusal(
            "window_outside_store", f"[{start}, {start + count}) of {samples}"
        )
    if count > max_samples(max_window_s, rate):
        raise IcActivityRefusal("window_too_long", f"{count} samples")


def ic_activity(
    view: Mapping,
    files: Mapping[str, bytes],
    store: Store,
    start: int,
    count: int,
    caps: Mapping = CAPS,
    bursts_repaired: bool | None = None,
) -> Activations:
    """The activations of a ``nemar.ic-activity`` view over samples
    [start, start + count) of its store, filtered for display.

    Runs the checks in the specification's order and raises
    :class:`IcActivityRefusal` with the word of the first that fails: the
    declaration (valid under the envelope and the transform's schema, whatever
    its kind), the inputs' locations against the record's names for them, the
    decomposition's store against the signal store, the files (unmixing,
    components, then badsegments when declared), the store digest, the
    matrix, the components table, the bad segments table, the channel match,
    the units, then the filter. A fault in the bad segments refuses the whole
    view: unshaded artifact spans could pass for brain signal. The window must
    lie in the recording and hold at most ``max_window_s`` of it.

    ``bursts_repaired`` is whether the record says ASR repaired at least one
    span of the decomposition's input (for nemar-ica, its recipe entry's metric
    ``asrBurstFraction`` above 0), or None when the renderer does not know: with
    it true, a bad-segment table with no row labeled ``shaded.label`` refuses
    the view (``label_unmatched``); otherwise it draws with ``no_shaded_rows``.
    """

    check_declaration(view)
    check_locations(view)
    check_store(view)
    parameters = view["parameters"]
    transform = view["transform"]["parameters"]
    unmixing_entry = _input(view, "unmixing")["file"]
    components_entry = _input(view, "components")["file"]
    signal = _input(view, "signal")["store"]
    segments_entry = next(
        (i["file"] for i in view["inputs"] if i["role"] == "badsegments"), None
    )
    unmixing_bytes = verified(unmixing_entry, files, caps)
    components_bytes = verified(components_entry, files, caps)
    segments_bytes = (
        None if segments_entry is None else verified(segments_entry, files, caps)
    )
    state = store_check(signal.get("content_sha256"), store.published_sha256)
    check_rate(store.rate)
    check_window(
        start, count, store.digital.shape[-1], parameters["max_window_s"], store.rate
    )
    header, weights = read_unmixing(unmixing_bytes, caps)
    labels = read_components(components_bytes, weights.shape[0], caps)
    label = transform["shaded"]["label"]
    shaded = (
        None if segments_bytes is None else read_shading(segments_bytes, label, caps)
    )
    notes = check_shaded(shaded, label, bursts_repaired)
    shaded = shaded or []
    rows = match_rows(
        header,
        store.labels,
        transform["match"],
        transform.get("rows"),
        transform.get("columns"),
    )
    factors = unit_factors(store.units, rows, transform["unit"])
    cutoff = parameters["display_filter"]["highpass_hz"]
    highpass_coefficients(cutoff, store.rate)  # refuses before any multiply
    samples = store.digital.shape[-1]
    before, after = context(start, count, samples, store.rate)
    first = start - before
    stretch = multiply(weights, store, rows, factors, first, before + count + after)
    filtered = display_filter(
        stretch,
        store.rate,
        cutoff,
        pad_start=first == 0,
        pad_end=start + count + after == samples,
    )
    return Activations(
        state=state,
        components=labels,
        channels=header,
        rows=rows,
        factors=factors,
        time_s=(start + np.arange(count, dtype=np.float64)) / store.rate,
        activations=stretch[:, before : before + count],
        filtered=filtered[:, before : before + count],
        shaded=shaded,
        notes=notes,
    )
