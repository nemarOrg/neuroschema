"""The transform nemar.ic-activity.v1 and the display filter, against the vectors.

``views/vectors/ic-activity.v1.json`` comes from
``scripts/generate_ic_activity_vectors.py``, which writes it from frozen inputs
with the Python reference and holds the reference to scipy. These tests replay
every case through ``neuroschema.views.ic_activity`` and show that each rule of
the specification is one the vectors catch: a renderer that changes it misses
at least one case by more than the parity tolerance. No mocks: each mutation
is a wrong rule built from the reference's own parts, and the real vectors
must notice.

Needs numpy, the ``views`` extra: ``uv run --extra views pytest``.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from neuroschema.views import ic_activity as ia  # noqa: E402
from neuroschema.views import load_registry  # noqa: E402
from neuroschema.views.digest import canonicalize  # noqa: E402
from neuroschema.views.models import view_validator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VECTORS_PATH = ROOT / "views" / "vectors" / "ic-activity.v1.json"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
CASES = VECTORS["cases"]
REFUSALS = VECTORS["refusals"]
FILTERS = VECTORS["filter_cases"]
SPEC = ROOT / "docs" / "views" / "ic-activity.md"
PARITY = VECTORS["tolerance"]["parity"]


def store_of(spec: dict) -> ia.Store:
    return ia.Store(
        labels=spec["labels"],
        units=spec["units"],
        scale=spec["scale"],
        offset=spec["offset"],
        digital=np.array(spec["digital"], dtype=np.int64),
        rate=spec["rate"],
        published_sha256=spec["published_sha256"],
    )


def files_of(case: dict) -> dict[str, bytes]:
    return {k: v["text"].encode("utf-8") for k, v in case["files"].items()}


def run(case: dict) -> ia.Activations:
    window = case["window"]
    return ia.ic_activity(
        case["view"],
        files_of(case),
        store_of(case["store"]),
        window["start"],
        window["count"],
        caps=ia.CAPS | case.get("caps", {}),
        bursts_repaired=case["bursts_repaired"],
    )


def scales(rows) -> list[float]:
    return [max((abs(v) for v in row), default=0.0) for row in rows]


def within(got, expected, scale_rows, tolerance=PARITY) -> bool:
    """Every row within tolerance times its scale."""
    got = np.asarray(got, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    if got.shape != expected.shape:
        return False
    bound = tolerance * np.asarray(scale_rows)[:, None]
    return bool((np.abs(got - expected) <= bound).all())


# ── The vectors replay ────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_cases_replay(case):
    expected = case["expected"]
    result = run(case)
    assert result.state == expected["state"]
    assert result.components == expected["components"]
    assert result.rows == expected["rows"]
    assert result.factors == expected["factors"]
    assert result.shaded == expected["shaded"]
    assert result.notes == expected["notes"]
    assert [float(t) for t in result.time_s] == expected["time_s"]
    scale = scales(expected["activations"])
    assert within(result.activations, expected["activations"], scale, 1e-12)
    assert within(result.filtered, expected["filtered"], scale, 1e-12)


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r["name"] for r in REFUSALS])
def test_refusals_replay(refusal):
    with pytest.raises(ia.IcActivityRefusal) as raised:
        run(refusal)
    assert raised.value.word == refusal["word"]


@pytest.mark.parametrize("case", FILTERS, ids=[c["name"] for c in FILTERS])
def test_filter_cases_replay(case):
    rows = np.array(case["input"], dtype=np.float64)
    assert ia.padding(rows.shape[-1]) == case["padding"]
    got = ia.display_filter(rows, case["rate"], case["highpass_hz"])
    assert within(got, case["expected"], scales(case["input"]), 1e-12)


def test_coefficients_replay():
    for entry in VECTORS["coefficients"]:
        b, a = ia.highpass_coefficients(entry["highpass_hz"], entry["rate"])
        assert np.allclose(b, entry["b"], rtol=0, atol=1e-15)
        assert np.allclose(a, entry["a"], rtol=0, atol=1e-15)
        assert entry["zi"] == [-entry["b"][0], entry["b"][2]]
        assert entry["b"][0] + entry["b"][1] + entry["b"][2] == 0.0


def test_store_checks_replay():
    for check in VECTORS["store_checks"]:
        try:
            got = ia.store_check(check["declared"], check["published"])
        except ia.IcActivityRefusal as exc:
            got = exc.word
        assert got == check["outcome"]


def test_vector_file():
    assert VECTORS["format"] == ia.IC_ACTIVITY == "nemar.ic-activity.v1"
    assert (ROOT / VECTORS["spec"]).resolve() == SPEC
    assert PARITY == 1e-6
    names = [c["name"] for c in [*CASES, *REFUSALS, *FILTERS]]
    assert len(names) == len(set(names))
    transforms = {t["name"]: t for t in load_registry()["transforms"]}
    assert transforms[ia.IC_ACTIVITY] == {
        "name": ia.IC_ACTIVITY,
        "spec": "docs/views/ic-activity.md",
        "vectors": "views/vectors/ic-activity.v1.json",
        "schema": "schema/views/transform.nemar.ic-activity.v1.schema.json",
    }


@pytest.mark.parametrize(
    "case", [*CASES, *REFUSALS], ids=[c["name"] for c in [*CASES, *REFUSALS]]
)
def test_vector_declarations_are_valid(case):
    """Every case and refusal declares a valid view, but a refusal whose word is
    declaration_invalid: the other words are the transform's, never the schema's."""
    invalid = case.get("word") == "declaration_invalid"
    if case["name"] == "order_kind_before_declaration":
        invalid = True  # both faults: the kind's word comes first
    assert view_validator().is_valid(case["view"]) is not invalid


def test_caps_are_only_lowered():
    """A case's caps take the place of registry caps of the same names, lowered."""
    registry = load_registry()["caps"]
    assert registry == ia.CAPS
    assert (
        "CAPS = {"
        not in (ROOT / "src" / "neuroschema" / "views" / "ic_activity.py").read_text()
    )
    overrides = [
        (k, v) for c in [*CASES, *REFUSALS] for k, v in c.get("caps", {}).items()
    ]
    assert {k for k, _v in overrides} == set(registry)
    for name, value in overrides:
        assert 0 < value < registry[name], name


