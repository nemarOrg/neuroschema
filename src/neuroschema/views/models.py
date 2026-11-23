"""``nemar.kinds-models.v1``: what a renderer builds before it draws a generic kind.

``docs/views/generic-kinds.md`` is the normative text. From a view declaration
and the bytes of the files it reads, a renderer builds one model: the table of
``nemar.table``, the x axis and series of ``nemar.lines``, the cells and color
limits of ``nemar.heatmap``, the bins of ``nemar.histogram`` (all version 1),
or the table-and-download fallback. Every number in a model is a stored value
and every readout prints stored text. ``views/vectors/kinds-models.v1.json``
holds the cases every renderer reproduces; this module is the Python reference.
"""

from __future__ import annotations

import bisect
import functools
import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema
from neuroschema.views.digest import (
    CanonicalizationError,
    canonicalize,
    parse_declaration,
)
from neuroschema.views.registry import REPO_ROOT, Drawing, draw_as, load_registry

MODELS_FORMAT = "nemar.kinds-models.v1"
VIEW_SCHEMA = REPO_ROOT / "schema" / "definitions" / "view.schema.json"
HISTOGRAM_CONTENT = (
    REPO_ROOT / "schema" / "views" / "content.nemar.histogram.v1.schema.json"
)
MAX_SAFE_INTEGER = 2**53 - 1

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")


class Refusal(ValueError):
    """A refusal with a fixed word (docs/views/generic-kinds.md, Words)."""

    def __init__(self, word: str, detail: str = "") -> None:
        super().__init__(f"{word}: {detail}" if detail else word)
        self.word = word


class ViewRefused(Refusal):
    """Nothing is drawn: an invalid declaration, or a file not the one recorded."""


class KindRefused(Refusal):
    """The kind's model cannot be built from the files; the view falls back."""


# ── Reading files ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tsv:
    """A TSV file that meets the grammar: its header and its rows of text."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def cells(self, name: str) -> list[str]:
        """The text of one column, top to bottom."""
        index = self.header.index(name)
        return [row[index] for row in self.rows]


def read_tsv(data: bytes) -> Tsv:
    """Read a TSV file under the grammar of docs/views.md.

    Refuses (:class:`KindRefused`) bytes that are not UTF-8 or begin with a
    byte order mark (``tsv_encoding``), text with a CR or without a final LF
    (``tsv_line_endings``), a repeated header name (``tsv_header_repeated``)
    and a row whose cell count differs from the header's (``tsv_ragged``).
    """
    if data.startswith(b"\xef\xbb\xbf"):
        raise KindRefused("tsv_encoding", "byte order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KindRefused("tsv_encoding", str(exc)) from exc
    if "\r" in text or not text.endswith("\n"):
        raise KindRefused("tsv_line_endings")
    lines = text[:-1].split("\n")
    header = tuple(lines[0].split("\t"))
    if len(set(header)) != len(header):
        raise KindRefused("tsv_header_repeated")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = tuple(line.split("\t"))
        if len(cells) != len(header):
            raise KindRefused("tsv_ragged", f"line {number}")
        rows.append(cells)
    return Tsv(header, tuple(rows))


def cell_value(text: str, value_type: str) -> float | str:
    """The value of one cell of a column or coordinate of the given type.

    A ``number`` cell matches the JSON number grammar and is finite; an
    ``integer`` cell is a JSON integer with no fraction or exponent, at most
    2^53 - 1 in magnitude. Numbers are the nearest binary64, with negative
    zero read as zero. A ``string`` cell is its text.
    """
    if value_type == "string":
        return text
    if value_type == "integer":
        digits = text.removeprefix("-")
        if not _INTEGER.fullmatch(text) or len(digits) > 16:
            raise KindRefused("cell_not_integer", repr(text))
        if abs(int(text)) > MAX_SAFE_INTEGER:
            raise KindRefused("cell_not_integer", repr(text))
        return float(int(text)) + 0.0
    if not _NUMBER.fullmatch(text):
        raise KindRefused("cell_not_number", repr(text))
    value = float(text)
    if not math.isfinite(value):
        raise KindRefused("cell_not_finite", repr(text))
    return value + 0.0


def read_json(data: bytes) -> Any:
    """Read a JSON file under the grammar of docs/views.md (``json_invalid``).

    Strict UTF-8 with no byte order mark, no repeated member name, no ``NaN``
    or ``Infinity`` literal, and every number finite (``1e400`` is not).
    """
    try:
        value = parse_declaration(data)
    except CanonicalizationError as exc:
        raise KindRefused("json_invalid", str(exc)) from exc
    if not _all_finite(value):
        raise KindRefused("json_invalid", "a number is not finite")
    return value


def _all_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_all_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_all_finite(v) for v in value)
    return True


# ── Readouts and bins ─────────────────────────────────────────────────────


def snap_row(xs: Sequence[float], x: float) -> int:
    """The stored row a pointer at ``x`` reads: the nearest x, the lower on a tie.

    ``xs`` is strictly increasing. A pointer before the first row reads the
    first, and one after the last reads the last. Nothing is interpolated.
    """
    i = bisect.bisect_right(xs, x) - 1
    if i < 0:
        return 0
    if i >= len(xs) - 1:
        return len(xs) - 1
    return i + 1 if xs[i + 1] - x < x - xs[i] else i


def locate_bin(edges: Sequence[float], value: float) -> int:
    """The bin holding ``value``: ``[e_i, e_i+1)``, the last bin closed.

    Returns -1 below the first edge (underflow) and the number of bins above
    the last edge (overflow).
    """
    bins = len(edges) - 1
    if value < edges[0]:
        return -1
    if value > edges[-1]:
        return bins
    return min(bisect.bisect_right(edges, value) - 1, bins - 1)


def number_text(value: float) -> str:
    """A number as ECMAScript's ``String(value)`` prints it (view-digest.md)."""
    return canonicalize(value).decode("utf-8")


