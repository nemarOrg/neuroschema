"""The presets' own checks (nemar.preset-checks.v1) against their vectors.

``views/vectors/preset-checks.v1.json`` comes from
``scripts/generate_kind_vectors.py``, which runs ``neuroschema.views.presets``
on views built from the presets example. These tests replay every case, hold
the words of ``docs/views/presets.md`` to the reference, and show that the
vectors catch a renderer that gets the window rule wrong. No mocks.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from neuroschema.views import load_registry
from neuroschema.views.models import view_validator
from neuroschema.views.presets import (
    PRESET_CHECKS_FORMAT,
    check_preset,
    window_samples,
)

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "views" / "presets.md"
VECTORS = __import__("json").loads(
    (ROOT / "views" / "vectors" / "preset-checks.v1.json").read_text(encoding="utf-8")
)
CASES = VECTORS["cases"]


def files_of(case: dict) -> dict[str, bytes]:
    return {k: v["text"].encode("utf-8") for k, v in case["files"].items()}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases_replay(case):
    got = check_preset(case["view"], files_of(case), store=case.get("store"))
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


def _doc_words() -> dict[str, str]:
    """The Words table of presets.md: word -> outcome."""
    section = SPEC.read_text().split("\n## Words\n", 1)[1].split("\n## ", 1)[0]
    words = {}
    for cells, outcome in re.findall(
        r"^\| (`[a-z_]+`(?:, `[a-z_]+`)*) \| `[^|]+` \| (base|nothing drawn) \|",
        section,
        re.M,
    ):
        for word in re.findall(r"`([a-z_]+)`", cells):
            words[word] = "base" if outcome == "base" else "nothing"
    return words


def _raised_words() -> set[str]:
    source = (ROOT / "src" / "neuroschema" / "views" / "presets.py").read_text()
    own = set(re.findall(r'(?:PresetRefused|KindRefused)\("([a-z_]+)"', source))
    return own | {
        "tsv_encoding",
        "tsv_line_endings",
        "tsv_header_repeated",
        "tsv_ragged",
    }


def test_words_table_matches_the_reference():
    assert set(_doc_words()) == _raised_words()


def test_every_word_has_a_vector_with_its_outcome():
    """Each word of the table is some case's word, with the table's outcome;
    the TSV grammar's words are the generic kinds', vectored there."""
    seen = {
        c["expected"]["word"]: c["expected"]["outcome"]
        for c in CASES
        if c["expected"]["word"] and c["expected"]["outcome"] != "fallback"
    }
    doc = _doc_words()
    grammar = {"tsv_encoding", "tsv_line_endings", "tsv_header_repeated"}
    assert set(doc) - grammar <= set(seen)
    for word, outcome in seen.items():
        if word in doc:
            assert doc[word] == outcome, word


def test_each_neighboring_pair_of_checks_has_a_two_fault_case():
    names = {c["name"] for c in CASES}
    assert {
        "ic_classes_order_variance_before_total",
        "ic_classes_order_content_before_total",
        "ic_classes_base_refuses",
        "signal_window_order",
    } <= names


def test_the_base_refuses_before_the_preset_checks():
    case = next(c for c in CASES if c["name"] == "ic_classes_base_refuses")
    assert case["expected"] == {"word": "counts_length", "outcome": "fallback"}


# ── The window rule ───────────────────────────────────────────────────────


WINDOWS = [c for c in CASES if c["view"]["kind"] == "nemar.signal-window"]


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
