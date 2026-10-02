/**
 * JSON without JavaScript's number rounding.
 *
 * JSON.parse turns every number into a 64-bit float: 9007199254740993
 * becomes 9007199254740992 and 1.0 becomes 1. For most applications that
 * is harmless. This one exists to notice when two APIs return different
 * values, and it lets people author the exact request bodies to send, so
 * a number has to come out the way it went in.
 *
 * lossless-json keeps each number as the text it was written with.
 */
import { parse, stringify } from "lossless-json";

export function parseJson(text: string): unknown {
  return parse(text);
}

export function stringifyJson(value: unknown, indent?: number): string {
  return stringify(value, undefined, indent) ?? "";
}

/** Text for display: indented if it is JSON, unchanged otherwise. */
export function prettyBody(body: string | null | undefined): string {
  if (!body) return "";
  try {
    return stringifyJson(parseJson(body), 2);
  } catch {
    return body;
  }
}
