import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  citationAnchorId,
  citationIdFromHref,
  isCitationHref,
  linkifyCitations,
  remarkCitationLinks,
} from "@/lib/chat/citation-anchors";

/**
 * The mdast is built by hand rather than parsed. `remark-parse` is only a transitive dependency
 * here, and a literal tree states exactly what the plugin is being given — which is the thing
 * these assertions are about.
 */
const text = (value: string) => ({ type: "text", value });
const paragraph = (...children: { type: string; value?: string }[]) => ({
  type: "root",
  children: [{ type: "paragraph", children }],
});

const run = (tree: ReturnType<typeof paragraph>, ids: string[]) => {
  linkifyCitations(tree, { prefix: "turn-3", resolvable: new Set(ids) });
  return tree.children[0].children as {
    type: string;
    value?: string;
    url?: string;
    children?: { value?: string }[];
  }[];
};

describe("linkifyCitations", () => {
  test("links a handle to its source entry and keeps the surrounding text", () => {
    const children = run(paragraph(text("Costs rose [C1]. Margins held [C4].")), ["C1", "C4"]);

    assert.deepEqual(
      children.map((node) => node.type),
      ["text", "link", "text", "link", "text"],
    );
    assert.equal(children[1].url, `#${citationAnchorId("turn-3", "C1")}`);
    assert.equal(children[1].children?.[0].value, "[C1]");
    assert.equal(children[2].value, ". Margins held ");
    assert.equal(children[3].url, `#${citationAnchorId("turn-3", "C4")}`);
  });

  test("a handle that resolves to nothing stays plain text", () => {
    // The backend flags a fabricated handle rather than removing it; rendering it as a link
    // would offer provenance that does not exist and look identical to a verified citation.
    const children = run(paragraph(text("Revenue doubled [C99].")), ["C1"]);

    assert.deepEqual(children, [text("Revenue doubled [C99].")]);
  });

  test("handles run together, as the model writes them", () => {
    // Answers routinely end a sentence with `[C1][C4][C5][C6]`, with no separator at all.
    const children = run(paragraph(text("...enforcement intensifies[C1][C4][C5].")), [
      "C1",
      "C4",
      "C5",
    ]);

    assert.deepEqual(
      children.filter((node) => node.type === "link").map((node) => node.url),
      ["C1", "C4", "C5"].map((id) => `#${citationAnchorId("turn-3", id)}`),
    );
    // No text is dropped or duplicated in the split.
    assert.equal(
      children
        .map((node) => node.value ?? node.children?.[0].value ?? "")
        .join(""),
      "...enforcement intensifies[C1][C4][C5].",
    );
  });

  test("descends into nested nodes but leaves code alone", () => {
    const tree = {
      type: "root",
      children: [
        {
          type: "paragraph",
          children: [
            { type: "strong", children: [text("Bold [C1]")] },
            { type: "inlineCode", value: "grep [C1]" },
          ],
        },
      ],
    };
    linkifyCitations(tree, { prefix: "turn-0", resolvable: new Set(["C1"]) });

    const [strong, code] = tree.children[0].children as {
      type: string;
      value?: string;
      children?: { type: string }[];
    }[];
    assert.deepEqual(
      strong.children?.map((node) => node.type),
      ["text", "link"],
    );
    assert.equal(code.value, "grep [C1]", "a code span is quoted verbatim");
  });

  test("a turn with no citations is left exactly as it was", () => {
    const tree = paragraph(text("Nothing was retrieved [C1]."));
    const before = JSON.stringify(tree);
    linkifyCitations(tree, { prefix: "turn-1", resolvable: new Set() });
    assert.equal(JSON.stringify(tree), before);
  });
});

describe("anchor ids", () => {
  test("are namespaced per turn, because every answer numbers from C1", () => {
    assert.notEqual(citationAnchorId("turn-0", "C3"), citationAnchorId("turn-2", "C3"));
  });

  test("round-trip through the href the plugin writes", () => {
    const href = `#${citationAnchorId("turn-7", "C12")}`;
    assert.ok(isCitationHref(href));
    assert.equal(citationIdFromHref(href), "C12");
  });

  test("an ordinary link is not mistaken for a citation", () => {
    for (const href of ["https://sec.gov/filing", "#section-heading", undefined]) {
      assert.equal(isCitationHref(href), false, `${href} should not read as a citation link`);
      assert.equal(citationIdFromHref(href), null);
    }
  });
});

describe("remarkCitationLinks", () => {
  test("is an attacher, not a transformer", () => {
    // unified calls a plugin with no arguments and uses what it returns to transform the tree.
    // Returning the transformer directly type-checks and then throws inside react-markdown,
    // which is how this shipped the first time.
    const tree = paragraph(text("Costs rose [C1]."));
    const transform = remarkCitationLinks({ prefix: "turn-0", resolvable: new Set(["C1"]) })();

    transform(tree);

    assert.deepEqual(
      tree.children[0].children.map((node: { type: string }) => node.type),
      ["text", "link", "text"],
    );
  });
});
