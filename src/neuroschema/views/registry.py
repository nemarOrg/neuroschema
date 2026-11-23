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


def meets_role_contract(view: Mapping, entry: Mapping) -> bool:
    """Whether a view's stored data meet a registered kind's role contract.

    Every role the registry lists for the kind appears exactly once in the
    view's ``data``, in a format listed for that role, carrying only dimensions
    listed for it (an empty list allows none). Roles the kind does not list are
    allowed; its renderer ignores them.
    """
    data = view.get("data")
    if not isinstance(data, list):
        return False
    for role, spec in entry["roles"].items():
        files = [f for f in data if isinstance(f, Mapping) and f.get("role") == role]
        if len(files) != 1:
            return False
        file = files[0]
        if file.get("format") not in spec["formats"]:
            return False
        dims = file.get("dims", [])
        if not isinstance(dims, list) or any(
            not isinstance(dim, Mapping) or dim.get("name") not in spec["dims"]
            for dim in dims
        ):
            return False
    return True


def draw_as(view: Mapping, registry: Mapping | None = None) -> Drawing:
    """Apply the renderer rule to a view declaration.

    A known kind draws with its own renderer. Otherwise a known base draws
    with the generic renderer, but only when the view's data meet the base's
    role contract (:func:`meets_role_contract`). Otherwise the data show as a
    table. A base without a base version, or one this registry does not know,
    falls back to the table; nothing here raises for an unknown kind.
    """
    kinds = known_kinds(load_registry() if registry is None else registry)
    own = (view.get("kind"), view.get("kind_version"))
    if own in kinds:
        return Drawing("kind", *own)
    base = kinds.get((view.get("base"), view.get("base_version")))
    if base is not None and meets_role_contract(view, base):
        return Drawing("base", base["kind"], base["kind_version"])
    return Drawing("table", None, None)
