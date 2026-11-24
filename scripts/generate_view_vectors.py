"""Generate the sensor-field and sensor-layout vectors from eegprep, the reference.

Writes ``views/vectors/sensor-field.v1.json`` and
``views/vectors/sensor-layout.v1.json``. With ``--check`` it writes nothing:
it regenerates both in memory and fails if they differ from the committed
files beyond the regeneration tolerance (numbers may move in the last bits
between linear algebra libraries; everything else must match exactly).

The cases' inputs (each sensor's theta, radius and value, or position) are
frozen in ``scripts/view_vector_inputs.json``: they are read from there, so a
platform's sine or a library's rounding cannot move them, and only the expected
outputs are computed. ``--refresh-inputs`` recomputes the inputs from eegprep's
packaged caps and rewrites that file; review its diff like any other.

Run with the ``vectors`` dependency group, which installs eegprep at the
pinned commit (Python 3.12 or later)::

    uv run --group vectors python scripts/generate_view_vectors.py --check

The rules the reference needs beyond eegprep (dropping sensors that are not
finite, merging near sensors, the frame table, the scalp rows, the sphere fit
and its bounds) are written here a second time, independently of
``neuroschema.views``: the tests hold the Python reference renderer to these
vectors, so the two copies check each other. Only data the specs list (the
montage names, the non-EEG name prefixes and the fiducial names of
nemar.sensor-labels.v1) is imported.
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

from neuroschema.views.sensor_labels import FIDUCIALS, MONTAGE_NAMES, NON_EEG_PREFIXES

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


INPUTS = Path(__file__).resolve().parent / "view_vector_inputs.json"
FROZEN: dict | None = None  # the stored inputs; None while refreshing them
FRESH: dict = {"sensor-field": {}, "sensor-layout": {}}


def frozen(family, name, computed):
    """A case's inputs: the stored ones, or, while refreshing, the computed."""
    FRESH[family][name] = computed
    if FROZEN is None:
        return computed
    stored = FROZEN[family].get(name)
    if stored is None:
        sys.exit(f"no frozen inputs for {family} {name}: run --refresh-inputs")
    return stored


def _floats(values):
    return np.array([math.nan if v is None else v for v in values], dtype=float)


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


