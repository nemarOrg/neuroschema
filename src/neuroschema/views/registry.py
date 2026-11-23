"""The view registry, ``views/registry.json`` (``neuroschema.views-registry.v1``).

The registry lists the view kinds neuroschema defines (each with its base,
roles, dimensions and schema file), the transforms and algorithms (each with
its specification and vectors), the data formats, the reserved dimension names
and the size caps. ``docs/views.md`` explains each part.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "views" / "registry.json"
REGISTRY_FORMAT = "neuroschema.views-registry.v1"


class Drawing(NamedTuple):
    """How a renderer that knows the registry draws a view.

    ``via`` is ``kind`` (the view's own kind is known), ``base`` (only its base
    is known, so the generic renderer draws it) or ``table`` (neither is known,
    so the data show as a table with a download; never an error).
    """

    via: Literal["kind", "base", "table"]
    kind: str | None
    kind_version: int | None


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    """Load the registry and check its format string."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("format") != REGISTRY_FORMAT:
        raise ValueError(
            f"{path}: format is {registry.get('format')!r}, not {REGISTRY_FORMAT!r}"
        )
    return registry


def known_kinds(registry: Mapping) -> dict[tuple[str, int], dict]:
    """The registry's kinds, keyed by (kind, kind_version)."""
    kinds: dict[tuple[str, int], dict] = {}
    for entry in registry["kinds"]:
        pair = (entry["kind"], entry["kind_version"])
        if pair in kinds:
            raise ValueError(f"kind {pair[0]} version {pair[1]} is listed twice")
        kinds[pair] = entry
    return kinds


def kind_schema_path(
    kind: str, kind_version: int, registry: Mapping | None = None
) -> Path | None:
    """The schema file of a known kind and version, or None for an unknown one."""
    registry = load_registry() if registry is None else registry
    entry = known_kinds(registry).get((kind, kind_version))
    return None if entry is None else REPO_ROOT / entry["schema"]


def draw_as(view: Mapping, registry: Mapping | None = None) -> Drawing:
    """Apply the renderer rule to a view declaration.

    A known kind draws with its own renderer; otherwise a known base draws
    with the generic renderer; otherwise the data show as a table.
    """
    kinds = known_kinds(load_registry() if registry is None else registry)
    own = (view["kind"], view["kind_version"])
    if own in kinds:
        return Drawing("kind", *own)
    if "base" in view:
        base = (view["base"], view["base_version"])
        if base in kinds:
            return Drawing("base", *base)
    return Drawing("table", None, None)
