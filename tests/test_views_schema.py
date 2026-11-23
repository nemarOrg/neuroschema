"""Tests for the view vocabulary (neuroschema 0.6.0).

Real schema files, examples and vectors; no mocks. Failures are asserted as
(validator, path) pairs so a negative test cannot pass for the wrong reason.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from neuroschema.views import (
    CanonicalizationError,
    canonicalize,
    view_digest,
)

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "views" / "vectors" / "view-digest.v1.json").read_text())


def vector(name: str) -> dict:
    """A copy of one digest vector's declaration."""
    case = next(c for c in VECTORS["cases"] if c["name"] == name)
    return copy.deepcopy(case["declaration"])


# ── nemar.view-digest.v1 ──────────────────────────────────────────────────


CASES = VECTORS["cases"]
REFUSALS = VECTORS["refusals"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_digest_vectors_replay(case):
    assert canonicalize(case["declaration"]) == case["canonical"].encode("utf-8")
    assert view_digest(case["declaration"]) == case["sha256"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vector_digest_is_the_sha256_of_its_canonical_text(case):
    digest = hashlib.sha256(case["canonical"].encode("utf-8")).hexdigest()
    assert digest == case["sha256"]


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r["name"] for r in REFUSALS])
def test_digest_refusals(refusal):
    with pytest.raises(CanonicalizationError):
        view_digest(json.loads(refusal["json"]))


def test_vector_file_header():
    assert VECTORS["format"] == "nemar.view-digest.v1"
    assert (ROOT / VECTORS["spec"]).is_file()
    names = [c["name"] for c in [*CASES, *REFUSALS]]
    assert len(names) == len(set(names))


def _jcs_like(value, *, sort, ensure_ascii=False):
    """A canonicalizer that differs from RFC 8785 in one way, for the test below."""
    if isinstance(value, dict):
        items = sort(value) if sort else list(value)
        inner = ",".join(
            json.dumps(k, ensure_ascii=ensure_ascii)
            + ":"
            + _jcs_like(value[k], sort=sort, ensure_ascii=ensure_ascii)
            for k in items
        )
        return "{" + inner + "}"
    if isinstance(value, list):
        return (
            "["
            + ",".join(
                _jcs_like(v, sort=sort, ensure_ascii=ensure_ascii) for v in value
            )
            + "]"
        )
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=ensure_ascii)
    return canonicalize(value).decode("utf-8")


@pytest.mark.parametrize(
    "variant",
    [
        {"sort": None},
        {"sort": sorted},
        {
            "sort": lambda d: sorted(d, key=lambda k: k.encode("utf-16-be")),
            "ensure_ascii": True,
        },
    ],
    ids=["unsorted", "code-point-order", "ensure-ascii"],
)
def test_vectors_catch_a_wrong_canonicalization(variant):
    """Each plausible mistake gives different bytes for at least one vector."""
    wrong = [
        c["name"]
        for c in CASES
        if _jcs_like(c["declaration"], **variant) != c["canonical"]
    ]
    assert wrong


def test_python_float_printing_is_caught():
    """json.dumps prints 100.0 and 1e-07; the numbers vector expects 100 and 1e-7."""
    case = next(c for c in CASES if c["name"] == "numbers")
    naive = json.dumps(case["declaration"], separators=(",", ":"), sort_keys=True)
    assert naive != case["canonical"]


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        {"s": {1, 2}},
        {"n": 10**400},
        {"n": float("nan")},
        {"n": float("-inf")},
    ],
    ids=["int-key", "set", "huge-int", "nan", "infinity"],
)
def test_values_with_no_canonical_form(value):
    with pytest.raises(CanonicalizationError):
        view_digest(value)


def test_digest_is_over_the_declaration_as_written():
    """A field a reader adds changes the digest, so readers digest before adding."""
    view = vector("table_view")
    plain = view_digest(view)
    assert view_digest(view | {"url": "https://example.org/v"}) != plain
    reordered = dict(reversed(list(view.items())))
    assert view_digest(reordered) == plain
