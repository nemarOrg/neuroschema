"""The Python reference renderers against the view vectors.

``views/vectors/sensor-field.v1.json`` and ``sensor-layout.v1.json`` come from
eegprep at a pinned commit (``scripts/generate_view_vectors.py``); these tests
hold ``neuroschema.views.sensor_field`` and ``sensor_layout`` to them, and show
that each rule of the specifications is one the vectors can catch: changing it
in the reference makes at least one case fail. No mocks: a mutation replaces a
specified constant or rule with a wrong one, and the real vectors must notice.

Needs numpy, the ``views`` extra: ``uv run --extra views pytest``.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from neuroschema.views import linalg  # noqa: E402
from neuroschema.views import sensor_field as sf  # noqa: E402
from neuroschema.views import sensor_layout as sl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIELD = json.loads((ROOT / "views" / "vectors" / "sensor-field.v1.json").read_text())
LAYOUT = json.loads((ROOT / "views" / "vectors" / "sensor-layout.v1.json").read_text())
FIELD_CASES = {case["name"]: case for case in FIELD["cases"]}
LAYOUT_CASES = {case["name"]: case for case in LAYOUT["cases"]}
TOL = FIELD["tolerance"]
LTOL = LAYOUT["tolerance"]


def numbers(values) -> np.ndarray:
    return np.array([math.nan if v is None else v for v in values], dtype=float)


def close(a, b, rel: float) -> bool:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return False
    scale = np.maximum(np.abs(a), np.abs(b))
    return bool((np.abs(a - b) <= rel * scale).all())


# ── nemar.sensor-field.v1 ─────────────────────────────────────────────────


def field_mismatches(case: dict) -> list[str]:
    """Where the reference renderer misses a vector case (empty: it matches)."""
    sensors = case["sensors"]
    values = numbers(sensors["value"])
    try:
        if "x" in sensors:
            xyz = np.column_stack([numbers(sensors[axis]) for axis in "xyz"])
            drawn = sf.sensor_field_from_positions(
                xyz,
                case["coordinate_system"],
                values,
                montage=case.get("montage"),
                names=sensors["name"],
            )
        else:
            theta = numbers(sensors["theta_deg"])
            drawn = sf.sensor_field(theta, numbers(sensors["radius"]), values)
    except (sf.SensorFieldRefusal, sl.SensorLayoutRefusal) as exc:
        return [] if case.get("refused") == exc.word else [f"refused {exc.word}"]
    if "refused" in case:
        return [f"drew a map; the vector refuses it ({case['refused']})"]
    expected = case["expected"]
    problems = []
    if "layout" in expected:
        positions = {axis: sensors[axis] for axis in ("name", "x", "y", "z")}
        projected = case | {"positions": positions, "expected": expected["layout"]}
        problems += [f"layout {p}" for p in layout_mismatches(projected)]
    z = np.array([numbers(row) for row in expected["z"]])
    if drawn.z.shape != z.shape:
        return [f"grid {drawn.z.shape}, not {z.shape}"]
    if not np.array_equal(np.isnan(drawn.z), np.isnan(z)):
        problems.append("mask")
    cells = z[~np.isnan(z)]
    low, high = cells.min(), cells.max()
    magnitude = float(np.abs(cells).max())
    bound = (
        TOL["cells_relative_to_range"] * (high - low)
        + TOL["cells_relative_to_magnitude"] * magnitude
    )
    both = ~np.isnan(z) & ~np.isnan(drawn.z)
    if not (np.abs(drawn.z[both] - z[both]) <= bound).all():
        problems.append("cells")
    geometry = TOL["geometry_relative"]
    for name in ("plotrad", "intrad", "squeezefac"):
        if not close(getattr(drawn, name), expected[name], geometry):
            problems.append(name)
    for axis in ("x", "y"):
        if not close(getattr(drawn, axis), numbers(expected[axis]), geometry):
            problems.append(f"grid {axis}")
    for name in ("limits", "color_axis"):
        for choice, pair in expected[name].items():
            got = getattr(drawn, name)[choice]
            if not (np.abs(np.subtract(got, pair)) <= bound).all():
                problems.append(f"{name} {choice}")
    contours = expected["contours"]
    if (
        len(drawn.contours) != len(contours)
        or not (np.abs(np.subtract(drawn.contours, contours)) <= bound).all()
    ):
        problems.append("contours")
    if list(drawn.notes) != expected["notes"]:
        problems.append("notes")
    if not close(drawn.value_range, expected["value_range"], geometry):
        problems.append("value range")
    head = expected["head"]
    if not close(drawn.head.radius, head["radius"], geometry):
        problems.append("head radius")
    for part in ("nose", "right_ear", "left_ear"):
        if not close(getattr(drawn.head, part), head[part], geometry):
            problems.append(f"head {part}")
    if list(drawn.plotted) != expected["plotted"]:
        problems.append("plotted")
    if list(drawn.interpolated) != expected["interpolated"]:
        problems.append("interpolated")
    if [list(group) for group in drawn.merged.values()] != expected["merged"]:
        problems.append("merged")
    return problems


@pytest.mark.parametrize("case", FIELD["cases"], ids=list(FIELD_CASES))
def test_sensor_field_vectors(case):
    assert field_mismatches(case) == []


def test_sensor_field_vector_file():
    assert FIELD["format"] == sf.SENSOR_FIELD
    assert FIELD["grid_size"] == sf.GRID_SIZE
    assert (ROOT / FIELD["spec"]).is_file()
    assert FIELD["reference"]["commit"] == LAYOUT["reference"]["commit"]
    words = {c["refused"] for c in FIELD["cases"] if "refused" in c}
    assert words == {
        "too_few_sensors",
        "head_outside_grid",
        "interpolation_failed",
        "frame_unknown",
        "positions_flat",
    }


def test_vectors_project_positions_to_a_map():
    drawn = [c for c in FIELD["cases"] if "x" in c["sensors"] and "expected" in c]
    assert {c.get("montage") for c in drawn} == {
        None,
        "GSN-HydroCel-32",
        "standard_1005",
    }


def test_vectors_cover_the_sizes_in_the_plan():
    counts = {len(c["sensors"]["name"]) for c in FIELD["cases"]}
    assert {32, 64, 128, 256} <= counts


def test_exact_duplicates_pseudo_inverse_equals_merge_then_lu():
    """The fallback eegprep intends for duplicates (pinv of G with g(0) = 0)
    draws the map the merge rule draws."""
    case = FIELD_CASES["exact_duplicates"]
    sensors = case["sensors"]
    theta, radius = numbers(sensors["theta_deg"]), numbers(sensors["radius"])
    values = numbers(sensors["value"])
    x, y = sf.planar(theta, radius)
    plotrad = max(min(1.0, radius.max() * 1.02), 0.5)
    squeeze = 0.5 / plotrad
    px, py = x * squeeze, y * squeeze
    g = sf.green(np.hypot(px[:, None] - px[None, :], py[:, None] - py[None, :]))
    assert np.linalg.matrix_rank(g) < len(g), "duplicates make G singular"
    groups = sf.merge(x, y, list(range(len(values))))
    m = sf.center(np.array([sf.mean(values, group) for group in groups.values()]))
    w = np.linalg.pinv(g) @ (values - m)
    expected = case["expected"]
    qx, qy = np.meshgrid(numbers(expected["x"]), numbers(expected["y"]), indexing="ij")
    z = m + sf.green(np.hypot(qx[:, :, None] - px, qy[:, :, None] - py)) @ w
    reference = np.array([numbers(row) for row in expected["z"]])
    inside = ~np.isnan(reference)
    span = reference[inside].max() - reference[inside].min()
    assert np.abs(z[inside] - reference[inside]).max() <= 1e-6 * span
    assert expected["merged"] == [[4, 32, 33], [17, 34]]


def test_eegprep_quirks_are_recorded():
    """The vectors record what eegprep at the pin does with the raw inputs."""
    duplicates = FIELD_CASES["exact_duplicates"]["expected"]
    assert duplicates["eegprep_unmerged_finite_cells"] == 0
    assert FIELD_CASES["nan_values"]["expected"]["eegprep_raw_agrees"] is False


def _abs_square(x, y, intrad):
    return (np.abs(x) <= intrad) & (np.abs(y) <= intrad)


def _absmax_from_max(z):
    cells = z[~np.isnan(z)]
    return {"absmax": (-cells.max(), cells.max()), "minmax": (cells.min(), cells.max())}


_HEAD = sf.head_outline  # the reference's, before a mutation replaces it


def _head_unsqueezed(squeezefac):
    return sf.Head(0.5, sf.NOSE, sf.RIGHT_EAR, tuple((x, -y) for x, y in sf.RIGHT_EAR))


def _head_at_the_mask(squeezefac):
    head = _HEAD(squeezefac)
    return sf.Head(0.5, head.nose, head.right_ear, head.left_ear)


def _ears_swapped(squeezefac):
    head = _HEAD(squeezefac)
    return sf.Head(head.radius, head.nose, head.left_ear, head.right_ear)


def _eegprep_nose(squeezefac):
    """eegprep's triangle in place of EEGLAB's nose."""
    head = _HEAD(squeezefac)
    r, w = 0.5 * squeezefac, 0.08 * squeezefac
    nose = ((r, w), (r + 0.06 * squeezefac, 0.0), (r, -w))
    return sf.Head(head.radius, nose, head.right_ear, head.left_ear)


def _eeglab_axis(pair, rule):
    """EEGLAB's caxis for every choice: 5% of each limit's magnitude away from
    zero (topoplot.m:1248-1250), the rule this page keeps for absmax only."""
    return tuple(v + np.sign(v) * sf.COLOR_MARGIN * abs(v) for v in pair)


def _mean_is_first(values, members):
    return float(values[members[0]])


def _no_pivoting(a, b, *, tiny=None):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    with np.errstate(all="ignore"):
        for k in range(len(b)):
            factors = a[k + 1 :, k] / a[k, k]
            a[k + 1 :, k + 1 :] -= np.outer(factors, a[k, k + 1 :])
            b[k + 1 :] -= factors * b[k]
        w = np.empty(len(b))
        for k in range(len(b) - 1, -1, -1):
            w[k] = (b[k] - a[k, k + 1 :] @ w[k + 1 :]) / a[k, k]
    return w


FIELD_MUTATIONS = {
    "radius margin 1.02 -> 1.0": ("RADIUS_MARGIN", 1.0),
    "grid 67 -> 66": ("GRID_SIZE", 66),
    "merge distance 1e-3 -> 0": ("MERGE_DISTANCE", 0.0),
    "merge distance 1e-3 -> 2e-3": ("MERGE_DISTANCE", 2e-3),
    "contours 6 -> 5": ("CONTOUR_COUNT", 5),
    "contours on a flat field": ("is_flat", lambda values: False),
    "head not squeezed": ("head_outline", _head_unsqueezed),
    "head circle at the mask": ("head_outline", _head_at_the_mask),
    "ears swapped": ("head_outline", _ears_swapped),
    "eegprep's nose": ("head_outline", _eegprep_nose),
    "fewest sensors 8 -> 7": ("MIN_SENSORS", 7),
    "fewest sensors 8 -> 9": ("MIN_SENSORS", 9),
    "fewest sensors 8 -> 3 (the old minimum)": ("MIN_SENSORS", 3),
    "color margin 5% -> 0": ("COLOR_MARGIN", 0.0),
    "minmax margin by magnitude (EEGLAB)": ("color_axis", _eeglab_axis),
    "square with abs()": ("in_square", _abs_square),
    "mask radius 0.5 -> 0.49": (
        "outside_head",
        lambda qx, qy: np.sqrt(qx * qx + qy * qy) > 0.49,
    ),
    "mask keeps the circle open": (
        "outside_head",
        lambda qx, qy: np.sqrt(qx * qx + qy * qy) >= 0.5,
    ),
    "absmax from the largest value": ("limits", _absmax_from_max),
    "merged value is the first": ("mean", _mean_is_first),
    "LU without pivoting": ("lu_solve", _no_pivoting),
    "plotted strictly inside plotrad": ("is_plotted", lambda r, plotrad: r < plotrad),
    "square strictly inside intrad": (
        "in_square",
        lambda x, y, intrad: (x < intrad) & (y < intrad),
    ),
    "merge strictly within the distance": (
        "within_merge",
        lambda d: d < sf.MERGE_DISTANCE,
    ),
}


@pytest.mark.parametrize("mutation", list(FIELD_MUTATIONS))
def test_sensor_field_vectors_catch_a_mutation(monkeypatch, mutation):
    name, value = FIELD_MUTATIONS[mutation]
    monkeypatch.setattr(sf, name, value)
    assert any(field_mismatches(case) for case in FIELD["cases"]), mutation


def test_radii_from_the_kept_sensors_are_caught(monkeypatch):
    """The radii come from every usable sensor; taking them from the sensors
    the merge keeps changes the merged_outermost case."""
    kept: list[int] = []
    merge = sf.merge

    def recording_merge(x, y, rows):
        groups = merge(x, y, rows)
        kept[:] = list(groups)
        return groups

    monkeypatch.setattr(sf, "merge", recording_merge)
    monkeypatch.setattr(sf, "outermost", lambda radius, usable: radius[kept].max())
    assert field_mismatches(FIELD_CASES["merged_outermost"])
    assert not field_mismatches(FIELD_CASES["montage_32"])


def test_a_map_needs_as_many_sensors_as_names_need():
    """The scalp map's minimum is sensor-labels' minimum of channels and matches."""
    from neuroschema.views import sensor_labels

    assert sf.MIN_SENSORS == sensor_labels.MIN_CHANNELS == sensor_labels.MIN_MATCHED
    assert len(FIELD_CASES["eight_sensors"]["expected"]["interpolated"]) == 8
    assert FIELD_CASES["seven_sensors"]["refused"] == "too_few_sensors"
    assert FIELD_CASES["merged_to_seven"]["refused"] == "too_few_sensors"


def test_refusals_without_usable_sensors():
    with pytest.raises(sf.SensorFieldRefusal) as raised:
        sf.sensor_field([math.nan, 10.0], [0.3, math.inf], [1.0, 2.0])
    assert raised.value.word == "too_few_sensors"


def test_inputs_are_equal_length_vectors():
    with pytest.raises(ValueError, match="equal-length"):
        sf.sensor_field([0.0, 1.0], [0.3], [1.0, 2.0])


@pytest.mark.parametrize(
    ("low", "high"), [(-0.5, 0.5), (-0.6123, 0.5), (-0.5, 0.77), (-3.5e9, 0.5)]
)
def test_grid_axis_is_numpy_linspace(low, high):
    assert np.array_equal(sf.grid_axis(low, high), np.linspace(low, high, 67))


def test_color_axis_of_zero_is_zero():
    for rule in ("absmax", "minmax"):
        low, high = sf.color_axis((-0.0, 0.0), rule)
        assert (low, high) == (0.0, 0.0)
        assert math.copysign(1.0, low) == 1.0


def test_the_head_sits_at_the_squeezed_equator():
    """The head circle is the layout's equator (radius 0.5) squeezed like the
    sensors, so with sensors below it the map's skirt reaches past the head."""
    for case in DRAWN:
        expected = case["expected"]
        squeeze = expected["squeezefac"]
        assert math.isclose(expected["head"]["radius"], 0.5 * squeeze, rel_tol=1e-15)
        tip = max(expected["head"]["nose"], key=lambda point: point[0])
        assert math.isclose(tip[0], 0.575 * squeeze, rel_tol=1e-12) and tip[1] == 0
        right, left = expected["head"]["right_ear"], expected["head"]["left_ear"]
        assert all(y > 0 for _x, y in right) and all(y < 0 for _x, y in left)
        assert [[x, -y] for x, y in right] == left
    outside = FIELD_CASES["outside"]["expected"]
    assert outside["plotrad"] > 0.5 and outside["head"]["radius"] < 0.5