def test_the_cases_cover_both_states_both_matches_and_every_factor():
    states = {c["expected"]["state"] for c in CASES}
    matches = {c["view"]["transform"]["parameters"]["match"] for c in CASES}
    factors = {f for c in CASES for f in c["expected"]["factors"]}
    assert states == {"matches", "not_checked"}
    assert matches == {"store_row", "label"}
    assert factors >= {1.0, 1e3, 1e6}


def test_only_the_shaded_label_is_shaded():
    """The bad segments hold a bad_window row between two bursts; only the
    bursts are shaded, in file order."""
    case = next(c for c in CASES if c["name"] == "shaded_burst_rows")
    location = ia_location(case, "badsegments")
    table = files_of(case)[location].decode()
    assert "bad_window" in table and table.count("burst") == 2
    assert case["expected"]["shaded"] == [
        {"onset": 0.1, "duration": 0.04},
        {"onset": 0.36, "duration": 0.2},
    ]


def test_no_table_is_said_never_silent():
    """A view whose record names no bad-segment table shades nothing and says
    so; one whose table has no row labeled shaded.label shades nothing and says
    so too; one that shades a row carries no note."""
    for case in CASES:
        declared = any(i["role"] == "badsegments" for i in case["view"]["inputs"])
        files = case["view"]["transform"]["parameters"]["shaded"]["files"]
        assert declared is (files is not None), case["name"]
        if not declared:
            expected = ["no_bad_segment_table"]
        else:
            expected = [] if case["expected"]["shaded"] else ["no_shaded_rows"]
        assert case["expected"]["notes"] == expected, case["name"]
    assert any(c["name"] == "no_bad_segment_table" for c in CASES)
    assert any(c["expected"]["notes"] == ["no_shaded_rows"] for c in CASES)


