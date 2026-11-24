# Presets: `nemar.spectrum`, `nemar.ic-maps`, `nemar.ic-classes`, `nemar.ic-activity` and `nemar.signal-window`

A preset is a kind drawn over one generic kind, its base.
This page is normative for version 1 of NEMAR's five presets: what each declares, what a renderer that knows it draws beyond its base, and what it checks.
[docs/views.md](../views.md) gives the renderer rule, and [generic-kinds.md](generic-kinds.md), [sensor-field.md](sensor-field.md) and [sensor-labels.md](sensor-labels.md) give the bases' models and the scalp map.

| Preset | Base | Data roles | Inputs | Written by |
|---|---|---|---|---|
| `nemar.spectrum` | `nemar.lines` | `values`, `layout` (optional) | none | the plugin `nemar-spectrum` |
| `nemar.ic-maps` | `nemar.sensor-field` | `values`, `layout`, `components` | none | the recipe `nemar-ica` |
| `nemar.ic-classes` | `nemar.histogram` | `histogram` | none | the plugin `nemar-quality` |
| `nemar.ic-activity` | `nemar.lines` | none | `unmixing`, `signal`, `components`, `badsegments` (optional) | the recipe `nemar-ica` |
| `nemar.signal-window` | `nemar.lines` | none | `signal`, `channels` (optional), `badsegments` (optional) | a recipe |

## Presets and their bases

Every preset declares `base` and `base_version`, and its schema fixes them.
A preset with stored data meets its base's role contract: for each role the base admits, the preset's schema takes the base's subschema for that role (`allOf` with a `$ref` to it) and narrows it, and its rules across roles imply the base's.
So a renderer that knows only the base draws the preset by it, from the roles the base reads, and offers every other file of the view for download; `neuroschema.views.draw_as` returns `base` for such a view when the registry does not list the preset.
The base ignores the preset's parameters and uses its own defaults.
The Python reference of the generic kinds, `neuroschema.views.build_model`, builds no preset's own model: it draws a registered preset by its base, as a renderer that knows only the base would.

A computed preset (`nemar.ic-activity`, `nemar.signal-window`) has inputs and no stored data, so no renderer can draw it from data by its base: its base names how its output is drawn.
A renderer that does not know a computed preset offers its file inputs for download, and the renderer rule shows the view as a table with nothing in it.

However a preset is drawn, every file it names, in `data` or as a `file` input, is drawn or offered for download.
A renderer that knows a preset first builds its base's model; when the base refuses the files, the view falls back as the base's rules say.
When the base draws, the preset's own checks run in the order this page gives, and the first that fails gives the word: the renderer draws the view by its base and keeps the word, so the page can say why the preset's extras are missing, or, for `nemar.signal-window`, draws nothing.
`neuroschema.views.presets.check_preset` is the Python reference of these checks, and [`views/vectors/preset-checks.v1.json`](../../views/vectors/preset-checks.v1.json) (`nemar.preset-checks.v1`) holds the cases every renderer reproduces.

## `nemar.spectrum` version 1

A power spectral density per sensor, over `nemar.lines`.

- **`values`** is a `nemar.lines` values entry: the column `freq_hz` (a `number` in `Hz`) is the x column, with the dimension `freq` along the rows (`unit` `Hz`, coordinates `{"column": "freq_hz"}`), and every other declared column is one sensor, a `number` in `dB`, with the dimension `sensor` along the columns.
- **`layout`**, optional, is a `nemar.sensor-field` layout entry (`name`, `theta_deg`, `radius`, optionally `sensor_type`).
  With a layout, the values' sensor coordinates are `{"role": "layout", "column": "name"}`: the sensors are the layout's rows, by position.
  Without one, they are `{"header": true}`: the sensors are the values' header names, which a renderer places with [`nemar.sensor-labels.v1`](sensor-labels.md).

The parameters record how the spectrum was computed; a renderer prints them and recomputes nothing.

