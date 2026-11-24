"""``nemar.sensor-field.v1``: the scalp map of one value per sensor.

The Python reference renderer for the algorithm ``docs/views/sensor-field.md``
specifies: EEGLAB's ``topoplot`` map (plotting and interpolation radii, squeeze,
a 67-by-67 grid, biharmonic interpolation, the head mask, limits, contours and
the head outline), with the rules eegprep leaves implicit stated outright
(sensors within 1e-3 of an earlier one merge, fewer than eight interpolated
sensors draw no map, the interpolation matrix is solved by LU decomposition
with partial pivoting).
``views/vectors/sensor-field.v1.json`` holds the cases every implementation
reproduces, computed by eegprep at a pinned commit.

numpy only: install the ``views`` extra, and import this module itself;
``neuroschema.views`` does not import it, so it needs no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neuroschema.views.linalg import lu_solve
from neuroschema.views.sensor_layout import sensor_layout

SENSOR_FIELD = "nemar.sensor-field.v1"

HEAD_RADIUS = 0.5
"""``rmax``: the head circle's radius on the grid; cells beyond it are masked."""
RADIUS_MARGIN = 1.02
"""The plotting and interpolation radii reach just past the outermost sensor."""
GRID_SIZE = 67
"""Grid points along each axis."""
MERGE_DISTANCE = 1e-3
"""Sensors this close (raw layout units) to an earlier kept sensor merge into it."""
MIN_SENSORS = 8
"""Fewer interpolated sensors than this draw no map: 8, as many channels as
``nemar.sensor-labels.v1`` needs to place sensors by name."""
CONTOUR_COUNT = 6
"""Interior contour levels."""
FLAT_FIELD = "flat_field"
"""The note of a flat field, every usable sensor one value: "all sensors have
the same value". Its map is that value in every cell."""
NEAR_FLAT = 1e-9
"""A map whose values' range is at most this share of their magnitude is near
flat: one color at the mean, with no contours."""
NEAR_FLAT_NOTE = "near_flat"
"""The note of a near-flat field: "all sensors are within <range> of each
other", the range of the usable values."""
COLOR_MARGIN = 0.05
"""The color axis widens the limits by this share: of each limit's magnitude
for ``absmax`` (EEGLAB's ``caxis``), of their range for ``minmax``."""
DEG = np.pi / 180
"""Degrees to radians: the binary64 nearest pi, divided by 180."""

# EEGLAB's cartoon nose and right ear for a head of radius 0.5 (topoplot.m,
# lines 1402 to 1409 of sccn/eeglab develop at 6c238f7), as (x, y) points in
# layout coordinates: x to the nose, y to the right ear. The left ear is the
# right ear with y negated. A drawn map scales them by squeezefac.
NOSE = ((0.4954, 0.09), (0.57, 0.02), (0.575, 0.0), (0.57, -0.02), (0.4954, -0.09))
RIGHT_EAR = (
    (0.0955, 0.492),
    (0.1175, 0.510),
    (0.1183, 0.518),
    (0.1146, 0.5299),
    (0.0955, 0.5419),
    (-0.0055, 0.540),
    (-0.0932, 0.547),
    (-0.1313, 0.532),
    (-0.1384, 0.510),
    (-0.1199, 0.484),
)


class SensorFieldRefusal(ValueError):
    """A map the algorithm refuses to draw, with the word a renderer shows."""

    def __init__(self, word: str, detail: str) -> None:
        super().__init__(f"{word}: {detail}")
        self.word = word


Point = tuple[float, float]


@dataclass(frozen=True)
class Head:
    """The head outline over a map, in grid coordinates (x to the nose).

    EEGLAB's cartoon head of radius 0.5, squeezed as the sensors are: a circle
    of ``radius`` ``0.5 * squeezefac`` about the origin, and the polylines
    ``nose``, ``right_ear`` and ``left_ear``, each model point times
    ``squeezefac`` (EEGLAB's ``sf = headrad / plotrad``, topoplot.m:1410).
    """

    radius: float
    nose: tuple[Point, ...]
    right_ear: tuple[Point, ...]
    left_ear: tuple[Point, ...]


def head_outline(squeezefac: float) -> Head:
    """The head outline of a map whose sensors are squeezed by ``squeezefac``."""

    def scale(points):
        return tuple((x * squeezefac + 0.0, y * squeezefac + 0.0) for x, y in points)

    left = tuple((x, -y) for x, y in RIGHT_EAR)
    return Head(HEAD_RADIUS * squeezefac, scale(NOSE), scale(RIGHT_EAR), scale(left))