def test_an_unmatched_label_refuses_only_where_bursts_were_repaired():
    """No row labeled shaded.label: refused (label_unmatched) when the record
    says ASR repaired a span, drawn with no_shaded_rows otherwise (probe p7)."""
    refused = {r["name"]: r for r in REFUSALS if r["word"] == "label_unmatched"}
    assert refused and all(r["bursts_repaired"] is True for r in refused.values())
    drawn = [c for c in CASES if c["expected"]["notes"] == ["no_shaded_rows"]]
    assert {c["bursts_repaired"] for c in drawn} == {None, False}


def test_in_step_orders_have_two_fault_vectors():
    """The components file before the bad segments file, and the onset column
    before the duration column, each with two faults of different words."""
    words = {r["name"]: r["word"] for r in REFUSALS}
    assert words["order_components_file_before_segments_file"] == "file_size_mismatch"
    assert words["badsegments_onset_before_duration"] == "cell_not_number"


def ia_location(case: dict, role: str) -> str:
    return next(i for i in case["view"]["inputs"] if i["role"] == role)["file"][
        "location"
    ]


def test_windows_shorter_than_the_padding_are_pinned():
    """Windows of 1 to 11 samples, around the 9-sample padding, are vectors,
    and a window of one sample filters to 0."""
    counts = {len(c["input"][0]) for c in FILTERS}
    assert {1, 2, 3, 5, 9, 10, 11} <= counts
    one = next(c for c in FILTERS if len(c["input"][0]) == 1)
    assert one["expected"] == [[0.0]]
    assert {c["window"]["count"] for c in CASES} >= {1, 2, 9, 10}


# ── The words ─────────────────────────────────────────────────────────────


def _doc_words() -> set[str]:
    """The words of the page's Words table."""
    section = SPEC.read_text().split("\n## Words\n", 1)[1].split("\n## ", 1)[0]
    words: set[str] = set()
    for row in re.findall(r"^\| (`[a-z_]+`(?:, `[a-z_]+`)*) \|", section, re.M):
        words |= set(re.findall(r"`([a-z_]+)`", row))
    return words


def _raised_words() -> set[str]:
    source = (ROOT / "src" / "neuroschema" / "views" / "ic_activity.py").read_text()
    own = set(re.findall(r'IcActivityRefusal\(\s*"([a-z_]+)"', source))
    grammar = {"tsv_encoding", "tsv_line_endings", "tsv_header_repeated", "tsv_ragged"}
    cells = {"cell_not_number", "cell_not_finite"}
    # The floor's tables and the store's rate are read as presets.md says.
    shared = {"duration_not_positive", "rate_invalid"}
    return own | grammar | cells | shared


def test_words_table_matches_the_reference():
    assert _doc_words() == _raised_words()


def test_every_word_has_a_vector():
    assert {r["word"] for r in REFUSALS} == _doc_words()


# ── The vectors catch a renderer that breaks a rule ───────────────────────


def _misses(compute) -> list[str]:
    """Cases whose activations or filtered values a variant misses by more
    than the parity tolerance, or whose word or refusal differs."""
    misses = []
    for case in CASES:
        try:
            raw, filtered = compute(case)
        except ia.IcActivityRefusal:
            misses.append(case["name"])
            continue
        scale = scales(case["expected"]["activations"])
        if not within(raw, case["expected"]["activations"], scale) or not within(
            filtered, case["expected"]["filtered"], scale
        ):
            misses.append(case["name"])
    return misses


