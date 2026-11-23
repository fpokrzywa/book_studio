import { useId, useState } from "react";
import {
  addChild,
  canIndent,
  canMergeNext,
  canOutdent,
  flatten,
  lastIndex,
  siblingCount,
  indent,
  insertAfter,
  mergeNext,
  move,
  newNode,
  outdent,
  remove,
  split,
  update,
  wordsOf,
  type NodePath,
  type OutlineNode,
} from "../../lib/outline";

const KIND_LABEL: Record<OutlineNode["kind"], string> = {
  part: "Part",
  chapter: "Chapter",
  section: "Section",
  front_matter: "Front matter",
  back_matter: "Back matter",
};

/** Edit an outline tree: reorder (drag or buttons), nest, merge, split, lock, set goals and targets. */
export function OutlineEditor({
  nodes,
  onChange,
  fiction,
  wordsPerHour,
}: {
  nodes: OutlineNode[];
  onChange: (n: OutlineNode[]) => void;
  fiction: boolean;
  wordsPerHour: number;
}) {
  const [drag, setDrag] = useState<NodePath | null>(null);
  const rows = flatten(nodes);
  const total = nodes.reduce((sum, n) => sum + wordsOf(n), 0);
  return (
    <div className="outline-editor">
      <p className="hint" aria-live="polite">
        {rows.filter((r) => r.node.kind === "chapter").length} chapters, {total.toLocaleString()} target
        words, about {(total / Math.max(1, wordsPerHour)).toFixed(1)} hours of drafting at {wordsPerHour}{" "}
        words per hour (estimate). Drag a row by its handle, or use the buttons, to reorder.
      </p>
      <ol className="outline-rows">
        {rows.map(({ node, depth, path }) => (
          <OutlineRow
            key={path.join("-")}
            node={node}
            depth={depth}
            path={path}
            nodes={nodes}
            onChange={onChange}
            fiction={fiction}
            dragging={drag}
            onDragStart={() => setDrag(path)}
            onDrop={() => {
              if (
                drag &&
                drag.length === path.length &&
                drag.slice(0, -1).join() === path.slice(0, -1).join()
              ) {
                onChange(move(nodes, drag, lastIndex(path)));
              }
              setDrag(null);
            }}
          />
        ))}
      </ol>
      <div className="page-actions">
        <button
          type="button"
          className="btn btn-small"
          onClick={() => onChange(insertAfter(nodes, null, newNode("chapter", "New chapter")))}
        >
          Add chapter
        </button>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => onChange(insertAfter(nodes, null, newNode("part", "New part")))}
        >
          Add part
        </button>
      </div>
    </div>
  );
}

