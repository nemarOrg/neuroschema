"""The view vocabulary: the registry of kinds, the view digest and the models.

See ``docs/views.md``. The schemas live in ``schema/definitions/view.schema.json``
and ``schema/views/``; this package reads the registry, computes digests and
builds the models of the generic kinds (``docs/views/generic-kinds.md``).
"""

from neuroschema.views.digest import (
    VIEW_DIGEST_FORMAT,
    CanonicalizationError,
    canonicalize,
    parse_declaration,
    view_digest,
)
from neuroschema.views.models import (
    MODELS_FORMAT,
    KindRefused,
    Refusal,
    ViewRefused,
    build_model,
    cell_value,
    locate_bin,
    read_json,
    read_tsv,
    snap_row,
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
    optional_roles,
    role_schemas,
)

__all__ = [
    "MODELS_FORMAT",
    "REGISTRY_FORMAT",
    "REGISTRY_PATH",
    "VIEW_DIGEST_FORMAT",
    "CanonicalizationError",
    "Drawing",
    "KindRefused",
    "Refusal",
    "ViewRefused",
    "build_model",
    "canonicalize",
    "cell_value",
    "draw_as",
    "kind_schema_path",
    "known_kinds",
    "load_registry",
    "locate_bin",
    "meets_role_contract",
    "optional_roles",
    "parse_declaration",
    "read_json",
    "read_tsv",
    "role_schemas",
    "snap_row",
    "view_digest",
]
