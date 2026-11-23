"""``nemar.sensor-labels.v1``: sensor positions inferred from channel names.

Given a recording's channels (name and BIDS type, in recording order), the
algorithm normalizes each name, matches the names against a fixed set of
standard montages, and either places the channels on the one montage the names
identify or refuses with a reason. It never falls back to a default: when no
montage is a confident match, nothing is placed and the reason says why.

``docs/views/sensor-labels.md`` is the normative text,
``views/vectors/sensor-labels.v1.json`` holds the cases every implementation
reproduces, and ``views/montages/`` holds the montages (generated from MNE-Python
by ``scripts/generate_montages.py``). This module is pure Python, with no numpy,
so it runs wherever neuroschema does.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
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
    "duplicate_label",
    "montage_ambiguous",
    "net_coverage_low",
)

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
    """

    outcome: str
    reason: str | None
    montage: str | None
    candidates: int
    matched: int
    contenders: tuple[str, ...]
    duplicates: tuple[str, ...]
    channels: tuple[Channel, ...]

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
            "channels": [
                {"status": c.status, "key": c.key, "electrode": c.electrode}
                for c in self.channels
            ],
        }


# ── Normalization ─────────────────────────────────────────────────────────


def ascii_lower(text: str) -> str:
    """Fold A-Z to a-z and leave every other character as it is."""
    return text.translate(_UPPER)


def clean(name: str) -> str:
    """Steps 1 to 3: NFKC, trim and collapse whitespace, drop a type prefix."""
    text = unicodedata.normalize("NFKC", name)
    text = _WHITESPACE_RUN.sub(" ", text.strip(_WHITESPACE))
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


def _type_class(channel_type: str | None) -> str:
    if channel_type is None:
        return "untyped"
    folded = ascii_lower(channel_type.strip(_WHITESPACE))
    if folded in ("", "n/a"):
        return "untyped"
    return "eeg" if folded == "eeg" else "other"


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
        kind = _type_class(channel_type)
        if kind == "other":
            status.append(EXCLUDED_TYPE)
        elif kind == "untyped" and ascii_lower(text).startswith(NON_EEG_PREFIXES):
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
        if key in montage.positions:
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
) -> Inference:
    """Apply ``nemar.sensor-labels.v1`` to a recording's channels.

    ``channels`` is (name, BIDS type or None) per channel, in recording order;
    ``montages`` defaults to :func:`load_montages`. See
    ``docs/views/sensor-labels.md`` for each rule.
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
        "placed", None, winner.name, candidates, best, tuple(names), (), tuple(placed)
    )


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
