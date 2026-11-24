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
| `nemar.signal-window` | `nemar.lines` | none | `signal`, `channels`, `badsegments` (exactly when `bad_segment_table` is true) | a recipe |

## Presets and their bases

Every preset declares `base` and `base_version`, and its schema fixes them.
A preset with stored data meets its base's role contract: for each role the base admits, the preset's schema takes the base's subschema for that role (`allOf` with a `$ref` to it) and narrows it, and its rules across roles imply the base's.
So a renderer that knows only the base draws the preset by it, from the roles the base reads, and offers every other file of the view for download; `neuroschema.views.draw_as` returns `base` for such a view when the registry does not list the preset.
The base ignores the preset's parameters and uses its own defaults.
The Python reference of the generic kinds, `neuroschema.views.build_model`, builds no preset's own model: it draws a registered preset by its base, as a renderer that knows only the base would.

A computed preset (`nemar.ic-activity`, `nemar.signal-window`) has inputs and no stored data, so no renderer can draw it from data by its base: its base names how its output is drawn.
A renderer that does not know a computed preset offers its file inputs for download, and the renderer rule shows the view as a table with nothing in it.

However a preset is drawn, every file it names, in `data` or as a `file` input, is drawn or offered for download.

A renderer that knows a preset with stored data first builds its base's model, as [generic-kinds.md](generic-kinds.md#building-a-model) says for `nemar.lines` and `nemar.histogram` and [sensor-field.md](sensor-field.md#the-model) for `nemar.sensor-field`.
When the base refuses the files, the view shows as tables with the base's word, the fallback of the base's rules, and the preset's own checks do not run; the vectors give that the outcome `fallback`.
When the base draws, the preset's own checks run in the order this page gives, and the first that fails gives the word, with its outcome: `base`, the renderer draws the view by its base and keeps the word, so the page can say why the preset's extras are missing; `fallback`, it shows the view as the fallback's tables with the word, because the base's drawing would mislead; or `nothing`, for `nemar.signal-window`, it draws nothing.
`neuroschema.views.presets.check_preset` is the Python reference of these checks, and [`views/vectors/preset-checks.v1.json`](../../views/vectors/preset-checks.v1.json) (`nemar.preset-checks.v1`) holds the cases every renderer reproduces.

### The floor's tables

`nemar.ic-activity` shades, and `nemar.signal-window` marks, the floor's decisions: its bad segments (`badsegments`, the floor's `_badsegments.tsv`) and its channels (`channels`, its `_channels.tsv`).
No view may mislead: a renderer never draws activations unshaded or a signal window unmarked when the floor recorded what to shade or mark, because an artifact span left unmarked could pass for brain signal.

**Declared.** A view declares every table the record names, and the schema holds it to that.
The floor always writes `_channels.tsv`, so a `nemar.signal-window` always declares `channels`.
It writes `_badsegments.tsv` unless its window step was skipped and ASR repaired nothing, so a `nemar.ic-activity` declares `badsegments` exactly when its transform's `shaded.files` is not null, and a `nemar.signal-window` exactly when its `bad_segment_table` is true.
The writer sets `shaded.files` and `bad_segment_table` from the record, null and false only when the floor wrote no table.

**Named.** A declared table is the one the record names, and a renderer checks it before it fetches anything (`table_location_mismatch`), because a view that read a decoy table with no rows would draw a clean window.
A `nemar.ic-activity`'s `badsegments` input is at `shaded.files[0]`, which comes from the record ([ic-activity.md](ic-activity.md#the-checks-in-order)).
A `nemar.signal-window`'s tables are the recording's: each lies in the directory of the `signal` store's `recording` and is named `<stem>_channels.tsv` or `<stem>_badsegments.tsv` (the schema checks the suffix), so the two share one stem, as the recipe writes them.
The stem is exactly the one nemar-process gives that recording's products under the label of the recipe that wrote the view, `L`, its id without hyphens (`naming.product_stem` and `naming.label`; `nemarica` for `nemar-ica`): the recording's file name without its last `_<suffix>.<ext>`, with its first `desc-<x>` entity becoming `desc-<x>L` in place (`sub-01_task-rest_desc-cleannemarica` for `sub-01_task-rest_desc-clean_eeg.set`), or, when it has none, `_desc-L` appended (`sub-01_task-rest_desc-nemarica` for `sub-01_task-rest_eeg.set`).
Any other stem is refused: another recording's (`_run-2`, the `ingstate` of `task-restingstate`, `_acq-other`, or the sibling `sub-01_task-rest_desc-preproc`, whose products begin the same way) or another recipe's (`desc-nemarfloor` in a view nemar-ica wrote).
A view a plugin wrote names no recipe, so its tables cannot be tied, and are refused.