| Parameter | Required | Meaning |
|---|---|---|
| `method` | yes | `welch`: the average of the periodograms of overlapping windows. |
| `window` | yes | The taper, by its lowercase name (`hamming` for NEMAR's spectra). |
| `window_s` | yes | Each window's length, in seconds (2 for NEMAR's). |
| `overlap` | yes | The share of each window that overlaps the next, from 0 up to but not including 1 (0.5 for NEMAR's). |
| `unit` | yes | `dB`: 10 log10 of the density in microvolts squared per hertz, so 0 dB is 1 µV²/Hz. |
| `upper_hz` | yes | The highest frequency the rows reach (125 Hz for NEMAR's EEG spectra); every `freq_hz` cell is at most this and at most half the sampling rate. |
| `initial_maps_hz` | no | Up to 8 frequencies whose maps are shown before the reader picks one. |

A renderer that knows this kind draws the `nemar.lines` model of the values, and below it a scalp map of the sensors' values at one frequency row: the row the readout snaps to, or, before the reader picks one, the row nearest each frequency of `initial_maps_hz` by the same rule.
A map is the row's cells as one value per sensor, drawn with `nemar.sensor-field.v1` with `minmax` limits (the decibels are not signed about zero), and placed by the layout or by the sensors' names.
A map the scalp-map algorithm refuses (for example `too_few_sensors`) shows that word in its place, and the lines are drawn all the same.

The writer makes sure that the rows rise strictly from 0 to at most `upper_hz`, and, with a layout, that the values' sensor columns are the layout's rows in order.

## `nemar.ic-maps` version 1

The scalp maps of the independent components of one decomposition, over `nemar.sensor-field`.

- **`values`** is the mixing matrix (`_mixing.tsv`), a `nemar.sensor-field` values entry: the dimension `sensor` along the rows, with coordinates `{"role": "layout", "column": "name"}`, and the dimension `component` along the columns, named by the header (`IC001`, `IC002` and so on), one `number` column per component.
- **`layout`**, required, is a `nemar.sensor-field` layout entry; the components were classified on these positions, so no map is placed by names.
- **`components`** is the components table (`_components.tsv`): one row per component, with the dimension `component` along the rows, named by its column `component` (a `string`); its other declared columns, such as `variance_pct` and the class probabilities, make the component's text row.

There are no parameters.
A renderer that knows this kind draws one map per component with `nemar.sensor-field.v1` and `absmax` limits, because a component's polarity is arbitrary, and prints each component's text row beside its map: the cells of its row of `components`, each with its column's name and unit, as stored text.
The text row of the component labeled L is the row of `components` whose `component` cell is L.
The renderer reads the components table under the TSV grammar ([generic-kinds.md](generic-kinds.md#tsv), with its words), checks it has the column `component` (`column_missing`), and checks that its `component` cells, top to bottom, are the values' declared column names in declared order, compared as text (`components_mismatch`): one row per map, in the maps' order.
When any of these fails, it draws the maps by the base, without text rows, and keeps the word.
A renderer that knows only `nemar.sensor-field` draws the maps and offers the components table for download.

## `nemar.ic-classes` version 1

The independent components of one decomposition counted by the class each is most likely to be (its dominant class), over `nemar.histogram`.

- **`histogram`** is one JSON file (`_icclasses.json`) whose content meets [`content.nemar.ic-classes.v1`](../../schema/views/content.nemar.ic-classes.v1.schema.json): a `nemar.histogram` content binned by category, `categories` (the classes in the classifier's order) and `counts` (the number of components whose dominant class each is), with `classifier`, `summed_variance_pct` (for each class, the sum of its components' `variance_pct`) and `n_components`.
  With `classifier` `ICLabel`, `categories` is exactly ICLabel's seven classes in ICLabel's order and spelling: `Brain`, `Muscle`, `Eye`, `Heart`, `Line Noise`, `Channel Noise`, `Other` (eegprep's `DEFAULT_ICLABEL_CLASSES`).
  The name is spelled `ICLabel`: any other case of it is refused, so a change of case cannot open the classes.
  Any other classifier names its own classes.

```json
{
  "classifier": "ICLabel",
  "categories": ["Brain", "Muscle", "Eye", "Heart", "Line Noise", "Channel Noise", "Other"],
  "counts": [12, 3, 2, 0, 1, 0, 4],
  "summed_variance_pct": [61.25, 9.5, 14.75, 0, 0.5, 0, 6.125],
  "n_components": 22
}
```

There are no parameters.
`variance_pct` is the percent of the data's variance a component accounts for on its own (EEGLAB's `pvaf`), which is not bounded to 0 to 100 and does not sum to 100 across components, so neither does `summed_variance_pct`.

A renderer that knows this kind draws the `nemar.histogram` model of the content, and prints with each bar its count and its class's summed variance, as the stored numbers; the text alternative names `n_components`.
After the histogram's own checks, the renderer checks, in this order, that the content meets `content.nemar.ic-classes.v1` (`content_invalid`: content that meets the histogram's content schema but not this one, such as ICLabel's classes out of order), that `summed_variance_pct` has one entry per category (`variance_length`), and that the counts sum to `n_components` (`components_total`); JSON Schema cannot state the last two.
When one fails, the view is drawn by the base with the word.
A renderer that knows only `nemar.histogram` draws the categories and counts.

## `nemar.ic-activity` version 1

The activations of the independent components of one decomposition over a window of the recording, computed in the browser from the serving copy and never stored, over `nemar.lines`.
[ic-activity.md](ic-activity.md) is normative: the transform `nemar.ic-activity.v1` (the browser's unmixing matrix times the serving copy's physical values, with no preprocessing), the display filter the view declares, the window, the store digest's states and the words.

## `nemar.signal-window` version 1

A window of the recording as the serving copy holds it, opened in the signal viewer, over `nemar.lines`: one line per channel over time.

- **`signal`** is the recording's store in the serving copy.
- **`channels`**, optional, is the floor's `_channels.tsv`: a channel whose `status` is `bad` is marked as bad.
- **`badsegments`**, optional, is the floor's `_badsegments.tsv`: each row is marked over `[onset, onset + duration)` seconds, labeled by its `label` cell.

| Parameter | Required | Meaning |
|---|---|---|
| `start_s` | yes | The window's start, in seconds from the recording's first sample. |
| `duration_s` | yes | Its length, in seconds, at most 30. |

The view computes nothing and has no transform: the renderer opens the signal viewer on the store's samples in the window and shows them as the store holds them, in physical units, with the floor's decisions marked.
The window holds the samples k of the recording (0 <= k < S, for S samples at rate r) whose time `k / r`, one binary64 division, satisfies `start_s <= k / r < end`, where `end = start_s + duration_s`, one binary64 sum: the first is the least such k, and a window past the recording's end is clipped to its last sample.
A renderer finds them from these times, not from `ceil(start_s * r)`, which can start a sample late at a rate such as 500/7 Hz.
NEMAR's recipes declare the 2-second window inside the floor's good samples nearest the recording's middle (`midsegment`).
The renderer checks the store digest first, as [ic-activity.md](ic-activity.md#the-checks-in-order) does: when the view declares one and the serving copy publishes another, nothing is drawn (`store_digest_mismatch`), because the decisions marked over the window were made on other data; when either is absent, the window is drawn and the state is `not_checked`.
Then a window that holds no sample (one that starts at or after the recording's end, or lies between two samples) draws nothing (`window_outside`).

## Words

| Word | Preset | Outcome | Meaning |
|---|---|---|---|
| `tsv_encoding`, `tsv_line_endings`, `tsv_header_repeated`, `tsv_ragged` | `nemar.ic-maps` | base | The components table breaks the TSV grammar ([generic-kinds.md](generic-kinds.md#words)). |
| `column_missing` | `nemar.ic-maps` | base | The components table has no column `component`. |
| `components_mismatch` | `nemar.ic-maps` | base | The components table's `component` cells are not the values' header names, in order. |
| `content_invalid` | `nemar.ic-classes` | base | The content fails `content.nemar.ic-classes.v1` (it meets the histogram's). |
| `variance_length` | `nemar.ic-classes` | base | `summed_variance_pct` does not have one entry per category. |
| `components_total` | `nemar.ic-classes` | base | The counts do not sum to `n_components`. |
| `store_digest_mismatch` | `nemar.signal-window` | nothing drawn | The serving copy publishes a digest other than the one the view declares. |
| `window_outside` | `nemar.signal-window` | nothing drawn | The window holds no sample of the recording. |

The words of a preset's base, of `nemar.sensor-field.v1` and of `nemar.ic-activity.v1` keep their meanings and outcomes; a file that is not the one recorded (`file_missing`, `file_size_mismatch`, `file_digest_mismatch`) draws nothing, as for every kind.

## The preset-check vectors

`preset-checks.v1.json` has `format`, `spec`, `description` and `cases`.
Each case has a `name`, what it `covers`, a `view` (built from the [example](../../examples/views/dataquality-record-nemar-ica.json)), its `files` (each location's UTF-8 text), for a signal window the `store` (`samples`, `rate` and the digest the serving copy publishes, or null), and the `expected` outcome: `word` null when the checks pass, with the `state` and the window's `first` sample and `count` for a signal window; otherwise the `word` and its `outcome`, `base`, `nothing` or `fallback` (the base refused the file first, with its own word).
The cases cover every word of this page, each pair of neighboring checks with two faults, and a window at 500/7 Hz where the times rule and a rounded product disagree.
`scripts/generate_kind_vectors.py` writes them with the Python reference.

## The verdict corpus

[`kinds-verdicts.v1.json`](../../views/vectors/kinds-verdicts.v1.json) holds each preset's declarations, valid and invalid, and contents of `content.nemar.ic-classes.v1`, with jsonschema's verdicts, beside the generic kinds' ([generic-kinds.md](generic-kinds.md#the-verdict-corpus)).
Each valid preset declaration with stored data also meets its base's role contract, and a test holds that.
