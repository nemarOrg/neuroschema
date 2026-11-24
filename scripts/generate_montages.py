"""Generate the montages and vectors of ``nemar.sensor-labels.v1`` from MNE-Python
and EEGLAB.

    uv run --group vectors python scripts/generate_montages.py
    uv run --group vectors python scripts/generate_montages.py --check

Writes ``views/montages/<name>.json`` (one per montage), ``views/montages/
PROVENANCE.json`` (MNE-Python's version and license, EEGLAB's commit and
license, each montage's source file and its upstream origin, and the BioSemi
angle corrections) and
``views/vectors/sensor-labels.v1.json`` (the
cases every implementation reproduces, computed by the Python reference from the
montages written here). ``--check`` regenerates everything in memory and exits
with status 1 when a file on disk differs, is missing or is not generated here.

The older EGI nets come from EEGLAB's ``sample_locs`` files, copied unchanged
into ``scripts/montage_sources/eeglab`` (with EEGLAB's LICENSE) from
sccn/eeglab at EEGLAB_COMMIT; each file's SHA-256 is pinned in EEGLAB_SHA256,
and MNE-Python's own .sfp reader reads them as it reads the HydroCel nets.

The output is deterministic: coordinates are rounded to 9 decimal places of a
meter (1 nm), which absorbs last-bit differences in the trigonometry of the
spherical montages between platforms, and nothing records a date or a path
outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from neuroschema.views.sensor_labels import (
    ALGORITHM,
    FAMILY_ALIASES,
    FIDUCIALS,
    MONTAGE_ALIASES,
    MONTAGE_FORMAT,
    MONTAGE_NAMES,
    MONTAGE_ORDER,
    NON_EEG_PREFIXES,
    TEMPLATE_ONLY_MONTAGES,
    infer_positions,
    label_key,
    montage_from_json,
)

ROOT = Path(__file__).resolve().parent.parent
MONTAGES = ROOT / "views" / "montages"
VECTORS = ROOT / "views" / "vectors" / "sensor-labels.v1.json"
MNE_VERSION = "1.13.2"
DECIMALS = 9

# SHA-256 of FieldTrip's template/electrode/standard_1005.elc on its release
# branch (last changed in FieldTrip commit 0b62f10a, 2011-05-10). MNE-Python
# 1.13.2 ships the same bytes as colin27_1005.elc; the generator asserts it.
FIELDTRIP_STANDARD_1005_SHA256 = (
    "1ee59197946d62de872db2ac7f2243a596662c231427366f6dc5d84ed237f853"
)

# SHA-256 of each MNE-Python 1.13.2 source file the montages are read from. A
# new MNE version that changes one fails here before anything is written.
SOURCE_SHA256 = {
    "colin27_1005.elc": FIELDTRIP_STANDARD_1005_SHA256,
    "GSN-HydroCel-32.sfp": (
        "057297752812a986a0fc5d72791ccb6a24da812544939c1de2b92225aa8ac5cd"
    ),
    "GSN-HydroCel-64_1.0.sfp": (
        "fb3834991fc06b297ccbedef907d408df74bba48caa8b077008ab33de21f1a51"
    ),
    "GSN-HydroCel-65_1.0.sfp": (
        "64e08a26b38867982acf6e0976653661ff69a11c5da4eea40df6d439b8cf96ab"
    ),
    "GSN-HydroCel-128.sfp": (
        "edd0bd8e690ed4ff6bbdafd73342c69d1ad39096c1ed7f0c76bd6dd997d767a2"
    ),
    "GSN-HydroCel-129.sfp": (
        "9751d2e6407ed091a42249fc41b4aee9cef44cc3666db0f0be7e94eae0e4ffa1"
    ),
    "GSN-HydroCel-256.sfp": (
        "63d3de763f3bd36bb9096989a828068edcb60fea81607ddb96022d3bd2126e1c"
    ),
    "GSN-HydroCel-257.sfp": (
        "70d629847d9053491237d1f52e4a9fc2e56bfd68a2929ee2ace546daf2c92f91"
    ),
    "biosemi16.txt": (
        "7b12f0eebcab3df2a07e9b72844d92891094f5216eb6326406907690895dd13e"
    ),
    "biosemi32.txt": (
        "eb3041379bef6f98eab77fdb22dd0ed9853344e3680f066e110b3e4a992f58b2"
    ),
    "biosemi64.txt": (
        "8bd39ec923854853c1d6830c46cd4942f700d90ba9112541e21e45ea2a6fd7af"
    ),
    "biosemi128.txt": (
        "3adbfb01f4ebcb77b70f85dcd373ad10a626122f8891455be917bfc78c594e0e"
    ),
    "biosemi160.txt": (
        "d161ccac60c0ae26f6c266cc95eff689c44f60093fcfa907e34c4c48ff4e95f3"
    ),
    "biosemi256.txt": (
        "3cc6adf82abe2d32e8d6485543a45b3f62a40fc54ca1a26421ddc4168bdd4380"
    ),
}

# EEGLAB's sample_locs files for the older EGI nets, copied unchanged from
# sccn/eeglab (develop at EEGLAB_COMMIT; every file last changed in
# EEGLAB_FILES_COMMIT, 2010-02-06), and EEGLAB's LICENSE at EEGLAB_COMMIT.
EEGLAB_SOURCES = ROOT / "scripts" / "montage_sources" / "eeglab"
EEGLAB_REPOSITORY = "https://github.com/sccn/eeglab"
EEGLAB_COMMIT = "1f8488b81eaec671319938278ab59bace267d341"
EEGLAB_FILES_COMMIT = "188434a932dc34977be8befeefcea85d0e8b918a"
EEGLAB_SHA256 = {
    "GSN64v2_0.sfp": "1986f9dd14dea9c2d5d8f717bec1c0e7c04c85dc6b403b4bd36c4ce981e2f69a",
    "GSN65v2_0.sfp": "c2a89461879fb713078de9cad406dc8cc34738e28b262fc8cade1e60eb5c05f4",
    "GSN128.sfp": "a127c4faeaa81fe39acc6d2770654c803d6b2a6f473b7d7ba39c8d2429f17e48",
    "GSN129.sfp": "0340f4505a30b04faa46be47f6761888ad67bbc689d1f8ab7fc3b0fc2af75c8b",
    "GSN256.sfp": "ef3a1b6009358fc378969fa259f2ea245f9b16e6cdf7fe262771efcb58292ab6",
    "GSN257.sfp": "b130d6508d785a806482facfade59306eb060da378896575c55d9b55872ca6dd",
    "LICENSE": "f098d1bbf6c5628b507fd4040810b77000fa1796e988be4ee68bd0ff6607bfe2",
}

UPSTREAM = {
    "FieldTrip": (
        "FieldTrip template/electrode/standard_1005.elc: 10-05 positions "
        "constructed by Robert Oostenveld (Oostenveld and Praamstra 2001, The five "
        "percent electrode system for high-resolution EEG and ERP measurements), "
        "in millimeters in Montreal Neurological Institute (MNI) coordinates on "
        "FieldTrip's template head (Colin27). The FieldTrip repository is "
        "GPL-3.0 and its website CC BY-SA 4.0; neither states a license for the "
        "template electrode files. MNE-Python ships the file under its "
        "BSD-3-Clause license."
    ),
    "EGI": (
        "Electrical Geodesics, Inc. (EGI) HydroCel Geodesic Sensor Net layouts. "
        "FieldTrip states its template/electrode/GSN-HydroCel-*.sfp files were "
        "downloaded from the EGI FTP server, and MNE-Python's montage README says "
        "its GSN-HydroCel files are taken from FieldTrip. MNE's files hold the "
        "same numbers as FieldTrip's (FieldTrip names the 64 and 65 nets without "
        "_1.0); the bytes differ in whitespace. No license is stated for the "
        "layouts by EGI or FieldTrip; MNE-Python ships them under BSD-3-Clause."
    ),
    "EGI via EEGLAB": (
        "Electrical Geodesics, Inc. (EGI) Geodesic Sensor Net layouts from before "
        "the HydroCel nets, in EGI's .sfp format with EGI's fiducial names "
        "(FidNz, FidT9, FidT10), as EEGLAB ships them in sample_locs: "
        "GSN64v2_0.sfp and GSN65v2_0.sfp (a 64-channel net, version 2.0, "
        "without and with Cz), GSN128.sfp and GSN129.sfp (a 128-channel net) "
        "and GSN256.sfp and GSN257.sfp (a 256-channel net). EEGLAB's "
        "readegilocs.m, given no file, defaults a 64 or 65 channel EGI recording "
        "to GSN65v2_0.sfp and a 128 or 129 channel one to GSN129.sfp, with a "
        "warning to check the file, and has mapped 256 and 257 channels to "
        "GSN-HydroCel-257.sfp since sccn/eeglab commit 3affa98b (2010-09-24); "
        "nothing in EEGLAB reads GSN256.sfp or GSN257.sfp. The files record "
        "neither their EGI source nor a net version beyond the 64 net's, and "
        "have not changed since commit 188434a9 (2010-02-06, no message). No "
        "cap model names these nets, so nemar.sensor-labels.v1 never places a "
        "recording on them by name; they are kept for template positions a "
        "writer names exactly. EEGLAB's LICENSE (BSD 2-Clause, Copyright "
        "(c) 2024 Swartz Center for Computational Neuroscience) covers eeglab.m "
        "and the functions folder and states no license for sample_locs."
    ),
    "BioSemi": (
        "BioSemi head cap layouts (ABC labels, A1 to H32), as spherical angles "
        "in MNE-Python's biosemi*.txt. MNE's montage README does not name their "
        "origin. BioSemi publishes the position coordinates of its standard head "
        "caps (biosemi.com/download/Cap_coords_all.xls, linked from "
        "biosemi.com/headcap.htm) with no license statement; its 16, 32 and 64 "
        "channel sheets list the same 10-20 names and angles as MNE's "
        "biosemi16/32/64.txt, in the same order (spreadsheet SHA-256 "
        "38304148957c86b16622a7511c972f268ecbe2a7da2288edd3d59718ab82e2fa); the "
        "128, 160 and 256 channel sheets were not compared. MNE-Python ships the "
        "files under BSD-3-Clause."
    ),
}

# A BioSemi 16, 32 or 64 channel recording names its channels by amplifier
# bank (A1 to A16, A1 to A32, A1 to B32); MNE's files name the same electrodes
# by the 10-20 system. Each list below is the 10-20 name of A1, A2, ... (then
# B1, ...) as BioSemi's own layout drawings label them; the generator relabels
# MNE's electrodes in file order and fails unless the file order is this one.
BIOSEMI_DRAWINGS = {
    "biosemi16": (
        "biosemi.com/pics/cap_16_layout_large.jpg (SHA-256 "
        "13244c52743a574cc2c71c43d107b9c0a5fb662cb5655064c433eb1fc9196554)"
    ),
    "biosemi32": (
        "biosemi.com/pics/cap_32_layout_large.jpg (SHA-256 "
        "b062d157d087c617749cc010a7881eca928f49613d34708bc636212d80b910c1)"
    ),
    "biosemi64": (
        "biosemi.com/pics/cap_64_layout_large.jpg (SHA-256 "
        "10412c6cf8013551294ed70bd6c6926031a25b4c9fadceb6732b09417a5d79f5)"
    ),
}
BIOSEMI_BANKS = {
    "biosemi16": [
        "Fp1",
        "Fp2",
        "F4",
        "Fz",
        "F3",
        "T7",
        "C3",
        "Cz",
        "C4",
        "T8",
        "P4",
        "Pz",
        "P3",
        "O1",
        "Oz",
        "O2",
    ],
    "biosemi32": [
        "Fp1",
        "AF3",
        "F7",
        "F3",
        "FC1",
        "FC5",
        "T7",
        "C3",
        "CP1",
        "CP5",
        "P7",
        "P3",
        "Pz",
        "PO3",
        "O1",
        "Oz",
        "O2",
        "PO4",
        "P4",
        "P8",
        "CP6",
        "CP2",
        "C4",
        "T8",
        "FC6",
        "FC2",
        "F4",
        "F8",
        "AF4",
        "Fp2",
        "Fz",
        "Cz",
    ],
    "biosemi64": [
        "Fp1",
        "AF7",
        "AF3",
        "F1",
        "F3",
        "F5",
        "F7",
        "FT7",
        "FC5",
        "FC3",
        "FC1",
        "C1",
        "C3",
        "C5",
        "T7",
        "TP7",
        "CP5",
        "CP3",
        "CP1",
        "P1",
        "P3",
        "P5",
        "P7",
        "P9",
        "PO7",
        "PO3",
        "O1",
        "Iz",
        "Oz",
        "POz",
        "Pz",
        "CPz",
        "Fpz",
        "Fp2",
        "AF8",
        "AF4",
        "AFz",
        "Fz",
        "F2",
        "F4",
        "F6",
        "F8",
        "FT8",
        "FC6",
        "FC4",
        "FC2",
        "FCz",
        "Cz",
        "C2",
        "C4",
        "C6",
        "T8",
        "TP8",
        "CP6",
        "CP4",
        "CP2",
        "P2",
        "P4",
        "P6",
        "P8",
        "P10",
        "PO8",
        "PO4",
        "O2",
    ],
}


def bank_labels(count: int) -> list[str]:
    """A1 to A32, then B1 to B32, for the first count electrodes."""
    return [f"{'AB'[i // 32]}{i % 32 + 1}" for i in range(count)]


@dataclass(frozen=True)
class Source:
    """How one montage is made: from MNE-Python's built-in montage
    ``mne_kind``, or from the EEGLAB file ``eeglab_file`` read by MNE-Python's
    .sfp reader."""

    name: str
    mne_kind: str | None
    head_size: float | None
    scale_to_m: float
    family: str
    upstream: str
    why: str
    eeglab_file: str | None = None


HYDROCEL_WHY = (
    "head_size=None keeps the net file's own geometry, in centimeters, so each "
    "net and its Cz variant (64 and 65, 128 and 129, 256 and 257) share their "
    "electrode positions exactly; MNE's default rescales each file by its own "
    "median radius, which moves the 64/65 and 256/257 pairs apart by up to "
    "0.14 mm."
)
OLDER_GSN_WHY = (
    "EEGLAB's file, read by MNE-Python's own .sfp reader with head_size=None "
    "as the HydroCel nets are: the file's geometry, in centimeters, converted "
    "to meters. The older nets put each electrode number elsewhere than the "
    "HydroCel nets: about each montage's own center, a median 22% of the head "
    "radius from the HydroCel 129 net's place (128 and 129), 19% from the "
    "HydroCel 257 net's (256 and 257) and 40% from the HydroCel 65 net's (64 "
    "and 65)."
)
BANK_WHY = (
    "MNE's file names the electrodes by the 10-20 system; this montage names "
    "them by BioSemi amplifier bank, as a recording does, in MNE's file order, "
    "which BioSemi's layout drawing confirms (bank_labels). The angles are "
    "integers, so every position is MNE's."
)
BIOSEMI_WHY = (
    "The angles are read from MNE's file as written, with decimals, and placed "
    "with MNE's own spherical conversion on a sphere of 0.095 m (MNE's default "
    "head_size; the spherical layout has no head size of its own). MNE's "
    "make_standard_montage reads the angles as integers, so an angle written "
    "as 11.5 becomes 11; angle_corrections lists every electrode that moves, "
    "with the angles as written, MNE's integer angles and the distance between "
    "the two positions. Every other electrode is MNE's position exactly."
)
SOURCES = (
    Source(
        "standard_1005",
        "colin27_1005",
        None,
        1.0,
        "10-05",
        "FieldTrip",
        "MNE-Python 1.13 renamed the standard_1005 montage colin27_1005 "
        "(standard_1005 is deprecated and leaves in MNE 1.14); it reads the same "
        "file, in meters in MNI coordinates, unscaled.",
    ),
    *(
        Source(
            f"GSN-HydroCel-{n}",
            f"GSN-HydroCel-{n}",
            None,
            0.01,
            "GSN-HydroCel",
            "EGI",
            HYDROCEL_WHY,
        )
        for n in ("32", "64_1.0", "65_1.0", "128", "129", "256", "257")
    ),
    *(
        Source(f"biosemi{n}", f"biosemi{n}", 0.095, 1.0, "BioSemi", "BioSemi", BANK_WHY)
        for n in ("16", "32", "64")
    ),
    *(
        Source(
            f"biosemi{n}", f"biosemi{n}", 0.095, 1.0, "BioSemi", "BioSemi", BIOSEMI_WHY
        )
        for n in ("128", "160", "256")
    ),
    *(
        Source(n, None, None, 0.01, "GSN", "EGI via EEGLAB", OLDER_GSN_WHY, f"{n}.sfp")
        for n in TEMPLATE_ONLY_MONTAGES
    ),
)
# Each net and its Cz variant must share every electrode position exactly.
CZ_VARIANTS = (
    ("GSN-HydroCel-64_1.0", "GSN-HydroCel-65_1.0"),
    ("GSN-HydroCel-128", "GSN-HydroCel-129"),
    ("GSN-HydroCel-256", "GSN-HydroCel-257"),
    ("GSN64v2_0", "GSN65v2_0"),
    ("GSN128", "GSN129"),
    ("GSN256", "GSN257"),
)


def fail(message: str) -> None:
    raise SystemExit(f"generate_montages: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def meters(value: float, scale: float) -> float:
    return round(float(value) * scale, DECIMALS) + 0.0


def render(value: object, indent: int = 0) -> str:
    """JSON with one line per member or item, and flat values on one line.

    A list or object whose items are all scalars, and that fits in 100
    characters, is written on one line, so a montage file has one electrode per
    line and a vectors file one channel per line. Non-ASCII characters are
    escaped, so an invisible character in a channel name (a no-break space)
    shows in the file.
    """
    inline = json.dumps(value, separators=(", ", ": "))

    def flat(v: object) -> bool:
        items = v.values() if isinstance(v, dict) else v
        fits = len(inline) <= 100
        return fits and not any(isinstance(i, dict | list) for i in items)

    pad = " " * (indent + 2)
    if isinstance(value, dict) and value and not flat(value):
        members = [
            f"{pad}{json.dumps(k)}: {render(v, indent + 2)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(members) + "\n" + " " * indent + "}"
    if isinstance(value, list) and value and not flat(value):
        items = [f"{pad}{render(v, indent + 2)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"
    return inline


def check_labels(name: str, family: str, keys: dict[str, str]) -> None:
    """No montage label is one a name rule would drop, split or redirect."""
    for key, label in keys.items():
        if "-" in key or key in FIDUCIALS or key.startswith(NON_EEG_PREFIXES):
            fail(f"{name}: label {label!r} could never be matched")
    for family_name, aliases in FAMILY_ALIASES.items():
        for source in aliases:
            if source in keys and family_name != family:
                fail(f"{name}: alias {source!r} of {family_name} is a label here")
    for source, target in MONTAGE_ALIASES.get(name, {}).items():
        if source in keys or target not in keys:
            fail(f"{name}: alias {source!r} is a label, or {target!r} is not")


def check_frame(name: str, electrodes: list, fiducials: dict) -> None:
    """The montage is RAS in meters: nose +y, right ear +x, vertex +z."""
    nasion, lpa, rpa = fiducials["nasion"], fiducials["lpa"], fiducials["rpa"]
    if not (nasion[1] > 0.05 and abs(nasion[0]) < 0.01):
        fail(f"{name}: the nasion is not on +y: {nasion}")
    if not (lpa[0] < -0.05 and rpa[0] > 0.05):
        fail(f"{name}: the preauricular points are not on -x and +x")
    if max(e[3] for e in electrodes) < 0.07:
        fail(f"{name}: no electrode is high on +z")
    if abs(sum(e[1] for e in electrodes) / len(electrodes)) > 0.01:
        fail(f"{name}: the electrodes are not centered on x = 0")
    radii = sorted(math.hypot(e[1], e[2], e[3]) for e in electrodes)
    median = radii[len(radii) // 2]
    if not 0.07 < median < 0.12:
        fail(f"{name}: median radius {median} m is not a head's")


def biosemi_angles(source_file: Path, head_size: float) -> dict:
    """Electrode positions from a biosemi*.txt file, its angles read as written.

    Returns {label: (theta, phi, xyz)} in file order, with MNE's own spherical
    conversion (theta is the polar angle and phi the azimuth, in degrees).
    """
    import numpy as np
    from mne.transforms import _sph_to_cart

    rows = []
    for line in source_file.read_text().splitlines()[1:]:
        if line.strip():
            label, theta, phi = line.split()
            rows.append((label, float(theta), float(phi)))
    angles = np.array([[head_size, np.deg2rad(p), np.deg2rad(t)] for _, t, p in rows])
    xyz = _sph_to_cart(angles)
    return {label: (t, p, xyz[i]) for i, (label, t, p) in enumerate(rows)}


def biosemi_positions(source: Source, source_file: Path, mne_positions: dict):
    """Positions with the angles as written, and where they differ from MNE's.

    An electrode whose angles are integers must sit exactly where MNE puts it;
    the generator fails otherwise.
    """
    from mne.channels._standard_montage_utils import _safe_np_loadtxt, _str

    names, mne_theta, mne_phi = _safe_np_loadtxt(
        source_file, skip_header=1, dtype=(_str, "i4", "i4")
    )
    mne_angles = {
        n: (int(t), int(p)) for n, t, p in zip(names, mne_theta, mne_phi, strict=True)
    }
    parsed = biosemi_angles(source_file, source.head_size)
    ours = {k: v for k, v in parsed.items() if k not in ("Nz", "LPA", "RPA")}
    if list(ours) != list(mne_positions["ch_pos"]):
        fail(f"{source.name}: the electrodes are not MNE's, in MNE's order")
    corrections = []
    for label, (theta, phi, xyz) in ours.items():
        distance = math.dist(xyz, mne_positions["ch_pos"][label])
        if theta.is_integer() and phi.is_integer():
            if distance > 1e-12:
                fail(f"{source.name}: {label} has integer angles but is not MNE's")
            continue
        corrections.append(
            [label, theta, phi, *mne_angles[label], round(distance * 1000, 3)]
        )
    fiducials = {
        name: parsed[label][2]
        for name, label in (("nasion", "Nz"), ("lpa", "LPA"), ("rpa", "RPA"))
    }
    return {k: v[2] for k, v in ours.items()}, fiducials, corrections


def montage_center(name: str, electrodes: list) -> list[float]:
    """The montage's own center: the sphere nemar.sensor-layout.v1 fits to all
    its electrodes (sensor_layout.sphere_center), rounded as the positions are.
    Template positions taken from the montage are projected about this center,
    never about a sphere fitted to the few a recording has."""
    import numpy as np

    from neuroschema.views.sensor_layout import SensorLayoutRefusal, sphere_center

    try:
        fit = sphere_center(np.array([e[1:4] for e in electrodes], dtype=float))
    except SensorLayoutRefusal as exc:
        fail(f"{name}: no center for the full montage ({exc})")
    return [meters(v, 1.0) for v in fit.center]


def build_montage(source: Source) -> tuple[str, dict]:
    """One montage file's text and its PROVENANCE.json entry."""
    import mne
    from mne.channels._standard_montage_utils import (
        MONTAGE_PATH,
        standard_montage_look_up_table,
    )

    if source.eeglab_file is not None:
        from mne.channels._standard_montage_utils import _read_sfp

        basename = source.eeglab_file
        source_file = EEGLAB_SOURCES / basename
        source_sha = sha256(source_file.read_bytes())
        if source_sha != EEGLAB_SHA256.get(basename):
            fail(f"{basename} is not EEGLAB's file this generator was written for")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            montage = _read_sfp(str(source_file), source.head_size)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            montage = mne.channels.make_standard_montage(
                source.mne_kind, head_size=source.head_size
            )
        basename = standard_montage_look_up_table[source.mne_kind].keywords["basename"]
        source_file = Path(MONTAGE_PATH) / basename
        source_sha = sha256(source_file.read_bytes())
        if source_sha != SOURCE_SHA256.get(basename):
            fail(f"{basename} is not the file this generator was written for")
    positions = montage.get_positions()

    ch_pos = positions["ch_pos"]
    fiducial_pos = {name: positions[name] for name in ("nasion", "lpa", "rpa")}
    corrections = None
    if source.family == "BioSemi":
        ch_pos, fiducial_pos, corrections = biosemi_positions(
            source, source_file, positions
        )
    banks = None
    if source.name in BIOSEMI_BANKS:
        names = [label.strip() for label in ch_pos]
        if names != BIOSEMI_BANKS[source.name]:
            fail(f"{source.name}: MNE's file order is not BioSemi's drawing")
        banks = list(zip(bank_labels(len(names)), names, strict=True))
        ch_pos = {
            bank: ch_pos[label]
            for bank, label in zip(bank_labels(len(names)), ch_pos, strict=True)
        }
    electrodes = [
        [label, *(meters(v, source.scale_to_m) for v in xyz)]
        for label, xyz in ch_pos.items()
    ]
    fiducials = {
        name: [meters(v, source.scale_to_m) for v in xyz]
        for name, xyz in fiducial_pos.items()
    }
    keys = {label_key(e[0]): e[0] for e in electrodes}
    if len(keys) != len(electrodes):
        fail(f"{source.name}: two labels share a key")
    check_labels(source.name, source.family, keys)
    check_frame(source.name, electrodes, fiducials)

    document = {
        "format": MONTAGE_FORMAT,
        "name": source.name,
        "family": source.family,
        "orientation": "RAS",
        "unit": "m",
        "fiducials": fiducials,
        "center": montage_center(source.name, electrodes),
        "electrodes": electrodes,
    }
    text = render(document) + "\n"
    provenance = {
        "name": source.name,
        "file": f"views/montages/{source.name}.json",
        "sha256": sha256(text.encode("utf-8")),
        "electrodes": len(electrodes),
        "family": source.family,
        "mne_call": (
            f"mne.channels.make_standard_montage({source.mne_kind!r}, "
            f"head_size={source.head_size!r}).get_positions()"
        ),
        "mne_source": f"mne/channels/data/montages/{basename}",
        "mne_source_sha256": source_sha,
        "mne_coord_frame": positions["coord_frame"],
        "scale_to_m": source.scale_to_m,
        "upstream": source.upstream,
        "notes": [source.why],
    }
    if source.eeglab_file is not None:
        del provenance["mne_source"], provenance["mne_source_sha256"]
        provenance["mne_call"] = (
            "mne.channels._standard_montage_utils._read_sfp(<source>, "
            f"head_size={source.head_size!r}).get_positions()"
        )
        provenance["source"] = f"scripts/montage_sources/eeglab/{basename}"
        provenance["source_sha256"] = source_sha
        provenance["eeglab_source"] = (
            f"{EEGLAB_REPOSITORY}/blob/{EEGLAB_COMMIT}/sample_locs/{basename}"
        )
    if source.mne_kind is not None:
        provenance["mne_montage"] = source.mne_kind
    if banks is not None:
        provenance["bank_labels"] = {
            "source": BIOSEMI_DRAWINGS[source.name],
            "columns": ["label", "mne_label"],
            "rows": [list(row) for row in banks],
        }
    if corrections:
        provenance["mne_call"] = (
            f"angles from {basename} as written; mne.transforms._sph_to_cart on a "
            f"sphere of {source.head_size} m, as make_standard_montage"
            f"({source.mne_kind!r}, head_size={source.head_size!r}) does with "
            "integer angles"
        )
        provenance["angle_corrections"] = {
            "columns": [
                "label",
                "theta_deg",
                "phi_deg",
                "mne_theta_deg",
                "mne_phi_deg",
                "moved_mm",
            ],
            "electrodes": len(corrections),
            "max_moved_mm": max(row[-1] for row in corrections),
            "rows": corrections,
        }
    return text, provenance