def test_a_flat_field_is_drawn_at_its_value():
    """Equal values would ripple through the spline; a flat field is drawn as
    the value itself, in one color, with no contours and the note flat_field."""
    case = FIELD_CASES["constant_values"]
    assert len(set(case["sensors"]["value"])) == 1
    expected = case["expected"]
    assert set(_drawn_cells(case)) == {2.5}
    assert expected["limits"] == {"absmax": [-2.5, 2.5], "minmax": [2.5, 2.5]}
    assert expected["color_axis"] == {"absmax": [-2.625, 2.625], "minmax": [2.5, 2.5]}
    assert expected["contours"] == []
    flat = {c["name"] for c in DRAWN if c["expected"]["notes"] == [sf.FLAT_FIELD]}
    assert flat == {
        "constant_values",
        "zero_map",
        "flat_nan_value",
        "flat_no_place",
        "flat_merge_group",
        "flat_huge_duplicate_pair",
        "flat_minus_zero",
    }
    allowed = ([], [sf.FLAT_FIELD], [sf.NEAR_FLAT_NOTE])
    assert all(c["expected"]["notes"] in allowed for c in DRAWN)
    assert sf.is_flat(np.array([2.5, 2.5, 2.5]))
    assert not sf.is_flat(np.array([2.5, 2.5, 2.5000000000000004]))


