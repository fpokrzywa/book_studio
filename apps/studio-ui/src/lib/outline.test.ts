import { describe, expect, it } from "vitest";
import {
  canIndent,
  indent,
  mergeNext,
  move,
  newNode,
  outdent,
  split,
  wordsOf,
  type OutlineNode,
} from "./outline";

function ch(id: string, words: number | null, sections: string[] = [], locked = false): OutlineNode {
  return {
    ...newNode("chapter", id),
    id,
    target_words: words,
    locked,
    children: sections.map((s) => ({ ...newNode("section", s), id: s })),
  };
}

describe("outline editing", () => {
  it("reorders siblings and keeps every ID", () => {
    const out = move([ch("a", 1), ch("b", 2), ch("c", 3)], [2], 0);
    expect(out.map((n) => n.id)).toEqual(["c", "a", "b"]);
  });

  it("merges a chapter with the next: first ID kept, words and sections combined", () => {
    const out = mergeNext([ch("a", 1000, ["a1"]), ch("b", 500, ["b1"])], [0]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ id: "a", title: "a / b", target_words: 1500 });
    expect(out[0]!.children.map((c) => c.id)).toEqual(["a1", "b1"]);
  });

  it("never merges or splits locked entries", () => {
    const nodes = [ch("a", 1000, [], true), ch("b", 500)];
    expect(mergeNext(nodes, [0])).toBe(nodes);
    expect(split(nodes, [0])).toBe(nodes);
  });

  it("splits a chapter: the new half has no ID yet and the words are shared", () => {
    const out = split([ch("a", 1001, ["s1", "s2", "s3"])], [0]);
    expect(out.map((n) => n.id)).toEqual(["a", undefined]);
    expect(out[0]!.children.map((c) => c.id)).toEqual(["s1", "s2"]);
    expect(out[1]!.children.map((c) => c.id)).toEqual(["s3"]);
    expect(wordsOf(out[0]!) + wordsOf(out[1]!)).toBe(1001);
  });

  it("nests only where the structure allows it, and un-nests back to a chapter", () => {
    const part = { ...newNode("part", "Part one"), id: "p" };
    const nodes = [part, ch("a", 100, ["a1"])];
    expect(canIndent(nodes, [1])).toBe(true);
    const nested = indent(nodes, [1]);
    expect(nested).toHaveLength(1);
    expect(nested[0]!.children[0]).toMatchObject({ id: "a", kind: "chapter" });
    // A chapter with sections cannot become a section.
    expect(canIndent([ch("x", 1), ch("y", 1, ["y1"])], [1])).toBe(false);
    const back = outdent(nested, [0, 0]);
    expect(back.map((n) => n.id)).toEqual(["p", "a"]);
    expect(back[1]!.kind).toBe("chapter");
  });
});
