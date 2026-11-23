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
| `base`, `base_version` | for a preset | The generic kind a preset draws over; always given together. |
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
2. Otherwise, if it knows the base and base version and the view's data meet the base's role contract, it draws the view with the generic renderer for the base, and offers every other file in the view's `data` for download.
3. Otherwise it shows the data as a table, with a download of each file.

No view hides data: however a view is drawn, every file in its `data` is either drawn or offered for download.

A view meets a kind's role contract when every role the kind's schema admits appears exactly once in its `data`, and that entry is valid under the kind schema's subschema for the role: `data.items`, or, for a kind with several roles, the branch of its `oneOf` or `anyOf` for that role.
The format, the dimensions and every field the kind requires (a table's `columns`, a dimension a kind needs) all come from that one schema.
Roles the kind does not admit are allowed, and its renderer ignores them.
A declared base is a claim: the schema cannot check an unknown kind's data against its base, so the renderer checks the contract before it trusts the claim.
The Python reference validates each entry with jsonschema, and a TypeScript renderer validates it against the base kind's schema with ajv, or with guards held to neuroschema's verdict corpus.
An unknown kind is never an error, and neither is a base the renderer does not know or a view that misses its base's contract.
`neuroschema.views.draw_as` implements the rule against the registry, `neuroschema.views.meets_role_contract` the contract, and `neuroschema.views.role_schemas` finds each role's subschema.

In the registry, each kind lists its roles: `roles.<role>.formats` are the formats the role may take, and `roles.<role>.dims` are the dimensions it may carry, where an empty list means the role carries none.
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

## Data roles

Each entry of `data` is one file read as one role.

| Field | Required | Meaning |
|---|---|---|
| `role` | yes | The role the file plays in the kind (`values`, `layout`, `table`). |
| `location` | yes | Path inside the run's product; the same string as its signalJourney `outputTargets` location. |
| `format` | yes | A registered format (`tsv` or `json`); a `tsv` file ends in `.tsv` and a `json` file in `.json`. |
| `size`, `sha256` | yes | The file's size in bytes and the Secure Hash Algorithm 256 (SHA-256) digest of its bytes. |
| `columns` | no | `[{name, type, unit?}]`: the columns this role reads; `type` is `number`, `integer` or `string`. |
| `dims` | no | `[{name, axis, type, unit?, coords}]`: the dimensions; see [Dimensions](#dimensions). |
| `coordinate_system` | no | For a role of sensor positions: the Brain Imaging Data Structure (BIDS) name of the coordinate system, or `n/a`. |
| `position_source` | no | For a role of sensor positions: `measured` (from the dataset's own files, which NEMAR does not verify) or `template`. |
| `montage` | no | For a role of `template` positions: the montage they were taken from, by its name in `views/montages` ([`nemar.sensor-labels.v1`](views/sensor-labels.md)). A `template` role carries `montage` and `coordinate_system` `n/a`, and its positions are read as right-anterior-superior (RAS) meters, the montage's frame. |

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
| `sensor` | A sensor, by its name; the coordinates are the `name` column of a layout role, in that role's row order. |

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
The registry lists the transforms neuroschema specifies, with their specifications and vectors.
A view's files are its `data` files and its `file` inputs.

## Scope

`scope` is `recording` when absent.
`subject`, `dataset` and `collection` are reserved: a view of one of these scopes lists the records it summarizes in `sources` (`[{record_sha256}]`, at least one), and a recording view has no `sources`.
Nothing writes or reads a reserved scope yet.

## Formats

The formats are an open registry; `tsv` and `json` are defined.

### TSV

- The encoding is UTF-8 (Unicode Transformation Format, 8-bit), and every line ends with a line feed (LF), the last line included.
- One header row, then data rows; cells are separated by a horizontal tab (TAB).
- A numeric cell matches the JSON number grammar and is finite.
- A text cell holds no TAB, carriage return (CR) or LF.

The recipes' writer, which prints numbers with `.17g`, conforms.

### JSON

UTF-8 JSON, with no duplicate member names and no `NaN` or `Infinity`.

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

The schema checks the envelope, each registered kind, identifier patterns, the extension of a `tsv` or `json` file, the unit of `time`, a store digest for a serving run, and the scope rule.
JSON Schema cannot compare one value with another, so the writer enforces:

- view keys are unique within a recipe entry, and roles are unique within a view;
- column names are unique within a role, and every declared column is in the file's header;
- a `{role, column}` coordinate names a role of the same view and a column that role declares;
- `size` and `sha256` are those of the file, and `location` is the `outputTargets` location of the step that wrote it;
- each file, dimension and role is within the caps;
- the reserved dimensions keep their meanings (a `sensor` dimension's coordinates are a layout role's names, in order);
- a view that declares a base meets that base's role contract, so a renderer that knows only the base can draw it.

A renderer does not rely on the writer for the last rule: before it draws a view by its base, it checks the contract, and it shows the data as a table when the view misses it.
Nor does it rely on the writer for the rules of a generic kind's files (a header that holds every declared column, finite numbers, an x column that increases): it checks them while it builds the model, and shows the data as a table, with the word, when a file breaks one ([generic-kinds.md](views/generic-kinds.md)).

## Versioning

A new kind, format or transform is an addition, released as a PATCH.
A change to a kind is a new `kind_version`, with its own schema file; the old version stays defined.
Changes to the envelope follow the schema's versioning rules (`.rules/schema-design.md`).
