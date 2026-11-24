"""``nemar.preset-checks.v1``: the checks a renderer of a preset runs beyond its base.

``docs/views/presets.md`` is the normative text. A renderer that knows a
preset first builds its base's model; when the base draws, the preset's own
checks run, in the stated order, and the first that fails gives the word:

- ``nemar.spectrum``: with a layout, the values' sensor columns are the
  layout's names, in order (``sensors_mismatch``, shown as the fallback);
- ``nemar.ic-maps``: the components table's ``component`` cells are the
  values' component names, in order (``components_mismatch``);
- ``nemar.ic-classes``: the content meets ``content.nemar.ic-classes.v1``
  (``content_invalid``), has one ``summed_variance_pct`` per category
  (``variance_length``), and counts that sum to ``n_components``
  (``components_total``);
- ``nemar.signal-window``: the floor's tables it marks (the files recorded, the
  TSV grammar and their columns), the store digest (``store_digest_mismatch``),
  each bad channel's name, a store row's label (``bad_channel_unknown``), and
  the window, which must hold a sample of the recording (``window_outside``).

A word of ``nemar.ic-maps`` or ``nemar.ic-classes`` draws the view by its base
and keeps the word, ``nemar.spectrum``'s shows the view as the fallback's
tables, and a word of ``nemar.signal-window`` draws nothing. All but the
signal window's run after their base's model, and a base that refuses the
files comes first. ``views/vectors/preset-checks.v1.json`` holds the cases;
this module is the Python reference. ``nemar.spectrum``'s scalp maps are
:func:`spectrum_maps`, drawn only when its check passes.
``nemar.ic-activity``'s checks are its transform's
(``neuroschema.views.ic_activity``).
"""

from __future__ import annotations

import bisect
import math
import posixpath
import re
from collections.abc import Mapping

from neuroschema.views.models import (
    KindRefused,
    Refusal,
    ViewRefused,
    _Reader,
    _sensor_role,
    _Sensors,
    build_model,
    cell_value,
    check_sensor_names,
    content_validator,
    declaration_valid,
    label_inputs,
    read_json,
    read_tsv,
    sensor_field_model,
    snap_row,
)
from neuroschema.views.registry import load_registry

PRESET_CHECKS_FORMAT = "nemar.preset-checks.v1"
# The note a view carries when it legitimately has no bad-segment table, so that
# drawing nothing shaded or marked is said, never silent.
NO_BAD_SEGMENT_TABLE = "no_bad_segment_table"
# The note a nemar.ic-activity carries when its bad-segment table has no row
# labeled shaded.label and the record does not say ASR repaired a span.
NO_SHADED_ROWS = "no_shaded_rows"
IC_CLASSES_CONTENT = "content.nemar.ic-classes.v1.schema.json"


class PresetRefused(Refusal):
    """A preset's own check failed. ``outcome`` is ``base`` (the view is drawn
    by its base, with the word), ``fallback`` (it shows as the fallback's
    tables, with the word) or ``nothing`` (nothing is drawn)."""

    def __init__(self, word: str, outcome: str, detail: str = "") -> None:
        super().__init__(word, detail)
        self.outcome = outcome


SEGMENT_COLUMNS = ("onset", "duration", "label")
CHANNEL_COLUMNS = ("name", "status")


def read_table(data: bytes, columns: tuple[str, ...], numbers: tuple[str, ...], caps):
    """One of the floor's tables, read as a view's data file is.

    The TSV grammar (its words), at most ``caps.cells_per_role`` cells counting
    every header column (``cap_exceeded``), each named column present, in that
    order (``column_missing``), and the cells of each ``numbers`` column, column
    by column, finite JSON numbers (``cell_not_number``, ``cell_not_finite``).
    Returns the rows as {column: text or number}. Raises ``KindRefused``.
    """
    table = read_tsv(data)
    if len(table.rows) * len(table.header) > caps["cells_per_role"]:
        raise KindRefused("cap_exceeded", f"{len(table.rows)} rows")
    for name in columns:
        if name not in table.header:
            raise KindRefused("column_missing", name)
    values = {name: table.cells(name) for name in columns}
    for name in numbers:
        values[name] = [cell_value(text, "number") for text in values[name]]
    return [
        dict(zip(columns, row, strict=True))
        for row in zip(*values.values(), strict=True)
    ]


