"""Tests for ``nemar.sensor-labels.v1``: channel names to template positions.

Real montages (generated from MNE-Python), the vectors file and hand-written
expectations; no mocks. A test that needs a montage the repository does not
have derives it from a real one and says how.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib.util
import json
import math
import re
import sys
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuroschema.validate import load_schema
from neuroschema.views import load_registry
from neuroschema.views.sensor_labels import (
    ALGORITHM,
    BIPOLAR,
    CANDIDATE,
    EXCLUDED_NAME,
    EXCLUDED_TYPE,
    FAMILY_ALIASES,
    FIDUCIAL,
    FIDUCIALS,
    MONTAGE_ALIASES,
    MONTAGE_FORMAT,
    MONTAGE_ORDER,
    NON_EEG_PREFIXES,
    REASONS,
    REFERENCES,
    classify,
    clean,
    finish,
    infer_positions,
    label_key,
    load_montages,
    montage_from_json,
)
from tests.helpers import failures

ROOT = Path(__file__).resolve().parent.parent
MONTAGE_DIR = ROOT / "views" / "montages"
VECTORS_PATH = ROOT / "views" / "vectors" / "sensor-labels.v1.json"
VECTORS = json.loads(VECTORS_PATH.read_text())
PROVENANCE = json.loads((MONTAGE_DIR / "PROVENANCE.json").read_text())
SPEC = (ROOT / "docs" / "views" / "sensor-labels.md").read_text()
VIEW_SCHEMA = ROOT / "schema" / "definitions" / "view.schema.json"
MONTAGES = load_montages()
BY_NAME = {m.name: m for m in MONTAGES}
CASES = VECTORS["cases"]
# The spec's lists, written out here so that dropping a member from the
# reference fails a test (a test parametrized over the reference's own tuple
# would lose that member's case with it).
SPEC_PREFIXES = [
    "eog",
    "heog",
    "veog",
    "ecg",
    "ekg",
    "emg",
    "trig",
    "status",
    "stim",
    "event",
    "marker",
    "resp",
    "gsr",
    "photic",
    "exg",
    "spo2",
    "pleth",
    "pulse",
    "position",
    "light",
]
SPEC_REFERENCES = [
    "ref",
    "reference",
    "avg",
    "ar",
    "car",
    "le",
    "re",
    "lm",
    "rm",
    "linked",
    "a1",
    "a2",
    "a12",
    "m1",
    "m2",
    "m12",
]
SPEC_FIDUCIALS = ["nz", "lpa", "rpa", "nas", "inion"]
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


def montage_document(name: str) -> dict:
    return json.loads((MONTAGE_DIR / f"{name}.json").read_text())


@functools.cache
def generator():
    """scripts/generate_montages.py as a module; it imports MNE only to generate."""
    path = ROOT / "scripts" / "generate_montages.py"
    spec = importlib.util.spec_from_file_location("generate_montages", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def infer(names, kind="EEG", montages=MONTAGES):
    return infer_positions([(n, kind) for n in names], montages)


def statuses(names_and_types):
    return [c.status for c in classify(names_and_types, MONTAGES)]


def keys(names, kind="EEG"):
    return [c.key for c in classify([(n, kind) for n in names], MONTAGES)]


# ── The vectors ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vectors_replay(case):
    channels = [(name, kind) for name, kind in case["channels"]]
    assert infer_positions(channels, MONTAGES).to_json() == case["result"]


def test_vector_file_header():
    assert VECTORS["format"] == ALGORITHM
    assert (ROOT / VECTORS["spec"]).is_file()
    assert list(VECTORS["montages"]) == list(MONTAGE_ORDER)
    for name, digest in VECTORS["montages"].items():
        data = (MONTAGE_DIR / f"{name}.json").read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name


def test_vectors_are_the_hand_written_expectations():
    """Each case's outcome, reason and montage is what the generator states.

    The generator refuses to write a result that differs from its hand-written
    expectation, so this holds the file to those expectations, not only to
    whatever the reference computes.
    """
    expected = {name: want for name, _desc, _channels, want in generator().CASES}
    assert list(expected) == [c["name"] for c in CASES]
    for case in CASES:
        result = case["result"]
        got = (result["outcome"], result["reason"], result["montage"])
        assert got == expected[case["name"]], case["name"]


def test_vectors_cover_every_reason_and_montage():
    reasons = {c["result"]["reason"] for c in CASES} - {None}
    assert reasons == set(REASONS)
    placed = {c["result"]["montage"] for c in CASES} - {None}
    assert placed == set(MONTAGE_ORDER) - {"GSN-HydroCel-32"}, (
        "GSN-HydroCel-32 is never placed: its names are the BioSemi 160 E bank's"
    )


def test_generated_files_are_in_canonical_form():
    """Each generated file is the generator's rendering of its own content.

    A hand edit that keeps the JSON valid but breaks the layout shows here;
    the full check (`--check`) needs MNE-Python and runs in CI.
    """
    render = generator().render
    for path in [*sorted(MONTAGE_DIR.glob("*.json")), VECTORS_PATH]:
        text = path.read_text(encoding="utf-8")
        assert render(json.loads(text)) + "\n" == text, path.name


def test_registry_lists_the_algorithm():
    entry = next(e for e in load_registry()["algorithms"] if e["name"] == ALGORITHM)
    assert entry == {
        "name": ALGORITHM,
        "spec": "docs/views/sensor-labels.md",
        "vectors": "views/vectors/sensor-labels.v1.json",
        "montages": "views/montages/PROVENANCE.json",
    }


# ── The montages ──────────────────────────────────────────────────────────


def test_montage_files_are_exactly_the_algorithms():
    files = sorted(p.name for p in MONTAGE_DIR.iterdir())
    assert files == sorted([*(f"{n}.json" for n in MONTAGE_ORDER), "PROVENANCE.json"])


def test_provenance_names_each_file_and_its_digest():
    assert PROVENANCE["format"] == "nemar.montages-provenance.v1"
    assert [m["name"] for m in PROVENANCE["montages"]] == list(MONTAGE_ORDER)
    for entry in PROVENANCE["montages"]:
        path = ROOT / entry["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert entry["electrodes"] == BY_NAME[entry["name"]].size
        assert entry["family"] == BY_NAME[entry["name"]].family
        assert entry["upstream"] in PROVENANCE["upstream"]
        assert entry["mne_source"].startswith("mne/channels/data/montages/")
        assert re.fullmatch(r"[0-9a-f]{64}", entry["mne_source_sha256"])


def test_provenance_pins_the_mne_version_of_the_lock():
    """PROVENANCE, the generator and the uv group name one MNE-Python version."""
    group = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]
    pins = [d for d in group["vectors"] if d.startswith("mne")]
    version = PROVENANCE["mne"]["version"]
    assert pins == [f"mne=={version}"]
    assert version == generator().MNE_VERSION
    assert PROVENANCE["mne"]["license"] == "BSD-3-Clause"
    text = PROVENANCE["mne"]["license_text"]
    assert "MNE-Python authors" in text
    assert "Redistribution and use in source and binary forms" in text


def test_standard_1005_is_fieldtrips_file():
    entry = PROVENANCE["montages"][0]
    assert entry["name"] == "standard_1005"
    assert entry["mne_source"].endswith("/colin27_1005.elc")
    assert entry["mne_source_sha256"] == generator().FIELDTRIP_STANDARD_1005_SHA256


@pytest.mark.parametrize("name", MONTAGE_ORDER)
def test_montage_is_ras_meters(name):
    doc = montage_document(name)
    assert (doc["format"], doc["unit"], doc["orientation"]) == (
        MONTAGE_FORMAT,
        "m",
        "RAS",
    )
    nasion, lpa, rpa = (doc["fiducials"][k] for k in ("nasion", "lpa", "rpa"))
    assert nasion[1] > 0.05 and abs(nasion[0]) < 0.01
    assert lpa[0] < -0.05 < 0.05 < rpa[0]
    xyz = [e[1:] for e in doc["electrodes"]]
    assert max(p[2] for p in xyz) > 0.07
    radii = sorted((x * x + y * y + z * z) ** 0.5 for x, y, z in xyz)
    assert 0.07 < radii[len(radii) // 2] < 0.12
    for value in [v for p in xyz for v in p]:
        assert round(value, 9) == value


@pytest.mark.parametrize(
    ("small", "large"),
    [
        ("GSN-HydroCel-64_1.0", "GSN-HydroCel-65_1.0"),
        ("GSN-HydroCel-128", "GSN-HydroCel-129"),
        ("GSN-HydroCel-256", "GSN-HydroCel-257"),
    ],
)
def test_cz_variants_share_every_position(small, large):
    a = {e[0]: e[1:] for e in montage_document(small)["electrodes"]}
    b = {e[0]: e[1:] for e in montage_document(large)["electrodes"]}
    assert set(b) - set(a) == {"Cz"}
    assert all(a[label] == b[label] for label in a)


BIOSEMI = ["biosemi128", "biosemi160", "biosemi256"]


def _on_sphere(theta: float, phi: float, radius: float = 0.095) -> list[float]:
    """MNE's spherical conversion: theta is the polar angle, phi the azimuth."""
    t, p = math.radians(theta), math.radians(phi)
    return [
        radius * math.sin(t) * math.cos(p),
        radius * math.sin(t) * math.sin(p),
        radius * math.cos(t),
    ]