@pytest.mark.parametrize("group", [1, 2, 3, 4])
@pytest.mark.parametrize("count", [8, 10, 12, 15, 19, 32])
@pytest.mark.parametrize(
    "value", [2.5, 0.1, 0.7, -110.0, 1e-300, 1e300, 1.5e308, -1.5e308, -0.0]
)
def test_a_flat_field_draws_exactly_its_value(value, count, group):
    """Equal values have deviations of exactly 0 from their mean, as the spec
    computes it (the merge's mean too), so every cell is the value itself, with
    no special case. A mean summed and then divided would not be: three 0.1s
    summed and divided by 3 are 0.10000000000000002, and two of 1.5e308 sum to
    infinity and would refuse a map that is flat."""
    case = FIELD_CASES["montage_32"]["sensors"]
    theta = numbers(case["theta_deg"])[:count]
    radius = numbers(case["radius"])[:count]
    theta = np.concatenate([theta, np.repeat(theta[5], group - 1)])
    radius = np.concatenate([radius, np.repeat(radius[5], group - 1)])
    drawn = sf.sensor_field(theta, radius, np.full(len(theta), value))
    cells = drawn.z[~np.isnan(drawn.z)]
    assert (cells == value).all()
    if value == 0:
        assert not np.signbit(cells).any(), "never -0"
    assert drawn.contours == () and drawn.notes == (sf.FLAT_FIELD,)
    if group > 1:
        assert next(iter(drawn.merged.values()))[0] == 5


@pytest.mark.parametrize("offset", [30.0, -110.0, 1e3])
def test_a_constant_offset_moves_the_map_and_nothing_else(offset):
    """The map of v + C is the map of v, plus C: the spline's ripple of a
    constant, which EEGLAB draws, is gone."""
    case = FIELD_CASES["montage_32"]["sensors"]
    theta, radius = numbers(case["theta_deg"]), numbers(case["radius"])
    values = numbers(case["value"])
    base = sf.sensor_field(theta, radius, values)
    moved = sf.sensor_field(theta, radius, values + offset)
    inside = ~np.isnan(base.z)
    span = np.ptp(base.z[inside])
    bound = 1e-9 * span + 1e-12 * abs(offset)
    assert np.abs(moved.z[inside] - offset - base.z[inside]).max() <= bound


def _variant(func, old, new):
    """``func`` with one line of its source replaced: a wrong rule to plant."""
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(func))
    assert old in source, old
    namespace = dict(func.__globals__)
    exec(source.replace(old, new), namespace)
    return namespace[func.__name__]


FLAT_RULES = {
    "flat within a relative 1e-6": (
        "flat = is_flat(values[rows])",
        "flat = bool(np.ptp(values[rows]) <= 1e-6 * np.abs(values[rows]).max())",
    ),
    "flat over every finite value, placed or not": (
        "flat = is_flat(values[rows])",
        "flat = is_flat(values[np.isfinite(values)])",
    ),
    "flat over the interpolated values": (
        "flat = is_flat(values[rows])",
        "flat = is_flat(v)",
    ),
    "raw values interpolated, as EEGLAB does": ("m = center(v)", "m = 0.0"),
    "no near-flat field": (
        "near_flat = not flat and is_near_flat(values[rows])",
        "near_flat = False",
    ),
    "near flat within 1e-7": (
        "near_flat = not flat and is_near_flat(values[rows])",
        "near_flat = not flat and bool(np.ptp(values[rows]) "
        "<= 1e-7 * np.abs(values[rows]).max())",
    ),
}


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
@pytest.mark.parametrize("rule", list(FLAT_RULES))
def test_the_vectors_catch_a_wrong_flat_or_offset_rule(monkeypatch, rule):
    old, new = FLAT_RULES[rule]
    monkeypatch.setattr(sf, "sensor_field", _variant(sf.sensor_field, old, new))
    assert any(field_mismatches(case) for case in FIELD["cases"]), rule


def test_a_near_flat_field_is_one_color_at_its_mean():
    """Within 1e-9 of their magnitude, the values' map would be the spline of
    their last digits stretched over the color axis: it is one color at the
    mean, with no contours and the note near_flat. Just above the bound, the
    map is drawn as any other."""
    for name in ("near_flat_one_ulp", "near_flat_one_nano_db"):
        expected = FIELD_CASES[name]["expected"]
        assert expected["notes"] == [sf.NEAR_FLAT_NOTE], name
        assert len(set(_drawn_cells(FIELD_CASES[name]))) == 1, name
        assert expected["contours"] == [], name
        values = numbers(FIELD_CASES[name]["sensors"]["value"])
        assert 0 < expected["value_range"] <= sf.NEAR_FLAT * np.abs(values).max()
    above = FIELD_CASES["near_flat_above_threshold"]
    values = numbers(above["sensors"]["value"])
    assert above["expected"]["value_range"] > sf.NEAR_FLAT * np.abs(values).max()
    assert above["expected"]["notes"] == [] and len(above["expected"]["contours"]) == 6
    assert sf.is_near_flat(np.array([30.0, 30.0 + 1e-9]))
    assert not sf.is_near_flat(np.array([30.0, 30.0 + 4e-8]))
    assert not sf.is_near_flat(np.array([30.0, 30.0])), "flat is not near flat"
    assert not sf.is_near_flat(np.zeros(3))


def test_a_flat_field_note_reads_as_its_caption():
    """The note's caption, as sensor-field.md's Notes table gives it."""
    section = (ROOT / FIELD["spec"]).read_text().split("\n## Refusals\n", 1)[1]
    notes = re.findall(r"^\| `([a-z_]+)` \| [^|]+ \| ([^|]+) \|", section, re.M)
    captions = [(word, caption.strip()) for word, caption in notes]
    assert ("flat_field", "all sensors have the same value") in captions
    assert ("near_flat", "all sensors are within <range> of each other") in captions


def test_color_axis_rules():
    """absmax: 5% of each magnitude (EEGLAB's caxis); minmax: 5% of the range."""
    assert sf.color_axis((-4.0, 4.0), "absmax") == (-4.2, 4.2)
    assert sf.color_axis((-2.0, 4.0), "minmax") == (-2.3, 4.3)
    assert sf.color_axis((10.0, 30.0), "minmax") == (9.0, 31.0)
    assert sf.color_axis((-30.0, -10.0), "minmax") == (-31.0, -9.0)
    assert sf.color_axis((2.5, 2.5), "minmax") == (2.5, 2.5)


def _drawn_cells(case):
    z = np.array([numbers(row) for row in case["expected"]["z"]])
    return z[~np.isnan(z)]


DRAWN = [c for c in FIELD["cases"] if "expected" in c]


@pytest.mark.parametrize("case", DRAWN, ids=[c["name"] for c in DRAWN])
def test_every_cell_lies_inside_both_color_axes(case):
    """No cell of a drawn map takes the color at an end of the axis."""
    cells = _drawn_cells(case)
    for rule, (low, high) in case["expected"]["color_axis"].items():
        assert low <= cells.min() and cells.max() <= high, rule


@pytest.mark.parametrize("name", ["one_sign_positive_db", "one_sign_negative_db"])
def test_eeglab_magnitude_rule_would_clip_a_one_sign_map(name):
    """The divergence from EEGLAB, shown on the vectors: on a map of one sign
    the magnitude rule moves the limit nearer zero inward, past cells."""
    case = FIELD_CASES[name]
    cells = _drawn_cells(case)
    assert cells.min() > 0 or cells.max() < 0, "a map of one sign"
    low, high = _eeglab_axis(case["expected"]["limits"]["minmax"], "minmax")
    assert cells.min() < low or cells.max() > high


# ── The LU solver ─────────────────────────────────────────────────────────


def test_lu_solve_matches_lapack():
    rng = np.random.default_rng(7)
    a = rng.normal(size=(40, 40))
    b = rng.normal(size=40)
    assert np.allclose(linalg.lu_solve(a, b), np.linalg.solve(a, b), rtol=1e-12)


def test_lu_solve_pivots():
    """A zero on the diagonal needs a row swap; without it the solve divides by 0."""
    a = np.array([[0.0, 2.0], [3.0, 1.0]])
    assert np.allclose(linalg.lu_solve(a, np.array([4.0, 5.0])), [1.0, 2.0])


