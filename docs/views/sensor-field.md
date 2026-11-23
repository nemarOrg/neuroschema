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
3. **Merge.**
   Walk the usable sensors in row order.
   A sensor whose distance `sqrt((x - xk) * (x - xk) + (y - yk) * (y - yk))` to a kept sensor `k` is at most ε = 0.001 merges into the first such kept sensor; otherwise it is kept.
   Distances are measured to kept sensors only, so merges do not chain.
   A kept sensor keeps its own place, and its value becomes the mean of its group: the members' values summed in row order, then divided by their count.
4. **Radii.**
   With `R` the largest radius among the kept sensors, `plotrad = max(min(1, R * 1.02), 0.5)`, `intrad = min(1, R * 1.02)` and `squeezefac = 0.5 / plotrad`.
5. **Plotted and interpolated sensors.**
   The plotted sensors are the usable sensors whose radius is at most `plotrad`: a renderer draws a marker for each.
   The interpolated sensors are the kept sensors with `x <= intrad` and `y <= intrad`.
   There is no absolute value: a sensor far behind the head or far to its left is interpolated, as in EEGLAB.
   If fewer than 3 sensors are interpolated, the map is refused with `too_few_sensors`.
6. **Squeeze.**
   An interpolated sensor's grid position is `(x * squeezefac, y * squeezefac)`.
7. **Grid.**
   `xmin = min(-0.5, the smallest squeezed x)` and `xmax = max(0.5, the largest squeezed x)`, and likewise `ymin` and `ymax` from the squeezed y.
   Each axis has 67 points: point `i` is `i * ((max - min) / 66) + min` for `i` from 0 to 65, and point 66 is `max` itself, as `numpy.linspace` and MATLAB's `linspace` compute them.
   `z[i][j]` is the value at `(x[i], y[j])`.
   On screen, y runs to the right and x runs up, so the nose is at the top.
   If no cell lies inside the head circle (step 10), the map is refused with `head_outside_grid`: a sensor far outside the head has stretched the grid past it.
8. **Interpolation.**
   For the interpolated sensors at grid positions `p` with values `v` (merged values for kept sensors that absorbed others), build the matrix `G[k][l] = d * d * (ln(d) - 1)` with `d` the distance between `p[k]` and `p[l]`, and `G[k][k] = 0`.
   There is no regularization term.
   Solve `G w = v` by lower-upper (LU) decomposition with partial pivoting: at step `k`, the pivot is the entry of largest magnitude in column `k` at or below the diagonal, the first such row on a tie; rows are swapped, the rows below are eliminated, and `w` follows by back substitution.
   Every pivot is used as it is: an exactly zero pivot divides by zero, and values near the binary64 limit overflow, and either gives weights that are not finite, which step 10 catches.
9. **Evaluation.**
   `z[i][j]` is the sum over interpolated sensors `k` of `g(d) * w[k]`, with `d` the distance from `(x[i], y[j])` to `p[k]`, `g(d) = d * d * (ln(d) - 1)` and `g(0) = 0`.
10. **Mask.**
    A cell is masked, with no value, when `sqrt(x[i] * x[i] + y[j] * y[j]) > 0.5`, computed in that order.
    A renderer leaves masked cells undrawn; the vectors write them `null`.
    If an unmasked cell is not finite, the map is refused with `interpolation_failed`: a weight that is not finite makes every cell so.
11. **Limits.**
    Over the unmasked cells, with their smallest value `min` and largest `max`:
    `absmax` gives `(-M, M)` with `M = max(|min|, |max|)`, and `minmax` gives `(min, max)`.
    The view's `parameters.limits` chooses one, and an absent choice is `absmax`.
    The color axis moves each limit `L` away from zero by 5% of its magnitude, `L + sign(L) * 0.05 * |L|`, as EEGLAB's `caxis` does; a cell beyond the color axis takes the color at its end.
    When `min` equals `max`, the map is constant: every unmasked cell takes the middle color of the color map, and there are no contours.
12. **Contours.**
    When `min` is below `max`, there are six levels: level `k` is `k * ((max - min) / 7) + min`, for `k` from 1 to 6.
    The contour lines themselves are the renderer's own (marching squares, for example) and are not part of parity.

## Refusals

A refused map draws nothing; the renderer shows a sentence for its word in the map's place.
These are every word a sensor-field view can end in, each with what it means for the person looking at the page; the website writes its sentences from this table.

| Word | From | Meaning |
|---|---|---|
| `too_few_sensors` | this algorithm, step 5 | Fewer than 3 sensors have a value and a place (after merging sensors at one place), and a map needs 3. |
| `head_outside_grid` | this algorithm, step 7 | A sensor lies so far outside the head that the map's grid has no point inside it. |
| `interpolation_failed` | this algorithm, step 10 | The values could not be interpolated into finite numbers (a value near the largest a double can hold, or sensors that make the system singular). |
| `frame_unknown` | `nemar.sensor-layout.v1` | The view's positions name a frame whose orientation is not known, or name it inconsistently, so they cannot be projected; the renderer places the sensors by name instead and says so. |

