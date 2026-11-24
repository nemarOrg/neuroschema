"""``nemar.sensor-labels.v1``: sensor positions inferred from channel names.

Given a recording's channels (name and BIDS type, in recording order) and,
optionally, its sidecar's cap model and reference, the algorithm
normalizes each name, matches the names against a fixed set of standard
montages, and either places the channels on the one montage the names identify
or refuses with a reason. It never falls back to a default: when no montage is
a confident match, nothing is placed and the reason says why.

``docs/views/sensor-labels.md`` is the normative text,
``views/vectors/sensor-labels.v1.json`` holds the cases every implementation
reproduces, and ``views/montages/`` holds the montages (generated from MNE-Python
and EEGLAB's files by ``scripts/generate_montages.py``). This module is pure
Python, with no numpy, so it runs wherever neuroschema does.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ALGORITHM = "nemar.sensor-labels.v1"
MONTAGE_FORMAT = "nemar.montage.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
MONTAGES_DIR = REPO_ROOT / "views" / "montages"

# The montages, in the order that breaks a tie between equal match counts.
MONTAGE_ORDER = (
    "standard_1005",
    "GSN-HydroCel-32",
    "GSN-HydroCel-64_1.0",
    "GSN-HydroCel-65_1.0",
    "GSN-HydroCel-128",
    "GSN-HydroCel-129",
    "GSN-HydroCel-256",
    "GSN-HydroCel-257",
    "biosemi16",
    "biosemi32",
    "biosemi64",
    "biosemi128",
    "biosemi160",
    "biosemi256",
)
# Montage files that names never reach: EEGLAB's files of EGI's nets from before
# the HydroCel nets. No cap model this algorithm can source names them, and
# their geometry is EEGLAB's alone, so they are not matched by name; a sensor
# role may still store template positions from them, named exactly.
TEMPLATE_ONLY_MONTAGES = (
    "GSN64v2_0",
    "GSN65v2_0",
    "GSN128",
    "GSN129",
    "GSN256",
    "GSN257",
)
# Every montage file of views/montages, by its exact name.
MONTAGE_NAMES = MONTAGE_ORDER + TEMPLATE_ONLY_MONTAGES

# An untyped channel whose name starts with one of these is not EEG.
NON_EEG_PREFIXES = (
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
    # Neuroscan's eye channels and cerebellar electrodes, which no montage
    # places.
    "heo",
    "veo",
    "cb1",
    "cb2",
    # Eye channels at the outer and upper or lower canthi, and the burst
    # suppression trends, of clinical EDF exports (the TUH EEG corpus).
    "roc",
    "loc",
    "luc",
    "rlc",
    "ibi",
    "bursts",
    "suppr",
)
FIDUCIALS = frozenset({"nz", "lpa", "rpa", "nas", "inion"})
# A right part (after the last hyphen) naming a reference, not an electrode.
REFERENCES = frozenset(
    {
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
    }
)
# Aliases apply only to the montages of their family. A new alias is a new
# version of the algorithm.
FAMILY_ALIASES: Mapping[str, Mapping[str, str]] = {
    # The American Clinical Neurophysiology Society (ACNS) renamed these.
    "10-05": {"t3": "t7", "t4": "t8", "t5": "p7", "t6": "p8"},
    # EGI's vertex reference electrode.
    "GSN-HydroCel": {"vref": "cz"},
}
# Aliases of one montage. An EGI net's vertex reference, Cz, is often named by
# the number after the net's last electrode; on a larger net that number is an
# electrode of its own, so the alias belongs to the one net.
MONTAGE_ALIASES: Mapping[str, Mapping[str, str]] = {
    "GSN-HydroCel-32": {"e33": "cz"},
    "GSN-HydroCel-65_1.0": {"e65": "cz"},
    "GSN-HydroCel-129": {"e129": "cz"},
    "GSN-HydroCel-257": {"e257": "cz"},
}

MIN_CHANNELS = 8
MIN_MATCHED = 8
# Shares are integer ratios, compared by cross-multiplying, so every
# implementation decides a boundary case the same way.
MIN_SHARE = (4, 5)
CONTENDER_SHARE = (9, 10)
COMMON_REFERENCE_SHARE = (9, 10)
COINCIDENT_M = 1e-9
# A recording on a numbered net carries most of the net: a chosen net of these
# families must match at least 90% of its electrodes.
NET_FAMILIES = ("GSN-HydroCel", "BioSemi")
NET_COVERAGE = (9, 10)

# EGI's nets number their electrodes E1, E2, ...: the HydroCel nets, and the
# older Geodesic Sensor Nets, which put the same numbers on positions 20% to
# 40% of the head radius away. Names never tell which, so a HydroCel placement
# needs the recording's cap model (BIDS CapManufacturersModelName) to name the
# net. Each model, folded by fold_cap_model, names the nets it fits, each net
# with and without its vertex reference; a model without a size fits every
# HydroCel net. Any other string names no net. A new model is a new version.
EGI_FAMILIES = ("GSN-HydroCel",)
_HYDROCEL_NETS = {
    "32": ("GSN-HydroCel-32",),
    "64": ("GSN-HydroCel-64_1.0", "GSN-HydroCel-65_1.0"),
    "128": ("GSN-HydroCel-128", "GSN-HydroCel-129"),
    "256": ("GSN-HydroCel-256", "GSN-HydroCel-257"),
}
_EVERY_HYDROCEL_NET = tuple(n for nets in _HYDROCEL_NETS.values() for n in nets)
CAP_MODELS: Mapping[str, tuple[str, ...]] = {
    "hydrocel geodesic sensor net": _EVERY_HYDROCEL_NET,
    # The misspelling of OpenNeuro ds004395's CapManufacturersModelName.
    "hydrocel geodisic sensor net": _EVERY_HYDROCEL_NET,
    "hydrocel gsn": _EVERY_HYDROCEL_NET,
    **{
        model: nets
        for size, nets in _HYDROCEL_NETS.items()
        for model in (
            f"hydrocel geodesic sensor net {size}",
            f"hydrocel gsn {size}",
            # The sensor layout name an EGI MFF recording carries.
            f"hydrocel gsn {size} 1.0",
        )
    },
    # The montage names (MNE-Python's, EEGLAB's and FieldTrip's files).
    **{name.lower(): nets for nets in _HYDROCEL_NETS.values() for name in nets},
}

# Channel status, decided from the names alone.
EXCLUDED_TYPE = "excluded_type"
EXCLUDED_NAME = "excluded_name"
FIDUCIAL = "fiducial"
BIPOLAR = "bipolar"
CANDIDATE = "candidate"

# Refusal reasons, in the order they are checked.
REASONS = (
    "too_few_channels",
    "bipolar_labels",
    "labels_unrecognized",
    "share_too_low",
    "too_few_matched",
    "cap_model_unknown",
    "duplicate_label",
    "montage_ambiguous",
    "net_coverage_low",
)

# Step 1's fold table, the same in every runtime: full-width ASCII (U+FF01 to
# U+FF5E) to ASCII, and the compatibility spaces to U+0020. Nothing else is
# folded, so a name keeps any other character, and a key that is not ASCII
# matches no montage.
_FOLD = {
    **{cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)},
    **{cp: 0x20 for cp in (0x00A0, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000)},
}
_WHITESPACE = "\t\n\v\f\r "
_WHITESPACE_RUN = re.compile(r"[\t\n\v\f\r ]+")
# A type prefix: EEG and a separator, or Nihon Kohden's POL and a space.
_TYPE_PREFIX = re.compile(r"[Ee][Ee][Gg][ \-_:]+|[Pp][Oo][Ll] +")
_LEADING_ZEROS = re.compile(r"([a-z]+)0+([0-9]+)")
_UPPER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True)
class Montage:
    """One standard montage: electrode labels and RAS positions in meters.

    ``positions`` maps each label's key (:func:`finish` of the label) to the
    label as the montage spells it and its (x, y, z) position.
    """

    name: str
    family: str
    labels: tuple[str, ...]
    positions: Mapping[str, tuple[str, tuple[float, float, float]]]

    @property
    def size(self) -> int:
        return len(self.labels)


@dataclass(frozen=True)
class Channel:
    """The outcome for one input channel.

    ``key`` is the normalized name (None for a channel excluded by its type or
    name). ``electrode`` and ``position`` are set only for a channel placed on
    the chosen montage.
    """

    name: str
    type: str | None
    status: str
    key: str | None
    electrode: str | None = None
    position: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class Inference:
    """The outcome for a recording: placed on one montage, or refused.

    ``candidates`` counts the channels that are neither excluded nor fiducials
    (bipolar channels included); ``matched`` is the most candidates any one
    montage matched. ``contenders`` lists the montages still competing when the
    choice was made, and ``duplicates`` the electrodes two channels mapped to.
    ``reference`` is the name of the placed channel the recording's reference
    names, whose values are all zero: a map leaves it out of the interpolation.
    """

    outcome: str
    reason: str | None
    montage: str | None
    candidates: int
    matched: int
    contenders: tuple[str, ...]
    duplicates: tuple[str, ...]
    channels: tuple[Channel, ...]
    reference: str | None = None

    def to_json(self) -> dict:
        """The result as the vectors file records it (positions omitted)."""
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "montage": self.montage,
            "candidates": self.candidates,
            "matched": self.matched,
            "contenders": list(self.contenders),
            "duplicates": list(self.duplicates),
            "reference": self.reference,
            "channels": [
                {"status": c.status, "key": c.key, "electrode": c.electrode}
                for c in self.channels
            ],
        }


# ── Normalization ─────────────────────────────────────────────────────────


def ascii_lower(text: str) -> str:
    """Fold A-Z to a-z and leave every other character as it is."""
    return text.translate(_UPPER)


def fold(text: str) -> str:
    """Step 1: full-width ASCII to ASCII and the compatibility spaces to a space.

    The table is fixed (:data:`_FOLD`), unlike Unicode normalization, whose
    mappings grow with each Unicode version a runtime ships.
    """
    return text.translate(_FOLD)


def clean(name: str) -> str:
    """Steps 1 to 3: fold, trim and collapse whitespace, drop a type prefix."""
    text = _WHITESPACE_RUN.sub(" ", fold(name).strip(_WHITESPACE))
    prefix = _TYPE_PREFIX.match(text)
    return text[prefix.end() :] if prefix else text


def finish(part: str) -> str:
    """Steps 5 to 7 for a name or one side of a hyphen.

    Strip spaces at both ends, dots at the end and quotation marks at both
    ends until none is left, fold A-Z to lowercase, and drop leading zeros
    from the number of a letters-then-digits name (E001 is e1, A01 is a1).
    """
    text = part
    while True:
        stripped = text.strip(" ").rstrip(".").strip("\"'")
        if stripped == text:
            break
        text = stripped
    text = ascii_lower(text)
    zeros = _LEADING_ZEROS.fullmatch(text)
    return zeros[1] + zeros[2] if zeros else text


def label_key(label: str) -> str:
    """The key of a montage label: the name normalized as a channel name is."""
    return finish(clean(label))


def type_class(channel_type: str | None) -> str:
    """``eeg``, ``untyped`` or ``other``: a BIDS channel type, trimmed of the
    step-2 whitespace and folded A to Z, never otherwise normalized."""
    if channel_type is None:
        return "untyped"
    folded = ascii_lower(channel_type.strip(_WHITESPACE))
    if folded in ("", "n/a"):
        return "untyped"
    return "eeg" if folded == "eeg" else "other"


def excluded_by_name(cleaned: str) -> bool:
    """An untyped channel whose name, after steps 1 to 3, starts with a non-EEG
    prefix (:data:`NON_EEG_PREFIXES`, compared in lowercase)."""
    return ascii_lower(cleaned).startswith(NON_EEG_PREFIXES)


def fold_cap_model(model: str) -> str:
    """A cap model as :data:`CAP_MODELS` compares it: trimmed and with each
    run of step-2 whitespace one space, A to Z folded, and nothing else."""
    return ascii_lower(_WHITESPACE_RUN.sub(" ", model.strip(_WHITESPACE)))


def sidecar_inputs(sidecar: Mapping) -> dict[str, str | None]:
    """The keyword arguments :func:`infer_positions` takes from a recording's
    sidecar: its ``CapManufacturersModelName`` and ``EEGReference``, each None
    unless a string.

    ``sidecar`` is the ``eeg.json`` that applies to the recording after BIDS
    inheritance: the files from the dataset level down to the recording's own,
    a key at a lower level replacing the same key above it.
    ``ManufacturersModelName`` names the recording system, not the cap, and is
    not read: the Healthy Brain Network releases' says GSN 200 of a HydroCel
    net.
    """

    def text(key: str) -> str | None:
        value = sidecar.get(key)
        return value if isinstance(value, str) else None

    return {
        "cap_model": text("CapManufacturersModelName"),
        "reference": text("EEGReference"),
    }


def cap_model_nets(model: str | None) -> tuple[str, ...]:
    """The EGI montages a cap model names (none for no model, or for any
    string not in :data:`CAP_MODELS`)."""
    if model is None:
        return ()
    return tuple(CAP_MODELS.get(fold_cap_model(model), ()))


def _common_reference(rights: Sequence[str], pending: int) -> str | None:
    """The right part most labels share, if it is the recording's reference.

    It is shared by at least 90% of the labels that have a right part, and
    those labels are more than half of the channels still in play: a few
    hyphenated names among unipolar ones are bipolar pairs, not a scheme.
    """
    if not rights or len(rights) * 2 <= pending:
        return None
    value, count = Counter(rights).most_common(1)[0]
    num, den = COMMON_REFERENCE_SHARE
    return value if count * den >= num * len(rights) else None


def aliases(montage: Montage) -> Mapping[str, str]:
    """The aliases that apply to a montage: its family's and its own."""
    return {
        **FAMILY_ALIASES.get(montage.family, {}),
        **MONTAGE_ALIASES.get(montage.name, {}),
    }