def test_lu_solve_threshold():
    singular = np.array([[1.0, 2.0], [2.0, 4.0]])
    with pytest.raises(linalg.SingularMatrix):
        linalg.lu_solve(singular, np.array([1.0, 2.0]), tiny=0.0)
    with pytest.raises(linalg.SingularMatrix):
        linalg.lu_solve(np.array([[1e-12]]), np.array([1.0]), tiny=1e-10)
    with pytest.raises(linalg.SingularMatrix):
        linalg.lu_solve(np.array([[math.nan]]), np.array([1.0]), tiny=1e-10)
    assert linalg.lu_solve(np.array([[1e-12]]), np.array([1.0]), tiny=1e-13) == 1e12


def test_lu_solve_without_threshold_lets_a_zero_pivot_divide():
    w = linalg.lu_solve(np.array([[1.0, 2.0], [2.0, 4.0]]), np.array([1.0, 3.0]))
    assert not np.isfinite(w).all()


def test_lu_solve_shapes():
    with pytest.raises(ValueError, match="2-by-2"):
        linalg.lu_solve(np.ones((2, 3)), np.ones(2))


# ── nemar.sensor-layout.v1 ────────────────────────────────────────────────


def layout_mismatches(case: dict, frame: str | None = None) -> list[str]:
    """Where the reference transform misses a vector case (empty: it matches)."""
    positions = case["positions"]
    xyz = np.column_stack([numbers(positions[axis]) for axis in "xyz"])
    frame = frame or case["coordinate_system"]
    montage = case.get("montage")
    try:
        layout = sl.sensor_layout(
            xyz,
            frame,
            montage=montage,
            names=positions.get("name"),
            sensor_types=positions.get("sensor_type"),
        )
    except sl.SensorLayoutRefusal as exc:
        if case.get("refused") != exc.word:
            return [f"refused {exc.word}"]
        return bounds_mismatches(
            case, exc.singular_ratio, exc.radius_ratio, exc.dilution, exc.stability
        )
    if "refused" in case:
        return [f"gave a layout; the vector refuses it ({case['refused']})"]
    expected = case["expected"]
    theta, radius = numbers(expected["theta_deg"]), numbers(expected["radius"])
    problems = bounds_mismatches(
        case,
        layout.singular_ratio,
        layout.radius_ratio,
        layout.dilution,
        layout.stability,
    )
    if not np.array_equal(np.isnan(layout.radius), np.isnan(radius)):
        return ["rows without a position"]
    if layout.center_method != expected["center_method"]:
        problems.append("center method")
    finite = np.isfinite(xyz).all(axis=1)
    als = sl.to_als(xyz[finite], frame, montage)
    centered = als - als.sum(axis=0) / len(als)
    scale = np.sqrt((centered * centered).sum(axis=1)).max()
    center_bound = LTOL["center_relative_to_scale"] * scale
    if not (
        np.abs(np.subtract(layout.center, expected["center"])) <= center_bound
    ).all():
        problems.append("center")
    rows = ~np.isnan(radius)
    if not (np.abs(layout.radius[rows] - radius[rows]) <= LTOL["radius"]).all():
        problems.append("radius")
    got = np.deg2rad(layout.theta_deg[rows])
    want = np.deg2rad(theta[rows])
    r = radius[rows]
    gap = np.hypot(
        np.cos(got) * layout.radius[rows] - np.cos(want) * r,
        np.sin(got) * layout.radius[rows] - np.sin(want) * r,
    )
    if not (gap <= LTOL["planar"]).all():
        problems.append("planar")
    return problems


def bounds_mismatches(
    case, singular_ratio, radius_ratio, dilution, stability
) -> list[str]:
    """A measured case's four measures, within tolerance.bounds_absolute (a
    template case has none)."""
    bounds = case.get("bounds")
    if bounds is None:
        reached = (singular_ratio, radius_ratio, dilution, stability)
        return [] if all(v is None for v in reached) else ["bounds"]
    problems = []
    for name, got in (
        ("singular_ratio", singular_ratio),
        ("radius_ratio", radius_ratio),
        ("dilution", dilution),
        ("stability", stability),
    ):
        want = bounds[name]
        if (want is None) != (got is None) or (
            want is not None and abs(got - want) > LTOL["bounds_absolute"]
        ):
            problems.append(f"bounds {name}")
    return problems


@pytest.mark.parametrize("case", LAYOUT["cases"], ids=list(LAYOUT_CASES))
def test_sensor_layout_vectors(case):
    assert layout_mismatches(case) == []


def test_sensor_layout_vector_file():
    assert LAYOUT["format"] == sl.SENSOR_LAYOUT
    assert (ROOT / LAYOUT["spec"]).is_file()
    assert "147b46d7" in LAYOUT["reference"]["frames"]


LAYOUT_SPEC = (ROOT / "docs" / "views" / "sensor-layout.md").read_text(encoding="utf-8")


def test_spec_names_every_frame_and_bound():
    """The normative page lists every frame by its full name (no ranges), the
    three words, and each bound."""
    for frame in sorted(sl.ALS_FRAMES | sl.RAS_FRAMES):
        assert f"`{frame}`" in LAYOUT_SPEC, frame
    for word in ("frame_unknown", "positions_flat", "positions_partial"):
        assert f"`{word}`" in LAYOUT_SPEC, word
    phrases = ("`\u03c33 < 0.05 * \u03c31`", "`rho > 3`", "`D > 4.5`", "`L > 0.12`")
    for phrase in (*phrases, "(0, 0, 0)"):
        assert phrase in LAYOUT_SPEC, phrase
    assert (sl.FLAT_RATIO, sl.RADIUS_RATIO) == (0.05, 3.0)
    assert (sl.PARTIAL_DILUTION, sl.PARTIAL_SHIFT) == (4.5, 0.12)


def test_frame_table_is_the_vectors():
    assert set(LAYOUT["frames"]["ALS"]) == sl.ALS_FRAMES
    assert set(LAYOUT["frames"]["RAS"]) == sl.RAS_FRAMES
    assert LAYOUT["frames"]["aliases"] == sl.FRAME_ALIASES
    assert "enums.yaml" in LAYOUT["reference"]["frame_names"]
    assert not sl.ALS_FRAMES & sl.RAS_FRAMES
    assert LAYOUT["frames"]["template"] == {
        "coordinate_system": "n/a",
        "orientation": "RAS",
    }


@pytest.mark.parametrize(
    ("coordinate_system", "montage"),
    [("n/a", None), ("n/a", ""), ("Other", "GSN-HydroCel-32"), ("EEGLAB", "x")],
)
def test_template_positions_need_n_a_and_a_montage(coordinate_system, montage):
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.orientation(coordinate_system, montage)
    assert raised.value.word == "frame_unknown"


def test_template_positions_are_ras():
    assert sl.orientation("n/a", "standard_1005") == "RAS"


def test_the_schema_enum_spelling_with_the_appendix_as_an_alias():
    """BIDS's schema enum spells MNI152NLin6Asym and its appendix MNI152NLin6ASym:
    the table holds the enum's spelling, and the appendix's is read as it."""
    assert "MNI152NLin6Asym" in sl.RAS_FRAMES
    assert "MNI152NLin6ASym" not in sl.RAS_FRAMES | sl.ALS_FRAMES
    for alias, name in sl.FRAME_ALIASES.items():
        assert name in sl.RAS_FRAMES | sl.ALS_FRAMES
        assert sl.orientation(alias) == sl.orientation(name)
        case = LAYOUT_CASES[f"alias_{alias}"]
        assert case["expected"] == LAYOUT_CASES["frame_ras"]["expected"]
        assert LAYOUT_CASES[f"alias_{alias}_lowercase"]["refused"] == "frame_unknown"


@pytest.mark.parametrize("frame", LAYOUT["frames"]["ALS"])
def test_every_als_name_keeps_the_frame(frame):
    assert layout_mismatches(LAYOUT_CASES["frame_als"], frame) == []


@pytest.mark.parametrize("frame", LAYOUT["frames"]["RAS"])
def test_every_ras_name_rotates_the_frame(frame):
    assert layout_mismatches(LAYOUT_CASES["frame_ras"], frame) == []


def cart2topo_mismatches() -> list[int]:
    points = np.array([entry["point"] for entry in LAYOUT["cart2topo"]])
    theta, radius = sl.cart2topo(points)
    return [
        i
        for i, entry in enumerate(LAYOUT["cart2topo"])
        if not abs(theta[i] - entry["theta_deg"]) <= LTOL["cart2topo_theta_deg"]
        or not abs(radius[i] - entry["radius"]) <= LTOL["radius"]
    ]


def test_cart2topo_vectors():
    assert cart2topo_mismatches() == []


