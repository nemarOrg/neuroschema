# `nemar.sensor-layout.v1`

The transform from three-dimensional sensor positions to the layout `nemar.sensor-field.v1` draws: each sensor's topoplot theta and radius.
This page is normative.
[`views/vectors/sensor-layout.v1.json`](../../views/vectors/sensor-layout.v1.json) holds the cases every implementation reproduces, and `neuroschema.views.sensor_layout.sensor_layout` is the Python reference (install the `views` extra).
The vectors' theta and radius come from eegprep's `convertlocs(..., 'cart2topo')` at commit `edf694c8344b9c4c68672eac3acf9a819f1462a8`, applied to positions centered by this page's sphere fit.

## Input

The positions of one recording's sensors, one row each: a name and `x`, `y` and `z`, Institute of Electrical and Electronics Engineers (IEEE) 754 binary64 values in one unit (any unit; the layout does not depend on it), in the frame a Brain Imaging Data Structure (BIDS) coordinate system names.
Template positions, taken from a standard montage by `nemar.sensor-labels.v1` (a sensor role with `position_source` `template`), name that montage instead: their coordinate system is `n/a`, and `montage` is the name of a file of `views/montages`, every one of which is in a right-anterior-superior frame, in meters.
In a view, the positions are the input role `positions`, a tab-separated values (TSV) file of the run's product with the columns `name`, `x`, `y` and `z`; the transform's parameter `coordinate_system` names the frame, and `montage`, for template positions, the montage (`schema/views/transform.nemar.sensor-layout.v1.schema.json`).

## Algorithm