STATUSES = ("good", "bad", "n/a")


def read_segments(data: bytes, caps) -> list[dict]:
    """The floor's ``_badsegments.tsv``: onset and duration (numbers, seconds)
    and label, one row per segment, each duration above 0
    (``duration_not_positive``): a span of no length, or a negative one, marks
    nothing, and the floor writes none."""
    rows = read_table(data, SEGMENT_COLUMNS, ("onset", "duration"), caps)
    for row in rows:
        if not row["duration"] > 0:
            raise KindRefused("duration_not_positive", repr(row["duration"]))
    return rows


def read_channels(data: bytes, caps) -> list[dict]:
    """The floor's ``_channels.tsv``: each channel's name and status, the
    status one of BIDS's ``good``, ``bad`` and ``n/a``, compared as exact
    strings (``channel_status_unknown``). A near miss (``BAD``, ``Bad``,
    ``excluded``) is refused, never read as good: the floor's decision would
    otherwise be dropped silently (probe p8)."""
    rows = read_table(data, CHANNEL_COLUMNS, (), caps)
    for row in rows:
        if row["status"] not in STATUSES:
            raise KindRefused("channel_status_unknown", repr(row["status"]))
    return rows


def check_rate(rate: float) -> None:
    """The store's sampling rate is a finite number above 0 (``rate_invalid``)."""
    if not (isinstance(rate, int | float) and math.isfinite(rate) and rate > 0):
        raise KindRefused("rate_invalid", repr(rate))


def _base_only(registry: Mapping) -> Mapping:
    """The registry as a renderer that knows the bases and not the presets."""
    return registry | {"kinds": [k for k in registry["kinds"] if k["base"] is None]}


def check_ic_maps(view: Mapping, files: Mapping[str, bytes], caps: Mapping) -> None:
    """The components table names the values' components, in order.

    The values' component names are its declared columns (each one map); the
    components table is read as a data file (the cap on bytes, the file, the
    TSV grammar, then at most ``caps.cells_per_role`` cells counting every
    header column), and its ``component`` column, top to bottom, must be those
    names. A file that breaks a rule or lacks the column is refused with the
    generic kinds' word, and the view is drawn by its base.
    """
    reader = _Reader(view, files, caps)
    names = [c["name"] for c in reader.entry("values")["columns"]]
    try:
        table = reader.tsv(reader.entry("components"))
        if len(table.rows) * len(table.header) > caps["cells_per_role"]:
            raise KindRefused("cap_exceeded", f"{len(table.rows)} rows")
        if "component" not in table.header:
            raise KindRefused("column_missing", "component")
    except KindRefused as exc:
        raise PresetRefused(exc.word, "base", str(exc)) from exc
    if table.cells("component") != names:
        raise PresetRefused("components_mismatch", "base")


def check_spectrum(view: Mapping, files: Mapping[str, bytes], caps: Mapping) -> None:
    """With a layout, the values' sensor columns are the layout's names, in
    order, compared as text (``sensors_mismatch``, by
    :func:`~neuroschema.views.models.check_sensor_names`, the definition a
    scalp map's model reads too).

    The base labels each series by the layout's name at its position, so a
    header that names other sensors (``O2``, ``O1`` where the layout says
    ``Fp1``, ``Fp2``) would draw each spectrum under another sensor's name
    (probe p16). Which of the two is right cannot be told, so the view shows as
    the fallback's tables, with the word, and no scalp map is drawn
    (:func:`spectrum_maps`).
    """
    reader = _Reader(view, files, caps)
    values = reader.entry("values")
    coords = next(d for d in values["dims"] if d["name"] == "sensor")["coords"]
    if "role" not in coords:
        return
    names = [c["name"] for c in values["columns"] if c["name"] != "freq_hz"]
    cells = reader.tsv(reader.entry(coords["role"])).cells(coords["column"])
    try:
        check_sensor_names(coords["role"], cells, names)
    except KindRefused as exc:
        raise PresetRefused(exc.word, "fallback", str(exc)) from exc


