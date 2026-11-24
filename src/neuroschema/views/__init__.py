"""The view vocabulary: the registry of kinds, the view digest and the references.

See ``docs/views.md``. The schemas live in ``schema/definitions/view.schema.json``
and ``schema/views/``. This package reads the registry and applies the renderer
rule (``registry``), computes digests (``digest``), and holds the Python
reference of each algorithm the vectors pin: the generic kinds' models
(``models``, ``docs/views/generic-kinds.md``), the presets' checks
(``presets``), and, with numpy (the extra ``views``), the scalp map
(``sensor_field``), the layout from positions (``sensor_layout``), positions from
labels (``sensor_labels``) and the component activations (``ic_activity``).
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
    draw_by_base,
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
    "draw_by_base",
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
