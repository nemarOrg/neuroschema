"""The presets' own checks (nemar.preset-checks.v1) against their vectors.

``views/vectors/preset-checks.v1.json`` comes from
``scripts/generate_kind_vectors.py``, which runs ``neuroschema.views.presets``
on views built from the presets example. These tests replay every case, hold
the words of ``docs/views/presets.md`` to the reference, and show that the
vectors catch a renderer that gets the window rule wrong. No mocks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest

from neuroschema.views import load_registry
from neuroschema.views.models import Refusal, content_validator, view_validator
from neuroschema.views.presets import (
    PRESET_CHECKS_FORMAT,
    check_preset,
    read_channels,
    read_segments,
    window_samples,
)

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "views" / "presets.md"
VECTORS = json.loads(
    (ROOT / "views" / "vectors" / "preset-checks.v1.json").read_text(encoding="utf-8")
)
CASES = VECTORS["cases"]


def files_of(case: dict) -> dict[str, bytes]:
    return {k: v["text"].encode("utf-8") for k, v in case["files"].items()}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases_replay(case):
    registry = load_registry()
    registry = registry | {"caps": registry["caps"] | case.get("caps", {})}
    got = check_preset(case["view"], files_of(case), registry, case.get("store"))
    assert got == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_every_case_declares_a_valid_view(case):
    assert view_validator().is_valid(case["view"])


def test_vector_file():
    assert VECTORS["format"] == PRESET_CHECKS_FORMAT == "nemar.preset-checks.v1"
    assert (ROOT / VECTORS["spec"]).resolve() == SPEC
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names))
    algorithms = {a["name"]: a for a in load_registry()["algorithms"]}
    assert algorithms[PRESET_CHECKS_FORMAT] == {
        "name": PRESET_CHECKS_FORMAT,
        "spec": "docs/views/presets.md",
        "vectors": "views/vectors/preset-checks.v1.json",
    }


def _doc_words() -> dict[tuple[str, str], str]:
    """The Words table of presets.md: (word, preset) -> outcome."""
    section = SPEC.read_text().split("\n## Words\n", 1)[1].split("\n## ", 1)[0]
    words = {}
    for cells, preset, outcome in re.findall(
        r"^\| (`[a-z_]+`(?:, `[a-z_]+`)*) \| `([a-z.-]+)` \| (base|nothing drawn) \|",
        section,
        re.M,
    ):
        for word in re.findall(r"`([a-z_]+)`", cells):
            words[(word, preset)] = "base" if outcome == "base" else "nothing"
    return words


GRAMMAR = {"tsv_encoding", "tsv_line_endings", "tsv_header_repeated", "tsv_ragged"}


def _raised_words() -> set[str]:
    """The words the reference raises: its own, and the generic readers' it
    calls (the TSV grammar, a cell's number, the caps)."""
    source = (ROOT / "src" / "neuroschema" / "views" / "presets.py").read_text()
    own = set(re.findall(r'(?:PresetRefused|KindRefused)\("([a-z_]+)"', source))
    return own | GRAMMAR | {"cell_not_number", "cell_not_finite", "cap_exceeded"}


def test_words_table_matches_the_reference():
    assert {word for word, _preset in _doc_words()} == _raised_words()


def test_every_word_has_a_vector_with_its_outcome():
    """Each (word, preset) of the table is some case's, with the table's
    outcome; the grammar's words other than tsv_ragged, and the caps, are the
    generic kinds' and vectored there."""
    seen = {
        (c["expected"]["word"], c["view"]["kind"]): c["expected"]["outcome"]
        for c in CASES
        if c["expected"]["word"] and c["expected"]["outcome"] != "fallback"
    }
    doc = _doc_words()
    generic = GRAMMAR - {"tsv_ragged"} | {"cap_exceeded", "cell_not_finite"}
    for (word, preset), outcome in doc.items():
        if word in generic:
            continue
        assert seen.get((word, preset)) == outcome, (word, preset)
    for (word, preset), outcome in seen.items():
        if (word, preset) in doc:
            assert doc[(word, preset)] == outcome, (word, preset)


# ── The order of checks: every neighboring pair has a two-fault case ──────


IC_CLASSES = [c for c in CASES if c["view"]["kind"] == "nemar.ic-classes"]
WINDOWS = [c for c in CASES if c["view"]["kind"] == "nemar.signal-window"]


def _content(case):
    return json.loads(files_of(case)[case["view"]["data"][0]["location"]])


def _content_check(case):
    ok = content_validator("content.nemar.ic-classes.v1.schema.json").is_valid(
        _content(case)
    )
    return None if ok else "content_invalid"


def _variance_check(case):
    """A guarded port: with no summed variances there is nothing to compare."""
    content = _content(case)
    if "summed_variance_pct" not in content:
        return None
    lengths = len(content["summed_variance_pct"]), len(content["categories"])
    return None if lengths[0] == lengths[1] else "variance_length"


def _total_check(case):
    content = _content(case)
    total = sum(content["counts"])
    return None if total == content.get("n_components") else "components_total"


def _files_check(case):
    try:
        check_signal_window_files(case)
    except Refusal as exc:  # the generic file words
        return exc.word
    return None


def check_signal_window_files(case):
    for role in ("channels", "badsegments"):
        entry = next((i for i in case["view"]["inputs"] if i["role"] == role), None)
        if entry is None:
            continue
        data = files_of(case)[entry["file"]["location"]]
        if len(data) != entry["file"]["size"]:
            raise _Word("file_size_mismatch")
        if hashlib.sha256(data).hexdigest() != entry["file"]["sha256"]:
            raise _Word("file_digest_mismatch")
        caps = load_registry()["caps"] | case.get("caps", {})
        if len(data) > caps["bytes_per_role"]:
            raise _Word("cap_exceeded")


class _Word(Refusal):
    """A file word this port raises itself."""


def _digest_check(case):
    signal = next(i for i in case["view"]["inputs"] if i["role"] == "signal")
    declared = signal["store"]["content_sha256"]
    published = case["store"]["published_sha256"]
    if declared is None or published is None or declared == published:
        return None
    return "store_digest_mismatch"


def _tables_check(case):
    caps = load_registry()["caps"] | case.get("caps", {})
    for role, read in (("channels", read_channels), ("badsegments", read_segments)):
        entry = next((i for i in case["view"]["inputs"] if i["role"] == role), None)
        if entry is not None:
            try:
                read(files_of(case)[entry["file"]["location"]], caps)
            except Refusal as exc:
                return exc.word
    return None


def _bad_channels_check(case):
    caps = load_registry()["caps"] | case.get("caps", {})
    entry = next(i for i in case["view"]["inputs"] if i["role"] == "channels")
    try:
        rows = read_channels(files_of(case)[entry["file"]["location"]], caps)
    except Refusal:
        return None  # the tables' check refuses this one
    labels = case["store"]["labels"]
    unknown = [r for r in rows if r["status"] == "bad" and r["name"] not in labels]
    return "bad_channel_unknown" if unknown else None


def _window_check(case):
    parameters, store = case["view"]["parameters"], case["store"]
    _first, count = window_samples(
        parameters["start_s"], parameters["duration_s"], store["samples"], store["rate"]
    )
    return None if count else "window_outside"


def _port(order):
    def run(case):
        for check in order:
            word = check(case)
            if word:
                return word
        return None

    return run


ORDERS = {
    "nemar.ic-classes": (IC_CLASSES, [_content_check, _variance_check, _total_check]),
    "nemar.signal-window": (
        WINDOWS,
        [
            _files_check,
            _digest_check,
            _tables_check,
            _bad_channels_check,
            _window_check,
        ],
    ),
}
PAIRS = [
    (kind, i) for kind, (_cases, order) in ORDERS.items() for i in range(len(order) - 1)
]


@pytest.mark.parametrize("kind", list(ORDERS))
def test_the_ports_in_the_stated_order_give_every_word(kind):
    cases, order = ORDERS[kind]
    run = _port(order)
    for case in cases:
        if case["expected"].get("outcome") == "fallback":
            continue  # the base refused first; the preset's checks never ran
        assert run(case) == case["expected"]["word"], case["name"]


@pytest.mark.parametrize(
    ("kind", "i"), PAIRS, ids=[f"{k}-{ORDERS[k][1][i].__name__}" for k, i in PAIRS]
)
def test_each_neighboring_pair_of_checks_has_a_two_fault_case(kind, i):
    """Some case fails both checks of the pair, and the port with the two
    swapped gives it another word."""
    cases, order = ORDERS[kind]
    swapped = [*order[:i], order[i + 1], order[i], *order[i + 2 :]]
    both = [
        c
        for c in cases
        if c["expected"].get("outcome") != "fallback"
        and order[i](c) is not None
        and order[i + 1](c) is not None
    ]
    assert both, "no case holds both faults"
    assert any(_port(swapped)(c) != c["expected"]["word"] for c in both)


IN_STEP = {
    "signal_window_order_channels_file_before_segments_file": "file_size_mismatch",
    "signal_window_order_channels_before_segments": "column_missing",
    "signal_window_onset_before_duration": "cell_not_number",
}


def test_in_step_orders_have_two_fault_vectors():
    """Channels before bad segments, for the files and for the reading, and
    the onset before the duration: each a case with two faults of different
    words, whose recorded word is the earlier check's."""
    by_name = {c["name"]: c for c in CASES}
    for name, word in IN_STEP.items():
        assert by_name[name]["expected"] == {"word": word, "outcome": "nothing"}


def test_a_table_the_record_names_none_of_is_said():
    case = next(c for c in CASES if c["name"] == "signal_window_no_bad_segment_table")
    assert case["view"]["parameters"]["bad_segment_table"] is False
    assert case["expected"]["notes"] == ["no_bad_segment_table"]
    assert case["expected"]["segments"] == []
    drawn = [c for c in CASES if c["view"]["kind"] == "nemar.signal-window"]
    for c in drawn:
        if c["expected"]["word"] is None:
            flag = c["view"]["parameters"]["bad_segment_table"]
            assert c["expected"]["notes"] == ([] if flag else ["no_bad_segment_table"])


def test_reordered_columns_draw():
    case = next(c for c in CASES if c["name"] == "signal_window_columns_reordered")
    plain = next(c for c in CASES if c["name"] == "signal_window")
    assert case["expected"] == plain["expected"]


def test_the_base_refuses_before_the_preset_checks():
    case = next(c for c in CASES if c["name"] == "ic_classes_base_refuses")
    assert case["expected"] == {"word": "counts_length", "outcome": "fallback"}


# ── The window rule ───────────────────────────────────────────────────────


def _rounded(start_s, duration_s, samples, rate):
    """A renderer that rounds the products up instead of comparing times."""
    first = math.ceil(start_s * rate)
    last = min(math.ceil((start_s + duration_s) * rate), samples)
    return min(first, samples), max(last - first, 0)


def test_the_vectors_catch_a_rounded_window():
    misses = []
    for case in WINDOWS:
        if case["expected"]["word"] is not None:
            continue
        parameters, store = case["view"]["parameters"], case["store"]
        got = _rounded(
            parameters["start_s"],
            parameters["duration_s"],
            store["samples"],
            store["rate"],
        )
        if got != (case["expected"]["first"], case["expected"]["count"]):
            misses.append(case["name"])
    assert misses == ["signal_window_odd_rate"]


@pytest.mark.parametrize(
    ("start", "duration", "expected"),
    [(0.0, 0.01, (0, 3)), (0.004, 0.004, (1, 1)), (1.0, 1.0, (250, 0))],
)
def test_window_samples(start, duration, expected):
    assert window_samples(start, duration, 250, 250.0) == expected
