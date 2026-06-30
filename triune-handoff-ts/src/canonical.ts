import { CanonicalizationError } from "./errors";

/**
 * Reference TypeScript implementation of TSCP-CANON-001 v1.0.
 *
 * Every structural rule (top-level type, NFC normalization, key-collision
 * detection, integer-only numeric policy) is enforced HERE, inside
 * canonicalize(), not in any test harness that calls it. A conformance test
 * that reimplements these rules itself instead of exercising this function
 * is not testing this implementation — it is testing a copy of the rules.
 *
 * Takes raw JSON text rather than an already-parsed object, because
 * JSON.parse() collapses "5" and "5.0" to the same JS number and silently
 * loses precision above Number.MAX_SAFE_INTEGER — both of which this spec
 * must detect exactly (§3.1.3). A tiny pre-pass tags every numeric literal
 * with its original source text before handing off to JSON.parse, so float
 * detection and big-integer preservation are both exact.
 */

type JsonValue =
  | null
  | boolean
  | string
  | RawNumber
  | JsonValue[]
  | { [key: string]: JsonValue };

interface RawNumber {
  __rawNumeric: true;
  text: string;
}

function isRawNumber(v: unknown): v is RawNumber {
  return typeof v === "object" && v !== null && (v as any).__rawNumeric === true;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v) && !isRawNumber(v);
}

function numberLiteralIsInteger(text: string): boolean {
  return !text.includes(".") && !text.includes("e") && !text.includes("E");
}

/**
 * Parses JSON text while tagging every numeric literal with its exact
 * source text, by substituting each top-level numeric token (outside of
 * string literals) with a small object before delegating to JSON.parse.
 */
function parseTaggingNumbers(raw: string): unknown {
  const pattern = /"(?:[^"\\]|\\.)*"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  const tagged = raw.replace(pattern, (match, numMatch: string | undefined) => {
    if (numMatch === undefined) return match; // matched a string literal; leave as-is
    return `{"__rawNumeric":true,"text":${JSON.stringify(numMatch)}}`;
  });
  return JSON.parse(tagged);
}

function nfc(s: string): string {
  return s.normalize("NFC");
}

function typeNameOf(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (isRawNumber(v)) return "number";
  return typeof v;
}

/** Recursively NFC-normalizes strings/keys and rejects float literals. */
function normalize(value: unknown): JsonValue {
  if (value === null) return null;
  if (typeof value === "boolean") return value;
  if (isRawNumber(value)) {
    if (!numberLiteralIsInteger(value.text)) {
      throw new CanonicalizationError(
        "TSCP-CANON-FLOAT-PROHIBITED",
        "NUMERIC",
        `floats are prohibited in Protocol Objects: ${value.text}`,
      );
    }
    return value;
  }
  if (typeof value === "string") return nfc(value);
  if (Array.isArray(value)) return value.map(normalize);
  if (isPlainObject(value)) {
    const out: Record<string, JsonValue> = {};
    for (const [k, v] of Object.entries(value)) {
      if (typeof k !== "string") {
        throw new CanonicalizationError("TSCP-CANON-NON-STRING-KEY", "VALIDATION", `non-string key: ${String(k)}`);
      }
      const nk = nfc(k);
      if (Object.prototype.hasOwnProperty.call(out, nk)) {
        throw new CanonicalizationError(
          "TSCP-CANON-KEY-COLLISION",
          "NORMALIZATION",
          `duplicate key after NFC normalization: ${JSON.stringify(nk)}`,
        );
      }
      out[nk] = normalize(v);
    }
    return out;
  }
  throw new CanonicalizationError("TSCP-CANON-TOPLEVEL-NONMAP", "VALIDATION", `unsupported type: ${typeNameOf(value)}`);
}

function serializeString(s: string): string {
  return JSON.stringify(s);
}

function serialize(value: JsonValue): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (isRawNumber(value)) return value.text.replace(/^(-?)0+(\d)/, "$1$2"); // defensive; inputs should already be normalized-form integers
  if (typeof value === "string") return serializeString(value);
  if (Array.isArray(value)) return "[" + value.map(serialize).join(",") + "]";
  const keys = Object.keys(value).sort();
  const body = keys.map((k) => `${serializeString(k)}:${serialize((value as Record<string, JsonValue>)[k])}`).join(",");
  return "{" + body + "}";
}

/**
 * Top-level entry point. Validates, normalizes, and serializes raw JSON
 * text into canonical UTF-8 bytes per TSCP-CANON-001 v1.0. Throws
 * CanonicalizationError (§8 taxonomy) on any spec violation.
 */
export function canonicalize(rawInput: string): Uint8Array {
  const parsed = parseTaggingNumbers(rawInput);

  if (!isPlainObject(parsed)) {
    throw new CanonicalizationError(
      "TSCP-CANON-TOPLEVEL-NONMAP",
      "VALIDATION",
      `top-level input must be a JSON object, got ${typeNameOf(parsed)}`,
    );
  }

  const normalized = normalize(parsed);
  const text = serialize(normalized);
  return new TextEncoder().encode(text);
}
