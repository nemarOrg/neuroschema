"""``nemar.sensor-layout.v1``: three-dimensional sensor positions to a layout.

The Python reference for the transform ``docs/views/sensor-layout.md``
specifies: rotate the positions into the ALS frame (x anterior, y left, z
superior) from the frame their Brain Imaging Data Structure (BIDS) coordinate
system names, keep the scalp rows (EEG sensors, never fiducials or other
channels), center them (template positions on their montage's own center;
measured positions on an algebraic least-squares sphere through the scalp
rows, refusing positions too flat to fix one or covering too little of the
head), and convert each to EEGLAB's ``topoplot`` theta and radius as eegprep's
``convertlocs(..., 'cart2topo')`` does.
``views/vectors/sensor-layout.v1.json`` holds the cases every implementation
reproduces.

numpy only: install the ``views`` extra, and import this module itself;
``neuroschema.views`` does not import it, so it needs no numpy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from neuroschema.views.linalg import lu_solve
from neuroschema.views.sensor_labels import (
    FIDUCIALS,
    MONTAGE_NAMES,
    clean,
    excluded_by_name,
    finish,
    type_class,
)

MONTAGES = Path(__file__).resolve().parents[3] / "views" / "montages"

SENSOR_LAYOUT = "nemar.sensor-layout.v1"

ALS_FRAMES = frozenset({"CTF", "4DBti", "KitYokogawa", "EEGLAB", "EEGLAB-HJ"})
"""BIDS coordinate systems with ALS orientation (x anterior, y left, z superior)."""

RAS_FRAMES = frozenset(
    {
        # MEG and EEG systems with RAS orientation.
        "NeuromagElektaMEGIN",
        "ElektaNeuromag",
        "ChietiItab",
        "CapTrak",
        # iEEG systems.
        "ACPC",
        "ScanRAS",
        # Standard template identifiers.
        "ICBM452AirSpace",
        "ICBM452Warp5Space",
        "IXI549Space",
        "fsaverage",
        "fsaverageSym",
        "fsLR",
        "MNIColin27",
        "MNI152Lin",
        "MNI152NLin2009aSym",
        "MNI152NLin2009bSym",
        "MNI152NLin2009cSym",
        "MNI152NLin2009aAsym",
        "MNI152NLin2009bAsym",
        "MNI152NLin2009cAsym",
        "MNI152NLin6Sym",
        "MNI152NLin6Asym",
        "MNI305",
        "NIHPD",
        "OASIS30AntsOASISAnts",
        "OASIS30Atropos",
        "Talairach",
        "UNCInfant",
        # Deprecated template identifiers BIDS still accepts.
        "fsaverage3",
        "fsaverage4",
        "fsaverage5",
        "fsaverage6",
        "fsaveragesym",
        *(f"UNCInfant{age}V{version}" for age in "012" for version in (21, 22, 23)),
    }
)
"""BIDS coordinate systems with RAS orientation (x right, y anterior, z superior),
spelled as the BIDS schema's enumerations spell them."""

FRAME_ALIASES = {"MNI152NLin6ASym": "MNI152NLin6Asym"}
"""Other spellings BIDS uses for a frame, each to the schema's spelling: its
coordinate-systems appendix writes MNI152NLin6ASym where its schema enum,
``src/schema/objects/enums.yaml``, writes MNI152NLin6Asym (both at the BIDS
specification's commit 147b46d7)."""

FLAT_RATIO = 0.05
"""Measured positions are flat when the smallest singular value of their
centered, scaled coordinates is below this share of the largest."""

RADIUS_RATIO = 3.0
"""Measured positions are flat when their fitted sphere's radius is above this
many times their scale."""

PARTIAL_DILUTION = 4.5
"""Measured positions cover too little of the head when the dilution of their
fitted center (:func:`dilution`) is above this; see
``docs/views/sensor-layout.md``, step 3, for the sets it was measured on."""

PARTIAL_SHIFT = 0.12
"""Measured positions are too unstable to fix the head's center when leaving
out any one of them moves the fitted center by more than this share of the
fitted radius (:func:`stability`); see ``docs/views/sensor-layout.md``."""

