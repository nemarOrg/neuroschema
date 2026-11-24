"""Internet JSON (I-JSON, RFC 7493) as every neuroschema reader parses it.

One reader for every JSON text neuroschema reads: a document ``neuroschema.validate``
checks, a view declaration ``nemar.view-digest.v1`` digests, and a view's JSON
file (``docs/views.md``, JSON). It refuses, with :class:`IJsonError`:

- bytes that are not strict UTF-8, or that begin with a byte order mark;
- text that is not JSON, including the ``NaN``, ``Infinity`` and ``-Infinity``
  literals Python's ``json`` accepts;
- an object with two members of one name, at any depth, however the names are
  escaped (``"a"`` and ``"\\u0061"`` are one name);
- a number that is not finite as a binary64 (``1e400``, or an integer literal
  beyond binary64 range);
- a string or member name holding a lone surrogate (U+D800 to U+DFFF) or a
  noncharacter (U+FDD0 to U+FDEF, and the last two code points of each plane);
- arrays and objects nested more than :data:`MAX_DEPTH` (64) deep.

Numbers are read as JavaScript's ``JSON.parse`` reads them, the binary64 nearest
the text: an integer literal beyond 2^53 is read as that binary64 (a ``float``),
so a schema check sees the value every other reader sees (:func:`binary64`).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

MAX_DEPTH = 64
# Integers up to 2^53 are exact in binary64 and stay ints.
EXACT = 2**53

# A lone surrogate, or a noncharacter: U+FDD0..U+FDEF and U+xFFFE, U+xFFFF for
# each of the 17 planes (66 code points; Unicode's definition, fixed since 3.1).
_NONCHARACTERS = "﷐-﷯" + "".join(
    f"{chr(plane * 0x10000 + 0xFFFE)}{chr(plane * 0x10000 + 0xFFFF)}"
    for plane in range(17)
)
FORBIDDEN = re.compile(f"[\ud800-\udfff{_NONCHARACTERS}]")
# A JSON string token, escapes included; for the depth scan only.
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)
_BRACKET = re.compile(r"[\[\]{}]")


class IJsonError(ValueError):
    """Text that is not I-JSON, or a value that has no binary64 reading."""


def decode(data: bytes | bytearray | str) -> str:
    """The text of strict UTF-8 bytes with no byte order mark, or the str itself."""
    if isinstance(data, str):
        if data.startswith("﻿"):
            raise IJsonError("a byte order mark")
        return data
    if not isinstance(data, bytes | bytearray):
        raise IJsonError(f"JSON text is str or UTF-8 bytes, not {type(data).__name__}")
    if bytes(data[:3]) == b"\xef\xbb\xbf":
        raise IJsonError("a byte order mark")
    try:
        return bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IJsonError(f"not UTF-8: {exc}") from exc


def depth(text: str) -> int:
    """How deep the text's arrays and objects nest (0 for a scalar).

    String tokens are skipped, so a bracket inside a string does not count. The
    scan runs before the parse, so no parser recurses past :data:`MAX_DEPTH`.
    """
    level = deepest = 0
    for match in _BRACKET.finditer(_STRING.sub('""', text)):
        if match.group() in "[{":
            level += 1
            deepest = max(deepest, level)
        else:
            level -= 1
    return deepest


def parse(data: bytes | bytearray | str, max_depth: int = MAX_DEPTH) -> Any:
    """Parse I-JSON text (module docstring), or raise :class:`IJsonError`."""
    text = decode(data)
    if depth(text) > max_depth:
        raise IJsonError(f"nested more than {max_depth} deep")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_members,
            parse_constant=_refuse_constant,
            parse_float=_finite_float,
            parse_int=_binary64_int,
        )
    except IJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise IJsonError(f"not JSON: {exc}") from exc
    except ValueError as exc:
        # An integer literal longer than Python's int_max_str_digits (4,300):
        # far beyond binary64, where JSON.parse reads Infinity.
        raise IJsonError(f"integer literal too long: {exc}") from exc
    check_strings(value)
    return value


def check_strings(value: Any) -> None:
    """Refuse a lone surrogate or a noncharacter in any string or member name."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            _check_string(item)
        elif isinstance(item, dict):
            for key, member in item.items():
                if isinstance(key, str):
                    _check_string(key)
                stack.append(member)
        elif isinstance(item, list | tuple):
            stack.extend(item)


def _check_string(text: str) -> None:
    found = FORBIDDEN.search(text)
    if found:
        code = ord(found.group())
        kind = "lone surrogate" if 0xD800 <= code <= 0xDFFF else "noncharacter"
        raise IJsonError(f"{kind} U+{code:04X} in a string")


def nesting(value: Any) -> int:
    """How deep a parsed value's lists and dicts nest (0 for a scalar).

    Iterative, so a value nested past the interpreter's recursion limit is
    measured rather than crashing.
    """
    deepest = 0
    stack = [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, dict):
            deepest = max(deepest, level)
            stack.extend((member, level + 1) for member in item.values())
        elif isinstance(item, list | tuple):
            deepest = max(deepest, level)
            stack.extend((member, level + 1) for member in item)
    return deepest


def binary64(value: Any) -> Any:
    """The value as JavaScript's ``JSON.parse`` would read it: every integer
    beyond 2^53 in magnitude becomes the nearest binary64, so a schema check
    (``uniqueItems``, ``maximum``, ``const``) gives one verdict in every engine.
    Raises :class:`IJsonError` for an integer beyond binary64 range or a float
    that is not finite. Nothing else changes; the input is not modified.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return _binary64_int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IJsonError(f"number is not finite: {value}")
        return value
    if isinstance(value, dict):
        return {key: binary64(member) for key, member in value.items()}
    if isinstance(value, list | tuple):
        return [binary64(member) for member in value]
    return value


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise IJsonError(f"duplicate member name {key!r}")
        obj[key] = value
    return obj


def _refuse_constant(literal: str) -> Any:
    raise IJsonError(f"{literal} is not a JSON number")


def _finite_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise IJsonError(f"number is not finite as a binary64: {text[:40]}")
    return number


def _binary64_int(literal: str | int) -> int | float:
    number = int(literal)
    if -EXACT <= number <= EXACT:
        return number
    try:
        return float(number)
    except OverflowError as exc:
        raise IJsonError("integer beyond binary64 range") from exc
