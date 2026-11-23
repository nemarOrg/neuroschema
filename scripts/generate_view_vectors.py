"""Generate the sensor-field and sensor-layout vectors from eegprep, the reference.

Writes ``views/vectors/sensor-field.v1.json`` and
``views/vectors/sensor-layout.v1.json``. With ``--check`` it writes nothing:
it regenerates both in memory and fails if they differ from the committed
files beyond the regeneration tolerance (numbers may move in the last bits
between linear algebra libraries; everything else must match exactly).

Run with the ``vectors`` dependency group, which installs eegprep at the
pinned commit (Python 3.12 or later)::

    uv run --group vectors python scripts/generate_view_vectors.py --check

The rules the reference needs beyond eegprep (dropping sensors that are not
finite, merging near sensors, the frame table and the sphere fit) are written
here a second time, independently of ``neuroschema.views``: the tests hold the
Python reference renderer to these vectors, so the two copies check each other.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.resources
import json
import math
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "views" / "vectors"
EEGPREP_COMMIT = "edf694c8344b9c4c68672eac3acf9a819f1462a8"
EEGPREP_REPOSITORY = "https://github.com/sccn/eegprep"
BIDS_SPEC = (
    "https://github.com/bids-standard/bids-specification/blob/"
    "147b46d771cd2b35b31a72b1f1bd1d7dc2d5a88a/src/appendices/coordinate-systems.md"
)

# Regeneration tolerance for --check: far inside the parity tolerance, wide
# enough for LAPACK and BLAS builds that round differently.
CHECK_CELLS = 1e-9
CHECK_SCALARS = 1e-12

GRID = 67
MERGE = 1e-3

# The BIDS frame table, from the coordinate-systems appendix (BIDS_SPEC).
ALS = ["CTF", "4DBti", "KitYokogawa", "EEGLAB", "EEGLAB-HJ"]
RAS = [
    "NeuromagElektaMEGIN",
    "ElektaNeuromag",
    "ChietiItab",
    "CapTrak",
    "ACPC",
    "ScanRAS",
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
    "fsaverage3",
    "fsaverage4",
    "fsaverage5",
    "fsaverage6",
    "fsaveragesym",
    "UNCInfant0V21",
    "UNCInfant0V22",
    "UNCInfant0V23",
    "UNCInfant1V21",
    "UNCInfant1V22",
    "UNCInfant1V23",
    "UNCInfant2V21",
    "UNCInfant2V22",
    "UNCInfant2V23",
]
UNKNOWN_FRAMES = ["Other", "n/a", "", "Pixels", "individual", "study", "scanner"]
UNKNOWN_FRAMES += ["eeglab", "captrak", "MNI", "CapTrak "]


# ── The reference ─────────────────────────────────────────────────────────


def reference() -> dict:
    """The pinned eegprep, or exit: vectors come from that commit only."""
    try:
        dist = importlib.metadata.distribution("eegprep")
    except importlib.metadata.PackageNotFoundError:
        sys.exit("eegprep is not installed: run with `uv run --group vectors`.")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    commit = direct.get("vcs_info", {}).get("commit_id")
    if commit != EEGPREP_COMMIT:
        sys.exit(f"eegprep is at {commit!r}, not the reference {EEGPREP_COMMIT}.")
    import scipy

    return {
        "implementation": "eegprep",
        "repository": EEGPREP_REPOSITORY,
        "commit": EEGPREP_COMMIT,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def eegprep_topoplot(theta, radius, values):
    """eegprep's map: (Zi, plotrad, x axis, y axis), drawn with noplot."""
    from eegprep.functions.sigprocfunc.topoplot import topoplot

    locs = [
        {"labels": f"S{i}", "theta": float(t), "radius": float(r)}
        for i, (t, r) in enumerate(zip(theta, radius, strict=True))
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _handle, zi, plotrad, xi, yi = topoplot(
            np.asarray(values, dtype=float), locs, noplot="on"
        )
    return zi, float(plotrad), xi[:, 0].copy(), yi[0, :].copy()


def eegprep_clim(z):
    """eegprep's absmax color axis (EEGLAB's 5% margin)."""
    from eegprep.functions.sigprocfunc.topoplot import _maplimits_kwargs

    limits = _maplimits_kwargs("absmax", z)
    return [float(limits["vmin"]), float(limits["vmax"])]


def eegprep_contours(z):
    from eegprep.functions.sigprocfunc.topoplot import _contour_levels

    low, high = float(np.nanmin(z)), float(np.nanmax(z))
    if not low < high:
        return []
    return [float(v) for v in _contour_levels(low, high, 6)]


def eegprep_cart2topo(points):
    """eegprep's convertlocs(..., 'cart2topo') on centered ALS points."""
    from eegprep.functions.sigprocfunc.convertlocs import convertlocs

    locs = [
        {"labels": f"S{i}", "X": float(x), "Y": float(y), "Z": float(z)}
        for i, (x, y, z) in enumerate(points)
    ]
    out = convertlocs(locs, "cart2topo")
    theta = [float(loc["theta"]) for loc in out]
    # The spec writes the angle in (-180, 180]; eegprep gives -180 for a point
    # straight behind the center, and the same position as 180.
    theta = [180.0 if t == -180.0 else t for t in theta]
    return theta, [float(loc["radius"]) for loc in out]


# ── The spec's rules around the reference, written independently ──────────


def to_als(xyz, frame, montage=None):
    """ALS positions, or None for a frame the spec refuses. Template positions
    name a montage of views/montages (all RAS, in meters) and the frame n/a."""
    xyz = np.asarray(xyz, dtype=float)
    if montage is not None:
        orientation = "RAS" if frame == "n/a" and montage else None
    else:
        orientation = "ALS" if frame in ALS else "RAS" if frame in RAS else None
    if orientation == "ALS":
        return xyz.copy()
    if orientation == "RAS":
        return np.column_stack([xyz[:, 1], -xyz[:, 0], xyz[:, 2]])
    return None


def fit_center(points):
    """Sphere-fit center by SVD least squares (the spec solves the normal
    equations by LU; the two agree far inside the tolerance)."""
    n = len(points)
    centroid = points.sum(axis=0) / n
    centered = points - centroid
    scale = float(np.sqrt((centered**2).sum(axis=1)).max())
    if scale == 0:
        return centroid, "centroid", scale
    u = centered / scale
    design = np.column_stack([2 * u, np.ones(n)])
    target = (u**2).sum(axis=1)
    solution, _res, rank, singular = np.linalg.lstsq(design, target, rcond=None)
    # The normal equations square the condition number, so their pivot
    # threshold of 1e-10 is a singular-value ratio near 1e-5.
    if rank < 4 or singular[-1] <= 1e-5 * singular[0]:
        return centroid, "centroid", scale
    a, b, c, _d = solution
    return centroid + scale * np.array([a, b, c]), "sphere", scale


def layout_of(xyz, frame, montage=None):
    """Theta, radius, center and method for positions in a BIDS frame."""
    als = to_als(xyz, frame, montage)
    finite = np.isfinite(als).all(axis=1)
    theta = [None] * len(als)
    radius = [None] * len(als)
    center, method, scale = fit_center(als[finite])
    t, r = eegprep_cart2topo(als[finite] - center)
    for k, row in enumerate(np.flatnonzero(finite)):
        theta[row], radius[row] = t[k], r[k]
    return theta, radius, [float(v) for v in center], method, scale


def planar(theta, radius):
    t = np.deg2rad(np.asarray(theta, dtype=float))
    r = np.asarray(radius, dtype=float)
    return np.cos(t) * r, np.sin(t) * r


def merged_inputs(theta, radius, values):
    """Usable rows, merge groups (kept row first) and the kept sensors."""
    theta, radius, values = (
        np.asarray(a, dtype=float) for a in (theta, radius, values)
    )
    usable = [
        i
        for i in range(len(values))
        if math.isfinite(values[i])
        and math.isfinite(theta[i])
        and math.isfinite(radius[i])
    ]
    x, y = planar(np.nan_to_num(theta), np.nan_to_num(radius))
    groups: list[list[int]] = []
    for i in usable:
        for group in groups:
            k = group[0]
            if math.sqrt((x[i] - x[k]) ** 2 + (y[i] - y[k]) ** 2) <= MERGE:
                group.append(i)
                break
        else:
            groups.append([i])
    kept = [g[0] for g in groups]
    means = []
    for group in groups:
        total = 0.0
        for i in group:
            total += float(values[i])
        means.append(total / len(group))
    return usable, groups, kept, means


def field_case(name, description, labels, theta, radius, values, extra=None):
    """One sensor-field case: inputs, then eegprep's map of the merged inputs."""
    theta = np.asarray(theta, dtype=float)
    radius = np.asarray(radius, dtype=float)
    values = np.asarray(values, dtype=float)
    case = {
        "name": name,
        "description": description,
        "sensors": {
            "name": list(labels),
            "theta_deg": _numbers(theta),
            "radius": _numbers(radius),
            "value": _numbers(values),
        },
    }
    usable, groups, kept, means = merged_inputs(theta, radius, values)
    outer = max(radius[k] for k in kept) if kept else math.nan
    intrad = min(1.0, outer * 1.02)
    x, y = planar(np.nan_to_num(theta), np.nan_to_num(radius))
    interpolated = [k for k in kept if x[k] <= intrad and y[k] <= intrad]
    if len(interpolated) < 3:
        case["refused"] = "too_few_sensors"
        return case
    zi, plotrad, gx, gy = eegprep_topoplot(theta[kept], radius[kept], means)
    inside_head = np.sqrt(gx[:, None] * gx[:, None] + gy[None, :] * gy[None, :]) <= 0.5
    if not inside_head.any():
        case["refused"] = "head_outside_grid"
        return case
    if not np.isfinite(zi[inside_head]).all():
        case["refused"] = "interpolation_failed"
        return case
    check_margins(name, theta, radius, usable, groups, plotrad, intrad, gx, gy)
    finite = zi[np.isfinite(zi)]
    low, high = float(finite.min()), float(finite.max())
    top = float(np.nanmax(np.abs(zi)))
    absmax = [-top, top]
    case["expected"] = {
        "plotrad": plotrad,
        "intrad": intrad,
        "squeezefac": 0.5 / plotrad,
        "plotted": [i for i in usable if radius[i] <= plotrad],
        "interpolated": interpolated,
        "merged": [g for g in groups if len(g) > 1],
        "x": _numbers(gx),
        "y": _numbers(gy),
        "z": [_numbers(row) for row in zi],
        "limits": {"absmax": absmax, "minmax": [low, high]},
        "color_axis": {
            "absmax": eegprep_clim(zi) if top > 0 else [0.0, 0.0],
            "minmax": [
                v + math.copysign(0.05, v) * abs(v) if v else 0.0 for v in (low, high)
            ],
        },
        "contours": eegprep_contours(zi),
    }
    if extra:
        case["expected"].update(extra(theta, radius, values, zi))
    return case


MARGIN = 1e-9


def check_margins(name, theta, radius, usable, groups, plotrad, intrad, gx, gy):
    """Every decision is at least MARGIN from its threshold, or exact, so a
    sine or cosine that differs in its last bit cannot flip it."""
    x, y = planar(np.nan_to_num(theta), np.nan_to_num(radius))
    problems = []
    for i in usable:
        for group in groups:
            k = group[0]
            if k < i:
                d = math.sqrt((x[i] - x[k]) ** 2 + (y[i] - y[k]) ** 2)
                if 0 < abs(d - MERGE) < MARGIN:
                    problems.append(f"merge {i}-{k}")
        if 0 < abs(radius[i] - plotrad) < MARGIN:
            problems.append(f"plotrad {i}")
        if 0 < abs(x[i] - intrad) < MARGIN or 0 < abs(y[i] - intrad) < MARGIN:
            problems.append(f"square {i}")
    s = np.sqrt(gx[:, None] * gx[:, None] + gy[None, :] * gy[None, :])
    near = (np.abs(s - 0.5) < MARGIN) & (s != 0.5)
    if near.any():
        problems.append(f"{int(near.sum())} cell(s) near the head circle")
    if problems:
        raise SystemExit(f"{name}: decisions too close to a threshold: {problems}")


def _numbers(values):
    return [
        float(v) if math.isfinite(v) else None for v in np.asarray(values, dtype=float)
    ]


# ── Montages: eegprep's packaged cap files ─────────────────────────────────


def _montage_file(name):
    return importlib.resources.files("eegprep") / "resources" / "montages" / name


def montage(name, count):
    """The first `count` sensors (no fiducials) of a packaged cap, with its frame."""
    path = _montage_file(name)
    if name.endswith(".sfp"):
        rows = [line.split() for line in path.read_text().splitlines() if line.strip()]
        rows = [r for r in rows if not r[0].startswith("Fid")]
        labels = [r[0] for r in rows]
        xyz = np.array([[float(v) for v in r[1:4]] for r in rows])
        frame = "CapTrak"  # x right, y anterior, z superior
    else:
        from scipy.io import loadmat

        with path.open("rb") as handle:
            mat = loadmat(handle, squeeze_me=True, struct_as_record=False)
        labels = [str(v) for v in mat["labels"]]
        xyz = np.asarray(mat["coordinates"], dtype=float)
        axes = (mat["meta"].x, mat["meta"].y)
        frame = {("right", "front"): "CapTrak", ("front", "left"): "EEGLAB"}[axes]
        keep = [i for i, v in enumerate(labels) if v not in {"LPA", "RPA", "Nz"}]
        labels, xyz = [labels[i] for i in keep], xyz[keep]
    return labels[:count], xyz[:count], frame


def field_values(xyz, frame, seed):
    """A smooth scalp field plus noise, in microvolts: deterministic per seed."""
    als = to_als(xyz, frame)
    u = (als - als.mean(axis=0)) / np.abs(als - als.mean(axis=0)).max()
    rng = np.random.default_rng(seed)
    field = 12 * u[:, 0] - 7 * u[:, 1] + 5 * u[:, 0] * u[:, 2] - 3 * u[:, 2] ** 2
    return field + rng.normal(scale=1.0, size=len(u))


def layout_from(name, count):
    labels, xyz, frame = montage(name, count)
    theta, radius, *_ = layout_of(xyz, frame)
    return (
        labels,
        np.array(theta, dtype=float),
        np.array(radius, dtype=float),
        xyz,
        frame,
    )


# ── The sensor-field cases ─────────────────────────────────────────────────


def pinv_check(theta, radius, values, zi):
    """eegprep's griddata_v4 leaves 0 * log(0) = NaN where two sensors share a
    position, so its solve returns NaN without raising and its pinv fallback
    never runs: record that eegprep's own map of the unmerged inputs is NaN."""
    raw, *_ = eegprep_topoplot(theta, radius, values)
    return {"eegprep_unmerged_finite_cells": int(np.isfinite(raw).sum())}


def misalignment_check(theta, radius, values, zi):
    """eegprep at the pin drops a sensor whose value is not finite from the
    positions but not from the values, so later values shift onto the wrong
    sensors (EEGLAB's topoplot.m drops both): record that eegprep's own map of
    the raw inputs misses the spec's by more than the parity tolerance."""
    raw, *_ = eegprep_topoplot(theta, radius, values)
    span = float(np.nanmax(zi) - np.nanmin(zi))
    same_mask = bool((np.isfinite(raw) == np.isfinite(zi)).all())
    error = np.abs(raw - zi)[np.isfinite(zi)]
    agrees = same_mask and bool(np.isfinite(error).all()) and error.max() <= 1e-6 * span
    return {"eegprep_raw_agrees": agrees}


def field_cases():
    cases = []
    sizes = [
        ("montage_32", "egi-gsn-hydrocell-32.sfp", 32),
        ("montage_64", "egi-gsn-65-v2.sfp", 64),
        ("montage_128", "biosemi-128.locs", 128),
        ("montage_256", "egi-gsn-hydrocell-257.locs", 256),
    ]
    layouts = {}
    for seed, (name, source, count) in enumerate(sizes, start=1):
        labels, theta, radius, xyz, frame = layout_from(source, count)
        layouts[count] = (labels, theta, radius)
        values = field_values(xyz, frame, seed)
        cases.append(
            field_case(
                name,
                f"{count} sensors of eegprep's {source} ({frame} frame), laid out by "
                "nemar.sensor-layout.v1, with a smooth field plus noise.",
                labels,
                theta,
                radius,
                values,
            )
        )
    labels, theta, radius = layouts[32]
    base = cases[0]["sensors"]["value"]
    base = np.array(base, dtype=float)

    # Exact duplicates: two copies of sensor 4 and one of sensor 17, each with
    # its own value (eegprep would give an all-NaN map).
    dup_rows = [4, 4, 17]
    cases.append(
        field_case(
            "exact_duplicates",
            "montage_32 plus three sensors at the exact layout position of an "
            "earlier one (two at row 4, one at row 17) with different values: "
            "the merged sensor carries the mean.",
            [*labels, "E5b", "E5c", "E18b"],
            [*theta, *theta[dup_rows]],
            [*radius, *radius[dup_rows]],
            [*base, 9.5, -4.25, 3.0],
            extra=pinv_check,
        )
    )

    # Near duplicates: within the merge distance (4e-4 and 9e-4 away).
    x, y = planar(theta, radius)
    near = [(6, 4e-4, 0.0), (20, 0.0, -9e-4)]
    nt, nr = [], []
    for row, dx, dy in near:
        px, py = x[row] + dx, y[row] + dy
        nt.append(math.degrees(math.atan2(py, px)))
        nr.append(math.hypot(px, py))
    cases.append(
        field_case(
            "near_duplicates",
            "montage_32 plus a sensor 4e-4 from row 6 and one 9e-4 from row 20 "
            "(raw layout units): within the merge distance, so each merges into "
            "the earlier sensor and the reference is eegprep on the merged inputs.",
            [*labels, "E7b", "E21b"],
            [*theta, *nt],
            [*radius, *nr],
            [*base, -6.0, 8.0],
        )
    )

    # Two sensors 1.5e-3 apart: not merged.
    px, py = x[9] + 1.5e-3, y[9]
    cases.append(
        field_case(
            "close_pair",
            "montage_32 plus a sensor 1.5e-3 from row 9 (raw layout units): "
            "beyond the merge distance, so both are interpolated.",
            [*labels, "E10b"],
            [*theta, math.degrees(math.atan2(py, px))],
            [*radius, math.hypot(px, py)],
            [*base, base[9] + 0.75],
        )
    )

    # Collinear sensors on the midline (theta 0 and 180).
    mid_r = [0.42, 0.3, 0.17, 0.05, 0.12, 0.26, 0.39, 0.47]
    mid_t = [0, 0, 0, 0, 180, 180, 180, 180]
    cases.append(
        field_case(
            "collinear_midline",
            "Eight sensors on the midline only (theta 0 and 180): every sensor "
            "is collinear.",
            [f"M{i}" for i in range(8)],
            mid_t,
            mid_r,
            [3.0, 2.0, 0.5, -1.0, -0.5, 1.5, 4.0, 2.5],
        )
    )

    # Outside the head and outside the interpolation square.
    cases.append(
        field_case(
            "outside",
            "montage_32 plus a sensor behind the head at radius 1.2 (x = -1.2: "
            "inside the square, which has no absolute value, so it is "
            "interpolated and widens the grid), one at theta 0 radius 1.1 "
            "(x = 1.1 > intrad: not interpolated, not plotted) and one at theta "
            "-90 radius 1.05 (y = -1.05: interpolated).",
            [*labels, "BACK", "FRONT", "LEFT"],
            [*theta, 180.0, 0.0, -90.0],
            [*radius, 1.2, 1.1, 1.05],
            [*base, -14.0, 20.0, 6.0],
        )
    )

    # Values that are not finite.
    nan_values = base.copy()
    nan_values[[3, 11, 27]] = [math.nan, math.inf, -math.inf]
    cases.append(
        field_case(
            "nan_values",
            "montage_32 with the values of rows 3, 11 and 27 not finite (NaN, "
            "+Infinity, -Infinity; written null here): those sensors are dropped.",
            labels,
            theta,
            radius,
            nan_values,
            extra=misalignment_check,
        )
    )

    # Positions that are not finite.
    bad_theta, bad_radius = theta.copy(), radius.copy()
    bad_theta[8] = math.nan
    bad_radius[15] = math.nan
    cases.append(
        field_case(
            "nan_positions",
            "montage_32 with row 8's theta and row 15's radius not finite "
            "(written null): those sensors are dropped.",
            labels,
            bad_theta,
            bad_radius,
            base,
        )
    )

    cases.append(
        field_case(
            "constant_values",
            "montage_32 with every value 2.5: the biharmonic interpolant of equal "
            "values is not constant (it has no constant term), as in EEGLAB.",
            labels,
            theta,
            radius,
            np.full(32, 2.5),
        )
    )
    cases.append(
        field_case(
            "zero_map",
            "montage_32 with every value 0: a constant map, drawn in one color "
            "with no contours.",
            labels,
            theta,
            radius,
            np.zeros(32),
        )
    )
    cases.append(
        field_case(
            "three_sensors",
            "Exactly three sensors: the fewest that draw a map.",
            ["A", "B", "C"],
            [-30.0, 45.0, 170.0],
            [0.3, 0.25, 0.4],
            [1.0, -2.0, 0.5],
        )
    )
    cases.append(
        field_case(
            "two_sensors",
            "Two sensors: refused.",
            ["A", "B"],
            [-30.0, 45.0],
            [0.3, 0.25],
            [1.0, -2.0],
        )
    )
    cases.append(
        field_case(
            "merged_to_two",
            "Three sensors, two at one position: two remain after the merge, "
            "so the map is refused.",
            ["A", "B", "B2"],
            [-30.0, 45.0, 45.0],
            [0.3, 0.25, 0.25],
            [1.0, -2.0, 4.0],
        )
    )
    wide = base.copy()
    wide = np.sign(wide) * 10.0 ** np.linspace(-3, 3, 32)
    cases.append(
        field_case(
            "dynamic_range",
            "montage_32 with magnitudes from 1e-3 to 1e3 (a dynamic range of 1e6) "
            "and mixed signs.",
            labels,
            theta,
            radius,
            wide,
        )
    )
    cases.append(
        field_case(
            "far_sensor",
            "montage_32 plus a sensor at theta -135 and radius 1e10: it is "
            "interpolated (x and y are far below intrad), and it stretches the "
            "grid so far that no cell lies inside the head, so the map is refused.",
            [*labels, "FAR"],
            [*theta, -135.0],
            [*radius, 1e10],
            [*base, 1.0],
        )
    )
    cases.append(
        field_case(
            "overflow",
            "montage_32 with values of magnitude 1e308: the interpolation "
            "overflows binary64, so the map is refused.",
            labels,
            theta,
            radius,
            np.sign(base) * 1e308,
        )
    )
    labels, theta, radius = layouts[128]
    cases.append(
        field_case(
            "negative_extreme",
            "montage_128 with a field whose most negative value is larger in "
            "magnitude than its most positive, so absmax differs from max.",
            labels,
            theta,
            radius,
            -np.abs(np.array(cases[2]["sensors"]["value"])) * 2 + 3,
        )
    )
    return cases


def sensor_field_vectors(ref):
    return {
        "format": "nemar.sensor-field.v1",
        "spec": "docs/views/sensor-field.md",
        "description": (
            "Cases every implementation of nemar.sensor-field.v1 reproduces. Each "
            "case gives sensors (name, theta_deg, radius, value; null is a value "
            "that is not finite) and either the expected map or the word it is "
            "refused with. z[i][j] is the value at (x[i], y[j]); null is a masked "
            "cell. Sensor indices are input rows from 0; merged lists each merge "
            "group, the kept sensor first. The expected maps are eegprep's topoplot "
            "of the merged, finite sensors."
        ),
        "reference": ref,
        "tolerance": {
            "cells_relative_to_range": 1e-6,
            "constant_map_cells": 1e-12,
            "geometry_relative": 1e-12,
        },
        "grid_size": GRID,
        "cases": field_cases(),
    }


# ── The sensor-layout cases ────────────────────────────────────────────────


def layout_case(name, description, labels, xyz, frame, montage=None):
    xyz = np.asarray(xyz, dtype=float)
    case = {
        "name": name,
        "description": description,
        "coordinate_system": frame,
        **({"montage": montage} if montage is not None else {}),
        "positions": {
            "name": list(labels),
            "x": _numbers(xyz[:, 0]),
            "y": _numbers(xyz[:, 1]),
            "z": _numbers(xyz[:, 2]),
        },
    }
    if to_als(xyz, frame, montage) is None:
        case["refused"] = "frame_unknown"
        return case
    theta, radius, center, method, _scale = layout_of(xyz, frame, montage)
    case["expected"] = {
        "center": center,
        "center_method": method,
        "theta_deg": theta,
        "radius": radius,
    }
    return case


def layout_cases():
    cases = []
    labels, xyz, frame = montage("biosemi-128.locs", 128)
    cases.append(
        layout_case(
            "biosemi_128_ras",
            "eegprep's biosemi-128 cap in millimeters, x right, y anterior, z "
            "superior (CapTrak, an RAS frame).",
            labels,
            xyz,
            frame,
        )
    )
    labels, xyz, frame = montage("standard-10-5-342ch.locs", 400)
    cases.append(
        layout_case(
            "standard_10_5_als",
            "eegprep's 10-5 template (339 positions, fiducials removed) in meters, "
            "x anterior, y left, z superior (EEGLAB, an ALS frame).",
            labels,
            xyz,
            frame,
        )
    )
    labels, xyz, frame = montage("egi-gsn-hydrocell-32.sfp", 33)
    shifted = xyz + np.array([3.0, -1.5, 2.0])
    cases.append(
        layout_case(
            "hydrocel_32_off_center",
            "eegprep's HydroCel 32 cap in centimeters (CapTrak), translated by "
            "(3, -1.5, 2): the sphere fit recovers the center.",
            labels,
            shifted,
            frame,
        )
    )
    small_labels, small, _ = montage("egi-gsn-hydrocell-32.sfp", 12)
    cases.append(
        layout_case(
            "frame_ras",
            "Twelve HydroCel positions in an RAS frame; every RAS name gives this "
            "layout.",
            small_labels,
            small,
            "CapTrak",
        )
    )
    als_small = np.column_stack([small[:, 1], -small[:, 0], small[:, 2]])
    cases.append(
        layout_case(
            "frame_als",
            "The same twelve positions rotated into ALS; every ALS name gives "
            "this layout.",
            small_labels,
            als_small,
            "EEGLAB",
        )
    )
    angles = np.deg2rad(np.arange(0, 360, 30))
    flat = np.column_stack([np.cos(angles) * 8, np.sin(angles) * 8, np.full(12, 4.0)])
    tilt = np.deg2rad(25.0)
    ring = flat @ np.array(
        [[1, 0, 0], [0, np.cos(tilt), np.sin(tilt)], [0, -np.sin(tilt), np.cos(tilt)]]
    )
    cases.append(
        layout_case(
            "ring_coplanar",
            "Twelve positions on one ring, tilted 25 degrees (coplanar, but not in "
            "a plane of the axes, so rounding leaves a pivot near zero rather than "
            "at it): the sphere fit is degenerate, so the center is the centroid.",
            [f"R{i}" for i in range(12)],
            ring,
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "three_positions",
            "Three positions, which are coplanar: the fit is degenerate, so the "
            "center is the centroid.",
            ["A", "B", "C"],
            [[7.0, 1.0, 3.0], [-2.0, 6.0, 4.0], [0.5, -5.0, 6.5]],
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "coincident_positions",
            "Four positions at one point: the scale is 0, so the center is the "
            "centroid, the point itself, and each position converts as the origin "
            "(theta 0, radius 0.5).",
            ["A", "B", "C", "D"],
            [[2.5, -1.0, 7.0]] * 4,
            "EEGLAB",
        )
    )
    labels, xyz, frame = montage("egi-gsn-hydrocell-32.sfp", 33)
    holes = xyz.copy()
    holes[5, 1] = math.nan
    holes[20] = [math.nan, math.nan, math.nan]
    cases.append(
        layout_case(
            "missing_positions",
            "HydroCel 32 with row 5's y and all of row 20 not finite (written "
            "null): those rows get no layout and the fit uses the others.",
            labels,
            holes,
            frame,
        )
    )
    labels, xyz, frame = montage("egi-gsn-hydrocell-32.sfp", 33)
    meters = np.round(xyz / 100, 9)
    cases.append(
        layout_case(
            "template_montage",
            "Template positions: HydroCel 32 in meters, RAS, as the montage "
            "GSN-HydroCel-32 of views/montages gives them, with the coordinate "
            "system n/a. A template role names its montage, and every montage is "
            "RAS, so the layout is not refused.",
            labels,
            meters,
            "n/a",
            montage="GSN-HydroCel-32",
        )
    )
    cases.append(
        layout_case(
            "template_with_a_frame",
            "Template positions from a montage that also name a coordinate system "
            "(CapTrak) other than n/a: the frame is ambiguous, so refused.",
            labels,
            meters,
            "CapTrak",
            montage="GSN-HydroCel-32",
        )
    )
    for number, frame in enumerate(UNKNOWN_FRAMES, start=1):
        cases.append(
            layout_case(
                f"unknown_frame_{number}",
                f"The coordinate system {frame!r}: no orientation is assumed.",
                small_labels,
                small,
                frame,
            )
        )
    return cases


CART2TOPO_POINTS = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, -1.0, 0.0],
    [-1.0, 0.0, 0.0],
    [-1.0, -0.0, 0.0],
    [-2.5, 0.0, 1.5],
    [-2.5, -0.0, -1.5],
    [0.0, 0.0, 3.0],
    [0.0, 0.0, -3.0],
    [0.3, -0.4, 0.5],
    [-0.6, 0.8, -0.2],
    [-1.0, 1e-300, 0.0],
    [-1.0, -1e-300, 0.0],
    [2.0, 2.0, 2.0 * math.sqrt(8.0)],
]


