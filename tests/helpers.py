"""Test-only helpers: failure reduction and the invariants JSON Schema cannot express.

The processing extensions carry arithmetic invariants (column sums, equal totals,
the skip cascade, histogram lengths) that JSON Schema 2020-12 cannot check. The
writer (the NEMAR backend) enforces them; these helpers check the examples and
are not part of the package.
"""

from __future__ import annotations


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


def histogram_problems(distribution: dict) -> list[str]:
    """Problems in one distribution's histogram."""
    problems: list[str] = []
    hist = distribution["histogram"]
    if len(hist["counts"]) != len(hist["edges"]) - 1:
        problems.append("len(counts) != len(edges) - 1")
    if distribution["n"] != sum(hist["counts"]) + hist["underflow"] + hist["overflow"]:
        problems.append("n != sum(counts) + underflow + overflow")
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
    return problems
