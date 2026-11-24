"""``nemar.sensor-layout.v1``: three-dimensional sensor positions to a layout.

The Python reference for the transform ``docs/views/sensor-layout.md``
specifies: rotate the positions into the ALS frame (x anterior, y left, z
superior) from the frame their Brain Imaging Data Structure (BIDS) coordinate
system names, center them (template positions on their montage's own center;
measured positions on an algebraic least-squares sphere through all of them,
refusing positions too flat to fix one), and convert each to EEGLAB's
``topoplot`` theta and radius as eegprep's ``convertlocs(..., 'cart2topo')``
does.
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
from neuroschema.views.sensor_labels import MONTAGE_ORDER

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

FLAT_RATIO = 0.05
"""Measured positions are flat when the smallest singular value of their
centered, scaled coordinates is below this share of the largest."""

RADIUS_RATIO = 3.0
"""Measured positions are flat when their fitted sphere's radius is above this
many times their scale."""

RAD = 180 / np.pi
"""Radians to degrees: 180 divided by the binary64 nearest pi."""


class SensorLayoutRefusal(ValueError):
    """Positions the transform refuses, with the word a renderer shows.

    A ``positions_flat`` refusal also carries the flatness measures it reached
    (``singular_ratio``, ``radius_ratio``, None where not reached).
    """

    def __init__(
        self,
        word: str,
        detail: str,
        singular_ratio: float | None = None,
        radius_ratio: float | None = None,
    ) -> None:
        super().__init__(f"{word}: {detail}")
        self.word = word
        self.singular_ratio = singular_ratio
        self.radius_ratio = radius_ratio


@dataclass(frozen=True)
class SensorLayout:
    """A layout: one theta (degrees) and radius per input row.

    Rows without a finite position have NaN theta and radius. ``center`` is
    the ALS point the positions were centered on, and ``center_method`` says
    how it was found: ``montage`` (template positions: the montage's own
    center) or ``sphere`` (measured positions: the sphere fitted to them).
    For measured positions, ``singular_ratio`` and ``radius_ratio`` are the
    two flatness measures :func:`sphere_center` bounds; both are None for
    template positions.
    """

    theta_deg: np.ndarray
    radius: np.ndarray
    center: tuple[float, float, float]
    center_method: str
    singular_ratio: float | None
    radius_ratio: float | None


def orientation(coordinate_system: str, montage: str | None = None) -> str:
    """``ALS`` or ``RAS``: the orientation of positions in a frame or a montage.

    Measured positions name their BIDS coordinate system. Template positions
    (a sensor role with ``position_source`` ``template``) name instead the
    montage they were taken from, exactly as ``nemar.sensor-labels.v1`` lists
    it (:data:`~neuroschema.views.sensor_labels.MONTAGE_ORDER`), with the
    coordinate system ``n/a``; every montage file is RAS, in meters.
    Any other combination raises :class:`SensorLayoutRefusal`
    (``frame_unknown``): an unknown name, ``n/a`` without a montage, a frame
    or a montage named in another case, a montage the list does not have
    (``PROVENANCE`` included, whatever the files beside the montages are),
    and a montage beside a coordinate system other than ``n/a``.
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
    elif coordinate_system != "n/a":
        detail = (
            f"template positions from montage {montage!r} name the coordinate "
            f"system {coordinate_system!r}, not n/a"
        )
    elif montage in MONTAGE_ORDER:
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


@dataclass(frozen=True)
class Fit:
    """A sphere fitted to measured positions, with its two flatness measures."""

    center: np.ndarray
    singular_ratio: float
    radius_ratio: float


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
    a, b, c, d = lu_solve(design.T @ design, design.T @ (u * u).sum(axis=1))
    radius_ratio = float(np.sqrt(a * a + b * b + c * c + d))
    if not radius_ratio <= RADIUS_RATIO:
        raise _flat(
            f"the positions are too flat: their sphere's radius is "
            f"{radius_ratio:.3g} times their scale, above {RADIUS_RATIO}",
            singular_ratio,
            radius_ratio,
        )
    return Fit(centroid + scale * np.array([a, b, c]), singular_ratio, radius_ratio)


def montage_center(montage: str, directory: Path = MONTAGES) -> np.ndarray:
    """A montage's own center, RAS meters, as ``views/montages/<name>.json``
    stores it: the sphere fitted to all its electrodes (``nemar.sensor-labels.v1``
    generates the files). The name is matched exactly against that algorithm's
    montage list, never through the file system (which may fold case): any
    other name raises ``frame_unknown``."""
    if montage not in MONTAGE_ORDER:
        raise SensorLayoutRefusal(
            "frame_unknown", f"{montage!r} is not a montage of nemar.sensor-labels.v1"
        )
    document = json.loads((directory / f"{montage}.json").read_text(encoding="utf-8"))
    return np.array(document["center"], dtype=np.float64)


def center_of(
    points: np.ndarray, coordinate_system: str, montage: str | None
) -> tuple[np.ndarray, str, float | None, float | None]:
    """The center of ALS ``points``: (center, method, singular_ratio, radius_ratio).

    Template positions (a ``montage``) take the montage's own center, rotated
    into ALS, and are never fitted: a subset of a montage, such as its
    midline, fixes no sphere of its own. Measured positions take the sphere
    fitted to all of them (:func:`sphere_center`).
    """
    if montage is not None:
        center = montage_center(montage)[None, :]
        return to_als(center, coordinate_system, montage)[0], "montage", None, None
    fit = sphere_center(points)
    return fit.center, "sphere", fit.singular_ratio, fit.radius_ratio


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
    ``coordinate_system`` ``n/a``); see :func:`orientation`. Template positions
    are centered on the montage's own center (:func:`montage_center`), never
    on a sphere fitted to the subset given; measured positions are centered on
    the sphere fitted to every row with a finite position (:func:`sphere_center`),
    so the rows should be all of the recording's measured positions. Raises
    :class:`SensorLayoutRefusal` with ``frame_unknown`` or ``positions_flat``,
    after which a renderer places the sensors by name.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("positions are an n-by-3 array")
    als = to_als(xyz, coordinate_system, montage)
    finite = np.isfinite(als).all(axis=1)
    theta = np.full(len(als), np.nan)
    radius = np.full(len(als), np.nan)
    center, method, singular_ratio, radius_ratio = center_of(
        als[finite], coordinate_system, montage
    )
    theta[finite], radius[finite] = cart2topo(als[finite] - center)
    return SensorLayout(
        theta,
        radius,
        tuple(float(v) for v in center),
        method,
        singular_ratio,
        radius_ratio,
    )
