# Quality views

A quality view is data that a browser draws, declared by the recipe or plugin that wrote it.
No figure image is stored: a view names small data files and says what they mean, and each renderer draws them.
The files are tab-separated values (TSV) or JavaScript Object Notation (JSON) today.
neuroschema owns the vocabulary: the declaration (`schema/definitions/view.schema.json`), the kinds (`schema/views/`), the registry (`views/registry.json`), and the algorithms with their test vectors (`docs/views/`, `views/vectors/`).

A recording's views sit in its record-level `dataQuality` entry, under `recipes.<recipe id>.views` (at most 32).
In the signalJourney record a run writes, the same declarations sit in `extensions.nemar.views`, and each data file is an `outputTargets` entry of the step that wrote it; the NEMAR backend projects them into `dataQuality`.

## The declaration

`$defs/view` is a closed object.

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | The view's key, unique within its recipe entry (`^[a-z][a-z0-9_]{0,63}$`). |
| `kind`, `kind_version` | yes | The kind, namespaced (`nemar.table`), and its version (1 to 999). |
| `base`, `base_version` | for a preset | The generic kind a preset draws over; always given together. A preset is never a base: the envelope refuses a `base` that names one. |
| `caption` | yes | Shown with the view (1 to 500 characters). |
| `source` | yes | `{"plugin": {name, version}}` or `{"recipe": {name, version}}`, exactly one. |
| `scope` | no | `recording` when absent; see [Scope](#scope). |
| `sources` | for a reserved scope | `[{record_sha256}]`, at least one. |
| `parameters` | no | How the data were computed or are to be drawn; each kind constrains it. |
| `data` | `data` or `inputs` | Stored files, one per role; see [Data roles](#data-roles). |
| `inputs` | `data` or `inputs` | Inputs a transform computes the view from; see [Inputs and transforms](#inputs-and-transforms). |
| `transform` | when the kind requires it | `{name, parameters}`, a named, versioned computation. |

At least one of `data` and `inputs` is non-empty.

## Kinds and the renderer rule

A kind is a namespaced name with its own version.
There are two layers: generic kinds, each with one renderer, and presets, each drawn over one generic kind (its `base`).
`views/registry.json` lists the kinds neuroschema defines.
This release defines the generic kinds `nemar.table`, `nemar.lines`, `nemar.heatmap` and `nemar.histogram`, version 1; [generic-kinds.md](views/generic-kinds.md) gives the model a renderer builds for each, the fallback's model, and the words a renderer refuses with.

`view.schema.json` checks every declaration against the envelope.
For a kind and version the registry lists, it also applies that kind's schema, `schema/views/kind.<kind>.v<N>.schema.json`.
Any other kind or version passes on the envelope alone: an unknown kind is never invalid.

A renderer applies this rule:

1. If it knows the view's kind and version, it draws the view with that kind's renderer.
2. Otherwise, if it knows the base and base version as a generic kind and the view's data meet the base's role contract, it draws the view with the generic renderer for the base, and offers every other file in the view's `data` for download. A preset is never a base, so a view that names one shows as a table (and the envelope refuses it).
3. Otherwise it shows the data as a table, with a download of each file.

No view hides data: however a view is drawn, every file in its `data` is either drawn or offered for download.

A view meets a kind's role contract when every role the kind's schema requires appears exactly once in its `data`, every role the schema marks optional appears at most once, and the view's entries in the roles the kind admits, in their order, are valid under the kind schema's `data` subschema.
So each entry is valid under the subschema for its role (`data.items`, or, for a kind with several roles, the branch of its `oneOf` or `anyOf` for that role), and a rule across roles (such as `nemar.sensor-field`'s sensor coordinates, which depend on whether a layout is present) holds too.
A kind marks a role optional with a `contains` clause on `data` (or in `data.allOf`) whose subschema names the role and whose `minContains` is 0; every other role it admits is required.
The format, the dimensions and every field the kind requires (a table's `columns`, a dimension a kind needs) all come from that one schema.
Roles the kind does not admit are allowed, and its renderer ignores them.
A declared base is a claim: the schema cannot check an unknown kind's data against its base, so the renderer checks the contract before it trusts the claim.
The Python reference validates each entry with jsonschema, and a TypeScript renderer validates it against the base kind's schema with ajv, or with guards held to neuroschema's verdict corpus.
An unknown kind is never an error, and neither is a base the renderer does not know or a view that misses its base's contract.
`neuroschema.views.draw_as` implements the rule against the registry, `neuroschema.views.meets_role_contract` the contract, `neuroschema.views.role_schemas` finds each role's subschema, and `neuroschema.views.optional_roles` the roles a kind marks optional.

In the registry, each kind lists its roles: `roles.<role>.formats` are the formats the role may take, and `roles.<role>.dims` are the dimensions it may carry, where an empty list means the role carries none.
A computed kind, which has inputs and no stored data, lists no roles; it lists its inputs instead, `inputs.<role>.source` (`file` or `store`) and, for a file, `inputs.<role>.formats`.
`null` means the names are open: the kind's schema constrains how many dimensions the role carries, along which axes, and where their coordinates come from, but not their names.
A JSON role whose content has a schema names it in `roles.<role>.content`, a file in `schema/views/`.
The kind's schema admits exactly these roles, formats and dimensions, and a test holds the two to each other.
Where they could differ, the schema decides: the role contract reads the schema, and the registry summarizes it.

### `nemar.table` version 1

One stored TSV file, read as the role `table`, with its `columns` declared.
A renderer shows the declared columns in the order declared, one row per data row, each cell as its stored text, and offers the file for download.
It is a generic kind: it has no base, no inputs, no transform, no parameters and no dimensions.

### `nemar.lines`, `nemar.heatmap` and `nemar.histogram` version 1

`nemar.lines` draws one TSV file in the role `values` as one line per value column over an x column that strictly increases.
`nemar.heatmap` draws one TSV file in the role `values` as one flat cell per stored value, with its row and column labels, under `minmax` or `absmax` color limits.
`nemar.histogram` draws one JSON file in the role `histogram`, whose content (`content.nemar.histogram.v1`) gives counts per bin, by numeric edges or by category.
Each is a generic kind with no base, no inputs and no transform; [generic-kinds.md](views/generic-kinds.md) is normative for all three, and for the table's model.

### `nemar.sensor-field` version 1

This release also defines the generic kind `nemar.sensor-field` version 1, a scalp map: the role `values` holds one or more maps, each one value per sensor.
The sensors are placed by one of three sources: the optional role `layout` (`name`, `theta_deg`, `radius`), the optional role `positions` (`name`, `x`, `y`, `z`, which the view's transform `nemar.sensor-layout.v1` projects), or, with neither, the sensors' names, which a renderer places with `nemar.sensor-labels.v1`.
A view has at most one of `layout` and `positions`, and the values' `sensor` coordinates are that role's `name` column, by position.
A renderer draws each map with the algorithm `nemar.sensor-field.v1`; [`views/sensor-field.md`](views/sensor-field.md) specifies the algorithm, the roles, how a renderer reads the maps, and parity.
It is a generic kind: it has no base and no inputs, a transform only with `positions`, and its one parameter, `limits`, chooses `absmax` (the default) or `minmax` color limits.
In the registry, the `values` role's dimensions are `null`, open names: its schema requires one `sensor` dimension (with `contains`) and admits one more of any name, which labels the maps; the `layout` and `positions` roles carry `sensor` only.
A registry entry lists the dimensions a role may carry; which of them it must carry, the kind's schema says, and the role contract reads it there.

### Presets

This release also defines five presets, version 1, each drawn over a generic kind:

- `nemar.spectrum`, a spectrum per sensor with scalp maps at a frequency, over `nemar.lines`;
- `nemar.ic-maps`, independent component maps with a text row per component, over `nemar.sensor-field`;
- `nemar.ic-classes`, components counted by their dominant class, over `nemar.histogram`, with the content `content.nemar.ic-classes.v1`;
- `nemar.ic-activity`, component activations computed in the browser, over `nemar.lines`;
- `nemar.signal-window`, a window of the recording in the signal viewer, over `nemar.lines`.

[presets.md](views/presets.md) is normative for all five, and [ic-activity.md](views/ic-activity.md) for `nemar.ic-activity` and its transform.
A preset with stored data meets its base's role contract, so a renderer that knows only the base draws it by the base; a computed preset has no stored data, and its base names how its output is drawn.

## Data roles

Each entry of `data` is one file read as one role.

| Field | Required | Meaning |
|---|---|---|
| `role` | yes | The role the file plays in the kind (`values`, `layout`, `table`). |
| `location` | yes | Path inside the run's product; the same string as its signalJourney `outputTargets` location. See [Locations](#locations). |
| `format` | yes | The file's format (`tsv` or `json`, or one the registry does not list); a `tsv` file ends in `.tsv` and a `json` file in `.json`, and a file whose name ends in `.tsv` or `.json`, in any case, is of that format. |
| `size`, `sha256` | yes | The file's size in bytes and the Secure Hash Algorithm 256 (SHA-256) digest of its bytes. |
| `columns` | no | `[{name, type, unit?}]`: the columns this role reads; `type` is `number`, `integer` or `string`. |
| `dims` | no | `[{name, axis, type, unit?, coords}]`: the dimensions; see [Dimensions](#dimensions). |
| `coordinate_system` | no | For a role of sensor positions: the Brain Imaging Data Structure (BIDS) name of the coordinate system, or `n/a`. |
| `position_source` | no | For a role of sensor positions: `measured` (from the dataset's own files, which NEMAR does not verify) or `template`. |
| `montage` | no | For a role of `template` positions: the montage they were taken from, by its name in `views/montages` ([`nemar.sensor-labels.v1`](views/sensor-labels.md)). A `template` role carries `montage` and `coordinate_system` `n/a`, and its positions are read as right-anterior-superior (RAS) meters, the montage's frame. |

### Locations

A location (`relativeLocation`, the `location` of a data entry or a file input, and every other path a view names) is a relative POSIX path: Unicode text, written in UTF-8 like the rest of the record, that names one file of the run's product and is never a URL.
It has no leading slash, no URI scheme, no `.` or `..` segment, no empty segment, no backslash, none of `%`, `?` and `#`, no leading or trailing space, no control character (C0, DEL or C1), no line or paragraph separator (U+2028, U+2029) and no bidirectional control (U+061C, U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069).
The pattern's lookaheads match any character with `[\s\S]`, never `.`, which in JavaScript stops at a line terminator.
So it means the same file in every reader: a URL parser strips a leading or trailing space and decodes `%2e%2e` as `..`, `?` and `#` would end the path, and a bidirectional control can show one name as another.
A renderer that fetches a file builds its URL from the location by percent-encoding the UTF-8 bytes of each `/`-separated segment (JavaScript's `encodeURIComponent`) and joining the segments with `/` under the product's base; it compares locations as text.

A role reads only the columns it declares, so one file can serve two roles (a file of sensor names, layout and positions can be the `layout` role with one set of columns and the `positions` role with another).
The sensor type of each row is the `sensor_type` column.

## Dimensions

Dimension names are an open vocabulary, each with an axis (`rows` or `columns` of the file), a type, an optional unit and its coordinates.
The coordinates come from one of:

- `{"column": "<name>"}`: a column of this file;
- `{"header": true}`: this file's header names;
- `{"role": "<role>", "column": "<name>"}`: by position, a column of another role of the same view.

These names are reserved, with fixed meanings (`reserved_dims` in the registry):

| Name | Meaning |
|---|---|
| `time` | Time, in seconds; the schema requires the unit `s`. |
| `epoch` | An epoch of the recording, by its index. |
| `recording` | A recording, by its BIDS path. |
| `subject` | A participant, by BIDS subject label. |
| `contact` | An intracranial electrode contact, by its name. |
| `sensor` | A sensor, by its name; with a layout or positions role, that role's `name` column in row order; with neither, names placed by `nemar.sensor-labels.v1`. |

No name is banned.
A view does not carry a recording's samples: its declared derivation (the step and parameters that wrote it, or its inputs by digest and a named transform), the caps below and the review of every plugin hold that together.

## Inputs and transforms

A computed view names its inputs and the transform that computes it; the browser computes it and nothing stores the result.
Each input has a `role` and exactly one of:

- `file`: `{location, sha256, size}`, a file of the run's product;
- `store`: `{recording, path?, group, content_sha256, profile}`, a recording's store in NEMAR's serving copy.
  `recording` is the BIDS path, `path` the store's path when it is not the recording path, `group` the channel group read, and `content_sha256` the group's `nemar.store-content.v1` digest.
  `profile` is the copy the declaring run read; `content_sha256` is `null` only when that is `archive`, because a run that read the archive recorded no digest of the serving store.

A transform is `{name, parameters}`; its name is namespaced and versioned (`nemar.ic-activity.v1`).
The registry lists the transforms neuroschema specifies, each with its specification, its vectors and its schema, `schema/views/transform.<name>.schema.json`.
`view.schema.json` applies a listed transform's schema to every view that names it, whatever the view's kind: the schema checks the view's inputs and the transform's parameters.
This release specifies `nemar.sensor-layout.v1` ([views/sensor-layout.md](views/sensor-layout.md)), three-dimensional sensor positions to a layout: the positions are a stored data role `positions` that names its own frame (as `nemar.sensor-field` declares it), or the view's one input `positions`, whose frame the transform's parameters name.
It also specifies `nemar.ic-activity.v1` ([views/ic-activity.md](views/ic-activity.md)), component activations as one plain multiply: the browser's unmixing matrix (`unmixing`) times the serving copy's physical values (`signal`) of the decomposition's channels, with no preprocessing, the rows labeled by `components`.
A view's files are its `data` files and its `file` inputs.

## Scope

`scope` is `recording` when absent.
`subject`, `dataset` and `collection` are reserved: a view of one of these scopes lists the records it summarizes in `sources` (`[{record_sha256}]`, at least one), and a recording view has no `sources`.
Nothing writes or reads a reserved scope yet.

## Formats

The formats are an open registry; `tsv` and `json` are defined.
The extension and the format name each other in both directions: a `tsv` file's location ends in `.tsv` and a `json` file's in `.json`, and a location that ends in `.tsv` or `.json` in any case is of that format, so a `.TSV` file or an `.html` file named `.tsv` is invalid.

A file of a format the registry does not list is offered for download only.
A renderer never draws it, embeds it, previews it or navigates to it, and it serves the download with `Content-Disposition: attachment`, the content type `application/octet-stream` and `X-Content-Type-Options: nosniff`, whatever the file's extension or bytes: an `html` or `svg` file a plugin declares would otherwise run as a page under the renderer's origin.
A download of a registered format is an attachment too, with the registry's `media_type`.

### TSV

- The encoding is UTF-8 (Unicode Transformation Format, 8-bit), and every line ends with a line feed (LF), the last line included.
- One header row, then data rows; cells are separated by a horizontal tab (TAB).
- A numeric cell matches the JSON number grammar and is finite.
- A text cell holds no TAB, carriage return (CR) or LF.

The recipes' writer, which prints numbers with `.17g`, conforms.

### JSON

Internet JSON (I-JSON, RFC 7493), the rules for every JSON text neuroschema reads: a view's JSON file, a view declaration (the [view digest's input](views/view-digest.md#input)) and a document `neuroschema.validate` checks.

- The text is UTF-8 with no byte order mark.
- No object has two members of one name, however the names are escaped (`"a"` and `"\u0061"` are one name).
- There is no `NaN` or `Infinity`, and every number is finite as a binary64: `1e400` is not.
- No string or member name holds a lone surrogate (U+D800 to U+DFFF) or a noncharacter (U+FDD0 to U+FDEF, and the last two code points of each plane, U+FFFE, U+FFFF, U+1FFFE and so on to U+10FFFF: 66 code points), written as itself or escaped.
- Arrays and objects nest at most 64 deep: `[[1]]` is 2 deep and a scalar 0.

Each number is the binary64 nearest its text, as JavaScript's `JSON.parse` reads it, and a schema check applies to that reading: 9007199254740993 is checked as 9007199254740992.
`neuroschema.ijson` is the Python reader.
A JavaScript reader decodes the bytes with `new TextDecoder("utf-8", {fatal: true, ignoreBOM: true})`, which throws on bytes that are not UTF-8 (without `fatal` it would put U+FFFD in their place) and keeps a byte order mark as U+FEFF (without `ignoreBOM` it would drop it silently), and refuses text that begins with U+FEFF.
It then parses with `JSON.parse` after a scan that refuses a repeated name and nesting past 64, and checks every string with `String.prototype.isWellFormed` and for the noncharacters.

## Caps

| Cap | Value |
|---|---|
| Bytes per role (one file) | 4,194,304 |
| Entries per dimension | 1,024 |
| Cells per role | 262,144 |

## Digests and what they prove

Every view file is named by its SHA-256 in the declaration and in the record, and a reader checks the digest before it parses the file.
A match shows that the bytes are the bytes NEMAR recorded: it catches corruption in storage, in a cache or in transit.
It does not show that NEMAR is honest, because the same backend serves both the files and their digests; a check "matches the digest NEMAR recorded" and claims nothing more.

A view declaration has its own digest, `nemar.view-digest.v1` ([view-digest.md](views/view-digest.md)): the SHA-256 of its canonical JSON.
The backend computes it, the website recomputes it, and an export embeds it, so an exported image or file names the exact declaration it was drawn from.
Two declarations with one digest are the same declaration; the digest is not a signature.

## What the schema checks and what the writer must check

The schema checks the envelope, each registered kind and transform, identifier patterns, the extension of a `tsv` or `json` file, the unit of `time`, a store digest for a serving run, and the scope rule.
Every integer it takes is at most 2^53 - 1 in magnitude, and every verdict is on the binary64 reading of the declaration ([JSON](#json)), so jsonschema and ajv agree on it.
JSON Schema cannot compare one value with another, so the writer enforces:

- view keys are unique within a recipe entry, and roles are unique within a view;
- column names are unique within a role, and every declared column is in the file's header;
- a `{role, column}` coordinate names a role of the same view and a column that role declares;
- `size` and `sha256` are those of the file, and `location` is the `outputTargets` location of the step that wrote it;
- each file, dimension and role is within the caps;
- the reserved dimensions keep their meanings (a `sensor` dimension's coordinates are, with a layout or positions role, that role's `name` column in row order; with neither, names placed by `nemar.sensor-labels.v1`);
- a view that declares a base meets that base's role contract, so a renderer that knows only the base can draw it.

A renderer does not rely on the writer for the last rule: before it draws a view by its base, it checks the contract, and it shows the data as a table when the view misses it.
Nor does it rely on the writer for the rules of a generic kind's files (a header that holds every declared column, finite numbers, an x column that increases): it checks them while it builds the model, and shows the data as a table, with the word, when a file breaks one ([generic-kinds.md](views/generic-kinds.md)).

## Versioning

A new kind, format or transform is an addition, released as a PATCH.
A change to a kind is a new `kind_version`, with its own schema file; the old version stays defined.
Changes to the envelope follow the schema's versioning rules (`.rules/schema-design.md`).