1. **Frame.**
   The positions are rotated into the anterior-left-superior (ALS) frame: x anterior, y left, z superior.
   A coordinate system of [ALS orientation](#frames) is kept as it is.
   One of right-anterior-superior (RAS) orientation (x right, y anterior, z superior) becomes ALS as `(x, y, z) -> (y, -x, z)`, the second component negated, not subtracted from 0.
   Template positions (coordinate system `n/a` and a `montage`) are RAS.
   Anything else is refused with `frame_unknown`: any other name, including `Other`, `Pixels`, `individual` and a known name in another case; `n/a` without a montage; and a montage beside a coordinate system other than `n/a`, whose frame would be ambiguous.
   No frame is assumed.
2. **Rows without a position.**
   A row whose x, y or z is not finite has no layout (no theta and no radius) and takes no part in the fit.
   When no row has a finite position, there is no layout and no center.
3. **Center.**
   With `n` finite positions `p`:
   the centroid `c0` is their sum, in row order, divided by `n`;
   `q = p - c0`;
   and the scale `s` is the largest Euclidean length of a `q`.
   If `n < 4` or `s = 0`, the center is the centroid.
   Otherwise, with `u = q / s`, fit the sphere `x*x + y*y + z*z = 2*a*x + 2*b*y + 2*c*z + d` to the `u` by least squares: each `u` gives the row `(2*ux, 2*uy, 2*uz, 1)` of a matrix `A` and the value `ux*ux + uy*uy + uz*uz` of a vector `b`, and `(a, b, c, d)` solves the 4-by-4 normal equations `(A^T A) w = A^T b` by lower-upper (LU) decomposition with partial pivoting, as `nemar.sensor-field.v1` solves its matrix.
   The fit is degenerate, and the center is the centroid, when a pivot's magnitude is at most `1e-10` times the largest magnitude of an entry of `A^T A`: the points are coplanar, such as a single ring of sensors.
   (The fitted squared radius, `a*a + b*b + c*c + d`, needs no check: for centered points it is their mean squared distance from the center.)
   Otherwise the center is `c0 + s * (a, b, c)`.
4. **Topoplot coordinates.**
   For each finite position, `(X, Y, Z)` is the position minus the center, and, with `k` 180/π computed in binary64 (57.29577951308232):
   `theta = -(atan2(Y, X) * k)`, written 180 where this gives -180, so theta lies in (-180, 180];
   `radius = 0.5 - (atan2(Z, hypot(X, Y)) * k) / 180`.
   `atan2` keeps the sign of zero, as IEEE 754 and every common math library do: a point straight behind the center has theta 180 whether its Y is +0 or -0.

The output is one layout row per input row, in input order: the name, theta in degrees and the radius, or no layout for a row without a position.

## Refusals

| Word | When |
|---|---|
| `frame_unknown` | The coordinate system is not in the [frame table](#frames), and the positions are not template positions (`n/a` with a montage). |

When the layout is refused, a renderer places the sensors by their names with `nemar.sensor-labels.v1`, a separate algorithm specified beside this one, and says that the positions' frame was not known.

## Frames

The table is BIDS's own, from the coordinate-systems appendix of the BIDS specification at commit `147b46d7`: every name whose orientation BIDS states.

| Orientation | Coordinate systems |
|---|---|
| ALS | `CTF`, `4DBti`, `KitYokogawa`, `EEGLAB`, `EEGLAB-HJ` |
| RAS | `NeuromagElektaMEGIN`, `ElektaNeuromag` (deprecated), `ChietiItab`, `CapTrak`, `ACPC`, `ScanRAS`, and the standard template identifiers: `ICBM452AirSpace`, `ICBM452Warp5Space`, `IXI549Space`, `fsaverage`, `fsaverageSym`, `fsLR`, `MNIColin27`, `MNI152Lin`, `MNI152NLin2009aSym`, `MNI152NLin2009bSym`, `MNI152NLin2009cSym`, `MNI152NLin2009aAsym`, `MNI152NLin2009bAsym`, `MNI152NLin2009cAsym`, `MNI152NLin6Sym`, `MNI152NLin6ASym`, `MNI305`, `NIHPD`, `OASIS30AntsOASISAnts`, `OASIS30Atropos`, `Talairach`, `UNCInfant`, and the deprecated `fsaverage3`, `fsaverage4`, `fsaverage5`, `fsaverage6`, `fsaveragesym` and `UNCInfant0V21` to `UNCInfant2V23` |

Names are compared exactly, case included.
Template positions, `n/a` with a montage, are RAS.
`Pixels` (positions on an image), `Other`, and the image-space names `individual`, `study` and `scanner`, whose orientation BIDS leaves to other files, are not in the table.

## Parity

An implementation matches a vector case when:

- it refuses the cases the vector refuses, with the same word, and gives a layout for the others, with no layout for the same rows;
- its center is within `1e-9 * s` of the vector's (with `s` the scale of step 3), and its center method (`sphere` or `centroid`) is the vector's;
- each radius is within `1e-12` of the vector's;
- each sensor's planar point `(cos(theta) * radius, sin(theta) * radius)` is within `1e-12` of the vector's.

Theta is compared through the planar point because it is undefined at the pole: a sensor straight above the center has radius 0 and any theta.
Each `cart2topo` entry gives a centered ALS point and the theta and radius it converts to, with no fit; an implementation's theta is within `1e-9` degrees of it, with no wrapping, so a point straight behind the center must give 180, and its radius is within `1e-12`.

## eegprep at the reference commit

- **The center is this page's.**
  eegprep centers positions with `chancenter`, which searches for the sphere with `fminsearch`; a search cannot be reproduced to parity in another language, so this page fits the sphere algebraically and the vectors convert positions centered by that fit.
  The generator fits the sphere a second way, by singular value decomposition, and the two centers agree far inside the tolerance.
- **Theta near ±180.**
  `convertlocs` wraps theta twice with `((v + 180) mod 360) - 180` and a `numpy.isclose` test, which writes a point straight behind the center as -180 when its Y is +0 and as 180 when its Y is -0, and can move the last digit of other angles.
  This page writes (-180, 180]; the vectors write eegprep's -180 as 180, and the tolerance absorbs the last digit.
- **Frames.**
  eegprep converts the positions it is given and has no frame table; the table is this page's, taken from BIDS.

## Vectors

[`views/vectors/sensor-layout.v1.json`](../../views/vectors/sensor-layout.v1.json) has the reference (eegprep's commit, the numpy and scipy versions, and the BIDS specification the frames come from), the tolerances above, `frames` (the ALS and RAS names, and the orientation of template positions), `cart2topo` (centered points straight to theta and radius, including the axes, the poles and points straight behind with Y = +0 and Y = -0), and the cases.
Each case gives `coordinate_system`, `montage` for template positions, `positions` (`name`, `x`, `y`, `z`, with `null` for a number that is not finite) and either `refused` (the word) or `expected`: `center` (in ALS), `center_method`, and `theta_deg` and `radius` per row (`null` for a row without a position).
An implementation gives the case `frame_als`'s layout for every ALS name and the case `frame_ras`'s for every RAS name.
The cases cover a 128-sensor cap in millimeters (RAS), a 339-position 10-5 template in meters (ALS), a 32-sensor cap moved off center, the frame cases, a coplanar ring and three positions (the centroid), rows without a position, template positions from a montage (and the same positions also naming a coordinate system, refused), and eleven coordinate systems that are refused.

`scripts/generate_view_vectors.py` writes this file with the sensor-field vectors; see [`sensor-field.md`](sensor-field.md#vectors).