# ── Building a model ──────────────────────────────────────────────────────


@functools.cache
def _validator(path: str, fragment: str) -> Draft202012Validator:
    schema_path = REPO_ROOT / path
    _schema, resolver = load_schema(schema_path)
    return Draft202012Validator(
        {"$ref": f"file://{schema_path}{fragment}"}, resolver=resolver
    )


def view_validator() -> Draft202012Validator:
    """A validator for one view declaration (``view.schema.json#/$defs/view``)."""
    return _validator(str(VIEW_SCHEMA.relative_to(REPO_ROOT)), "#/$defs/view")


def histogram_content_validator() -> Draft202012Validator:
    """A validator for the content of a histogram role."""
    return _validator(str(HISTOGRAM_CONTENT.relative_to(REPO_ROOT)), "")


class _Reader:
    """The files of one view: verified once, read once, under the caps."""

    def __init__(self, view: Mapping, files: Mapping[str, bytes], caps: Mapping):
        self.view = view
        self.files = files
        self.caps = caps
        self._tsv: dict[str, Tsv] = {}

    def entry(self, role: str) -> Mapping | None:
        entries = [e for e in self.view.get("data", []) if e.get("role") == role]
        return entries[0] if len(entries) == 1 else None

    def verified(self, entry: Mapping) -> bytes:
        location = entry["location"]
        if location not in self.files:
            raise ViewRefused("file_missing", location)
        data = bytes(self.files[location])
        if len(data) != entry["size"]:
            raise ViewRefused("file_size_mismatch", location)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ViewRefused("file_digest_mismatch", location)
        if len(data) > self.caps["bytes_per_role"]:
            raise KindRefused("cap_exceeded", f"{location}: bytes")
        return data

    def tsv(self, entry: Mapping) -> Tsv:
        location = entry["location"]
        if location not in self._tsv:
            self._tsv[location] = read_tsv(self.verified(entry))
        return self._tsv[location]


