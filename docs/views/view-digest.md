# `nemar.view-digest.v1`

The digest of a view declaration: the Secure Hash Algorithm 256 (SHA-256) of the declaration's canonical JavaScript Object Notation (JSON), written as 64 lowercase hexadecimal digits.
The canonical form is the JSON Canonicalization Scheme (JCS) of Request for Comments (RFC) 8785.
This page is normative; [`views/vectors/view-digest.v1.json`](../../views/vectors/view-digest.v1.json) holds the cases every implementation reproduces, and `neuroschema.views.view_digest` is the Python reference.

## Input

The input is one view declaration, a JSON object, exactly as written in the record (the signalJourney record's `extensions.nemar.views`, or the record-level `dataQuality` entry projected from it).
A field that a reader adds, such as an address a route attaches, is not part of it: a reader digests the declaration before it adds anything.
The declaration is parsed with a standard JSON parser, so each number is the Institute of Electrical and Electronics Engineers (IEEE) 754 binary64 value nearest its text, as JavaScript's `JSON.parse` reads it; an integer beyond 2^53 becomes the nearest binary64 (9007199254740993 reads as 9007199254740992).

## Canonical form

1. There is no whitespace between tokens.
2. `null`, `true` and `false` are written as themselves.
3. An array keeps its order.
4. An object's members are sorted by name, comparing the names' UTF-16 code units (Unicode Transformation Format, 16-bit) as unsigned integers.
   This is not code point order: U+1F600 (code units D83D DE00) sorts before U+FF61.
5. A string is written between quotation marks with only these escapes:
   `\"` for the quotation mark, `\\` for the reverse solidus, `\b`, `\t`, `\n`, `\f` and `\r` for U+0008, U+0009, U+000A, U+000C and U+000D, and `\u00xx` with lowercase hexadecimal digits for every other character from U+0000 to U+001F.
   Every other character is written as itself, including `/`, U+007F, U+2028, U+2029 and every character above U+007F.
6. A number is written as ECMAScript's `Number.prototype.toString` writes it: the shortest decimal that reads back as the same binary64, with no trailing `.0`, `-0` written as `0`, plain notation from 10^-6 up to below 10^21, and otherwise an exponent with an explicit sign (`1e+21`, `1e-7`).
7. The text is encoded as UTF-8 (Unicode Transformation Format, 8-bit), and the digest is the SHA-256 of those bytes.

In JavaScript, rules 2, 5 and 6 are what `JSON.stringify` does for a single value, and rule 4 is the default `Array.prototype.sort` of the names.
A JavaScript implementation must still apply the [refusals](#refusals) itself, before it writes anything: it checks every string and every member name with `String.prototype.isWellFormed` and every number with `Number.isFinite`, because `JSON.stringify` does not fail on either.
It writes a lone surrogate as a `\u` escape and a non-finite number as `null`, which would give a digest where there must be none.
In Python, `json.dumps` is not enough: it prints `100.0` and `1e-07`, sorts by code point, and escapes every character above U+007F by default.

## Refusals

A declaration has no digest, and an implementation raises an error rather than guess, when:

- it is not a JSON object;
- a string or a member name holds a lone surrogate (a code unit from U+D800 to U+DFFF that is not part of a pair);
- a number is not finite (a parser reads `1e400` as infinite).

## What the digest shows

Two declarations with one digest are the same declaration, whatever the order of their members or the spelling of their numbers.
The NEMAR backend computes the digest, the website recomputes it, and an export (an image or a file) embeds it with the kind, the kind version and a permalink, so an export names the exact declaration it was drawn from.
The digest is not a signature: it shows that two copies agree, not who wrote them.

## Vectors

Each case of the vectors file gives a `declaration`, its `canonical` text and its `sha256`.
An implementation parses the vectors file with its standard JSON parser, canonicalizes each declaration, and compares the UTF-8 bytes with `canonical` and their SHA-256 with `sha256`.
Each refusal gives JSON text in `json`, which the implementation parses the same way and must refuse.
The cases cover member order (at every depth, and UTF-16 against code point order), number printing (the ECMAScript boundaries and the RFC 8785 Appendix B values), integers beyond binary64 precision, string escapes, and two declarations of the kind a recipe or plugin writes.
The canonical texts were computed with ECMAScript's own `JSON.stringify` and checked against the Python reference.
