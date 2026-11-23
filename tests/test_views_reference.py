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
    scale = np.maximum(np.abs(a), np.abs(b))
    return a.shape == b.shape and bool((np.abs(a - b) <= rel * scale).all())


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
    }


def test_vectors_project_positions_to_a_map():
    drawn = [c for c in FIELD["cases"] if "x" in c["sensors"] and "expected" in c]
    assert {c.get("montage") for c in drawn} == {None, "GSN-HydroCel-32"}


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
    "fewest sensors 3 -> 2": ("MIN_SENSORS", 2),
    "color margin 5% -> 0": ("COLOR_MARGIN", 0.0),
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
}


@pytest.mark.parametrize("mutation", list(FIELD_MUTATIONS))
def test_sensor_field_vectors_catch_a_mutation(monkeypatch, mutation):
    name, value = FIELD_MUTATIONS[mutation]
    monkeypatch.setattr(sf, name, value)
    assert any(field_mismatches(case) for case in FIELD["cases"]), mutation


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
    assert sf.color_axis((-0.0, 0.0)) == (0.0, 0.0)
    assert sf.color_axis((-2.0, 4.0)) == (-2.1, 4.2)


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
        return [] if case.get("refused") == exc.word else [f"refused {exc.word}"]
    if "refused" in case:
        return [f"gave a layout; the vector refuses it ({case['refused']})"]
    expected = case["expected"]
    theta, radius = numbers(expected["theta_deg"]), numbers(expected["radius"])
    problems = []
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
    return points.sum(axis=0) / len(points), "centroid"


def _no_wrap(xyz):
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    return -(np.arctan2(y, x) * sl.RAD), 0.5 - (
        np.arctan2(z, np.hypot(x, y)) * sl.RAD
    ) / 180


LAYOUT_MUTATIONS = {
    "an ALS name misspelled": (
        "ALS_FRAMES",
        (sl.ALS_FRAMES - {"EEGLAB-HJ"}) | {"EEGLAB_HJ"},
    ),
    "an RAS name moved to ALS": ("ALS_FRAMES", sl.ALS_FRAMES | {"ACPC"}),
    "RAS positions not rotated": ("to_als", _ras_unrotated),
    "template positions refused": ("orientation", _template_unknown),
    "a montage beside a named frame accepted": ("orientation", _template_any_frame),
    "no degenerate fit": ("FIT_PIVOT", 0.0),
    "always the centroid": ("sphere_center", _always_centroid),
    "theta not written in (-180, 180]": ("cart2topo", _no_wrap),
}


@pytest.mark.parametrize("mutation", list(LAYOUT_MUTATIONS))
def test_sensor_layout_vectors_catch_a_mutation(monkeypatch, mutation):
    name, value = LAYOUT_MUTATIONS[mutation]
    monkeypatch.setattr(sl, name, value)
    assert layout_suite_fails(), mutation


def test_positions_are_n_by_3():
    with pytest.raises(ValueError, match="n-by-3"):
        sl.sensor_layout(np.ones((4, 2)), "CapTrak")


def test_no_finite_position_gives_no_layout():
    layout = sl.sensor_layout(np.full((3, 3), math.nan), "EEGLAB")
    assert np.isnan(layout.theta_deg).all() and np.isnan(layout.radius).all()
    assert layout.center is None and layout.center_method is None


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
