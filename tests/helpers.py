"""Test-only helpers: failure reduction and the invariants JSON Schema cannot express.

The processing extensions carry arithmetic invariants (column sums, equal totals,
the skip cascade, histogram lengths) that JSON Schema 2020-12 cannot check. The
writer (the NEMAR backend) enforces them; these helpers check the examples and
are not part of the package.
"""

from __future__ import annotations

import bisect
from itertools import pairwise


def failures(errors) -> set[tuple[str, str]]:
    """Reduce validation errors to (failing validator, JSON path) pairs.

    Asserting the validator and the path, not just that some error exists,
    keeps a negative test from passing for the wrong reason (for example,
    "additional property not allowed" when the field is missing from the
    schema altogether).
    """
    return {
        (e.validator, "/".join(str(part) for part in e.absolute_path)) for e in errors
    }


def count_problems(dataset_processing: dict) -> list[str]:
    """Problems in a dataset-level processing document's counts."""
    problems: list[str] = []
    for recipe, entry in dataset_processing.get("recipes", {}).items():
        counts = entry["counts"]
        declared = entry["declared_checkpoints"]
        if set(counts) != set(declared):
            problems.append(f"{recipe}: count keys differ from declared checkpoints")
        totals = set()
        for name, c in counts.items():
            if c["passed"] + c["failed"] + c["skipped"] != c["total"]:
                problems.append(f"{recipe}/{name}: passed+failed+skipped != total")
            totals.add(c["total"])
        if len(totals) > 1:
            problems.append(f"{recipe}: checkpoints have unequal totals")
        present = [name for name in declared if name in counts]
        for before, name in pairwise(present):
            here, nxt = counts[before], counts[name]
            if nxt["skipped"] < here["skipped"] + here["failed"]:
                problems.append(
                    f"{recipe}/{name}: skipped below earlier failed+skipped"
                )
            if nxt["passed"] > here["passed"]:
                problems.append(f"{recipe}/{name}: passed above the earlier checkpoint")
    return problems


def cascade_problems(
    record_processing: dict, declared: dict[str, list[str]]
) -> list[str]:
    """Problems in a record-level processing document's checkpoint cascade.

    ``declared`` maps each recipe to its declared checkpoints in order.
    """
    problems: list[str] = []
    for recipe, entry in record_processing.get("recipes", {}).items():
        checkpoints = entry["checkpoints"]
        order = declared[recipe]
        undeclared = sorted(set(checkpoints) - set(order))
        if undeclared:
            problems.append(f"{recipe}: undeclared checkpoints {undeclared}")
        missing = [name for name in order if name not in checkpoints]
        if missing:
            problems.append(f"{recipe}: missing checkpoints {missing}")
            continue
        first = None
        for name in order:
            outcome = checkpoints[name]
            if first is None:
                if outcome["status"] != "passed":
                    first = outcome
            elif (
                outcome["status"] != "skipped"
                or outcome.get("code") != first.get("code")
                or outcome.get("step") != first.get("step")
            ):
                problems.append(f"{recipe}/{name}: breaks the skip cascade")
    return problems


def _bin(edges: list[float], value: float) -> int:
    """nemar-process's binning: [e_i, e_i+1), last bin closed; -1 under, len over."""
    if value < edges[0]:
        return -1
    if value > edges[-1]:
        return len(edges) - 1
    return min(bisect.bisect_right(edges, value) - 1, len(edges) - 2)


def _bin_of_rank(hist: dict, rank: int) -> int:
    """The bin holding the rank-th smallest value (1-based), underflow -1."""
    cells = [hist["underflow"], *hist["counts"], hist["overflow"]]
    seen = 0
    for index, count in enumerate(cells):
        seen += count
        if seen >= rank:
            return index - 1
    return len(cells) - 2


def histogram_problems(distribution: dict) -> list[str]:
    """Problems in one distribution: its histogram and its min, median and max."""
    problems: list[str] = []
    hist = distribution["histogram"]
    edges, n = hist["edges"], distribution["n"]
    if any(b <= a for a, b in pairwise(edges)):
        problems.append("edges not strictly increasing")
        return problems
    if len(hist["counts"]) != len(edges) - 1:
        problems.append("len(counts) != len(edges) - 1")
        return problems
    if n != sum(hist["counts"]) + hist["underflow"] + hist["overflow"]:
        problems.append("n != sum(counts) + underflow + overflow")
        return problems
    lo, mid, hi = distribution["min"], distribution["median"], distribution["max"]
    if n == 0:
        if (lo, mid, hi) != (None, None, None):
            problems.append("min, median, max must be null when n is 0")
        return problems
    if None in (lo, mid, hi):
        problems.append("min, median, max must be set when n > 0")
        return problems
    if not lo <= mid <= hi:
        problems.append("not min <= median <= max")
    if _bin(edges, lo) != _bin_of_rank(hist, 1):
        problems.append("min is not in the first non-empty bin")
    if _bin(edges, hi) != _bin_of_rank(hist, n):
        problems.append("max is not in the last non-empty bin")
    low_rank, high_rank = (n + 1) // 2, n // 2 + 1
    if not (
        _bin_of_rank(hist, low_rank)
        <= _bin(edges, mid)
        <= _bin_of_rank(hist, high_rank)
    ):
        problems.append("median is not in the bin the cumulative counts give")
    return problems


def quality_problems(dataset_quality: dict) -> list[str]:
    """Problems in a dataset-level dataQuality document's counts and lists."""
    problems: list[str] = []
    for recipe, entry in dataset_quality.get("recipes", {}).items():
        c = entry["counts"]
        if c["passed"] + c["failed"] + c["skipped"] != c["total"]:
            problems.append(f"{recipe}: passed+failed+skipped != total")
        listed = len(entry["not_processed"]) + entry["not_processed_truncated"]
        if listed != c["failed"] + c["skipped"]:
            problems.append(f"{recipe}: not_processed does not cover failed+skipped")
        for name, dist in entry["distributions"].items():
            problems += [f"{recipe}/{name}: {p}" for p in histogram_problems(dist)]
    return problems


def total_problems(dataset_quality: dict, dataset_processing: dict) -> list[str]:
    """dataQuality dataset totals must equal the processing totals per recipe."""
    problems: list[str] = []
    for recipe, entry in dataset_quality.get("recipes", {}).items():
        proc = dataset_processing.get("recipes", {}).get(recipe)
        if proc is None:
            problems.append(f"{recipe}: no processing entry")
            continue
        totals = {c["total"] for c in proc["counts"].values()}
        if totals != {entry["counts"]["total"]}:
            problems.append(f"{recipe}: dataQuality total differs from processing")
        last = proc["counts"].get(proc["declared_checkpoints"][-1])
        if last is None:
            continue
        quality = entry["counts"]
        if quality["passed"] != last["passed"]:
            problems.append(
                f"{recipe}: dataQuality passed differs from the last checkpoint"
            )
        if quality["failed"] + quality["skipped"] != last["total"] - last["passed"]:
            problems.append(
                f"{recipe}: dataQuality failed+skipped differs from the last checkpoint"
            )
    return problems