def _variant(case, *, factors=None, rows=None, reference=False, filt=None):
    """The reference's own steps, with one of them replaced."""
    view, store = case["view"], store_of(case["store"])
    start, count = case["window"]["start"], case["window"]["count"]
    _header, weights = ia.read_unmixing(
        files_of(case)[view["inputs"][0]["file"]["location"]]
    )
    expected = case["expected"]
    rows = expected["rows"] if rows is None else rows(case)
    factors = expected["factors"] if factors is None else factors(case)
    if reference:
        values = np.array(
            [
                ia.physical(store, r, start, count) * f
                for r, f in zip(rows, factors, strict=True)
            ]
        )
        raw = weights @ (values - values.mean(axis=0, keepdims=True))
    else:
        raw = ia.multiply(weights, store, rows, factors, start, count)
    cutoff = view["parameters"]["display_filter"]["highpass_hz"]
    filtered = (filt or ia.display_filter)(raw, store.rate, cutoff)
    return raw, filtered


def test_the_reference_steps_reproduce_every_case():
    """The variants below change one step; unchanged, they miss nothing."""
    assert _misses(lambda case: _variant(case)) == []


def test_a_renderer_that_references_again_is_caught():
    """Re-referencing is a no-op for a matrix whose rows sum to zero, so the
    vectors hold one whose rows do not."""
    assert _misses(lambda case: _variant(case, reference=True)) == ["rows_not_zero_sum"]


@pytest.mark.parametrize(
    "factors",
    [
        lambda case: [1.0] * len(case["expected"]["factors"]),
        lambda case: [1.0 / f for f in case["expected"]["factors"]],
        lambda case: [f * 1e3 if f != 1.0 else f for f in case["expected"]["factors"]],
    ],
    ids=["factor_omitted", "factor_inverted", "volts_read_as_millivolts"],
)
def test_a_wrong_unit_factor_is_caught(factors):
    assert "archive_label_volts" in _misses(
        lambda case: _variant(case, factors=factors)
    )


def test_matching_by_position_is_caught():
    """Columns matched by label do not follow the store's row order."""

    def by_position(case):
        return list(range(len(case["expected"]["rows"])))

    assert "archive_label_volts" in _misses(
        lambda case: _variant(case, rows=by_position)
    )


def test_matching_by_label_where_rows_are_given_is_caught():
    """With a label twice in the store, the rows decide; by label it refuses."""
    misses = []
    for case in CASES:
        if case["view"]["transform"]["parameters"]["match"] != "store_row":
            continue
        header, _weights = ia.read_unmixing(files_of(case)[ia_unmixing(case)])
        try:
            got = ia.match_rows(header, case["store"]["labels"], "label")
        except ia.IcActivityRefusal:
            misses.append(case["name"])
            continue
        if got != case["expected"]["rows"]:
            misses.append(case["name"])
    assert misses == ["store_row_duplicate_label"]


def ia_unmixing(case: dict) -> str:
    return next(i for i in case["view"]["inputs"] if i["role"] == "unmixing")["file"][
        "location"
    ]


def test_case_insensitive_labels_are_caught():
    refusal = next(r for r in REFUSALS if r["name"] == "label_case")
    header, _ = ia.read_unmixing(files_of(refusal)[ia_unmixing(refusal)])
    labels = refusal["store"]["labels"]
    folded = [label.casefold() for label in labels]
    assert ia.match_rows([h.casefold() for h in header], folded, "label")
    with pytest.raises(ia.IcActivityRefusal):
        ia.match_rows(header, labels, "label")


def _filtfilt(
    *, padding=None, extension="odd", steady=True, backward=True, prewarp=True
):
    """A display filter with one rule changed."""

    def run_filter(series, rate, cutoff):
        b, a = ia.highpass_coefficients(cutoff, rate)
        if not prewarp:
            k = math.pi * cutoff / rate
            norm = 1.0 / (1.0 + ia.SQRT2 * k + k * k)
            b = (norm, -2.0 * norm, norm)
            a = (1.0, 2.0 * (k * k - 1.0) * norm, (1.0 - ia.SQRT2 * k + k * k) * norm)
        x = np.asarray(series, dtype=np.float64)
        n = x.shape[-1]
        p = min(ia.PADDING, n - 1) if padding is None else min(padding, n - 1)
        if p:
            if extension == "odd":
                before = 2.0 * x[..., :1] - x[..., p:0:-1]
                after = 2.0 * x[..., -1:] - x[..., -2 : -(p + 2) : -1]
            elif extension == "even":
                before, after = x[..., p:0:-1], x[..., -2 : -(p + 2) : -1]
            else:
                before = np.repeat(x[..., :1], p, axis=-1)
                after = np.repeat(x[..., -1:], p, axis=-1)
            x = np.concatenate([before, x, after], axis=-1)
        zi = (-b[0], b[2]) if steady else (0.0, 0.0)
        y = ia._lfilter(b, a, x, zi[0] * x[..., 0], zi[1] * x[..., 0])
        if backward:
            y = y[..., ::-1]
            y = ia._lfilter(b, a, y, zi[0] * y[..., 0], zi[1] * y[..., 0])[..., ::-1]
        return y[..., p : p + n]

    return run_filter