def test_straight_behind_is_180_whatever_the_sign_of_zero():
    theta, _ = sl.cart2topo(np.array([[-1.0, 0.0, 0.0], [-1.0, -0.0, 0.0]]))
    assert list(theta) == [180.0, 180.0]


def layout_suite_fails() -> bool:
    if cart2topo_mismatches():
        return True
    if any(layout_mismatches(case) for case in LAYOUT["cases"]):
        return True
    frames = [(LAYOUT_CASES["frame_als"], f) for f in LAYOUT["frames"]["ALS"]]
    frames += [(LAYOUT_CASES["frame_ras"], f) for f in LAYOUT["frames"]["RAS"]]
    return any(layout_mismatches(case, frame) for case, frame in frames)


def _ras_unrotated(xyz, coordinate_system, montage=None):
    sl.orientation(coordinate_system, montage)
    return np.asarray(xyz, dtype=float).copy()


def _template_unknown(coordinate_system, montage=None):
    if coordinate_system in sl.ALS_FRAMES:
        return "ALS"
    if coordinate_system in sl.RAS_FRAMES:
        return "RAS"
    raise sl.SensorLayoutRefusal("frame_unknown", coordinate_system)


def _template_any_frame(coordinate_system, montage=None):
    if montage:
        return "RAS"
    return _template_unknown(coordinate_system)


def _always_centroid(points):
    centroid = points.sum(axis=0) / len(points)
    return sl.Fit(centroid, 1.0, 1.0, 3.0, 0.0)


def _no_wrap(xyz):
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    return -(np.arctan2(y, x) * sl.RAD), 0.5 - (
        np.arctan2(z, np.hypot(x, y)) * sl.RAD
    ) / 180


def _fit_the_subset(points, coordinate_system, montage):
    """Template positions fitted like measured ones: the round-2 fault."""
    fit = sl.sphere_center(points)
    return fit.center, "montage", None


def _zeros_kept(xyz):
    """Every finite row has a position, (0, 0, 0) included: the R4 M1 fault."""
    return np.isfinite(np.asarray(xyz, dtype=float)).all(axis=1)


def _every_row_fitted(count, names=None, sensor_types=None):
    """Every row a scalp row, EOG, neck and fiducial rows included."""
    return np.ones(count, dtype=bool)


def _types_ignored(count, names=None, sensor_types=None):
    """The scalp rows chosen by name alone, as if no row were typed."""
    return _scalp_rows(count, names, None)


def _fiducials_kept(count, names=None, sensor_types=None):
    """Fiducial names are not excluded."""
    return _scalp_rows(count, None, sensor_types)


_scalp_rows = sl.scalp_rows


def _montage_from_the_file_system(coordinate_system, montage=None):
    """Template positions accepted for any montage name, then looked up as a
    file: the R3 M9 fault (a case-folding file system finds another case, and
    PROVENANCE.json has no center)."""
    if montage is not None and coordinate_system == "n/a" and montage:
        return "RAS"
    return _orientation(coordinate_system, montage)


def _center_from_the_file_system(montage, directory=sl.MONTAGES):
    path = directory / f"{montage}.json"
    if not path.is_file():
        raise sl.SensorLayoutRefusal("frame_unknown", montage)
    return np.array(json.loads(path.read_text())["center"], dtype=float)


_orientation = sl.orientation


LAYOUT_MUTATIONS = {
    "flat ratio 0.05 -> 0.01": ("FLAT_RATIO", 0.01),
    "flat ratio 0.05 -> 0.06": ("FLAT_RATIO", 0.06),
    "radius ratio 3 -> 10": ("RADIUS_RATIO", 10.0),
    "radius ratio 3 -> 2.5": ("RADIUS_RATIO", 2.5),
    "templates fitted to the subset": ("center_of", _fit_the_subset),
    "an ALS name misspelled": (
        "ALS_FRAMES",
        (sl.ALS_FRAMES - {"EEGLAB-HJ"}) | {"EEGLAB_HJ"},
    ),
    "an RAS name moved to ALS": ("ALS_FRAMES", sl.ALS_FRAMES | {"ACPC"}),
    "the appendix's spelling not read": ("FRAME_ALIASES", {}),
    "the appendix's spelling in the table": (
        "RAS_FRAMES",
        (sl.RAS_FRAMES - {"MNI152NLin6Asym"}) | {"MNI152NLin6ASym"},
    ),
    "RAS positions not rotated": ("to_als", _ras_unrotated),
    "template positions refused": ("orientation", _template_unknown),
    "a montage beside a named frame accepted": ("orientation", _template_any_frame),
    "always the centroid": ("sphere_center", _always_centroid),
    "theta not written in (-180, 180]": ("cart2topo", _no_wrap),
    "dilution bound 4.5 -> 6.5": ("PARTIAL_DILUTION", 6.5),
    "dilution bound 4.5 -> 4.3": ("PARTIAL_DILUTION", 4.3),
    "stability bound 0.12 -> 0.13": ("PARTIAL_SHIFT", 0.13),
    "stability bound 0.12 -> 0.11": ("PARTIAL_SHIFT", 0.11),
    "rows at (0, 0, 0) kept": ("has_position", _zeros_kept),
    "every row fitted": ("scalp_rows", _every_row_fitted),
    "sensor types ignored": ("scalp_rows", _types_ignored),
    "fiducial names kept": ("scalp_rows", _fiducials_kept),
    "montages found through the file system": (
        ("orientation", _montage_from_the_file_system),
        ("montage_center", _center_from_the_file_system),
    ),
}


# The one mutation that may raise rather than mismatch: a montage looked up on
# the file system reads PROVENANCE.json, which has no center (KeyError), or a
# case-sensitive file system finds no file for another case.
MAY_RAISE = {"montages found through the file system": (KeyError, FileNotFoundError)}


@pytest.mark.parametrize("mutation", list(LAYOUT_MUTATIONS))
def test_sensor_layout_vectors_catch_a_mutation(monkeypatch, mutation):
    name, value = LAYOUT_MUTATIONS[mutation]
    pairs = [(name, value)] if isinstance(name, str) else [name, value]
    for attribute, replacement in pairs:
        monkeypatch.setattr(sl, attribute, replacement)
    if mutation not in MAY_RAISE:
        assert layout_suite_fails(), mutation
        return
    try:
        caught = layout_suite_fails()
    except MAY_RAISE[mutation]:
        caught = True
    assert caught, mutation


TEMPLATES = {"template_midline_9", "template_coronal_9"}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_a_template_subset_lands_where_the_full_cap_puts_it(name):
    """A midline or a coronal row of standard_1005 is drawn at the full cap's
    positions: the center is the montage's, never a sphere through the subset."""
    full = LAYOUT_CASES["template_full_1005"]
    by_name = {
        n: (t, r)
        for n, t, r in zip(
            full["positions"]["name"],
            full["expected"]["theta_deg"],
            full["expected"]["radius"],
            strict=True,
        )
    }
    case = LAYOUT_CASES[name]
    assert case["expected"]["center"] == full["expected"]["center"]
    for n, t, r in zip(
        case["positions"]["name"],
        case["expected"]["theta_deg"],
        case["expected"]["radius"],
        strict=True,
    ):
        assert (t, r) == by_name[n], n


def test_the_midline_runs_from_nose_to_back():
    """The fault round 2 found: a midline fitted alone was stacked on the left
    ear (theta near -90). About the montage's center it runs along theta 0
    (front) and 180 (back)."""
    theta = LAYOUT_CASES["template_midline_9"]["expected"]["theta_deg"]
    assert all(abs(t) < 5 or abs(abs(t) - 180) < 5 for t in theta)
    coronal = LAYOUT_CASES["template_coronal_9"]["expected"]
    ends = [coronal["theta_deg"][0], coronal["theta_deg"][-1]]
    assert abs(ends[0] + 90) < 5 and abs(ends[1] - 90) < 5


MONTAGE_FILES = sorted(
    p
    for p in (ROOT / "views" / "montages").glob("*.json")
    if p.name != "PROVENANCE.json"
)


@pytest.mark.parametrize("path", MONTAGE_FILES, ids=lambda p: p.stem)
def test_each_montage_stores_its_own_center(path):
    """The stored center is the sphere fitted to every electrode, rounded to
    1e-9 m as the positions are (scripts/generate_montages.py writes it)."""
    document = json.loads(path.read_text())
    electrodes = np.array([e[1:4] for e in document["electrodes"]], dtype=float)
    fit = sl.sphere_center(electrodes)
    assert document["center"] == [round(float(v), 9) + 0.0 for v in fit.center]


