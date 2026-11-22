import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { EditorState } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, keymap } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export interface SourceEditorHandle {
  insertBlock(text: string): void;
  focus(): void;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  readOnly: boolean;
  label: string;
  describedBy?: string;
  /** Plain <textarea> mode: same text, no syntax colouring. Some screen-reader users prefer it. */
  plain: boolean;
}

/**
 * Markdown source editor. The text is the canonical BookMD source, so editing is lossless by
 * construction: tables, math, citations, footnotes and figure attributes are never transformed.
 * Tab is NOT captured, so keyboard users can always leave the editor (accessibility).
 */
export const SourceEditor = forwardRef<SourceEditorHandle, Props>(function SourceEditor(
  { value, onChange, onSave, readOnly, label, describedBy, plain },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onSave });
  useEffect(() => {
    callbacks.current = { onChange, onSave };
  }, [onChange, onSave]);

  useImperativeHandle(ref, () => ({
    insertBlock(text: string) {
      if (view.current) {
        const v = view.current;
        const pos = v.state.selection.main.head;
        const before = v.state.doc.sliceString(Math.max(0, pos - 2), pos);
        const prefix = pos === 0 ? "" : before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
        const insert = `${prefix}${text}\n\n`;
        v.dispatch({ changes: { from: pos, insert }, selection: { anchor: pos + insert.length } });
        v.focus();
      } else if (textarea.current) {
        const t = textarea.current;
        const pos = t.selectionStart ?? t.value.length;
        const next = `${t.value.slice(0, pos)}\n\n${text}\n\n${t.value.slice(pos)}`;
        callbacks.current.onChange(next);
        t.focus();
      }
    },
    focus() {
      (view.current ?? textarea.current)?.focus();
    },
  }));

  useEffect(() => {
    if (plain || !host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          drawSelection(),
          highlightActiveLine(),
          highlightSelectionMatches(),
          markdown(),
          syntaxHighlighting(bookHighlight),
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          keymap.of([
            { key: "Mod-s", preventDefault: true, run: () => (callbacks.current.onSave(), true) },
            ...defaultKeymap,
            ...historyKeymap,
            ...searchKeymap,
          ]),
          EditorView.contentAttributes.of({
            "aria-label": label,
            ...(describedBy ? { "aria-describedby": describedBy } : {}),
            spellcheck: "true",
            autocorrect: "on",
          }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) callbacks.current.onChange(u.state.doc.toString());
          }),
          editorTheme,
        ],
      }),
    });
    view.current = v;
    return () => {
      v.destroy();
      view.current = null;
    };
    // Rebuild only when the mode or read-only state changes; text updates flow through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plain, readOnly, label, describedBy]);

  // Apply external changes (draft recovery, restore, conflict resolution) without losing the cursor.
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  if (plain) {
    return (
      <textarea
        ref={textarea}
        className="plain-editor"
        aria-label={label}
        aria-describedby={describedBy}
        value={value}
        readOnly={readOnly}
        spellCheck
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
            e.preventDefault();
            onSave();
          }
        }}
      />
    );
  }
  return <div ref={host} className="source-editor" data-readonly={readOnly} />;
});

const bookHighlight = HighlightStyle.define([
  { tag: tags.heading, fontWeight: "700", color: "var(--ink)" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strong, fontWeight: "700" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: [tags.link, tags.url], color: "var(--cloth)" },
  { tag: [tags.monospace, tags.processingInstruction], fontFamily: "ui-monospace, Consolas, monospace" },
  { tag: [tags.meta, tags.comment, tags.punctuation, tags.contentSeparator], color: "var(--ink-soft)" },
  { tag: tags.quote, color: "var(--ink-soft)", fontStyle: "italic" },
]);

const editorTheme = EditorView.theme({
  "&": {
    backgroundColor: "var(--leaf)",
    color: "var(--ink)",
    border: "1px solid var(--rule)",
    borderRadius: "6px",
  },
  "&.cm-focused": { outline: "3px solid var(--focus)", outlineOffset: "2px" },
  ".cm-content": {
    fontFamily: "var(--font-text)",
    fontSize: "1.0625rem",
    lineHeight: "1.7",
    padding: "1.25rem 1.5rem",
    minHeight: "60vh",
    caretColor: "var(--ink)",
  },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--leaf-sunk) 55%, transparent)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "color-mix(in srgb, var(--focus) 25%, transparent) !important",
  },
  ".cm-cursor": { borderLeftColor: "var(--ink)" },
});