@pytest.mark.parametrize("name", BIOSEMI)
def test_biosemi_angle_corrections_are_the_montage(name):
    """Each corrected electrode sits where its angles as written put it.

    The recorded distance is to where MNE's integer angles put it.
    """
    entry = next(m for m in PROVENANCE["montages"] if m["name"] == name)
    table = entry["angle_corrections"]
    assert table["columns"] == [
        "label",
        "theta_deg",
        "phi_deg",
        "mne_theta_deg",
        "mne_phi_deg",
        "moved_mm",
    ]
    rows = table["rows"]
    assert table["electrodes"] == len(rows) > 0
    assert table["max_moved_mm"] == max(r[-1] for r in rows)
    positions = {e[0]: e[1:] for e in montage_document(name)["electrodes"]}
    for label, theta, phi, mne_theta, mne_phi, moved_mm in rows:
        assert not (float(theta).is_integer() and float(phi).is_integer()), label
        assert (mne_theta, mne_phi) == (int(theta), int(phi)), label
        ours = _on_sphere(theta, phi)
        assert math.dist(ours, positions[label]) < 1e-9, label
        moved = math.dist(ours, _on_sphere(mne_theta, mne_phi)) * 1000
        assert abs(moved - moved_mm) <= 0.0005 + 1e-9, label


