"""The view vocabulary: the registry of kinds and the view digest.

See ``docs/views.md``. The schemas live in ``schema/definitions/view.schema.json``
and ``schema/views/``; this package reads the registry and computes digests.
"""

from neuroschema.views.digest import (
    VIEW_DIGEST_FORMAT,
    CanonicalizationError,
    canonicalize,
    parse_declaration,
    view_digest,
)
from neuroschema.views.registry import (
    REGISTRY_FORMAT,
    REGISTRY_PATH,
    Drawing,
    draw_as,
    kind_schema_path,
    known_kinds,
    load_registry,
    meets_role_contract,
)

__all__ = [
    "REGISTRY_FORMAT",
    "REGISTRY_PATH",
    "VIEW_DIGEST_FORMAT",
    "CanonicalizationError",
    "Drawing",
    "canonicalize",
    "draw_as",
    "kind_schema_path",
    "known_kinds",
    "load_registry",
    "meets_role_contract",
    "parse_declaration",
    "view_digest",
]