def _declared(entry: Mapping, tsv: Tsv) -> list[Mapping]:
    columns = list(entry.get("columns", []))
    names = [c["name"] for c in columns]
    if len(set(names)) != len(names):
        raise KindRefused("column_repeated")
    for name in names:
        if name not in tsv.header:
            raise KindRefused("column_missing", name)
    return columns


def _match(dim: Mapping, column: Mapping) -> None:
    """A coordinate column's declared type and unit are its dimension's."""
    if column["type"] != dim["type"] or (
        "unit" in column and column["unit"] != dim.get("unit")
    ):
        raise KindRefused("coords_mismatch", dim["name"])


def _coordinate_column(dim: Mapping, declared: Sequence[Mapping]) -> Mapping:
    name = dim["coords"]["column"]
    column = next((c for c in declared if c["name"] == name), None)
    if column is None:
        raise KindRefused("coords_unresolved", f"{dim['name']}: {name}")
    _match(dim, column)
    return column


def _value_columns(columns: Sequence[Mapping]) -> str | None:
    """Check the value columns are numeric with one unit, and return the unit."""
    for column in columns:
        if column["type"] not in ("number", "integer"):
            raise KindRefused("value_type", column["name"])
    units = {column.get("unit") for column in columns}
    if len(units) > 1:
        raise KindRefused("value_units_differ")
    return next(iter(units), None)


def _check_caps(caps: Mapping, rows: int, values: int, read: int) -> None:
    per_dim = caps["entries_per_dim"]
    if rows > per_dim or values > per_dim or rows * read > caps["cells_per_role"]:
        raise KindRefused("cap_exceeded", f"{rows} rows, {values} value columns")


def _parse_column(tsv: Tsv, column: Mapping) -> tuple[list, list[str]]:
    texts = tsv.cells(column["name"])
    return [cell_value(text, column["type"]) for text in texts], texts


def _role_labels(reader: _Reader, dim: Mapping, count: int) -> list[str]:
    """Coordinates by position from a column of another role of the view."""
    role, name = dim["coords"]["role"], dim["coords"]["column"]
    other = reader.entry(role)
    if other is None or other.get("format") != "tsv":
        raise KindRefused("coords_unresolved", f"{dim['name']}: role {role}")
    column = next((c for c in other.get("columns", []) if c["name"] == name), None)
    if column is None:
        raise KindRefused("coords_unresolved", f"{dim['name']}: {role}.{name}")
    tsv = reader.tsv(other)
    if name not in tsv.header:
        raise KindRefused("column_missing", f"{role}.{name}")
    _match(dim, column)
    texts = tsv.cells(name)
    if len(texts) != count:
        raise KindRefused("coords_length", f"{dim['name']}: {len(texts)} != {count}")
    for text in texts:
        cell_value(text, dim["type"])
    return texts


def _axis(dim: Mapping) -> dict:
    return {"dim": dim["name"], "type": dim["type"], "unit": dim.get("unit")}


def _dims(entry: Mapping) -> tuple[Mapping, Mapping]:
    dims = entry["dims"]
    return (
        next(d for d in dims if d["axis"] == "rows"),
        next(d for d in dims if d["axis"] == "columns"),
    )


def _table(reader: _Reader, own: bool) -> dict:
    entry = reader.entry("table")
    tsv = reader.tsv(entry)
    declared = _declared(entry, tsv)
    if len(tsv.rows) * len(declared) > reader.caps["cells_per_role"]:
        raise KindRefused("cap_exceeded", f"{len(tsv.rows)} rows")
    for column in declared:
        _parse_column(tsv, column)
    indexes = [tsv.header.index(c["name"]) for c in declared]
    return {
        "type": "table",
        "columns": [
            {"name": c["name"], "type": c["type"], "unit": c.get("unit")}
            for c in declared
        ],
        "rows": [[row[i] for i in indexes] for row in tsv.rows],
    }