def _filter_misses(variant) -> list[str]:
    misses = []
    for case in FILTERS:
        got = variant(np.array(case["input"]), case["rate"], case["highpass_hz"])
        if not within(got, case["expected"], scales(case["input"])):
            misses.append(case["name"])
    return misses


def test_the_unchanged_filter_misses_nothing():
    assert _filter_misses(_filtfilt()) == []


@pytest.mark.parametrize(
    "variant",
    [
        {"padding": 6},
        {"padding": 12},
        {"padding": 8},
        {"extension": "even"},
        {"extension": "constant"},
        {"steady": False},
        {"backward": False},
        {"prewarp": False},
    ],
    ids=lambda v: "-".join(f"{k}={v[k]}" for k in v),
)
def test_a_wrong_filter_rule_is_caught(variant):
    assert _filter_misses(_filtfilt(**variant))
    assert _misses(lambda case: _variant(case, filt=_filtfilt(**variant)))


def test_short_windows_pin_the_padding_rule():
    """A renderer that pads short windows by the full 9 samples (with a
    repeated edge, since there are not 9 to reflect) misses the short cases."""

    def nine_always(series, rate, cutoff):
        x = np.asarray(series, dtype=np.float64)
        n = x.shape[-1]
        if n > ia.PADDING:
            return ia.display_filter(x, rate, cutoff)
        idx = np.clip(np.arange(1, ia.PADDING + 1), 0, n - 1)
        before = 2.0 * x[..., :1] - x[..., idx[::-1]]
        after = 2.0 * x[..., -1:] - x[..., (n - 1 - idx)]
        ext = np.concatenate([before, x, after], axis=-1)
        b, a = ia.highpass_coefficients(cutoff, rate)
        zi = (-b[0], b[2])
        y = ia._lfilter(b, a, ext, zi[0] * ext[..., 0], zi[1] * ext[..., 0])[..., ::-1]
        y = ia._lfilter(b, a, y, zi[0] * y[..., 0], zi[1] * y[..., 0])[..., ::-1]
        return y[..., ia.PADDING : ia.PADDING + n]

    misses = _filter_misses(nine_always)
    assert {"window_2", "window_3", "window_5", "window_9"} <= set(misses)


def test_a_wrong_store_check_is_caught():
    """Refusing when either digest is absent, or drawing a mismatch."""

    def strict(declared, published):
        return "matches" if declared == published else "store_digest_mismatch"

    def lenient(declared, published):
        return "matches" if declared and declared == published else "not_checked"

    for variant in (strict, lenient):
        assert any(
            variant(c["declared"], c["published"]) != c["outcome"]
            for c in VECTORS["store_checks"]
        )


# The specification's order of checks, as the reference's own steps. Each step
# finds what it needs from the case itself (a port that runs it earlier would
# have the same inputs), so a swapped order always yields a word of its own.


def _input_file(case, role):
    entry = next((i for i in case["view"]["inputs"] if i["role"] == role), None)
    return None if entry is None else entry["file"]


def _raw(case, role):
    entry = _input_file(case, role)
    return None if entry is None else files_of(case).get(entry["location"], b"")


def _caps(case):
    return ia.CAPS | case.get("caps", {})