def eegprep_topoplot(theta, radius, values, plotrad=None):
    """eegprep's map: (Zi, plotrad, x axis, y axis), drawn with noplot.

    ``plotrad``, when given, is passed as eegprep's own option: the spec takes
    it from every usable sensor before the merge, as EEGLAB's topoplot.m takes
    its radii before it interpolates, and eegprep is given only the merged
    sensors."""
    from eegprep.functions.sigprocfunc.topoplot import topoplot

    locs = [
        {"labels": f"S{i}", "theta": float(t), "radius": float(r)}
        for i, (t, r) in enumerate(zip(theta, radius, strict=True))
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        options = {} if plotrad is None else {"plotrad": plotrad}
        _handle, zi, plotrad, xi, yi = topoplot(
            np.asarray(values, dtype=float), locs, noplot="on", **options
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
    name a montage of nemar.sensor-labels.v1, exactly as it lists them (all
    RAS, in meters), and the frame n/a."""
    xyz = np.asarray(xyz, dtype=float)
    if montage is not None:
        orientation = "RAS" if frame == "n/a" and montage in MONTAGE_NAMES else None
    else:
        orientation = "ALS" if frame in ALS else "RAS" if frame in RAS else None
    if orientation == "ALS":
        return xyz.copy()
    if orientation == "RAS":
        return np.column_stack([xyz[:, 1], -xyz[:, 0], xyz[:, 2]])
    return None


FLAT_RATIO = 0.05
RADIUS_RATIO = 3.0
PARTIAL_DILUTION = 4.5
# Every vector keeps its measures this far from a bound (singular ratio,
# radius ratio, dilution).
BOUND_MARGIN = (0.002, 0.05, 0.05)
NO_BOUNDS = {"singular_ratio": None, "radius_ratio": None, "dilution": None}


def fit_center(points):
    """Measured positions: (center, bounds, None), or (None, bounds, word) when
    the spec refuses them as flat or partial. Computed by SVD, least squares
    and a matrix inverse (the spec uses the eigenvalues of u.T u and LU); the
    vectors keep every measure at least BOUND_MARGIN from its bound, so the two
    cannot disagree."""
    n = len(points)
    if n == 0:
        return None, dict(NO_BOUNDS), "positions_flat"
    centroid = points.sum(axis=0) / n
    centered = points - centroid
    scale = float(np.sqrt((centered**2).sum(axis=1)).max())
    if scale == 0:
        return None, dict(NO_BOUNDS), "positions_flat"
    u = centered / scale
    singular = np.linalg.svd(u, compute_uv=False)
    ratio = float(singular[-1] / singular[0]) if len(singular) == 3 else 0.0
    bounds = dict(NO_BOUNDS, singular_ratio=ratio)
    if ratio < FLAT_RATIO:
        return None, bounds, "positions_flat"
    design = np.column_stack([2 * u, np.ones(n)])
    target = (u**2).sum(axis=1)
    (a, b, c, d), *_ = np.linalg.lstsq(design, target, rcond=None)
    bounds["radius_ratio"] = float(math.sqrt(a * a + b * b + c * c + d))
    if bounds["radius_ratio"] > RADIUS_RATIO:
        return None, bounds, "positions_flat"
    # The dilution: the center block of the inverse of the mean of [e, 1] [e, 1]'
    # over the unit vectors e from the center to each position.
    spokes = u - np.array([a, b, c])
    spokes /= np.linalg.norm(spokes, axis=1)[:, None]
    augmented = np.column_stack([spokes, np.ones(n)])
    inverse = np.linalg.inv(augmented.T @ augmented / n)
    bounds["dilution"] = float(math.sqrt(np.trace(inverse[:3, :3])))
    if bounds["dilution"] > PARTIAL_DILUTION:
        return None, bounds, "positions_partial"
    return centroid + scale * np.array([a, b, c]), bounds, None


def check_bounds(name, bounds):
    ratio, radius, spread = (
        bounds["singular_ratio"],
        bounds["radius_ratio"],
        bounds["dilution"],
    )
    if ratio is not None and 0 < abs(ratio - FLAT_RATIO) < BOUND_MARGIN[0]:
        raise SystemExit(f"{name}: singular ratio {ratio} too near {FLAT_RATIO}")
    if radius is not None and abs(radius - RADIUS_RATIO) < BOUND_MARGIN[1]:
        raise SystemExit(f"{name}: radius ratio {radius} too near {RADIUS_RATIO}")
    if spread is not None and abs(spread - PARTIAL_DILUTION) < BOUND_MARGIN[2]:
        raise SystemExit(f"{name}: dilution {spread} too near {PARTIAL_DILUTION}")


def has_position(xyz):
    """Rows with a position: finite, and not exactly (0, 0, 0) in either sign."""
    xyz = np.asarray(xyz, dtype=float)
    return np.isfinite(xyz).all(axis=1) & ~np.all(xyz == 0.0, axis=1)


def _plain_name(name):
    """A vector's name as the spec compares it for the scalp rows: trimmed, an
    EEG prefix dropped, then lowercase (the vectors' names are plain ASCII)."""
    text = name.strip()
    if text[:3].lower() == "eeg" and text[3:4] in (" ", "-", "_", ":"):
        text = text[3:].lstrip(" -_:")
    return text.lower()


def scalp(names, types):
    """The scalp rows: typed EEG when any row is typed, otherwise every row but
    those named with a non-EEG prefix; never a row named as a fiducial."""
    kinds = [(t or "").strip().lower() for t in types] if types else []
    typed = any(k not in ("", "n/a") for k in kinds)
    keep = []
    for i, name in enumerate(names):
        plain = _plain_name(name)
        row = kinds[i] == "eeg" if typed else not plain.startswith(NON_EEG_PREFIXES)
        keep.append(row and plain not in FIDUCIALS)
    return np.array(keep, dtype=bool)


MONTAGES = ROOT / "views" / "montages"


def montage_document(name):
    return json.loads((MONTAGES / f"{name}.json").read_text(encoding="utf-8"))


def montage_center(name):
    """The montage's stored center (RAS meters), checked against an independent
    SVD fit of all its electrodes (the stored one is rounded to 1e-9 m)."""
    document = montage_document(name)
    stored = np.array(document["center"], dtype=float)
    electrodes = np.array([e[1:4] for e in document["electrodes"]], dtype=float)
    center, _bounds, _word = fit_center(electrodes)
    if center is None or np.abs(center - stored).max() > 2e-9:
        sys.exit(f"{name}: the stored center {stored} is not the fit {center}")
    return stored


def layout_of(xyz, frame, montage=None, names=None, types=None):
    """(theta, radius, center, method, bounds) for positions in a BIDS frame,
    or (None, word, bounds) for measured positions the spec refuses as flat or
    partial. Only the scalp rows with a position are projected. Template
    positions use their montage's own center; measured positions a sphere
    fitted to the scalp rows with a position."""
    als = to_als(xyz, frame, montage)
    rows = has_position(als)
    if names is not None:
        rows &= scalp(names, types)
    theta = [None] * len(als)
    radius = [None] * len(als)
    if montage is not None:
        center = to_als(montage_center(montage)[None, :], frame, montage)[0]
        method, bounds = "montage", None
    else:
        center, bounds, word = fit_center(als[rows])
        if center is None:
            return None, word, bounds
        method = "sphere"
    t, r = eegprep_cart2topo(als[rows] - center)
    for k, row in enumerate(np.flatnonzero(rows)):
        theta[row], radius[row] = t[k], r[k]
    return theta, radius, [float(v) for v in center], method, bounds


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
    sensors = {
        "name": list(labels),
        "theta_deg": _numbers(theta),
        "radius": _numbers(radius),
        "value": _numbers(values),
    }
    sensors = frozen("sensor-field", name, sensors)
    return field_case_from(name, description, sensors, extra)


def field_case_from(name, description, sensors, extra=None):
    """A sensor-field case from its inputs: eegprep's map of the merged inputs."""
    theta = _floats(sensors["theta_deg"])
    radius = _floats(sensors["radius"])
    values = _floats(sensors["value"])
    case = {"name": name, "description": description, "sensors": sensors}
    usable, groups, kept, means = merged_inputs(theta, radius, values)
    outer = max(radius[i] for i in usable) if usable else math.nan
    plotrad_all = max(min(1.0, outer * 1.02), 0.5)
    intrad = min(1.0, outer * 1.02)
    x, y = planar(np.nan_to_num(theta), np.nan_to_num(radius))
    interpolated = [k for k in kept if x[k] <= intrad and y[k] <= intrad]
    if len(interpolated) < 3:
        case["refused"] = "too_few_sensors"
        return case
    outer_kept = max(radius[k] for k in kept)
    option = None if outer_kept == outer else plotrad_all
    zi, plotrad, gx, gy = eegprep_topoplot(theta[kept], radius[kept], means, option)
    if plotrad != plotrad_all:
        sys.exit(f"{name}: eegprep's plotrad {plotrad!r} is not {plotrad_all!r}")
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
    assert theta is not None, name
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
    return {"eegprep_raw_agrees": bool(agrees)}


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
    cases.append(
        field_case(
            "boundary_ties",
            "montage_32 plus three sensors on exact ties: EDGE at theta 0, radius "
            "1.0 (the largest radius, so plotrad = intrad = 1.0, and x = 1.0 = "
            "intrad: plotted and interpolated, because both tests are <=), and "
            "NEAR at theta 0, radius 1e-3, exactly 1e-3 from ORIGIN at radius 0 "
            "(merged, because the merge test is <=).",
            [*labels, "ORIGIN", "NEAR", "EDGE"],
            [*theta, 0.0, 0.0, 0.0],
            [*radius, 0.0, 1e-3, 1.0],
            [*base, 1.0, 3.0, -2.0],
        )
    )
    outer = int(np.argmax(radius))
    cases.append(
        field_case(
            "merged_outermost",
            f"montage_32 plus a sensor 5e-4 outside row {outer}, the outermost: it "
            "merges into that sensor, and the radii come from every usable sensor "
            "before the merge (EEGLAB), so from it. The reference passes eegprep "
            "that plotrad, since eegprep sees only the merged sensors.",
            [*labels, "OUT"],
            [*theta, theta[outer]],
            [*radius, radius[outer] + 5e-4],
            [*base, base[outer] + 4.0],
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
    return cases + positions_cases()


def positions_case(name, description, labels, xyz, frame, values, montage=None):
    """A map placed by 3D positions: projected (sensor-layout), then drawn."""
    xyz = np.asarray(xyz, dtype=float)
    sensors = frozen(
        "sensor-field",
        name,
        {
            "name": list(labels),
            "x": _numbers(xyz[:, 0]),
            "y": _numbers(xyz[:, 1]),
            "z": _numbers(xyz[:, 2]),
            "value": _numbers(values),
        },
    )
    case = {
        "name": name,
        "description": description,
        "coordinate_system": frame,
        **({"montage": montage} if montage is not None else {}),
        "sensors": sensors,
    }
    xyz = np.column_stack([_floats(sensors[axis]) for axis in "xyz"])
    if to_als(xyz, frame, montage) is None:
        case["refused"] = "frame_unknown"
        return case
    projected = layout_of(xyz, frame, montage, sensors["name"])
    if projected[-1] is not None:
        check_bounds(name, projected[-1])
        case["bounds"] = projected[-1]
    if projected[0] is None:
        case["refused"] = projected[1]
        return case
    theta, radius, center, method, _bounds = projected
    drawn = field_case_from(
        name,
        description,
        {
            "name": sensors["name"],
            "theta_deg": theta,
            "radius": radius,
            "value": sensors["value"],
        },
    )
    if "refused" in drawn:
        case["refused"] = drawn["refused"]
        return case
    layout = {
        "center": center,
        "center_method": method,
        "theta_deg": theta,
        "radius": radius,
    }
    case["expected"] = {"layout": layout} | drawn["expected"]
    return case


def positions_cases():
    labels, xyz, frame = montage("egi-gsn-65-v2.sfp", 64)
    holes = xyz.copy()
    holes[10, 0] = math.nan
    values = field_values(xyz, frame, 11)
    cases = [
        positions_case(
            "positions_measured",
            "Measured positions: 64 sensors of eegprep's GSN 65 cap in centimeters "
            "(CapTrak), row 10 without a finite x (written null; that sensor is "
            "dropped). They are projected by nemar.sensor-layout.v1 (expected."
            "layout), and the projected layout is drawn.",
            labels,
            holes,
            frame,
            values,
        )
    ]
    hydrocel = montage_document("GSN-HydroCel-32")
    labels = [e[0] for e in hydrocel["electrodes"]]
    meters = np.array([e[1:4] for e in hydrocel["electrodes"]], dtype=float)
    values = field_values(meters, "CapTrak", 12)
    cases.append(
        positions_case(
            "positions_template",
            "Template positions: every electrode of the montage GSN-HydroCel-32 "
            "(RAS meters) with the coordinate system n/a, projected about the "
            "montage's own center.",
            labels,
            meters,
            "n/a",
            values,
            montage="GSN-HydroCel-32",
        )
    )
    ten_05 = {e[0]: e[1:4] for e in montage_document("standard_1005")["electrodes"]}
    cases.append(
        positions_case(
            "positions_template_midline",
            "Template positions: the nine midline electrodes of standard_1005, "
            "Fpz to Oz, with n/a. Projected about the montage's own center, they "
            "lie along the line from the nose to the back of the head, as on the "
            "full cap, and the map is drawn.",
            MIDLINE_9,
            [ten_05[k] for k in MIDLINE_9],
            "n/a",
            [2.0, 1.5, 1.0, 0.25, -0.5, -1.0, -1.75, -2.5, -3.0],
            montage="standard_1005",
        )
    )
    cases.append(
        positions_case(
            "positions_frame_unknown",
            "The same positions in the coordinate system Other: the projection is "
            "refused, and a renderer places the sensors by name instead.",
            labels,
            meters,
            "Other",
            values,
        )
    )
    disk = flat_disk()
    cases.append(
        positions_case(
            "positions_flat_disk",
            "Thirty-two positions on a disk in the plane z = 0 (EEGLAB): flat, "
            "so the projection is refused (positions_flat), and a renderer places "
            "the sensors by name instead.",
            [f"D{i}" for i in range(32)],
            disk,
            "EEGLAB",
            np.round(disk[:, 0] - 0.5 * disk[:, 1], 6),
        )
    )
    cases.append(
        positions_case(
            "positions_three",
            "Three positions: refused (positions_flat).",
            ["A", "B", "C"],
            [[7.0, 1.0, 3.0], [-2.0, 6.0, 4.0], [0.5, -5.0, 6.5]],
            "EEGLAB",
            [1.0, -2.0, 0.5],
        )
    )
    ring = uneven_ring()
    cases.append(
        positions_case(
            "positions_ring",
            "Nine measured positions on one tilted circle (EEGLAB): in one plane, "
            "so they fix no head; the projection is refused (positions_flat), and "
            "a renderer places the sensors by name instead.",
            [f"R{i}" for i in range(9)],
            ring,
            "EEGLAB",
            [3.0, 1.0, -1.0, -2.5, 0.5, 2.0, -0.5, 1.5, -3.0],
        )
    )
    cases.append(
        positions_case(
            "positions_montage_beside_a_frame",
            "Template positions that name a montage and also CapTrak: inconsistent, "
            "so refused, never guessed.",
            labels,
            meters,
            "CapTrak",
            values,
            montage="GSN-HydroCel-32",
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
            "of the merged, finite sensors. A case whose sensors give x, y and z "
            "instead of theta_deg and radius places them by 3D positions in the "
            "frame coordinate_system names (or n/a with a montage): "
            "nemar.sensor-layout.v1 projects them (expected.layout, compared as in "
            "sensor-layout.v1.json), then the map is drawn; frame_unknown is the "
            "projection's refusal."
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


def layout_case(name, description, labels, xyz, frame, montage=None, types=None):
    """One sensor-layout case; ``types``, when given, is the sensor_type column."""
    xyz = np.asarray(xyz, dtype=float)
    positions = frozen(
        "sensor-layout",
        name,
        {
            "name": list(labels),
            "x": _numbers(xyz[:, 0]),
            "y": _numbers(xyz[:, 1]),
            "z": _numbers(xyz[:, 2]),
            **({"sensor_type": list(types)} if types is not None else {}),
        },
    )
    case = {
        "name": name,
        "description": description,
        "coordinate_system": frame,
        **({"montage": montage} if montage is not None else {}),
        "positions": positions,
    }
    xyz = np.column_stack([_floats(positions[axis]) for axis in "xyz"])
    if to_als(xyz, frame, montage) is None:
        case["refused"] = "frame_unknown"
        return case
    projected = layout_of(
        xyz, frame, montage, positions["name"], positions.get("sensor_type")
    )
    if projected[-1] is not None:
        check_bounds(name, projected[-1])
        case["bounds"] = projected[-1]
    if projected[0] is None:
        case["refused"] = projected[1]
        return case
    theta, radius, center, method, _bounds = projected
    case["expected"] = {
        "center": center,
        "center_method": method,
        "theta_deg": theta,
        "radius": radius,
    }
    return case


def uneven_ring():
    """Nine positions on one circle, unevenly spaced (so the circle's center
    is not their centroid) and tilted 25 degrees out of the axes' planes."""
    angles = np.deg2rad([0, 20, 50, 90, 150, 200, 260, 300, 330])
    flat = np.column_stack(
        [np.cos(angles) * 8 + 1.0, np.sin(angles) * 8 - 2.0, np.full(9, 4.0)]
    )
    tilt = np.deg2rad(25.0)
    return flat @ np.array(
        [[1, 0, 0], [0, np.cos(tilt), np.sin(tilt)], [0, -np.sin(tilt), np.cos(tilt)]]
    )


MIDLINE_9 = ["Fpz", "AFz", "Fz", "FCz", "Cz", "CPz", "Pz", "POz", "Oz"]
CORONAL_9 = ["T7", "C5", "C3", "C1", "Cz", "C2", "C4", "C6", "T8"]


def fibonacci_sphere(count):
    """``count`` points spread evenly over a unit sphere (ALS: z up)."""
    i = np.arange(count) + 0.5
    polar = np.arccos(1 - 2 * i / count)
    azimuth = np.pi * (1 + 5**0.5) * i
    return np.column_stack(
        [
            np.cos(azimuth) * np.sin(polar),
            np.sin(azimuth) * np.sin(polar),
            np.cos(polar),
        ]
    )


def squashed_sphere(factor):
    """Sixty-four points over a 9 cm sphere, with z scaled by ``factor``."""
    points = fibonacci_sphere(64) * 0.09
    points[:, 2] *= factor
    return points


def spherical_cap(angle):
    """The points of an 800-point 9 cm sphere within ``angle`` degrees of its top."""
    points = fibonacci_sphere(800)
    cap = points[np.arccos(np.clip(points[:, 2], -1, 1)) <= np.deg2rad(angle)]
    return [f"P{i}" for i in range(len(cap))], cap * 0.09


def noisy_disk():
    """Forty-eight points on a 9 cm disk, with 0.09 mm of noise out of its plane."""
    rng = np.random.default_rng(7)
    r = 0.09 * np.sqrt(rng.uniform(0, 1, 48))
    a = rng.uniform(0, 2 * np.pi, 48)
    return np.column_stack(
        [np.cos(a) * r, np.sin(a) * r, rng.normal(0, 1e-3 * 0.09, 48)]
    )


def flat_disk():
    """Thirty-two positions scattered over a disk in the plane z = 0."""
    rng = np.random.default_rng(32)
    r = 8 * np.sqrt(rng.uniform(0, 1, 32))
    a = rng.uniform(0, 2 * np.pi, 32)
    return np.column_stack([np.cos(a) * r, np.sin(a) * r, np.zeros(32)])


# Five rows beside eegprep's HydroCel 32 cap (centimeters, CapTrak): eye
# channels at the outer canthi and below the left eye, and neck muscle
# channels, placed as a recording's electrodes.tsv lists them.
AUXILIARY_POSITIONS = [
    [5.5, 7.5, -3.0],
    [-5.5, 7.5, -3.0],
    [-3.0, 8.5, -5.5],
    [-4.0, -5.0, -10.0],
    [4.0, -5.0, -10.0],
]


def scalp_row_cases():
    """The rows a sphere is fitted to: scalp rows with a position only."""
    cases = []
    labels, xyz, frame = montage("egi-gsn-hydrocell-32.sfp", 33)
    zeros = xyz.copy()
    zeros[[3, 17]] = 0.0
    zeros[25] = [-0.0, 0.0, -0.0]
    cases.append(
        layout_case(
            "zero_rows",
            "eegprep's HydroCel 32 cap with rows 3 and 17 at exactly (0, 0, 0) "
            "and row 25 at (-0, 0, -0): a row at the frame's origin is a position "
            "the file does not have, so those rows get no layout and the sphere "
            "is fitted to the others.",
            labels,
            zeros,
            frame,
        )
    )
    auxiliary = np.vstack([xyz, AUXILIARY_POSITIONS])
    typed_names = [
        *labels,
        "R_horizontal_eog",
        "L_horizontal_eog",
        "L_vertical_eog",
        "L_neck_emg",
        "R_neck_emg",
    ]
    cases.append(
        layout_case(
            "eog_and_neck_typed",
            "eegprep's HydroCel 32 cap typed EEG, three eye channels typed EOG at "
            "the canthi and below the left eye, and two neck muscle channels "
            "with no type (absent from channels.tsv), as OpenNeuro's "
            "emg_Multimodal example writes them: when any row is typed only the "
            "EEG rows are scalp rows, so the five get no layout and the center "
            "is the cap's (fitted to all 38 rows it would move 8.5% of the head "
            "radius).",
            typed_names,
            auxiliary,
            frame,
            types=["EEG"] * len(labels) + ["EOG", "EOG", "EOG", "n/a", "n/a"],
        )
    )
    cases.append(
        layout_case(
            "eog_and_neck_untyped",
            "The same 38 rows with no types, the five named EOG_R, EOG_L, EOG_V, "
            "EMG_neck_L and EMG_neck_R: with no row typed, a name that starts "
            "with a non-EEG prefix of nemar.sensor-labels.v1 is not a scalp row.",
            [*labels, "EOG_R", "EOG_L", "EOG_V", "EMG_neck_L", "EMG_neck_R"],
            auxiliary,
            frame,
        )
    )
    ten_05 = montage_document("standard_1005")
    by_name = {e[0]: e[1:4] for e in ten_05["electrodes"]}
    fiducials = [ten_05["fiducials"][k] for k in ("nasion", "lpa", "rpa")]
    rows = [by_name[k] for k in TEN_TWENTY_19] + fiducials
    for name, types, how in [
        (
            "fiducials_typed",
            ["EEG"] * 19 + ["n/a"] * 3,
            "typed EEG, the fiducials untyped, so only the EEG rows are scalp rows",
        ),
        (
            "fiducials_untyped",
            None,
            "with no types: a row named as a fiducial is never a scalp row",
        ),
    ]:
        cases.append(
            layout_case(
                name,
                "The 19 electrodes of the 10-20 system from the montage "
                "standard_1005 as measured positions (FieldTrip's 10-05 positions "
                "on the Colin27 head, MNIColin27, meters), with its nasion and "
                f"preauricular points as rows Nz, LPA and RPA, {how}: the "
                "fiducials get no layout (fitted with them, the center would move "
                "2% of the head radius).",
                [*TEN_TWENTY_19, "Nz", "LPA", "RPA"],
                rows,
                "MNIColin27",
                types=types,
            )
        )
    biosemi = montage_document("biosemi64")
    flat = [[x, y, 0.0] for _label, x, y, _z in biosemi["electrodes"]]
    cases.append(
        layout_case(
            "flat_cap_with_fiducials",
            "The montage biosemi64 flattened to z = 0 (a two-dimensional layout "
            "written as three-dimensional positions) with "
            "its nasion and preauricular points at their true heights, named NAS, "
            "LPA and RPA (the vertex electrode lands on the origin, so it has no "
            "position): the fiducials are not scalp rows, so the flatness bound "
            "sees the flat cap alone and refuses it (positions_flat). Fitted with "
            "the fiducials it passed both flatness bounds.",
            [*(e[0] for e in biosemi["electrodes"]), "NAS", "LPA", "RPA"],
            [*flat, *(biosemi["fiducials"][k] for k in ("nasion", "lpa", "rpa"))],
            "CapTrak",
        )
    )
    return cases


TEN_TWENTY_19 = [
    "Fp1",
    "Fp2",
    "F7",
    "F3",
    "Fz",
    "F4",
    "F8",
    "T7",
    "C3",
    "Cz",
    "C4",
    "T8",
    "P7",
    "P3",
    "Pz",
    "P4",
    "P8",
    "O1",
    "O2",
]
# Regional sets of the reviewers' coverage probe, measured on the Colin27 head
# (standard_1005 as measured positions). The fit error is the largest planar
# distance, as a share of the head radius (0.5), between a sensor projected
# about the sphere fitted to the set and about the montage's own center.
REGIONAL_SETS = [
    (
        "measured_ten_twenty",
        TEN_TWENTY_19,
        "the 19 electrodes of the 10-20 system: they cover the head (dilution "
        "3.46; fit error 4.6% of the head radius); drawn",
    ),
    (
        "measured_emotiv_14",
        [
            "AF3",
            "F7",
            "F3",
            "FC5",
            "T7",
            "P7",
            "O1",
            "O2",
            "P8",
            "T8",
            "FC6",
            "F4",
            "F8",
            "AF4",
        ],
        "the 14 electrodes of the Emotiv EPOC, a ring around the head with no "
        "top (dilution 5.96; fit error 10.0% of the head radius); refused "
        "(positions_partial)",
    ),
    (
        "measured_frontal_6",
        ["Fp1", "Fp2", "AF3", "AF4", "F7", "F8"],
        "six frontal electrodes (dilution 8.02; fit error 30.1% of the head "
        "radius); refused (positions_partial)",
    ),
    (
        "measured_central_9",
        ["FC3", "FCz", "FC4", "C3", "Cz", "C4", "CP3", "CPz", "CP4"],
        "nine central electrodes around the vertex (dilution 5.99; fit error "
        "14.8% of the head radius); refused (positions_partial)",
    ),
]


def partial_cases():
    """The coverage bound, from both sides: regional sets of a real head, and
    spherical caps just inside and outside the bound."""
    cases = []
    ten_05 = montage_document("standard_1005")
    by_name = {e[0]: e[1:4] for e in ten_05["electrodes"]}
    for name, keys, what in REGIONAL_SETS:
        cases.append(
            layout_case(
                name,
                "Measured positions: from the montage standard_1005 (FieldTrip's "
                f"10-05 positions on the Colin27 head, MNIColin27, meters), {what}.",
                keys,
                [by_name[k] for k in keys],
                "MNIColin27",
            )
        )
    for name, angle, dilution, verdict in [
        ("cap_partial_inside", 88.0, 4.36, "drawn"),
        ("cap_partial_outside", 84.0, 4.62, "refused (positions_partial)"),
    ]:
        cases.append(
            layout_case(
                name,
                f"Positions on a 9 cm sphere within {angle} degrees of its top, an "
                f"even cover of a little {'more' if angle > 85 else 'less'} than "
                f"a hemisphere: dilution {dilution}, against the bound 4.5; "
                f"{verdict}.",
                *spherical_cap(angle),
                "EEGLAB",
            )
        )
    return cases


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
    cases.append(
        layout_case(
            "ring_coplanar",
            "Nine positions on one circle, unevenly spaced and tilted 25 degrees: "
            "in one plane, so their singular ratio is 0 and they fix no head; "
            "refused (positions_flat).",
            [f"R{i}" for i in range(9)],
            uneven_ring(),
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "disk_flat",
            "Thirty-two positions scattered over a disk in the plane z = 0: "
            "refused (positions_flat).",
            [f"D{i}" for i in range(32)],
            flat_disk(),
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "noisy_disk",
            "Forty-eight positions on a 9 cm disk with 0.09 mm of noise out of "
            "its plane, as a flat layout measured with noise: a sphere fitted to "
            "them would fit the noise; their singular ratio is 0.002, so refused "
            "(positions_flat).",
            [f"N{i}" for i in range(48)],
            noisy_disk(),
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "collinear_positions",
            "Five positions on one line: refused (positions_flat).",
            [f"L{i}" for i in range(5)],
            [[i * 2.0, 1.0 - i, 3.0 + 0.5 * i] for i in range(5)],
            "EEGLAB",
        )
    )
    bent = [[i * 2.0, 1.0 - i, 3.0 + 0.5 * i] for i in range(5)]
    bent[2] = [bent[2][0] + 1e-12, bent[2][1] + 2e-12, bent[2][2]]
    cases.append(
        layout_case(
            "nearly_collinear",
            "Five positions on one line but for 2.2e-12 off it at the middle one: "
            "refused (positions_flat).",
            [f"B{i}" for i in range(5)],
            bent,
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "three_positions",
            "Three positions, which always lie in one plane: refused (positions_flat).",
            ["A", "B", "C"],
            [[7.0, 1.0, 3.0], [-2.0, 6.0, 4.0], [0.5, -5.0, 6.5]],
            "EEGLAB",
        )
    )
    cases.append(
        layout_case(
            "coincident_positions",
            "Four positions at one point: refused (positions_flat).",
            ["A", "B", "C", "D"],
            [[2.5, -1.0, 7.0]] * 4,
            "EEGLAB",
        )
    )
    for name, factor, verdict in [
        (
            "squashed_sphere_inside",
            0.055,
            "it passes, and the dilution (13) then refuses it (positions_partial)",
        ),
        ("squashed_sphere_outside", 0.045, "refused (positions_flat)"),
    ]:
        cases.append(
            layout_case(
                name,
                f"Sixty-four positions spread over a whole 9 cm sphere, squashed "
                f"to {factor} of its height: singular ratio {factor}, against the "
                f"bound 0.05, with a sphere radius under 1 times their scale; "
                f"{verdict}.",
                [f"S{i}" for i in range(64)],
                squashed_sphere(factor),
                "EEGLAB",
            )
        )
    for name, angle, verdict in [
        (
            "cap_inside",
            21.0,
            "it passes, and the dilution (52) then refuses it (positions_partial)",
        ),
        ("cap_outside", 19.0, "refused (positions_flat)"),
    ]:
        cases.append(
            layout_case(
                name,
                f"Positions on a 9 cm sphere within {angle} degrees of its top: a "
                f"shallow cap whose sphere radius is "
                f"{'2.8' if angle == 21.0 else '3.1'} times their scale, against "
                f"the bound 3, with a singular ratio near 0.1; {verdict}.",
                *spherical_cap(angle),
                "EEGLAB",
            )
        )
    labels, xyz, frame = montage("standard-10-5-342ch.locs", 400)
    ten_five = dict(zip(labels, xyz, strict=True))
    six = ["F3", "F4", "C3", "C4", "P3", "P4"]
    cases.append(
        layout_case(
            "measured_six",
            "Six measured positions, F3 F4 C3 C4 P3 P4 of eegprep's 10-5 "
            "template (EEGLAB, meters), and no others: they pass both flatness "
            "bounds (singular ratio 0.15, sphere radius 1.1 times their scale), "
            "but they cover a band across the top of the head, and their dilution "
            "(10.9) refuses them (positions_partial).",
            six,
            [ten_five[k] for k in six],
            frame,
        )
    )
    cases.append(
        layout_case(
            "measured_midline_9",
            "Nine measured positions on the midline, Fpz to Oz, of eegprep's 10-5 "
            "template: they lie in one plane and fix no left or right, so refused "
            "(positions_flat); a renderer places them by name instead.",
            MIDLINE_9,
            [ten_five[k] for k in MIDLINE_9],
            frame,
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
    hydrocel = montage_document("GSN-HydroCel-32")
    names = [e[0] for e in hydrocel["electrodes"]]
    positions = [e[1:4] for e in hydrocel["electrodes"]]
    cases.append(
        layout_case(
            "template_montage",
            "Template positions: every electrode of the montage GSN-HydroCel-32 "
            "(views/montages, RAS meters), with the coordinate system n/a. They "
            "are projected about the montage's own center, stored in its file.",
            names,
            positions,
            "n/a",
            montage="GSN-HydroCel-32",
        )
    )
    cases.append(
        layout_case(
            "template_with_a_frame",
            "Template positions from a montage that also name a coordinate system "
            "(CapTrak) other than n/a: the frame is ambiguous, so refused.",
            names,
            positions,
            "CapTrak",
            montage="GSN-HydroCel-32",
        )
    )
    ten_05 = montage_document("standard_1005")
    by_name = {e[0]: e[1:4] for e in ten_05["electrodes"]}
    for name, keys, what in [
        ("template_full_1005", list(by_name), "every electrode of"),
        ("template_midline_9", MIDLINE_9, "the nine midline electrodes, Fpz to Oz, of"),
        ("template_coronal_9", CORONAL_9, "the nine coronal electrodes, T7 to T8, of"),
    ]:
        cases.append(
            layout_case(
                name,
                f"Template positions: {what} the montage standard_1005, with the "
                "coordinate system n/a. A subset is projected about the montage's "
                "own center, never a sphere fitted to the subset, so each "
                "electrode lands where template_full_1005 puts it.",
                keys,
                [by_name[k] for k in keys],
                "n/a",
                montage="standard_1005",
            )
        )
    for name, montage_name, why in [
        (
            "template_montage_wrong_case",
            "gsn-hydrocel-32",
            "GSN-HydroCel-32 in another case: montage names are matched exactly "
            "against the montage list, never through a file system that may fold "
            "case",
        ),
        (
            "template_montage_provenance",
            "PROVENANCE",
            "PROVENANCE, the name of the file beside the montages that records "
            "where they come from, which is not a montage",
        ),
    ]:
        cases.append(
            layout_case(
                name,
                f"Template positions naming the montage {why}: refused "
                "(frame_unknown).",
                names,
                positions,
                "n/a",
                montage=montage_name,
            )
        )
    cases += scalp_row_cases()
    cases += partial_cases()
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
            "montage's frame, RAS, with coordinate_system n/a; null is not finite; "
            "and sensor_type when the case has that column) and either the "
            "expected layout (center and center_method, montage or sphere, in the "
            "ALS frame, theta_deg and radius per row, null for a row that is not a "
            "scalp row or has no position: not finite, or exactly 0, 0, 0) or the "
            "word it is refused with. Template positions are centered on the "
            "montage's own center, its file's center; measured positions carry "
            "bounds, their singular_ratio, radius_ratio and dilution (null when "
            "not reached), which decide positions_flat against 0.05 and 3 and "
            "positions_partial against 4.5, within tolerance.bounds_absolute. The "
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
            "bounds_absolute": 1e-6,
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


LAYOUT_KEYS = {"theta_deg", "radius", "center", "center_method"}
SCALED_KEYS = {"z", "limits", "color_axis", "contours"}


def _close(a, b, bound):
    return abs(a - b) <= bound


def layout_differences(new, old, path, extent=None):
    """A layout's rows, compared as the parity rule compares them: radius
    absolutely and theta through the planar point, since theta is undefined at
    the pole and a vertex sensor's theta moves with the last bit of the center.
    A row missing a number must miss the same one, and its other number is
    compared alone. The center is compared absolutely, against the extent of
    the positions it was fitted to, since a center at the origin is rounding."""
    if len(new["theta_deg"]) != len(old["theta_deg"]):
        return [f"{path}: {len(old['theta_deg'])} rows -> {len(new['theta_deg'])}"]
    out = []
    columns = (new["theta_deg"], new["radius"], old["theta_deg"], old["radius"])
    for i, (tn, rn, to, ro) in enumerate(zip(*columns, strict=True)):
        row = f"{path}/{i}: ({to!r}, {ro!r}) -> ({tn!r}, {rn!r})"
        if (tn is None, rn is None) != (to is None, ro is None):
            out.append(row)
        elif tn is None or rn is None:
            same_theta = tn is None or _close(
                tn, to, CHECK_SCALARS * max(abs(tn), abs(to), 1.0)
            )
            same_radius = rn is None or _close(rn, ro, CHECK_SCALARS)
            if not (same_theta and same_radius):
                out.append(row)
        else:
            an, ao = math.radians(tn), math.radians(to)
            gap = math.hypot(
                math.cos(an) * rn - math.cos(ao) * ro,
                math.sin(an) * rn - math.sin(ao) * ro,
            )
            if abs(rn - ro) > CHECK_SCALARS or gap > CHECK_SCALARS:
                out.append(row)
    if "center" in new:
        size = max([abs(v) for v in old["center"] + new["center"]] + [extent or 0.0])
        bound = CHECK_SCALARS * size
        pairs = zip(new["center"], old["center"], strict=True)
        if any(abs(a - b) > bound for a, b in pairs):
            out.append(f"{path}/center: {old['center']!r} -> {new['center']!r}")
        if new["center_method"] != old["center_method"]:
            out.append(
                f"{path}/center_method: {old['center_method']} -> "
                f"{new['center_method']}"
            )
    return out


def _extent(case):
    """The largest finite coordinate of a case's 3D positions, or None."""
    positions = case.get("positions") or case.get("sensors") or {}
    if not isinstance(positions, dict) or "x" not in positions:
        return None
    values = [abs(v) for axis in "xyz" for v in positions[axis] if v is not None]
    return max(values, default=None)


def differences(new, old, path="", scale=None, extent=None):
    """Where two vector documents differ beyond the regeneration tolerance.

    ``scale`` is a map's range, inherited by everything below a key that
    follows from the cells (``z``, ``limits``, ``color_axis``, ``contours``);
    ``extent`` is the size of a case's 3D positions, for comparing a center.
    """
    if isinstance(new, dict) and isinstance(old, dict):
        if set(new) != set(old):
            return [f"{path}: keys {sorted(set(new) ^ set(old))}"]
        out = []
        extent = _extent(new) or extent
        if isinstance(new.get("theta_deg"), list):
            out += layout_differences(new, old, path, extent)
            new = {k: v for k, v in new.items() if k not in LAYOUT_KEYS}
            old = {k: v for k, v in old.items() if k not in LAYOUT_KEYS}
        grid = new.get("z")
        local = scale
        if isinstance(grid, list) and grid and isinstance(grid[0], list):
            finite = [v for row in grid for v in row if v is not None]
            local = max(finite) - min(finite) or 1.0
        for key in new:
            if key in SCALED_KEYS or scale is not None:
                tol = local
            else:
                tol = 1.0 if key == "bounds" else None
            out += differences(new[key], old[key], f"{path}/{key}", tol, extent)
        return out
    if isinstance(new, list) and isinstance(old, list):
        if len(new) != len(old):
            return [f"{path}: length {len(old)} -> {len(new)}"]
        out = []
        for i, (a, b) in enumerate(zip(new, old, strict=True)):
            out += differences(a, b, f"{path}/{i}", scale, extent)
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
    parser.add_argument(
        "--refresh-inputs",
        action="store_true",
        help=f"recompute the cases' inputs from eegprep and rewrite {INPUTS.name}",
    )
    args = parser.parse_args()
    if args.check and args.refresh_inputs:
        parser.error("--check compares against frozen inputs; drop --refresh-inputs")
    global FROZEN
    FROZEN = None if args.refresh_inputs else json.loads(INPUTS.read_text())
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
    if args.check:
        drift = differences(FRESH, {family: FROZEN[family] for family in FRESH})
        print(
            f"inputs: {len(drift)} difference(s) beyond the tolerance between the "
            f"frozen inputs and inputs recomputed here (reported; the vectors use "
            f"the frozen ones)"
        )
        for line in drift[:20]:
            print(f"  {line}")
    if args.refresh_inputs:
        stored = {
            "description": (
                "The frozen inputs of the view vectors: each case's sensors (theta, "
                "radius and value, or position and value) and positions, computed "
                "once from eegprep's packaged caps by `generate_view_vectors.py "
                "--refresh-inputs`. The generator reads them, so the vectors' inputs "
                "never move with a platform's math; only the expected outputs are "
                "computed."
            ),
            **FRESH,
        }
        INPUTS.write_text(dumps(stored) + "\n", encoding="utf-8")
        print(f"wrote {INPUTS.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