COVERAGE_ELEVATION = 38.0
"""Measured positions do not cover the whole head when some quadrant about the
fitted center, front, left, back or right, has no position at most this many
degrees above the equator (:func:`coverage`); see
``docs/views/sensor-layout.md``, step 3."""

GAP_AZIMUTH = 120.0
"""Measured positions do not go all around the head when two neighbors, in
azimuth about the vertical through the fitted center, are more than this many
degrees apart (:func:`azimuth_gap`)."""

RAD = 180 / np.pi
"""Radians to degrees: 180 divided by the binary64 nearest pi."""


class SensorLayoutRefusal(ValueError):
    """Positions the transform refuses, with the word a renderer shows.

    A ``positions_flat`` or ``positions_partial`` refusal also carries the
    measures it reached (``singular_ratio``, ``radius_ratio``, ``dilution``,
    ``stability``, ``coverage``, ``gap``, None where not reached).
    """

    def __init__(
        self,
        word: str,
        detail: str,
        singular_ratio: float | None = None,
        radius_ratio: float | None = None,
        dilution: float | None = None,
        stability: float | None = None,
        coverage: float | None = None,
        gap: float | None = None,
    ) -> None:
        super().__init__(f"{word}: {detail}")
        self.word = word
        self.singular_ratio = singular_ratio
        self.radius_ratio = radius_ratio
        self.dilution = dilution
        self.stability = stability
        self.coverage = coverage
        self.gap = gap


@dataclass(frozen=True)
class SensorLayout:
    """A layout: one theta (degrees) and radius per input row.

    Rows that are not scalp rows, and rows without a position, have NaN theta
    and radius. ``center`` is the ALS point the positions were centered on,
    and ``center_method`` says how it was found: ``montage`` (template
    positions: the montage's own center) or ``sphere`` (measured positions:
    the sphere fitted to the scalp rows). For measured positions,
    ``singular_ratio``, ``radius_ratio``, ``dilution``, ``stability``,
    ``coverage`` and ``gap`` are the six measures :func:`sphere_center`
    bounds; all are None for template positions.
    """

    theta_deg: np.ndarray
    radius: np.ndarray
    center: tuple[float, float, float]
    center_method: str
    singular_ratio: float | None
    radius_ratio: float | None
    dilution: float | None
    stability: float | None
    coverage: float | None
    gap: float | None


def orientation(coordinate_system: str, montage: str | None = None) -> str:
    """``ALS`` or ``RAS``: the orientation of positions in a frame or a montage.

    Measured positions name their BIDS coordinate system. Template positions
    (a sensor role with ``position_source`` ``template``) name instead the
    montage they were taken from, exactly as ``nemar.sensor-labels.v1`` lists
    it (:data:`~neuroschema.views.sensor_labels.MONTAGE_NAMES`), with the
    coordinate system ``n/a``; every montage file is RAS, in meters.
    Any other combination raises :class:`SensorLayoutRefusal`
    (``frame_unknown``): an unknown name, ``n/a`` without a montage, a frame
    or a montage named in another case, a montage the list does not have
    (``PROVENANCE`` included, whatever the files beside the montages are),
    and a montage beside a coordinate system other than ``n/a``.
    A name of :data:`FRAME_ALIASES` is read as the name it maps to. No frame is
    assumed.
    """
    if montage is None:
        coordinate_system = FRAME_ALIASES.get(coordinate_system, coordinate_system)
        if coordinate_system in ALS_FRAMES:
            return "ALS"
        if coordinate_system in RAS_FRAMES:
            return "RAS"
        detail = (
            f"{coordinate_system!r} is not a BIDS coordinate system of known "
            "orientation"
        )
    elif coordinate_system != "n/a":
        detail = (
            f"template positions from montage {montage!r} name the coordinate "
            f"system {coordinate_system!r}, not n/a"
        )
    elif montage in MONTAGE_NAMES:
        return "RAS"
    else:
        detail = f"{montage!r} is not a montage of nemar.sensor-labels.v1"
    raise SensorLayoutRefusal("frame_unknown", detail)


