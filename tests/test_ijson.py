"""The I-JSON reader every neuroschema reader shares (``neuroschema.ijson``).

``neuroschema.validate`` reads documents with it, ``nemar.view-digest.v1``
parses declarations with it, and a view's JSON file is read with it
(``json_invalid``). The documents are the real example of
``examples/views``, edited in their text the way an adversarial writer would.
No mocks.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from neuroschema import ijson
from neuroschema.validate import validate_document, validate_file

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "views" / "dataquality-record-nemar-ica.json"
DATA_QUALITY = ROOT / "schema" / "extensions" / "dataQuality.schema.json"
TEXT = EXAMPLE.read_text(encoding="utf-8")


def edited(old: str, new: str) -> str:
    assert TEXT.count(old) >= 1, old
    return TEXT.replace(old, new, 1)


# Each edit is a way the example's text can stop being I-JSON (probes p3, p4b).
REFUSED = {
    "nan_literal": edited('"duration_s": 2', '"duration_s": NaN'),
    "infinity_literal": edited('"start_s": 151.5', '"start_s": Infinity'),
    "number_beyond_binary64": edited('"duration_s": 2', '"duration_s": 1e400'),
    "duplicate_member": edited(
        '"kind": "nemar.signal-window",',
        '"kind": "evil.whatever", "kind": "nemar.signal-window",',
    ),
    "escaped_duplicate_member": edited(
        '"kind": "nemar.signal-window",',
        '"\\u006bind": "evil.whatever", "kind": "nemar.signal-window",',
    ),
    "lone_surrogate": edited('"key": "midsegment"', '"key": "mid\\ud800segment"'),
    "noncharacter": edited('"key": "midsegment"', '"key": "mid\\ufdd0segment"'),
    "nested_65": edited(
        '"level": "record",', '"level": "record", "x": ' + "[" * 64 + "]" * 64 + ","
    ),
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_validate_file_refuses_what_is_not_i_json(name, tmp_path):
    path = tmp_path / f"{name}.json"
    path.write_text(REFUSED[name], encoding="utf-8")
    with pytest.raises(ijson.IJsonError):
        validate_file(path, DATA_QUALITY)


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_the_cli_refuses_what_is_not_i_json(name, tmp_path):
    path = tmp_path / f"{name}.json"
    path.write_text(REFUSED[name], encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "neuroschema.validate",
            str(path),
            "--schema",
            str(DATA_QUALITY),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 2
    assert run.stderr.splitlines()[-1].startswith("ERROR: Invalid JSON")


def test_the_example_is_valid_as_text_and_as_bytes():
    assert validate_file(EXAMPLE, DATA_QUALITY) == []
    assert validate_document(ijson.parse(TEXT.encode()), DATA_QUALITY) == []


def test_a_byte_order_mark_is_refused(tmp_path):
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + TEXT.encode())
    with pytest.raises(ijson.IJsonError, match="byte order mark"):
        validate_file(path, DATA_QUALITY)


def test_utf16_is_refused(tmp_path):
    path = tmp_path / "utf16.json"
    path.write_bytes(TEXT.encode("utf-16"))
    with pytest.raises(ijson.IJsonError, match="not UTF-8"):
        validate_file(path, DATA_QUALITY)


def test_the_file_is_read_as_utf8_whatever_the_locale(tmp_path):
    """The example's micro sign (U+00B5) is UTF-8; under the C locale and with
    UTF-8 mode off, a reader that uses the locale's encoding would misread it
    (probe p4b). The CLI reads bytes and decodes them as UTF-8."""
    assert "µV" in TEXT
    env = os.environ | {
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
    }
    env.pop("PYTHONIOENCODING", None)
    run = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8=0",
            "-m",
            "neuroschema.validate",
            str(EXAMPLE),
            "--schema",
            str(DATA_QUALITY),
        ],
        capture_output=True,
        env=env,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith(b"VALID")


# ── The reader itself ─────────────────────────────────────────────────────


def test_depth_counts_arrays_and_objects_and_skips_strings():
    assert ijson.depth("1") == 0
    assert ijson.depth("[]") == 1
    assert ijson.depth('{"a": [{"b": []}]}') == 4
    assert ijson.depth('["[[[[", "\\"[[["]') == 1


def test_sixty_four_levels_parse_and_sixty_five_do_not():
    assert ijson.nesting(ijson.parse("[" * 64 + "]" * 64)) == 64
    with pytest.raises(ijson.IJsonError, match="64 deep"):
        ijson.parse("[" * 65 + "]" * 65)


def test_deep_nesting_is_refused_before_the_parser_recurses():
    """Nesting far past the interpreter's recursion limit is a refusal, not a
    RecursionError (probe p2: a histogram nested 500 deep)."""
    with pytest.raises(ijson.IJsonError, match="64 deep"):
        ijson.parse("[" * 100_000 + "]" * 100_000)


@pytest.mark.parametrize(
    "text",
    [
        '"\\ud800"',
        '"\\udfff"',
        '{"\\udc00": 1}',
        '"\\ufdd0"',
        '"\\ufdef"',
        '"\\ufffe"',
        '"\\uffff"',
        '"\\ud83f\\udffe"',
        '"\\udbff\\udfff"',
        '"x￾"',
    ],
)
def test_lone_surrogates_and_noncharacters_are_refused(text):
    with pytest.raises(ijson.IJsonError, match=r"lone surrogate|noncharacter"):
        ijson.parse(text)


@pytest.mark.parametrize(
    "text",
    ['"\\ud83d\\ude00"', '"\\ufdcf"', '"\\ufdf0"', '"\\ufffd"', '"\\ud83f\\udffd"'],
)
def test_neighbors_of_the_forbidden_code_points_are_read(text):
    assert isinstance(ijson.parse(text), str)


def test_there_are_66_noncharacters():
    forbidden = [
        c
        for c in range(0x110000)
        if not 0xD800 <= c <= 0xDFFF and ijson.FORBIDDEN.match(chr(c))
    ]
    assert len(forbidden) == 66
    assert forbidden[:2] == [0xFDD0, 0xFDD1]
    assert forbidden[-2:] == [0x10FFFE, 0x10FFFF]


def test_integers_beyond_2_53_read_as_binary64():
    """JSON.parse reads 9007199254740993 as 9007199254740992; so does the reader."""
    value = ijson.parse("[9007199254740993, 9007199254740992, 9007199254740991, 1]")
    assert value == [9007199254740992.0, 9007199254740992.0, 9007199254740991, 1]
    assert isinstance(value[2], int)
    assert ijson.binary64([2**53 + 1, {"n": -(2**53) - 1}]) == [
        2.0**53,
        {"n": -(2.0**53)},
    ]


def test_binary64_refuses_what_has_no_binary64():
    with pytest.raises(ijson.IJsonError):
        ijson.binary64(10**400)
    with pytest.raises(ijson.IJsonError):
        ijson.binary64(float("nan"))


def test_a_bool_is_not_a_number():
    assert ijson.binary64([True, False, None]) == [True, False, None]


def test_validate_document_checks_the_binary64_reading():
    """Two frequencies an exact reader holds distinct and JSON.parse reads as one
    binary64: the document is checked as JSON.parse reads it (probe p9)."""
    document = ijson.parse(TEXT)
    spectrum = next(
        v
        for v in document["recipes"]["nemar-ica"]["views"]
        if v["kind"] == "nemar.spectrum"
    )
    spectrum["parameters"]["initial_maps_hz"] = [9007199254740993, 9007199254740992]
    errors = validate_document(document, DATA_QUALITY)
    assert {e.validator for e in errors} == {"uniqueItems"}


FOUR_MB = 4 * 1024 * 1024
WORST_CASES = {
    # Review r29: an unterminated string of escaped quotes made the old regular
    # expression scan backtrack from every quote, quadratic in the length.
    "unterminated_escaped_quotes": '"' + '\\"' * (FOUR_MB // 2),
    "bracket_pairs": "[" + "[]," * (FOUR_MB // 3) + "]",
    "one_long_string": '{"a": "' + "x" * FOUR_MB + '"}',
    "backslashes": '"' + "\\\\" * (FOUR_MB // 2),
    "quotes": '"' * FOUR_MB,
    "deep": "[" * FOUR_MB,
    "quote_backslash": '"\\' * (FOUR_MB // 2),
}


@pytest.mark.parametrize("name", sorted(WORST_CASES))
def test_the_depth_scan_is_linear(name):
    """A 4 MB text, the cap on bytes, is scanned in well under a second, by one
    pass with an in-string flag (probe r29/ijson_quadratic)."""
    text = WORST_CASES[name]
    started = time.perf_counter()
    ijson.depth(text)
    assert time.perf_counter() - started < 1.0
    started = time.perf_counter()
    with pytest.raises(ijson.IJsonError):
        ijson.parse(text.encode() + b"x")
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('"\\\\"', 0),
        ('["\\\\", "]"]', 1),
        ('["\\"]", [1]]', 2),
        ('{"a\\\\\\"[": [[]]}', 3),
        ('"unterminated [[[', 0),
    ],
)
def test_the_depth_scan_reads_escapes(text, expected):
    assert ijson.depth(text) == expected


def test_the_depth_scan_counts_past_the_limit():
    assert ijson.depth("[" * 100 + "]" * 100) == 100
    assert ijson.depth('["\\\\", ["b"], {"c": [1]}]') == 3


def test_the_view_validator_reads_binary64_too():
    """view_validator() itself checks the binary64 reading, as ajv does, so a
    caller that hands it a parsed declaration gets one verdict (review r29)."""
    from neuroschema.views.models import view_validator

    document = ijson.parse(TEXT)
    spectrum = next(
        v
        for v in document["recipes"]["nemar-ica"]["views"]
        if v["kind"] == "nemar.spectrum"
    )
    assert view_validator().is_valid(spectrum)
    spectrum["parameters"]["initial_maps_hz"] = [9007199254740993, 9007199254740992]
    errors = list(view_validator().iter_errors(spectrum))
    assert [e.validator for e in errors] == ["uniqueItems"]
    spectrum["parameters"]["initial_maps_hz"] = [float("inf")]
    assert [e.validator for e in view_validator().iter_errors(spectrum)] == ["binary64"]


# The vectors files that carry, as data, an input the reader must refuse.
CARRIERS = {
    "views/vectors/kinds-models.v1.json": (
        "histogram_noncharacter_raw and refusal_caption_noncharacter hold U+FFFE"
    ),
    "views/vectors/view-digest.v1.json": "a declaration nested 65 deep",
}
PUBLISHED = sorted(
    p
    for folder in ("schema", "views", "examples")
    for p in (ROOT / folder).rglob("*.json")
)


@pytest.mark.parametrize(
    "path", PUBLISHED, ids=[p.relative_to(ROOT).as_posix() for p in PUBLISHED]
)
def test_every_published_json_file_is_i_json(path):
    """Every schema, montage, vectors file, registry and example reads under
    the I-JSON reader (the montages and sensor vectors of S6b included), but
    the two vectors files whose cases carry the input a reader refuses."""
    name = path.relative_to(ROOT).as_posix()
    if name in CARRIERS:
        with pytest.raises(ijson.IJsonError):
            ijson.parse(path.read_bytes())
    else:
        ijson.parse(path.read_bytes())


def test_the_published_files_include_the_montages_and_sensor_vectors():
    names = {p.relative_to(ROOT).as_posix() for p in PUBLISHED}
    assert {
        "views/montages/GSN128.json",
        "views/montages/PROVENANCE.json",
        "views/vectors/sensor-labels.v1.json",
        "views/vectors/sensor-layout.v1.json",
        "views/registry.json",
    } <= names
    assert set(CARRIERS) <= names


def _script(name: str, monkeypatch):
    """A generator script as a module, registered while it loads (its
    dataclasses look their module up)."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name, writer",
    [("generate_kind_vectors", "_scalars"), ("generate_montages", "render")],
)
def test_the_vector_writers_refuse_what_is_not_finite(name, writer, monkeypatch):
    """The writers of the model vectors, the verdicts and the montages refuse
    NaN and Infinity, which no I-JSON text holds, rather than write them."""
    pytest.importorskip("numpy")
    write = getattr(_script(name, monkeypatch), writer)
    for value in (float("nan"), float("inf"), [1.0, float("-inf")]):
        with pytest.raises(ValueError):
            write(value)