def electrode_keys(montages: Iterable[Montage]) -> frozenset[str]:
    """Every key that names an electrode in some montage, aliases included."""
    keys: set[str] = set()
    for montage in montages:
        keys.update(montage.positions)
        keys.update(aliases(montage))
    return frozenset(keys)


def classify(
    channels: Sequence[tuple[str, str | None]], montages: Sequence[Montage]
) -> list[Channel]:
    """Each channel's status and key, before any montage is chosen."""
    cleaned = [clean(name) for name, _type in channels]
    status: list[str | None] = []
    for (_name, channel_type), text in zip(channels, cleaned, strict=True):
        kind = type_class(channel_type)
        if kind == "other":
            status.append(EXCLUDED_TYPE)
        elif kind == "untyped" and excluded_by_name(text):
            status.append(EXCLUDED_NAME)
        else:
            status.append(None)
    pending = [i for i, s in enumerate(status) if s is None]
    rights = [
        finish(cleaned[i].rpartition("-")[2]) for i in pending if "-" in cleaned[i]
    ]
    common = _common_reference(rights, len(pending))
    names = electrode_keys(montages)
    out: list[Channel] = []
    for i, ((name, channel_type), text) in enumerate(
        zip(channels, cleaned, strict=True)
    ):
        if status[i] is not None:
            out.append(Channel(name, channel_type, status[i], None))
            continue
        state, key = CANDIDATE, finish(text)
        if "-" in text:
            left, _, right = text.rpartition("-")
            right_key = finish(right)
            if right_key in REFERENCES or right_key == common:
                key = finish(left)
            elif right_key in names:
                state = BIPOLAR
        if state == CANDIDATE and key in FIDUCIALS:
            state = FIDUCIAL
        out.append(Channel(name, channel_type, state, key))
    return out


