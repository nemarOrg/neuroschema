"""``nemar.view-digest.v1``: the SHA-256 of a view declaration's canonical JSON.

The canonical form is the JSON Canonicalization Scheme (JCS) of RFC 8785:
object members sorted by the UTF-16 code units of their names, no whitespace,
numbers as ECMAScript prints a binary64 value, strings with only the escapes
JSON requires, and UTF-8 output. ``docs/views/view-digest.md`` is the normative
text and ``views/vectors/view-digest.v1.json`` holds the cases every
implementation must reproduce.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

VIEW_DIGEST_FORMAT = "nemar.view-digest.v1"

_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


class CanonicalizationError(ValueError):
    """A value that has no canonical JSON form, so no digest."""


def canonicalize(value: object) -> bytes:
    """Return the RFC 8785 canonical JSON of a parsed JSON value, as UTF-8.

    Raises :class:`CanonicalizationError` for a value that is not JSON (a
    non-string key, a tuple key, a set), a number that is not finite or not
    representable as a binary64, and a string holding a lone surrogate.
    """
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts).encode("utf-8")


def parse_declaration(text: str | bytes) -> object:
    """Parse a declaration from JSON text as Internet JSON (I-JSON, RFC 7493).

    ``text`` is a ``str``, or ``bytes`` that decode as strict UTF-8 with no
    byte order mark; ``json.loads`` would also accept UTF-16, UTF-32 and a
    UTF-8 byte order mark, which I-JSON forbids. Refuses, with
    :class:`CanonicalizationError`, any other input, text that is not JSON, a
    duplicate member name at any depth (``json.loads`` would keep the last one
    silently) and the ``NaN``, ``Infinity`` and ``-Infinity`` literals Python
    accepts and JSON does not. Digest a declaration read from text through
    this function.
    """
    if isinstance(text, bytes | bytearray):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError("declaration text is not UTF-8") from exc
    elif not isinstance(text, str):
        raise CanonicalizationError(
            f"declaration text is str or UTF-8 bytes, not {type(text).__name__}"
        )
    try:
        return json.loads(
            text, object_pairs_hook=_unique_members, parse_constant=_refuse_constant
        )
    except json.JSONDecodeError as exc:
        # A byte order mark lands here too: json.loads refuses one in a str.
        raise CanonicalizationError(f"declaration text is not JSON: {exc}") from exc


def _unique_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise CanonicalizationError(f"duplicate member name {key!r}")
        obj[key] = value
    return obj


def _refuse_constant(literal: str) -> object:
    raise CanonicalizationError(f"{literal} is not a JSON number")


def view_digest(declaration: Mapping[str, object]) -> str:
    """Return the ``nemar.view-digest.v1`` of a view declaration as 64 hex digits.

    The declaration is the object as written in the record, without any field
    a reader added to it.
    """
    if not isinstance(declaration, Mapping):
        raise CanonicalizationError("a view declaration is a JSON object")
    return hashlib.sha256(canonicalize(declaration)).hexdigest()


def _write(value: object, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif value is True:
        parts.append("true")
    elif value is False:
        parts.append("false")
    elif isinstance(value, int | float):
        parts.append(_number(value))
    elif isinstance(value, str):
        parts.append(_string(value))
    elif isinstance(value, Mapping):
        parts.append("{")
        for index, key in enumerate(_sorted_keys(value)):
            if index:
                parts.append(",")
            parts.append(_string(key))
            parts.append(":")
            _write(value[key], parts)
        parts.append("}")
    elif isinstance(value, list | tuple):
        parts.append("[")
        for index, item in enumerate(value):
            if index:
                parts.append(",")
            _write(item, parts)
        parts.append("]")
    else:
        raise CanonicalizationError(f"not a JSON value: {type(value).__name__}")


def _sorted_keys(obj: Mapping) -> list[str]:
    for key in obj:
        if not isinstance(key, str):
            raise CanonicalizationError(f"object key is not a string: {key!r}")
    # UTF-16 code unit order; big-endian bytes compare in that order.
    return sorted(obj, key=lambda k: k.encode("utf-16-be", "surrogatepass"))


def _string(text: str) -> str:
    out = ['"']
    for char in text:
        code = ord(char)
        if char in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[char])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        elif 0xD800 <= code <= 0xDFFF:
            raise CanonicalizationError(f"lone surrogate U+{code:04X} in a string")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _number(value: int | float) -> str:
    """ECMAScript Number::toString of the binary64 nearest the value."""
    try:
        number = float(value)
    except OverflowError as exc:
        raise CanonicalizationError(f"number out of binary64 range: {value}") from exc
    if not math.isfinite(number):
        raise CanonicalizationError(f"number is not finite: {value}")
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    # repr gives the shortest decimal that round-trips, as ECMAScript requires.
    mantissa, _, exponent = repr(abs(number)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = whole + fraction
    point = len(whole) + (int(exponent) if exponent else 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    k, n = len(digits), point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    shift = n - 1
    exp = ("+" if shift >= 0 else "-") + str(abs(shift))
    if k == 1:
        return sign + digits + "e" + exp
    return sign + digits[0] + "." + digits[1:] + "e" + exp
