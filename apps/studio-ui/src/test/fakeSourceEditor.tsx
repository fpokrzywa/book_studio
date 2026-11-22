import { forwardRef, useImperativeHandle, useRef } from "react";

/** jsdom has no layout engine for CodeMirror; unit tests use this textarea with the same contract. */
export const FakeSourceEditor = forwardRef<
  { insertBlock(text: string): void; focus(): void },
  {
    value: string;
    onChange: (v: string) => void;
    onSave: () => void;
    readOnly: boolean;
    label: string;
    describedBy?: string;
  }
>(function FakeSourceEditor({ value, onChange, onSave, readOnly, label, describedBy }, ref) {
  const el = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({
    insertBlock: (text: string) => onChange(`${value}\n\n${text}\n\n`),
    focus: () => el.current?.focus(),
  }));
  return (
    <textarea
      ref={el}
      aria-label={label}
      aria-describedby={describedBy}
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          onSave();
        }
      }}
    />
  );
});