def cart2topo_cases():
    """Centered ALS points straight to theta and radius, edges included: the
    axes, straight behind with y = +0 and y = -0, and the poles."""
    theta, radius = eegprep_cart2topo(np.array(CART2TOPO_POINTS))
    return [
        {"point": point, "theta_deg": t, "radius": r}
        for point, t, r in zip(CART2TOPO_POINTS, theta, radius, strict=True)
    ]


def sensor_layout_vectors(ref):
    return {
        "format": "nemar.sensor-layout.v1",
        "spec": "docs/views/sensor-layout.md",
        "description": (
            "Cases every implementation of nemar.sensor-layout.v1 reproduces. Each "
            "case gives positions (name, x, y, z in the frame coordinate_system "
            "names, or, for template positions that name a montage, in that "
            "montage's frame, RAS, with coordinate_system n/a; null is not finite) "
            "and either the expected layout (center and "
            "center_method in the ALS frame, theta_deg and radius per row, null for "
            "a row without a finite position) or the word it is refused with. The "
            "expected theta and radius are eegprep's convertlocs(..., 'cart2topo') "
            "of the positions minus the center, with -180 written 180. frames lists "
            "the BIDS coordinate systems of each orientation: an implementation "
            "gives frame_als's layout for every ALS name and frame_ras's for every "
            "RAS name. cart2topo gives centered ALS points and the theta and "
            "radius each converts to, with no fit (theta within "
            "tolerance.cart2topo_theta_deg degrees, with no wrapping, and radius "
            "within tolerance.radius). Tolerances for the cases: radius within "
            "tolerance.radius; theta through the planar point (cos(theta) * radius, "
            "sin(theta) * radius), within tolerance.planar of the expected one, "
            "because theta is undefined at the pole; the center within "
            "tolerance.center_relative_to_scale times the largest distance of a "
            "finite position from their centroid."
        ),
        "reference": ref | {"frames": BIDS_SPEC},
        "tolerance": {
            "planar": 1e-12,
            "radius": 1e-12,
            "center_relative_to_scale": 1e-9,
            "cart2topo_theta_deg": 1e-9,
        },
        "frames": {
            "ALS": sorted(ALS),
            "RAS": sorted(RAS),
            "template": {"coordinate_system": "n/a", "orientation": "RAS"},
        },
        "cart2topo": cart2topo_cases(),
        "cases": layout_cases(),
    }