def _lines(reader: _Reader, own: bool) -> dict:
    entry = reader.entry("values")
    tsv = reader.tsv(entry)
    declared = _declared(entry, tsv)
    x_dim, series_dim = _dims(entry)
    x_column = _coordinate_column(x_dim, declared)
    value_columns = [c for c in declared if c["name"] != x_column["name"]]
    unit = _value_columns(value_columns)
    if not tsv.rows or not value_columns:
        raise KindRefused("empty")
    _check_caps(reader.caps, len(tsv.rows), len(value_columns), len(declared))
    xs, x_texts = _parse_column(tsv, x_column)
    series = [_parse_column(tsv, column) for column in value_columns]
    if any(b <= a for a, b in pairwise(xs)):
        raise KindRefused("x_not_increasing")
    if "header" in series_dim["coords"]:
        labels = [column["name"] for column in value_columns]
    else:
        labels = _role_labels(reader, series_dim, len(value_columns))
    every = [value for values, _texts in series for value in values]
    return {
        "type": "lines",
        "x": _axis(x_dim) | {"column": x_column["name"], "values": xs, "text": x_texts},
        "y": {"unit": unit, "min": min(every), "max": max(every)},
        "series": _axis(series_dim)
        | {
            "items": [
                {
                    "label": label,
                    "column": column["name"],
                    "values": values,
                    "text": texts,
                }
                for label, column, (values, texts) in zip(
                    labels, value_columns, series, strict=True
                )
            ]
        },
    }


def _heatmap(reader: _Reader, own: bool) -> dict:
    entry = reader.entry("values")
    tsv = reader.tsv(entry)
    declared = _declared(entry, tsv)
    row_dim, column_dim = _dims(entry)
    label_column = None
    if "role" not in row_dim["coords"]:
        label_column = _coordinate_column(row_dim, declared)
    value_columns = [c for c in declared if c is not label_column]
    unit = _value_columns(value_columns)
    if not tsv.rows or not value_columns:
        raise KindRefused("empty")
    _check_caps(reader.caps, len(tsv.rows), len(value_columns), len(declared))
    row_labels = None
    if label_column is not None:
        _values, row_labels = _parse_column(tsv, label_column)
    columns = [_parse_column(tsv, column) for column in value_columns]
    if row_labels is None:
        row_labels = _role_labels(reader, row_dim, len(tsv.rows))
    if "header" in column_dim["coords"]:
        column_labels = [column["name"] for column in value_columns]
    else:
        column_labels = _role_labels(reader, column_dim, len(value_columns))
    values = [list(row) for row in zip(*(v for v, _t in columns), strict=True)]
    texts = [list(row) for row in zip(*(t for _v, t in columns), strict=True)]
    parameters = reader.view.get("parameters", {}) if own else {}
    rule = parameters.get("limits", "minmax")
    every = [value for row in values for value in row]
    if rule == "absmax":
        largest = max(abs(value) for value in every)
        low, high = (-largest, largest) if largest else (0.0, 0.0)
    else:
        low, high = min(every), max(every)
    return {
        "type": "heatmap",
        "rows": _axis(row_dim) | {"labels": row_labels},
        "columns": _axis(column_dim)
        | {"labels": column_labels, "names": [c["name"] for c in value_columns]},
        "unit": unit,
        "values": values,
        "text": texts,
        "limits": {"rule": rule, "min": low, "max": high},
    }