def check_ic_classes(view: Mapping, files: Mapping[str, bytes], caps: Mapping) -> None:
    """The content meets content.nemar.ic-classes.v1, with one summed variance
    per category and counts that sum to the number of components."""
    reader = _Reader(view, files, caps)
    content = read_json(reader.verified(reader.entry("histogram")))
    if not content_validator(IC_CLASSES_CONTENT).is_valid(content):
        raise PresetRefused("content_invalid", "base")
    if len(content["summed_variance_pct"]) != len(content["categories"]):
        raise PresetRefused("variance_length", "base")
    if sum(int(c) for c in content["counts"]) != content["n_components"]:
        raise PresetRefused("components_total", "base")


def window_samples(start_s: float, duration_s: float, samples: int, rate: float):
    """The samples k of the recording (0 <= k < samples) whose time k / rate,
    one binary64 division, lies in [start_s, start_s + duration_s), the end one
    binary64 sum: (first, count), count 0 when none does."""
    end = start_s + duration_s
    times = _Times(samples, rate)
    first = bisect.bisect_left(times, start_s)
    last = bisect.bisect_left(times, end)
    return first, max(last - first, 0)


class _Times:
    """k / rate for k in [0, samples), as a sequence bisect can search."""

    def __init__(self, samples: int, rate: float) -> None:
        self.samples, self.rate = samples, rate

    def __len__(self) -> int:
        return self.samples

    def __getitem__(self, k: int) -> float:
        return k / self.rate


def _file_input(view: Mapping, role: str) -> Mapping | None:
    entry = next((i for i in view["inputs"] if i["role"] == role), None)
    return None if entry is None else entry["file"]


TABLE_SUFFIXES = (("channels", "channels"), ("badsegments", "badsegments"))
_TABLE = re.compile(r"(?P<stem>.+)_(?P<suffix>[A-Za-z0-9]+)\.tsv")
_DESC = re.compile(r"desc-(?P<value>[^_]*)")


def recipe_label(view: Mapping) -> str | None:
    """The label of the recipe that wrote the view: its id without hyphens, as
    nemar-process's ``naming.label`` gives it (``nemar-ica`` is ``nemarica``),
    from the view's ``source``; None for a view a plugin wrote. The record check
    (``view_source_mismatch``) holds that recipe to the entry's."""
    recipe = view.get("source", {}).get("recipe")
    return None if recipe is None else recipe["name"].replace("-", "")


def product_stem(recording: str, label: str) -> str:
    """The stem nemar-process gives a recording's products under a recipe's
    label (``naming.product_stem``): the recording's file name without its last
    ``_<suffix>.<ext>``, with ``desc-<x>`` becoming ``desc-<x><label>`` in place
    when it has a ``desc`` entity (the first), and ``_desc-<label>`` appended
    when it has none."""
    entities = posixpath.basename(recording).rsplit("_", 1)[0]
    parts = entities.split("_")
    for position, part in enumerate(parts):
        found = _DESC.fullmatch(part)
        if found:
            parts[position] = f"desc-{found['value']}{label}"
            return "_".join(parts)
    return "_".join([*parts, f"desc-{label}"])


def table_stem(
    location: str, recording: str, label: str, suffix: str | None = None
) -> str | None:
    """The stem of a table the recipe of ``label`` wrote for the recording, or
    None.

    The table lies in the recording's directory and is named
    ``<stem>_<suffix>.tsv`` (``suffix`` when given), and the stem is exactly the
    one nemar-process gives that recording's products under the label
    (:func:`product_stem`). So a table of another recording (``_run-2``, the
    ``ingstate`` of ``task-restingstate``, ``_acq-other``, a sibling
    ``_desc-preproc``) or of another recipe (``desc-nemarfloor`` in a nemar-ica
    view) gives None.
    """
    directory = posixpath.dirname(recording)
    where, table = posixpath.split(location)
    found = _TABLE.fullmatch(table)
    if where != directory or found is None or "_" not in posixpath.basename(recording):
        return None
    if suffix is not None and found["suffix"] != suffix:
        return None
    stem = product_stem(recording, label)
    return stem if found["stem"] == stem else None


