"""Validate JSON documents against neuroschema.

Programmatic usage::

    from neuroschema.validate import validate_document
    errors = validate_document(doc, schema_path)

CLI usage::

    python -m neuroschema.validate examples/schema1.json
    python -m neuroschema.validate examples/schema1.json \\
        --schema schema/core/record.schema.json

Note: Currently uses the deprecated ``jsonschema.RefResolver`` for $ref
resolution. Planned migration to the ``referencing`` library.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver, ValidationError

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schema"


def _build_store(schema_dir: Path) -> dict[str, dict]:
    """Load all schema files into a URI -> schema mapping for $ref resolution."""
    if not schema_dir.is_dir():
        raise FileNotFoundError(
            f"Schema directory not found: {schema_dir}. "
            f"Ensure the schema files are present or pass a valid schema path."
        )
    store: dict[str, dict] = {}
    for schema_file in schema_dir.rglob("*.schema.json"):
        try:
            with open(schema_file) as f:
                schema = json.load(f)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"Failed to parse {schema_file}: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc
        if "$id" in schema:
            rel = schema_file.relative_to(schema_dir)
            uri = f"file://{schema_dir}/{rel}"
            store[uri] = schema
            store[schema["$id"]] = schema
    return store


def load_schema(
    schema_path: Path | None = None,
    schema_dir: Path = SCHEMA_DIR,
) -> tuple[dict, RefResolver]:
    """Load a JSON Schema with $ref resolution across the schema directory.

    Note: Currently uses the deprecated ``RefResolver``; planned migration
    to the ``referencing`` library.

    Args:
        schema_path: Path to the specific schema file. Defaults to root schema.
        schema_dir: Directory containing all schema files.

    Returns:
        Tuple of (schema_dict, resolver).
    """
    if schema_path is None:
        schema_path = schema_dir / "neuroschema.schema.json"

    with open(schema_path) as f:
        schema = json.load(f)

    store = _build_store(schema_dir)
    resolver = RefResolver(
        base_uri=f"file://{schema_path.parent}/",
        referrer=schema,
        store=store,
    )
    return schema, resolver


def validate_document(
    document: dict,
    schema_path: Path | None = None,
    schema_dir: Path = SCHEMA_DIR,
) -> list[ValidationError]:
    """Validate a document against a neuroschema schema.

    Args:
        document: The JSON document to validate.
        schema_path: Path to the schema file. Defaults to root schema.
        schema_dir: Directory containing all schema files.

    Returns:
        List of validation errors (empty if valid).
    """
    schema, resolver = load_schema(schema_path, schema_dir)
    validator = Draft202012Validator(schema, resolver=resolver)
    return sorted(validator.iter_errors(document), key=lambda e: list(e.path))


def validate_file(
    file_path: Path,
    schema_path: Path | None = None,
    schema_dir: Path = SCHEMA_DIR,
) -> list[ValidationError]:
    """Validate a JSON file against a neuroschema schema.

    Args:
        file_path: Path to the JSON file.
        schema_path: Path to the schema file. Defaults to root schema.
        schema_dir: Directory containing all schema files.

    Returns:
        List of validation errors (empty if valid).
    """
    with open(file_path) as f:
        document = json.load(f)
    return validate_document(document, schema_path, schema_dir)


def main() -> int:
    """CLI entry point for schema validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate JSON documents against neuroschema schemas."
    )
    parser.add_argument("file", type=Path, help="JSON file to validate")
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Schema file to validate against (default: root schema)",
    )
    args = parser.parse_args()

    try:
        errors = validate_file(args.file, args.schema)
    except FileNotFoundError as exc:
        print(f"ERROR: File not found: {exc.filename or exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: Invalid JSON (line {exc.lineno}, col {exc.colno}): {exc.msg}",
            file=sys.stderr,
        )
        return 2
    except PermissionError as exc:
        print(f"ERROR: Permission denied: {exc.filename}", file=sys.stderr)
        return 2

    if errors:
        print(f"INVALID: {len(errors)} error(s) found in {args.file}")
        for error in errors:
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            print(f"  - {path}: {error.message}")
        return 1

    print(f"VALID: {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
