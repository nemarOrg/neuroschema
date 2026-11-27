/**
 * Compile every neuroschema schema with ajv 8 in strict mode, then replay the
 * verdict corpus and the view examples, so a TypeScript renderer that
 * validates with ajv gets jsonschema's verdicts (docs/views/generic-kinds.md,
 * The verdict corpus). CI runs it as the job `ajv`:
 *
 *     bun install --frozen-lockfile --cwd scripts/ajv
 *     bun scripts/ajv/check.ts
 *
 * Each schema is added as it is in schema/, under its own absolute $id, so the
 * folder-qualified relative $refs resolve by RFC 3986 with no loader of our own.
 * Strict mode is ajv's `strict: true` (unknown keywords, ignored keywords,
 * missing types, tuples, numbers) with two settings stated here: the one
 * annotation keyword the schemas use, x-extension-managers, is declared, and
 * strictRequired is off, because a `required` inside an `if`, `not` or `oneOf`
 * branch names a property its parent defines, which is how these schemas state
 * conditions. Formats are not validated, as in the Python reference, which
 * passes no format checker. Patterns compile with the `u` flag (ajv's default),
 * as .rules/schema-design.md requires.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";

const ROOT = join(import.meta.dir, "..", "..");
const SCHEMA_DIR = join(ROOT, "schema");
const BASE = "https://raw.githubusercontent.com/nemarOrg/neuroschema/v0.6.1/schema/";

const ajv = new Ajv2020({
  strict: true,
  strictRequired: false,
  allErrors: true,
  validateFormats: false,
  keywords: ["x-extension-managers"],
});

function schemaFiles(dir: string): string[] {
  return readdirSync(dir)
    .sort()
    .flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return schemaFiles(path);
      return name.endsWith(".schema.json") ? [path] : [];
    });
}

const problems: string[] = [];
const ids: string[] = [];
for (const path of schemaFiles(SCHEMA_DIR)) {
  const schema = JSON.parse(readFileSync(path, "utf8"));
  const id = BASE + relative(SCHEMA_DIR, path).split(sep).join("/");
  if (schema.$id !== id) problems.push(`${path}: $id is ${schema.$id}, not ${id}`);
  ajv.addSchema(schema);
  ids.push(schema.$id);
}
for (const id of ids) {
  try {
    ajv.getSchema(id);
  } catch (error) {
    problems.push(`${id}: ${(error as Error).message.split("\n")[0]}`);
  }
}

function report(): void {
  for (const problem of problems) console.error(problem);
  if (problems.length) process.exit(1);
}
report();

function validator(name: string) {
  const id =
    name === "view"
      ? `${BASE}definitions/view.schema.json#/$defs/view`
      : name === "dataQuality"
        ? `${BASE}extensions/dataQuality.schema.json`
        : name === "neuroschema.schema.json" || name.includes("/")
          ? `${BASE}${name}`
          : `${BASE}views/${name}`;
  const validate = ajv.getSchema(id);
  if (!validate) throw new Error(`no schema ${id}`);
  return validate;
}

const corpus = JSON.parse(
  readFileSync(join(ROOT, "views", "vectors", "kinds-verdicts.v1.json"), "utf8"),
);
for (const c of corpus.cases) {
  const valid = validator(c.schema)(c.instance) as boolean;
  if (valid !== c.valid)
    problems.push(`verdict ${c.name}: ajv says ${valid}, the corpus ${c.valid}`);
}

const dataQuality = ajv.getSchema(`${BASE}extensions/dataQuality.schema.json`);
const examples = join(ROOT, "examples", "views");
const exampleFiles = readdirSync(examples).filter((name) => name.endsWith(".json"));
for (const name of exampleFiles) {
  const document = JSON.parse(readFileSync(join(examples, name), "utf8"));
  if (!dataQuality?.(document)) {
    problems.push(`examples/views/${name}: ${JSON.stringify(dataQuality?.errors?.slice(0, 3))}`);
  }
}

console.log(
  `${ids.length} schemas compiled in strict mode; ${corpus.cases.length} verdicts and ` +
    `${exampleFiles.length} view examples replayed`,
);
report();
