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
                xyz, case["coordinate_system"], values, montage=case.get("montage")
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
        positions = {axis: sensors[axis] for axis in "xyz"}
        projected = case | {"positions": positions, "expected": expected["layout"]}
        problems += [f"layout {p}" for p in layout_mismatches(projected)]
    z = np.array([numbers(row) for row in expected["z"]])
    if drawn.z.shape != z.shape:
        return [f"grid {drawn.z.shape}, not {z.shape}"]
    if not np.array_equal(np.isnan(drawn.z), np.isnan(z)):
        problems.append("mask")
    cells = z[~np.isnan(z)]
    low, high = cells.min(), cells.max()
    bound = (
        TOL["cells_relative_to_range"] * (high - low)
        if high > low
        else TOL["constant_map_cells"] * max(1.0, abs(high))
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
    w = np.linalg.pinv(g) @ values
    expected = case["expected"]
    qx, qy = np.meshgrid(numbers(expected["x"]), numbers(expected["y"]), indexing="ij")
    z = sf.green(np.hypot(qx[:, :, None] - px, qy[:, :, None] - py)) @ w
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


def test_a_flat_field_has_no_contours():
    """Equal values ripple through the spline; the ripple draws no contour."""
    case = FIELD_CASES["constant_values"]
    assert len(set(case["sensors"]["value"])) == 1
    limits = case["expected"]["limits"]["minmax"]
    assert limits[0] < limits[1], "the interpolant ripples"
    assert case["expected"]["contours"] == []
    assert sf.is_flat(np.array([2.5, 2.5, 2.5]))
    assert not sf.is_flat(np.array([2.5, 2.5, 2.5000000000000004]))


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
        layout = sl.sensor_layout(xyz, frame, montage=montage)
    except sl.SensorLayoutRefusal as exc:
        if case.get("refused") != exc.word:
            return [f"refused {exc.word}"]
        return bounds_mismatches(case, exc.singular_ratio, exc.radius_ratio)
    if "refused" in case:
        return [f"gave a layout; the vector refuses it ({case['refused']})"]
    expected = case["expected"]
    theta, radius = numbers(expected["theta_deg"]), numbers(expected["radius"])
    problems = bounds_mismatches(case, layout.singular_ratio, layout.radius_ratio)
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


def bounds_mismatches(case, singular_ratio, radius_ratio) -> list[str]:
    """A measured case's flatness measures, within tolerance.bounds_absolute
    (a template case has none)."""
    bounds = case.get("bounds")
    if bounds is None:
        return [] if singular_ratio is None and radius_ratio is None else ["bounds"]
    problems = []
    for name, got in (
        ("singular_ratio", singular_ratio),
        ("radius_ratio", radius_ratio),
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


def test_frame_table_is_the_vectors():
    assert set(LAYOUT["frames"]["ALS"]) == sl.ALS_FRAMES
    assert set(LAYOUT["frames"]["RAS"]) == sl.RAS_FRAMES
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
    return sl.Fit(centroid, 1.0, 1.0)


def _no_wrap(xyz):
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    return -(np.arctan2(y, x) * sl.RAD), 0.5 - (
        np.arctan2(z, np.hypot(x, y)) * sl.RAD
    ) / 180


def _fit_the_subset(points, coordinate_system, montage):
    """Template positions fitted like measured ones: the round-2 fault."""
    fit = sl.sphere_center(points)
    return fit.center, "montage", None, None


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
    "RAS positions not rotated": ("to_als", _ras_unrotated),
    "template positions refused": ("orientation", _template_unknown),
    "a montage beside a named frame accepted": ("orientation", _template_any_frame),
    "always the centroid": ("sphere_center", _always_centroid),
    "theta not written in (-180, 180]": ("cart2topo", _no_wrap),
}


@pytest.mark.parametrize("mutation", list(LAYOUT_MUTATIONS))
def test_sensor_layout_vectors_catch_a_mutation(monkeypatch, mutation):
    name, value = LAYOUT_MUTATIONS[mutation]
    monkeypatch.setattr(sl, name, value)
    assert layout_suite_fails(), mutation


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


def test_an_unknown_montage_is_refused():
    with pytest.raises(sl.SensorLayoutRefusal) as raised:
        sl.sensor_layout(np.eye(3), "n/a", montage="no-such-cap")
    assert raised.value.word == "frame_unknown"


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


# Every value the ubuntu-latest view-vectors job regenerated differently from
# these macOS-written vectors (CI run 45247745795, eegprep edf694c8, numpy
# 2.5.5, scipy 1.18.1): the regeneration tolerance must absorb each of them.
LINUX_FIELD = {
    ("close_pair", "limits", "absmax"): [-19.426989565881048, 19.426989565881048],
    ("close_pair", "limits", "minmax"): [-19.426989565881048, 13.450841521473963],
    ("close_pair", "color_axis", "absmax"): [-20.3983390441751, 20.3983390441751],
    # The minmax color axis widens by the range since; this is the Linux limits
    # above widened by that rule, which binary64 computes alike everywhere.
    ("close_pair", "color_axis", "minmax"): [-21.0708811202488, 15.094733075841713],
}
LINUX_RADIUS = ("nan_positions", 8, 0.48437218538703425)
LINUX_CENTER = (
    "biosemi_128_ras",
    [7.105427357601002e-15, 1.9152969403041287e-14, -4.263256414560601e-14],
)


def _as_linux(field: dict, layout: dict) -> tuple[dict, dict]:
    field, layout = json.loads(json.dumps(field)), json.loads(json.dumps(layout))
    cases = {c["name"]: c for c in field["cases"]}
    for (name, key, choice), pair in LINUX_FIELD.items():
        cases[name]["expected"][key][choice] = pair
    name, row, radius = LINUX_RADIUS
    cases[name]["sensors"]["radius"][row] = radius
    name, center = LINUX_CENTER
    next(c for c in layout["cases"] if c["name"] == name)["expected"]["center"] = center
    return field, layout


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
    """Each vector's flatness measures stay 0.002 and 0.05 from the bounds, so
    an implementation's rounding cannot flip a case."""
    gen = _generator()
    gen.check_bounds("clear", {"singular_ratio": 0.06, "radius_ratio": 2.9})
    gen.check_bounds("flat", {"singular_ratio": 0.0, "radius_ratio": None})
    with pytest.raises(SystemExit, match="singular ratio"):
        gen.check_bounds("near", {"singular_ratio": 0.0505, "radius_ratio": None})
    with pytest.raises(SystemExit, match="radius ratio"):
        gen.check_bounds("near", {"singular_ratio": 0.2, "radius_ratio": 3.01})


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
