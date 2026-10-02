import { describe, expect, it } from "vitest";

import { parseJson, prettyBody, stringifyJson } from "./json";

describe("lossless JSON", () => {
  it.each(["9007199254740993", "1.0", "1e400", "0.1000000000000000055", "-0"])(
    "keeps %s exactly as written",
    (number) => {
      const text = `{"n":${number}}`;

      expect(stringifyJson(parseJson(text))).toBe(text);
      // Which the built-in parser does not:
      expect(JSON.stringify(JSON.parse(text))).not.toBe(text);
    },
  );

  it("leaves everything that is not a number alone", () => {
    const text = '{"a":"x","b":[true,null,"1.0"],"c":{}}';

    expect(stringifyJson(parseJson(text))).toBe(text);
  });

  it("rejects what is not JSON", () => {
    expect(() => parseJson("{not json")).toThrow();
  });
});

describe("prettyBody", () => {
  it("indents JSON without touching its numbers", () => {
    expect(prettyBody('{"id":9007199254740993,"amount":1.0}')).toBe(
      '{\n  "id": 9007199254740993,\n  "amount": 1.0\n}',
    );
  });

  it("leaves anything that is not JSON as it is", () => {
    expect(prettyBody("<html>")).toBe("<html>");
    expect(prettyBody(null)).toBe("");
  });
});