def to_als(
    xyz: np.ndarray, coordinate_system: str, montage: str | None = None
) -> np.ndarray:
    """Positions rotated into ALS from the frame :func:`orientation` gives.

    ALS positions are kept as they are; RAS positions become ALS as
    ``(x, y, z) -> (y, -x, z)``, the second component negated.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if orientation(coordinate_system, montage) == "ALS":
        return xyz.copy()
    return np.stack([xyz[:, 1], -xyz[:, 0], xyz[:, 2]], axis=1)


def _flat(
    detail: str, singular_ratio: float | None = None, radius_ratio: float | None = None
) -> SensorLayoutRefusal:
    return SensorLayoutRefusal("positions_flat", detail, singular_ratio, radius_ratio)


def scalp_rows(
    count: int,
    names: list[str] | None = None,
    sensor_types: list[str | None] | None = None,
) -> np.ndarray:
    """Which of ``count`` rows are scalp rows: the sensors a scalp map draws.

    When any row has a sensor type (not absent, empty or ``n/a``, compared as
    ``nemar.sensor-labels.v1`` compares a channel type), the scalp rows are
    the rows typed EEG. When no row has one, every row is a scalp row but one
    whose name starts with a non-EEG prefix of ``nemar.sensor-labels.v1``
    (``EOG1``, ``ECG``). In either case a row named as a fiducial (Nz, LPA,
    RPA, NAS, inion, normalized as that algorithm normalizes a name) is not a
    scalp row.
    """
    keep = np.ones(count, dtype=bool)
    classes = [type_class(t) for t in sensor_types] if sensor_types else []
    if any(c != "untyped" for c in classes):
        keep &= np.array([c == "eeg" for c in classes], dtype=bool)
    elif names is not None:
        keep &= np.array([not excluded_by_name(clean(n)) for n in names], dtype=bool)
    if names is not None:
        keep &= np.array([finish(clean(n)) not in FIDUCIALS for n in names], dtype=bool)
    return keep


def has_position(xyz: np.ndarray) -> np.ndarray:
    """Rows with a position: x, y and z finite, and not all three exactly zero.

    A row at exactly (0, 0, 0), with either sign of zero, is how many files
    write a position they do not have; no sensor sits at a frame's origin.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    return np.isfinite(xyz).all(axis=1) & ~(xyz == 0).all(axis=1)


def dilution(directions: np.ndarray) -> float:
    """The dilution of a fitted center, from the unit vectors to the positions.

    With each unit vector ``e`` (pointing from the center to one position) and
    the 4-by-4 matrix ``M``, the mean of ``[e, 1]`` times its transpose, the
    dilution is the square root of the sum of the first three diagonal entries
    of ``M`` inverted (each column solved by LU decomposition with partial
    pivoting). It depends only on the directions from the fitted center: 3
    for an even cover of a sphere, ``sqrt(18)`` (4.24) for one of a
    hemisphere, and more as the directions bunch together or lie on one band.
    For independent radial noise of a share ``sigma`` of the radius it gives
    the center's root mean square error, about ``dilution * sigma / sqrt(n)``
    radii; a real head departs from a sphere systematically, which it does not
    predict. A singular ``M`` gives a value that is not finite.
    """
    n = len(directions)
    augmented = np.column_stack([directions, np.ones(n)])
    moments = augmented.T @ augmented / n
    total = 0.0
    for k in range(3):
        unit = np.zeros(4)
        unit[k] = 1.0
        total += float(lu_solve(moments, unit)[k])
    with np.errstate(invalid="ignore"):
        return float(np.sqrt(total))


def stability(
    design: np.ndarray, target: np.ndarray, solution: np.ndarray, radius: float
) -> float:
    """The largest move of the fitted center when one position is left out, as
    a share of the fitted radius.

    ``design`` and ``target`` are the sphere's least-squares rows and values
    (:func:`sphere_center`), ``solution`` its ``(a, b, c, d)`` and ``radius``
    its radius, all in the scaled coordinates. For each row ``k``, the normal
    equations without that row, ``(AᵀA - a_k a_kᵀ) w = Aᵀb - a_k b_k``, are
    solved by LU decomposition with partial pivoting, and the move is the
    Euclidean length of the first three entries of ``w`` minus the
    solution's. A set whose reduced equations are singular gives a value that
    is not finite.
    """
    normal = design.T @ design
    right = design.T @ target
    moves = np.empty(len(design))
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        for k, row in enumerate(design):
            left_out = lu_solve(normal - np.outer(row, row), right - row * target[k])
            moves[k] = np.sqrt(((left_out[:3] - solution[:3]) ** 2).sum()) / radius
    return float(np.max(moves))