@pytest.mark.parametrize(
    "montage", ["no-such-cap", "PROVENANCE", "biosemi64 ", "BIOSEMI64", "Biosemi64"]
)
def test_an_unknown_montage_is_refused(montage):
    """Names are matched exactly against the montage list: another case, a
    trailing space and the provenance file are no montage."""
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.sensor_layout(np.eye(3), "n/a", montage=montage)
    assert raised.value.word == "frame_unknown"
    # Each layer refuses on its own: the frame step and the center lookup.
    with pytest.raises(sl.SensorLayoutRefusal):
        sl.orientation("n/a", montage)
    with pytest.raises(sl.SensorLayoutRefusal):
        sl.montage_center(montage)


def test_the_montage_list_is_the_label_algorithms():
    from neuroschema.views.sensor_labels import MONTAGE_NAMES

    files = {p.stem for p in (ROOT / "views" / "montages").glob("*.json")}
    assert files == {*MONTAGE_NAMES, "PROVENANCE"}
    for name in MONTAGE_NAMES:
        assert sl.orientation("n/a", name) == "RAS"


@pytest.mark.parametrize(
    "row",
    [[0.0, 0.0, 0.0], [-0.0, 0.0, 0.0], [0.0, -0.0, -0.0], [-0.0, -0.0, -0.0]],
)
def test_a_row_at_the_origin_has_no_position(row):
    xyz = np.array([[1.0, 2.0, 3.0], row, [0.0, 0.0, 1e-300], [math.nan, 0, 0]])
    assert sl.has_position(xyz).tolist() == [True, False, True, False]


def test_scalp_rows_follow_types_then_names():
    names = ["Cz", "HEOG", "ECG", "Nz", "lpa ", "EEG RPA", "X1"]
    # No row typed: names with a non-EEG prefix and fiducials are not scalp rows.
    assert sl.scalp_rows(7, names).tolist() == [1, 0, 0, 0, 0, 0, 1]
    untyped = [None, "", "n/a", " N/A ", None, None, None]
    assert sl.scalp_rows(7, names, untyped).tolist() == [1, 0, 0, 0, 0, 0, 1]
    # One row typed: only the rows typed EEG, never a fiducial name.
    typed = [" eeg ", "EEG", "EOG", "EEG", None, "EEG", "n/a"]
    assert sl.scalp_rows(7, names, typed).tolist() == [1, 1, 0, 0, 0, 0, 0]
    # Types are not normalized: full-width EEG is another type.
    assert sl.scalp_rows(2, ["Cz", "Pz"], ["EEG", "\uff25\uff25\uff27"]).tolist() == [
        1,
        0,
    ]
    # Without names, every row with a position is a scalp row.
    assert sl.scalp_rows(3).tolist() == [1, 1, 1]


def test_a_map_from_positions_drops_the_rows_that_are_not_scalp_rows():
    """sensor_field_from_positions passes the names and types to the layout:
    the cap with its eye and neck rows (values on every row) draws the cap's
    own map."""
    case = LAYOUT_CASES["eog_and_neck_typed"]
    positions = case["positions"]
    xyz = np.column_stack([numbers(positions[a]) for a in "xyz"])
    values = np.linspace(-3.0, 4.0, len(xyz))
    count = len(LAYOUT_CASES["hydrocel_32_off_center"]["positions"]["name"])
    with_rows = sf.sensor_field_from_positions(
        xyz,
        case["coordinate_system"],
        values,
        names=positions["name"],
        sensor_types=positions["sensor_type"],
    )
    cap = sf.sensor_field_from_positions(
        xyz[:count], case["coordinate_system"], values[:count]
    )
    assert np.array_equal(np.isnan(with_rows.z), np.isnan(cap.z))
    assert np.allclose(with_rows.z, cap.z, equal_nan=True, rtol=0, atol=1e-12)
    assert list(with_rows.plotted) == list(cap.plotted)


def test_names_and_types_have_one_entry_per_row():
    with pytest.raises(ValueError, match="names has 2 entries for 3 rows"):
        sl.sensor_layout(np.eye(3), "CapTrak", names=["a", "b"])
    with pytest.raises(ValueError, match="sensor_types has 1 entries"):
        sl.sensor_layout(np.eye(3), "CapTrak", sensor_types=["EEG"])


def test_dilution_of_an_even_hemisphere_is_three_root_two():
    """The mean of [e, 1] [e, 1]' over an even hemisphere is diag(1/3, 1/3, M),
    with M = [[1/3, 1/2], [1/2, 1]], whose inverse gives 3 + 3 + 12: the
    dilution is sqrt(18). A whole sphere gives sqrt(9); a ring, a singular
    matrix and a value that is not finite."""
    count = 200_000
    i = np.arange(count) + 0.5
    z = 1 - i / count
    a = np.pi * (1 + 5**0.5) * i
    r = np.sqrt(1 - z * z)
    hemisphere = np.column_stack([r * np.cos(a), r * np.sin(a), z])
    assert abs(sl.dilution(hemisphere) - math.sqrt(18)) < 1e-3
    z = 1 - 2 * i / count
    r = np.sqrt(1 - z * z)
    sphere = np.column_stack([r * np.cos(a), r * np.sin(a), z])
    assert abs(sl.dilution(sphere) - 3.0) < 1e-3
    ring = np.column_stack([np.cos(a[:50]), np.sin(a[:50]), np.zeros(50)])
    assert not math.isfinite(sl.dilution(ring))


def test_partial_positions_carry_their_measures():
    case = LAYOUT_CASES["measured_emotiv_14"]
    xyz = np.column_stack([numbers(case["positions"][a]) for a in "xyz"])
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.sensor_layout(xyz, case["coordinate_system"])
    refusal = raised.value
    assert refusal.word == "positions_partial"
    assert abs(refusal.dilution - case["bounds"]["dilution"]) <= LTOL["bounds_absolute"]
    assert refusal.radius_ratio is not None and refusal.singular_ratio is not None
    assert refusal.stability is None  # the dilution refused it first
    unstable = LAYOUT_CASES["p300_8_noisy_unstable"]
    xyz = np.column_stack([numbers(unstable["positions"][a]) for a in "xyz"])
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.sensor_layout(xyz, unstable["coordinate_system"])
    refusal = raised.value
    assert refusal.word == "positions_partial"
    for measure in ("dilution", "stability"):
        got, want = getattr(refusal, measure), unstable["bounds"][measure]
        assert abs(got - want) <= LTOL["bounds_absolute"], measure
    assert refusal.dilution <= sl.PARTIAL_DILUTION  # passed, so stability refused
    assert refusal.stability > sl.PARTIAL_SHIFT


def test_stability_is_the_largest_move_of_a_refit_without_one_position():
    """The downdated normal equations give the center a least-squares refit
    without each row gives, on a real cap and on a noisy regional set."""
    for name in ("hydrocel_32_off_center", "p300_8_noisy_unstable"):
        case = LAYOUT_CASES[name]
        xyz = np.column_stack([numbers(case["positions"][a]) for a in "xyz"])
        als = sl.to_als(xyz, case["coordinate_system"])
        n = len(als)
        centroid = als.sum(axis=0) / n
        u = (als - centroid) / np.sqrt(((als - centroid) ** 2).sum(axis=1)).max()
        design = np.column_stack([2 * u, np.ones(n)])
        target = (u * u).sum(axis=1)
        w = np.linalg.lstsq(design, target, rcond=None)[0]
        radius = math.sqrt(w[0] ** 2 + w[1] ** 2 + w[2] ** 2 + w[3])
        moves = []
        for k in range(n):
            keep = np.arange(n) != k
            wk = np.linalg.lstsq(design[keep], target[keep], rcond=None)[0]
            moves.append(np.linalg.norm(wk[:3] - w[:3]) / radius)
        assert abs(sl.stability(design, target, w, radius) - max(moves)) < 1e-9
        assert abs(case["bounds"]["stability"] - max(moves)) < 1e-9


def test_the_flatness_cases_test_what_their_names_say():
    """The cases inside the flatness bounds pass them and are refused only as
    partial; a set with no midline that spans the head is drawn."""
    for name, measure, inside in (
        ("squashed_sphere_not_flat", "singular_ratio", lambda v: v > sl.FLAT_RATIO),
        ("cap_not_flat", "radius_ratio", lambda v: v < sl.RADIUS_RATIO),
    ):
        case = LAYOUT_CASES[name]
        assert case["refused"] == "positions_partial", name
        assert inside(case["bounds"][measure]), name
        assert case["bounds"]["dilution"] > sl.PARTIAL_DILUTION, name
    eight = LAYOUT_CASES["measured_eight_no_midline"]
    assert "expected" in eight and eight["expected"]["center_method"] == "sphere"
    assert not any(n.lower().endswith("z") for n in eight["positions"]["name"])