@dataclass(frozen=True)
class SensorField:
    """A drawn map: the grid, the masked values and the scalars around them.

    ``z[i, j]`` is the value at ``(x[i], y[j])`` in layout coordinates, where x
    points to the nose and y to the right ear; on screen, x runs up and y runs
    right. Cells outside the head circle are NaN. Sensor indices are row
    numbers of the input, counted from 0; ``merged`` maps each kept sensor
    that absorbed others to its whole group, itself first. ``head`` is the
    outline drawn over the map (:func:`head_outline`), ``notes`` what a
    renderer says with it (:data:`FLAT_FIELD`, :data:`NEAR_FLAT_NOTE`), and
    ``value_range`` the range of the usable values, for the near-flat caption.
    """

    plotrad: float
    intrad: float
    squeezefac: float
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    plotted: tuple[int, ...]
    interpolated: tuple[int, ...]
    merged: dict[int, tuple[int, ...]]
    limits: dict[str, tuple[float, float]]
    color_axis: dict[str, tuple[float, float]]
    contours: tuple[float, ...]
    head: Head
    notes: tuple[str, ...]
    value_range: float


def planar(theta_deg: np.ndarray, radius: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Layout (theta in degrees, radius) to raw planar x (nose) and y (right ear)."""
    theta = np.asarray(theta_deg, dtype=np.float64) * DEG
    radius = np.asarray(radius, dtype=np.float64)
    return np.cos(theta) * radius, np.sin(theta) * radius


def within_merge(distance: float) -> bool:
    """A distance at which a sensor merges: at most :data:`MERGE_DISTANCE`."""
    return distance <= MERGE_DISTANCE


def is_plotted(radius: float, plotrad: float) -> bool:
    """A sensor gets a marker when its radius is at most ``plotrad``."""
    return radius <= plotrad


def merge(x: np.ndarray, y: np.ndarray, rows: list[int]) -> dict[int, list[int]]:
    """Group sensors in row order: each joins the first kept sensor within reach.

    A sensor whose distance to an earlier kept sensor is at most
    :data:`MERGE_DISTANCE` merges into the first such sensor; otherwise it is
    kept. Distances are measured to kept sensors only, so merges do not chain.
    Returns each kept row with its group (itself first).
    """
    groups: dict[int, list[int]] = {}
    for row in rows:
        for kept in groups:
            dx = x[row] - x[kept]
            dy = y[row] - y[kept]
            if within_merge(np.sqrt(dx * dx + dy * dy)):
                groups[kept].append(row)
                break
        else:
            groups[row] = [row]
    return groups


def outermost(radius: np.ndarray, usable: list[int]) -> float:
    """The largest radius among the usable sensors, merged or not.

    EEGLAB's ``topoplot.m`` takes its radii from every channel with a value
    and a place, before it interpolates, so a sensor merged into another still
    reaches the plotting radius.
    """
    return float(radius[usable].max())


def mean(values: np.ndarray, members: list[int]) -> float:
    """A merged sensor's value: the mean of its members' values, in row order,
    computed as :func:`center` computes one, ``first + sum(x - first) / k``,
    so equal members give their value exactly and huge ones do not overflow."""
    return center(np.array([values[row] for row in members], dtype=np.float64))


def in_square(x: np.ndarray, y: np.ndarray, intrad: float) -> np.ndarray:
    """EEGLAB's interpolation square: ``x <= intrad`` and ``y <= intrad``.

    There is no absolute value, so a sensor far behind the head or far to its
    left is still interpolated; EEGLAB's ``topoplot.m`` has the same test.
    """
    return (x <= intrad) & (y <= intrad)


def grid_axis(low: float, high: float) -> np.ndarray:
    """``GRID_SIZE`` points: ``i * ((high - low) / (GRID_SIZE - 1)) + low``.

    The last point is ``high`` itself. This is the specification's formula; it
    is also how ``numpy.linspace`` computes the points, so eegprep's grid is
    the same to the bit.
    """
    step = (high - low) / (GRID_SIZE - 1)
    axis = np.arange(GRID_SIZE) * step + low
    axis[-1] = high
    return axis


def outside_head(qx: np.ndarray, qy: np.ndarray) -> np.ndarray:
    """Cells beyond the head circle: ``sqrt(x * x + y * y) > HEAD_RADIUS``."""
    return np.sqrt(qx * qx + qy * qy) > HEAD_RADIUS


def green(d: np.ndarray) -> np.ndarray:
    """The biharmonic Green's function ``d * d * (ln(d) - 1)``, 0 where d is 0."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        g = (d * d) * (np.log(d) - 1)
    g[d == 0] = 0
    return g


def limits(z: np.ndarray) -> dict[str, tuple[float, float]]:
    """The color limits over the unmasked cells: ``absmax`` and ``minmax``."""
    cells = z[~np.isnan(z)]
    low, high = float(cells.min()), float(cells.max())
    top = max(abs(low), abs(high))
    return {"absmax": (-top, top), "minmax": (low, high)}


def color_axis(pair: tuple[float, float], rule: str) -> tuple[float, float]:
    """The color axis around the limits ``pair`` of the rule ``absmax`` or ``minmax``.

    ``absmax``: each limit moves 5% of its magnitude away from zero, as
    EEGLAB's ``caxis`` does; the limits have opposite signs, so both move
    outward. ``minmax``: both limits move outward by 5% of their range,
    ``(low - 0.05 * span, high + 0.05 * span)`` with ``span = high - low``, so
    a map of one sign keeps every cell inside the axis (EEGLAB's magnitude rule
    would move its limit nearer zero inward and clip the cells beside it).
    """
    low, high = pair
    if rule == "absmax":
        low, high = (v + np.sign(v) * COLOR_MARGIN * abs(v) for v in pair)
    else:
        span = high - low
        low, high = low - COLOR_MARGIN * span, high + COLOR_MARGIN * span
    return float(low) + 0.0, float(high) + 0.0


def is_flat(values: np.ndarray) -> bool:
    """A flat field: every usable sensor's value is equal, exactly.

    Its map is that value in every cell (the deviations from the mean are 0),
    and it carries the note :data:`FLAT_FIELD`.
    """
    return bool(values.min() == values.max())


def center(v: np.ndarray) -> float:
    """``m``, the mean of the interpolated values ``v``, in their order:
    ``v[0] + ((v[0] - v[0]) + (v[1] - v[0]) + ... + (v[n-1] - v[0])) / n``.

    Equal values give ``m`` equal to them exactly, so a flat field's deviations
    are exactly 0. The map interpolates the deviations ``v - m`` and adds ``m``
    back, so it is the same map, moved, whatever constant the values carry: the
    spline has no constant term, and a constant interpolated with it ripples.
    """
    first = float(v[0])
    total = 0.0
    for value in v:
        total += float(value) - first
    return first + total / len(v) + 0.0


def value_spread(values: np.ndarray) -> float:
    """The range of the usable values, ``max - min``, for the note's caption."""
    with np.errstate(over="ignore", invalid="ignore"):
        return float(values.max() - values.min()) + 0.0


def is_near_flat(values: np.ndarray) -> bool:
    """A near-flat field: the usable values' range is at most
    :data:`NEAR_FLAT` times their magnitude (the largest absolute value).

    Its map would be the spline of differences in the last digits, stretched
    over the whole color axis; it is drawn as one color at the mean instead,
    with the note :data:`NEAR_FLAT_NOTE`. A flat field (range 0) is not near
    flat: it has its own note.
    """
    spread = value_spread(values)
    magnitude = float(np.abs(values).max())
    return bool(0 < spread <= NEAR_FLAT * magnitude)


def contour_levels(z: np.ndarray) -> tuple[float, ...]:
    """``CONTOUR_COUNT`` levels evenly inside (min, max) of the cells ``z``;
    none for a constant map, a flat field among them."""
    cells = z[~np.isnan(z)]
    low, high = float(cells.min()), float(cells.max())
    if not low < high:
        return ()
    step = (high - low) / (CONTOUR_COUNT + 1)
    return tuple(float(k * step + low) for k in range(1, CONTOUR_COUNT + 1))


def sensor_field(
    theta_deg: np.ndarray, radius: np.ndarray, values: np.ndarray
) -> SensorField:
    """Draw ``nemar.sensor-field.v1`` for one value per sensor.

    ``theta_deg``, ``radius`` and ``values`` are one entry per sensor, in the
    layout's row order. Raises :class:`SensorFieldRefusal` with
    ``too_few_sensors``, ``head_outside_grid`` or ``interpolation_failed``.
    """
    theta_deg = np.asarray(theta_deg, dtype=np.float64)
    radius = np.asarray(radius, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if not theta_deg.shape == radius.shape == values.shape or values.ndim != 1:
        raise ValueError("theta_deg, radius and values are equal-length vectors")

    # 1. Usable sensors: a finite value, theta and radius.
    usable = np.isfinite(values) & np.isfinite(theta_deg) & np.isfinite(radius)
    rows = [int(i) for i in np.flatnonzero(usable)]
    if not rows:
        raise SensorFieldRefusal("too_few_sensors", "no sensor is usable")

    # 2. Planar positions, in raw layout units.
    x, y = planar(np.where(usable, theta_deg, 0), np.where(usable, radius, 0))

    # 4. Merge sensors within MERGE_DISTANCE of an earlier kept sensor.
    groups = merge(x, y, rows)
    kept = np.array(list(groups), dtype=np.int64)
    kept_values = np.array([mean(values, members) for members in groups.values()])

    # 3. Radii and squeeze, from every usable sensor, merged or not (the code
    # runs the merge first; the radii do not depend on it).
    outer = outermost(radius, rows)
    plotrad = max(min(1.0, outer * RADIUS_MARGIN), HEAD_RADIUS)
    intrad = min(1.0, outer * RADIUS_MARGIN)
    squeezefac = HEAD_RADIUS / plotrad

    # 5. Plotted and interpolated sensors.
    plotted = tuple(r for r in rows if is_plotted(radius[r], plotrad))
    inside = in_square(x[kept], y[kept], intrad)
    interpolated = kept[inside]
    if len(interpolated) < MIN_SENSORS:
        raise SensorFieldRefusal(
            "too_few_sensors",
            f"{len(interpolated)} interpolated sensor(s); a map needs {MIN_SENSORS}",
        )

    # 6. Squeeze.
    v = kept_values[inside]
    px = x[interpolated] * squeezefac
    py = y[interpolated] * squeezefac

    # 7. The grid, and whether any cell is inside the head.
    gx = grid_axis(
        min(-HEAD_RADIUS, float(px.min())), max(HEAD_RADIUS, float(px.max()))
    )
    gy = grid_axis(
        min(-HEAD_RADIUS, float(py.min())), max(HEAD_RADIUS, float(py.max()))
    )
    qx, qy = np.meshgrid(gx, gy, indexing="ij")
    masked = outside_head(qx, qy)
    if masked.all():
        raise SensorFieldRefusal(
            "head_outside_grid", "no grid cell lies inside the head circle"
        )

    # 8. The mean of the interpolated values, and whether the usable values
    # are flat (all equal) or near flat (their range at most NEAR_FLAT of
    # their magnitude): a near-flat map is its mean in every cell.
    m = center(v)
    flat = is_flat(values[rows])
    value_range = value_spread(values[rows])
    near_flat = not flat and is_near_flat(values[rows])
    if near_flat:
        z = np.full(qx.shape, m)
    else:
        # Biharmonic interpolation of the deviations from the mean: solve
        # G w = v - m. A flat field's deviations are exactly 0, so are its
        # weights, and every cell is m, its value: no special case draws it.
        d = np.hypot(px[:, None] - px[None, :], py[:, None] - py[None, :])
        with np.errstate(over="ignore", invalid="ignore"):
            w = lu_solve(green(d), v - m)

        # 9. Evaluation, with the mean added back. A weight that is not
        # finite (a zero pivot, or an overflow) makes the cells not finite, so
        # step 10's check serves.
        dq = np.hypot(qx[:, :, None] - px, qy[:, :, None] - py)
        with np.errstate(over="ignore", invalid="ignore"):
            z = m + green(dq) @ w
    # 10. The mask.
    z[masked] = np.nan
    if not np.isfinite(z[~masked]).all():
        raise SensorFieldRefusal("interpolation_failed", "a cell is not finite")

    # 11. Limits and 12. contours.
    lim = limits(z)
    return SensorField(
        plotrad=plotrad,
        intrad=intrad,
        squeezefac=squeezefac,
        x=gx,
        y=gy,
        z=z,
        plotted=plotted,
        interpolated=tuple(int(r) for r in interpolated),
        merged={int(k): tuple(m) for k, m in groups.items() if len(m) > 1},
        limits=lim,
        color_axis={name: color_axis(pair, name) for name, pair in lim.items()},
        contours=contour_levels(z),
        head=head_outline(squeezefac),
        notes=(FLAT_FIELD,) if flat else (NEAR_FLAT_NOTE,) if near_flat else (),
        value_range=value_range,
    )


def sensor_field_from_positions(
    xyz: np.ndarray,
    coordinate_system: str,
    values: np.ndarray,
    *,
    montage: str | None = None,
    names: list[str] | None = None,
    sensor_types: list[str | None] | None = None,
) -> SensorField:
    """Draw a map whose sensors are placed by three-dimensional positions.

    The view's role ``positions`` gives ``xyz`` (n by 3) with its
    ``coordinate_system``, or ``n/a`` and the ``montage`` for template
    positions, and its ``name`` and ``sensor_type`` columns. ``nemar.sensor-
    layout.v1`` projects the scalp rows to theta and radius, and
    :func:`sensor_field` draws the map; a row with no layout is dropped like
    any sensor without a place. Raises
    :class:`~neuroschema.views.sensor_layout.SensorLayoutRefusal`
    (``frame_unknown``, ``positions_flat`` or ``positions_partial``), after
    which a renderer places the sensors by name only when every drawn row is
    typed EEG, or :class:`SensorFieldRefusal`.
    """
    layout = sensor_layout(
        xyz, coordinate_system, montage=montage, names=names, sensor_types=sensor_types
    )
    return sensor_field(layout.theta_deg, layout.radius, values)