# ── The choice ────────────────────────────────────────────────────────────


def _hits(montage: Montage, channels: Sequence[Channel]) -> dict[int, str]:
    """Candidate index -> the montage key it matches."""
    hits: dict[int, str] = {}
    redirect = aliases(montage)
    for i, channel in enumerate(channels):
        if channel.status != CANDIDATE:
            continue
        key = redirect.get(channel.key, channel.key)
        if key.isascii() and key in montage.positions:
            hits[i] = key
    return hits


def _refused(
    reason: str,
    candidates: int,
    matched: int,
    channels: Sequence[Channel],
    contenders: Sequence[str] = (),
    duplicates: Sequence[str] = (),
) -> Inference:
    return Inference(
        "refused",
        reason,
        None,
        candidates,
        matched,
        tuple(contenders),
        tuple(duplicates),
        tuple(channels),
    )


def infer_positions(
    channels: Iterable[tuple[str, str | None]],
    montages: Sequence[Montage] | None = None,
    *,
    cap_model: str | None = None,
    reference: str | None = None,
) -> Inference:
    """Apply ``nemar.sensor-labels.v1`` to a recording's channels.

    ``channels`` is (name, BIDS type or None) per channel, in recording order;
    ``montages`` defaults to :func:`load_montages`. ``cap_model`` and
    ``reference`` are the recording's ``CapManufacturersModelName`` and
    ``EEGReference`` (:func:`sidecar_inputs` reads both from its sidecar): a
    placement on a HydroCel net needs the cap model to name that net
    (:data:`CAP_MODELS`), and the placed channel the reference names is
    reported (:attr:`Inference.reference`). See ``docs/views/sensor-labels.md``
    for each rule.
    """
    montages = load_montages() if montages is None else tuple(montages)
    channels = [(name, channel_type) for name, channel_type in channels]
    classified = classify(channels, montages)
    candidates = sum(c.status in (CANDIDATE, BIPOLAR) for c in classified)
    bipolar = sum(c.status == BIPOLAR for c in classified)
    hits = {m.name: _hits(m, classified) for m in montages}
    best = max((len(h) for h in hits.values()), default=0)

    if candidates < MIN_CHANNELS:
        return _refused("too_few_channels", candidates, best, classified)
    num, den = MIN_SHARE
    if best * den < candidates * num:
        unmatched = candidates - best
        if bipolar * 2 >= unmatched:
            reason = "bipolar_labels"
        elif best == 0:
            reason = "labels_unrecognized"
        else:
            reason = "share_too_low"
        return _refused(reason, candidates, best, classified)
    if best < MIN_MATCHED:
        return _refused("too_few_matched", candidates, best, classified)

    num, den = CONTENDER_SHARE
    contenders = [m for m in montages if len(hits[m.name]) * den >= best * num]
    named = cap_model_nets(cap_model)
    kept = [m for m in contenders if m.family not in EGI_FAMILIES or m.name in named]
    if not any(len(hits[m.name]) == best for m in kept):
        names = [m.name for m in contenders]
        return _refused("cap_model_unknown", candidates, best, classified, names)
    contenders = kept
    remaining = [
        m
        for m in contenders
        if not any(
            s.family == m.family
            and s.size < m.size
            and hits[m.name].keys() <= hits[s.name].keys()
            for s in contenders
        )
    ]
    names = [m.name for m in remaining]
    winner = next(m for m in remaining if len(hits[m.name]) == best)
    chosen = hits[winner.name]

    counts = Counter(chosen.values())
    duplicates: list[str] = []
    for key in chosen.values():
        label = winner.positions[key][0]
        if counts[key] > 1 and label not in duplicates:
            duplicates.append(label)
    if duplicates:
        return _refused(
            "duplicate_label", candidates, best, classified, names, duplicates
        )

    for other in remaining:
        if other is winner:
            continue
        theirs = hits[other.name]
        for i in chosen.keys() & theirs.keys():
            here = winner.positions[chosen[i]][1]
            there = other.positions[theirs[i]][1]
            if math.dist(here, there) > COINCIDENT_M:
                return _refused(
                    "montage_ambiguous", candidates, best, classified, names
                )

    num, den = NET_COVERAGE
    if winner.family in NET_FAMILIES and best * den < winner.size * num:
        return _refused("net_coverage_low", candidates, best, classified, names)

    placed = []
    for i, channel in enumerate(classified):
        if i in chosen:
            label, position = winner.positions[chosen[i]]
            channel = Channel(
                channel.name, channel.type, channel.status, channel.key, label, position
            )
        placed.append(channel)
    return Inference(
        "placed",
        None,
        winner.name,
        candidates,
        best,
        tuple(names),
        (),
        tuple(placed),
        reference_channel(reference, winner, classified, chosen),
    )