def _header(case):
    first = _raw(case, "unmixing").split(b"\n", 1)[0]
    return first.decode("utf-8", "replace").split("\t")


def _lenient_rows(case):
    """Each column's store row, by the transform's rule, skipping misses."""
    transform = case["view"]["transform"]["parameters"]
    labels = case["store"]["labels"]
    if transform["match"] == "store_row":
        return [r for r in transform["rows"] if 0 <= r < len(labels)]
    return [labels.index(h) for h in _header(case) if h in labels]


def _step_declaration(case):
    ia.check_declaration(case["view"])


def _step_locations(case):
    ia.check_locations(case["view"])


def _step_store(case):
    ia.check_store(case["view"])


def _step_files(case):
    for role in ("unmixing", "components", "badsegments"):
        entry = _input_file(case, role)
        if entry is not None:
            ia.verified(entry, files_of(case), _caps(case))


def _step_digest(case):
    signal = next(i for i in case["view"]["inputs"] if i["role"] == "signal")["store"]
    ia.store_check(signal["content_sha256"], case["store"]["published_sha256"])


def _step_rate(case):
    ia.check_rate(case["store"]["rate"])


def _step_window(case):
    rate = case["store"]["rate"]
    max_window_s = case["view"]["parameters"]["max_window_s"]
    samples = len(case["store"]["digital"][0])
    window = case["window"]
    ia.check_window(window["start"], window["count"], samples, max_window_s, rate)


def _step_matrix(case):
    ia.read_unmixing(_raw(case, "unmixing"), _caps(case))


def _step_components(case):
    rows = max(_raw(case, "unmixing").count(b"\n") - 1, 0)
    ia.read_components(_raw(case, "components"), rows, _caps(case))


def _step_segments(case):
    data = _raw(case, "badsegments")
    label = case["view"]["transform"]["parameters"]["shaded"]["label"]
    shaded = None if data is None else ia.read_shading(data, label, _caps(case))
    ia.check_shaded(shaded, label, case["bursts_repaired"])


def _step_match(case):
    transform = case["view"]["transform"]["parameters"]
    ia.match_rows(
        _header(case),
        case["store"]["labels"],
        transform["match"],
        transform.get("rows"),
        transform.get("columns"),
    )


def _step_units(case):
    unit = case["view"]["transform"]["parameters"]["unit"]
    ia.unit_factors(case["store"]["units"], _lenient_rows(case), unit)


def _step_filter(case):
    cutoff = case["view"]["parameters"]["display_filter"]["highpass_hz"]
    ia.highpass_coefficients(cutoff, case["store"]["rate"])


ORDER = [
    _step_declaration,
    _step_locations,
    _step_store,
    _step_files,
    _step_digest,
    _step_rate,
    _step_window,
    _step_matrix,
    _step_components,
    _step_segments,
    _step_match,
    _step_units,
    _step_filter,
]
# The refusal that holds both faults of each neighboring pair.
PAIRS = [
    "order_declaration_before_locations",
    "order_locations_before_store",
    "order_store_before_files",
    "order_file_before_digest",
    "order_digest_before_rate",
    "order_rate_before_window",
    "order_window_before_matrix",
    "order_matrix_before_components",
    "order_components_before_segments",
    "order_segments_before_match",
    "order_match_before_unit",
    "order_unit_before_filter",
]


def _word(case, order) -> str | None:
    try:
        for step in order:
            step(case)
    except ia.IcActivityRefusal as exc:
        return exc.word
    return None


def test_the_order_of_checks_gives_every_word():
    assert [_word(r, ORDER) for r in REFUSALS] == [r["word"] for r in REFUSALS]


@pytest.mark.parametrize("i", range(len(ORDER) - 1), ids=lambda i: ORDER[i].__name__)
def test_swapping_two_neighboring_checks_is_caught(i):
    """Each neighboring pair has a refusal with both faults, whose word the
    swapped order changes; every step runs on its own inputs, so the swap gives
    a real word, never a missing prerequisite."""
    swapped = [*ORDER[:i], ORDER[i + 1], ORDER[i], *ORDER[i + 2 :]]
    case = next(r for r in REFUSALS if r["name"] == PAIRS[i])
    assert _word(case, [ORDER[i]]) is not None
    assert _word(case, [ORDER[i + 1]]) is not None
    assert _word(case, ORDER) == case["word"]
    assert _word(case, swapped) not in (None, case["word"])


