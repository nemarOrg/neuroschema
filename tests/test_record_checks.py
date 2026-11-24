"""The record checks (nemar.record-checks.v1) against their vectors.

``views/vectors/record-checks.v1.json`` comes from
``scripts/generate_kind_vectors.py``, which runs ``neuroschema.records``. These
tests replay it, hold the words to the page, and show the vectors catch a port
that skips a rule. No mocks: the entries are the example's, edited.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from neuroschema.records import RECORD_CHECKS_FORMAT, WORDS, check_record
from neuroschema.views import load_registry

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "processing-extensions.md"
VECTORS = json.loads(
    (ROOT / "views" / "vectors" / "record-checks.v1.json").read_text(encoding="utf-8")
)
CASES = VECTORS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_record_check_vectors_replay(case):
    assert check_record(case["recipe"], case["entry"]) == case["expected"]


def test_vector_file():
    assert VECTORS["format"] == RECORD_CHECKS_FORMAT == "nemar.record-checks.v1"
    assert (ROOT / VECTORS["spec"]).resolve() == SPEC
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names))
    algorithms = {a["name"]: a for a in load_registry()["algorithms"]}
    assert algorithms[RECORD_CHECKS_FORMAT] == {
        "name": RECORD_CHECKS_FORMAT,
        "spec": "docs/processing-extensions.md",
        "vectors": "views/vectors/record-checks.v1.json",
    }


def test_the_words_table_is_the_references():
    section = SPEC.read_text().split("### Record checks", 1)[1].split("\n## ", 1)[0]
    documented = re.findall(r"^\| `([a-z_]+)` \|", section, re.M)
    assert tuple(documented) == WORDS
    given = {f["word"] for c in CASES for f in c["expected"]}
    assert given == set(WORDS)


def test_the_example_passes():
    assert next(c for c in CASES if c["name"] == "record")["expected"] == []


@pytest.mark.parametrize(
    ("skipped", "name"),
    [
        ("metric_producer_mismatch", "metric_prefix_other_plugin"),
        ("view_source_mismatch", "view_source_other_recipe"),
        ("view_key_repeated", "view_key_repeated"),
    ],
)
def test_a_port_that_skips_a_rule_misses_a_case(skipped, name):
    """A port that never gives one word misses that word's case."""
    case = next(c for c in CASES if c["name"] == name)
    port = [
        f for f in check_record(case["recipe"], case["entry"]) if f["word"] != skipped
    ]
    assert port != case["expected"]
