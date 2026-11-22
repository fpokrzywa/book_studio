import type { ChapterStatus, ProjectType, PublicationFormat } from "../api/client";

export const PROJECT_TYPES: { value: ProjectType; label: string }[] = [
  { value: "nonfiction", label: "Nonfiction" },
  { value: "technical", label: "Technical book" },
  { value: "course", label: "Course or manual" },
  { value: "workbook", label: "Workbook" },
  { value: "memoir", label: "Memoir" },
  { value: "fiction", label: "Fiction" },
  { value: "serial", label: "Serialized fiction" },
];

export const FORMATS: { value: PublicationFormat; label: string }[] = [
  { value: "ebook", label: "Ebook" },
  { value: "paperback", label: "Paperback" },
  { value: "hardcover", label: "Hardcover" },
];

export const CHAPTER_STATUSES: { value: ChapterStatus; label: string }[] = [
  { value: "planned", label: "Planned" },
  { value: "draft", label: "Draft" },
  { value: "in_review", label: "In review" },
  { value: "approved", label: "Approved" },
];

export function typeLabel(t: ProjectType): string {
  return PROJECT_TYPES.find((x) => x.value === t)?.label ?? t;
}

export function formatList(formats: PublicationFormat[]): string {
  if (formats.length === 0) return "Not chosen yet";
  return formats.map((f) => FORMATS.find((x) => x.value === f)?.label ?? f).join(", ");
}

export function statusLabel(s: ChapterStatus): string {
  return CHAPTER_STATUSES.find((x) => x.value === s)?.label ?? s;
}

const numberFmt = new Intl.NumberFormat();
export function n(value: number): string {
  return numberFmt.format(value);
}

export function words(count: number): string {
  return `${n(count)} ${count === 1 ? "word" : "words"}`;
}

export function progress(count: number, target: number | null | undefined): number | null {
  if (!target) return null;
  return Math.min(1, count / target);
}

export function languageName(tag: string): string {
  try {
    const name = new Intl.DisplayNames(undefined, { type: "language" }).of(tag);
    return name ? `${name} (${tag})` : tag;
  } catch {
    return tag;
  }
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const steps: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function absoluteTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function spineVar(t: ProjectType): string {
  return `var(--cloth-${t})`;
}