def test_the_stability_bound_is_pinned_from_both_sides():
    inside, outside = (
        LAYOUT_CASES["stability_inside"],
        LAYOUT_CASES["stability_outside"],
    )
    assert "expected" in inside and outside["refused"] == "positions_partial"
    got = inside["bounds"]["stability"], outside["bounds"]["stability"]
    assert sl.PARTIAL_SHIFT - 0.006 < got[0] < sl.PARTIAL_SHIFT < got[1] < 0.126
    for case in (inside, outside):
        assert case["bounds"]["dilution"] < sl.PARTIAL_DILUTION - 1.0


@pytest.mark.parametrize(
    "name", ["central_9_with_egi_fiducials", "p300_8_with_eeglab_fiducials"]
)
def test_a_regional_set_with_fiducial_rows_is_still_partial(name):
    """FidNz, FidT9, FidT10, Nasion, LeftEar and RightEar are fiducials: left
    out of the fit, so they cannot lend a regional set the coverage it lacks."""
    case = LAYOUT_CASES[name]
    assert case["refused"] == "positions_partial"
    xyz = np.column_stack([numbers(case["positions"][a]) for a in "xyz"])
    names = case["positions"]["name"]
    fitted = sl.scalp_rows(len(names), names)
    assert fitted.tolist() == [True] * (len(names) - 3) + [False] * 3
    # Fitted with them, the fiducials would lend the set a passing dilution.
    try:
        spread = sl.sphere_center(sl.to_als(xyz, case["coordinate_system"])).dilution
    except sl.SensorLayoutRefusal as refusal:
        spread = refusal.dilution
    assert spread is not None and spread <= sl.PARTIAL_DILUTION


def test_the_coverage_bound_separates_the_reviewers_sets():
    """Frontal 6, central 9 and the Emotiv 14 are refused; the 10-20 set is
    drawn, each well clear of the bound."""
    for name in ("measured_frontal_6", "measured_central_9", "measured_emotiv_14"):
        case = LAYOUT_CASES[name]
        assert case["refused"] == "positions_partial", name
        assert case["bounds"]["dilution"] > sl.PARTIAL_DILUTION + 1.0, name
    ten_twenty = LAYOUT_CASES["measured_ten_twenty"]
    assert "expected" in ten_twenty
    assert ten_twenty["bounds"]["dilution"] < sl.PARTIAL_DILUTION - 1.0


@pytest.mark.parametrize(
    ("with_rows", "without"),
    [
        ("eog_and_neck_typed", "hydrocel_32_off_center"),
        ("eog_and_neck_untyped", "hydrocel_32_off_center"),
        ("fiducials_typed", "measured_ten_twenty"),
        ("fiducials_untyped", "measured_ten_twenty"),
    ],
)
def test_rows_that_are_not_scalp_rows_change_nothing(with_rows, without):
    """The cap's layout with and without the EOG, neck or fiducial rows is the
    same: those rows get none, and the center is the cap's own."""
    case, bare = LAYOUT_CASES[with_rows], LAYOUT_CASES[without]
    count = len(bare["expected"]["radius"])
    expected = case["expected"]
    assert all(r is None for r in expected["radius"][count:])
    for measure, value in bare["bounds"].items():
        assert abs(case["bounds"][measure] - value) <= 1e-9, measure
    if without == "hydrocel_32_off_center":
        # That case is the same cap moved by (3, -1.5, 2): compare radii only.
        assert np.allclose(expected["radius"][:count], bare["expected"]["radius"])
    else:
        assert expected["radius"][:count] == bare["expected"]["radius"]
        assert expected["center"] == bare["expected"]["center"]


def test_positions_are_n_by_3():
    with pytest.raises(ValueError, match="n-by-3"):
        sl.sensor_layout(np.ones((4, 2)), "CapTrak")


@pytest.mark.parametrize("finite", [0, 3])
def test_three_or_fewer_finite_positions_are_flat(finite):
    xyz = np.full((6, 3), math.nan)
    points = [[7.0, 1.0, 3.0], [-2.0, 6.0, 4.0], [0.5, -5.0, 6.5]]
    for row in range(finite):
        xyz[row] = points[row]
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.sensor_layout(xyz, "EEGLAB")
    assert raised.value.word == "positions_flat"


# ── The generator's --check ────────────────────────────────────────────────


