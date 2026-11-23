# Generic kinds: `nemar.table`, `nemar.lines`, `nemar.heatmap` and `nemar.histogram`

This page is normative for version 1 of the generic kinds that draw stored data as a table, a line chart, a heatmap or a histogram.
`nemar.sensor-field`, the fifth generic kind, has its own page.
For each kind, the page says what the declaration holds and which model a renderer builds from the declaration and its files before it draws anything.
The model is what two renderers must agree on: the same numbers, the same labels, the same readout under a pointer and the same refusals.
How a model is drawn (colors, fonts, layout) is the renderer's, within the rules below.

[`views/vectors/kinds-models.v1.json`](../../views/vectors/kinds-models.v1.json) (`nemar.kinds-models.v1`) holds the cases every renderer reproduces, and `neuroschema.views.build_model` is the Python reference.
[`views/vectors/kinds-verdicts.v1.json`](../../views/vectors/kinds-verdicts.v1.json) (`nemar.kinds-verdicts.v1`) holds declarations and contents with the schemas' verdicts, for a renderer that checks them without a JSON Schema engine.

## Building a model

A renderer builds a view's model in four steps.

1. It checks the declaration against `view.schema.json#/$defs/view`, with a JSON Schema engine or with guards held to the [verdict corpus](#the-verdict-corpus).
   An invalid declaration is refused with `declaration_invalid`, and nothing is drawn.
2. It chooses the drawing by the [renderer rule](../views.md#kinds-and-the-renderer-rule): the view's own kind, its base when the view meets the base's role contract, or the fallback.
3. It builds that kind's model from the files, as this page says.
   A preset drawn by its base gets the base's model, and the base ignores the preset's `parameters` and uses its own defaults.
4. When the kind's rules refuse the files, it builds the [fallback](#the-fallback) instead and keeps the kind and the word, so the page can say why the view shows as a table.

A renderer reads only the files its model needs, and it checks each one before it parses it.
The file must be present (`file_missing`), its length must be the declared `size` (`file_size_mismatch`), and its Secure Hash Algorithm 256 (SHA-256) digest must be the declared `sha256` (`file_digest_mismatch`).
A failed check refuses the whole view and nothing is drawn, because the bytes are not the bytes NEMAR recorded.
Because no view hides data, the renderer still offers every other file of the view for download, and it checks a file it has not read when that file is downloaded.
An invalid declaration offers no file, because the declaration that names the files is itself invalid.
A file longer than `caps.bytes_per_role` in the registry (4,194,304 bytes) is refused with `cap_exceeded`, and the view falls back.

Every model lists the view's files under `downloads`: each `data` entry, then each `file` input, in declaration order, with its role, location, size and SHA-256.
A renderer offers each of them for download, so no view hides data, whether a file is drawn, shown as a table or neither.

## Reading files

### TSV

A tab-separated values (TSV) file is read under the grammar of [docs/views.md](../views.md#tsv).

- The bytes do not begin with a byte order mark, and they decode as UTF-8 (Unicode Transformation Format, 8-bit) (`tsv_encoding`).
  JavaScript's `TextDecoder` replaces bytes that are not UTF-8 with U+FFFD unless it is built with `fatal: true`, and it drops a byte order mark unless it is built with `ignoreBOM: true`; a renderer builds it with `{fatal: true}` and checks the first three bytes itself.
- The text holds no carriage return (CR) and ends with a line feed (LF) (`tsv_line_endings`).
- Without its final LF, the text splits at each LF into lines: the first is the header, and each later line is a data row.
- A line splits at each TAB into cells.
  Header names are unique (`tsv_header_repeated`), and every data row has as many cells as the header (`tsv_ragged`).

These checks run in the order of this list.
An empty line is a row of one empty cell, and a file with only a header has no data rows.

A role reads only the columns it declares in `columns`, by header name and in declared order.
A role that declares a name twice is refused with `column_repeated`, and one that declares a name the header lacks with `column_missing`.
Header columns the role does not declare are ignored, so one file can serve two roles.

A cell is read by the type of its column, or of its dimension when it is a coordinate.

- `string`: the cell's text.
- `number`: the text matches the JavaScript Object Notation (JSON) number grammar, `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?` (`cell_not_number`), and its value is finite (`cell_not_finite`; `1e400` is not).
- `integer`: the text matches `-?(0|[1-9][0-9]*)`, with no fraction and no exponent, and its magnitude is at most 9007199254740991, which is 2^53 - 1 (`cell_not_integer`).

A numeric cell's value is the binary64 nearest its text, as JavaScript's `Number(text)` and Python's `float(text)` both read it, and a negative zero reads as zero.
The text is kept as well: a readout prints the stored text and never prints a number again.

### JSON

A JSON file is read as Internet JSON (I-JSON): UTF-8 with no byte order mark, no object with two members of one name, no `NaN` or `Infinity` literal, and every number finite as a binary64 (`json_invalid`).
These are the rules for the [view digest's input](view-digest.md#input), plus the finite rule.
`1e400` is not finite, and neither is an integer literal beyond binary64 range, such as 1 followed by 400 zeros: JavaScript's `JSON.parse` reads it as `Infinity`, and Python reads it exactly but cannot make it a binary64.
The rule covers every number in the file, members the kind does not read included.

## Coordinates

A dimension's coordinates label the rows or the columns of a role ([docs/views.md](../views.md#dimensions)).

- `{"column": c}`, on a dimension along the rows: the cells of column `c` of the same file, which the role declares (`coords_unresolved`).
  That column is the role's coordinate column; it is not a value column.
- `{"header": true}`, on a dimension along the columns: the names of the role's value columns.
  Its type is `string`.
- `{"role": r, "column": c}`, on either: by position, the cells of column `c` of role `r` of the same view, top to bottom.
  Role `r` appears exactly once in the view's `data`, as a `tsv` file that declares `c` (`coords_unresolved`).
  Its file is checked and read as above, `c` is in its header (`column_missing`), and it has one cell per position (`coords_length`): one per data row for a dimension along the rows, and one per value column for a dimension along the columns.

A coordinate column's declared `type` is its dimension's `type`, and its `unit`, when it declares one, is its dimension's `unit` (`coords_mismatch`).
Each coordinate cell is read by the dimension's type, and its text is its label.

Each kind's schema says which forms it admits.
A view of a generic kind has only that kind's one role, so its coordinates come from its own file.
A preset over a generic kind may take them from another of its own roles; the base's model resolves them against the preset's `data`, and that role's file is drawn as labels.

## Value columns

The value columns of a `nemar.lines` or `nemar.heatmap` role are its declared columns other than its coordinate column, in declared order.
Each has the type `number` or `integer` (`value_type`), and all of them have the same `unit` or all have none (`value_units_differ`); that unit is the unit of the values.
A role with no data row or no value column is refused with `empty`.

A role holds at most `caps.entries_per_dim` (1,024) data rows and 1,024 value columns, and at most `caps.cells_per_role` (262,144) cells, counting every declared column of every data row (`cap_exceeded`).

## Order of checks

When the files break more than one rule, the first rule broken gives the word.
For `nemar.table`, `nemar.lines` and `nemar.heatmap`, the checks run in this order.

1. The role's file: present, size, SHA-256, then the cap on bytes.
2. The TSV grammar, in the order of its list.
3. The declared columns: first whether any name is declared twice (`column_repeated`), then each name in declared order (`column_missing`).
4. The coordinate column, if the role has one (`coords_unresolved`, then `coords_mismatch`).
5. The value columns, each in declared order (`value_type`), then their units (`value_units_differ`), then `empty`, then the caps on rows, value columns and cells.
   A table has only the cap on cells here.
6. The cells, column by column and never row by row: the coordinate column first, then the value columns in declared order (for a table, the declared columns in declared order), each column from top to bottom.
7. The kind's own rule (`x_not_increasing` for `nemar.lines`).
8. Coordinates from another role, the rows' dimension before the columns'; for each, `coords_unresolved`, then that role's file and grammar, `column_missing`, `coords_mismatch`, `coords_length`, and its cells.

For `nemar.histogram`, they run in this order: the file and the cap on bytes, `json_invalid`, `content_invalid`, `edges_not_increasing`, `counts_length`, then the cap on the total (`cap_exceeded`).
The vectors hold one case for each pair of neighboring checks, with two faults, so a renderer that runs two checks in the other order gives the other word.

## `nemar.table` version 1

The declaration is one TSV file in the role `table`, with `columns` and no dimensions ([docs/views.md](../views.md#nemartable-version-1)).

```json
{
  "type": "table",
  "columns": [{"name": "name", "type": "string", "unit": null}],
  "rows": [["Fp1", "EEG", "good"], ["Fp2", "EEG", "bad"]]
}
```

`columns` are the declared columns in declared order, each with its unit or `null`.
`rows` holds, for each data row in file order, the text of each declared column in declared order.
Each cell of a `number` or `integer` column is checked by its type, so a column with `n/a` cells is declared `string`.
A table with a header and no rows is valid and has no rows.
A table holds at most 262,144 cells, counting the declared columns.

A renderer shows the columns in declared order, with each column's unit in its header, and each cell as its text.
It may let a reader sort the rows by a column, and it never changes a cell's text.

## `nemar.lines` version 1

The declaration is one TSV file in the role `values`, with at least two `columns`, each `number` or `integer`, and exactly two `dims`:

- the x dimension, along the rows, of type `number` or `integer`, with coordinates `{"column": x}`;
- the series dimension, along the columns, with coordinates `{"header": true}` or, in a preset, `{"role": r, "column": c}`.

It has no base, no inputs, no transform and no parameters.
This `values` entry draws a spectrum, one series per sensor:

```json
{
  "role": "values",
  "location": "sub-01/eeg/sub-01_desc-nemarspectrum_spectrum.tsv",
  "format": "tsv",
  "size": 9120,
  "sha256": "…",
  "columns": [
    {"name": "freq_hz", "type": "number", "unit": "Hz"},
    {"name": "Fp1", "type": "number", "unit": "dB"},
    {"name": "Fp2", "type": "number", "unit": "dB"}
  ],
  "dims": [
    {"name": "freq", "axis": "rows", "type": "number", "unit": "Hz", "coords": {"column": "freq_hz"}},
    {"name": "sensor", "axis": "columns", "type": "string", "coords": {"header": true}}
  ]
}
```

The model:

```json
{
  "type": "lines",
  "x": {"dim": "freq", "type": "number", "unit": "Hz", "column": "freq_hz", "values": [0, 0.5], "text": ["0", "0.5"]},
  "y": {"unit": "dB", "min": -3.25, "max": 12.5},
  "series": {
    "dim": "sensor", "type": "string", "unit": null,
    "items": [{"label": "Fp1", "column": "Fp1", "values": [12.5, 8], "text": ["12.5", "8"]}]
  }
}
```

- `x.values` and `x.text` are the x column's cells; the values are strictly increasing (`x_not_increasing`).
- There is one series per value column, in declared order, and its label is its coordinate: the column's name, or the other role's cell at its position.
- `y.min` and `y.max` are the smallest and the largest value of all the series, and `y.unit` is the unit of the values.

A renderer draws each series as straight segments between its points in row order, on one x axis and one y axis.

A pointer reads one stored row, never a value between rows.
For a pointer at x, let i be the last row with x_i <= x.
If there is no such row, the pointer reads row 0, and if i is the last row, it reads row i.
Otherwise it reads row i + 1 when x_(i+1) - x < x - x_i, and row i when not, so a tie reads the lower row.
The two differences are computed in binary64.
The readout prints `x.text` at that row with `x.unit`, and each series' `text` at that row, or the hovered series' only, with `y.unit`.

## `nemar.heatmap` version 1

The declaration is one TSV file in the role `values`, with `columns` and exactly two `dims`:

- the row dimension, along the rows, with coordinates `{"column": c}`, a label column of the file, or, in a preset, `{"role": r, "column": c}`;
- the column dimension, along the columns, with coordinates `{"header": true}` or, in a preset, `{"role": r, "column": c}`.

`parameters.limits` is `minmax`, the default, or `absmax`.
It has no base, no inputs and no transform.

```json
{
  "type": "heatmap",
  "rows": {"dim": "component", "type": "string", "unit": null, "labels": ["IC1", "IC2"]},
  "columns": {"dim": "class", "type": "string", "unit": null, "labels": ["brain", "eye"], "names": ["brain", "eye"]},
  "unit": "%",
  "values": [[91.5, 2], [4.25, 88]],
  "text": [["91.5", "2"], ["4.25", "88"]],
  "limits": {"rule": "minmax", "min": 2, "max": 91.5}
}
```

- `values[i][j]` and `text[i][j]` are data row i of value column j.
- `rows.labels` are the row coordinates; `columns.names` are the value columns' header names, and `columns.labels` their coordinates.
- With `minmax`, the limits are the smallest and the largest cell.
  With `absmax`, they are minus and plus the largest absolute cell, and both are zero when every cell is zero.
  A preset drawn as a heatmap by its base uses `minmax`.

A renderer draws the rows from top to bottom, the first row at the top, and the columns from left to right, the first column at the left.
Each cell is one flat rectangle, colored by its value between the limits: a sequential map for `minmax`, and a diverging map centered on zero for `absmax`.
When the two limits are equal, every cell takes one color.
Nothing is interpolated or smoothed between cells.
A pointer over a cell reads that cell: the row label, the column label and the cell's text, with the unit.

## `nemar.histogram` version 1

The declaration is one JSON file in the role `histogram`, with no columns and no dimensions, and no parameters.
Its content meets [`content.nemar.histogram.v1`](../../schema/views/content.nemar.histogram.v1.schema.json), which has two forms.

- Bins by edges: `edges`, 2 to 1,025 numbers; `counts`, one per bin; `underflow` and `overflow`; and an optional `unit` of the binned values.
  This is the shape of a `dataQuality` distribution's `histogram`.
- Bins by category: `categories`, 1 to 1,024 distinct names with no TAB, CR or LF, and `counts`, one per category, with none of `edges`, `underflow`, `overflow` and `unit`.

Every count is an integer from 0 to 2^53 - 1.
The content may hold other members, which a preset over this kind defines; this kind reads only these.
Content that fails the schema is refused with `content_invalid`.
JSON Schema cannot state two more rules: the edges are strictly increasing (`edges_not_increasing`), and there is one count per bin (`counts_length`).

Bin i holds the values v with e_i <= v < e_(i+1), and the last bin also holds a value equal to the last edge.
`underflow` counts the values below the first edge, and `overflow` the values above the last edge.
This is the rule of nemar-process's binning and of the `dataQuality` distributions.
A renderer draws the counts it is given and never bins values itself; when it marks a value on a histogram, such as one recording's value on its dataset's distribution, it finds the bin by this rule.

```json
{
  "type": "histogram",
  "bins": "edges",
  "unit": "%",
  "items": [
    {"label": "[0, 50)", "lower": 0, "upper": 50, "upper_closed": false, "count": 2},
    {"label": "[50, 100]", "lower": 50, "upper": 100, "upper_closed": true, "count": 15}
  ],
  "underflow": {"label": "< 0", "count": 0},
  "overflow": {"label": "> 100", "count": 1},
  "total": 18,
  "max_count": 15
}
```

- Each bin's label is `[a, b)`, or `[a, b]` for the last bin; the underflow's is `< e` with the first edge, and the overflow's `> e` with the last.
  A number in a label is printed as ECMAScript's `String(x)` prints it (`0.1`, `100`, `1e-7`, `1e+21`), as the [view digest](view-digest.md#canonical-form) prints numbers.
- With bins by category, `bins` is `categories`, each item is `{"label", "count"}` with the category as its label, and `unit`, `underflow` and `overflow` are `null`.
- `total` is the sum of all the counts, underflow and overflow included, summed in binary64, and `max_count` is the largest of them.
  A content whose total would pass 2^53 - 1 is refused with `cap_exceeded`, so that sum is exact.

A renderer draws one bar per bin, in order, whose height is its count, never a density.
Bins by edges sit on a numeric axis from the first edge to the last, each bar spanning its bin; bins by category are bars of equal width.
An underflow or overflow bar is drawn at its end only when its count is not zero.
A pointer over a bar reads its label and its count, with the unit for bins by edges.

## Keyboard, data table and text alternative

A renderer offers each drawing three other ways, each built from the model alone.

- **Keyboard.** One step moves the selection to the next or previous stored row (`nemar.lines`), cell (`nemar.heatmap`, by row or by column) or bar (`nemar.histogram`), in model order, and shows the readout a pointer on it would show.
  It never stops between stored rows.
- **Data table.** A toggle shows the model as a table built from its text arrays.
  For `nemar.lines`, there is one row per stored row, with `x.text` and each series' `text`; for `nemar.heatmap`, one row per row label, with that row of `text`; for `nemar.histogram`, one row per item with its label and count, then the underflow and the overflow for bins by edges.
  A count is printed as the integer it is, and no other number is printed again.
- **Text alternative.** The text alternative of a drawing is the view's caption followed by text from the model: its axes or dimensions with their units, and the stored texts through the data table.
  It states no number the model does not hold.

## The fallback

A view of a kind the renderer cannot draw, by itself or by its base, shows as tables with downloads; so does a view whose kind refused its files.

```json
{
  "type": "fallback",
  "tables": [{"role": "values", "location": "…_spectrum.tsv", "header": ["freq_hz", "Fp1"], "rows": [["0", "12.5"]]}]
}
```

`tables` holds, in declaration order, each `data` file of format `tsv` that meets the TSV grammar and the caps on bytes and on cells, counting every header column; each table is the file's header and rows as text.
Every other file, such as a JSON file, a file of another format or a TSV file that breaks the grammar, is offered for download only.
The fallback refuses nothing of its own, but a missing or changed file still refuses the whole view.

A model's `drawing` is the drawing chosen (`{"via": "kind" | "base" | "table", "kind", "kind_version"}`), and the fallback's is `{"via": "table", "kind": null, "kind_version": null}`.
When a kind refused the files, `refused` is `{"kind", "kind_version", "word"}`, and otherwise it is `null`.

## Words

| Word | Outcome | Meaning |
|---|---|---|
| `declaration_invalid` | nothing drawn | The declaration fails `view.schema.json#/$defs/view`. |
| `file_missing` | nothing drawn | A file the model reads is not there. |
| `file_size_mismatch` | nothing drawn | A file's length is not its declared `size`. |
| `file_digest_mismatch` | nothing drawn | A file's SHA-256 is not its declared `sha256`. |
| `cap_exceeded` | fallback | A file, the rows, the value columns or the cells exceed the registry's caps, or a histogram's total passes 2^53 - 1. |
| `tsv_encoding` | fallback | Not UTF-8, or a byte order mark. |
| `tsv_line_endings` | fallback | A CR, or no final LF. |
| `tsv_header_repeated` | fallback | Two header names are equal. |
| `tsv_ragged` | fallback | A data row's cell count differs from the header's. |
| `column_repeated` | fallback | The role declares a column twice. |
| `column_missing` | fallback | A declared column, or a coordinate column of another role, is not in the header. |
| `coords_unresolved` | fallback | A coordinate column is not declared, or a coordinate role is absent, repeated or not TSV. |
| `coords_mismatch` | fallback | A coordinate column's type or unit differs from its dimension's. |
| `coords_length` | fallback | Coordinates from another role do not have one cell per position. |
| `value_type` | fallback | A value column is not numeric. |
| `value_units_differ` | fallback | The value columns' units differ. |
| `empty` | fallback | No data row, or no value column. |
| `cell_not_number` | fallback | A `number` cell does not match the JSON number grammar. |
| `cell_not_finite` | fallback | A `number` cell is not finite. |
| `cell_not_integer` | fallback | An `integer` cell is not a JSON integer of at most 2^53 - 1 in magnitude. |
| `x_not_increasing` | fallback | The x values of a line chart are not strictly increasing. |
| `json_invalid` | fallback | Not I-JSON, or a number that is not finite. |
| `content_invalid` | fallback | The content fails its content schema. |
| `edges_not_increasing` | fallback | The edges are not strictly increasing. |
| `counts_length` | fallback | The counts are not one per bin. |

## The model vectors

`kinds-models.v1.json` has `format`, `spec`, `description`, `cases` and `refusals`.
Each case has a `name`, what it `covers`, a `view` declaration, its `files` and the expected `model`, which is the whole output of `build_model`: `drawing`, `refused`, `downloads` and `model`.
`files` maps each location to `{"text": …}`, the file's UTF-8 text, or to `{"base64": …}` for bytes that are not UTF-8; the declaration's `size` and `sha256` are those of the bytes.
A case of `nemar.lines` also lists `snaps`, each a pointer `x` and the `row` it reads, and a case of bins by edges lists `locates`, each a `value` and the `bin` that holds it (-1 for underflow, the number of bins for overflow).
A case or a refusal may carry `caps`, which take the place of the registry's caps of the same names for that case alone, so that small files can reach a cap.
Each refusal has a `name`, what it `covers`, a `view`, its `files`, the `word` and the `downloads` still offered: the view is refused and nothing is drawn.

An implementation parses the file with its JSON parser, builds each case's model and compares it with `model`, texts exactly and numbers by binary64 equality that tells -0 from 0, as JavaScript's `Object.is` does.
A model holds no negative zero: a cell or an edge of -0 reads as 0, and a label prints it as `0`.

## The verdict corpus

`kinds-verdicts.v1.json` has `format`, `spec`, `description` and `cases`.
Each case has a `name`, what it `covers`, the `schema` it is checked against (`view` for `view.schema.json#/$defs/view`, or a content schema's file name), the `instance`, the verdict `valid`, and `errors`: for each error jsonschema reports, the failing keyword and the instance path.
Only `valid` binds an implementation; `errors` say why, for a reader.
The corpus covers the envelope, each generic kind of this page and the histogram content; presets add their own cases.

`scripts/generate_kind_vectors.py` writes both files from the cases it defines, with the Python reference and jsonschema, and `--check` fails when a committed file differs from what it would write.