When the sensors are placed by name, `nemar.sensor-labels.v1` has its own words for names it cannot place, with their meanings, in [`sensor-labels.md`](sensor-labels.md); the renderer shows that word's sentence and draws no map.

## The kind `nemar.sensor-field` version 1

A view of this kind draws one map, or a row of maps, from stored data.
Its sensors are placed by one of three sources: a two-dimensional `layout`, three-dimensional `positions` that the transform `nemar.sensor-layout.v1` projects, or, with neither, the sensors' names.
`schema/views/kind.nemar.sensor-field.v1.schema.json` checks the declaration; this section says what a renderer reads.

### Roles

Every role is a tab-separated values (TSV) file, read under the grammar of [`docs/views.md`](../views.md#tsv).
A view has at most one of `layout` and `positions`.

| Role | Required | File and columns | Dimensions |
|---|---|---|---|
| `values` | yes | TSV; the map values, and the sensor names when there is no layout | `sensor`, and at most one more of any name along the other axis |
| `layout` | no | TSV; columns `name` (string), `theta_deg` (number, unit `deg`), `radius` (number), and optionally `sensor_type` (string) | `sensor` along the rows, coordinates `{"column": "name"}` |
| `positions` | no | TSV; columns `name` (string), `x`, `y` and `z` (numbers in one unit), and optionally `sensor_type` (string) | `sensor` along the rows, coordinates `{"column": "name"}` |

The layout and the positions each carry `coordinate_system` (the Brain Imaging Data Structure (BIDS) name of the frame the positions were in, or `n/a`) and `position_source` (`measured` or `template`).
Template positions have the coordinate system `n/a` and name their `montage` (`nemar.sensor-labels.v1`); a montage beside any other coordinate system is inconsistent, and the schema refuses it.
`parameters` may give `limits`: `absmax` (the default, for a diverging color map) or `minmax` (for a sequential one).
A view with `positions` declares the transform `nemar.sensor-layout.v1` with no parameters (the positions role names its frame, once); a view without `positions` has no transform.
A view of this kind has no `inputs`.

### Sensors

The source decides the values' `sensor` coordinates and how a renderer places each sensor:

1. **A layout.**
   The coordinates are `{"role": "layout", "column": "name"}`: the values' sensors are the layout's rows, by position, at the layout's theta and radius.
2. **Positions.**
   The coordinates are `{"role": "positions", "column": "name"}`: the values' sensors are the positions' rows, by position.
   The renderer projects the positions with `nemar.sensor-layout.v1` in the frame the role names (`coordinate_system`, or `n/a` with a `montage`), and draws the projected layout; a row without a finite position has no place and is dropped (step 1).
   If the projection is refused (`frame_unknown`), the renderer places the sensors by name, as in 3, and says that the positions' frame was not known.
3. **Names.**
   The coordinates are names in the values file, `{"column": "<name column>"}` along the rows or `{"header": true}` along the columns, and a renderer places each name with `nemar.sensor-labels.v1` (a separate algorithm, specified beside this one).
   When a name cannot be placed, that algorithm says why, and the renderer draws no map and shows its sentence.

### Maps

- **Sensors along the rows.**
  Each declared column of type `number` is one map, in declared order, and row `k` holds sensor `k`.
  A second dimension along the columns labels the maps: with `{"header": true}`, by the column names; with `{"role": "<role>", "column": "<column>"}`, by that column's cells in row order.
  Without one, a map's label is its column name.
- **Sensors along the columns.**
  Each data row is one map, and the declared columns of type `number` are the sensors, in declared order (with `{"header": true}`, their names are the sensor names).
  A second dimension along the rows labels the maps by a column of this file (`{"column": "<column>"}`, which is not a sensor) or by a column of another role (`{"role": "<role>", "column": "<column>"}`, by position).
  Without one, a map's label is its row number, counted from 1.

A renderer reads each map's values in sensor order and pairs sensor `k` with layout row `k`, with the projection of positions row `k`, or with the place `nemar.sensor-labels.v1` gives the `k`-th name.

### What the renderer shows

Every number on screen comes from a stored row.
A map's readout is the hovered sensor's stored value, never a grid cell, and a marker sits at each plotted sensor's squeezed place.
A sensor that was merged keeps its own marker and readout; only the interpolation uses the merged value.

### What the writer enforces

JSON Schema cannot compare one file with another, so the writer enforces that the values have one entry per layout or positions row (or per name), that those names are unique, and that every declared column is in the file's header.

## Parity

An implementation matches a vector case when:

- it refuses the cases the vector refuses, with the same word, and draws the others;
- its mask is the vector's, cell for cell;
- each unmasked cell is within `1e-6 * (max_ref - min_ref)` of the vector's, where `max_ref` and `min_ref` are the vector's largest and smallest unmasked cells; for a constant map, within `1e-12 * max(1, |v|)` of its value `v`;
- `plotrad`, `intrad`, `squeezefac` and each grid point are within a relative `1e-12` of the vector's;
- the limits, the color axis and the contour levels, which follow from the cells, are within the cells' bound;
- its plotted, interpolated and merged sensors are the vector's exactly.

Every decision in a vector case (a merge distance against ε, a sensor against the square or `plotrad`, a cell against the head circle) is at least `1e-9` from its threshold, or computed exactly as written here, so a sine or cosine that differs in its last bit cannot flip one.

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
  The merge (step 3) is this page's answer for exact duplicates and for sensors closer than ε, whose matrix is nearly singular.
  The vectors' `exact_duplicates` case records that eegprep's own map of the unmerged sensors has no finite cell, and the test suite checks the pseudo-inverse map against the merged one (sccn/eegprep#670).
- **A value that is not finite shifts the others.**
  eegprep drops such a sensor from the positions but not from the values (EEGLAB's `Values = Values(plotchans)` has no counterpart), so every later value lands on the wrong sensor.
  This page drops both, as EEGLAB does; the vectors' `nan_values` case is eegprep's map with those sensors removed, and records that eegprep's map of the raw inputs disagrees with it (sccn/eegprep#670).
- **The interpolation square has no absolute value.**
  eegprep tests `(x <= intrad) & (y <= intrad)`, and EEGLAB's `topoplot.m` has the same test, `intchans = find(x <= intrad & y <= intrad)` (checked against EEGLAB's development copy of 17 September 2025).
  A sensor far behind the head (large negative x) or far to its left (large negative y) is interpolated and widens the grid; one far in front or far to the right is not.
  This page keeps the rule for parity with the maps users compare against.
- **The color axis margin.**
  EEGLAB moves both color limits 5% away from zero after every limit choice; eegprep does so for `absmax` and explicit limits but not for `maxmin`, where it leaves the limits to matplotlib.
  This page follows EEGLAB.
- **Too few sensors, and maps with nothing to draw.**
  eegprep draws any number of sensors; this page refuses fewer than 3.
  Where a sensor stretches the grid past the head, or the interpolation overflows, eegprep returns a map with no finite cell; this page refuses it with a word.

## Vectors

[`views/vectors/sensor-field.v1.json`](../../views/vectors/sensor-field.v1.json) has the reference it came from (eegprep's commit, and the numpy and scipy versions), the tolerances above, and the cases.
Each case gives `sensors` (`name`, `theta_deg`, `radius`, `value`, with `null` for a number that is not finite) and either `refused` (the word) or `expected`: `plotrad`, `intrad`, `squeezefac`, `plotted`, `interpolated` and `merged` (sensor rows counted from 0; each merge group lists its kept sensor first), the grid axes `x` and `y`, the cells `z` (`z[i][j]` at `(x[i], y[j])`, `null` where masked), `limits` and `color_axis` for both choices, and `contours`.
The expected map is eegprep's `topoplot` of the usable, merged sensors.
A case whose `sensors` give `x`, `y` and `z` instead of `theta_deg` and `radius` is placed by positions, in the frame its `coordinate_system` names (or `n/a` with its `montage`): its `expected.layout` is the projection by `nemar.sensor-layout.v1` (`center`, `center_method`, `theta_deg`, `radius`, compared as [`sensor-layout.md`](sensor-layout.md#parity) says), and the map is drawn from that layout.
The cases cover 32, 64, 128 and 256 sensors on eegprep's packaged caps (laid out by `nemar.sensor-layout.v1`), exact duplicates, sensors 4e-4 and 9e-4 from another (merged), two sensors 1.5e-3 apart (not merged), sensors all on the midline, sensors outside the head and outside the interpolation square, values and places that are not finite, equal values, all zeros (a constant map), exactly 3 sensors, 2 sensors and a merge down to 2 (refused), a dynamic range of 10^6, a sensor so far out that no cell is inside the head and values that overflow (refused), a field whose most negative value outweighs its most positive, and positions: 64 measured positions (one without a finite x) and 32 template positions projected to maps, and positions in an unknown frame and a montage beside a named frame (refused, `frame_unknown`).

`scripts/generate_view_vectors.py` writes the file from eegprep, with the `vectors` dependency group (Python 3.12 or later): `uv run --group vectors python scripts/generate_view_vectors.py`.
With `--check` it writes nothing and fails when a regenerated value differs from the committed one by more than `1e-9` of the map's range (`1e-12` relative for other numbers), which absorbs linear algebra libraries that round differently and catches any change to eegprep or to the rules around it.
