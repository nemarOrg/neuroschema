# `nemar.sensor-layout.v1`

The transform from three-dimensional sensor positions to the layout `nemar.sensor-field.v1` draws: each sensor's topoplot theta and radius.
This page is normative.
[`views/vectors/sensor-layout.v1.json`](../../views/vectors/sensor-layout.v1.json) holds the cases every implementation reproduces, and `neuroschema.views.sensor_layout.sensor_layout` is the Python reference (install the `views` extra).
The vectors' theta and radius come from eegprep's `convertlocs(..., 'cart2topo')` at commit `edf694c8344b9c4c68672eac3acf9a819f1462a8`, applied to positions centered by this page's sphere fit.

## Input

The positions of one recording's sensors, one row each: a name, `x`, `y` and `z`, Institute of Electrical and Electronics Engineers (IEEE) 754 binary64 values in one unit (any unit; the layout does not depend on it), in the frame a Brain Imaging Data Structure (BIDS) coordinate system names, and, when the file has the column, the row's `sensor_type` (its BIDS channel type, as `channels.tsv` gives it).
Template positions, taken from a standard montage by `nemar.sensor-labels.v1` (a sensor role with `position_source` `template`), name that montage instead: their coordinate system is `n/a`, and `montage` is one of the montage names that algorithm lists, every one of which is in a right-anterior-superior frame, in meters.

A view declares the transform in one of two forms (`schema/views/transform.nemar.sensor-layout.v1.schema.json`), and names the frame once in either:

- **Stored positions.**
  The positions are the view's data role `positions`, a tab-separated values (TSV) file with the columns `name`, `x`, `y` and `z`, which carries `coordinate_system` (and, for template positions, `montage`) itself.
  The transform then takes no parameters, and the view has no inputs.
  `nemar.sensor-field` version 1 declares the transform this way (see [`sensor-field.md`](sensor-field.md#sensors)).
- **Positions as an input.**
  The positions are the view's one input, the role `positions`, a TSV file of the run's product with the same columns, and the transform's parameters name the frame: `coordinate_system`, and `montage` for template positions.

## Algorithm

1. **Frame.**
   The positions are rotated into the anterior-left-superior (ALS) frame: x anterior, y left, z superior.
   A coordinate system of [ALS orientation](#frames) is kept as it is.
   One of right-anterior-superior (RAS) orientation (x right, y anterior, z superior) becomes ALS as `(x, y, z) -> (y, -x, z)`, the second component negated, not subtracted from 0.
   Template positions (coordinate system `n/a` and a `montage`) are RAS.
   The montage is compared exactly, case included, against the twenty names of [`sensor-labels.md`](sensor-labels.md#montages), never looked up as a file: a file system may fold case, and `views/montages` also holds `PROVENANCE.json`, which is not a montage.
   Anything else is refused with `frame_unknown`: any other name, including `Other`, `Pixels`, `individual` and a known name in another case; `n/a` without a montage; a montage that is not one of the twenty (`gsn-hydrocel-32`, `PROVENANCE`); and a montage beside a coordinate system other than `n/a`, whose frame would be ambiguous.
   No frame is assumed.
2. **Rows without a position.**
   A row whose x, y or z is not finite has no position, and neither has a row at exactly (0, 0, 0), with either sign of zero: files write it for a position they do not have, and no sensor sits at a frame's origin.
   A row without a position has no layout (no theta and no radius) and takes no part in the fit.
   **Scalp rows.**
   Only the sensors a scalp map draws are laid out: the scalp rows.
   When any row's `sensor_type`, trimmed of whitespace and folded A to Z as `nemar.sensor-labels.v1` reads a channel type, is a type (not absent, empty or `n/a`), the scalp rows are the rows whose type is `eeg`; EOG, ECG, EMG and the other types, and rows with no type, are not.
   When no row has a type, every row is a scalp row but one whose name starts with a non-EEG prefix of `nemar.sensor-labels.v1` (`EOG1`, `ECG`, `HEO`), as that algorithm reads an untyped name.
   Either way, a row whose name is a fiducial (`Nz`, `LPA`, `RPA`, `NAS`, `inion`, normalized as that algorithm normalizes a name) is not a scalp row.
   A row that is not a scalp row has no layout and takes no part in the fit or its bounds: an eye or neck electrode, or a fiducial below the cap, would move the sphere (8.5% of the head radius for three eye and two neck electrodes beside a 32-sensor cap, in the vectors), and a flat layout with fiducials at their true heights would pass the flatness bounds.
3. **Center.**
   No center is guessed: positions that do not fix one are refused with `positions_flat` or `positions_partial`, and a renderer places the sensors by name instead.
   - **Template positions** (`n/a` and a `montage`) are centered on the montage's own center, the `center` its file in `views/montages` stores (right-anterior-superior meters, rotated into ALS as the positions are; method `montage`).
     That center is the sphere this step fits to all of the montage's electrodes, computed once when the montage files are generated (`scripts/generate_montages.py`, which `--check` holds to it).
     Template positions are never fitted themselves: a subset of a montage, such as its midline or one coronal row, fixes no sphere of its own, and about the montage's center each electrode lands where the full cap puts it.
     A montage outside the twenty is refused with `frame_unknown` at step 1.
   - **Measured positions** are centered on the sphere fitted to all their scalp rows with a position, whether or not a view draws a value for each, so a writer gives the recording's full set of measured positions (method `sphere`).
     With `n` such positions `p`, the centroid `c0` is their sum, in row order, divided by `n`; `q = p - c0`; the scale `s` is the largest Euclidean length of a `q`; and `u = q / s`.
     If `s = 0` (no positions, or all at one point), they are refused.
     **Flatness bound 1.**
     With `σ1 ≥ σ2 ≥ σ3` the singular values of the `n`-by-3 matrix `u` (the square roots of the eigenvalues of the 3-by-3 matrix `uᵀu`), the positions are refused when `σ3 < 0.05 * σ1`: they lie too close to one plane (any three or fewer positions, a line, a ring, a disk, a midline) to fix a head.
     **The sphere.**
     Fit `x*x + y*y + z*z = 2*a*x + 2*b*y + 2*c*z + d` to the `u` by least squares: each `u` gives the row `(2*ux, 2*uy, 2*uz, 1)` of a matrix `A` and the value `ux*ux + uy*uy + uz*uz` of a vector `b`, and `(a, b, c, d)` solves the 4-by-4 normal equations `(Aᵀ A) w = Aᵀ b` by lower-upper (LU) decomposition with partial pivoting, as `nemar.sensor-field.v1` solves its matrix.
     **Flatness bound 2.**
     The sphere's radius, in units of `s`, is `rho = sqrt(a*a + b*b + c*c + d)`; the positions are refused when `rho > 3`: a shallow patch of the head whose sphere is mostly a guess.
     **The coverage bound.**
     For each position, `e` is the unit vector from the sphere's center toward it, `(u - (a, b, c))` divided by its Euclidean length.
     `M` is the 4-by-4 mean, over the positions in row order, of `[ex, ey, ez, 1]ᵀ [ex, ey, ez, 1]`.
     The dilution `D` is the square root of the sum of the first three diagonal entries of `M⁻¹`, each found by solving `M x = e_k` (`k` = 1, 2, 3) by LU decomposition with partial pivoting, as above.
     The positions are refused with `positions_partial` when `D > 4.5`, or when `D` is not finite (a position at the center, or a singular `M`).
     Otherwise the center is `c0 + s * (a, b, c)`.
   The flatness bounds are scale-invariant, and they separate with margin what lies near one plane or on a shallow patch from what does not: whole caps and the subsets a recording uses measure `σ3 / σ1` of 0.12 or more and `rho` of 1.6 or less (F3, F4, C3, C4, P3 and P4 alone: 0.15 and 1.1), while a midline, a coronal row or a flat layout measured with noise measures `σ3 / σ1` near 1e-5 to 2e-3 and, when fitted anyway, `rho` from 16 to 1500.
   The coverage bound refuses what passes them and still fixes the center badly: a set that covers one region of the head.
   `D` measures how much departures from a sphere move the fitted center: when `n` positions depart from a sphere independently, along its radius, by a share `σ` of the radius, the center's error has a root mean square of about `D * σ / sqrt(n)` radii (a simulation of the Emotiv, central, frontal and 10-20 sets agrees within 2%).
   It grows as the directions bunch together or lie on one band, and it is scale-invariant and independent of the number of positions.
   An even cover of a whole sphere measures 3, of a hemisphere `sqrt(18)` (4.24), and of a cap reaching 85° from its top about 4.55.
   The bound was measured on the 10-05 positions of the Colin27 head (`standard_1005` as measured positions), against the fit error of a set: the largest planar distance, as a share of the head radius, between a sensor projected about the sphere fitted to the set and about the montage's own center.

   | Measured positions | `D` | Fit error | |
   |---|---|---|---|
   | actiCAP 32 | 3.26 | 1.4% | drawn |
   | the 19 electrodes of the 10-20 system | 3.46 | 4.6% | drawn |
   | 16 of the 10-20 electrodes (OpenBCI 16) | 3.88 | 2.6% | drawn |
   | Fp1, Fp2, C3, C4, P7, P8, O1 and O2 (OpenBCI 8) | 4.19 | 7.0% | drawn |
   | Fz, Cz, Pz, P3, P4, PO7, PO8 and Oz | 4.86 | 4.5% | refused |
   | the 14 electrodes of the Emotiv EPOC, a ring with no top | 5.96 | 10.0% | refused |
   | FC3, FCz, FC4, C3, Cz, C4, CP3, CPz and CP4 | 5.99 | 14.8% | refused |
   | F3, F4, C3, C4, O1 and O2 | 6.92 | 8.8% | refused |
   | Fp1, Fp2, AF3, AF4, F7 and F8 | 8.02 | 30.1% | refused |
   | F3, F4, C3, C4, P3 and P4 | 17.15 | 17.3% | refused |

   With 3 mm of independent noise on each position (1000 draws per set), no whole-head cap of 16 or more sensors measured above 4.13 and none was refused, while the reviewers' frontal, central and Emotiv sets never measured below 4.76 and were never drawn; the montages of `views/montages` measure 3.06 to 3.75 and the measured positions of the BIDS example datasets 3.10 to 3.71.
   The bound 4.5 lies in that gap.
   The Emotiv set is refused because its fit error, 10% of the head radius, is twice the 5% a drawn set may have.
   Sets of eight sensors straddle the bound when measured with noise (OpenBCI 8 was drawn in 98% of the draws, the posterior P300 set in 4%): the bound measures how the positions cover the head, so a sparse set that spans it is drawn with its larger error, and a regional set that happens to fit well is refused.
   Each vector case of measured positions records its three measures (`bounds`), and the cases pin each bound from both sides.
4. **Topoplot coordinates.**
   For each scalp row with a position, `(X, Y, Z)` is the position minus the center, and, with `k` 180/π computed in binary64 (57.29577951308232):
   `theta = -(atan2(Y, X) * k)`, written 180 where this gives -180, so theta lies in (-180, 180];
   `radius = 0.5 - (atan2(Z, hypot(X, Y)) * k) / 180`.
   `atan2` keeps the sign of zero, as IEEE 754 and every common math library do: a point straight behind the center has theta 180 whether its Y is +0 or -0.

The output is one layout row per input row, in input order: the name, theta in degrees and the radius, or no layout for a row that is not a scalp row or has no position.

## Refusals

| Word | When |
|---|---|
| `frame_unknown` | The coordinate system is not in the [frame table](#frames), and the positions are not template positions (`n/a` with a montage). |
| `positions_flat` | Measured positions do not fix a center: no scalp row with a position, all at one point, too close to one plane (singular ratio below 0.05), or on a sphere more than 3 times their scale (step 3). |
| `positions_partial` | Measured positions cover too little of the head to fix its center: the dilution of their center is above 4.5 (step 3), as for a frontal, central or occipital set, or a ring with no top. |

When the layout is refused, a renderer places the sensors by their names with `nemar.sensor-labels.v1`, a separate algorithm specified beside this one, and says why.
After `frame_unknown`, it says that the positions' coordinate system is not one whose orientation is known, or names it inconsistently.
After `positions_flat`, it says that the positions are too flat, or too few, to locate the center of the head.
After `positions_partial`, it says that the positions cover too little of the head to locate its center.

## Frames

The table is BIDS's own, from the coordinate-systems appendix of the BIDS specification at commit `147b46d7`: every name whose orientation BIDS states.

| Orientation | Coordinate systems |
|---|---|
| ALS | `CTF`, `4DBti`, `KitYokogawa`, `EEGLAB`, `EEGLAB-HJ` |
| RAS | `NeuromagElektaMEGIN`, `ElektaNeuromag` (deprecated), `ChietiItab`, `CapTrak`, `ACPC`, `ScanRAS`, and the standard template identifiers: `ICBM452AirSpace`, `ICBM452Warp5Space`, `IXI549Space`, `fsaverage`, `fsaverageSym`, `fsLR`, `MNIColin27`, `MNI152Lin`, `MNI152NLin2009aSym`, `MNI152NLin2009bSym`, `MNI152NLin2009cSym`, `MNI152NLin2009aAsym`, `MNI152NLin2009bAsym`, `MNI152NLin2009cAsym`, `MNI152NLin6Sym`, `MNI152NLin6ASym`, `MNI305`, `NIHPD`, `OASIS30AntsOASISAnts`, `OASIS30Atropos`, `Talairach`, `UNCInfant`, and the deprecated `fsaverage3`, `fsaverage4`, `fsaverage5`, `fsaverage6`, `fsaveragesym`, `UNCInfant0V21`, `UNCInfant1V21`, `UNCInfant2V21`, `UNCInfant0V22`, `UNCInfant1V22`, `UNCInfant2V22`, `UNCInfant0V23`, `UNCInfant1V23` and `UNCInfant2V23` |

Names are compared exactly, case included.
Template positions, `n/a` with a montage, are RAS.
`Pixels` (positions on an image), `Other`, and the image-space names `individual`, `study` and `scanner`, whose orientation BIDS leaves to other files, are not in the table.

## Parity

An implementation matches a vector case when:

- it refuses the cases the vector refuses, with the same word, and gives a layout for the others, with no layout for the same rows;
- its center is within `1e-9 * s` of the vector's (with `s` the scale of step 3), and its center method (`montage` or `sphere`) is the vector's;
- it gives a layout to the same rows: the scalp rows with a position;
- for measured positions, its three measures of step 3 (`bounds`: `singular_ratio`, and `radius_ratio` and `dilution` when reached) are each within `1e-6` of the vector's, refused cases included; every vector keeps them at least 0.002, 0.05 and 0.05 from their bounds, so an implementation that computes them as accurately decides as the vector does;
- each radius is within `1e-12` of the vector's;
- each sensor's planar point `(cos(theta) * radius, sin(theta) * radius)` is within `1e-12` of the vector's.

Theta is compared through the planar point because it is undefined at the pole: a sensor straight above the center has radius 0 and any theta.
Each `cart2topo` entry gives a centered ALS point and the theta and radius it converts to, with no fit; an implementation's theta is within `1e-9` degrees of it, with no wrapping, so a point straight behind the center must give 180, and its radius is within `1e-12`.

## eegprep at the reference commit

- **The center is this page's.**
  eegprep centers positions with `chancenter`, which searches for the sphere with `fminsearch`; a search cannot be reproduced to parity in another language, so this page fits the sphere algebraically and the vectors convert positions centered by that fit.
  The generator fits the sphere a second way, by singular value decomposition and least squares, and the two centers agree far inside the tolerance.
  The algebraic center is not `chancenter`'s geometric one (which minimizes the spread of the distances to the center): measured on the vectors' drawn caps, they differ by 0.71% of the head radius on the twelve-position frame cases, 0.54% on GSN 65 (`positions_measured`), 0.50% on HydroCel 257, 0.39%, 0.37% and 0.34% on HydroCel 32 (with three rows at the origin, with two rows missing, and whole, with or without its eye and neck rows), 0.18% on the 10-20 electrodes of the Colin27 head (with or without its fiducials), and 0 on BioSemi 128, the 10-5 template and the spherical cap of dilution 4.36, whose positions lie on an exact sphere; a difference of that size moves a sensor's radius by a few thousandths.
- **Flat positions and subsets.**
  `chancenter` needs four positions and otherwise keeps the origin, and it centers any set it is given, flat, partial or not, on a sphere through that set: a midline alone gets a sphere that puts every electrode on one ear, and six frontal electrodes one that moves them by 30% of the head radius.
  This page centers template positions on their montage's own center and refuses measured positions that do not fix a center (`positions_flat`, `positions_partial`), rather than project them about a guess.
- **The rows fitted.**
  `chancenter` fits every channel it is given; this page fits only the scalp rows with a position, so eye, neck and fiducial rows, and rows written as (0, 0, 0), neither move the center nor get a place.
- **Theta near ±180.**
  `convertlocs` wraps theta twice with `((v + 180) mod 360) - 180` and a `numpy.isclose` test, which writes a point straight behind the center as -180 when its Y is +0 and as 180 when its Y is -0, and can move the last digit of other angles.
  This page writes (-180, 180]; the vectors write eegprep's -180 as 180, and the tolerance absorbs the last digit.
- **Frames.**
  eegprep converts the positions it is given and has no frame table; the table is this page's, taken from BIDS.

## Vectors

[`views/vectors/sensor-layout.v1.json`](../../views/vectors/sensor-layout.v1.json) has the reference (eegprep's commit, the numpy and scipy versions, and the BIDS specification the frames come from), the tolerances above, `frames` (the ALS and RAS names, and the orientation of template positions), `cart2topo` (centered points straight to theta and radius, including the axes, the poles and points straight behind with Y = +0 and Y = -0), and the cases.
Each case gives `coordinate_system`, `montage` for template positions, `positions` (`name`, `x`, `y`, `z`, with `null` for a number that is not finite, and `sensor_type` when the case has that column), `bounds` for measured positions (the three measures of step 3), and either `refused` (the word) or `expected`: `center` (in ALS), `center_method` (`montage` or `sphere`), and `theta_deg` and `radius` per row (`null` for a row with no layout).
An implementation gives the case `frame_als`'s layout for every ALS name and the case `frame_ras`'s for every RAS name.
The cases cover:

- drawn caps: a 128-sensor cap in millimeters (RAS), a 339-position 10-5 template in meters (ALS), a 32-sensor cap moved off center, the frame cases, and rows without a position;
- the bounds, each from both sides: a whole sphere squashed to singular ratios 0.055 (passed, then refused as partial) and 0.045 (refused as flat), spherical caps with sphere radii 2.8 (passed, then refused as partial) and 3.1 (refused as flat) times their scale, and spherical caps of dilution 4.36 (drawn) and 4.62 (refused as partial);
- measured sets: the 10-20 electrodes of the Colin27 head (drawn), the Emotiv 14, six frontal and nine central electrodes of that head (refused as partial), F3, F4, C3, C4, P3 and P4 alone (refused as partial), and the nine midline positions Fpz to Oz (refused as flat);
- the rows fitted: three rows at (0, 0, 0) with either sign of zero, eye and neck rows beside a cap (typed, and untyped with non-EEG names), fiducial rows beside the 10-20 electrodes (typed and untyped), each of which gets no layout and leaves the center the cap's, and a flat layout with fiducials at their true heights (refused as flat);
- flat sets, each refused (`positions_flat`): a ring, a flat disk, a disk measured with noise, five collinear positions and five a hair off one line, three positions and four coincident ones;
- template positions: the whole GSN-HydroCel-32 and standard_1005 montages, and the standard_1005 midline (Fpz to Oz) and coronal row (T7 to T8), drawn where the whole montage puts them; and a montage beside a named coordinate system, a montage named in another case and the montage `PROVENANCE` (each refused, `frame_unknown`);
- eleven coordinate systems that are refused.
Each case's positions are frozen in `scripts/view_vector_inputs.json` ([`sensor-field.md`](sensor-field.md#vectors)).

`scripts/generate_view_vectors.py` writes this file with the sensor-field vectors; see [`sensor-field.md`](sensor-field.md#vectors).