def reference_channel(
    reference: str | None,
    montage: Montage,
    channels: Sequence[Channel],
    chosen: Mapping[int, str],
) -> str | None:
    """The name of the placed channel the recording's reference names, or None.

    The reference (BIDS ``EEGReference``) is normalized as a montage label is
    (:func:`label_key`), with the montage's aliases; the channel placed on that
    electrode is the reference channel. A reference that names no placed
    channel (``average``, ``linked mastoids``, an electrode not recorded)
    gives None.
    """
    if reference is None:
        return None
    key = label_key(reference)
    key = aliases(montage).get(key, key)
    for i, electrode in chosen.items():
        if electrode == key:
            return channels[i].name
    return None


# ── Montages ──────────────────────────────────────────────────────────────


def montage_from_json(document: Mapping) -> Montage:
    """Build a montage from its parsed ``views/montages/<name>.json`` document."""
    if document.get("format") != MONTAGE_FORMAT:
        raise ValueError(
            f"montage {document.get('name')!r}: format is "
            f"{document.get('format')!r}, not {MONTAGE_FORMAT!r}"
        )
    if document.get("unit") != "m" or document.get("orientation") != "RAS":
        raise ValueError(f"montage {document['name']!r}: not RAS meters")
    positions: dict[str, tuple[str, tuple[float, float, float]]] = {}
    labels = []
    for label, x, y, z in document["electrodes"]:
        key = label_key(label)
        if not key.isascii():
            raise ValueError(f"montage {document['name']!r}: {label!r} is not ASCII")
        if key in positions:
            raise ValueError(
                f"montage {document['name']!r}: {label!r} and "
                f"{positions[key][0]!r} have one key {key!r}"
            )
        xyz = (float(x), float(y), float(z))
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError(f"montage {document['name']!r}: {label!r} not finite")
        positions[key] = (label, xyz)
        labels.append(label)
    return Montage(document["name"], document["family"], tuple(labels), positions)


def load_montages(
    directory: Path = MONTAGES_DIR, names: Sequence[str] = MONTAGE_ORDER
) -> tuple[Montage, ...]:
    """Load the montages, in the order given, from a neuroschema checkout."""
    montages = []
    for name in names:
        path = directory / f"{name}.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Montage not found: {path}. neuroschema reads views/montages/ from "
                "a checkout of its repository (it is not packaged)."
            )
        montage = montage_from_json(json.loads(path.read_text(encoding="utf-8")))
        if montage.name != name:
            raise ValueError(f"{path}: names montage {montage.name!r}")
        montages.append(montage)
    return tuple(montages)