def check_table_locations(view: Mapping) -> None:
    """The floor's tables are the recording's (``table_location_mismatch``).

    Each table the view declares is named for the signal's ``recording`` under
    the label of the recipe that wrote the view (:func:`table_stem`), with its
    suffix (``_channels.tsv``, ``_badsegments.tsv``): the recipe writes both
    beside the recording, under one stem. So a view cannot mark a window with
    another recording's tables, another recipe's, or a decoy (probes p8, r29).
    A view a plugin wrote names no recipe, so its tables cannot be tied, and
    are refused.
    """
    signal = next(i for i in view["inputs"] if i["role"] == "signal")["store"]
    label = recipe_label(view)
    for role, suffix in TABLE_SUFFIXES:
        entry = _file_input(view, role)
        if entry is None:
            continue
        if label is None or not table_stem(
            entry["location"], signal["recording"], label, suffix
        ):
            raise PresetRefused("table_location_mismatch", "nothing", role)


def check_signal_window(
    view: Mapping,
    files: Mapping[str, bytes],
    labels: list[str | None],
    samples: int,
    rate: float,
    published_sha256: str | None,
    caps: Mapping,
) -> dict:
    """The store digest's state, the floor's marks and the window's samples.

    In order: the declared tables (channels, then badsegments) are the files
    recorded (the generic file words); the digest the serving copy publishes,
    when it differs from the declared one (``store_digest_mismatch``; when
    either is absent the state is ``not_checked``); the tables' grammar and
    columns (channels: name and status; badsegments: onset, duration and label,
    the first two numbers); each bad channel's name, which must be the label of
    a store row, compared as exact strings (``bad_channel_unknown``); every
    store row's label, which must name a row of the channels table
    (``channel_row_missing``: a floor decision dropped); and a window that holds
    a sample of the recording (``window_outside``). Every
    refusal draws nothing: a window with its marks missing could pass for clean
    data. With no bad segments declared, the result notes
    ``no_bad_segment_table``.
    """
    check_table_locations(view)
    reader = _Reader(view, files, caps)
    tables = {}
    for role in ("channels", "badsegments"):
        entry = _file_input(view, role)
        if entry is not None:
            try:
                tables[role] = reader.verified(entry)
            except KindRefused as exc:
                raise PresetRefused(exc.word, "nothing", str(exc)) from exc
    signal = next(i for i in view["inputs"] if i["role"] == "signal")["store"]
    declared = signal.get("content_sha256")
    if declared is None or published_sha256 is None:
        state = "not_checked"
    elif declared != published_sha256:
        raise PresetRefused("store_digest_mismatch", "nothing")
    else:
        state = "matches"
    try:
        check_rate(rate)
    except KindRefused as exc:
        raise PresetRefused(exc.word, "nothing", str(exc)) from exc
    try:
        channels = (
            read_channels(tables["channels"], caps) if "channels" in tables else []
        )
        segments = (
            read_segments(tables["badsegments"], caps)
            if "badsegments" in tables
            else []
        )
    except KindRefused as exc:
        raise PresetRefused(exc.word, "nothing", str(exc)) from exc
    bad = [row["name"] for row in channels if row["status"] == "bad"]
    for name in bad:
        if name not in labels:
            raise PresetRefused("bad_channel_unknown", "nothing", name)
    if "channels" in tables:
        named = {row["name"] for row in channels}
        for label in labels:
            if label not in named:
                # The floor writes a row for every channel; a store row with
                # none is a decision dropped, and could be a bad channel shown
                # as good (review r29).
                raise PresetRefused("channel_row_missing", "nothing", repr(label))
    parameters = view["parameters"]
    first, count = window_samples(
        parameters["start_s"], parameters["duration_s"], samples, rate
    )
    if count == 0:
        raise PresetRefused("window_outside", "nothing")
    return {
        "state": state,
        "first": first,
        "count": count,
        "bad_channels": bad,
        "segments": segments,
        "notes": [] if "badsegments" in tables else [NO_BAD_SEGMENT_TABLE],
    }