def test_biosemi_matches_mne_where_the_angles_are_integers():
    """Our parse of MNE's files places integer-angle electrodes where MNE does.

    Needs MNE-Python (`uv run --group vectors`); the Montages CI job runs it.
    """
    mne = pytest.importorskip("mne")
    from mne.channels._standard_montage_utils import MONTAGE_PATH

    for name in BIOSEMI:
        source = Path(MONTAGE_PATH) / f"{name}.txt"
        entry = next(m for m in PROVENANCE["montages"] if m["name"] == name)
        assert (
            hashlib.sha256(source.read_bytes()).hexdigest()
            == (entry["mne_source_sha256"])
        )
        rows = [line.split() for line in source.read_text().splitlines()[1:]]
        angles = {r[0]: (float(r[1]), float(r[2])) for r in rows if r}
        theirs = mne.channels.make_standard_montage(name).get_positions()["ch_pos"]
        ours = {e[0]: e[1:] for e in montage_document(name)["electrodes"]}
        assert list(ours) == list(theirs)
        corrected = {r[0] for r in entry["angle_corrections"]["rows"]}
        for label, position in ours.items():
            theta, phi = angles[label]
            if theta.is_integer() and phi.is_integer():
                assert label not in corrected
                assert position == [round(float(v), 9) + 0.0 for v in theirs[label]]
            else:
                assert label in corrected


def test_ten_five_aliases_sit_on_their_targets():
    positions = BY_NAME["standard_1005"].positions
    for source, target in FAMILY_ALIASES["10-05"].items():
        assert positions[source][1] == positions[target][1]


@pytest.mark.parametrize("name", MONTAGE_ORDER)
def test_every_montage_label_can_be_matched(name):
    for key in BY_NAME[name].positions:
        assert "-" not in key
        assert key not in FIDUCIALS
        assert not key.startswith(NON_EEG_PREFIXES)
        assert label_key(BY_NAME[name].positions[key][0]) == key


