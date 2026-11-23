"""``nemar.sensor-field.v1``: the scalp map of one value per sensor.

The Python reference renderer for the algorithm ``docs/views/sensor-field.md``
specifies: EEGLAB's ``topoplot`` map (plotting and interpolation radii, squeeze,
a 67-by-67 grid, biharmonic interpolation, the head mask, limits and contours),
with the rules eegprep leaves implicit stated outright (sensors within 1e-3 of
an earlier one merge, fewer than three interpolated sensors draw no map, the
interpolation matrix is solved by LU decomposition with partial pivoting).
``views/vectors/sensor-field.v1.json`` holds the cases every implementation
reproduces, computed by eegprep at a pinned commit.

numpy only: install the ``views`` extra, and import this module itself;
``neuroschema.views`` does not import it, so it needs no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neuroschema.views.linalg import lu_solve

SENSOR_FIELD = "nemar.sensor-field.v1"

HEAD_RADIUS = 0.5
"""``rmax``: the head circle's radius on the grid; cells beyond it are masked."""
RADIUS_MARGIN = 1.02
"""The plotting and interpolation radii reach just past the outermost sensor."""
GRID_SIZE = 67
"""Grid points along each axis."""
MERGE_DISTANCE = 1e-3
"""Sensors this close (raw layout units) to an earlier kept sensor merge into it."""
MIN_SENSORS = 3
"""Fewer interpolated sensors than this draw no map."""
CONTOUR_COUNT = 6
"""Interior contour levels."""
COLOR_MARGIN = 0.05
"""Each color limit moves this share of its magnitude away from zero."""
DEG = np.pi / 180
"""Degrees to radians: the binary64 nearest pi, divided by 180."""


class SensorFieldRefusal(ValueError):
    """A map the algorithm refuses to draw, with the word a renderer shows."""

    def __init__(self, word: str, detail: str) -> None:
        super().__init__(f"{word}: {detail}")
        self.word = word


@dataclass(frozen=True)
class SensorField:
    """A drawn map: the grid, the masked values and the scalars around them.

    ``z[i, j]`` is the value at ``(x[i], y[j])`` in layout coordinates, where x
    points to the nose and y to the right ear; on screen, x runs up and y runs
    right. Cells outside the head circle are NaN. Sensor indices are row
    numbers of the input, counted from 0; ``merged`` maps each kept sensor
    that absorbed others to its whole group, itself first.
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


def planar(theta_deg: np.ndarray, radius: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Layout (theta in degrees, radius) to raw planar x (nose) and y (right ear)."""
    theta = np.asarray(theta_deg, dtype=np.float64) * DEG
    radius = np.asarray(radius, dtype=np.float64)
    return np.cos(theta) * radius, np.sin(theta) * radius


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
            if np.sqrt(dx * dx + dy * dy) <= MERGE_DISTANCE:
                groups[kept].append(row)
                break
        else:
            groups[row] = [row]
    return groups


def mean(values: np.ndarray, members: list[int]) -> float:
    """A merged sensor's value: the members' values summed in row order, over count."""
    total = 0.0
    for row in members:
        total += float(values[row])
    return total / len(members)


def in_square(x: np.ndarray, y: np.ndarray, intrad: float) -> np.ndarray:
    """EEGLAB's interpolation square: ``x <= intrad`` and ``y <= intrad``.

    There is no absolute value, so a sensor far behind the head or far to its
    left is still interpolated; EEGLAB's ``topoplot.m`` has the same test.
    """
    return (x <= intrad) & (y <= intrad)


def grid_axis(low: float, high: float) -> np.ndarray:
    """``GRID_SIZE`` points: ``i * ((high - low) / (GRID_SIZE - 1)) + low``.

    The last point is ``high`` itself, as ``numpy.linspace`` and MATLAB's
    ``linspace`` give it.
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


def color_axis(pair: tuple[float, float]) -> tuple[float, float]:
    """EEGLAB's color axis: each limit moved 5% of its magnitude away from zero."""
    low, high = (float(v + np.sign(v) * COLOR_MARGIN * abs(v)) for v in pair)
    return low, high


def contour_levels(z: np.ndarray) -> tuple[float, ...]:
    """``CONTOUR_COUNT`` levels evenly inside (min, max); none for a constant map."""
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

    # 3. Merge sensors within MERGE_DISTANCE of an earlier kept sensor.
    groups = merge(x, y, rows)
    kept = np.array(list(groups), dtype=np.int64)
    kept_values = np.array([mean(values, members) for members in groups.values()])

    # 4. Radii and squeeze, from the kept sensors.
    outer = float(radius[kept].max())
    plotrad = max(min(1.0, outer * RADIUS_MARGIN), HEAD_RADIUS)
    intrad = min(1.0, outer * RADIUS_MARGIN)
    squeezefac = HEAD_RADIUS / plotrad

    # 5. Plotted and interpolated sensors.
    plotted = tuple(r for r in rows if radius[r] <= plotrad)
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

    # 8. Biharmonic interpolation: solve G w = v.
    d = np.hypot(px[:, None] - px[None, :], py[:, None] - py[None, :])
    w = lu_solve(green(d), v)
    if not np.isfinite(w).all():
        raise SensorFieldRefusal("interpolation_failed", "a weight is not finite")

    # 9. Evaluation, and 10. the mask.
    dq = np.hypot(qx[:, :, None] - px, qy[:, :, None] - py)
    with np.errstate(over="ignore", invalid="ignore"):
        z = green(dq) @ w
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
        color_axis={name: color_axis(pair) for name, pair in lim.items()},
        contours=contour_levels(z),
    )