# ── The reference beyond the vectors ──────────────────────────────────────


def test_unknown_matrix_unit_is_refused():
    with pytest.raises(ia.IcActivityRefusal) as raised:
        ia.unit_factors(["uV"], [0], "nV")
    assert raised.value.word == "unit_unknown"


def test_a_window_holds_a_sample():
    with pytest.raises(ValueError, match="at least one sample"):
        ia.display_filter(np.zeros((1, 0)), 250.0, 1.0)


def test_a_window_beyond_the_cap_or_the_recording_is_not_computed():
    case = copy.deepcopy(next(c for c in CASES if c["name"] == "last_window"))
    case["window"]["count"] += 1
    with pytest.raises(ia.IcActivityRefusal) as raised:
        run(case)
    assert raised.value.word == "window_outside_store"
    case["window"].update(start=0, count=1)
    case["view"]["parameters"]["max_window_s"] = 0.001  # 0.25 samples at 250 Hz
    with pytest.raises(ia.IcActivityRefusal) as raised:
        run(case)
    assert raised.value.word == "window_too_long"
    assert ia.max_samples(30, 250.0) == 7500


def test_a_constant_filters_to_zero_exactly():
    out = ia.display_filter(np.full((2, 40), 7.25), 250.0, 1.0)
    assert np.abs(out).max() < 1e-12


def test_the_matrix_reads_numbers_only():
    with pytest.raises(ia.IcActivityRefusal) as raised:
        ia.read_unmixing(b"Fp1\tFp2\n1\tn/a\n")
    assert raised.value.word == "cell_not_number"


DIGESTS = VECTORS["channel_types_digests"]


@pytest.mark.parametrize("case", DIGESTS, ids=[c["name"] for c in DIGESTS])
def test_channel_types_digests_replay(case):
    """RFC 8785, as nemar.view-digest.v1 canonicalizes: the text, then its hash."""
    assert canonicalize({"channel_types": case["channel_types"]}) == (
        case["canonical"].encode("utf-8")
    )
    assert (
        hashlib.sha256(case["canonical"].encode("utf-8")).hexdigest()
        == (case["sha256"])
    )
    assert ia.channel_types_sha256(case["channel_types"]) == case["sha256"]