def check_cz_variants(documents: dict) -> None:
    for small, large in CZ_VARIANTS:
        a = {e[0]: e[1:] for e in documents[small]["electrodes"]}
        b = {e[0]: e[1:] for e in documents[large]["electrodes"]}
        if set(b) - set(a) != {"Cz"} or any(a[k] != b[k] for k in a):
            fail(f"{small} and {large} do not share their electrodes exactly")


def check_aliases(documents: dict) -> None:
    """In the 10-05 montage an alias source, if listed, sits on its target."""
    positions = {
        label_key(e[0]): e[1:] for e in documents["standard_1005"]["electrodes"]
    }
    for source, target in FAMILY_ALIASES["10-05"].items():
        if target not in positions:
            fail(f"alias target {target!r} is not in standard_1005")
        if source in positions and positions[source] != positions[target]:
            fail(f"standard_1005 lists {source!r} away from {target!r}")


# ── Vector cases ──────────────────────────────────────────────────────────

TEN_TWENTY = [
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
NO_CZ = [n for n in TEN_TWENTY if n != "Cz"]
LEGACY = [
    {"T7": "T3", "T8": "T4", "P7": "T5", "P8": "T6"}.get(n, n) for n in TEN_TWENTY
]
BANANA = [
    "Fp1-F7",
    "F7-T7",
    "T7-P7",
    "P7-O1",
    "Fp1-F3",
    "F3-C3",
    "C3-P3",
    "P3-O1",
    "Fz-Cz",
    "Cz-Pz",
    "Fp2-F4",
    "F4-C4",
    "C4-P4",
    "P4-O2",
    "Fp2-F8",
    "F8-T8",
    "T8-P8",
    "P8-O2",
]
# A Neuroscan Quik-Cap 64's channel names, as its recordings spell them.
QUIK_CAP_64 = [
    "FP1",
    "FPZ",
    "FP2",
    "AF3",
    "AF4",
    "F7",
    "F5",
    "F3",
    "F1",
    "FZ",
    "F2",
    "F4",
    "F6",
    "F8",
    "FT7",
    "FC5",
    "FC3",
    "FC1",
    "FCZ",
    "FC2",
    "FC4",
    "FC6",
    "FT8",
    "T7",
    "C5",
    "C3",
    "C1",
    "CZ",
    "C2",
    "C4",
    "C6",
    "T8",
    "M1",
    "TP7",
    "CP5",
    "CP3",
    "CP1",
    "CPZ",
    "CP2",
    "CP4",
    "CP6",
    "TP8",
    "M2",
    "P7",
    "P5",
    "P3",
    "P1",
    "PZ",
    "P2",
    "P4",
    "P6",
    "P8",
    "PO7",
    "PO5",
    "PO3",
    "POZ",
    "PO4",
    "PO6",
    "PO8",
    "CB1",
    "O1",
    "OZ",
    "O2",
    "CB2",
]
PHYSIONET = [
    "Fc5.",
    "Fc3.",
    "Fc1.",
    "Fcz.",
    "Fc2.",
    "Fc4.",
    "Fc6.",
    "C5..",
    "C3..",
    "C1..",
    "Cz..",
    "C2..",
    "C4..",
    "C6..",
    "Cp5.",
    "Cp3.",
    "Cp1.",
    "Cpz.",
    "Cp2.",
    "Cp4.",
    "Cp6.",
    "Fp1.",
    "Fpz.",
    "Fp2.",
]


# Thirteen electrodes of the 129 net, dropped in the coverage cases.
DROPPED = (8, 14, 17, 21, 25, 43, 48, 49, 56, 63, 68, 73, 81)


def eeg(names, kind="EEG"):
    return [[n, kind] for n in names]


def egi(n, extra=(), width=0):
    return eeg([f"E{i:0{width}d}" for i in range(1, n + 1)] + list(extra))


def biosemi_bank(count):
    return eeg(bank_labels(count))


def biosemi(banks):
    return eeg([f"{b}{i}" for b in banks for i in range(1, 33)])


CASES = [
    (
        "ten_twenty",
        "The 19 electrodes of the 10-20 system, with modern names.",
        eeg(TEN_TWENTY),
        ("placed", None, "standard_1005"),
    ),
    (
        "ten_twenty_legacy_names",
        "T3, T4, T5 and T6 are the ACNS aliases of T7, T8, P7 and P8.",
        eeg(LEGACY),
        ("placed", None, "standard_1005"),
    ),
    (
        "legacy_and_modern_name_together",
        "T3 and T7 name one electrode, so two channels map to it.",
        eeg([*TEN_TWENTY, "T3"]),
        ("refused", "duplicate_label", None),
    ),
    (
        "edf_prefix_and_reference",
        "European Data Format (EDF) style names with an EEG prefix and a "
        "reference suffix; a typed ECG channel and an untyped photic channel "
        "are excluded and not counted.",
        [*eeg([f"EEG {n}-REF" for n in TEN_TWENTY]), ["EKG", "ECG"], ["Photic", None]],
        ("placed", None, "standard_1005"),
    ),
    (
        "eeg_prefix_variants",
        "Each separator after the EEG prefix is stripped; EEG directly followed "
        "by a letter or a digit is not a prefix.",
        eeg(
            [
                "EEG:Fp1",
                "EEG_Fp2",
                "eeg-F3",
                "EEG  F4",
                "EEG - C3",
                "Eeg:_C4",
                "EEG P3",
                "EEG P4",
                "EEG O1",
                "EEGO2",
                "EEG1",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "nihon_kohden_pol_prefix",
        "Nihon Kohden names carry POL and a space, in any case; POL directly "
        "followed by a letter is not a prefix.",
        eeg(
            [
                *(f"POL {n}" for n in ["Fp1", "Fp2", "F3", "F4", "C3", "C4"]),
                *(f"POL {n}" for n in ["P3", "P4", "O1", "O2"]),
                "pol Fz",
                "POLCz",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "channel_types",
        "Types are trimmed of the step-2 whitespace and folded A to Z, without "
        "NFKC: empty and N/A are untyped, ' EEG ' and eeg are EEG, and U+FEFF "
        "before EEG, U+0085 after it, or full-width letters make another type.",
        [
            *eeg(TEN_TWENTY[:9]),
            ["Fpz", ""],
            ["Oz", "N/A"],
            ["AFz", " EEG "],
            ["POz", "eeg"],
            ["CPz", "\ufeffEEG"],
            ["FCz", "EEG\u0085"],
            ["Iz", "\uff25\uff25\uff27"],
        ],
        ("placed", None, "standard_1005"),
    ),
    (
        "names_with_other_line_breaks",
        "U+0085, U+2028 and U+FEFF are not whitespace here: names carrying them "
        "keep them and match nothing.",
        eeg([*TEN_TWENTY[:13], "Pz\u0085", "\u2028Fz", "\ufeffCz"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "unicode_hyphen_is_not_a_split",
        "Fp1-REF written with U+2010 (hyphen), not U+002D: no split, so the "
        "name matches nothing.",
        eeg([*TEN_TWENTY[1:10], "Fp1\u2010REF"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "trailing_dots_untyped",
        "Untyped names padded with dots to four characters.",
        [[n, None] for n in PHYSIONET],
        ("placed", None, "standard_1005"),
    ),
    (
        "quotes_whitespace_unicode",
        "Quotation marks, surrounding whitespace, a no-break space and "
        "full-width characters normalize to the plain name; a space inside a "
        "name stays, so P 4 matches nothing.",
        eeg(
            [
                '"Fp1"',
                "'Fp2'",
                " F3 ",
                "F4\u00a0",
                "\uff23\uff13",
                "C4\t",
                "'P3.'",
                "P\u2004 4",
                "O1",
                "O2",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "neuroscan_auxiliary_names",
        "A Neuroscan Quik-Cap 64, untyped, with its HEO and VEO eye channels and "
        "its cerebellar CB1 and CB2, which no montage places: their names "
        "exclude them, so they are not counted.",
        [[n, None] for n in QUIK_CAP_64] + [["HEO", None], ["VEO", None]],
        ("placed", None, "standard_1005"),
    ),
    (
        "clinical_auxiliary_names",
        "A clinical EDF export (the TUH EEG corpus's names), untyped: the 10-20 "
        "electrodes and A1 and A2 with -REF, the eye channels ROC, LOC, LUC and "
        "RLC, an EKG, the photic stimulus and the burst suppression trends IBI, "
        "BURSTS and SUPPR. The auxiliary names are excluded, so 21 of 21 "
        "candidates match; counted, they would hold the share to 21 of 28.",
        [
            *([f"EEG {n.upper()}-REF", None] for n in [*LEGACY, "A1", "A2"]),
            *(
                [f"EEG {n}-REF", None]
                for n in ["ROC", "LOC", "LUC", "RLC", "EKG1", "PHOTIC"]
            ),
            ["IBI", None],
            ["BURSTS", None],
            ["SUPPR", None],
        ],
        ("placed", None, "standard_1005"),
    ),
    (
        "unicode_newer_than_some_runtimes",
        "Characters whose Unicode normalization (NFKC) to ASCII depends on the "
        "Unicode version a runtime ships: OZ in outlined letters (U+1CCE4 "
        "U+1CCEF, Unicode 16), AF and an outlined 7 (U+1CCF7), Fp and the "
        "subscript z of Unicode 18 (U+209F), and the modifier capital C "
        "(U+A7F2, Unicode 14) before P1. The fold table maps none of them, so "
        "every runtime leaves the four unmatched.",
        eeg(
            [
                *TEN_TWENTY,
                "\U0001cce4\U0001ccef",
                "AF\U0001ccf7",
                "Fp\u209f",
                "\ua7f2P1",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "unicode_compatibility_characters",
        "Compatibility characters NFKC folds to ASCII in every runtime, but the "
        "fold table does not: a subscript two (F\u2082), a Roman numeral one "
        "hundred (U+216D) before 1, bold mathematical P, O and z (U+1D40F "
        "U+1D428 U+1D433), and a superscript four (AF\u2074). They stay "
        "unmatched; full-width letters and digits still fold (C3 in full width "
        "is a duplicate of C3 and is not used here).",
        eeg(
            [
                *TEN_TWENTY,
                "F\u2082",
                "\u216d1",
                "\U0001d40f\U0001d428\U0001d433",
                "AF\u2074",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "common_reference_suffix",
        "Every name but the reference's carries -Cz: the shared suffix is the "
        "recording's reference and is stripped.",
        eeg([f"{n}-Cz" for n in TEN_TWENTY if n != "Cz"] + ["Cz"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "common_reference_at_ninety_percent",
        "Nine of ten hyphenated names end in -Cz (90%): Cz is the reference, and "
        "the tenth, O1-F7, is a bipolar pair.",
        eeg([f"{n}-Cz" for n in TEN_TWENTY[:9]] + ["O1-F7", "Cz"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "common_reference_below_ninety_percent",
        "Eight of ten hyphenated names end in -Cz (80%): no common reference, so "
        "every hyphenated name is a bipolar pair.",
        eeg([f"{n}-Cz" for n in TEN_TWENTY[:8]] + ["O1-F7", "O2-F8", "Cz"]),
        ("refused", "bipolar_labels", None),
    ),
    (
        "common_reference_on_most_names",
        "Ten of 19 names end in -Cz: hyphenated names are most of the names, so "
        "-Cz is the reference.",
        eeg([f"{n}-Cz" for n in NO_CZ[:10]] + NO_CZ[10:] + ["Cz"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "common_reference_on_half_the_names",
        "Nine of 18 names end in -Cz: hyphenated names are not most of the "
        "names, so they are bipolar pairs.",
        eeg([f"{n}-Cz" for n in NO_CZ[:9]] + NO_CZ[9:]),
        ("refused", "bipolar_labels", None),
    ),
    (
        "reference_names",
        "Each reference name after the last hyphen is stripped; a name with two "
        "hyphens splits at the last, so Fpz-Fz-Ref keeps fpz-fz and matches "
        "nothing.",
        eeg(
            [
                "Fp1-Ref",
                "Fp2-REFERENCE",
                "F3-avg",
                "F4-AR",
                "C3-CAR",
                "C4-LE",
                "P3-RE",
                "P4-LM",
                "O1-RM",
                "O2-linked",
                "F7-A1",
                "F8-A2",
                "T7-A12",
                "T8-M1",
                "P7-M2",
                "P8-M12",
                "Fpz-Fz-Ref",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
    (
        "single_bipolar_among_unipolar",
        "One hyphenated name among unipolar ones is a bipolar pair, not a "
        "reference scheme: it stays unplaced and the rest are placed.",
        eeg([n for n in TEN_TWENTY if n != "Fp1"] + ["Fp1-F7"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "bipolar_double_banana",
        "A clinical bipolar montage: every name is a pair of electrodes.",
        eeg(BANANA),
        ("refused", "bipolar_labels", None),
    ),
    (
        "numeric_labels",
        "Numbered channels name no electrode.",
        [[str(i), None] for i in range(1, 33)],
        ("refused", "labels_unrecognized", None),
    ),
    (
        "share_too_low",
        "12 of 16 names match (75%).",
        eeg([*TEN_TWENTY[:12], "X1", "X2", "X3", "X4"]),
        ("refused", "share_too_low", None),
    ),
    (
        "share_at_threshold",
        "12 of 15 names match (80%, the threshold).",
        eeg([*TEN_TWENTY[:12], "X1", "X2", "X3"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "too_few_channels",
        "Seven candidate channels.",
        eeg(TEN_TWENTY[:7]),
        ("refused", "too_few_channels", None),
    ),
    (
        "too_few_matched",
        "Seven of eight names match: the share passes, the count does not.",
        eeg([*TEN_TWENTY[:7], "X1"]),
        ("refused", "too_few_matched", None),
    ),
    (
        "eight_matched",
        "Eight names, all matched (the minimum).",
        eeg(TEN_TWENTY[:8]),
        ("placed", None, "standard_1005"),
    ),
    (
        "excluded_channels_not_counted",
        "Typed non-EEG channels and untyped names with a non-EEG prefix are "
        "excluded and not counted; an EEG-typed name with such a prefix is a "
        "candidate.",
        [
            *eeg(TEN_TWENTY[:9]),
            ["HEOG", "EOG"],
            ["VEOG", "EOG"],
            ["EMG1", "EMG"],
            ["Trigger", "TRIG"],
            ["X5", "MISC"],
            *[[n, None] for n in ("EOG1", "ECG", "Resp", "Status", "EXG1", "SpO2")],
            ["EXG2", "n/a"],
            ["EOG2", "EEG"],
        ],
        ("placed", None, "standard_1005"),
    ),
    (
        "fiducials_dropped",
        "Fiducial names are not electrodes and are not counted.",
        eeg([*TEN_TWENTY[:8], "Nz", "LPA", "RPA", "NAS", "Inion"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "vref_outside_egi_nets",
        "VREF is Cz only on an EGI net, so on the 10-05 montage it stays unplaced.",
        eeg([n for n in TEN_TWENTY if n != "Cz"] + ["VREF"]),
        ("placed", None, "standard_1005"),
    ),
    (
        "egi_129",
        "An EGI 128-channel net with its vertex reference (E1 to E128 and Cz), "
        "on a cap named HydroCel GSN 128 1.0 (the sensor layout name an MFF "
        "recording carries). The 257 net holds the same names, but the 129 net, "
        "of the same family and smaller, holds every name the 257 net matched.",
        egi(128, ["Cz"]),
        ("placed", None, "GSN-HydroCel-129"),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_129_zeros_and_vref",
        "Zero-padded numbers and VREF for the vertex reference, on a cap named "
        "by its montage name, GSN-HydroCel-129.",
        egi(128, ["VREF"], width=3),
        ("placed", None, "GSN-HydroCel-129"),
        "GSN-HydroCel-129",
    ),
    (
        "egi_128",
        "E1 to E128 on a HydroCel GSN 128 1.0: the 129, 256 and 257 nets hold "
        "every name the 128 net matched and are larger nets of its family, so "
        "they do not contend.",
        egi(128),
        ("placed", None, "GSN-HydroCel-128"),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_e129",
        "E1 to E129, as many EGI exports name a 129-channel net: E129 is Cz on "
        "the 129 net. The 256 and 257 nets hold E129 as an electrode of their "
        "own, but the 129 net, of the same family and smaller, matches every "
        "channel they match. The cap model, Hydrocel Geodesic Sensor Net (as "
        "OpenNeuro ds004444 writes it), names no size, so it fits every "
        "HydroCel net.",
        egi(129),
        ("placed", None, "GSN-HydroCel-129"),
        "Hydrocel Geodesic Sensor Net",
    ),
    (
        "egi_e129_and_cz",
        "E129 and Cz are one electrode on the 129 net.",
        egi(128, ["Cz", "E129"]),
        ("refused", "duplicate_label", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_duplicate_after_zeros",
        "E001 and E1 are one electrode.",
        egi(128, ["Cz", "E001"]),
        ("refused", "duplicate_label", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_257",
        "A 256-channel net with its vertex reference, on a HydroCel GSN 256 1.0.",
        egi(256, ["Cz"]),
        ("placed", None, "GSN-HydroCel-257"),
        "HydroCel GSN 256 1.0",
    ),
    (
        "egi_256",
        "E1 to E256 on a HydroCel GSN 256 1.0: the 257 net holds no name the "
        "256 net lacks.",
        egi(256),
        ("placed", None, "GSN-HydroCel-256"),
        "HydroCel GSN 256 1.0",
    ),
    (
        "egi_65",
        "The 64-channel net, version 1.0, with its vertex reference, on a "
        "HydroCel GSN 64 1.0.",
        egi(64, ["Cz"]),
        ("placed", None, "GSN-HydroCel-65_1.0"),
        "HydroCel GSN 64 1.0",
    ),
    (
        "egi_64",
        "E1 to E64 on a HydroCel GSN 64 1.0.",
        egi(64),
        ("placed", None, "GSN-HydroCel-64_1.0"),
        "HydroCel GSN 64 1.0",
    ),
    (
        "egi_e257",
        "E1 to E257 on a HydroCel GSN 256 1.0: E257 is Cz on the 257 net.",
        egi(257),
        ("placed", None, "GSN-HydroCel-257"),
        "HydroCel GSN 256 1.0",
    ),
    (
        "egi_e65",
        "E1 to E65 on a HydroCel GSN 64 1.0: E65 is Cz on the 65 net. E65 is an "
        "electrode of the 128, 129, 256 and 257 nets, which the 65 net "
        "dismisses.",
        egi(65),
        ("placed", None, "GSN-HydroCel-65_1.0"),
        "HydroCel GSN 64 1.0",
    ),
    (
        "hbn_without_cap_model",
        "The Healthy Brain Network (HBN) releases as published: E1 to E128 and Cz "
        "on a HydroCel 128-channel net whose vertex reference is Cz, with no "
        "CapManufacturersModelName (their ManufacturersModelName names the "
        "recording system, says 128-channel GSN 200 v.2.1, and is not read). "
        "The names are numbered alike on the HydroCel nets and on older nets, "
        "on other positions, so they do not place the recording; nor is a "
        "reference reported for a refusal.",
        egi(128, ["Cz"]),
        ("refused", "cap_model_unknown", None),
        None,
        "Cz",
    ),
    (
        "hbn_with_cap_model",
        "The same channels with a corrected CapManufacturersModelName, HydroCel "
        "GSN 128 1.0, and EEGReference Cz: placed on the HydroCel 129 net, and "
        "Cz, the reference, is reported, since its values are all zero.",
        egi(128, ["Cz"]),
        ("placed", None, "GSN-HydroCel-129"),
        "HydroCel GSN 128 1.0",
        "Cz",
    ),
    (
        "reference_by_alias",
        "E1 to E128 and Cz on a HydroCel GSN 128 1.0 with EEGReference VREF, "
        "EGI's name for the vertex reference: VREF is Cz on an EGI net, so Cz "
        "is the reference channel.",
        egi(128, ["Cz"]),
        ("placed", None, "GSN-HydroCel-129"),
        "HydroCel GSN 128 1.0",
        "VREF",
    ),
    (
        "reference_on_ten_twenty",
        "The 10-20 names referenced to Cz, which is recorded: Cz is placed and "
        "reported as the reference (EEGReference written CZ, normalized as a "
        "name).",
        eeg(TEN_TWENTY),
        ("placed", None, "standard_1005"),
        None,
        " CZ ",
    ),
    (
        "reference_names_no_channel",
        "The 10-20 names with EEGReference linked mastoids: no channel is the "
        "reference.",
        eeg(TEN_TWENTY),
        ("placed", None, "standard_1005"),
        None,
        "linked mastoids",
    ),
    (
        "reference_not_recorded",
        "The 10-20 names without Cz, with EEGReference Cz: the reference is not "
        "among the channels.",
        eeg(NO_CZ),
        ("placed", None, "standard_1005"),
        None,
        "Cz",
    ),
    (
        "older_egi_net_gsn_200",
        "E1 to E128 and Cz on a cap named 128-channel GSN 200 v.2.1: no listed "
        "model, so refused. The older nets' montages (EEGLAB's GSN128 and "
        "GSN129) are never reached by name.",
        egi(128, ["Cz"]),
        ("refused", "cap_model_unknown", None),
        "128-channel GSN 200 v.2.1",
    ),
    (
        "older_egi_net_by_eeglab_file",
        "E1 to E256 on a cap named GSN256, EEGLAB's file name for an older "
        "256-channel net: not a listed model, so refused.",
        egi(256),
        ("refused", "cap_model_unknown", None),
        "GSN256",
    ),
    (
        "older_egi_net_gsn_64_v2",
        "E1 to E64 on a cap named Geodesic Sensor Net 64 2.0, the GSN 64 version "
        "2.0: not a listed model, so refused.",
        egi(64),
        ("refused", "cap_model_unknown", None),
        "Geodesic Sensor Net 64 2.0",
    ),
    (
        "cap_model_case_and_whitespace",
        "E1 to E256 on a cap named '  hydroCEL   gsn 256 1.0 ': the model is "
        "trimmed, its whitespace collapsed and its letters folded before it is "
        "compared.",
        egi(256),
        ("placed", None, "GSN-HydroCel-256"),
        "  hydroCEL   gsn 256 1.0 ",
    ),
    (
        "cap_model_of_another_size",
        "E1 to E256 on a cap named HydroCel GSN 128 1.0: the names point to the "
        "256-channel net, which the model does not name.",
        egi(256),
        ("refused", "cap_model_unknown", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "cap_model_not_listed",
        "E1 to E128 and Cz on a cap named EGI HydroCel 128: models are compared "
        "against the list exactly, so a name the list does not hold is refused.",
        egi(128, ["Cz"]),
        ("refused", "cap_model_unknown", None),
        "EGI HydroCel 128",
    ),
    (
        "cap_model_beside_other_names",
        "The 10-20 names on a cap named HydroCel GSN 128 1.0: the model is read "
        "only when the names point to a HydroCel net.",
        eeg(TEN_TWENTY),
        ("placed", None, "standard_1005"),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_prefix_of_128",
        "E1 to E100 on a HydroCel GSN 128 1.0: the 128 net holds every name, but "
        "100 is below 90% of its 128 electrodes, so the names may come from a "
        "cap this algorithm does not list.",
        egi(100),
        ("refused", "net_coverage_low", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_prefix_of_64",
        "E1 to E40 on a HydroCel GSN 64 1.0: 40 of the 64 net's electrodes.",
        egi(40),
        ("refused", "net_coverage_low", None),
        "HydroCel GSN 64 1.0",
    ),
    (
        "egi_duplicate_on_a_partial_net",
        "E1 to E100 and E001 on a HydroCel GSN 128 1.0: a duplicate is reported "
        "before the coverage.",
        egi(100, ["E001"]),
        ("refused", "duplicate_label", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "egi_e1_to_e28",
        "E1 to E28 on a HydroCel GSN 32: the 32 net and the BioSemi 160 E bank "
        "both hold the names; an ambiguity is reported before the 32 net's "
        "coverage (28 of 33).",
        egi(28),
        ("refused", "montage_ambiguous", None),
        "HydroCel GSN 32",
    ),
    (
        "egi_129_twelve_dropped",
        "E1 to E128 and Cz with twelve electrodes dropped, on a HydroCel GSN "
        "128: 117 of 129 is at least 90% of the net.",
        eeg([f"E{i}" for i in range(1, 129) if i not in DROPPED[:12]] + ["Cz"]),
        ("placed", None, "GSN-HydroCel-129"),
        "HydroCel GSN 128",
    ),
    (
        "egi_129_thirteen_dropped",
        "E1 to E128 and Cz with thirteen electrodes dropped: 116 of 129 is below "
        "90% of the net, which is reported although the cap model names the "
        "net.",
        eeg([f"E{i}" for i in range(1, 129) if i not in DROPPED] + ["Cz"]),
        ("refused", "net_coverage_low", None),
        "HydroCel GSN 128 1.0",
    ),
    (
        "biosemi_160_at_ninety_percent",
        "A1 to D32 and E1 to E16: 144 of the BioSemi 160 cap's electrodes, "
        "exactly 90%.",
        eeg([*(n for n, _ in biosemi("ABCD")), *(f"E{i}" for i in range(1, 17))]),
        ("placed", None, "biosemi160"),
    ),
    (
        "biosemi_160_below_ninety_percent",
        "A1 to D32 and E1 to E15: 143 of 160.",
        eeg([*(n for n, _ in biosemi("ABCD")), *(f"E{i}" for i in range(1, 16))]),
        ("refused", "net_coverage_low", None),
    ),
    (
        "egi_e33_ambiguous_with_biosemi_e_bank",
        "E1 to E33 on a cap named GSN-HydroCel-32: E33 is Cz on the 32 net, which "
        "matches all 33 names, but the BioSemi 160 cap's E bank matches E1 to E32 "
        "(97%) on other positions.",
        egi(33),
        ("refused", "montage_ambiguous", None),
        "GSN-HydroCel-32",
    ),
    (
        "egi_32_ambiguous_with_biosemi_e_bank",
        "E1 to E32 and Cz on a cap named GSN-HydroCel-32: the BioSemi 160 cap's E "
        "bank matches 32 of the 33 names (97%), on other positions, so the names "
        "do not identify a net.",
        egi(32, ["Cz"]),
        ("refused", "montage_ambiguous", None),
        "GSN-HydroCel-32",
    ),
    (
        "biosemi_16",
        "A BioSemi 16 cap, named by bank as a recording names it (A1 to A16).",
        biosemi_bank(16),
        ("placed", None, "biosemi16"),
    ),
    (
        "biosemi_32",
        "A BioSemi 32 cap (A1 to A32). The 128 cap's A bank holds the same names "
        "on other positions; the 32 cap, smaller, dismisses it.",
        biosemi_bank(32),
        ("placed", None, "biosemi32"),
    ),
    (
        "biosemi_64",
        "A BioSemi 64 cap (A1 to B32).",
        biosemi_bank(64),
        ("placed", None, "biosemi64"),
    ),
    (
        "biosemi_64_zero_padded",
        "A01 to B32: zero-padded bank numbers.",
        eeg([f"{n[0]}{int(n[1:]):02d}" for n, _ in biosemi_bank(64)]),
        ("placed", None, "biosemi64"),
    ),
    (
        "biosemi_64_with_exg",
        "A1 to B32 and the eight external channels, all typed EEG: the external "
        "channels stay unplaced.",
        [*biosemi_bank(64), *eeg([f"EXG{i}" for i in range(1, 9)])],
        ("placed", None, "biosemi64"),
    ),
    (
        "biosemi_64_cms_suffix",
        "A1-CMS to B32-CMS: the shared suffix names BioSemi's common mode sense "
        "reference and is stripped.",
        eeg([f"{n}-CMS" for n, _ in biosemi_bank(64)]),
        ("placed", None, "biosemi64"),
    ),
    (
        "biosemi_64_at_ninety_percent",
        "A1 to B26: 58 of the BioSemi 64 cap's electrodes, the fewest at or above 90%.",
        biosemi_bank(58),
        ("placed", None, "biosemi64"),
    ),
    (
        "biosemi_64_below_ninety_percent",
        "A1 to B25: 57 of 64.",
        biosemi_bank(57),
        ("refused", "net_coverage_low", None),
    ),
    (
        "biosemi_16_at_ninety_percent",
        "A1 to A15: 15 of the BioSemi 16 cap's electrodes, the fewest at or above 90%.",
        biosemi_bank(15),
        ("placed", None, "biosemi16"),
    ),
    (
        "biosemi_16_below_ninety_percent",
        "A1 to A14: 14 of 16.",
        biosemi_bank(14),
        ("refused", "net_coverage_low", None),
    ),
    (
        "biosemi_128",
        "A BioSemi 128 cap (A1 to D32) with external and status channels left "
        "untyped. The 160 and 256 caps hold the same names; the 128 cap, of the "
        "same family and smaller, holds every name they matched.",
        [*biosemi("ABCD"), *[[f"EXG{i}", None] for i in range(1, 9)], ["Status", None]],
        ("placed", None, "biosemi128"),
    ),
    (
        "biosemi_160",
        "A BioSemi 160 cap (A1 to E32).",
        biosemi("ABCDE"),
        ("placed", None, "biosemi160"),
    ),
    (
        "biosemi_256",
        "A BioSemi 256 cap (A1 to H32).",
        biosemi("ABCDEFGH"),
        ("placed", None, "biosemi256"),
    ),
    (
        "ten_five_or_biosemi",
        "A1, A2 and C1 to C6 are 10-05 names and BioSemi names on other "
        "positions: the two families tie.",
        eeg(["A1", "A2", "C1", "C2", "C3", "C4", "C5", "C6"]),
        ("refused", "montage_ambiguous", None),
    ),
    (
        "runner_up_at_ninety_percent",
        "18 names are both 10-05 and BioSemi 256 names; with Fz and Cz the 10-05 "
        "montage matches 20 and the BioSemi 256 cap 18 (90%, a contender).",
        eeg(
            [
                "A1",
                "A2",
                *(f"C{i}" for i in range(1, 7)),
                *(f"F{i}" for i in range(1, 11)),
                "Fz",
                "Cz",
            ]
        ),
        ("refused", "montage_ambiguous", None),
    ),
    (
        "runner_up_below_ninety_percent",
        "With Pz as well the 10-05 montage matches 21 and the BioSemi 256 cap 18 "
        "(86%, not a contender).",
        eeg(
            [
                "A1",
                "A2",
                *(f"C{i}" for i in range(1, 7)),
                *(f"F{i}" for i in range(1, 11)),
                "Fz",
                "Cz",
                "Pz",
            ]
        ),
        ("placed", None, "standard_1005"),
    ),
]


def build_vectors(montages: tuple, sha: dict[str, str]) -> str:
    cases = []
    for name, description, channels, expected, *inputs in CASES:
        cap_model, reference = (*inputs, None, None)[:2]
        result = infer_positions(
            [tuple(c) for c in channels],
            montages,
            cap_model=cap_model,
            reference=reference,
        ).to_json()
        got = (result["outcome"], result["reason"], result["montage"])
        if got != expected:
            fail(f"vector case {name}: expected {expected}, the reference gives {got}")
        cases.append(
            {
                "name": name,
                "description": description,
                "channels": channels,
                "cap_model": cap_model,
                "eeg_reference": reference,
                "result": result,
            }
        )
    document = {
        "format": ALGORITHM,
        "spec": "docs/views/sensor-labels.md",
        "description": (
            "Cases every implementation of nemar.sensor-labels.v1 reproduces. Each "
            "case lists a recording's channels as [name, BIDS type or null] in "
            "recording order, its sidecar's cap_model and eeg_reference (BIDS "
            "CapManufacturersModelName and EEGReference, each null when absent), "
            "and the result: the outcome, the refusal reason, the "
            "montage, the counts, the contending montages, the duplicated "
            "electrodes, the reference channel, and per channel its status, its "
            "normalized key and the "
            "montage electrode it is placed on. The montages are views/montages "
            "with the SHA-256 digests listed here."
        ),
        "montages": sha,
        "cases": cases,
    }
    return render(document) + "\n"


def eeglab_provenance() -> dict:
    """EEGLAB's repository, commit and license, for the files copied from it."""
    license_file = EEGLAB_SOURCES / "LICENSE"
    if sha256(license_file.read_bytes()) != EEGLAB_SHA256["LICENSE"]:
        fail("scripts/montage_sources/eeglab/LICENSE is not EEGLAB's")
    return {
        "repository": EEGLAB_REPOSITORY,
        "commit": EEGLAB_COMMIT,
        "files_last_changed": EEGLAB_FILES_COMMIT,
        "copied_to": "scripts/montage_sources/eeglab",
        "license": "BSD-2-Clause",
        "license_scope": (
            "EEGLAB's LICENSE covers eeglab.m and the functions folder; plugins "
            "may have other licenses, and it states none for sample_locs, the "
            "folder these files come from."
        ),
        "license_sha256": EEGLAB_SHA256["LICENSE"],
        "license_text": license_file.read_text(encoding="utf-8"),
    }


def generate() -> dict[Path, str]:
    import mne

    if mne.__version__ != MNE_VERSION:
        fail(f"MNE-Python is {mne.__version__}; this generator pins {MNE_VERSION}")
    names = tuple(s.name for s in SOURCES)
    if names != MONTAGE_NAMES:
        fail("the sources are not the montages of the algorithm, in its order")

    outputs: dict[Path, str] = {}
    documents, entries, sha = {}, [], {}
    for source in SOURCES:
        text, provenance = build_montage(source)
        outputs[MONTAGES / f"{source.name}.json"] = text
        documents[source.name] = json.loads(text)
        entries.append(provenance)
        sha[source.name] = provenance["sha256"]
    check_cz_variants(documents)
    check_aliases(documents)

    license_text = importlib.metadata.distribution("mne").read_text(
        "licenses/LICENSE.txt"
    )
    if license_text is None:
        fail("MNE-Python's LICENSE.txt is not in its distribution")
    provenance = {
        "format": "nemar.montages-provenance.v1",
        "description": (
            f"Where the montages of {ALGORITHM} come from. Each file holds the "
            "electrode positions MNE-Python returns for one built-in montage, "
            "or reads from one of EEGLAB's files (source, eeglab_source), times "
            "scale_to_m, rounded to 9 decimal places of a meter. Every montage "
            "is RAS: +x toward the right preauricular point, +y toward the "
            "nasion, +z up."
        ),
        "generator": "scripts/generate_montages.py",
        "mne": {
            "version": MNE_VERSION,
            "license": "BSD-3-Clause",
            "license_text": license_text,
        },
        "eeglab": eeglab_provenance(),
        "upstream": UPSTREAM,
        "montages": entries,
    }
    outputs[MONTAGES / "PROVENANCE.json"] = render(provenance) + "\n"
    montages = tuple(montage_from_json(documents[n]) for n in MONTAGE_ORDER)
    outputs[VECTORS] = build_vectors(montages, {n: sha[n] for n in MONTAGE_ORDER})
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the files on disk instead of writing them",
    )
    args = parser.parse_args(argv)
    outputs = generate()
    if not args.check:
        MONTAGES.mkdir(parents=True, exist_ok=True)
        for path, text in outputs.items():
            path.write_text(text, encoding="utf-8")
        print(f"wrote {len(outputs)} files")
        return 0
    problems = []
    for path, text in outputs.items():
        if not path.is_file():
            problems.append(f"missing: {path.relative_to(ROOT)}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"differs: {path.relative_to(ROOT)}")
    for path in sorted(MONTAGES.iterdir()):
        if path not in outputs:
            problems.append(f"not generated: {path.relative_to(ROOT)}")
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"{len(outputs)} files match")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
