/**
 * Turning the `[C1]` handles inside an answer into links to the source they name.
 *
 * The handles are the citation contract made visible, but as plain text they ask the reader to
 * do the join themselves — scroll to the panel, scan for `[C12]`, scroll back. An answer that
 * cites seven passages in one sentence makes that unreasonable, so each handle links to its
 * entry.
 *
 * Two rules matter more than the convenience:
 *
 * 1. **A handle is only linked if it resolves.** A fabricated `[C99]` stays plain text.
 *    Rendering it as a link would offer provenance that does not exist, which is precisely the
 *    failure the backend's citation check exists to catch — and it would look identical to a
 *    verified one.
 * 2. **The id shape lives here, once.** The link and the element it points at are written by
 *    two different components; if each spelled the id itself they could drift into a link that
 *    scrolls nowhere, silently.
 */

/** The DOM id of one source entry. `prefix` scopes it to a single turn, since every answer in a conversation numbers its handles from C1. */
export function citationAnchorId(prefix: string, citationId: string): string {
  return `${prefix}-cite-${citationId}`;
}

/** `#…` hrefs this module produces, so the link renderer can tell them from a real URL. */
export function isCitationHref(href: string | undefined): boolean {
  return typeof href === "string" && href.startsWith("#") && href.includes("-cite-");
}

/** The citation id a handle link points at, or null if it isn't one of ours. */
export function citationIdFromHref(href: string | undefined): string | null {
  if (!isCitationHref(href)) return null;
  return href!.slice(href!.lastIndexOf("-cite-") + "-cite-".length) || null;
}

// --- the remark plugin -------------------------------------------------------------------

/**
 * Minimal mdast shapes. Typed locally rather than pulled from `@types/mdast`: this plugin
 * touches text and link nodes and nothing else, and a hand-written type that says so is easier
 * to check than a generic one that permits everything.
 */
type MdastNode = {
  type: string;
  value?: string;
  url?: string;
  children?: MdastNode[];
};

const HANDLE = /\[(C\d+)\]/g;

/**
 * Node types whose text must be left alone: code is quoted verbatim, and a handle inside an
 * existing link cannot be wrapped in a second one.
 */
const OPAQUE = new Set(["code", "inlineCode", "link", "linkReference", "definition"]);

export type CitationLinkOptions = {
  prefix: string;
  /** Citation ids that were actually retrieved. Anything else stays plain text. */
  resolvable: ReadonlySet<string>;
};

/**
 * The plugin, in the shape unified expects: an **attacher**, called once with no arguments,
 * returning the transformer that receives the tree.
 *
 * The distinction is not pedantic. This first shipped as a factory returning the transformer
 * directly, which type-checked, passed its unit tests against hand-built trees, and threw
 * `Cannot read properties of undefined` the first time it ran inside react-markdown — unified
 * had called the transformer as the attacher, with no tree. The transform itself is exported
 * separately so tests exercise it without going through unified.
 */
export function remarkCitationLinks(options: CitationLinkOptions) {
  return () => (tree: MdastNode) => linkifyCitations(tree, options);
}

/**
 * Replaces each resolvable `[Cn]` in the tree with a link to its source entry, in place.
 *
 * Written as a plain tree walk rather than with `unist-util-visit` to avoid adding a
 * dependency for one recursion — and because replacing a text node with several siblings is
 * the awkward case for a visitor anyway.
 */
export function linkifyCitations(
  tree: MdastNode,
  { prefix, resolvable }: CitationLinkOptions,
): void {
  if (resolvable.size) walk(tree);

  function walk(node: MdastNode): void {
    if (!node.children?.length) return;

    const rewritten: MdastNode[] = [];
    let changed = false;

    for (const child of node.children) {
      if (child.type === "text" && child.value) {
        const parts = split(child.value);
        if (parts) {
          rewritten.push(...parts);
          changed = true;
          continue;
        }
      } else if (!OPAQUE.has(child.type)) {
        walk(child);
      }
      rewritten.push(child);
    }

    if (changed) node.children = rewritten;
  }

  /** Text split into alternating text and link nodes, or null when nothing here resolves. */
  function split(value: string): MdastNode[] | null {
    const parts: MdastNode[] = [];
    let cursor = 0;

    for (const match of value.matchAll(HANDLE)) {
      const id = match[1];
      if (!resolvable.has(id)) continue;

      const at = match.index ?? 0;
      if (at > cursor) parts.push({ type: "text", value: value.slice(cursor, at) });
      parts.push({
        type: "link",
        url: `#${citationAnchorId(prefix, id)}`,
        children: [{ type: "text", value: match[0] }],
      });
      cursor = at + match[0].length;
    }

    if (!parts.length) return null;
    if (cursor < value.length) parts.push({ type: "text", value: value.slice(cursor) });
    return parts;
  }
}