def _histogram(reader: _Reader, own: bool) -> dict:
    entry = reader.entry("histogram")
    content = read_json(reader.verified(entry))
    if not histogram_content_validator().is_valid(content):
        raise KindRefused("content_invalid")
    counts = [int(count) for count in content["counts"]]
    if "categories" in content:
        if len(counts) != len(content["categories"]):
            raise KindRefused("counts_length")
        return {
            "type": "histogram",
            "bins": "categories",
            "unit": None,
            "items": [
                {"label": label, "count": count}
                for label, count in zip(content["categories"], counts, strict=True)
            ],
            "underflow": None,
            "overflow": None,
            "total": sum(counts),
            "max_count": max(counts),
        }
    edges = [float(edge) + 0.0 for edge in content["edges"]]
    if any(b <= a for a, b in pairwise(edges)):
        raise KindRefused("edges_not_increasing")
    if len(counts) != len(edges) - 1:
        raise KindRefused("counts_length")
    under, over = int(content["underflow"]), int(content["overflow"])
    last = len(counts) - 1
    items = []
    for i, count in enumerate(counts):
        low, high = edges[i], edges[i + 1]
        close = "]" if i == last else ")"
        items.append(
            {
                "label": f"[{number_text(low)}, {number_text(high)}{close}",
                "lower": low,
                "upper": high,
                "upper_closed": i == last,
                "count": count,
            }
        )
    return {
        "type": "histogram",
        "bins": "edges",
        "unit": content.get("unit"),
        "items": items,
        "underflow": {"label": f"< {number_text(edges[0])}", "count": under},
        "overflow": {"label": f"> {number_text(edges[-1])}", "count": over},
        "total": sum(counts) + under + over,
        "max_count": max([*counts, under, over]),
    }


def _fallback(reader: _Reader) -> dict:
    tables = []
    for entry in reader.view.get("data", []):
        if entry.get("format") != "tsv":
            continue
        try:
            tsv = reader.tsv(entry)
        except KindRefused:
            continue
        if len(tsv.rows) * len(tsv.header) > reader.caps["cells_per_role"]:
            continue
        tables.append(
            {
                "role": entry["role"],
                "location": entry["location"],
                "header": list(tsv.header),
                "rows": [list(row) for row in tsv.rows],
            }
        )
    return {"type": "fallback", "tables": tables}


def _downloads(view: Mapping) -> list[dict]:
    files = [(e["role"], e) for e in view.get("data", [])]
    files += [(i["role"], i["file"]) for i in view.get("inputs", []) if "file" in i]
    return [
        {
            "role": role,
            "location": f["location"],
            "size": f["size"],
            "sha256": f["sha256"],
        }
        for role, f in files
    ]


BUILDERS: dict[tuple[str, int], Callable[[_Reader, bool], dict]] = {
    ("nemar.table", 1): _table,
    ("nemar.lines", 1): _lines,
    ("nemar.heatmap", 1): _heatmap,
    ("nemar.histogram", 1): _histogram,
}


def build_model(
    view: Mapping,
    files: Mapping[str, bytes],
    registry: Mapping | None = None,
) -> dict:
    """Build the model a renderer draws for one view (``nemar.kinds-models.v1``).

    ``files`` maps a file's ``location`` to its bytes; only the files the
    model reads are needed. The drawing follows :func:`draw_as`. When the
    kind's model cannot be built from the files, the view falls back to the
    table-and-download model and ``refused`` names the kind and the word.
    Every view file is listed in ``downloads``, drawn or not.

    Raises :class:`ViewRefused` when the declaration is invalid or a file it
    reads is missing or differs from its recorded size or SHA-256: nothing is
    drawn. Raises ``LookupError`` for a registered kind this module has no
    model for (``nemar.sensor-field`` has its own reference).
    """
    registry = load_registry() if registry is None else registry
    if not view_validator().is_valid(view):
        raise ViewRefused("declaration_invalid")
    drawing = draw_as(view, registry)
    reader = _Reader(view, files, registry["caps"])
    refused = None
    model = None
    if drawing.via != "table":
        builder = BUILDERS.get((drawing.kind, drawing.kind_version))
        if builder is None:
            raise LookupError(
                f"no reference model for {drawing.kind} version {drawing.kind_version}"
            )
        try:
            model = builder(reader, drawing.via == "kind")
        except KindRefused as exc:
            refused = {
                "kind": drawing.kind,
                "kind_version": drawing.kind_version,
                "word": exc.word,
            }
            drawing = Drawing("table", None, None)
    if model is None:
        model = _fallback(reader)
    return {
        "drawing": drawing._asdict(),
        "refused": refused,
        "downloads": _downloads(view),
        "model": model,
    }