def quadrants(spokes: np.ndarray) -> np.ndarray:
    """The quadrant of each unit vector from the fitted center (ALS): 0 front,
    1 left, 2 back, 3 right, or -1 for a vector on the vertical axis.

    With ``x`` anterior and ``y`` left, front is ``x > |y|``, back ``-x > |y|``,
    left ``y >= |x|`` with ``y > 0`` and right ``-y >= |x|`` with ``y < 0``: in
    azimuth from the anterior axis toward the left, front is (-45, 45) degrees,
    left [45, 135], back (135, 225) and right [225, 315], so a vector on a
    diagonal is a side's.
    """
    x, y = spokes[:, 0], spokes[:, 1]
    out = np.full(len(spokes), -1)
    out[(y >= np.abs(x)) & (y > 0)] = 1
    out[(-y >= np.abs(x)) & (y < 0)] = 3
    out[x > np.abs(y)] = 0
    out[-x > np.abs(y)] = 2
    return out


def elevations(spokes: np.ndarray) -> np.ndarray:
    """Degrees above the plane through the fitted center normal to the frame's
    superior axis: ``atan2(z, hypot(x, y))`` of each unit vector."""
    return np.arctan2(spokes[:, 2], np.hypot(spokes[:, 0], spokes[:, 1])) * RAD


def coverage(spokes: np.ndarray) -> float:
    """How low the positions reach on every side of the head, in degrees.

    For each quadrant (:func:`quadrants`), the lowest elevation
    (:func:`elevations`) of its unit vectors, 90 when it has none; the
    coverage is the largest of the four. Positions above the equator in
    every quadrant, reaching at most ``c`` degrees above it on each side (or
    below it), have coverage ``c``; a set that covers only the top of the
    head, or misses a side, has a large one. It depends on the frame's
    anterior and superior axes and, unlike the other measures, changes when
    the positions are turned about the vertical axis.
    """
    quadrant = quadrants(spokes)
    height = elevations(spokes)
    lowest = [
        float(height[quadrant == k].min()) if (quadrant == k).any() else 90.0
        for k in range(4)
    ]
    return max(lowest)


def azimuth_gap(spokes: np.ndarray) -> float:
    """The widest azimuth between neighboring positions about the vertical
    axis through the fitted center, in degrees.

    Each unit vector off the vertical axis has the azimuth
    ``atan2(y, x)`` (ALS, degrees); sorted, the gaps are the differences of
    neighbors and 360 minus the last less the first. With fewer than two
    azimuths the gap is 360. It is unchanged by any turn about the vertical
    axis.
    """
    off_axis = np.hypot(spokes[:, 0], spokes[:, 1]) > 0
    azimuth = np.sort(np.arctan2(spokes[off_axis, 1], spokes[off_axis, 0]) * RAD)
    if len(azimuth) < 2:
        return 360.0
    gaps = np.diff(azimuth)
    return float(max(gaps.max(), 360.0 - (azimuth[-1] - azimuth[0])))


@dataclass(frozen=True)
class Fit:
    """A sphere fitted to measured positions, with its six measures."""

    center: np.ndarray
    singular_ratio: float
    radius_ratio: float
    dilution: float
    stability: float
    coverage: float
    gap: float


