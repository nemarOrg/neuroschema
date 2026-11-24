"""``nemar.preset-checks.v1``: the checks a renderer of a preset runs beyond its base.

``docs/views/presets.md`` is the normative text. A renderer that knows a
preset first builds its base's model; when the base draws, the preset's own
checks run, in the stated order, and the first that fails gives the word:

- ``nemar.ic-maps``: the components table's ``component`` cells are the
  values' component names, in order (``components_mismatch``);
- ``nemar.ic-classes``: the content meets ``content.nemar.ic-classes.v1``
  (``content_invalid``), has one ``summed_variance_pct`` per category
  (``variance_length``), and counts that sum to ``n_components``
  (``components_total``);
- ``nemar.signal-window``: the store digest (``store_digest_mismatch``) and the
  window, which must hold a sample of the recording (``window_outside``).

A word of ``nemar.ic-maps`` or ``nemar.ic-classes`` draws the view by its base
and keeps the word; a word of ``nemar.signal-window`` draws nothing.
``views/vectors/preset-checks.v1.json`` holds the cases; this module is the
Python reference. ``nemar.spectrum`` has no checks of its own, and
``nemar.ic-activity``'s are its transform's (``neuroschema.views.ic_activity``).
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping

from neuroschema.views.models import (
    KindRefused,
    Refusal,
    ViewRefused,
    _Reader,
    build_model,
    content_validator,
    read_json,
)
from neuroschema.views.registry import load_registry

PRESET_CHECKS_FORMAT = "nemar.preset-checks.v1"
IC_CLASSES_CONTENT = "content.nemar.ic-classes.v1.schema.json"


class PresetRefused(Refusal):
    """A preset's own check failed. ``outcome`` is ``base`` (the view is drawn
    by its base, with the word) or ``nothing`` (nothing is drawn)."""

    def __init__(self, word: str, outcome: str, detail: str = "") -> None:
        super().__init__(word, detail)
        self.outcome = outcome


def _base_only(registry: Mapping) -> Mapping:
    """The registry as a renderer that knows the bases and not the presets."""
    return registry | {"kinds": [k for k in registry["kinds"] if k["base"] is None]}


def check_ic_maps(view: Mapping, files: Mapping[str, bytes], caps: Mapping) -> None:
    """The components table names the values' components, in order.

    The values' component names are its declared columns (each one map); the
    components table is read under the TSV grammar, and its ``component``
    column, top to bottom, must be those names. A file that breaks the grammar
    or lacks the column is refused with the generic kinds' word, and the view
    is drawn by its base.
    """
    reader = _Reader(view, files, caps)
    names = [c["name"] for c in reader.entry("values")["columns"]]
    try:
        table = reader.tsv(reader.entry("components"))
        if "component" not in table.header:
            raise KindRefused("column_missing", "component")
    except KindRefused as exc:
        raise PresetRefused(exc.word, "base", str(exc)) from exc
    if table.cells("component") != names:
        raise PresetRefused("components_mismatch", "base")


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


def check_signal_window(
    view: Mapping, samples: int, rate: float, published_sha256: str | None
) -> dict:
    """The store digest's state and the window's samples, or the refusal.

    A digest the serving copy publishes that differs from the declared one
    draws nothing (``store_digest_mismatch``); when either is absent the state
    is ``not_checked``. A window that holds no sample of the recording draws
    nothing (``window_outside``).
    """
    signal = next(i for i in view["inputs"] if i["role"] == "signal")["store"]
    declared = signal.get("content_sha256")
    if declared is None or published_sha256 is None:
        state = "not_checked"
    elif declared != published_sha256:
        raise PresetRefused("store_digest_mismatch", "nothing")
    else:
        state = "matches"
    parameters = view["parameters"]
    first, count = window_samples(
        parameters["start_s"], parameters["duration_s"], samples, rate
    )
    if count == 0:
        raise PresetRefused("window_outside", "nothing")
    return {"state": state, "first": first, "count": count}


def check_preset(
    view: Mapping,
    files: Mapping[str, bytes],
    registry: Mapping | None = None,
    store: Mapping | None = None,
) -> dict:
    """The outcome of a preset's own checks, as the vectors state it.

    ``{"word": None}`` when they pass (with the state and window of a
    ``nemar.signal-window``); ``{"word", "outcome"}`` when one fails, the
    outcome ``base`` or ``nothing``; and, for ``nemar.ic-classes`` when its base
    refuses its file first, the base's word with the outcome ``fallback``.
    ``store`` holds a signal window's ``samples``, ``rate`` and
    ``published_sha256``. A file that is not the one recorded gives the
    generic kinds' word with the outcome ``nothing``.
    """
    registry = load_registry() if registry is None else registry
    kind = view["kind"]
    try:
        if kind == "nemar.signal-window":
            return {"word": None} | check_signal_window(
                view, store["samples"], store["rate"], store["published_sha256"]
            )
        if kind == "nemar.ic-classes":
            base = build_model(view, files, _base_only(registry))
            if base["refused"] is not None:
                return {"word": base["refused"]["word"], "outcome": "fallback"}
            check_ic_classes(view, files, registry["caps"])
        elif kind == "nemar.ic-maps":
            # The base's map has its own reference and vectors
            # (neuroschema.views.sensor_field); this checks the preset's file.
            check_ic_maps(view, files, registry["caps"])
    except PresetRefused as exc:
        return {"word": exc.word, "outcome": exc.outcome}
    except ViewRefused as exc:
        return {"word": exc.word, "outcome": "nothing"}
    return {"word": None}
