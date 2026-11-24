# `nemar.sensor-field.v1`

The scalp map of one value per sensor: EEGLAB's `topoplot` map, interpolated from a two-dimensional layout of the sensors onto a 67-by-67 grid and masked at the head.
This page is normative for the algorithm and for the kind `nemar.sensor-field` version 1 that draws with it.
[`views/vectors/sensor-field.v1.json`](../../views/vectors/sensor-field.v1.json) holds the cases every implementation reproduces, and `neuroschema.views.sensor_field.sensor_field` is the Python reference (install the `views` extra).
The vectors come from eegprep's `topoplot` at commit `edf694c8344b9c4c68672eac3acf9a819f1462a8`, the reference implementation.
Where eegprep and this page differ, this page decides; [eegprep at the reference commit](#eegprep-at-the-reference-commit) lists each difference.

## Input

One map is one value per sensor, with each sensor's place in the layout, in the layout's row order.
A place is EEGLAB's polar topoplot coordinate pair:

- `theta` in degrees, 0 at the nose and 90 at the right ear;
- `radius`, the arc length from the vertex, 0.5 at the head's equator, so a sensor below the equator has a radius above 0.5.

Every number is an Institute of Electrical and Electronics Engineers (IEEE) 754 binary64 value, and every step below computes in binary64.
Version 1 takes no override of the radii, the grid or the head.

## Algorithm

1. **Usable sensors.**
   A sensor is usable when its value, its theta and its radius are all finite.
   Any other sensor is dropped, value and place together.
2. **Planar positions.**
   For each usable sensor, `t = theta * c`, where `c` is π/180 computed in binary64 (0.017453292519943295), and then `x = cos(t) * radius` and `y = sin(t) * radius`.
   `x` points to the nose and `y` to the right ear; these are raw layout units.
3. **Radii.**
   With `R` the largest radius among the usable sensors, `plotrad = max(min(1, R * 1.02), 0.5)`, `intrad = min(1, R * 1.02)` and `squeezefac = 0.5 / plotrad`.
   `R` is taken before the merge of step 4, so a sensor merged into another still reaches the radii: EEGLAB's `topoplot.m` takes its radii from every channel with a value and a place, before it interpolates.
4. **Merge.**
   Walk the usable sensors in row order.
   A sensor whose distance `sqrt((x - xk) * (x - xk) + (y - yk) * (y - yk))` to a kept sensor `k` is at most ε = 0.001 merges into the first such kept sensor; otherwise it is kept.
   Distances are measured to kept sensors only, so merges do not chain.
   A kept sensor keeps its own place, and its value becomes the mean of its group, its `k` members' values `x` in row order, computed as step 8 computes a mean: `x[0] + ((x[0] - x[0]) + (x[1] - x[0]) + ... + (x[k-1] - x[0])) / k`, so equal members give their value exactly, and values near the binary64 limit do not overflow.
5. **Plotted and interpolated sensors.**
   The plotted sensors are the usable sensors whose radius is at most `plotrad`: a renderer draws a marker for each.
   The interpolated sensors are the kept sensors with `x <= intrad` and `y <= intrad`.
   There is no absolute value: a sensor far behind the head or far to its left is interpolated, as in EEGLAB.
   If fewer than 8 sensors are interpolated, the map is refused with `too_few_sensors`: a map needs 8, as many as `nemar.sensor-labels.v1` needs to place sensors by name, because a spline through fewer shows the spline more than the field.
6. **Squeeze.**
   An interpolated sensor's grid position is `(x * squeezefac, y * squeezefac)`.
7. **Grid.**
   `xmin = min(-0.5, the smallest squeezed x)` and `xmax = max(0.5, the largest squeezed x)`, and likewise `ymin` and `ymax` from the squeezed y.
   Each axis has 67 points: point `i` is `i * ((max - min) / 66) + min` for `i` from 0 to 65, and point 66 is `max` itself, computed in that order.
   `z[i][j]` is the value at `(x[i], y[j])`.
   On screen, y runs to the right and x runs up, so the nose is at the top.
   If no cell lies inside the head circle (step 10), the map is refused with `head_outside_grid`: a sensor far outside the head has stretched the grid past it.
8. **Interpolation.**
   For the interpolated sensors at grid positions `p` with values `v` (merged values for kept sensors that absorbed others), in row order, the mean is `m = v[0] + ((v[0] - v[0]) + (v[1] - v[0]) + ... + (v[n-1] - v[0])) / n`, the differences summed in that order.
   It is the mean, computed so that equal values give `m` equal to them exactly.
   Build the matrix `G[k][l] = d * d * (ln(d) - 1)` with `d` the distance between `p[k]` and `p[l]`, and `G[k][k] = 0`.
   There is no regularization term.
   Solve `G w = v - m` (each deviation `v[k] - m` one binary64 subtraction) by lower-upper (LU) decomposition with partial pivoting: at step `k`, the pivot is the entry of largest magnitude in column `k` at or below the diagonal, the first such row on a tie; rows are swapped, the rows below are eliminated, and `w` follows by back substitution.
   Every pivot is used as it is: an exactly zero pivot divides by zero, and values near the binary64 limit overflow, and either gives weights that are not finite, which step 10 catches.
   The deviations are interpolated, not the values: the biharmonic spline has no constant term, so a constant carried by every value ripples through it, and on a map whose values share a large offset (a spectrum's decibels) that ripple can fill the color axis with structure the sensors do not have.
   With the mean removed, the map of `v + C` is the map of `v` moved by `C`, and a flat field, every deviation exactly 0, is `m` in every cell.
   A near-flat field is not interpolated: when the usable sensors' values (step 1) differ, but their range `max - min` is at most `1e-9` of their magnitude, the largest absolute value among them, every cell is `m`, there are no contours, and the map carries the note `near_flat`; its spline would stretch differences in the last digits over the whole color axis, and no view may mislead.
9. **Evaluation.**
   `z[i][j]` is `m` plus the sum over interpolated sensors `k` of `g(d) * w[k]`, with `d` the distance from `(x[i], y[j])` to `p[k]`, `g(d) = d * d * (ln(d) - 1)` and `g(0) = 0`.
   The field is flat when every usable sensor (step 1) has the same value; its every cell is then that value, and the map carries the note `flat_field`, whose caption is "all sensors have the same value".
   A sensor that is usable but not interpolated (beyond the interpolation square) counts: when its value differs, the map may still be constant, but it carries no note, because not all sensors have the same value.
10. **Mask.**
    A cell is masked, with no value, when `sqrt(x[i] * x[i] + y[j] * y[j]) > 0.5`, computed in that order.
    A renderer leaves masked cells undrawn; the vectors write them `null`.
    If an unmasked cell is not finite, the map is refused with `interpolation_failed`: a weight that is not finite makes every cell so.
11. **Limits.**
    Over the unmasked cells, with their smallest value `min` and largest `max`:
    `absmax` gives `(-M, M)` with `M = max(|min|, |max|)`, and `minmax` gives `(min, max)`.
    The view's `parameters.limits` chooses one, and an absent choice is `absmax`.
    The color axis widens the limits outward by 5%, so that no cell takes the color at an end of the color map:
    for `absmax`, each limit `L` moves away from zero by 5% of its magnitude, `L + sign(L) * 0.05 * |L|`, which gives `(-1.05 * M, 1.05 * M)`, as EEGLAB's `caxis` does;
    for `minmax`, with `span = max - min`, the axis is `(min - 0.05 * span, max + 0.05 * span)`, each computed in that order, 5% of the range on each side.
    Every unmasked cell lies inside the color axis; a renderer gives a value beyond it the color at its end.
    The `minmax` axis differs from EEGLAB's ([below](#eegprep-at-the-reference-commit)): on a map of one sign, moving the limit nearer zero away from zero would move it inward and clip the cells beside it.
    A renderer colors each cell by its value's place on the color axis.
    When `min` equals `max`, the map is constant, a flat field among them: every unmasked cell takes one color, the color of its value on the axis, and there are no contours.
    Under `minmax`, and for a map of zeros, the axis is one point and that color is the middle of the color map; under `absmax`, a value `v0` other than zero sits on the axis `(-1.05 * |v0|, 1.05 * |v0|)`, so a flat field at `v0` takes the color that `v0` has on any map with those limits.
12. **Contours.**
    When `min` is below `max`, there are six levels: level `k` is `k * ((max - min) / 7) + min`, for `k` from 1 to 6.
    The contour lines themselves are the renderer's own (marching squares, for example) and are not part of parity.
13. **Head.**
    Over the map, a renderer draws EEGLAB's cartoon head for a head of radius 0.5, squeezed as the sensors are (EEGLAB's `topoplot.m`, lines 1289 and 1402 to 1410 of the `develop` branch at commit `6c238f7`):
    a circle about the origin of radius `0.5 * squeezefac`, and three polylines, the nose and the two ears, whose points are the model points below times `squeezefac` (EEGLAB's `sf = headrad / plotrad` with `headrad` 0.5), each product computed in binary64.
    The circle is the layout's equator, radius 0.5, so when `plotrad` is above 0.5 the sensors below the equator are drawn in the skirt between the head and the mask, as EEGLAB draws them.
    The model points, `(x, y)` with x to the nose and y to the right ear, are EEGLAB's numbers for a head of radius 0.5:

    | Polyline | Points |
    |---|---|
    | nose | (0.4954, 0.09), (0.57, 0.02), (0.575, 0), (0.57, -0.02), (0.4954, -0.09) |
    | right ear | (0.0955, 0.492), (0.1175, 0.51), (0.1183, 0.518), (0.1146, 0.5299), (0.0955, 0.5419), (-0.0055, 0.54), (-0.0932, 0.547), (-0.1313, 0.532), (-0.1384, 0.51), (-0.1199, 0.484) |
    | left ear | the right ear's points with y negated, in the same order |

    The line widths and colors are the renderer's own.

## Refusals

A map that is not drawn shows, in its place, a sentence for its word.
These are every word that can take a map's place, each with what it means for the person looking at the page; the website writes its sentences from this table.

| Word | From | Meaning |
|---|---|---|
| `too_few_sensors` | this algorithm, step 5 | Fewer than 8 sensors have a value and a place inside the interpolation square (after merging sensors at one place), and a map needs 8. |
| `head_outside_grid` | this algorithm, step 7 | A sensor lies so far outside the head that the map's grid has no point inside it. |
| `interpolation_failed` | this algorithm, step 10 | The values could not be interpolated into finite numbers (a value near the largest a double can hold, or sensors that make the system singular). |
| `frame_not_scalp` | the kind's placement | The sensors' positions are in a coordinate system of intracranial recordings (`Pixels`, `ACPC` or `ScanRAS`), so they are not positions on the scalp, and no scalp map is drawn from them, by place or by name. |
| `no_eeg_sensors` | the kind's placement | No sensor says it is EEG: measured positions whose rows are none of them typed EEG (untyped, or an intracranial recording's SEEG, ECOG or DBS contacts), or other sensors typed and none EEG; a scalp map draws EEG sensors only. |
| `template_name_unknown` | the kind's placement | The sensors' template positions name a montage, and a row's name is none of its electrodes (compared as `nemar.sensor-labels.v1` compares names), so the positions are not that montage's. |

When the sensors are placed by name, `nemar.sensor-labels.v1` has its own words for names it cannot place, with their meanings, in [`sensor-labels.md`](sensor-labels.md); that word takes every map's place.

Three more words say why a view's positions were not used.
When every row the map draws is typed EEG, the sensors are placed by name instead, and the word explains that; otherwise the word takes every map's place, because names alone cannot say that the sensors are on the scalp.

| Word | From | Meaning |
|---|---|---|
| `frame_unknown` | `nemar.sensor-layout.v1` | The view's positions name a frame whose orientation is not known, or name it inconsistently, so they cannot be projected; sensors typed EEG are placed by name instead, and the map says so. |
| `positions_flat` | `nemar.sensor-layout.v1` | The view's measured positions are too flat, or too few, to locate the head's center (singular ratio below 0.05, or a sphere more than 3 times their scale), so they cannot be projected; sensors typed EEG are placed by name instead, and the map says so. |
| `positions_partial` | `nemar.sensor-layout.v1` | The view's measured positions cover too little of the head, or fix it too unstably, to locate its center (a frontal, central or occipital set, or a ring with no top: the dilution of their center is above 4.5; or leaving one position out moves the center by more than 0.12 of the radius), so they cannot be projected; sensors typed EEG are placed by name instead, and the map says so. |

A note is shown with a drawn map, in its caption, and says what the map alone cannot.

| Note | From | Caption | Meaning |
|---|---|---|---|
| `flat_field` | this algorithm, step 9 | all sensors have the same value | Every sensor with a value and a place has exactly one value, so the map is that value's one color, with no contours. |
| `near_flat` | this algorithm, step 8 | all sensors are within <range> of each other | The sensors' values differ by at most `1e-9` of their magnitude, so the map is one color at their mean, with no contours; `<range>` is the usable values' `max - min` (the vectors' `value_range`), printed as ECMAScript's `String(x)` prints it, with the values' unit. |

A fault in the files themselves (a broken TSV grammar, a missing column, a cell that is not a number, a sensor role with the wrong number of rows or other names than the sensors it places, a cap) takes no map's place: the whole view shows as tables, with the word, as for every generic kind ([The model](#the-model)).
The spectrum's maps are the exception: the lines have already drawn the view, so a fault that only the maps read (in the layout's place columns, or `sensors_mismatch`) shows its generic word in every map's place while the lines stay drawn ([presets.md](presets.md#nemarspectrum-version-1)).

## The kind `nemar.sensor-field` version 1

A view of this kind draws one map, or a row of maps, from stored data.
Its sensors are placed by one of three sources: a two-dimensional `layout`, three-dimensional `positions` that the transform `nemar.sensor-layout.v1` projects, or, with neither, the sensors' names.
`schema/views/kind.nemar.sensor-field.v1.schema.json` checks the declaration; this section says what a renderer reads and the model it builds.

### Roles

Every role is a tab-separated values (TSV) file, read under the grammar of [`docs/views.md`](../views.md#tsv).
A view has at most one of `layout` and `positions`.

| Role | Required | File and columns | Dimensions |
|---|---|---|---|
| `values` | yes | TSV; the map values, and the sensor names when there is no layout | `sensor`, and at most one more of any name along the other axis |
| `layout` | no | TSV; columns `name` (string), `theta_deg` (number, unit `deg`), `radius` (number), and `sensor_type` (string), required when `position_source` is `measured` | `sensor` along the rows, coordinates `{"column": "name"}` |
| `positions` | no | TSV; columns `name` (string), `x`, `y` and `z` (numbers in one unit), and `sensor_type` (string), required when `position_source` is `measured` | `sensor` along the rows, coordinates `{"column": "name"}` |

The layout and the positions each carry `coordinate_system` (the Brain Imaging Data Structure (BIDS) name of the frame the positions were in, or `n/a`) and `position_source` (`measured` or `template`).
Template positions have the coordinate system `n/a` and name their `montage` (`nemar.sensor-labels.v1`); a montage beside any other coordinate system is inconsistent, and the schema refuses it.
A layout or positions role of `measured` positions declares `sensor_type`, and the schema refuses one that does not: a scalp map draws a measured position only when its row is typed EEG.
Template positions, taken from a montage, may be untyped; every row of a template role names an electrode of its `montage` (`template_name_unknown` otherwise), when `views/montages` holds that montage.
The role that names the sensors, the positions or, with no sensor role, the values, may carry `cap_model` and `reference`: the recording's `CapManufacturersModelName` and `EEGReference`, as its `eeg.json` gives them after BIDS inheritance.
A placement by name passes them to `nemar.sensor-labels.v1`, which needs the cap model to place names on an EGI net and reports the channel the reference names; a layout is never placed by name and carries neither (the schema refuses them).
A place cell (`theta_deg` and `radius` of a layout, `x`, `y` and `z` of positions) is a number, or exactly `n/a`, as BIDS writes a position it does not have: that sensor has no place, and every map drops it (step 1).
Any other cell that is not a number refuses the files (`cell_not_number`), and so does `n/a` in the values: a map's value is always a number.
`parameters` may give `limits`: `absmax` (the default, for a diverging color map) or `minmax` (for a sequential one).
A view with `positions` declares the transform `nemar.sensor-layout.v1` with no parameters (the positions role names its frame, once); a view without `positions` has no transform.
A view of this kind has no `inputs`.

### Sensors

The source decides the values' `sensor` coordinates and how a renderer places each sensor:

1. **A layout.**
   The coordinates are `{"role": "layout", "column": "name"}`: the values' sensors are the layout's rows, by position, at the layout's theta and radius.
2. **Positions.**
   The coordinates are `{"role": "positions", "column": "name"}`: the values' sensors are the positions' rows, by position.
   The renderer projects the drawn rows' positions (below) with `nemar.sensor-layout.v1` in the frame the role names (`coordinate_system`, or `n/a` with a `montage`), giving it their `name` and `sensor_type` cells for the scalp rows, and draws the projected layout; a drawn row with no layout (not a scalp row, such as a fiducial, or without a position) has no place and is dropped (step 1).
   The projection is given the drawn rows only, in row order, and fits every scalp row with a position that it is given, so with typed rows the sphere is fitted to the EEG rows alone.
   If the projection is refused (`frame_unknown`, `positions_flat` or `positions_partial`), the renderer places the drawn rows by their names, as in 3, only when every one of them is typed EEG, and says why the positions could not be used; if that placement is refused too, its word takes every map's place.
   When a drawn row is untyped (template positions may be), the projection's word takes every map's place instead: names alone never place sensors whose rows do not say they are EEG, so an intracranial strip named F1 to C6 in the frame `Other` is never laid on a scalp.
3. **Names.**
   The coordinates are names in the values file, `{"column": "<name column>"}` along the rows or `{"header": true}` along the columns, and a renderer places the names with `nemar.sensor-labels.v1` (a separate algorithm, specified beside this one), each with its row's type when the names came from a positions role and no type otherwise, and with the `cap_model` and `reference` of the role that names them (above), each absent when the role does not carry it.
   The placed names are template positions of the montage the algorithm chose, projected as such (`n/a` with that `montage`); a name it does not place has no place and is not drawn.
   When the algorithm refuses the names, its word takes every map's place.
   When it reports a reference channel and every value of that row, in every map, is exactly zero (`0` or `-0`), the row is not drawn: a channel recorded against itself holds no data, and drawing its zeros would pull each map toward zero around it.
   When any of its values is not zero, the data were re-referenced and the row is drawn like any other.
   Only a placement by name reports a reference channel, so a layout or projected positions draw every row they place.

Which rows a map draws:

- **Sensor types.**
  A row's type is its `sensor_type` cell, read as `nemar.sensor-labels.v1` reads a channel's type: trimmed of TAB, LF, VT, FF, CR and space at both ends, its letters A to Z folded to a to z; then `eeg` is EEG, an empty cell or `n/a` is untyped, and anything else is another type.
  Measured positions (a layout or positions role with `position_source` `measured`): a map draws only the rows typed EEG, never an untyped row.
  Template positions and names in the values file: when any row is typed, a map draws only the rows typed EEG; when no row is typed, or there is no `sensor_type` column, every row is drawn.
  When no row is drawn by these rules, `no_eeg_sensors` takes every map's place.
  So a map holds one sensor type, never draws a row typed `SEEG`, `ECOG` or `DBS`, and never draws a measured position whose row does not say it is EEG.
  What this guarantees is bounded by what a declaration says: a row typed EEG is believed; names in a values file carry no type; and template positions are checked by their names only, each an electrode of the montage they name, never by comparing their positions with the montage's. So a writer that types intracranial contacts EEG, names them in a values file with no positions, or declares them template positions under a montage's electrode names, is believed; the writer types each row as the recording's `channels.tsv` does.
- **Frames.**
  A layout or positions role whose `coordinate_system` is `Pixels`, `ACPC` or `ScanRAS`, BIDS's coordinate systems for intracranial electrodes only, draws no scalp map: `frame_not_scalp` takes every map's place, and the sensors are not placed by name either, because an implant's contacts are often named like scalp electrodes (a strip named C1 to C6).
  BIDS admits every one of its standard template spaces for EEG as well as for intracranial positions, so no template space is refused here; a template space in the frame table of `nemar.sensor-layout.v1` is projected as it says.

### Maps

- **Sensors along the rows.**
  Each declared column of type `number` or `integer` is one map, in declared order, and row `k` holds sensor `k`; an `integer` column's cells are read under the integer grammar, and the map is drawn like any other.
  A second dimension along the columns labels the maps: with `{"header": true}`, by the column names; with `{"role": "<role>", "column": "<column>"}`, by that column's cells in row order.
  Without one, a map's label is its column name.
- **Sensors along the columns.**
  Each data row is one map, and the declared columns of type `number` or `integer` are the sensors, in declared order (with `{"header": true}`, their names are the sensor names).
  A second dimension along the rows labels the maps by a column of this file (`{"column": "<column>"}`, which is not a sensor) or by a column of another role (`{"role": "<role>", "column": "<column>"}`, by position).
  Without one, a map's label is its row number, counted from 1.

A `{"column"}` coordinate on a dimension along the columns, or `{"header": true}` on one along the rows, names nothing (`coords_unresolved`).
A renderer reads each map's values in sensor order and pairs sensor `k` with layout row `k`, with the projection of positions row `k`, or with the place `nemar.sensor-labels.v1` gives the `k`-th name.

### The model

A renderer builds a view's model before it draws, in the four steps of [generic-kinds.md](generic-kinds.md#building-a-model), for a view of this kind and for a preset drawn by it (`nemar.ic-maps`): an invalid declaration or a file that is not the one recorded draws nothing, and a fault in the files shows the view as tables, with the word.
The model holds the stored numbers and the decisions; the maps themselves are this page's algorithm, run on them.

```json
{
  "type": "sensor-field",
  "limits": "absmax",
  "unit": "uV",
  "placement": {
    "source": "layout", "role": "layout", "coordinate_system": "CapTrak",
    "position_source": "measured", "montage": null, "unused_positions": null,
    "reference": null, "word": null
  },
  "sensors": {
    "dim": "sensor", "type": "string", "unit": null, "axis": "rows",
    "labels": ["Fp1", "Fp2"], "types": null, "drawn": [true, true], "electrodes": null,
    "theta_deg": [-18, 18], "radius": [0.511, 0.511], "x": null, "y": null, "z": null
  },
  "maps": {
    "dim": "component", "type": "string", "unit": null,
    "items": [{"label": "IC001", "values": [-2, -0.25], "text": ["-2.0", "-0.25"], "word": null, "notes": []}]
  }
}
```

- `limits` is the view's `parameters.limits`, `absmax` when absent; a preset drawn by this kind uses `absmax`, the base's default.
  `unit` is the value columns' unit, or `null`.
- `placement` says where the sensors' places came from.
  `source` is `layout`, `positions` or `names`, and `role` the sensor role (`layout`, `positions`, or `null` when the values name the sensors).
  `coordinate_system`, `position_source` and `montage` are the role's; for sensors placed by name, they are `n/a`, `template` and the montage `nemar.sensor-labels.v1` chose (`null` when it refused).
  `unused_positions` is `frame_unknown`, `positions_flat` or `positions_partial` whenever the view's positions could not be projected, whether the sensors were then placed by name or the word took every map's place, and `null` otherwise.
  `reference` is the name of the reference channel `nemar.sensor-labels.v1` reported for sensors placed by name, as stored, and `null` otherwise; whether a map draws it is its `drawn` entry ([Sensors](#sensors), 3).
  `word` is the placement's refusal (`frame_not_scalp`, `no_eeg_sensors`, `template_name_unknown`, `frame_unknown`, `positions_flat` or `positions_partial` for positions not all typed EEG, or a word of `nemar.sensor-labels.v1`), or `null`.
- `sensors` has one entry per sensor, in sensor order: `labels`, the stored names; `types`, the stored `sensor_type` cells, or `null` without the column; and `drawn`, whether a map draws that row, by the rules above: `false` for every row when the placement refused, and for a row with no place (an `n/a` cell, a position the projection gives no layout, a name not placed) or a reference channel whose values are all exactly zero.
  The places are the stored numbers a map is drawn from, each `null` for a cell `n/a`: for a layout, `theta_deg` and `radius`; for positions, `x`, `y` and `z` in the role's frame; for sensors placed by name, `electrodes` (the montage's label for each placed name, `null` for the others) and `x`, `y` and `z`, the montage's positions in meters.
  The other places are `null`.
- `maps` has the maps' dimension (`dim`, `type` and `unit` of the second dimension, or all `null` without one) and one item per map, in order: its `label`, its `values` and their stored `text`, one per sensor, its `word`, the word that takes its place, or `null` when it is drawn, and its `notes`, those of a drawn map (`flat_field`), empty otherwise.
  When the placement refused, every map's `word` is the placement's; otherwise it is the word this page's algorithm refuses that map with.

To draw map `m`, a renderer runs the algorithm on the drawn rows, in row order: a layout's theta and radius, or the projection by `nemar.sensor-layout.v1` of their `x`, `y` and `z` (in `placement.coordinate_system`, with `placement.montage` for template positions), and map `m`'s values at those rows.
Every number in the model is a stored value read from a file: a value, a layout's place or a position, or a montage's position from `views/montages`.
So the model vectors compare the model exactly, as for every generic kind, and a drawn map is compared within this page's [parity](#parity) by its own vectors.

### The order of checks

When the files break more than one rule, the first rule broken gives the word.

1. The values file: present, size, SHA-256 (nothing is drawn), then the cap on bytes.
2. The TSV grammar, in the order of its list ([generic-kinds.md](generic-kinds.md#tsv)).
3. The declared columns: `column_repeated`, then each name in declared order (`column_missing`).
4. The values' coordinates, each dimension in turn, the sensor dimension first: `{"header": true}` along the rows or `{"column"}` along the columns names nothing (`coords_unresolved`), and a `{"column"}` coordinate's column is declared (`coords_unresolved`) with its dimension's type and unit (`coords_mismatch`); it is the values' coordinate column.
5. The value columns, each in declared order (`value_type`: `number` or `integer`), their units (`value_units_differ`), `empty`, then the caps on rows, value columns and cells.
6. The cells, column by column: the coordinate column first, then the value columns in declared order, each from top to bottom.
7. Coordinates from another role, the rows' dimension before the columns'.
   For the sensor role (`layout` or `positions`): it is there once, as a TSV file that declares the coordinate column (`coords_unresolved`); its file and the cap on bytes; its TSV grammar; its declared columns (`column_repeated`, then each `column_missing` in declared order); the coordinate column's type and unit (`coords_mismatch`); one row per sensor (`coords_length`); the cap on its cells, counting every declared column; its cells, column by column in declared order, a place column's cells numbers or `n/a`; and, when the sensors run along the values' columns, its name cells, top to bottom, are the value columns' names in declared order, compared as exact text (`sensors_mismatch`), so no value is drawn at another sensor's place.
   For any other role labeling the maps, the generic rule ([generic-kinds.md](generic-kinds.md#coordinates)).
8. The placement, which draws the view but puts its word in every map's place: `frame_not_scalp`, then `no_eeg_sensors`, then `template_name_unknown`, then, for positions, the projection (a refusal is kept in `unused_positions`, and places the sensors by name when every drawn row is typed EEG, or is every map's word otherwise), then, for names, `nemar.sensor-labels.v1`.
9. Each map, by this page's algorithm: `too_few_sensors` (step 5), `head_outside_grid` (step 7), `interpolation_failed` (step 10).

The words of steps 1 to 7 are the generic kinds' ([generic-kinds.md](generic-kinds.md#words)), with their outcomes.
The [model vectors](generic-kinds.md#the-model-vectors) hold a case for each of them in a scalp map and, for each pair of neighboring checks that a scalp map adds, a case with both faults.

### What the renderer shows

Every number on screen comes from a stored row.
A map's readout is the hovered sensor's stored value, never a grid cell, and a marker sits at each plotted sensor's squeezed place.
A sensor that was merged keeps its own marker and readout; only the interpolation uses the merged value.
The head (step 13) is drawn over every map.

**Where the positions came from.**
Beside the maps, the renderer states where the sensors' places came from, from the model's `placement`; the caption alone never says it.

- A map drawn from a stored layout or from positions states its `position_source`, `measured` or `template`, and the `montage` when the role names one.
  For measured positions it also states that they are the dataset's own and that NEMAR does not verify them.
- A map placed by name states that the positions are template positions matched by name, and the montage; when the view's positions were not used, it also states why, with the sentence for `unused_positions`.

### What the writer enforces

JSON Schema cannot compare one file with another, so the writer makes the values hold one entry per layout or positions row (or per name), gives the sensors unique names, and declares only columns in the file's header.
A renderer relies on none of it: it checks the declared columns (`column_missing`) and the number of rows (`coords_length`) as it builds the model, and shows the view as tables, with the word, when either fails.
It pairs sensors by position, never by name, so two sensors of one name are two sensors, each with its own readout.

## Parity

An implementation matches a vector case when:

- it refuses the cases the vector refuses, with the same word, and draws the others;
- its mask is the vector's, cell for cell;
- each unmasked cell is within `1e-6 * (max_ref - min_ref) + 1e-12 * mag_ref` of the vector's, where `max_ref` and `min_ref` are the vector's largest and smallest unmasked cells and `mag_ref` the largest magnitude among them (the second term absorbs the last bits of a map drawn at its mean; a map of zeros is compared exactly);
- `plotrad`, `intrad`, `squeezefac` and each grid point are within a relative `1e-12` of the vector's;
- the limits, the color axis and the contour levels, which follow from the cells, are within the cells' bound;
- its plotted, interpolated and merged sensors and its notes are the vector's exactly, and its `value_range` within a relative `1e-12`;
- the head's radius and each point of its nose and ears are within a relative `1e-12` of the vector's.

Every decision in a vector case (a merge distance against ε, a sensor against the square or `plotrad`, a cell against the head circle) is at least `1e-9` from its threshold, or an exact tie computed with no sine or cosine in doubt, so a sine or cosine that differs in its last bit cannot flip one.
The `boundary_ties` case holds the three ties: a sensor at radius exactly `plotrad` and `x` exactly `intrad` (plotted and interpolated, because both tests are `<=`), and two sensors exactly ε apart (merged).

## eegprep at the reference commit

The reference is eegprep's `topoplot` and `griddata_v4` in `src/eegprep/functions/sigprocfunc/topoplot.py`, at `edf694c8`.
It follows EEGLAB's `topoplot.m`, and it leaves these points implicit or differs from EEGLAB.
The two divergences, the unreachable pseudo-inverse fallback and the shifted values, are reported upstream as [sccn/eegprep#670](https://github.com/sccn/eegprep/issues/670); this page does not depend on how that issue is resolved, because its own rules (the merge and the drop) decide both cases.

- **The regularization term is zero.**
  `griddata_v4` adds `1e-8 * trace(g) / n` to the diagonal as "Tikhonov regularization", but it sets the diagonal of `g` to 0 just before, so the trace is 0 and the term is identically 0.
  This page has no regularization.
- **Duplicate positions give an empty map.**
  Where two sensors share a position, the distance is 0 and `g = 0 * (ln 0 - 1) = 0 * -∞`, which is NaN (not a number); only the diagonal is set to 0.
  `numpy.linalg.solve` returns NaN without raising, so the `pinv` (pseudo-inverse) fallback in its `except LinAlgError` branch never runs, and every cell of eegprep's map is NaN.
  The fallback the code intends, the pseudo-inverse of the matrix with `g(0) = 0`, is the least-squares solution, and for exact duplicates it equals merging them at their mean value and solving the smaller system.
  The merge (step 4) is this page's answer for exact duplicates and for sensors closer than ε, whose matrix is nearly singular.
  The vectors' `exact_duplicates` case records that eegprep's own map of the unmerged sensors has no finite cell, and the test suite checks the pseudo-inverse map against the merged one (sccn/eegprep#670).
- **A value that is not finite shifts the others.**
  eegprep drops such a sensor from the positions but not from the values (EEGLAB's `Values = Values(plotchans)` has no counterpart), so every later value lands on the wrong sensor.
  This page drops both, as EEGLAB does; the vectors' `nan_values` case is eegprep's map with those sensors removed, and records that eegprep's map of the raw inputs disagrees with it (sccn/eegprep#670).
- **The interpolation square has no absolute value.**
  eegprep tests `(x <= intrad) & (y <= intrad)`, and EEGLAB's `topoplot.m` has the same test, `intchans = find(x <= intrad & y <= intrad)` (checked against EEGLAB's development copy of 17 September 2025).
  A sensor far behind the head (large negative x) or far to its left (large negative y) is interpolated and widens the grid; one far in front or far to the right is not.
  This page keeps the rule for parity with the maps users compare against.
- **The color axis margin.**
  EEGLAB moves both color limits 5% of their own magnitude away from zero after every limit choice (`topoplot.m`, lines 1248 to 1250 of the `develop` branch at commit `6c238f7`, the file's last change); eegprep does so for `absmax` and explicit limits but not for `maxmin`, where it leaves the limits to matplotlib.
  This page follows EEGLAB for `absmax`, whose limits have opposite signs and so both move outward.
  For `minmax` it widens both limits by 5% of the range instead, and so differs from EEGLAB and from eegprep: on a map of one sign, such as a spectrum's map in decibels, EEGLAB's rule moves the limit nearer zero inward (a smallest cell of 20 dB gives a lower limit of 21 dB), so the cells between take the color at the axis's end and the map's floor is clipped.
  The vectors' `one_sign_positive_db` and `one_sign_negative_db` cases are maps of one sign whose every cell lies inside the axis; under EEGLAB's rule some would not.
- **The radii and the merge.**
  EEGLAB's `topoplot.m` takes its radii from every channel with a value and a place, before it interpolates; eegprep does the same and has no merge.
  The vectors' maps are eegprep's map of the merged sensors, so where a merged-away sensor is the outermost (the `merged_outermost` case), the generator passes eegprep the plotting radius from every usable sensor through eegprep's own `plotrad` option; everywhere else it checks that eegprep's radius is the spec's.
- **The mean is removed before the interpolation.**
  EEGLAB's `topoplot.m` and eegprep interpolate the values themselves, so a constant every value carries ripples through the spline (about 4% of the value on the `constant_values` case's cap, and most of a spectrum's color axis when its decibels share an offset); a flat field is drawn as that ripple, with its colors and contours.
  This page interpolates the deviations from the mean and adds the mean back (step 8), for `absmax` and `minmax` alike, because a map that shows only what the sensors hold outranks parity with that ripple.
  The vectors' maps are eegprep's map of the deviations, plus the mean: the generator gives eegprep `v - m` and adds `m` to its cells.
- **The head.**
  eegprep draws the head circle at `squeezefac * rmax` and EEGLAB's ears scaled by `squeezefac`, as this page does, but its nose is a triangle of its own (0.08 wide and 0.06 tall at the scale of a head of radius 0.5); this page draws EEGLAB's nose.
  EEGLAB itself draws the circle at `hin = squeezefac * headrad * (1 - 0.007 / 2)` (line 1289), 0.35% inside the equator, leaving room for a head ring 0.007 wide; this page draws it on the equator, as eegprep does, a difference under the width of the line.
  The vectors' `head` is written from EEGLAB's own expressions (such as `0.497 - 0.005`), not from eegprep, and the reference's decimal points above match them within the tolerance.
- **Too few sensors, and maps with nothing to draw.**
  eegprep draws any number of sensors; this page refuses fewer than 8.
  Where a sensor stretches the grid past the head, or the interpolation overflows, eegprep returns a map with no finite cell; this page refuses it with a word.

## Vectors

[`views/vectors/sensor-field.v1.json`](../../views/vectors/sensor-field.v1.json) has the reference it came from (eegprep's commit, and the numpy and scipy versions), the tolerances above, and the cases.
Each case gives `sensors` (`name`, `theta_deg`, `radius`, `value`, with `null` for a number that is not finite) and either `refused` (the word) or `expected`: `plotrad`, `intrad`, `squeezefac`, `plotted`, `interpolated` and `merged` (sensor rows counted from 0; each merge group lists its kept sensor first), the grid axes `x` and `y`, the cells `z` (`z[i][j]` at `(x[i], y[j])`, `null` where masked), `limits` and `color_axis` for both choices, `contours`, `head` (`radius`, and `nose`, `right_ear` and `left_ear` as lists of `[x, y]` points), `notes` (`["flat_field"]` for a flat field, `["near_flat"]` for a near-flat one, else empty), and `value_range`, the usable values' `max - min`.
The expected map is eegprep's `topoplot` of the usable, merged sensors' deviations from their mean, plus the mean, and a near-flat map is its mean in every cell; the `minmax` color axis is this page's rule, since eegprep sets none.
A case whose `sensors` give `x`, `y` and `z` instead of `theta_deg` and `radius` is placed by positions, in the frame its `coordinate_system` names (or `n/a` with its `montage`): its `expected.layout` is the projection by `nemar.sensor-layout.v1` (`center`, `center_method`, `theta_deg`, `radius`, compared as [`sensor-layout.md`](sensor-layout.md#parity) says), and the map is drawn from that layout.
The cases cover 32, 64, 128 and 256 sensors on eegprep's packaged caps (laid out by `nemar.sensor-layout.v1`), exact duplicates, sensors 4e-4 and 9e-4 from another (merged), two sensors 1.5e-3 apart (not merged), sensors all on the midline, sensors outside the head and outside the interpolation square, values and places that are not finite, equal values and all zeros (flat fields, drawn at their value with the note), the edges of a flat field (a value or a place that is not finite, a sensor beyond the square with another value, a merge group of three, a duplicate pair at 1.5e308, a -0 among zeros), near-flat fields (one unit in the last place and 1e-9 dB, drawn at their mean, and 4e-8 dB, just above the bound, drawn as any map), -110 dB plus 0.05 dB of a pattern, exactly 8 sensors, 7 sensors and a merge down to 7 (refused), a dynamic range of 10^6, a sensor so far out that no cell is inside the head and values that overflow (refused), a field whose most negative value outweighs its most positive, exact ties at every `<=` (`boundary_ties`), a merged sensor that is the outermost (`merged_outermost`), maps of one sign whose every cell lies inside both color axes (`one_sign_positive_db`, `one_sign_negative_db`), and positions: 64 measured positions (one without a finite x), the whole GSN-HydroCel-32 montage and the standard_1005 midline as template positions, projected to maps; positions in an unknown frame and a montage beside a named frame (refused, `frame_unknown`); and a flat disk, three positions and a ring of measured positions (refused, `positions_flat`).

Each case's inputs (names, theta, radius and value, or positions and value) are frozen in `scripts/view_vector_inputs.json`: they were computed once from eegprep's packaged caps, and the generator reads them, so a platform's sine or a library's rounding can never move an input; only the expected outputs are computed.
`scripts/generate_view_vectors.py` writes the vectors from eegprep, with the `vectors` dependency group (Python 3.12 or later): `uv run --group vectors python scripts/generate_view_vectors.py`.
With `--check` it writes nothing and fails when a regenerated value differs from the committed one by more than `1e-9` of the map's range plus `1e-12` of its magnitude (for the cells, the limits, the color axis and the contours), `1e-12` absolutely for a layout's radius and planar point, `1e-12` of the positions' extent for a center, and `1e-12` relative for other numbers; this absorbs linear algebra libraries that round differently (the ubuntu-latest job and macOS differ by about `1e-12` of a map's range) and catches any change to eegprep or to the rules around it.
`--refresh-inputs` recomputes the frozen inputs and rewrites `view_vector_inputs.json`, whose diff is then reviewed like any other.