function OutlineRow({
  node,
  depth,
  path,
  nodes,
  onChange,
  fiction,
  dragging,
  onDragStart,
  onDrop,
}: {
  node: OutlineNode;
  depth: number;
  path: NodePath;
  nodes: OutlineNode[];
  onChange: (n: OutlineNode[]) => void;
  fiction: boolean;
  dragging: NodePath | null;
  onDragStart: () => void;
  onDrop: () => void;
}) {
  const id = useId();
  const i = lastIndex(path);
  const siblings = siblingCount(nodes, path);
  const req = node.requirements as Record<string, unknown>;
  const list = (k: string) => ((req[k] as string[] | undefined) ?? []).join("\n");
  const setList = (k: string, v: string) =>
    onChange(
      update(nodes, path, {
        requirements: {
          ...req,
          [k]: v
            .split("\n")
            .map((x) => x.trim())
            .filter(Boolean),
        },
      }),
    );
  const label = `${KIND_LABEL[node.kind]} ${node.title}`;
  return (
    // Drag-and-drop is a mouse shortcut; the Up/Down/Indent/Outdent buttons are the keyboard path.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="outline-row"
      data-kind={node.kind}
      data-locked={node.locked}
      style={{ marginLeft: `${depth * 1.5}rem` }}
      onDragOver={(e) => dragging && e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        onDrop();
      }}
    >
      <div className="outline-line">
        <span
          className="drag-handle"
          draggable={!node.locked}
          onDragStart={onDragStart}
          aria-hidden="true"
          title="Drag to reorder"
        >
          ⠿
        </span>
        <span className="tag">{KIND_LABEL[node.kind]}</span>
        <label className="visually-hidden" htmlFor={`${id}-title`}>
          Title of {KIND_LABEL[node.kind].toLowerCase()} {i + 1}
        </label>
        <input
          id={`${id}-title`}
          className="outline-title"
          value={node.title}
          readOnly={node.locked}
          onChange={(e) => onChange(update(nodes, path, { title: e.target.value }))}
        />
        <label className="visually-hidden" htmlFor={`${id}-words`}>
          Target words for {label}
        </label>
        <input
          id={`${id}-words`}
          className="outline-words"
          type="number"
          min={0}
          placeholder={String(wordsOf(node) || "words")}
          value={node.target_words ?? ""}
          readOnly={node.locked}
          onChange={(e) =>
            onChange(
              update(nodes, path, { target_words: e.target.value === "" ? null : Number(e.target.value) }),
            )
          }
        />
        <label className="inline-check">
          <input
            type="checkbox"
            checked={node.locked}
            onChange={(e) => onChange(update(nodes, path, { locked: e.target.checked }))}
          />
          Lock
        </label>
      </div>
      <div className="outline-tools" role="group" aria-label={`Arrange ${label}`}>
        <button
          type="button"
          className="btn btn-small"
          disabled={i === 0}
          onClick={() => onChange(move(nodes, path, i - 1))}
        >
          Up
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={i >= siblings - 1}
          onClick={() => onChange(move(nodes, path, i + 1))}
        >
          Down
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={!canIndent(nodes, path)}
          onClick={() => onChange(indent(nodes, path))}
        >
          Indent
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={!canOutdent(nodes, path)}
          onClick={() => onChange(outdent(nodes, path))}
        >
          Outdent
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={!canMergeNext(nodes, path)}
          onClick={() => onChange(mergeNext(nodes, path))}
        >
          Merge with next
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={node.locked}
          onClick={() => onChange(split(nodes, path))}
        >
          Split
        </button>
        {node.kind === "chapter" ? (
          <button
            type="button"
            className="btn btn-small"
            onClick={() => onChange(addChild(nodes, path, newNode("section", "New section")))}
          >
            Add section
          </button>
        ) : null}
        {node.kind === "part" ? (
          <button
            type="button"
            className="btn btn-small"
            onClick={() => onChange(addChild(nodes, path, newNode("chapter", "New chapter")))}
          >
            Add chapter
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-small btn-danger"
          disabled={node.locked}
          onClick={() => onChange(remove(nodes, path))}
        >
          Remove
        </button>
      </div>
      <details>
        <summary>Goal and requirements</summary>
        <div className="field">
          <label htmlFor={`${id}-goal`}>Goal for the reader</label>
          <textarea
            id={`${id}-goal`}
            rows={2}
            value={node.goal}
            readOnly={node.locked}
            onChange={(e) => onChange(update(nodes, path, { goal: e.target.value }))}
          />
        </div>
        {node.kind === "chapter" ? (
          fiction ? (
            <div className="form-row">
              {(
                [
                  ["plot_points", "Plot points (one per line)"],
                  ["characters", "Characters who appear"],
                  ["continuity", "Continuity to keep"],
                ] as const
              ).map(([k, l]) => (
                <div className="field" key={k}>
                  <label htmlFor={`${id}-${k}`}>{l}</label>
                  <textarea
                    id={`${id}-${k}`}
                    rows={3}
                    value={list(k)}
                    readOnly={node.locked}
                    onChange={(e) => setList(k, e.target.value)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="form-row">
              <div className="field">
                <label htmlFor={`${id}-cites`}>Sources to cite (at least)</label>
                <input
                  id={`${id}-cites`}
                  type="number"
                  min={0}
                  max={50}
                  value={Number(req.citations_min ?? 0)}
                  readOnly={node.locked}
                  onChange={(e) =>
                    onChange(
                      update(nodes, path, {
                        requirements: { ...req, citations_min: Number(e.target.value) },
                      }),
                    )
                  }
                />
              </div>
              <div className="field">
                <label htmlFor={`${id}-notes`}>Requirements (one per line)</label>
                <textarea
                  id={`${id}-notes`}
                  rows={3}
                  value={list("notes")}
                  readOnly={node.locked}
                  onChange={(e) => setList("notes", e.target.value)}
                />
              </div>
            </div>
          )
        ) : null}
      </details>
    </li>
  );
}