def _write(tmp_path, name, doc):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(doc))
    return path


def test_loader_refuses_a_wrong_format(tmp_path):
    doc = montage_document("biosemi128") | {"format": "nemar.montage.v0"}
    _write(tmp_path, "biosemi128", doc)
    with pytest.raises(ValueError, match=re.escape("nemar.montage.v0")):
        load_montages(tmp_path, ["biosemi128"])


def test_loader_refuses_two_labels_with_one_key(tmp_path):
    doc = montage_document("standard_1005")
    doc["electrodes"].append(["FP1", 0.0, 0.0, 0.0])
    _write(tmp_path, "standard_1005", doc)
    with pytest.raises(ValueError, match="have one key 'fp1'"):
        load_montages(tmp_path, ["standard_1005"])


def test_loader_refuses_a_position_that_is_not_finite():
    doc = montage_document("biosemi128")
    doc["electrodes"][0][1] = float("nan")
    with pytest.raises(ValueError, match="not finite"):
        montage_from_json(doc)


@pytest.mark.parametrize("field", [("unit", "mm"), ("orientation", "LPS")])
def test_loader_refuses_another_frame(field):
    with pytest.raises(ValueError, match="not RAS meters"):
        montage_from_json(montage_document("biosemi128") | dict([field]))


def test_loader_refuses_a_missing_or_misnamed_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Montage not found"):
        load_montages(tmp_path, ["biosemi128"])
    _write(tmp_path, "biosemi160", montage_document("biosemi128"))
    with pytest.raises(ValueError, match="names montage 'biosemi128'"):
        load_montages(tmp_path, ["biosemi160"])


# ── Normalizing a name ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Fp1", "fp1"),
        ("FP1", "fp1"),
        ("\uff26\uff50\uff11", "fp1"),  # full-width letters and digit (NFKC)
        ("\u00a0Cz\u00a0", "cz"),  # no-break spaces (NFKC, then trimmed)
        ("\tCz\r\n", "cz"),
        ("P  z", "p z"),  # an inner run of whitespace becomes one space
        ("EEG Fp1", "fp1"),
        ("eeg-Fp1", "fp1"),
        ("EEG:_ Fp1", "fp1"),
        ("EEGFp1", "eegfp1"),  # a letter is not a separator
        ("EEG1", "eeg1"),  # nor is a digit
        ("EEG", "eeg"),
        ("Cz..", "cz"),
        ("Fc5.", "fc5"),
        ('"Fp1"', "fp1"),
        ("'P3.'", "p3"),
        ("Fp1 .", "fp1"),
        (".Fp1", ".fp1"),  # a leading dot stays
        ("E001", "e1"),
        ("A01", "a1"),
        ("E000", "e0"),
        ("E0", "e0"),
        ("Fp01", "fp1"),
        ("007", "007"),  # digits alone are not letters then digits
        ("AF7h", "af7h"),
        ("\u00df", "\u00df"),  # only A to Z fold
    ],
)
def test_normalized_key(name, key):
    assert keys([name]) == [key]


def test_clean_keeps_case_and_inner_hyphens():
    assert clean("  EEG  Fp1-REF ") == "Fp1-REF"
    assert finish(" 'Cz.' ") == "cz"


def test_the_lists_are_the_specs():
    assert list(NON_EEG_PREFIXES) == SPEC_PREFIXES
    assert sorted(REFERENCES) == sorted(SPEC_REFERENCES)
    assert sorted(FIDUCIALS) == sorted(SPEC_FIDUCIALS)
    assert FAMILY_ALIASES == {
        "10-05": {"t3": "t7", "t4": "t8", "t5": "p7", "t6": "p8"},
        "GSN-HydroCel": {"vref": "cz"},
    }
    assert MONTAGE_ALIASES == {
        "GSN-HydroCel-32": {"e33": "cz"},
        "GSN-HydroCel-65_1.0": {"e65": "cz"},
        "GSN-HydroCel-129": {"e129": "cz"},
        "GSN-HydroCel-257": {"e257": "cz"},
    }


@pytest.mark.parametrize("reference", SPEC_REFERENCES)
def test_each_reference_suffix_is_dropped(reference):
    assert keys([f"Fp1-{reference.upper()}"]) == ["fp1"]