def check_preset(
    view: Mapping,
    files: Mapping[str, bytes],
    registry: Mapping | None = None,
    store: Mapping | None = None,
) -> dict:
    """The outcome of a preset's own checks, as the vectors state it.

    ``{"word": None}`` when they pass (with, for a ``nemar.signal-window``, its
    state, the window's ``first`` sample and ``count``, its ``bad_channels``,
    its ``segments`` and its ``notes``); ``{"word", "outcome"}`` when one fails, the
    outcome ``base`` or ``nothing``; and, for ``nemar.ic-maps`` and
    ``nemar.ic-classes`` when the base's model refuses the files first, the
    base's word with the outcome ``fallback``.
    ``store`` holds a signal window's store ``labels``, ``samples``, ``rate``
    and ``published_sha256``. A file that is not the one recorded gives the
    generic kinds' word with the outcome ``nothing``.
    """
    registry = load_registry() if registry is None else registry
    kind = view["kind"]
    try:
        if not declaration_valid(view):
            raise PresetRefused("declaration_invalid", "nothing")
        if kind == "nemar.signal-window":
            return {"word": None} | check_signal_window(
                view,
                files,
                store["labels"],
                store["samples"],
                store["rate"],
                store["published_sha256"],
                registry["caps"],
            )
        if kind in ("nemar.ic-classes", "nemar.spectrum"):
            base = build_model(view, files, _base_only(registry))
            if base["refused"] is not None:
                return {"word": base["refused"]["word"], "outcome": "fallback"}
            if kind == "nemar.spectrum":
                check_spectrum(view, files, registry["caps"])
            else:
                check_ic_classes(view, files, registry["caps"])
        elif kind == "nemar.ic-maps":
            base = build_model(view, files, _base_only(registry))
            if base["refused"] is not None:
                return {"word": base["refused"]["word"], "outcome": "fallback"}
            check_ic_maps(view, files, registry["caps"])
    except PresetRefused as exc:
        return {"word": exc.word, "outcome": exc.outcome}
    except ViewRefused as exc:
        return {"word": exc.word, "outcome": "nothing"}
    return {"word": None}


def spectrum_maps(
    view: Mapping,
    files: Mapping[str, bytes],
    frequencies: list[float],
    registry: Mapping | None = None,
) -> dict | None:
    """The scalp maps a renderer that knows ``nemar.spectrum`` draws below its
    lines, one at each of ``frequencies`` (presets.md).

    None when the view is not drawn by its lines: the base, ``nemar.lines``,
    refuses the files or draws them as tables, or the preset's own check
    (:func:`check_spectrum`) finds the layout's names are not the sensor
    columns (``sensors_mismatch``, the outcome ``fallback`` of
    :func:`check_preset`): there are no lines and no maps. Otherwise
    ``rows`` are the stored rows the frequencies snap to, by the lines'
    readout rule, and ``model`` is the
    ``nemar.sensor-field`` model of those rows' cells, one map per row labeled
    by its frequency's stored text, with ``minmax`` limits, the sensors placed
    by the layout or, without one, by their names. When the layout breaks a
    rule of the files that only the maps read (a place column), ``refused``
    is the word, shown in every map's place while the lines are drawn, and
    ``model`` is None.

    Raises :class:`ViewRefused`, as :func:`build_model` does, when a file the
    lines or the maps read is missing or is not the one recorded: nothing is
    drawn, neither the lines nor the maps.
    """
    registry = load_registry() if registry is None else registry
    base = build_model(view, files, _base_only(registry))
    if base["refused"] is not None or base["drawing"]["via"] == "table":
        return None
    try:
        check_spectrum(view, files, registry["caps"])
    except PresetRefused:
        return None
    lines = base["model"]
    rows = [snap_row(lines["x"]["values"], hz) for hz in frequencies]
    reader = _Reader(view, files, registry["caps"])
    entry = reader.entry("values")
    sensor_dim = next(d for d in entry["dims"] if d["name"] == "sensor")
    freq_dim = next(d for d in entry["dims"] if d is not sensor_dim)
    series = lines["series"]["items"]
    try:
        if "role" in sensor_dim["coords"]:
            columns = [item["column"] for item in series]
            sensors = _sensor_role(reader, sensor_dim, len(series), columns)
        else:
            sensors = _Sensors([item["label"] for item in series])
    except KindRefused as exc:
        return {"rows": rows, "refused": exc.word, "model": None}
    maps = [
        (
            lines["x"]["text"][row],
            [item["values"][row] for item in series],
            [item["text"][row] for item in series],
        )
        for row in rows
    ]
    inputs = label_inputs(sensors, entry)
    model = sensor_field_model(
        sensors, maps, "minmax", lines["y"]["unit"], sensor_dim, freq_dim, inputs
    )
    return {"rows": rows, "refused": None, "model": model}