def test_the_digest_writes_labels_outside_ascii_as_themselves():
    """Fails for Python's ensure_ascii escaping or a final line feed, which a
    TypeScript port of RFC 8785 would not reproduce."""
    case = next(c for c in DIGESTS if c["name"] == "outside_ascii")
    assert "\u00b5" in case["canonical"] and "\\u" not in case["canonical"]
    assert not case["canonical"].endswith("\n")
    escaped = json.dumps(
        {"channel_types": case["channel_types"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    for text in (escaped, escaped + "\n", case["canonical"] + "\n"):
        assert hashlib.sha256(text.encode()).hexdigest() != case["sha256"]


def test_every_declared_channel_types_digest_is_rfc_8785():
    for case in [*CASES, *REFUSALS]:
        given = case["view"]["parameters"]["decomposition_input"]
        assert (
            ia.channel_types_sha256(given["channel_types"])
            == (given["channel_types_sha256"])
        )
    example = json.loads(
        (ROOT / "examples" / "views" / "dataquality-record-nemar-ica.json").read_text()
    )
    view = next(
        v for v in example["recipes"]["nemar-ica"]["views"] if v["key"] == "icactivity"
    )
    given = view["parameters"]["decomposition_input"]
    assert (
        ia.channel_types_sha256(given["channel_types"])
        == (given["channel_types_sha256"])
    )


def test_the_matrix_header_is_the_records_columns():
    header = ["Fp1", "Fp2"]
    assert ia.match_rows(header, header, "label", None, header) == [0, 1]
    with pytest.raises(ia.IcActivityRefusal) as raised:
        ia.match_rows(header, header, "label", None, header[::-1])
    assert raised.value.word == "channel_set_mismatch"


# ── The generator's --check ───────────────────────────────────────────────


def _generator():
    path = ROOT / "scripts" / "generate_ic_activity_vectors.py"
    spec = importlib.util.spec_from_file_location("generate_ic_activity_vectors", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vectors_are_current():
    """The committed vectors are what the generator writes from the frozen
    inputs, within its regeneration tolerance."""
    gen = _generator()
    assert gen.differences(gen.regenerate(), VECTORS) == []


def test_check_tolerates_rounding_and_catches_changes():
    gen = _generator()
    case = copy.deepcopy(next(c for c in CASES if c["name"] == "serving_32"))
    assert gen.differences(case, case) == []
    scale = scales(case["expected"]["activations"])[3]
    moved = copy.deepcopy(case)
    moved["expected"]["filtered"][3][7] += 5e-11 * scale
    assert gen.differences(moved, case) == []
    moved["expected"]["filtered"][3][7] += 2e-10 * scale
    assert len(gen.differences(moved, case)) == 1
    moved = copy.deepcopy(case)
    moved["expected"]["factors"][0] = 1.0000000000000002
    assert gen.differences(moved, case)
    moved = copy.deepcopy(case)
    moved["expected"]["time_s"][1] += 1e-15
    assert gen.differences(moved, case)
    coefficients = copy.deepcopy(VECTORS["coefficients"][0])
    moved = copy.deepcopy(coefficients)
    moved["a"][1] += 1e-15
    assert gen.differences(moved, coefficients) == []
    moved["a"][1] += 1e-9
    assert gen.differences(moved, coefficients)
    refusal = copy.deepcopy(REFUSALS[0])
    assert gen.differences(refusal | {"word": "file_size_mismatch"}, refusal)


INPUTS = json.loads((ROOT / "scripts" / "ic_activity_vector_inputs.json").read_text())


def test_vectors_are_drawn_from_the_frozen_inputs():
    """Each case's stored integers and matrix are the frozen ones, so neither a
    platform's sine nor a random generator can move them."""
    gen = _generator()
    by_name = {c["name"]: c for c in [*CASES, *REFUSALS]}
    serving = by_name["serving_32"]
    assert serving["store"]["digital"] == INPUTS["cases"]["serving_32"]["digital"]
    _header, weights = ia.read_unmixing(files_of(serving)[gen.UNMIXING_AT])
    assert weights.tolist() == INPUTS["cases"]["serving_32"]["weights"]
    eeg = next(c for c in FILTERS if c["name"] == "eeg_250")
    assert eeg["input"] == [INPUTS["filters"]["inputs"]["eeg_1000"]]


def test_generator_reads_the_frozen_inputs(monkeypatch):
    gen = _generator()
    monkeypatch.setattr(gen, "FROZEN", INPUTS)
    stored = gen.frozen("cases", "small", lambda: {"digital": [], "weights": []})
    assert stored == INPUTS["cases"]["small"]
    with pytest.raises(SystemExit, match="--refresh-inputs"):
        gen.frozen("cases", "no_such_case", dict)
    monkeypatch.setattr(gen, "FROZEN", None)
    assert gen.frozen("cases", "small", lambda: {"fresh": True}) == {"fresh": True}


def test_check_refuses_to_refresh_inputs(capsys):
    gen = _generator()
    with pytest.raises(SystemExit):
        gen.main(["--check", "--refresh-inputs"])
    assert "drop --refresh-inputs" in capsys.readouterr().err


def test_the_reference_agrees_with_scipy():
    """scipy's filtfilt and numpy's matrix product hold the reference (the
    vectors group installs scipy; CI runs the generator's --check with it)."""
    pytest.importorskip("scipy")
    assert _generator().against_scipy(VECTORS) == []