def test_an_electrode_suffix_makes_a_bipolar_pair():
    names = [("Fp1-F7", "EEG"), ("C3-T3", "EEG"), ("E1-VREF", "EEG")]
    assert statuses(names) == [BIPOLAR] * 3


def test_another_suffix_stays_in_the_key():
    channels = classify([("Fp1-0", "EEG"), ("Fp1-", "EEG"), ("-Fp1", "EEG")], MONTAGES)
    assert [(c.status, c.key) for c in channels] == [
        (CANDIDATE, "fp1-0"),
        (CANDIDATE, "fp1-"),
        (BIPOLAR, "-fp1"),  # the right part names an electrode
    ]


def test_a_name_splits_at_its_last_hyphen():
    channels = classify([("Fp1-F7-REF", "EEG"), ("C3-C4-Cz", "EEG")], MONTAGES)
    assert [(c.status, c.key) for c in channels] == [
        (CANDIDATE, "fp1-f7"),
        (BIPOLAR, "c3-c4-cz"),
    ]


def test_the_common_reference_is_the_part_after_the_last_hyphen():
    names = [(f"{n}-L-Cz", "EEG") for n in TEN_TWENTY[:10]]
    assert [(c.status, c.key) for c in classify(names, MONTAGES)][:2] == [
        (CANDIDATE, "fp1-l"),
        (CANDIDATE, "fp2-l"),
    ]


@pytest.mark.parametrize("prefix", SPEC_PREFIXES)
def test_each_non_eeg_prefix_excludes_an_untyped_channel(prefix):
    for kind in (None, "", "n/a", "N/A", " n/a "):
        assert statuses([(f"{prefix.upper()}1", kind)]) == [EXCLUDED_NAME]
        assert statuses([(f"EEG {prefix}", kind)]) == [EXCLUDED_NAME]
    assert statuses([(f"{prefix.upper()}1", "EEG")]) == [CANDIDATE]


@pytest.mark.parametrize("kind", ["EOG", "MISC", "ECG", "TRIG", "SEEG", "eegx"])
def test_a_typed_non_eeg_channel_is_excluded(kind):
    assert statuses([("Cz", kind)]) == [EXCLUDED_TYPE]


@pytest.mark.parametrize("kind", ["EEG", "eeg", " EEG "])
def test_an_eeg_channel_is_in_play(kind):
    assert statuses([("Cz", kind)]) == [CANDIDATE]


@pytest.mark.parametrize("fiducial", SPEC_FIDUCIALS)
def test_each_fiducial_is_dropped(fiducial):
    assert statuses([(fiducial.upper(), "EEG"), (f"{fiducial}-REF", None)]) == [
        FIDUCIAL,
        FIDUCIAL,
    ]


def test_excluded_channels_have_no_key():
    channels = classify([("EOG1", None), ("Cz", "MISC")], MONTAGES)
    assert [c.key for c in channels] == [None, None]


# ── Choosing a montage ────────────────────────────────────────────────────


def test_aliases_belong_to_their_family():
    """VREF is Cz on an EGI net only; T3 is T7 on the 10-05 montage only."""
    egi = infer([f"E{i}" for i in range(1, 129)] + ["VREF"])
    assert egi.montage == "GSN-HydroCel-129"
    assert egi.channels[-1].electrode == "Cz"
    ten_five = infer([n for n in TEN_TWENTY if n != "Cz"] + ["VREF"])
    assert ten_five.montage == "standard_1005"
    assert ten_five.channels[-1].electrode is None
    legacy = infer(["T3" if n == "T7" else n for n in TEN_TWENTY])
    assert legacy.channels[TEN_TWENTY.index("T7")].electrode == "T7"


@pytest.mark.parametrize(
    ("last", "net"),
    [
        (33, "GSN-HydroCel-32"),
        (65, "GSN-HydroCel-65_1.0"),
        (129, "GSN-HydroCel-129"),
        (257, "GSN-HydroCel-257"),
    ],
)
def test_the_number_after_a_nets_last_electrode_is_its_cz(last, net):
    """E129 is Cz on the 129 net and electrode E129 wherever it is a label."""
    keys_ = BY_NAME[net].positions
    assert f"e{last}" not in keys_ and "cz" in keys_
    names = [f"E{i}" for i in range(1, last + 1)]
    assert infer(names, montages=(BY_NAME[net],)).channels[-1].electrode == "Cz"
    for other in MONTAGES:
        if other.name != net and f"e{last}" in other.positions:
            placed = infer(names, montages=(other,)).channels[-1].electrode
            assert placed == f"E{last}", other.name