# ── Writing and checking ───────────────────────────────────────────────────


def dumps(value, depth=0):
    """JSON with one line per list of scalars, so a grid row is one line."""
    pad = "  " * depth
    if isinstance(value, dict):
        items = [
            f"{pad}  {json.dumps(k)}: {dumps(v, depth + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}" if items else "{}"
    if isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
        items = [f"{pad}  {dumps(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(value, allow_nan=False, ensure_ascii=False)


def differences(new, old, path="", scale=None):
    """Where two vector documents differ beyond the regeneration tolerance."""
    if isinstance(new, dict) and isinstance(old, dict):
        if set(new) != set(old):
            return [f"{path}: keys {sorted(set(new) ^ set(old))}"]
        grid = new.get("z")
        if isinstance(grid, list) and grid and isinstance(grid[0], list):
            finite = [v for row in grid for v in row if v is not None]
            scale = max(finite) - min(finite) or 1.0
        out = []
        for key in new:
            tol = scale if key in {"z", "limits", "color_axis", "contours"} else None
            out += differences(new[key], old[key], f"{path}/{key}", tol)
        return out
    if isinstance(new, list) and isinstance(old, list):
        if len(new) != len(old):
            return [f"{path}: length {len(old)} -> {len(new)}"]
        out = []
        for i, (a, b) in enumerate(zip(new, old, strict=True)):
            out += differences(a, b, f"{path}/{i}", scale)
        return out
    if (
        isinstance(new, float)
        and isinstance(old, (float, int))
        and not isinstance(old, bool)
    ):
        if scale is not None:
            ok = abs(new - old) <= CHECK_CELLS * scale
        else:
            ok = abs(new - old) <= CHECK_SCALARS * max(abs(new), abs(old), 1e-300)
        return [] if ok else [f"{path}: {old!r} -> {new!r}"]
    return (
        [] if new == old and type(new) is type(old) else [f"{path}: {old!r} -> {new!r}"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    args = parser.parse_args()
    ref = reference()
    documents = {
        VECTORS / "sensor-field.v1.json": sensor_field_vectors(ref),
        VECTORS / "sensor-layout.v1.json": sensor_layout_vectors(ref),
    }
    failed = False
    for path, document in documents.items():
        text = dumps(document) + "\n"
        if not args.check:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)} ({len(text.encode()):,} bytes)")
            continue
        if not path.is_file():
            print(f"{path.relative_to(ROOT)}: missing")
            failed = True
            continue
        committed = json.loads(path.read_text(encoding="utf-8"))
        problems = differences(json.loads(text), committed)
        if problems:
            failed = True
            print(f"{path.relative_to(ROOT)}: {len(problems)} difference(s)")
            for line in problems[:20]:
                print(f"  {line}")
        else:
            print(f"{path.relative_to(ROOT)}: matches")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
