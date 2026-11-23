"""``nemar.sensor-layout.v1``: three-dimensional sensor positions to a layout.

The Python reference for the transform ``docs/views/sensor-layout.md``
specifies: rotate the positions into the ALS frame (x anterior, y left, z
superior) from the frame their Brain Imaging Data Structure (BIDS) coordinate
system names, center them on an algebraic least-squares sphere (the centroid
when that fit is degenerate), and convert each to EEGLAB's ``topoplot`` theta
and radius as eegprep's ``convertlocs(..., 'cart2topo')`` does.
``views/vectors/sensor-layout.v1.json`` holds the cases every implementation
reproduces.

numpy only: install the ``views`` extra, and import this module itself;
``neuroschema.views`` does not import it, so it needs no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neuroschema.views.linalg import SingularMatrix, lu_solve

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
        "MNI152NLin6ASym",
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
"""BIDS coordinate systems with RAS orientation (x right, y anterior, z superior)."""

FIT_PIVOT = 1e-10
"""A sphere-fit pivot at most this share of the largest normal-equation entry
is degenerate."""

RAD = 180 / np.pi
"""Radians to degrees: 180 divided by the binary64 nearest pi."""


class SensorLayoutRefusal(ValueError):
    """Positions the transform refuses, with the word a renderer shows."""

    def __init__(self, word: str, detail: str) -> None:
        super().__init__(f"{word}: {detail}")
        self.word = word


@dataclass(frozen=True)
class SensorLayout:
    """A layout: one theta (degrees) and radius per input row.

    Rows without a finite position have NaN theta and radius. ``center`` is
    the ALS point the positions were centered on, and ``center_method`` says
    how it was found (``sphere`` or ``centroid``); both are None when no row
    has a finite position.
    """

    theta_deg: np.ndarray
    radius: np.ndarray
    center: tuple[float, float, float] | None
    center_method: str | None


def orientation(coordinate_system: str, montage: str | None = None) -> str:
    """``ALS`` or ``RAS``: the orientation of positions in a frame or a montage.

    Measured positions name their BIDS coordinate system. Template positions
    (a sensor role with ``position_source`` ``template``) name instead the
    montage of ``views/montages`` they were taken from (``nemar.sensor-labels.v1``),
    with the coordinate system ``n/a``; every montage file is RAS, in meters.
    Any other combination raises :class:`SensorLayoutRefusal`
    (``frame_unknown``): an unknown name, ``n/a`` without a montage, a name in
    another case, and a montage beside a coordinate system other than ``n/a``.
    No frame is assumed.
    """
    if montage is None:
        if coordinate_system in ALS_FRAMES:
            return "ALS"
        if coordinate_system in RAS_FRAMES:
            return "RAS"
        detail = (
            f"{coordinate_system!r} is not a BIDS coordinate system of known "
            "orientation"
        )
    elif coordinate_system == "n/a" and montage:
        return "RAS"
    else:
        detail = (
            f"template positions from montage {montage!r} name the coordinate "
            f"system {coordinate_system!r}, not n/a"
        )
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


def sphere_center(points: np.ndarray) -> tuple[np.ndarray, str]:
    """Center of the least-squares sphere through ``points`` (n by 3, finite).

    The points are translated to their centroid and scaled by the largest
    distance from it, and the algebraic fit
    ``x**2 + y**2 + z**2 = 2*a*x + 2*b*y + 2*c*z + d`` is solved from its 4-by-4
    normal equations by LU decomposition with partial pivoting. The fit is
    degenerate, and the centroid is returned, when the points all coincide or
    when a pivot is at most :data:`FIT_PIVOT` times the largest normal-equation
    entry: the points are coplanar, as any three or fewer are. The fitted
    squared radius needs no check: for centered points it is their mean
    squared distance from the center, which is positive.
    """
    n = len(points)
    centroid = points.sum(axis=0) / n
    centered = points - centroid
    scale = float(np.sqrt((centered * centered).sum(axis=1)).max())
    if scale == 0:
        return centroid, "centroid"
    u = centered / scale
    design = np.column_stack([2 * u, np.ones(n)])
    normal = design.T @ design
    rhs = design.T @ (u * u).sum(axis=1)
    try:
        a, b, c, _d = lu_solve(
            normal, rhs, tiny=FIT_PIVOT * float(np.abs(normal).max())
        )
    except SingularMatrix:
        return centroid, "centroid"
    return centroid + scale * np.array([a, b, c]), "sphere"


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
    xyz: np.ndarray, coordinate_system: str, *, montage: str | None = None
) -> SensorLayout:
    """Apply ``nemar.sensor-layout.v1`` to positions (n by 3).

    The positions are in the BIDS frame ``coordinate_system`` names, or, for
    template positions, in the frame of the ``montage`` they came from (with
    ``coordinate_system`` ``n/a``); see :func:`orientation`.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("positions are an n-by-3 array")
    als = to_als(xyz, coordinate_system, montage)
    finite = np.isfinite(als).all(axis=1)
    theta = np.full(len(als), np.nan)
    radius = np.full(len(als), np.nan)
    if not finite.any():
        return SensorLayout(theta, radius, None, None)
    center, method = sphere_center(als[finite])
    theta[finite], radius[finite] = cart2topo(als[finite] - center)
    return SensorLayout(theta, radius, tuple(float(v) for v in center), method)