**Verified.** A declared table is verified like any data file, and a fault refuses the whole view.
It declares at most `caps.bytes_per_role` bytes (`cap_exceeded`, checked before the file is fetched), it is present, and its length is its `size` and its SHA-256 its `sha256` (`file_missing`, `file_size_mismatch`, `file_digest_mismatch`); when a view declares both tables, the channels' file is checked first.
It meets the TSV grammar, with its words ([generic-kinds.md](generic-kinds.md#tsv)), and holds at most `caps.cells_per_role` cells counting every header column (`cap_exceeded`).
It has its columns (`column_missing`): `onset`, `duration` and `label` for the bad segments, and `name` and `status` for the channels.
A column is found by its name in any position of the header, and the names are looked for in that order; other columns are ignored.
Every `onset` cell and then every `duration` cell is a number (`cell_not_number`, `cell_not_finite`), then every duration is above 0 (`duration_not_positive`): a span of no length or a negative one marks nothing, and the floor writes none.
Every `status` cell of the channels is one of BIDS's `good`, `bad` and `n/a`, compared as exact strings (`channel_status_unknown`): a near miss such as `BAD`, `Bad` or `excluded` is refused, never read as a good channel.
The other columns are text.
The channels are read before the bad segments.

**Said.** A view with no bad-segment table, because the record names none, is drawn and carries the note `no_bad_segment_table`, which a renderer shows with [its sentence](#notes-and-states): nothing is left unshaded or unmarked silently.
The vectors give the note in `notes`.

## `nemar.spectrum` version 1

A power spectral density per sensor, over `nemar.lines`.

- **`values`** is a `nemar.lines` values entry: the column `freq_hz` (a `number` in `Hz`) is the x column, with the dimension `freq` along the rows (`unit` `Hz`, coordinates `{"column": "freq_hz"}`), and every other declared column is one sensor, a `number` in `dB`, with the dimension `sensor` along the columns.
- **`layout`**, optional, is a `nemar.sensor-field` layout entry (`name`, `theta_deg`, `radius`, and `sensor_type`, required when `position_source` is `measured`).
  With a layout, the values' sensor coordinates are `{"role": "layout", "column": "name"}`: the sensors are the layout's rows, by position.
  Without one, they are `{"header": true}`: the sensors are the values' header names, which a renderer places with [`nemar.sensor-labels.v1`](sensor-labels.md).

The parameters record how the spectrum was computed; a renderer prints them and recomputes nothing.

| Parameter | Required | Meaning |
|---|---|---|
| `method` | yes | `welch`: Welch's method, as stated below the table. |
| `window` | yes | The taper, by its lowercase name (`hamming` for NEMAR's spectra). |
| `window_s` | yes | Each window's length, in seconds (2 for NEMAR's). |
| `overlap` | yes | The share of each window that overlaps the next, from 0 up to but not including 1 (0.5 for NEMAR's). |
| `unit` | yes | `dB`: 10 log10 of the density in microvolts squared per hertz, so 0 dB is 1 µV²/Hz. |
| `upper_hz` | yes | The highest frequency the rows reach (125 Hz for NEMAR's EEG spectra); every `freq_hz` cell is at most this and at most half the sampling rate. |

| `initial_maps_hz` | no | Up to 8 frequencies whose maps are shown before the reader picks one. |

`welch` names one computation, so two renderers that print the parameters describe the same numbers.
The recording is cut into windows of `window_s` seconds overlapping by `overlap`; each window is detrended by subtracting its own mean (a constant detrend), tapered by `window`, and its periodogram taken; the periodograms are averaged by their mean, not their median.
The density is one-sided: the power of each frequency above 0 and below half the sampling rate is doubled, so the rows integrate to the variance of the signal over the frequencies they cover.
By rule the 0 Hz row is left out, since detrending each window by its mean makes it meaningless: the first row is the lowest frequency above 0, `1 / window_s` (0.5 Hz for NEMAR's), and the rows rise from it in steps of `1 / window_s`.

A renderer that knows this kind draws the `nemar.lines` model of the values, and below it a scalp map of the sensors' values at one frequency row: the row the readout snaps to, or, before the reader picks one, the row nearest each frequency of `initial_maps_hz` by the same rule.
A map is the row's cells as one value per sensor, drawn with `nemar.sensor-field.v1` with `minmax` limits (the decibels are not signed about zero), and placed by the layout or by the sensors' names.
Its model is the `nemar.sensor-field` model ([sensor-field.md](sensor-field.md#the-model)) of the series' stored cells at those rows: one map per row, labeled by the row's stored frequency text (the dimension `freq`, in Hz), with the sensors and their places read and checked as that page's order of checks says from step 7 on, the layout's rows being the sensors, or the header's names without a layout.
The lines have already read the layout's names, and the preset's own check (below) has found them to be the sensor columns', so what is left to check is the layout's place columns.
A fault in them (for example a theta that is not a number) puts that word in every map's place, and a map the placement or the scalp-map algorithm refuses (for example `too_few_sensors`) shows that word in its place; either way, the lines are drawn all the same.
When the base refuses the values, or the layout's names are not the sensor columns (`sensors_mismatch`, by the one rule a scalp map's model reads too: [sensor-field.md](sensor-field.md#the-order-of-checks)), the view shows as the fallback's tables, and there are no lines and no maps, even when a place column is at fault as well.
A file that is not the one recorded draws nothing, neither the lines nor the maps: `spectrum_maps` raises `ViewRefused`, as `build_model` does.
`neuroschema.views.presets.spectrum_maps` is the Python reference, and the [model vectors](generic-kinds.md#the-model-vectors)' `nemar.spectrum` cases list `maps`: the frequencies asked for (`hz`), the `rows` they snap to, and the maps' `model`, or the word that `refused` them, all three `null` when the view falls back; and `preset`, the outcome of the preset's own check, as the [preset-check vectors](#the-preset-check-vectors) state it.

The writer makes sure that the rows rise strictly from above 0 to at most `upper_hz`, and, with a layout, that the values' sensor columns are the layout's rows in order.
A renderer does not rely on the writer for the last rule: after the base's model is built, it checks, with a layout, that the values' sensor columns (every declared column but `freq_hz`) are the layout's `name` cells, top to bottom, compared as text (`sensors_mismatch`).
The base labels each series by the layout's name at its position, so a header that named other sensors would draw each spectrum under another sensor's name; which of the two is right cannot be told, so the view shows as the fallback's tables ([generic-kinds.md](generic-kinds.md#the-fallback)), with the word, and no lines or maps are drawn.

## `nemar.ic-maps` version 1

The scalp maps of the independent components of one decomposition, over `nemar.sensor-field`.

- **`values`** is the mixing matrix (`_mixing.tsv`), a `nemar.sensor-field` values entry: the dimension `sensor` along the rows, with coordinates `{"role": "layout", "column": "name"}`, and the dimension `component` along the columns, named by the header (`IC001`, `IC002` and so on), one `number` column per component.
- **`layout`**, required, is a `nemar.sensor-field` layout entry; the components were classified on these positions, so no map is placed by names.
- **`components`** is the components table (`_components.tsv`): one row per component, with the dimension `component` along the rows, named by its column `component` (a `string`); its other declared columns, such as `variance_pct` and the class probabilities, make the component's text row.

There are no parameters.
A renderer that knows this kind first builds the `nemar.sensor-field` model of the values and the layout ([sensor-field.md](sensor-field.md#the-model)); when that refuses the files, the view falls back to its tables and no text row is checked.
Otherwise it draws one map per component with `nemar.sensor-field.v1` and `absmax` limits, because a component's polarity is arbitrary, and prints each component's text row beside its map: the cells of its row of `components`, each with its column's name and unit, as stored text.
The text row of the component labeled L is the row of `components` whose `component` cell is L.
The renderer reads the components table as a data file, in this order: its declared size within the cap on bytes, the file (present, size, SHA-256), the TSV grammar ([generic-kinds.md](generic-kinds.md#tsv), with its words), and at most `caps.cells_per_role` cells counting every header column (`cap_exceeded`); then it checks the table has the column `component` (`column_missing`), and that its `component` cells, top to bottom, are the values' declared column names in declared order, compared as text (`components_mismatch`): one row per map, in the maps' order.
When any of these fails, it draws the maps by the base, without text rows, and keeps the word.
A renderer that knows only `nemar.sensor-field` draws the maps and offers the components table for download.

## `nemar.ic-classes` version 1

The independent components of one decomposition counted by the class each is most likely to be (its dominant class), over `nemar.histogram`.

- **`histogram`** is one JSON file (`_icclasses.json`) whose content meets [`content.nemar.ic-classes.v1`](../../schema/views/content.nemar.ic-classes.v1.schema.json): a `nemar.histogram` content binned by category, `categories` (the classes in the classifier's order) and `counts` (the number of components whose dominant class each is), with `classifier`, `summed_variance_pct` (for each class, the sum of its components' `variance_pct`) and `n_components`.
  With `classifier` `ICLabel`, `categories` is exactly ICLabel's seven classes in ICLabel's order and spelling: `Brain`, `Muscle`, `Eye`, `Heart`, `Line Noise`, `Channel Noise`, `Other` (eegprep's `DEFAULT_ICLABEL_CLASSES`).
  The name is spelled `ICLabel`: any other case of it, or `I`, `l`, `1` or `|` in place of one another (`ICLabeI`, `lCLabel`), is refused, so a change of case or a look-alike cannot open the classes.
  The classifier and every category are printable ASCII (U+0020 to U+007E, with no space at either end), so no look-alike from outside ASCII (a Cyrillic letter, a Roman numeral, a fullwidth form, a variation selector or a format character) can pass for a known name.
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

A renderer that knows this kind draws the `nemar.histogram` model of the content, and prints with each bar its count and its class's summed variance, as the stored numbers, labeled "summed variance of components classed X" (with the class for X), never "variance explained by X": each `variance_pct` is one component's own share, the components are not orthogonal, and their sum is not the share the class accounts for together; the text alternative names `n_components`.
After the histogram's own checks, the renderer checks, in this order, that the content meets `content.nemar.ic-classes.v1` (`content_invalid`: content that meets the histogram's content schema but not this one, such as ICLabel's classes out of order), that `summed_variance_pct` has one entry per category (`variance_length`), and that the counts sum to `n_components` (`components_total`); JSON Schema cannot state the last two.
When one fails, the view is drawn by the base with the word.
A renderer that knows only `nemar.histogram` draws the categories and counts.

## `nemar.ic-activity` version 1

The activations of the independent components of one decomposition over a window of the recording, computed in the browser from the serving copy and never stored, over `nemar.lines`.
[ic-activity.md](ic-activity.md) is normative: the transform `nemar.ic-activity.v1` (the browser's unmixing matrix times the serving copy's physical values, with no preprocessing), the display filter the view declares, the window, the store digest's states and the words.

## `nemar.signal-window` version 1

A window of the recording as the serving copy holds it, opened in the signal viewer, over `nemar.lines`: one line per channel over time.

- **`signal`** is the recording's store in the serving copy.
- **`channels`**, always, is the floor's `_channels.tsv`: a channel whose `status` is `bad` is marked as bad.
  Its name must be the label of a store row, compared as exact strings; a bad channel that matches none refuses the view (`bad_channel_unknown`), never left unmarked.
- **`badsegments`**, exactly when `bad_segment_table` is true, is the floor's `_badsegments.tsv`: each row is marked over `[onset, onset + duration)` seconds, labeled by its `label` cell.

Both are [the floor's tables](#the-floors-tables), declared as the record names them and verified before anything is drawn.

| Parameter | Required | Meaning |
|---|---|---|
| `start_s` | yes | The window's start, in seconds from the recording's first sample. |
| `duration_s` | yes | Its length, in seconds, at most 30. |
| `bad_segment_table` | yes | Whether the floor wrote `_badsegments.tsv`, as the record names it: true, and the view declares `badsegments`. |

The view computes nothing and has no transform: the renderer opens the signal viewer on the store's samples in the window and shows them as the store holds them, in physical units, with the floor's decisions marked.
The window holds the samples k of the recording (0 <= k < S, for S samples at rate r) whose time `k / r`, one binary64 division, satisfies `start_s <= k / r < end`, where `end = start_s + duration_s`, one binary64 sum: the first is the least such k, and a window past the recording's end is clipped to its last sample.
A renderer finds them from these times, not from `ceil(start_s * r)`, which can start a sample late at a rate such as 500/7 Hz.
NEMAR's recipes declare the 2-second window inside the floor's good samples nearest the recording's middle (`midsegment`).
The renderer runs nine checks in this order, and the first that fails gives the word; each draws nothing.
First the declaration is valid (`declaration_invalid`).
Then the tables are named as the recording's (`table_location_mismatch`, [the floor's tables](#the-floors-tables)).
Then the tables' files (channels, then badsegments) are the ones recorded.
Then the store digest, as [ic-activity.md](ic-activity.md#the-checks-in-order) checks it: when the view declares one and the serving copy publishes another, nothing is drawn (`store_digest_mismatch`), because the decisions marked over the window were made on other data; when either is absent, the window is drawn and the state is `not_checked`.
Then the store's sampling rate is a finite number above 0 (`rate_invalid`).
Then the tables, channels first, are read as [the floor's tables](#the-floors-tables) says.
Then each bad channel's name is the label of a store row (`bad_channel_unknown`).
Then each store row's label names a row of the channels table (`channel_row_missing`): the floor writes a row for every channel, so a store row with none is a decision dropped, and could be a bad channel drawn as good.
Last, a window that holds no sample (one that starts at or after the recording's end, or lies between two samples) draws nothing (`window_outside`).
The vectors give, for a window drawn, its state, its `first` sample and `count`, the names of its `bad_channels` (status `bad`, in file order), its `segments` (every row of the bad segments, `{onset, duration, label}`, in file order) and its `notes`.

## Words

| Word | Preset | Outcome | Meaning |
|---|---|---|---|
| `sensors_mismatch` | `nemar.spectrum` | fallback | With a layout, the values' sensor columns are not the layout's names, in order. |
| `tsv_encoding`, `tsv_line_endings`, `tsv_header_repeated`, `tsv_ragged` | `nemar.ic-maps` | base | The components table breaks the TSV grammar ([generic-kinds.md](generic-kinds.md#words)). |
| `cap_exceeded` | `nemar.ic-maps` | base | The components table exceeds the registry's caps on bytes or cells. |
| `column_missing` | `nemar.ic-maps` | base | The components table has no column `component`. |
| `components_mismatch` | `nemar.ic-maps` | base | The components table's `component` cells are not the values' header names, in order. |
| `content_invalid` | `nemar.ic-classes` | base | The content fails `content.nemar.ic-classes.v1` (it meets the histogram's). |
| `variance_length` | `nemar.ic-classes` | base | `summed_variance_pct` does not have one entry per category. |
| `components_total` | `nemar.ic-classes` | base | The counts do not sum to `n_components`. |
| `declaration_invalid` | `nemar.signal-window` | nothing drawn | The declaration fails `view.schema.json#/$defs/view` or has no digest (for example, `bad_segment_table` true and no `badsegments` declared). |
| `table_location_mismatch` | `nemar.signal-window` | nothing drawn | A floor table is not beside the recording, or its stem is not the one the view's recipe gives the recording's products (so the two tables share one stem). |
| `tsv_encoding`, `tsv_line_endings`, `tsv_header_repeated`, `tsv_ragged` | `nemar.signal-window` | nothing drawn | A floor table breaks the TSV grammar. |
| `column_missing` | `nemar.signal-window` | nothing drawn | The bad segments lack `onset`, `duration` or `label`, or the channels lack `name` or `status`. |
| `cell_not_number`, `cell_not_finite` | `nemar.signal-window` | nothing drawn | A bad segment's `onset` or `duration` is not a finite JSON number. |
| `cap_exceeded` | `nemar.signal-window` | nothing drawn | A floor table exceeds the registry's caps on bytes or cells. |
| `channel_status_unknown` | `nemar.signal-window` | nothing drawn | A channel's `status` is not `good`, `bad` or `n/a`. |
| `duration_not_positive` | `nemar.signal-window` | nothing drawn | A bad segment's `duration` is not above 0. |
| `rate_invalid` | `nemar.signal-window` | nothing drawn | The store's sampling rate is not a finite number above 0. |
| `store_digest_mismatch` | `nemar.signal-window` | nothing drawn | The serving copy publishes a digest other than the one the view declares. |
| `bad_channel_unknown` | `nemar.signal-window` | nothing drawn | A channel the floor marked bad is no store row's label, compared as exact strings. |
| `channel_row_missing` | `nemar.signal-window` | nothing drawn | A store row's label names no row of the channels table: a floor decision dropped. |
| `window_outside` | `nemar.signal-window` | nothing drawn | The window holds no sample of the recording. |

The words of a preset's base, of `nemar.sensor-field.v1` and of `nemar.ic-activity.v1` keep their meanings and outcomes; a file that is not the one recorded (`file_missing`, `file_size_mismatch`, `file_digest_mismatch`) draws nothing, as for every kind.

## Notes and states

A drawn `nemar.ic-activity` or `nemar.signal-window` carries one store digest state and any notes, and a renderer shows each with its sentence, worded as here and nowhere else.
The vectors give the state in `state` and the notes in `notes`.

| Name | Is a | Preset | Sentence |
|---|---|---|---|
| `matches` | state | both | The serving copy matches the digest NEMAR recorded. |
| `not_checked` | state | both | The serving copy was not checked against a digest NEMAR recorded. |
| `no_bad_segment_table` | note | both | No bad-segment table was written, so nothing is shaded or marked as a bad segment. |
| `no_shaded_rows` | note | `nemar.ic-activity` | The bad-segment table has no row labeled for the spans ASR repaired, so nothing is shaded. |

`matches` claims no more than the digests' agreement ([docs/views.md](../views.md#digests-and-what-they-prove)), and `not_checked` is the state whenever the view declares no digest or the serving copy publishes none.

## The preset-check vectors

`preset-checks.v1.json` has `format`, `spec`, `description` and `cases`.
Each case has a `name`, what it `covers`, a `view` (built from the [example](../../examples/views/dataquality-record-nemar-ica.json)), its `files` (each location's UTF-8 text: for `nemar.ic-maps`, the mixing matrix and the layout its base reads as well as the components table), for a signal window the `store` (its row `labels`, `samples`, `rate` and the digest the serving copy publishes, or null), optionally `caps` in place of the registry's caps of the same names, and the `expected` outcome: `word` null when the checks pass, with, for a signal window, the `state`, the window's `first` sample and `count`, its `bad_channels`, its `segments` and its `notes`; otherwise the `word` and its `outcome`, `base`, `nothing` or `fallback` (the view shows as the fallback's tables: the base refused the file first, with its own word, or the preset's check found the base's drawing would mislead, `sensors_mismatch`).
The cases cover every word of this page, each pair of neighboring checks with two faults, and a window at 500/7 Hz where the times rule and a rounded product disagree.
`scripts/generate_kind_vectors.py` writes them with the Python reference.

The example is one recording of the 19 electrodes of the 10-20 system, all good, decomposed into 18 components (the rank under the average reference).
Its stored views ship their files, and the files of the inputs they share, in [`examples/views/product`](../../examples/views/product) at their locations, with the declared sizes and SHA-256 digests, so the example draws as it stands: its scalp maps and its spectrum's maps at `initial_maps_hz` are drawn, and its presets' checks pass.
The same generator writes those files, and its `--check` holds them.

## The verdict corpus

[`kinds-verdicts.v1.json`](../../views/vectors/kinds-verdicts.v1.json) holds each preset's declarations, valid and invalid, and contents of `content.nemar.ic-classes.v1`, with jsonschema's verdicts, beside the generic kinds' ([generic-kinds.md](generic-kinds.md#the-verdict-corpus)).
Each valid preset declaration with stored data also meets its base's role contract, and a test holds that.