def sphere_center(points: np.ndarray) -> Fit:
    """The center of measured positions ``points`` (n by 3, finite, ALS).

    The points are translated to their centroid ``c0`` and scaled by ``s``, the
    largest distance from it, giving ``u``. They are flat, and raise
    :class:`SensorLayoutRefusal` (``positions_flat``), when ``s`` is 0, when the
    smallest singular value of ``u`` is below :data:`FLAT_RATIO` times the
    largest (the square roots of the eigenvalues of the 3-by-3 ``u.T @ u``),
    or when the least-squares sphere through them has a radius above
    :data:`RADIUS_RATIO` times ``s``. The sphere
    ``x**2 + y**2 + z**2 = 2*a*x + 2*b*y + 2*c*z + d`` is solved from its 4-by-4
    normal equations by LU decomposition with partial pivoting; its center is
    ``c0 + s * (a, b, c)`` and its radius, in units of ``s``,
    ``sqrt(a*a + b*b + c*c + d)``. Both bounds are scale-invariant: real caps
    and their usual subsets measure a singular ratio of 0.12 or more and a
    radius ratio of 1.6 or less, while a midline or a row of sensors measures
    about 1e-5 and 16 to 1500, so the bounds refuse what fixes no head.
    Last, they cover too little of the head, and raise ``positions_partial``,
    when the :func:`dilution` of the center (from the unit vectors
    ``u - (a, b, c)``, normalized) is above :data:`PARTIAL_DILUTION`, when
    leaving out one of them moves the center by more than
    :data:`PARTIAL_SHIFT` of the radius (:func:`stability`), when some
    quadrant has no position within :data:`COVERAGE_ELEVATION` degrees of
    the equator (:func:`coverage`), or when two neighbors in azimuth are more
    than :data:`GAP_AZIMUTH` degrees apart (:func:`azimuth_gap`): the whole
    head, all around and low on every side.
    """
    n = len(points)
    centroid = points.sum(axis=0) / max(n, 1)
    centered = points - centroid
    scale = float(np.sqrt((centered * centered).sum(axis=1)).max()) if n else 0.0
    if scale == 0:
        raise _flat("the positions coincide, or there are none")
    u = centered / scale
    eigen = np.clip(np.linalg.eigvalsh(u.T @ u), 0, None)
    singular_ratio = float(np.sqrt(eigen[0] / eigen[-1]))
    if not singular_ratio >= FLAT_RATIO:
        raise _flat(
            f"the positions are flat: their singular ratio {singular_ratio:.3g} is "
            f"below {FLAT_RATIO}",
            singular_ratio,
        )
    design = np.column_stack([2 * u, np.ones(n)])
    target = (u * u).sum(axis=1)
    solution = lu_solve(design.T @ design, design.T @ target)
    a, b, c, d = solution
    radius_ratio = float(np.sqrt(a * a + b * b + c * c + d))
    if not radius_ratio <= RADIUS_RATIO:
        raise _flat(
            f"the positions are too flat: their sphere's radius is "
            f"{radius_ratio:.3g} times their scale, above {RADIUS_RATIO}",
            singular_ratio,
            radius_ratio,
        )
    spokes = u - np.array([a, b, c])
    with np.errstate(invalid="ignore", divide="ignore"):
        spokes = spokes / np.sqrt((spokes * spokes).sum(axis=1))[:, None]
    spread = dilution(spokes)
    if not spread <= PARTIAL_DILUTION:
        raise SensorLayoutRefusal(
            "positions_partial",
            f"the positions cover too little of the head: the dilution of their "
            f"center is {spread:.3g}, above {PARTIAL_DILUTION}",
            singular_ratio,
            radius_ratio,
            spread,
        )
    shift = stability(design, target, solution, radius_ratio)
    if not shift <= PARTIAL_SHIFT:
        raise SensorLayoutRefusal(
            "positions_partial",
            f"the positions do not fix the head's center: leaving one out moves "
            f"it {shift:.3g} of the radius, above {PARTIAL_SHIFT}",
            singular_ratio,
            radius_ratio,
            spread,
            shift,
        )
    reach = coverage(spokes)
    if not reach <= COVERAGE_ELEVATION:
        raise SensorLayoutRefusal(
            "positions_partial",
            f"the positions do not cover the whole head: some quadrant's lowest "
            f"position is {reach:.3g} degrees above the equator, above "
            f"{COVERAGE_ELEVATION}",
            singular_ratio,
            radius_ratio,
            spread,
            shift,
            reach,
        )
    widest = azimuth_gap(spokes)
    if not widest <= GAP_AZIMUTH:
        raise SensorLayoutRefusal(
            "positions_partial",
            f"the positions do not go around the head: two neighbors are "
            f"{widest:.3g} degrees apart in azimuth, above {GAP_AZIMUTH}",
            singular_ratio,
            radius_ratio,
            spread,
            shift,
            reach,
            widest,
        )
    return Fit(
        centroid + scale * np.array([a, b, c]),
        singular_ratio,
        radius_ratio,
        spread,
        shift,
        reach,
        widest,
    )


