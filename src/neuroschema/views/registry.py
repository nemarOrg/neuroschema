"""The view registry, ``views/registry.json`` (``neuroschema.views-registry.v1``).

The registry lists the view kinds neuroschema defines (each with its base,
roles, dimensions and schema file), the transforms and algorithms (each with
its specification and vectors), the data formats, the reserved dimension names
and the size caps. ``docs/views.md`` explains each part.

The registry is read from a neuroschema checkout, as ``neuroschema.validate``
reads ``schema/``: neither is packaged, because consumers vendor both from the
repository at their published paths.
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import quote

from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema

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
    if not path.is_file():
        raise FileNotFoundError(
            f"View registry not found: {path}. neuroschema reads views/registry.json "
            "from a checkout of its repository (it is not packaged); install from a "
            "checkout or pass the registry's path."
        )
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("format") != REGISTRY_FORMAT:
        raise ValueError(
            f"{path}: format is {registry.get('format')!r}, not {REGISTRY_FORMAT!r}"
        )
    return registry


def download_headers(
    location: str, file_format: str, registry: Mapping | None = None
) -> dict[str, str]:
    """The headers a renderer serves a view file's download with (docs/views.md,
    Formats): the registry's media type for a registered format, and
    ``application/octet-stream`` for any other, so no file runs as a page;
    ``nosniff`` always; and an attachment named for the location's last segment
    by RFC 6266, ``filename*`` in RFC 8187's UTF-8 encoding with an ASCII
    ``filename`` beside it for a client that reads only that."""
    registry = load_registry() if registry is None else registry
    known = registry["formats"].get(file_format)
    name = posixpath.basename(location)
    fallback = "".join(c if " " <= c <= "~" and c not in '"\\%' else "_" for c in name)
    encoded = quote(name.encode("utf-8"), safe="-._~")
    return {
        "Content-Type": known["media_type"] if known else "application/octet-stream",
        "Content-Disposition": (
            f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
        ),
        "X-Content-Type-Options": "nosniff",
    }


def version_of(value: object) -> int | None:
    """A kind or base version as a version: an int, and never a bool. In Python
    ``True == 1`` and they hash alike, so a declaration's ``kind_version: true``
    would find version 1 in any lookup; JSON's ``true`` is no version
    (review r29, round 2)."""
    return value if type(value) is int else None


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


def _admitted(node: Mapping) -> list:
    """The values a role subschema's const or enum admits."""
    if "const" in node:
        return [node["const"]]
    if "enum" in node:
        return list(node["enum"])
    raise ValueError(f"a kind schema's role must be a const or an enum: {node}")


def _kind_schema(entry: Mapping) -> dict:
    return json.loads((REPO_ROOT / entry["schema"]).read_text(encoding="utf-8"))


def role_schemas(entry: Mapping) -> dict[str, dict]:
    """Each role a registered kind's schema admits, with the subschema for it.

    The subschema is the kind schema's ``data.items``, or, for a kind with
    several roles, the branch of its ``oneOf`` or ``anyOf`` whose ``role``
    admits that role. The kind's schema, not the registry's ``roles``, is the
    source: the registry mirrors it, and a test holds the two together. A
    computed kind, whose schema refuses ``data``, has no roles.
    """
    items = _kind_schema(entry)["properties"]["data"].get("items")
    if items is None:  # a computed kind (data: {"not": {}}) has no data roles
        return {}
    branches = items.get("oneOf") or items.get("anyOf") or [items]
    roles: dict[str, dict] = {}
    for branch in branches:
        for role in _admitted(branch["properties"]["role"]):
            if role in roles:
                raise ValueError(f"{entry['schema']}: role {role} has two branches")
            roles[role] = branch
    return roles


def optional_roles(entry: Mapping) -> set[str]:
    """The roles a registered kind's schema marks optional.

    A kind marks a role optional with a ``contains`` clause on ``data`` (or in
    ``data.allOf``) whose subschema's ``role`` is that role and whose
    ``minContains`` is 0. Every other role the kind admits is required.
    """
    data = _kind_schema(entry)["properties"]["data"]
    optional: set[str] = set()
    for clause in [data, *data.get("allOf", [])]:
        if "contains" in clause and clause.get("minContains") == 0:
            optional.update(_admitted(clause["contains"]["properties"]["role"]))
    return optional


def meets_role_contract(view: Mapping, entry: Mapping) -> bool:
    """Whether a view's stored data meet a registered kind's role contract.

    Every role the kind's schema requires appears exactly once in the view's
    ``data``, every role it marks optional (:func:`optional_roles`) at most
    once, and the view's entries in the roles the kind admits, in their order,
    are valid under the kind schema's ``data`` subschema. So each entry meets
    the subschema for its role (:func:`role_schemas`), and the format, the
    dimensions, every field the kind requires and every rule across roles come
    from the one schema. Roles the kind does not admit are allowed; its
    renderer ignores them, and the renderer offers their files for download.
    """
    data = view.get("data")
    if not isinstance(data, list):
        return False
    roles = role_schemas(entry)
    optional = optional_roles(entry)
    files = [f for f in data if isinstance(f, Mapping) and f.get("role") in roles]
    for role in roles:
        count = sum(1 for f in files if f.get("role") == role)
        if count > 1 or (count == 0 and role not in optional):
            return False
    schema, resolver = load_schema(REPO_ROOT / entry["schema"])
    validator = Draft202012Validator(schema["properties"]["data"], resolver=resolver)
    return validator.is_valid(files)


def draw_as(view: Mapping, registry: Mapping | None = None) -> Drawing:
    """Apply the renderer rule to a view declaration.

    A known kind draws with its own renderer. Otherwise a known base draws
    with the generic renderer, but only when the view's data meet the base's
    role contract (:func:`meets_role_contract`). Otherwise the data show as a
    table. A base without a base version, or one this registry does not know,
    falls back to the table; nothing here raises for an unknown kind.
    """
    registry = load_registry() if registry is None else registry
    own = (view.get("kind"), version_of(view.get("kind_version")))
    if own in known_kinds(registry):
        return Drawing("kind", *own)
    return draw_by_base(view, registry)


def draw_by_base(view: Mapping, registry: Mapping | None = None) -> Drawing:
    """The renderer rule for a renderer that does not know the view's own kind.

    The view's base when the registry lists it as a generic kind and the view's
    data meet its role contract (:func:`meets_role_contract`), otherwise a
    table: a preset is never a base. A preset
    with stored data meets its base's contract, so a renderer that knows only
    the base draws it; a computed preset has no data and shows as a table.
    """
    kinds = known_kinds(load_registry() if registry is None else registry)
    base = kinds.get((view.get("base"), version_of(view.get("base_version"))))
    # Only a generic kind is a base: a preset names its own base (and the
    # envelope refuses a preset as a base), so none is drawn over a preset.
    if base is not None and base["base"] is None and meets_role_contract(view, base):
        return Drawing("base", base["kind"], base["kind_version"])
    return Drawing("table", None, None)