def test_dismissal_compares_channels_with_each_montages_aliases():
    """E1 to E129: the 129 net matches E129 as Cz, so it dismisses the 256 net."""
    result = infer([f"E{i}" for i in range(1, 130)])
    assert (result.montage, result.contenders) == (
        "GSN-HydroCel-129",
        ("GSN-HydroCel-128", "GSN-HydroCel-129"),
    )


def test_placed_channels_carry_the_montages_positions():
    result = infer([*TEN_TWENTY[:7], "T3", "X1"])
    assert result.outcome == "placed"
    t7 = montage_document("standard_1005")
    t7 = next(e[1:] for e in t7["electrodes"] if e[0] == "T7")
    assert result.channels[7].position == tuple(t7)
    assert result.channels[8].position is None
    assert all(c.position is not None for c in result.channels[:8])


def test_a_refusal_places_nothing():
    result = infer(TEN_TWENTY[:7])
    assert result.reason == "too_few_channels"
    assert all(c.electrode is None and c.position is None for c in result.channels)


def _moved(name: str, label: str, dx: float):
    """A copy of a real montage with one electrode moved dx meters along x."""
    montage = BY_NAME[name]
    positions = dict(montage.positions)
    key = label_key(label)
    spelled, (x, y, z) = positions[key]
    positions[key] = (spelled, (x + dx, y, z))
    return tuple(
        dataclasses.replace(m, positions=positions) if m.name == name else m
        for m in MONTAGES
    )


@pytest.mark.parametrize(("dx", "outcome"), [(0.5e-9, "placed"), (2e-9, "refused")])
def test_coincidence_tolerance(dx, outcome):
    """E1 to E128 and Cz: the 128 and 129 nets must agree within 1e-9 m."""
    names = [f"E{i}" for i in range(1, 129)] + ["Cz"]
    result = infer(names, montages=_moved("GSN-HydroCel-128", "E7", dx))
    assert result.outcome == outcome
    if outcome == "refused":
        assert result.reason == "montage_ambiguous"
        assert result.contenders == ("GSN-HydroCel-128", "GSN-HydroCel-129")


def test_nested_nets_are_dismissed_within_a_family_only():
    hbn = infer([f"E{i}" for i in range(1, 129)] + ["Cz"])
    assert (hbn.montage, hbn.contenders) == (
        "GSN-HydroCel-129",
        ("GSN-HydroCel-128", "GSN-HydroCel-129"),
    )
    shared = infer(["A1", "A2", "C1", "C2", "C3", "C4", "C5", "C6"])
    assert (shared.reason, shared.contenders) == (
        "montage_ambiguous",
        ("standard_1005", "biosemi128"),
    )


def test_montages_of_one_size_never_dismiss_each_other():
    """Only a net with fewer electrodes dismisses another of its family.

    Derived input: a second copy of the real BioSemi 128 cap under another
    name, so two montages of one family and one size hold the same names.
    """
    copy = dataclasses.replace(BY_NAME["biosemi128"], name="biosemi128-copy")
    result = infer(
        [f"{bank}{i}" for bank in "ABCD" for i in range(1, 33)],
        montages=(*MONTAGES, copy),
    )
    assert (result.montage, result.contenders) == (
        "biosemi128",
        ("biosemi128", "biosemi128-copy"),
    )


def test_the_montage_is_first_in_order_among_equal_counts():
    """The 64 net is dismissed by nothing; with Cz the 65 net has the most."""
    result = infer([f"E{i}" for i in range(1, 65)] + ["Cz"])
    assert result.contenders == ("GSN-HydroCel-64_1.0", "GSN-HydroCel-65_1.0")
    assert result.montage == "GSN-HydroCel-65_1.0"