def _generator():
    path = ROOT / "scripts" / "generate_view_vectors.py"
    spec = importlib.util.spec_from_file_location("generate_view_vectors", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_tolerates_rounding_and_catches_changes():
    gen = _generator()
    case = json.loads(json.dumps(FIELD_CASES["montage_32"]))
    assert gen.differences(case, case) == []
    z = case["expected"]["z"]
    cells = [v for row in z for v in row if v is not None]
    span = max(cells) - min(cells)
    moved = json.loads(json.dumps(case))
    row = next(i for i, r in enumerate(z) if r[33] is not None)
    moved["expected"]["z"][row][33] += 5e-10 * span
    assert gen.differences(moved, case) == []
    moved["expected"]["z"][row][33] += 2e-9 * span
    assert gen.differences(moved, case) == [
        f"/expected/z/{row}/33: {z[row][33]!r} -> {moved['expected']['z'][row][33]!r}"
    ]
    moved = json.loads(json.dumps(case))
    moved["expected"]["plotrad"] *= 1 + 1e-11
    assert len(gen.differences(moved, case)) == 1
    moved = json.loads(json.dumps(case))
    moved["expected"]["interpolated"] = moved["expected"]["interpolated"][1:]
    assert gen.differences(moved, case)
    assert gen.differences({"refused": "too_few_sensors"}, {"refused": "x"})
    # Limits and the color axis follow the cells: the map's range bounds them.
    for key in ("limits", "color_axis"):
        moved = json.loads(json.dumps(case))
        moved["expected"][key]["minmax"][1] += 5e-10 * span
        assert gen.differences(moved, case) == []
        moved["expected"][key]["minmax"][1] += 2e-9 * span
        assert len(gen.differences(moved, case)) == 1
    # A row with a null theta compares its radius alone, absolutely.
    holes = json.loads(json.dumps(FIELD_CASES["nan_positions"]))
    row = holes["sensors"]["theta_deg"].index(None)
    moved = json.loads(json.dumps(holes))
    moved["sensors"]["radius"][row] += 5e-17
    assert gen.differences(moved, holes) == []
    moved["sensors"]["radius"][row] += 1e-11
    assert len(gen.differences(moved, holes)) == 1
    # A center at the origin is compared against the positions' extent.
    cap = json.loads(json.dumps(LAYOUT_CASES["biosemi_128_ras"]))
    assert max(abs(v) for v in cap["expected"]["center"]) < 1e-12
    moved = json.loads(json.dumps(cap))
    moved["expected"]["center"][1] += 4e-14
    assert gen.differences(moved, cap) == []
    moved["expected"]["center"][1] += 1e-9
    assert len(gen.differences(moved, cap)) == 1


FROZEN_INPUTS = json.loads((ROOT / "scripts" / "view_vector_inputs.json").read_text())


def test_vectors_are_drawn_from_the_frozen_inputs():
    """Every case's inputs are the stored ones, so platform math cannot move
    them; only --refresh-inputs rewrites the store."""
    field = FROZEN_INPUTS["sensor-field"]
    layout = FROZEN_INPUTS["sensor-layout"]
    assert set(field) == set(FIELD_CASES)
    assert set(layout) == set(LAYOUT_CASES)
    for name, case in FIELD_CASES.items():
        assert case["sensors"] == field[name], name
    for name, case in LAYOUT_CASES.items():
        assert case["positions"] == layout[name], name


def test_generator_reads_the_frozen_inputs(monkeypatch):
    """Inputs come from the store; computed ones are used only while refreshing,
    and a case missing from the store stops the generator."""
    gen = _generator()
    computed = {"name": ["X"], "theta_deg": [0.0], "radius": [0.1], "value": [1.0]}
    monkeypatch.setattr(gen, "FROZEN", FROZEN_INPUTS)
    stored = gen.frozen("sensor-field", "montage_32", computed)
    assert stored == FROZEN_INPUTS["sensor-field"]["montage_32"]
    with pytest.raises(SystemExit, match="--refresh-inputs"):
        gen.frozen("sensor-field", "no_such_case", computed)
    monkeypatch.setattr(gen, "FROZEN", None)
    assert gen.frozen("sensor-field", "montage_32", computed) is computed


def test_check_refuses_to_refresh_inputs(monkeypatch, capsys):
    gen = _generator()
    monkeypatch.setattr("sys.argv", ["gen", "--check", "--refresh-inputs"])
    with pytest.raises(SystemExit):
        gen.main()
    assert "drop --refresh-inputs" in capsys.readouterr().err


def test_check_compares_layouts_by_planar_point():
    """A vertex sensor's theta may move freely; a sensor off the pole may not."""
    gen = _generator()
    case = json.loads(json.dumps(LAYOUT_CASES["biosemi_128_ras"]))
    expected = case["expected"]
    vertex = min(range(len(expected["radius"])), key=lambda i: expected["radius"][i])
    assert expected["radius"][vertex] < 1e-12
    moved = json.loads(json.dumps(case))
    moved["expected"]["theta_deg"][vertex] += 65.0
    assert gen.differences(moved, case) == []
    off = next(i for i, r in enumerate(expected["radius"]) if r > 0.3)
    moved["expected"]["theta_deg"][off] += 1e-9
    theta, radius = expected["theta_deg"][off], expected["radius"][off]
    now = moved["expected"]["theta_deg"][off]
    assert gen.differences(moved, case) == [
        f"/expected/{off}: ({theta!r}, {radius!r}) -> ({now!r}, {radius!r})"
    ]
    moved = json.loads(json.dumps(case))
    moved["expected"]["center"][0] += 1e-6
    assert gen.differences(moved, case)
    moved = json.loads(json.dumps(case))
    moved["expected"]["theta_deg"][off] = None
    assert gen.differences(moved, case)


# What the ubuntu-latest view-vectors job regenerated differently from the
# macOS-written vectors (CI run 45247745795, eegprep edf694c8, numpy 2.5.5,
# scipy 1.18.1), as the Linux value minus the macOS value: the regeneration
# tolerance must absorb each of them. They are kept as differences, applied
# to the committed vectors, since the maps those runs drew have changed since.
LINUX_FIELD = {
    ("close_pair", "limits", "absmax"): (-4.118660967833421e-11, 4.118660967833421e-11),
    ("close_pair", "limits", "minmax"): (-4.118660967833421e-11, 3.370992374129855e-11),
    ("close_pair", "color_axis", "absmax"): (
        -4.32436308983597e-11,
        4.32436308983597e-11,
    ),
    # The minmax axis of the Linux limits, widened by the range rule.
    ("close_pair", "color_axis", "minmax"): (
        -4.4931169895789935e-11,
        3.745448395875428e-11,
    ),
}
LINUX_RADIUS = ("nan_positions", 8, 0.48437218538703425)
LINUX_CENTER = (
    "biosemi_128_ras",
    [7.105427357601002e-15, 1.9152969403041287e-14, -4.263256414560601e-14],
)


def _as_linux(field: dict, layout: dict) -> tuple[dict, dict]:
    field, layout = json.loads(json.dumps(field)), json.loads(json.dumps(layout))
    cases = {c["name"]: c for c in field["cases"]}
    for (name, key, choice), deltas in LINUX_FIELD.items():
        pair = cases[name]["expected"][key][choice]
        cases[name]["expected"][key][choice] = [
            v + d for v, d in zip(pair, deltas, strict=True)
        ]
    name, row, radius = LINUX_RADIUS
    cases[name]["sensors"]["radius"][row] = radius
    name, center = LINUX_CENTER
    next(c for c in layout["cases"] if c["name"] == name)["expected"]["center"] = center
    return field, layout


def test_check_bounds_cells_by_range_and_magnitude_with_no_floor():
    """A cell may move 1e-9 of the map's range plus 1e-12 of its magnitude: a
    map of zeros is compared exactly, and a map drawn at 30 within 3e-11."""
    gen = _generator()
    zero = json.loads(json.dumps(FIELD_CASES["zero_map"]))
    moved = json.loads(json.dumps(zero))
    row = next(i for i, r in enumerate(moved["expected"]["z"]) if r[33] is not None)
    moved["expected"]["z"][row][33] = 1e-300
    assert gen.differences(moved, zero)
    near = json.loads(json.dumps(FIELD_CASES["near_flat_one_ulp"]))
    moved = json.loads(json.dumps(near))
    moved["expected"]["z"][row][33] += 2e-11
    assert gen.differences(moved, near) == []
    moved["expected"]["z"][row][33] += 2e-11
    assert gen.differences(moved, near)


def test_check_absorbs_the_linux_rounding():
    gen = _generator()
    field, layout = _as_linux(FIELD, LAYOUT)
    assert gen.differences(field, FIELD) == []
    assert gen.differences(layout, LAYOUT) == []


def test_check_still_catches_changes_where_linux_rounds():
    """The same places, moved beyond the tolerance: a limit by 1e-8 of the
    map's range, a radius on a row without theta by 1e-11, the center at the
    origin by 1e-9 of the cap's extent."""
    gen = _generator()
    field, layout = _as_linux(FIELD, LAYOUT)
    close_pair = next(c for c in field["cases"] if c["name"] == "close_pair")
    close_pair["expected"]["limits"]["minmax"][1] += 1e-8 * 33
    nan_positions = next(c for c in field["cases"] if c["name"] == "nan_positions")
    nan_positions["sensors"]["radius"][8] += 1e-11
    assert len(gen.differences(field, FIELD)) == 2
    biosemi = next(c for c in layout["cases"] if c["name"] == "biosemi_128_ras")
    biosemi["expected"]["center"][2] += 1e-9 * 100
    assert len(gen.differences(layout, LAYOUT)) == 1


def test_generator_keeps_every_measure_off_its_bound():
    """Each vector's measures stay 0.002, 0.05 and 0.05 from the bounds, so an
    implementation's rounding cannot flip a case."""
    gen = _generator()

    def bounds(singular_ratio, radius_ratio=None, dilution=None, stability=None):
        return {
            "singular_ratio": singular_ratio,
            "radius_ratio": radius_ratio,
            "dilution": dilution,
            "stability": stability,
        }

    gen.check_bounds("clear", bounds(0.06, 2.9, 4.44))
    gen.check_bounds("clear", bounds(0.06, 2.9, 4.56))
    gen.check_bounds("flat", bounds(0.0))
    with pytest.raises(SystemExit, match="singular ratio"):
        gen.check_bounds("near", bounds(0.0505))
    with pytest.raises(SystemExit, match="radius ratio"):
        gen.check_bounds("near", bounds(0.2, 3.01))
    with pytest.raises(SystemExit, match="dilution"):
        gen.check_bounds("near", bounds(0.2, 1.0, 4.46))
    with pytest.raises(SystemExit, match="dilution"):
        gen.check_bounds("near", bounds(0.2, 1.0, 4.54))
    gen.check_bounds("clear", bounds(0.2, 1.0, 3.0, 0.114))
    gen.check_bounds("clear", bounds(0.2, 1.0, 3.0, 0.126))
    with pytest.raises(SystemExit, match="stability"):
        gen.check_bounds("near", bounds(0.2, 1.0, 3.0, 0.118))
    with pytest.raises(SystemExit, match="stability"):
        gen.check_bounds("near", bounds(0.2, 1.0, 3.0, 0.122))
    assert gen.PARTIAL_DILUTION == sl.PARTIAL_DILUTION
    assert gen.PARTIAL_SHIFT == sl.PARTIAL_SHIFT


def test_generator_checks_each_stored_montage_center(monkeypatch):
    """The generator refits every montage and stops when the stored center is
    not that fit."""
    gen = _generator()
    document = json.loads((ROOT / "views" / "montages" / "biosemi64.json").read_text())
    monkeypatch.setattr(gen, "montage_document", lambda name: document)
    assert np.array_equal(gen.montage_center("biosemi64"), document["center"])
    document["center"] = [0.0, 0.001, 0.0]
    with pytest.raises(SystemExit, match="not the fit"):
        gen.montage_center("biosemi64")


def test_generator_refuses_decisions_near_a_threshold():
    gen = _generator()
    theta = np.array([0.0, 0.0, 90.0, -90.0])
    radius = np.array([0.3, 0.3 + gen.MERGE + 1e-11, 0.2, 0.25])
    usable = [0, 1, 2, 3]
    groups = [[0], [1], [2], [3]]
    gx = gy = np.linspace(-0.5, 0.5, 67)
    with pytest.raises(SystemExit, match="merge 1-0"):
        gen.check_margins("near", theta, radius, usable, groups, 0.5, 0.4, gx, gy)
    radius[1] = 0.32
    gen.check_margins("clear", theta, radius, usable, groups, 0.5, 0.4, gx, gy)
