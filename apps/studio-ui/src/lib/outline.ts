/**
 * Outline tree editing: pure functions, so every edit is predictable and testable.
 * Node IDs never change here; new nodes get no ID and Core assigns one when the draft is saved.
 * Structure follows Core's rules: parts hold chapters, chapters hold sections, sections hold nothing.
 */

export type NodeKind = "part" | "chapter" | "section" | "front_matter" | "back_matter";

export interface OutlineNode {
  id?: string;
  kind: NodeKind;
  title: string;
  goal: string;
  target_words: number | null;
  locked: boolean;
  notes: string;
  requirements: Record<string, unknown>;
  children: OutlineNode[];
}

/** Address of a node: indexes from the root, e.g. [2, 0] = first child of the third top-level node. */
export type NodePath = number[];

const CHILD: Record<NodeKind, NodeKind | undefined> = {
  part: "chapter",
  chapter: "section",
  section: undefined,
  front_matter: undefined,
  back_matter: undefined,
};

export function newNode(kind: NodeKind, title = "Untitled"): OutlineNode {
  return {
    kind,
    title,
    goal: "",
    target_words: null,
    locked: false,
    notes: "",
    requirements: {},
    children: [],
  };
}

function clone(nodes: OutlineNode[]): OutlineNode[] {
  return structuredClone(nodes);
}

export function lastIndex(path: NodePath): number {
  return path[path.length - 1] ?? 0;
}

function siblingsOf(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  let list = nodes;
  for (const i of path.slice(0, -1)) {
    const n = list[i];
    if (!n) throw new Error("bad outline path");
    list = n.children;
  }
  return list;
}

export function nodeAt(nodes: OutlineNode[], path: NodePath): OutlineNode {
  const n = siblingsOf(nodes, path)[lastIndex(path)];
  if (!n) throw new Error("bad outline path");
  return n;
}

export function siblingCount(nodes: OutlineNode[], path: NodePath): number {
  return siblingsOf(nodes, path).length;
}

export function update(nodes: OutlineNode[], path: NodePath, patch: Partial<OutlineNode>): OutlineNode[] {
  const out = clone(nodes);
  Object.assign(nodeAt(out, path), patch);
  return out;
}

/** Move a node among its siblings (drag-reorder and Up/Down buttons). */
export function move(nodes: OutlineNode[], path: NodePath, to: number): OutlineNode[] {
  const out = clone(nodes);
  const list = siblingsOf(out, path);
  const from = lastIndex(path);
  if (to < 0 || to >= list.length || to === from) return nodes;
  const [item] = list.splice(from, 1);
  if (item) list.splice(to, 0, item);
  return out;
}

export function remove(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  const out = clone(nodes);
  siblingsOf(out, path).splice(lastIndex(path), 1);
  return out;
}

export function insertAfter(nodes: OutlineNode[], path: NodePath | null, node: OutlineNode): OutlineNode[] {
  const out = clone(nodes);
  if (path === null) return [...out, node];
  siblingsOf(out, path).splice(lastIndex(path) + 1, 0, node);
  return out;
}

export function addChild(nodes: OutlineNode[], path: NodePath, node: OutlineNode): OutlineNode[] {
  const out = clone(nodes);
  nodeAt(out, path).children.push(node);
  return out;
}

/** Merge a node with the next sibling of the same kind: the first keeps its ID, words add up. */
export function canMergeNext(nodes: OutlineNode[], path: NodePath): boolean {
  const list = siblingsOf(nodes, path);
  const a = list[lastIndex(path)];
  const b = list[lastIndex(path) + 1];
  return !!a && !!b && a.kind === b.kind && !a.locked && !b.locked;
}

export function mergeNext(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  if (!canMergeNext(nodes, path)) return nodes;
  const out = clone(nodes);
  const list = siblingsOf(out, path);
  const i = lastIndex(path);
  const a = list[i];
  const b = list[i + 1];
  if (!a || !b) return nodes;
  a.title = `${a.title} / ${b.title}`;
  a.goal = [a.goal, b.goal].filter(Boolean).join("\n");
  a.notes = [a.notes, b.notes].filter(Boolean).join("\n");
  a.target_words =
    a.target_words === null && b.target_words === null ? null : (a.target_words ?? 0) + (b.target_words ?? 0);
  a.children = [...a.children, ...b.children];
  list.splice(i + 1, 1);
  return out;
}

/** Split a node in two: the first half of its children stay, the rest go to a new node right after it. */
export function split(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  const out = clone(nodes);
  const list = siblingsOf(out, path);
  const i = lastIndex(path);
  const a = list[i];
  if (!a || a.locked) return nodes;
  const keep = Math.ceil(a.children.length / 2);
  const b: OutlineNode = {
    ...newNode(a.kind, `${a.title} (continued)`),
    children: a.children.slice(keep),
    target_words: a.target_words === null ? null : Math.floor(a.target_words / 2),
    requirements: structuredClone(a.requirements),
  };
  a.children = a.children.slice(0, keep);
  if (a.target_words !== null) a.target_words = a.target_words - (b.target_words ?? 0);
  list.splice(i + 1, 0, b);
  return out;
}

/** Make a node a child of its previous sibling, when that sibling may hold it. */
export function canIndent(nodes: OutlineNode[], path: NodePath): boolean {
  const list = siblingsOf(nodes, path);
  const i = lastIndex(path);
  const item = list[i];
  const prev = list[i - 1];
  if (!item || !prev || item.locked) return false;
  const newKind = CHILD[prev.kind];
  if (!newKind) return false;
  if (newKind === "section") return item.children.length === 0;
  return item.children.every((c) => c.kind === "section");
}

export function indent(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  if (!canIndent(nodes, path)) return nodes;
  const out = clone(nodes);
  const list = siblingsOf(out, path);
  const i = lastIndex(path);
  const [item] = list.splice(i, 1);
  const prev = list[i - 1];
  const newKind = prev ? CHILD[prev.kind] : undefined;
  if (!item || !prev || !newKind) return nodes;
  item.kind = newKind;
  prev.children.push(item);
  return out;
}

/** Move a node out of its parent, to just after the parent. It becomes a chapter (valid at both levels). */
export function canOutdent(nodes: OutlineNode[], path: NodePath): boolean {
  if (path.length < 2) return false;
  const item = nodeAt(nodes, path);
  return !item.locked && item.children.every((c) => c.kind === "section");
}

export function outdent(nodes: OutlineNode[], path: NodePath): OutlineNode[] {
  if (!canOutdent(nodes, path)) return nodes;
  const out = clone(nodes);
  const parentPath = path.slice(0, -1);
  const parentList = siblingsOf(out, parentPath);
  const parent = nodeAt(out, parentPath);
  const [item] = parent.children.splice(lastIndex(path), 1);
  if (!item) return nodes;
  item.kind = "chapter";
  parentList.splice(lastIndex(parentPath) + 1, 0, item);
  return out;
}

export function wordsOf(node: OutlineNode): number {
  return node.target_words ?? node.children.reduce((sum, c) => sum + wordsOf(c), 0);
}

export function flatten(
  nodes: OutlineNode[],
  depth = 0,
  prefix: NodePath = [],
): { node: OutlineNode; depth: number; path: NodePath }[] {
  return nodes.flatMap((n, i) => [
    { node: n, depth, path: [...prefix, i] },
    ...flatten(n.children, depth + 1, [...prefix, i]),
  ]);
}
