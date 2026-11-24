"""``nemar.record-checks.v1``: the rules of a recording's ``dataQuality`` entry
that JSON Schema cannot state, because each compares one value with another.

``docs/processing-extensions.md`` (Record checks) is the normative text. The
backend runs them before it stores an entry, and a renderer runs them before it
draws the entry's views, so neither relies on the writer alone.
``views/vectors/record-checks.v1.json`` holds the cases every implementation
reproduces; this module is the Python reference.
"""

from __future__ import annotations

from collections.abc import Mapping

RECORD_CHECKS_FORMAT = "nemar.record-checks.v1"
WORDS = ("metric_producer_mismatch", "view_source_mismatch", "view_key_repeated")


def check_record(recipe_id: str, entry: Mapping) -> list[dict]:
    """The findings of one recording's entry for one recipe, each
    ``{"word", "at"}`` (``at`` a slash path inside the entry), in document order:
    the metrics in key order, then the views, then the views skipped.

    ``recipe_id`` is the entry's key under ``recipes``: an entry does not hold
    its own key. An empty list means the entry passes.

    - ``metric_producer_mismatch``: a metric ``<plugin>:<name>`` whose producer
      is another plugin, or a bare metric whose producer recipe is not the
      entry's recipe;
    - ``view_source_mismatch``: a view whose ``source`` is a recipe other than
      the entry's (a view a plugin wrote is the plugin's, and not checked here);
    - ``view_key_repeated``: a view key a view earlier in the entry has, or a
      key of ``views_skipped`` that repeats or names a view the entry declares.
    """
    findings: list[dict] = []
    for name, metric in entry.get("metrics", {}).items():
        prefix, colon, _local = name.partition(":")
        if colon:
            producer = (metric.get("plugin") or {}).get("name")
            if producer != prefix:
                findings.append(_finding("metric_producer_mismatch", f"metrics/{name}"))
        elif (metric.get("recipe") or {}).get("name") != recipe_id:
            findings.append(_finding("metric_producer_mismatch", f"metrics/{name}"))
    keys: set[str] = set()
    for index, view in enumerate(entry.get("views", [])):
        recipe = view.get("source", {}).get("recipe")
        if recipe is not None and recipe.get("name") != recipe_id:
            findings.append(_finding("view_source_mismatch", f"views/{index}/source"))
        if view.get("key") in keys:
            findings.append(_finding("view_key_repeated", f"views/{index}/key"))
        keys.add(view.get("key"))
    for index, skipped in enumerate(entry.get("views_skipped", [])):
        if skipped.get("key") in keys:
            findings.append(_finding("view_key_repeated", f"views_skipped/{index}/key"))
        keys.add(skipped.get("key"))
    return findings


def _finding(word: str, at: str) -> dict:
    return {"word": word, "at": at}