def test_reasons_are_checked_in_order():
    # Seven channels, none matched: too few channels before anything else.
    assert infer([f"X{i}" for i in range(7)]).reason == "too_few_channels"
    # Seven of nine matched: the share (78%) refuses before the count.
    assert infer([*TEN_TWENTY[:7], "X1", "X2"]).reason == "share_too_low"
    # A duplicate refuses before an ambiguity is looked for.
    dup = infer(["A1", "A2", "C1", "C2", "C3", "C4", "C5", "C6", "C6"])
    assert (dup.reason, dup.duplicates) == ("duplicate_label", ("C6",))


def test_unmatched_half_bipolar_is_bipolar_labels():
    """Two of four unmatched names are bipolar: at least half, so bipolar_labels."""
    names = [*TEN_TWENTY[:12], "Fp1-F7", "F3-C3", "X1", "X2"]
    assert infer(names).reason == "bipolar_labels"
    names = [*TEN_TWENTY[:12], "Fp1-F7", "X1", "X2", "X3"]
    assert infer(names).reason == "share_too_low"


def test_infer_reads_the_repository_montages_by_default():
    assert infer_positions([(n, "EEG") for n in TEN_TWENTY]).montage == (
        "standard_1005"
    )


# ── The spec page ─────────────────────────────────────────────────────────


def test_spec_names_every_list_member_and_threshold():
    """The normative page and the reference carry the same lists."""
    for word in [
        *REASONS,
        *NON_EEG_PREFIXES,
        *REFERENCES,
        *FIDUCIALS,
        *MONTAGE_ORDER,
        *FAMILY_ALIASES,
    ]:
        assert f"`{word}`" in SPEC, word
    for family, aliases in FAMILY_ALIASES.items():
        for source, target in aliases.items():
            assert f"`{source}` is `{target}`" in SPEC, (family, source)
    for montage, aliases in MONTAGE_ALIASES.items():
        for source, target in aliases.items():
            row = f"| `{montage}` | `{source}` is `{target}` |"
            assert row in SPEC, row
    for phrase in [
        "fewer than 8 candidates",
        "best is below 8",
        "5 \u00d7 best < 4 \u00d7 candidates",
        "10 \u00d7 n(m) \u2265 9 \u00d7 best",
        "10 \u00d7 its count \u2265 9 \u00d7 their number",
        "more than half of the names in play",
        "more than 1e-9 m",
        "MNE-Python 1.13.2",
    ]:
        assert phrase in SPEC, phrase


# ── The montage field of a sensor role ────────────────────────────────────


def data_errors(entry: dict) -> set[tuple[str, str]]:
    _schema, resolver = load_schema(VIEW_SCHEMA)
    validator = Draft202012Validator(
        {"$ref": f"file://{VIEW_SCHEMA}#/$defs/viewData"}, resolver=resolver
    )
    return failures(validator.iter_errors(entry))


def positions_role(**fields) -> dict:
    return {
        "role": "positions",
        "location": "views/sub-01_chanlocs.tsv",
        "format": "tsv",
        "size": 1024,
        "sha256": "a" * 64,
        "coordinate_system": "n/a",
        **fields,
    }


@pytest.mark.parametrize("name", MONTAGE_ORDER)
def test_a_template_role_names_its_montage(name):
    assert data_errors(positions_role(position_source="template", montage=name)) == (
        set()
    )


def test_a_montage_needs_template_positions():
    measured = positions_role(position_source="measured", montage="biosemi128")
    assert data_errors(measured) == {("const", "position_source")}
    assert data_errors(positions_role(montage="biosemi128")) == {("required", "")}


def test_a_template_role_names_its_montage_with_no_frame():
    """A template role carries montage and coordinate_system n/a (RAS meters)."""
    assert data_errors(positions_role(position_source="template")) == {("required", "")}
    framed = positions_role(
        position_source="template", montage="biosemi128", coordinate_system="CTF"
    )
    assert data_errors(framed) == {("const", "coordinate_system")}
    unframed = positions_role(position_source="template", montage="biosemi128")
    del unframed["coordinate_system"]
    assert data_errors(unframed) == {("required", "")}
    measured = positions_role(position_source="measured", coordinate_system="CTF")
    assert data_errors(measured) == set()


@pytest.mark.parametrize("name", ["", "-biosemi", "a b", "biosemi128\n", "x" * 65])
def test_a_montage_name_is_a_plain_name(name):
    entry = positions_role(position_source="template", montage=name)
    assert data_errors(entry) == {("pattern", "montage")}