def montage_center(montage: str, directory: Path = MONTAGES) -> np.ndarray:
    """A montage's own center, RAS meters, as ``views/montages/<name>.json``
    stores it: the sphere fitted to all its electrodes (``nemar.sensor-labels.v1``
    generates the files). The name is matched exactly against that algorithm's
    montage list, never through the file system (which may fold case): any
    other name raises ``frame_unknown``."""
    if montage not in MONTAGE_NAMES:
        raise SensorLayoutRefusal(
            "frame_unknown", f"{montage!r} is not a montage of nemar.sensor-labels.v1"
        )
    document = json.loads((directory / f"{montage}.json").read_text(encoding="utf-8"))
    return np.array(document["center"], dtype=np.float64)


def center_of(
    points: np.ndarray, coordinate_system: str, montage: str | None
) -> tuple[np.ndarray, str, Fit | None]:
    """The center of ALS ``points``: (center, method, the fit or None).

    Template positions (a ``montage``) take the montage's own center, rotated
    into ALS, and are never fitted: a subset of a montage, such as its
    midline, fixes no sphere of its own. Measured positions take the sphere
    fitted to all of them (:func:`sphere_center`), which also bounds how flat
    and how partial they may be.
    """
    if montage is not None:
        center = montage_center(montage)[None, :]
        return to_als(center, coordinate_system, montage)[0], "montage", None
    fit = sphere_center(points)
    return fit.center, "sphere", fit


def cart2topo(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centered ALS positions to topoplot theta (degrees) and radius.

    ``theta = -atan2(y, x)`` in degrees, written in (-180, 180] (so -180 is
    180), and ``radius = 0.5 - elevation / 180`` with the elevation
    ``atan2(z, hypot(x, y))`` in degrees: eegprep's
    ``convertlocs(..., 'cart2topo')``.
    """
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    theta = -(np.arctan2(y, x) * RAD)
    theta = np.where(theta <= -180, theta + 360, theta)
    radius = 0.5 - (np.arctan2(z, np.hypot(x, y)) * RAD) / 180
    return theta, radius


def sensor_layout(
    xyz: np.ndarray,
    coordinate_system: str,
    *,
    montage: str | None = None,
    names: list[str] | None = None,
    sensor_types: list[str | None] | None = None,
) -> SensorLayout:
    """Apply ``nemar.sensor-layout.v1`` to positions (n by 3).

    The positions are in the BIDS frame ``coordinate_system`` names, or, for
    template positions, in the frame of the ``montage`` they came from (with
    ``coordinate_system`` ``n/a``); see :func:`orientation`. ``names`` and
    ``sensor_types`` (the role's ``name`` and ``sensor_type`` columns, one per
    row) choose the scalp rows (:func:`scalp_rows`); every other row, and
    every row without a position (:func:`has_position`), has no layout.
    Template positions are centered on the montage's own center
    (:func:`montage_center`), never on a sphere fitted to the subset given;
    measured positions are centered on the sphere fitted to every scalp row
    with a position (:func:`sphere_center`), so the rows should be all of the
    recording's measured positions. Raises :class:`SensorLayoutRefusal` with
    ``frame_unknown``, ``positions_flat`` or ``positions_partial``, after
    which a renderer places the sensors by name only when every drawn row is
    typed EEG.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("positions are an n-by-3 array")
    for column, values in (("names", names), ("sensor_types", sensor_types)):
        if values is not None and len(values) != len(xyz):
            raise ValueError(f"{column} has {len(values)} entries for {len(xyz)} rows")
    als = to_als(xyz, coordinate_system, montage)
    rows = has_position(als) & scalp_rows(len(als), names, sensor_types)
    theta = np.full(len(als), np.nan)
    radius = np.full(len(als), np.nan)
    center, method, fit = center_of(als[rows], coordinate_system, montage)
    theta[rows], radius[rows] = cart2topo(als[rows] - center)
    return SensorLayout(
        theta,
        radius,
        tuple(float(v) for v in center),
        method,
        None if fit is None else fit.singular_ratio,
        None if fit is None else fit.radius_ratio,
        None if fit is None else fit.dilution,
        None if fit is None else fit.stability,
        None if fit is None else fit.coverage,
        None if fit is None else fit.gap,
    )
