# `nemar.sensor-labels.v1`

Sensor positions inferred from channel names: given a recording's channels (and, for an EGI net, its cap model), the algorithm either places them on the one standard montage their names identify, or refuses and says why.
It never assumes a default.
When the names do not identify one montage with confidence, nothing is placed, and the reason is shown instead of a map.

This page is normative.
[`views/vectors/sensor-labels.v1.json`](../../views/vectors/sensor-labels.v1.json) holds the cases every implementation reproduces,
`neuroschema.views.sensor_labels` is the Python reference (pure Python, no numpy),
and [`views/montages/`](../../views/montages/) holds the montages, with their origin in `PROVENANCE.json`.

## Where it applies

A consumer that draws sensor positions (the viewer's live scalp map, and a `nemar.sensor-field` view without a layout role) chooses positions in this order:

1. Measured positions in a frame that `nemar.sensor-layout.v1` knows are used as they are (`position_source` `measured`).
2. When the recording has no positions, declares no frame, declares a frame that `nemar.sensor-layout.v1` does not know (`frame_unknown`), or has measured positions that `nemar.sensor-layout.v1` refuses as too flat or too few to locate the head's center (`positions_flat`) or as covering too little of the head (`positions_partial`), the consumer infers positions from the channel names with this algorithm.
   The caption says that the positions are template positions matched by name, names the montage, and says why measured positions were not used.
3. When the algorithm refuses, the consumer draws no map and shows the reason.

The pipeline does not use this algorithm: a recipe that needs positions (ICLabel) still needs positions the dataset declares.

## Input

- The recording's channels in recording order, each a name (a string) and a Brain Imaging Data Structure (BIDS) channel type (a string, or absent), as in `channels.tsv`.
- Optionally, the recording's cap model: the BIDS `CapManufacturersModelName` of its `eeg.json` (a string, or absent).
  Only a placement on a HydroCel net reads it ([The cap model](#the-cap-model)).
  `ManufacturersModelName`, the amplifier's model, is not a cap model and is not read.

## Montages

| Montage | Family | Electrodes | MNE-Python montage | Origin |
|---|---|---|---|---|
| `standard_1005` | `10-05` | 343 | `colin27_1005` | FieldTrip `standard_1005.elc` |
| `GSN-HydroCel-32` | `GSN-HydroCel` | 33 | same name | Electrical Geodesics, Inc. (EGI), via FieldTrip |
| `GSN-HydroCel-64_1.0` | `GSN-HydroCel` | 64 | same name | EGI, via FieldTrip |
| `GSN-HydroCel-65_1.0` | `GSN-HydroCel` | 65 | same name | EGI, via FieldTrip |
| `GSN-HydroCel-128` | `GSN-HydroCel` | 128 | same name | EGI, via FieldTrip |
| `GSN-HydroCel-129` | `GSN-HydroCel` | 129 | same name | EGI, via FieldTrip |
| `GSN-HydroCel-256` | `GSN-HydroCel` | 256 | same name | EGI, via FieldTrip |
| `GSN-HydroCel-257` | `GSN-HydroCel` | 257 | same name | EGI, via FieldTrip |
| `biosemi16` | `BioSemi` | 16 | `biosemi16`, relabeled A1 to A16 | BioSemi head caps |
| `biosemi32` | `BioSemi` | 32 | `biosemi32`, relabeled A1 to A32 | BioSemi head caps |
| `biosemi64` | `BioSemi` | 64 | `biosemi64`, relabeled A1 to B32 | BioSemi head caps |
| `biosemi128` | `BioSemi` | 128 | same name, angles as written | BioSemi head caps |
| `biosemi160` | `BioSemi` | 160 | same name, angles as written | BioSemi head caps |
| `biosemi256` | `BioSemi` | 256 | same name, angles as written | BioSemi head caps |

The table's order is the montage order, which breaks ties.
Each file holds the positions MNE-Python 1.13.2 returns from `make_standard_montage(...).get_positions()` (for the BioSemi caps, from MNE-Python's own files as the list below says), in meters, rounded to 9 decimal places, in a right-anterior-superior (RAS) frame: +x toward the right preauricular point, +y toward the nasion, +z up.
`scripts/generate_montages.py` writes them (`uv run --group vectors python scripts/generate_montages.py`, and `--check` to compare), and refuses any other MNE-Python version or any source file whose SHA-256 differs from the one it was written for.

- `standard_1005` is MNE-Python's `colin27_1005` (MNE-Python 1.13 renamed `standard_1005`, which leaves in 1.14): FieldTrip's 10-05 positions on the Colin27 head, in Montreal Neurological Institute (MNI) coordinates, unscaled.
  It lists T3, T4, T5 and T6 on the positions of T7, T8, P7 and P8.
- The HydroCel nets are read with `head_size=None`, the file's own geometry in centimeters, converted to meters.
  Each net and its Cz variant (64 and 65, 128 and 129, 256 and 257) then share every electrode position exactly; MNE-Python's default rescales each file by its own median radius, which moves the 64/65 and 256/257 pairs apart by up to 0.14 mm.
- Older EGI nets, such as the Geodesic Sensor Net 200 and the GSN 64 version 2.0, number their electrodes E1, E2 and so on as the HydroCel nets do, on positions 20% to 40% of the head radius away.
  Channel names cannot tell them apart, so a recording is placed on a HydroCel net only when its cap model names one ([The cap model](#the-cap-model)).
- The BioSemi caps lie on a sphere of radius 0.095 m (MNE-Python's default).
  A BioSemi recording names its channels by amplifier bank (A1 to A32, then B1 to B32, and so on), while MNE-Python names the electrodes of the 16, 32 and 64 channel caps by the 10-20 system.
  The montages of those caps carry the bank labels, given to MNE-Python's electrodes in file order; BioSemi's own layout drawings label the electrodes in that order, and the generator fails unless the file order is the drawings' (`bank_labels` in `PROVENANCE.json` lists each label with its 10-20 name).
  The angles of the 16, 32 and 64 channel caps are integers, so their positions are MNE-Python's.
  `make_standard_montage` reads their angles as integers, so an angle written as 11.5 becomes 11 and the electrode moves by up to 1.8 mm.
  The generator instead reads the angles in MNE-Python's `biosemi*.txt` as written and places them with MNE-Python's own spherical conversion.
  An electrode whose angles are integers sits exactly where MNE-Python puts it; `PROVENANCE.json` lists every other electrode (`angle_corrections`) with its angles as written, MNE-Python's integer angles and the distance between the two positions.

A montage file is `{"format": "nemar.montage.v1", "name", "family", "orientation": "RAS", "unit": "m", "fiducials": {"nasion", "lpa", "rpa"}, "center": [x, y, z], "electrodes": [[label, x, y, z], ...]}`, with the electrodes in MNE-Python's order.
`center` is the montage's own center: the sphere `nemar.sensor-layout.v1` fits to all its electrodes, rounded to 9 decimal places as the positions are.
Positions placed from the montage are projected about it, never about a sphere fitted to the few a recording has (see [`sensor-layout.md`](sensor-layout.md), step 3).
A montage label's key is the label normalized as a channel name is (steps 1 to 7 below); no two labels of one montage share a key.

## Normalizing a name

1. Fold the name by this table, and leave every other character as it is:
   - the full-width forms of ASCII, U+FF01 to U+FF5E, to U+0021 to U+007E (`Ｃ３` is `C3`, and `－`, U+FF0D, is a hyphen-minus);
   - the no-break and typographic spaces U+00A0, U+2000 to U+200A, U+202F, U+205F and U+3000 to the space, U+0020.

   The table is fixed, so every runtime folds a name alike: Unicode normalization is not used, because the characters it maps grow with each Unicode version a runtime ships (Python 3.11 to 3.14 and current JavaScript engines carry Unicode 14 to 18, and disagree on outlined letters, modifier capitals and new subscripts).
   A character the table does not fold stays, and a key with any character outside ASCII matches no montage: a subscript (`O₂`), a Roman numeral (`Ⅽ3`), a mathematical letter and a Cyrillic look-alike leave the name unmatched.
2. Trim whitespace from both ends, and replace each run of whitespace inside the name with one space.
   Whitespace here is exactly TAB, LF, VT, FF and CR (U+0009 to U+000D) and space (U+0020).
   Step 1 has already turned the no-break and typographic spaces into U+0020; U+0085, U+2028, U+2029 and U+FEFF are not whitespace here and stay in the name (so `Cz` followed by U+0085 matches nothing).
3. Drop a leading type prefix: the letters E, E, G in any case, followed by one or more of space, hyphen-minus (U+002D), underscore and colon (`EEG Fp1`, `EEG-Fp1`, `eeg:_Fp1`), or the letters P, O, L in any case, followed by one or more spaces (Nihon Kohden's `POL Fp1`).
   `EEG1`, `EEGFp1` and `POLFp1` keep theirs.
4. Split at the last hyphen-minus (U+002D), as [Reference suffixes and bipolar names](#reference-suffixes-and-bipolar-names) says.
   No other dash is a split point: U+2010 (hyphen), which step 1 keeps, stays in the name, so `Fp1‐REF` written with U+2010 matches nothing.
5. Strip spaces from both ends, dots from the end, and straight quotation marks (`"` and `'`) from both ends, repeating until none is left (`Cz..` is `Cz`, `'P3.'` is `P3`).
6. Fold the ASCII letters A to Z to a to z and leave every other character.
   Every montage label is ASCII, so full Unicode case folding could not change a match, and ASCII folding keeps implementations identical.
7. Drop the leading zeros of the number in a name that is ASCII letters a-z followed by ASCII digits 0-9 (`E001` is `e1`, `A01` is `a1`, `E000` is `e0`).

The result is the channel's key.
Steps 5 to 7 also normalize each side of a split.
A space inside a name stays (`P 4` matches nothing).

## Candidates

Each channel is decided in this order:

1. A channel's type is trimmed of the step-2 whitespace at both ends and its ASCII letters A to Z are folded to a to z; it is not folded by step 1 (a type written with full-width letters, or with U+FEFF before it, is another type).
   A channel whose type is then `eeg` is in play.
   A channel with no type, an empty type or `n/a` is untyped, and is in play unless its name after steps 1 to 3, folded to lowercase, starts with one of `eog`, `heog`, `veog`, `ecg`, `ekg`, `emg`, `trig`, `status`, `stim`, `event`, `marker`, `resp`, `gsr`, `photic`, `exg`, `spo2`, `pleth`, `pulse`, `position`, `light`, `heo`, `veo`, `cb1`, `cb2`, `roc`, `loc`, `luc`, `rlc`, `ibi`, `bursts` and `suppr` (status `excluded_name`).
   The last eleven are Neuroscan's eye channels (`HEO`, `VEO`) and cerebellar electrodes (`CB1`, `CB2`), which no montage places, and a clinical EDF export's eye channels at the canthi (`ROC`, `LOC`, `LUC`, `RLC`) and burst suppression trends (`IBI`, `BURSTS`, `SUPPR`).
   No prefix starts the key of an electrode of any montage, or an alias.
   A channel of any other type is excluded (status `excluded_type`).
2. A channel in play gets its key (with the split below).
3. A channel whose key is `nz`, `lpa`, `rpa`, `nas` or `inion` is a fiducial (status `fiducial`).

The remaining channels are the candidates (status `candidate` or `bipolar`).
Excluded channels and fiducials are not counted anywhere.

## Reference suffixes and bipolar names

For a name in play with a hyphen-minus (U+002D), the right part is what follows the last one, normalized by steps 5 to 7.

- **The common reference.** Among the names in play, take those with a hyphen, and their most frequent right part R.
  R is the recording's common reference when at least 90% of the names with a hyphen have it (10 × its count ≥ 9 × their number) and the names with a hyphen are more than half of the names in play.
- When the right part is a reference name (`ref`, `reference`, `avg`, `ar`, `car`, `le`, `re`, `lm`, `rm`, `linked`, `a1`, `a2`, `a12`, `m1`, `m2`, `m12`) or the common reference, it is dropped, and the key is the left part, normalized by steps 5 to 7 (`EEG Fp1-REF` is `fp1`, `C3-A2` is `c3`).
- Otherwise, when the right part names an electrode (it is the key of an electrode of some montage, or an alias), the channel is bipolar (status `bipolar`): its key is the whole name normalized by steps 5 to 7, and it matches no montage (`Fp1-F7`).
- Otherwise the key is the whole name normalized by steps 5 to 7 (`Fp1-0` is `fp1-0`).

A name with two hyphens splits at the last (`Fpz-Fz-Ref` is `fpz-fz`, which matches nothing).

A bipolar channel is a candidate: it counts toward the candidates and is never placed.

## Matching

A candidate that is not bipolar matches a montage when its key, after the aliases of the montage's family, is the key of one of the montage's electrodes.

| Family | Aliases |
|---|---|
| `10-05` | `t3` is `t7`, `t4` is `t8`, `t5` is `p7`, `t6` is `p8` (the American Clinical Neurophysiology Society (ACNS) names) |
| `GSN-HydroCel` | `vref` is `cz` (EGI's vertex reference) |

An EGI net's vertex reference is also often named by the number after the net's last electrode.
On a larger net that number is an electrode of its own, so these aliases belong to one montage each:

| Montage | Alias |
|---|---|
| `GSN-HydroCel-32` | `e33` is `cz` |
| `GSN-HydroCel-65_1.0` | `e65` is `cz` |
| `GSN-HydroCel-129` | `e129` is `cz` |
| `GSN-HydroCel-257` | `e257` is `cz` |

A family's alias applies only to the montages of its family, and a montage's alias only to that montage: `VREF` is Cz on an EGI net and matches nothing on the 10-05 montage, and `E129` is Cz on the 129-channel net and electrode E129 on the 256-channel net.
A new alias is a new version of the algorithm.

n(m) is the number of candidates that match montage m, and *best* is the largest n(m).

## Choosing a montage

These steps run in order, and the first that refuses decides the reason.

1. **`too_few_channels`**: fewer than 8 candidates.
2. **The share**: when 5 × best < 4 × candidates (fewer than 80% match), refuse with:
   - **`bipolar_labels`** when the bipolar channels are at least half of the unmatched candidates (2 × bipolar ≥ candidates − best);
   - otherwise **`labels_unrecognized`** when no candidate matches any montage;
   - otherwise **`share_too_low`**.
3. **`too_few_matched`**: best is below 8.
4. **Contenders**: the montages with 10 × n(m) ≥ 9 × best, in montage order.
5. **Nested nets**: a contender is dismissed when another contender of the same family has fewer electrodes and matches every candidate the first one matched (each montage with its own aliases).
6. **The montage**: the first remaining contender with n(m) = best.
7. **`duplicate_label`**: two or more candidates match one electrode of the montage (`T3` and `T7`, or `E1` and `E001`).
8. **`montage_ambiguous`**: another remaining contender puts a channel that both match more than 1e-9 m (Euclidean distance) from where the montage puts it.
9. **`net_coverage_low`**: the montage is a numbered net (family `GSN-HydroCel` or `BioSemi`) and best is below 90% of its electrodes (10 × best < 9 × electrodes).
10. **`cap_model_unknown`**: the montage is a HydroCel net (family `GSN-HydroCel`) and the cap model does not name it ([The cap model](#the-cap-model)): there is none, or it is not a HydroCel model, or it names a net of another size.
11. Otherwise every candidate the montage matches is placed on its electrode, and the other candidates stay unplaced.

Every comparison of a share is between integers, so every implementation decides a boundary case the same way.

| Reason | What it means |
|---|---|
| `too_few_channels` | Fewer than 8 channels could be EEG electrodes. |
| `bipolar_labels` | Most names that did not match name a pair of electrodes (`Fp1-F7`), which has no single position. |
| `labels_unrecognized` | No name matched a standard montage. |
| `share_too_low` | Fewer than 80% of the names matched one montage. |
| `too_few_matched` | Fewer than 8 names matched one montage. |
| `duplicate_label` | Two channels name the same electrode. |
| `montage_ambiguous` | The names fit two montages that put the electrodes in different places. |
| `net_coverage_low` | The names match fewer than 90% of the electrodes of the net they point to, so they may come from another cap that shares its numbering. |
| `cap_model_unknown` | The names number an EGI net's electrodes, but the recording does not name its cap as the HydroCel net they point to, and older EGI nets number their electrodes the same way on other positions. |

### The cap model

A HydroCel placement needs the recording's cap model to name the net, because the names alone are also an older EGI net's.
The cap model is trimmed of the step-2 whitespace at both ends, each run of that whitespace inside it becomes one space, and its letters A to Z are folded to a to z; nothing else is folded.
It names the nets of the one row of this table it then equals exactly, and no net when it equals none:

| Cap model | Nets it names |
|---|---|
| `hydrocel geodesic sensor net`, `hydrocel gsn`, and `hydrocel geodisic sensor net` (the spelling of OpenNeuro ds004395) | every HydroCel net |
| `hydrocel geodesic sensor net 32`, `hydrocel gsn 32`, `hydrocel gsn 32 1.0`, `gsn-hydrocel-32` | `GSN-HydroCel-32` |
| `hydrocel geodesic sensor net 64`, `hydrocel gsn 64`, `hydrocel gsn 64 1.0`, `gsn-hydrocel-64_1.0`, `gsn-hydrocel-65_1.0` | `GSN-HydroCel-64_1.0`, `GSN-HydroCel-65_1.0` |
| `hydrocel geodesic sensor net 128`, `hydrocel gsn 128`, `hydrocel gsn 128 1.0`, `gsn-hydrocel-128`, `gsn-hydrocel-129` | `GSN-HydroCel-128`, `GSN-HydroCel-129` |
| `hydrocel geodesic sensor net 256`, `hydrocel gsn 256`, `hydrocel gsn 256 1.0`, `gsn-hydrocel-256`, `gsn-hydrocel-257` | `GSN-HydroCel-256`, `GSN-HydroCel-257` |

`HydroCel GSN 128 1.0` is the sensor layout name an EGI MFF recording carries, and `GSN-HydroCel-129` a montage name as MNE-Python, EEGLAB and FieldTrip spell it; a sized model names its net with and without the vertex reference, one physical net.
Every other string is no HydroCel model: an older net's name (`Geodesic Sensor Net 200`, `128-channel GSN 200 v.2.1`, `GSN 64 2.0`), a model with other words (`EGI HydroCel 128`, `HydroCel GSN 128 v1.0`), and one written with a no-break space or full-width letters.
A wrong guess is never made: a HydroCel recording whose sidecar names no cap model, such as the Healthy Brain Network (HBN) releases (whose `ManufacturersModelName` says `128-channel GSN 200 v.2.1`), draws no map from its names.

### Why nested nets are dismissed, and why a net needs coverage

The nets of one family number their electrodes in one sequence, so a larger net holds every name of a smaller one: E1 to E128 and Cz are names on the 257-channel net as well as the 129-channel net, on other positions.
Without step 5 every 128-channel EGI recording, and every BioSemi 16, 32, 64, 128 or 160 recording, would tie with a larger net and be refused.
A recording carries the electrodes of its net, and E1 to E128 from a 256-channel net would be half a net, so the smallest net of the family that matches every channel the larger one matches is the one the names identify.
Names cannot reveal banks a recording left unused, so a recording is placed on the smallest net it fills: A1 to A32 recorded on a 64-channel cap goes to `biosemi32`, and A1 to B32 recorded on a 128-channel cap goes to `biosemi64`.
The comparison is by channel, with each montage's own aliases, so E1 to E129 is the 129-channel net (E129 is its Cz) and not the 256-channel net (where E129 is an electrode).
Across families the rule does not apply: `A1`, `A2` and `C1` to `C6` are 10-05 names and BioSemi names on unrelated positions, and such a recording is refused.

Step 5 picks the smallest listed net that holds the names, which is only right when that net is the recording's cap.
A cap that numbers its electrodes like a listed net but is not listed would otherwise land on the smallest listed net that holds its names, with every position wrong.
Step 9 refuses unless the names cover at least 90% of the chosen net's electrodes: `E1` to `E100` is not placed on the 128-channel net, nor `E1` to `E40` on the 64-channel net.
The cost is that a recording on a listed net that dropped more than a tenth of the net's electrodes is refused too.

One refusal remains on a full real net, and it is deliberate in version 1:
a 32-channel EGI recording (`E1` to `E32` with `Cz` or `E33`), because the BioSemi 160 cap's E bank matches 32 of its 33 names on unrelated positions.

### Residual risks

These wrong placements remain possible in version 1, and are accepted:

- A recording that leaves banks of its cap unused is placed on the smallest net it fills, as above: A1 to A32 from a 64-channel cap lands on the 32-channel cap's positions.
- A recording whose cap model names a HydroCel net it was not recorded on is placed on that net's positions: the model is the writer's statement, and is not checked against anything else.
  A model with no size names every HydroCel net, so with it a recording that left most of a larger net unused can land on a smaller net, as above.
- The `POL ` prefix is dropped from untyped names too, so an untyped Nihon Kohden recording's intracranial strip or depth contacts named like scalp electrodes or bank labels (`POL C3`, `POL A1`) are read as EEG electrodes.
  A contact typed `SEEG` or `ECOG` is excluded by its type; an untyped set is refused only when the share, coverage or ambiguity rules refuse it.

## Output

| Field | Meaning |
|---|---|
| `outcome` | `placed` or `refused`. |
| `reason` | The refusal reason, or null. |
| `montage` | The montage the channels are placed on, or null. |
| `candidates` | The number of candidates. |
| `matched` | best. |
| `contenders` | The contenders left after step 5, in montage order; empty when step 1, 2 or 3 refused. |
| `duplicates` | For `duplicate_label`, the electrodes two candidates matched, in the order of their first channel. |
| `channels` | Per channel, in input order: `status`, `key` (null for an excluded channel) and `electrode` (the montage's label, for a placed channel; otherwise null). |

A consumer takes each placed channel's position from the montage file.
A sensor role that stores such positions sets `position_source` to `template`, `montage` to the montage's name and `coordinate_system` to `n/a`, and a reader reads its positions as RAS meters, the montage's frame.
The schema requires all three together.

## Versioning

A change to any step, list, threshold or alias, or to a montage's positions (including a new MNE-Python version that moves them), is a new version, `nemar.sensor-labels.v2`, with its own vectors.

## Vectors

Each case of the vectors file gives a recording's `channels` as `[name, type]` pairs (type null when absent), its `cap_model` (null when absent) and the `result` above.
The vectors file lists the SHA-256 of each montage file it was computed with; an implementation checks its copies against them, then reproduces every result exactly.
The cases cover the normalization steps (the fold table, and characters outside it whose normalization depends on the runtime's Unicode version: outlined letters and digits, a modifier capital, subscripts, a Roman numeral, mathematical letters, a superscript), the exclusions (the auxiliary names of a Neuroscan cap and of a clinical EDF export among them), each reference name and the common reference, bipolar names, each count, share and coverage threshold at and beside its boundary, each refusal, the family and montage aliases, every montage but `GSN-HydroCel-32` (its names are also the BioSemi 160 cap's E bank), the nested nets, the coincident Cz variants, and the cap model: the HBN channels with and without a model, the older nets' names, case and whitespace, a model of another size, one the list does not hold, and a model beside names that are not an EGI net's.
No two real montages place an electrode within 1e-9 m of each other without placing it at the same point, so `tests/test_sensor_labels.py` tests that tolerance on a montage derived from a real one.
