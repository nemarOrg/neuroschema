# `nemar.ic-activity`: component activations computed in the browser

This page is normative for the transform `nemar.ic-activity.v1` and for version 1 of the kind `nemar.ic-activity`, which draws the transform's output.
An activation is an independent component's time course: the independent component analysis (ICA) unmixing matrix times the recording's values.
NEMAR never stores activations.
A browser computes them from the serving copy, NEMAR's 16-bit Zarr copy of each recording, which the viewer already reads under the dataset's read rule (anyone, for a public dataset; for a private one, only the people that rule admits), over a window of at most 30 seconds.

[`views/vectors/ic-activity.v1.json`](../../views/vectors/ic-activity.v1.json) holds the cases every renderer reproduces, and `neuroschema.views.ic_activity` is the Python reference (numpy, the optional extra `views`).
`scripts/generate_ic_activity_vectors.py` writes the vectors from inputs frozen in `scripts/ic_activity_vector_inputs.json`, and holds the reference to scipy's `filtfilt` and to numpy's matrix product.

## What the decomposition got, and what the browser computes

The decomposition always gets the recipe's full preprocessing, whether it reads the dataset's own files (the archive) or the serving copy: channel selection, the removal of flat and bad channels, a high-pass, line-noise removal, artifact subspace reconstruction (ASR), which repairs its bursts (the repaired spans are flagged in the floor's tables, never removed), and the average reference.
The record says what it got, in `decomposition_input`, which the view repeats in its parameters.

The browser applies none of that preprocessing.
The transform is one plain multiply:

    A = W_serving · X

`X` is the serving copy's physical values of the decomposition's channels, and `W_serving` is the browser's matrix, which the recipe writes as `_servingunmixing.tsv`: the unmixing (the ICA weights times the sphere, from microvolts) with each row less its mean, which is the unmixing times the average reference over those channels, times the factor to microvolts from the unit the matrix takes.
So `A` is the unmixing times the average-referenced serving values in microvolts, to rounding.
It approximates the decomposition's own activations, because the decomposition's input was filtered and repaired and the serving copy's values are neither; the view says so.

For display only, the kind then passes each component's activations through a zero-phase high-pass that the view declares (`display_filter`).
That filter is not part of the decomposition and not part of the transform.

## The declaration

```json
{
  "key": "icactivity",
  "kind": "nemar.ic-activity",
  "kind_version": 1,
  "base": "nemar.lines",
  "base_version": 1,
  "caption": "Component activations computed in your browser from the serving copy, with no preprocessing; they approximate the decomposition's input.",
  "source": {"recipe": {"name": "nemar-ica", "version": "1.0.0-b1"}},
  "inputs": [
    {"role": "unmixing", "file": {"location": "sub-01/eeg/sub-01_task-rest_desc-nemarica_servingunmixing.tsv", "sha256": "…", "size": 6312}},
    {"role": "signal", "store": {"recording": "sub-01/eeg/sub-01_task-rest_eeg.set", "path": "sub-01/eeg/sub-01_task-rest_eeg.zarr", "group": "eeg", "content_sha256": "…", "profile": "serving"}},
    {"role": "components", "file": {"location": "sub-01/eeg/sub-01_task-rest_desc-nemarica_components.tsv", "sha256": "…", "size": 1980}},
    {"role": "badsegments", "file": {"location": "sub-01/eeg/sub-01_task-rest_desc-nemarica_badsegments.tsv", "sha256": "…", "size": 120}}
  ],
  "transform": {"name": "nemar.ic-activity.v1", "parameters": {
    "matrix": "sub-01/eeg/sub-01_task-rest_desc-nemarica_servingunmixing.tsv",
    "applies_to": "serving_copy channels listed, physical unit",
    "note": "no preprocessing; activations approximate the decomposition input",
    "match": "store_row", "rows": [0, 1, 2, 3, 5], "columns": ["Fp1", "Fp2", "Cz", "Pz", "O2"], "unit": "µV",
    "caption": null,
    "shaded": {"label": "burst", "files": ["sub-01/eeg/sub-01_task-rest_desc-nemarica_badsegments.tsv"]}
  }},
  "parameters": {
    "display_filter": {"highpass_hz": 1, "order": 2},
    "max_window_s": 30,
    "decomposition_input": {
      "source": "serving_copy",
      "preprocessing": [{"step": "drift", "function": "eegprep.pop_eegfiltnew"}, {"step": "asr", "function": "eegprep.clean_asr"}, {"step": "reref", "function": "eegprep.pop_reref"}],
      "channels": ["Fp1", "Fp2", "Cz", "Pz", "O2"],
      "channel_types": [["Fp1", "EEG"], ["Fp2", "EEG"], ["Cz", "EEG"], ["Pz", "EEG"], ["O1", "EEG"], ["O2", "EEG"], ["ECG", "ECG"]],
      "channel_types_sha256": "…",
      "reference": "average",
      "unit": "uV",
      "store": {"path": "sub-01/eeg/sub-01_task-rest_eeg.zarr", "group": "eeg", "content_sha256": "…"}
    }
  }
}
```

| Input | Source | What it is |
|---|---|---|
| `unmixing` | a TSV file | `W_serving`: one column per channel, headed by the channel's label, and one row per component, every cell a number (no row-label column). |
| `signal` | a store | The recording's channel group in the serving copy, with the digest the run recorded (`content_sha256`, null for a run that read the archive) and the copy that run read (`profile`). |
| `components` | a TSV file | One row per component, in the matrix's row order; its column `component` labels the components (the recipe's `_components.tsv`). |
| `badsegments` | a TSV file, exactly when `shaded.files` is not null | The floor's bad segments (`onset` and `duration` in seconds, `label`), which a renderer shades. Declared, verified and, when absent, said, as [the floor's tables](presets.md#the-floors-tables) says. |

The transform's parameters are the record's `browser_transform` block (`extensions.nemar.ica.browser_transform`), exactly as nemar-process writes it (nemarOrg/nemar-process#81), every member required:

| Parameter | Meaning |
|---|---|
| `matrix` | The matrix's location in the run's product, the location of the input `unmixing`. |
| `applies_to`, `note` | What the matrix is multiplied by, and what the activations are, in words. |
| `match` | `store_row`: column j is store row `rows[j]` (a decomposition of the serving copy, which read those rows). `label`: column j is the one store row whose label is column j's (a decomposition of the archive, which read no store). |
| `rows` | With `store_row`, the 0-based store row of each column, in column order; `null` with `label`. |
| `columns` | The matrix's columns: its header names, in column order. |
| `unit` | The unit the matrix takes: the store's own unit for a decomposition of the serving copy (its factor to microvolts is folded into the matrix), `uV` for one of the archive. Microvolts may be spelled `uV`, `µV` (U+00B5) or `μV` (U+03BC). |
| `caption` | A caption the view shows with the activations, or `null`; a string when `match` is `label`, which says the channels were not checked against the decomposition's input (nemar-ica writes "not checked against the decomposition input"). |
| `shaded` | `{label, files}`: the spans ASR repaired in the decomposition's input (flagged, never removed), the rows labeled `label` (`burst`) of the floor's bad-segment table. `files` names that table alone, the floor's `_badsegments.tsv` (the location of the `badsegments` input), or is null when the floor wrote no table (its window step was skipped and ASR repaired nothing). `_samplemask.tsv` is never named: its sample indices are the grid the floor read, not the serving copy the view draws. |

The kind's parameters:

| Parameter | Meaning |
|---|---|
| `display_filter` | `{highpass_hz, order}`: the [display filter](#the-display-filter)'s cutoff in hertz, and its order, 2. |
| `max_window_s` | The longest window, in seconds, a renderer computes at once; at most 30. |
| `decomposition_input` | What the decomposition was given, the record's block of that name exactly as nemar-process writes it, closed: `source` (`archive` or `serving_copy`), `preprocessing` (the steps that changed its input, in the order they ran, each `{step, function}`), `channels` (its channels, the matrix's columns, in the recording's order), `channel_types` (every row of the loaded recording as `[label, type]`, the type null for an untyped row), `channel_types_sha256`, `reference`, `unit`, and, for `serving_copy` only, `store` (`{path, group, content_sha256}`). |

`channel_types_sha256` is the SHA-256, in lowercase hexadecimal, of the RFC 8785 canonical JSON of `{"channel_types": channel_types}` as UTF-8: the canonicalization of [`nemar.view-digest.v1`](view-digest.md#canonical-form), so a character outside ASCII is written as itself, not escaped, and there is no final line feed.
`neuroschema.views.ic_activity.channel_types_sha256` computes it, and the vectors' `channel_types_digests` hold cases with labels outside ASCII; a renderer does not need it to draw, but can verify it.

The schema checks that a decomposition of the archive declares a store of profile `archive` and matches by `label`, with a caption that is a string, and that one of the serving copy declares a store of profile `serving`, whose `content_sha256` is then a digest, and matches by `store_row`: the serving copy is never matched by label, which could find a row the decomposition did not read.
In a recording's `dataQuality` entry, every store input of a view names the copy the entry's run read: its `profile` is the entry's.
The transform's schema checks that the view declares `badsegments` exactly when `shaded.files` is not null, whatever the view's kind, so a kind that reuses the transform cannot drop the table.
The writer also makes sure that `shaded.files` is null only when the floor wrote no bad-segment table, that `rows` has one entry per column, that the matrix's header is `columns` and `decomposition_input.channels`, and that the components table has one row per matrix row.
A renderer does not rely on the writer for the rest: it checks that `matrix` is the `unmixing` input's location and `shaded.files[0]` the `badsegments` input's, and, for the serving copy, that `decomposition_input.store` names the `signal` store and its digest ([the checks](#the-checks-in-order)).

## The transform `nemar.ic-activity.v1`

### The store

The transform reads one channel group of the recording's store: its rows in store order, each with a label, a unit, a scale and an offset, the stored integers of each row, and the sampling rate.
A row's label or unit may be absent.
A row's physical value at sample k is

    x = (d · scale) + offset

two binary64 operations, each rounded, as the store content digest `nemar.store-content.v1` computes it.

### The checks, in order

A renderer runs these checks in this order, and the first that fails gives the word.

1. **The declaration.**
   The view's kind is `nemar.ic-activity` version 1 (`kind_unsupported`): the display filter and the window are that kind's, so a view of another kind that names the transform is drawn by the renderer rule (by its base, or as a table), never by these checks.
   Then the declaration is valid (`declaration_invalid`): it has a digest and meets `view.schema.json#/$defs/view`, which applies the transform's schema to every view that names the transform, whatever its kind ([generic-kinds.md](generic-kinds.md#building-a-model)); the transform's schema requires the parameters the computation reads (`display_filter`, `max_window_s`, `decomposition_input`).
2. **The inputs' locations.**
   Each file input is where the record says (`table_location_mismatch`): the `unmixing` input's location is the transform's `matrix`, then the `badsegments` input's, when there is one, is `shaded.files[0]`.
   Then the `unmixing`, `components` and `badsegments` tables are the recording's: each is named `<stem>_<suffix>.tsv` beside the `signal` store's `recording`, with the stem of a product of it, and all share one stem ([the floor's tables](presets.md#the-floors-tables) gives the rule).
   A view cannot read one table and name another, such as a decoy table with no rows in place of the floor's.
3. **The decomposition's store.**
   For a decomposition of the serving copy, `decomposition_input.store` names the `signal` store (`store_mismatch`): its `path` is the store's `path` (or its `recording`, when it has no `path`) and its `group` the store's `group`, then its `content_sha256` is the store's.
   So the state the view shows, `matches` or `not_checked`, is about the store the decomposition read.
4. **The files.**
   The `unmixing` file, then the `components` file, then the `badsegments` file when the view declares one, in that order: each declares at most `caps.bytes_per_role` bytes (`cap_exceeded`, checked before the file is fetched), is present (`file_missing`), has the declared `size` as its length (`file_size_mismatch`) and the declared `sha256` as its SHA-256 (`file_digest_mismatch`).
5. **The store digest.**
   When the view declares a digest (`content_sha256` is not null) and the serving copy publishes one for that group, the two are equal (`store_digest_mismatch`).
   Where the serving copy publishes each group's digest is nemarOrg/nemar-cli#2343's (the converter writes it at commit); until it does, no store publishes one and every view is `not_checked`.
   When either is absent, the activations are drawn and the state is `not_checked`; when both are present and equal, the state is `matches`.
6. **The rate.**
   The store's sampling rate is a finite number above 0 (`rate_invalid`).
7. **The window.**
   The window the renderer asks for, `[s0, s0 + n)`, holds at least one sample and lies in the store, `0 <= s0` and `s0 + n <= S` for S samples (`window_outside_store`), and holds at most `floor(max_window_s · rate)` samples (`window_too_long`); see [The window](#the-window).
8. **The matrix.**
   The `unmixing` file meets the TSV grammar, with its words, in their order ([generic-kinds.md](generic-kinds.md#tsv)); its header names are the channel labels, and the grammar already refuses a name twice (`tsv_header_repeated`).
   It has at least one data row (`empty`), and at most `caps.entries_per_dim` (1,024) rows and columns and `caps.cells_per_role` (262,144) cells (`cap_exceeded`).
   Then every cell is a `number` (`cell_not_number`, `cell_not_finite`), read column by column from the first, each from top to bottom.
9. **The components.**
   The `components` file meets the TSV grammar, holds at most `caps.cells_per_role` cells counting every header column (`cap_exceeded`), has the column `component` (`column_missing`), and has one data row per matrix row (`coords_length`).
   Its `component` cells, in order, label the matrix's rows.
10. **The bad segments.**
   When the view declares `badsegments`, its file is read as [presets.md](presets.md#the-floors-tables) says for the floor's tables: the TSV grammar, at most `caps.cells_per_role` cells counting every header column (`cap_exceeded`), the columns `onset`, `duration` and `label`, found by name in any position and looked for in that order (`column_missing`), then every `onset` cell and then every `duration` cell a number (`cell_not_number`, `cell_not_finite`), then every duration above 0 (`duration_not_positive`).
   Then, when no row's `label` cell is `shaded.label`, or the view declares no bad-segment table: if the record says ASR repaired at least one span of the decomposition's input (`bursts_repaired`, below), the table cannot be the right one, its labels are misspelled (`Burst`, `BURST`), or its absence contradicts the record, and the view is refused (`label_unmatched`); otherwise, when the record says it repaired none or the renderer does not know, the view is drawn with nothing shaded and the note `no_shaded_rows`, or `no_bad_segment_table` when there is no table.
   `bursts_repaired` is a fact of the record beside the view, not of the declaration: for nemar-ica, the recipe entry's metric `asrBurstFraction` is above 0; a renderer that has no such fact treats it as unknown.
   A fault refuses the whole view, as every other check does: activations drawn without their shading could pass the spans ASR repaired for brain signal.
11. **The channel match.**
   The matrix's header is the transform's `columns`, in order (`channel_set_mismatch`).
   With `store_row`, `rows` has one entry per column, each a row of the store, and the label of row `rows[j]` is column j's label (`channel_set_mismatch`).
   With `label`, each column's label is the label of exactly one store row (`channel_set_mismatch` when none is, or two are).
   Labels are compared as exact strings: `FP1` is not `Fp1`.
   A store whose rows have no labels matches nothing.
12. **The units.**
   Each matched row's unit is one of the table below (`unit_unknown`, also for a row with no unit), and column j's factor is

       f_j = m(unit of row r_j) / m(unit)

   with `m` from the table, one binary64 division.
   For a decomposition of the serving copy the matrix takes the store's own unit, so every factor is 1.
13. **The display filter.**
   `display_filter.highpass_hz` is below half the store's rate (`filter_out_of_range`).

| Unit | m, to microvolts |
|---|---|
| `V` | 1e6 |
| `mV` | 1e3 |
| `uV`, `µV` (U+00B5), `μV` (U+03BC) | 1 |

### The multiply

For a window of n samples starting at sample s0, with r_j the store row of column j, the transform computes, for each column j and each k from 0 to n - 1,

    x'[j][k] = x(r_j, s0 + k) · f_j

and then, for each component i,

    A[i][k] = W[i][0]·x'[0][k] + W[i][1]·x'[1][k] + … + W[i][C-1]·x'[C-1][k]

in binary64, summed in column order from column 0's product, each product and each sum rounded, with no fused multiply-add.
The time of sample k is `(s0 + k) / rate` seconds, one division.
Nothing else is applied: no reference, no filter, no repair.
A renderer that re-references the store's values changes the activations when the matrix's rows do not sum to zero, and the vectors hold such a case.

The output is a `values` role of `nemar.lines`: time in seconds along x (the reserved dimension `time`), and one series per component, labeled by the `components` table's `component` cells by position.

## The kind `nemar.ic-activity` version 1

### The window

A renderer computes the activations over a window of n consecutive samples `[s0, s0 + n)` that lies in the recording, with `1 <= n <= floor(max_window_s · rate)` (the product in binary64, then the floor).
A window that holds no sample or runs outside the recording is refused with `window_outside_store`, and a longer one with `window_too_long` ([the checks](#the-checks-in-order)); the vectors hold both.
It may draw a longer stretch as several windows, each computed and filtered on its own.

### The display filter

Each component's activations over the window, `x[0..n-1]`, are filtered by a zero-phase high-pass: a Butterworth filter of order 2 at `f = display_filter.highpass_hz`, run forward and then backward over an odd extension of the window.
The reference is scipy's `filtfilt(b, a, x, padtype="odd", padlen=p)` with `(b, a) = butter(2, f, "highpass", fs=rate)`; this section states it so that a renderer in any language computes the same numbers.

**Coefficients.**
The bilinear transform with a prewarped cutoff (the same filter as the high-pass biquad with Q = 1/√2), each line one binary64 expression evaluated left to right, `π` and `√2` the binary64 numbers nearest them:

    K    = tan(π · f / rate)
    norm = 1 / (1 + √2·K + K·K)
    b    = (norm, -2·norm, norm)
    a    = (1, 2·(K·K - 1)·norm, (1 - √2·K + K·K)·norm)

**Initial state.**
The filter's steady state for a constant input of 1 is `zi = (-b0, b2)`: a constant filters to zero.
(`b0 + b1 + b2` is exactly 0, which scipy's `lfilter_zi` reaches by solving a linear system, to rounding.)

**Padding.**
The window is extended at each end by `p = min(9, n - 1)` samples, the odd extension: before the window, `2·x[0] - x[p], …, 2·x[0] - x[1]`; after it, `2·x[n-1] - x[n-2], …, 2·x[n-1] - x[n-1-p]`.
Nine is scipy's default, three times the number of coefficients; a window of 9 samples or fewer is extended by one sample fewer than its length, which is the most scipy allows, and a window of one sample is not extended at all.

**Forward and backward.**
Let `e` be the extended series, of length n + 2p.
The forward pass runs the direct form II transposed from the state `(z0, z1) = (zi0·e[0], zi1·e[0])`, for each sample in order:

    y  = z0 + b0·e[k]
    z0 = (z1 + b1·e[k]) - a1·y
    z1 = b2·e[k] - a2·y

The backward pass runs the same recurrence over the forward output reversed, from the state `zi` times the first sample of that reversed series.
Its output, reversed again, is cut to the window: samples p to p + n - 1.
A window of one sample filters to 0.

The filter's transient at each end of a window is part of the display: the same window always gives the same numbers, and a renderer that draws a recording in several windows filters each on its own.

### Drawing

A renderer draws the filtered activations as `nemar.lines` draws a `values` role: one series per component, against time in seconds, with the readout snapping to a stored sample ([generic-kinds.md](generic-kinds.md#nemarlines-version-1)).
It shades each row of the `badsegments` input whose `label` cell is `shaded.label`, and no other row, over `[onset, onset + duration)` seconds: the spans ASR repaired in the decomposition's input, drawn where they meet the window.
The vectors' `shaded` lists every such row, in file order, whether or not it meets the window, and a renderer clips each to the window itself.
When there is none, it says so with the note `no_shaded_rows` ([presets.md](presets.md#notes-and-states)).
A view with no bad-segment table (`shaded.files` null) shades nothing and says so: its result carries the note `no_bad_segment_table`, shown with its sentence ([presets.md](presets.md#notes-and-states); the vectors' `notes`).
It may mark the table's other rows (the floor's bad windows) apart from them.
With the view's caption it states:

- that the activations were computed in the browser from the serving copy with no preprocessing, so they approximate the decomposition's input, which `decomposition_input` describes;
- the display filter, a high-pass at `highpass_hz` hertz;
- the store digest's state, `matches` or `not_checked`, with its sentence ([presets.md](presets.md#notes-and-states));
- the transform's `caption` when it is not null (with `match` `label`, that the channels were matched by label and not checked against the decomposition's input).

A refused view draws no activations: it shows the word and offers every file input for download.
A renderer that knows `nemar.lines` and this transform but not this kind may draw the transform's output as lines; one that knows neither offers the files for download.

### Parity

A renderer matches the vectors when, for each case and each component i, every activation and every filtered value is within `tolerance.parity` (1e-6) times `m_i`, the largest magnitude of that component's expected activations over the window, and the state, the component labels, the rows, the factors and the times are equal.
A refusal must give its word.
A filter case matches when every value is within 1e-6 times the largest magnitude of its input row.

## Words

| Word | Meaning |
|---|---|
| `kind_unsupported` | The view's kind is not `nemar.ic-activity` version 1, whose display filter and window these checks apply. |
| `declaration_invalid` | The declaration fails `view.schema.json#/$defs/view` (with the transform's schema) or has no digest; among others, it declares `badsegments` when `shaded.files` is null, or not when it names a table. |
| `table_location_mismatch` | The `unmixing` input is not at the transform's `matrix`, or the `badsegments` input is not at `shaded.files[0]`. |
| `store_mismatch` | `decomposition_input.store` does not name the `signal` store: another path, group or digest. |
| `rate_invalid` | The store's sampling rate is not a finite number above 0. |
| `window_outside_store` | The window holds no sample, or does not lie in the store. |
| `window_too_long` | The window holds more than `floor(max_window_s · rate)` samples. |
| `duration_not_positive` | A bad segment's `duration` is not above 0. |
| `label_unmatched` | The record says ASR repaired a span, and no row of the bad segments is labeled `shaded.label`, or the view declares no bad-segment table. |
| `file_missing` | An input file is not there. |
| `file_size_mismatch` | An input file's length is not its declared `size`. |
| `file_digest_mismatch` | An input file's SHA-256 is not its declared `sha256`. |
| `store_digest_mismatch` | The serving copy publishes a digest of the group other than the one the view declares. |
| `cap_exceeded` | A file, the matrix's rows, columns or cells, or the cells of the components or the bad segments exceed the registry's caps. |
| `tsv_encoding`, `tsv_line_endings`, `tsv_header_repeated`, `tsv_ragged` | The matrix, the components table or the bad segments break the TSV grammar ([generic-kinds.md](generic-kinds.md#words)). |
| `cell_not_number` | A matrix cell, or a bad segment's `onset` or `duration`, does not match the JSON number grammar. |
| `cell_not_finite` | A matrix cell, or a bad segment's `onset` or `duration`, is not finite. |
| `empty` | The matrix has no data row. |
| `column_missing` | The components table has no column `component`, or the bad segments lack `onset`, `duration` or `label`. |
| `coords_length` | The components table does not have one row per matrix row. |
| `channel_set_mismatch` | The matrix's header is not `columns`, or a column does not find exactly one store row with its label (by `rows` or by label). |
| `unit_unknown` | A matched store row's unit is not in the table, or is absent. |
| `filter_out_of_range` | The display filter's cutoff is not below half the store's rate. |

## The vectors

`ic-activity.v1.json` has `format` (`nemar.ic-activity.v1`), `spec`, `description`, `tolerance`, `cases`, `refusals`, `store_checks`, `channel_types_digests`, `coefficients` and `filter_cases`.

- Each case has a `name`, what it `covers`, the `view` declaration, its `files` (each location's UTF-8 text), the `store` (`labels`, `units`, `scale`, `offset`, `rate`, `published_sha256`, the digest the serving copy publishes or null, and `digital`, rows by samples), the `window` (`start`, `count`), `bursts_repaired` (whether the record says ASR repaired a span: true, false or null for unknown), and what it gives under `expected`: `state`, `components`, `rows`, `factors`, `time_s`, `activations` and `filtered` (components by samples), `shaded`, the bad segments whose label is `shaded.label`, as `{onset, duration}` in file order, and `notes` (`no_bad_segment_table` when the view declares no bad segments, `no_shaded_rows` when its table has no row labeled `shaded.label`).
  A case may carry `caps`, which take the place of the registry's caps of the same names for that case alone.
- Each refusal has the same fields as a case, with the `word` in place of `expected`.
  The refusals cover each word, and each pair of neighboring checks with two faults, so a renderer that runs two checks in the other order gives the other word.
- `store_checks` lists the digest states: a `declared` and a `published` digest (each a digest or null) and the `outcome`.
- `channel_types_digests` lists `channel_types` lists with their RFC 8785 `canonical` text and `sha256`, among them labels outside ASCII and untyped rows.
- `coefficients` lists `b`, `a` and `zi` for several rates and cutoffs; `filter_cases` lists a `rate`, a `highpass_hz`, the `padding` p, the `input` rows and the `expected` rows, among them windows of 1 to 11 samples around the padding.

The expected values are the Python reference's, which follows this page's order of operations; only the tangent in the coefficients may differ between platforms in its last bit.
`generate_ic_activity_vectors.py --check` regenerates them and compares within 1e-10 of each component's (or input row's) largest magnitude, and fails when the reference differs from scipy by more than 1e-9 of it.
