"""Assembled book -> Typst source -> print-ready interior PDF.

Print rules: page = trim size (no bleed: PBS places no full-bleed art in the interior), mirrored
margins with the KDP minimum gutter for the final page count, chapters opening on a right-hand page
when the template says so, even page numbers on left pages, running heads, a table of contents, numbered
captions shared with every other format, and fonts embedded from Typst's built-in, freely licensed set.

Print has no live links, bookmarks or annotations (KDP asks for none): a web link prints its address
after the link text, and cross-references print as text. Equations Typst cannot take are printed as
LaTeX source and listed in the report.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import typst

from pbs_core.document.bookmd import SAFE_LINK_SCHEMES, inline_text
from pbs_core.publishing import kdp_rules
from pbs_core.publishing.book import Book, BookChapter, MatterItem
from pbs_core.publishing.fidelity import _title_heading
from pbs_core.publishing.latex_typst import UnsupportedMath, to_typst


class LayoutError(RuntimeError):
    """Typst rejected the generated layout (a PBS bug or unsupported content); reported, never hidden."""


_ESC = re.compile(r"([\\#$*_`<>@\[\]~/=+\-\"'])")
_LABEL_OK = re.compile(r"[^A-Za-z0-9_\-:.]")
MAX_PASSES = 4


def esc(text: str) -> str:
    return _ESC.sub(r"\\\1", text)


def s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def label(raw: str) -> str:
    return "<" + _LABEL_OK.sub("-", raw) + ">"


@dataclass
class Stats:
    equations: int = 0
    equations_as_source: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    broken_refs: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    dropped_title_headings: int = 0


class _W:
    def __init__(self, book: Book, text_width_in: Decimal) -> None:
        self.book = book
        self.t = book.template
        self.text_width_in = text_width_in
        self.stats = Stats()
        self.anchors: set[str] = set()
        self.chapter_notes: list[str] = []
        self.book_notes: list[tuple[str, list[str]]] = []
        self.notes_mode = "endnotes_book" if book.matter("endnotes") else self.t["notes"]
        self.cur_footnotes: dict[str, list[dict[str, Any]]] = {}
        self.cur_order: list[str] = []
        self.prefix = ""
        for ch in book.chapters:
            self.anchors.add(f"ch-{ch.slug}")
            if ch.doc:
                for b in _walk(ch.doc.get("blocks", [])):
                    a = b.get("attrs", {}).get("id")
                    if a:
                        self.anchors.add(f"{ch.slug}-{a}")

    # ----- inline -----
    def inl(self, nodes: list[dict[str, Any]]) -> str:
        return "".join(self.node(n) for n in nodes)

    def node(self, n: dict[str, Any]) -> str:
        t = n["t"]
        if t == "text":
            return esc(n["v"])
        if t == "softbreak":
            return " "
        if t == "hardbreak":
            return "#linebreak()"
        if t == "code":
            return f"#raw({s(n['v'])})"
        if t == "math":
            return self.math(n["tex"], display=False)
        if t == "emph":
            return f"#emph[{self.inl(n['c'])}]"
        if t == "strong":
            return f"#strong[{self.inl(n['c'])}]"
        if t == "strike":
            return f"#strike[{self.inl(n['c'])}]"
        if t == "link":
            href, inner = n["href"], self.inl(n["c"])
            if href.startswith("#"):
                key = f"{self.prefix}{href[1:]}"
                known = key in self.anchors or href[1:] in self.anchors
                if not known and not any(f"{c.slug}-{href[1:]}" in self.anchors for c in self.book.chapters):
                    self.stats.broken_refs.append(href)
                return inner  # print: a cross-reference is plain text
            if not href.lower().startswith(SAFE_LINK_SCHEMES):
                self.stats.unsupported.append(f"unsafe link removed: {href[:60]}")
                return inner
            self.stats.links.append(href)
            shown = inline_text(n["c"]).strip()
            addr = href.removeprefix("mailto:")
            return inner if shown in (addr, href) else f"{inner} ({esc(addr)})"
        if t == "image":
            return self.image(n["src"], n.get("alt") or inline_text(n["c"]), inline=True)
        if t == "cite":
            return esc("(" + "; ".join(self.book.cite_label(i) for i in n["items"]) + ")")
        if t == "footnote_ref":
            return self.footnote(n["label"])
        return esc(str(n.get("v", "")))

    def footnote(self, lbl: str) -> str:
        body_blocks = self.cur_footnotes.get(lbl)
        if body_blocks is None:
            self.stats.unsupported.append(f"footnote [^{lbl}] has no text")
            return esc(f"[^{lbl}]")
        body = " ".join(self.inl(b.get("inlines", [])) for b in body_blocks if b.get("type") == "paragraph")
        if self.notes_mode == "footnotes":
            return f"#footnote[{body}]"
        if lbl not in self.cur_order:
            self.cur_order.append(lbl)
            self.chapter_notes.append(body)
        return f"#super[{self.cur_order.index(lbl) + 1}]"

    def math(self, tex: str, *, display: bool) -> str:
        self.stats.equations += 1
        try:
            body = to_typst(tex).strip()
            if not body:
                raise UnsupportedMath("empty")
        except UnsupportedMath:
            self.stats.equations_as_source.append(tex)
            if display:
                return f'#align(center)[#raw({s(tex)}, lang: "latex")]'
            return f"#raw({s(tex)})"
        return f"$ {body} $" if display else f"${body}$"

    def image(self, src: str, alt: str, *, inline: bool = False) -> str:
        if not src.startswith("asset:"):
            self.stats.unsupported.append(f"web image not embedded: {src[:60]}")
            return esc(f"[image not included: {src[:60]}]")
        a = self.book.assets.get(src[6:])
        if a is None:
            return esc("[missing image]")
        # Never print below 300 DPI: the image is at most its pixel width / 300 inches wide.
        natural = Decimal(a.width_px or 600) / Decimal(kdp_rules.MIN_IMAGE_DPI)
        width = min(natural, self.text_width_in)
        dpi = int(Decimal(a.width_px or 0) / width) if a.width_px else None
        self.stats.images.append({"asset": a.short_hash, "placed_width_in": str(round(width, 3)), "effective_dpi": dpi})
        size = "height: 1em" if inline else f"width: {round(float(width), 3)}in"
        return f'#image("assets/{a.short_hash}.{a.ext}", {size}, alt: {s(alt)})'

    # ----- blocks -----
    def blocks(self, items: list[dict[str, Any]]) -> str:
        return "\n\n".join(x for x in (self.block(b) for b in items) if x)

    def cap(self, b: dict[str, Any], caption: str) -> str:
        lbl = self.book.labels.get(b.get("id", ""))
        return f"[{esc(lbl + ': ') if lbl else ''}{caption}]"

    def block(self, b: dict[str, Any]) -> str:
        t = b["type"]
        anchor = b.get("attrs", {}).get("id")
        tag = f" {label(self.prefix + anchor)}" if anchor else ""
        if t == "heading":
            lvl = min(b["level"] + 1, 6)
            return f"#heading(level: {lvl}, outlined: {str(lvl <= self.t['toc_depth']).lower()})[{self.inl(b['inlines'])}]{tag}"
        if t == "paragraph":
            return self.index_marks(b) + self.inl(b["inlines"])
        if t == "thematic_break":
            return "#align(center)[#sym.ast.op #h(1em) #sym.ast.op #h(1em) #sym.ast.op]"
        if t == "code":
            lang = b.get("lang") or ""
            caption = b.get("attrs", {}).get("kv", {}).get("caption")
            code = f"#raw({s(b['text'])}, block: true{', lang: ' + s(lang) if lang else ''})"
            if caption:
                return f"#figure({code[1:]}, caption: {self.cap(b, esc(caption))}, kind: raw, numbering: none, supplement: none){tag}"
            return code + tag
        if t == "math_block":
            return self.math(b["tex"], display=True) + tag
        if t == "quote":
            return f"#quote(block: true)[{self.blocks(b['blocks'])}]{tag}"
        if t == "list":
            items = []
            for item in b["items"]:
                box = ("☑ " if item["checked"] else "☐ ") if "checked" in item else ""
                items.append(f"[{box}{self.blocks(item['blocks'])}]")
            if b["ordered"]:
                return (
                    f"#enum(start: {b.get('start', 1)}, tight: {str(b.get('tight', True)).lower()}, {', '.join(items)})"
                )
            return f"#list(tight: {str(b.get('tight', True)).lower()}, {', '.join(items)})"
        if t == "table":
            n = max(len(b["head"]), max((len(r) for r in b["rows"]), default=0), 1)
            aligns = ", ".join(
                {"left": "left", "right": "right", "center": "center"}.get(a or "", "auto")
                for a in (b["align"] + [None] * n)[:n]
            )
            head = ", ".join(f"[#strong[{self.inl(c)}]]" for c in b["head"])
            rows = ", ".join(f"[{self.inl(c)}]" for r in b["rows"] for c in (r + [[]] * n)[:n])
            tbl = f"table(columns: {n}, align: ({aligns},), stroke: 0.5pt, inset: 4pt, table.header({head}), {rows})"
            caption = self.cap(b, self.inl(b["caption"])) if b.get("caption") else "none"
            return f"#figure({tbl}, caption: {caption}, kind: table, numbering: none, supplement: none){tag}"
        if t == "figure":
            alt = b.get("alt") if b.get("alt") is not None else inline_text(b["caption"])
            img = self.image(b["src"], alt or "")[1:]
            caption = self.cap(b, self.inl(b["caption"])) if b.get("caption") else "none"
            return f"#figure({img}, caption: {caption}, numbering: none, supplement: none){tag}"
        if t == "div":
            return self.blocks(b["blocks"])
        if t == "unsupported":
            self.stats.unsupported.append("unsupported block printed as written")
            return f"#raw({s(b['raw'])}, block: true)"
        self.stats.unsupported.append(f"unknown block type {t}")
        return ""

    def index_marks(self, b: dict[str, Any]) -> str:
        if not self.book.index_terms:
            return ""
        text = inline_text(b.get("inlines", [])).lower()
        marks = [
            f"#metadata({s(term)})<pbs-index>"
            for term in self.book.index_terms
            if re.search(rf"\b{re.escape(term.lower())}\b", text)
        ]
        return "".join(marks)

    # ----- chapters and matter -----
    def chapter(self, ch: BookChapter) -> str:
        self.prefix = f"{ch.slug}-"
        self.cur_footnotes = dict((ch.doc or {}).get("footnotes", {}))
        self.cur_order, self.chapter_notes = [], []
        blocks = list((ch.doc or {}).get("blocks", []))
        if _title_heading(blocks, ch.title):
            blocks = blocks[1:]
            self.stats.dropped_title_headings += 1
        opener = '#pagebreak(to: "odd", weak: true)' if self.t["chapter_opens"] == "recto" else "#pagebreak(weak: true)"
        word = self.t["chapter_label"]
        lead = f"{word} {ch.number}" if (word and ch.number) else ""
        if ch.depth > 0:
            head = f"#heading(level: {min(ch.depth + 1, 6)}, outlined: {str(ch.depth < self.t['toc_depth']).lower()})[{esc(ch.title)}] {label('ch-' + ch.slug)}"
            return head + "\n\n" + self.blocks(blocks) + self.notes_section()
        out = [opener, f"#pbs-chapter({s(lead)})[{esc(ch.title)}] {label('ch-' + ch.slug)}", self.blocks(blocks)]
        return "\n\n".join(out) + self.notes_section(ch.title) + '\n\n#metadata("end")<pbs-end>'

    def notes_section(self, title: str = "") -> str:
        if not self.chapter_notes:
            return ""
        if self.notes_mode == "endnotes_book":
            self.book_notes.append((title, list(self.chapter_notes)))
            return ""
        items = ", ".join(f"[{n}]" for n in self.chapter_notes)
        return f'\n\n#v(1em)#text(weight: "bold")[Notes]\n#enum({items})'

    def matter_item(self, m: MatterItem) -> str:
        k = m.kind
        b = self.book
        if k == "half_title":
            return f"#page(header: none, footer: none)[#v(30%)#align(center)[#text(size: 20pt)[{esc(b.title)}]]]"
        if k == "title_page":
            lines = [f'#text(size: 28pt, weight: "bold")[{esc(b.title)}]']
            if b.subtitle:
                lines.append(f"#v(0.5em)#text(size: 16pt)[{esc(b.subtitle)}]")
            if b.author:
                lines.append(f"#v(3em)#text(size: 14pt)[{esc(b.author)}]")
            return "#page(header: none, footer: none)[#v(25%)#align(center)[" + "\n".join(lines) + "]]"
        if k == "copyright":
            c = b.copyright
            parts = []
            if (c.get("notice_md") or "").strip():
                parts.append(self.markdown_blocks(m, c["notice_md"]))
            elif c.get("holder") or c.get("year"):
                parts.append(
                    esc(f"Copyright © {c.get('year') or ''} {c.get('holder') or ''}".replace("  ", " ").strip())
                )
            if c.get("edition"):
                parts.append(esc(str(c["edition"])))
            if c.get("isbn"):
                parts.append(esc(f"ISBN {c['isbn']}"))
            return "#page(header: none, footer: none)[#set text(size: 9pt)\n#v(1fr)\n" + "\n\n".join(parts) + "]"
        if k in ("dedication", "epigraph"):
            return (
                f"#page(header: none, footer: none)[#v(25%)#align(center)[#emph[{self.markdown_blocks(m, m.body_md)}]]]"
            )
        if k == "toc":
            return (
                f"#pagebreak(weak: true)\n#outline(title: [{esc(m.title)}], depth: {self.t['toc_depth']}, indent: auto)"
            )
        if k == "glossary":
            items = ", ".join(f"terms.item[{esc(t)}][{esc(d)}]" for t, d in b.glossary)
            return self.unnumbered(m.title, f"#terms({items})")
        if k == "bibliography":
            rows = []
            for key in b.cited_keys:
                e = b.bibliography.get(key)
                if e is None:
                    rows.append(f"[{esc(key)} (no details entered)]")
                    continue
                bits = [", ".join(e.authors)] if e.authors else []
                bits.append(f"({e.year})" if e.year else "")
                bits.append(f"#emph[{esc(e.title)}].")
                if e.publisher:
                    bits.append(esc(e.publisher) + ".")
                if e.doi:
                    bits.append(esc("https://doi.org/" + e.doi))
                elif e.url:
                    bits.append(esc(e.url))
                rows.append("[" + " ".join(x if x.startswith("#") else esc(x) for x in bits if x) + "]")
            return self.unnumbered(m.title, "#list(" + ", ".join(rows) + ")" if rows else "")
        if k == "endnotes":
            parts = []
            for title, notes in self.book_notes:
                parts.append(f'#text(weight: "bold")[{esc(title)}]\n#enum(' + ", ".join(f"[{n}]" for n in notes) + ")")
            return self.unnumbered(m.title, "\n\n".join(parts) or esc("No notes."))
        if k == "index":
            body = (
                "#context {\n  let entries = (:)\n  for m in query(<pbs-index>) {\n"
                "    let p = counter(page).at(m.location()).first()\n"
                "    entries.insert(m.value, entries.at(m.value, default: ()) + (p,))\n  }\n"
                "  for k in entries.keys().sorted() {\n"
                '    [#k #box(width: 1fr, repeat[.]) #entries.at(k).dedup().map(str).join(", ") \\ ]\n  }\n}'
            )
            return self.unnumbered(m.title, body)
        return self.unnumbered(m.title, self.markdown_blocks(m, m.body_md))

    def markdown_blocks(self, m: MatterItem, md: str) -> str:
        from pbs_core.document import bookmd

        doc = m.doc if md == m.body_md and m.doc else bookmd.parse(md, chapter_id="matter", new_id=lambda: "x").doc
        self.prefix = f"matter-{m.kind}-"
        self.cur_footnotes = dict(doc.get("footnotes", {}))
        return self.blocks(doc.get("blocks", []))

    def unnumbered(self, title: str, body: str) -> str:
        opener = '#pagebreak(to: "odd", weak: true)' if self.t["chapter_opens"] == "recto" else "#pagebreak(weak: true)"
        return f'{opener}\n#pbs-chapter("")[{esc(title)}]\n\n{body}\n\n#metadata("end")<pbs-end>'


def _walk(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in blocks:
        out.append(b)
        if isinstance(b.get("blocks"), list):
            out += _walk(b["blocks"])
        if b.get("type") == "list":
            for it in b["items"]:
                out += _walk(it["blocks"])
    return out


@dataclass
class TypstBuild:
    source: str
    pdf: bytes
    page_count: int
    inside_in: Decimal
    passes: int
    stats: Stats
    width_in: Decimal
    height_in: Decimal


def _preamble(book: Book, w: Decimal, h: Decimal, inside: Decimal) -> str:
    t = book.template
    num_align = "center" if t["page_numbers"] == "footer_center" else None
    footer = (
        'context { if not state("pbs-body").get() or pbs-blank(here().page()) { return }\n'
        + (
            '  align(center, counter(page).display("1"))'
            if num_align
            else '  let p = here().page()\n  align(if calc.even(p) { left } else { right }, counter(page).display("1"))'
        )
        + "\n}"
    )
    header = (
        'context {\n  let p = here().page()\n  if not state("pbs-body").get() or pbs-blank(p) { return }\n'
        "  if query(heading.where(level: 1)).any(h => h.location().page() == p) { return }\n"
        f"  if calc.even(p) {{ text(size: 8.5pt, smallcaps({s(book.title)})) }} else {{\n"
        "    let hs = query(heading.where(level: 1).before(here()))\n"
        "    if hs.len() > 0 { align(right, text(size: 8.5pt, smallcaps(hs.last().body))) }\n  }\n}"
        if t["running_heads"]
        else "none"
    )
    author = f", author: {s(book.author)}" if book.author else ""
    return f"""// Generated by Personal Book Studio (interior template: {t["label"]}).
// A page left blank so the next chapter opens on a right-hand page gets no running head or number.
#let pbs-blank(p) = query(<pbs-end>).all(m => m.location().page() != p) and query(heading.where(level: 1)).any(h => h.location().page() == p + 1)
#set document(title: {s(book.title)}{author})
#set page(width: {w}in, height: {h}in, binding: left,
  margin: (inside: {inside}in, outside: {t["outside_in"]}in, top: {t["top_in"]}in, bottom: {t["bottom_in"]}in),
  header: {header},
  footer: {footer})
#set text(font: {s(t["body_font"])}, size: {t["body_pt"]}pt, lang: {s(book.language.split("-")[0])}, hyphenate: true)
#set par(justify: {str(t["justify"]).lower()}, leading: {t["leading_em"]}em)
#set heading(bookmarked: false)
#show raw: set text(font: {s(t["code_font"])}, size: {t["code_pt"]}pt)
#show raw.where(block: true): it => block(width: 100%, inset: 6pt, fill: luma(244), breakable: true, it)
#show math.equation: set text(font: {s(t["math_font"])})
#show heading.where(level: 1): it => block(below: 2em)[#text(size: 22pt, weight: "bold", it.body)]
#show heading.where(level: 2): set text(size: 14pt)
#show heading.where(level: 3): set text(size: 12pt)
#show figure.caption: set text(size: 0.9em)
#show figure: set block(breakable: true)
#let pbs-chapter(lead, title) = {{
  v(0.9in)
  if lead != "" {{ text(size: 10pt, tracking: 0.12em, upper(lead)); v(0.4em) }}
  heading(level: 1, title)
  v(0.3in)
}}
#state("pbs-body").update(false)
"""


def _stamp(book: Book) -> int:
    """PDF dates come from the book's last revision, so the same book always gives the same bytes."""
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(book.modified.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 1767225600  # 2026-01-01T00:00:00Z


def build(book: Book, trim: str) -> TypstBuild:
    w, h, _ = kdp_rules.TRIM_SIZES[trim]
    t = book.template
    inside = Decimal(str(t["inside_in"]))
    work = Path(tempfile.mkdtemp(prefix="pbs-typst-"))
    try:
        (work / "assets").mkdir()
        for a in book.assets.values():
            (work / "assets" / f"{a.short_hash}.{a.ext}").write_bytes(a.data)
        passes = 0
        while True:
            passes += 1
            text_w = w - inside - Decimal(str(t["outside_in"]))
            wr = _W(book, text_w)
            parts = [_preamble(book, w, h, inside)]
            front_titled = [m for m in book.front if m.kind in ("foreword", "preface", "introduction")]
            for m in book.front:
                if m not in front_titled:
                    parts.append(wr.matter_item(m))
            started = False
            for m in front_titled:
                parts.append(wr.matter_item(m))
            for ch in book.chapters:
                if not started and ch.depth == 0:
                    parts.append(
                        '#pagebreak(to: "odd", weak: true)\n#state("pbs-body").update(true)\n#counter(page).update(1)'
                    )
                    started = True
                parts.append(wr.chapter(ch))
            if not started:
                parts.append('#state("pbs-body").update(true)')
            for m in book.back:
                parts.append(wr.matter_item(m))
            source = "\n\n".join(p for p in parts if p) + "\n"
            (work / "main.typ").write_text(source, encoding="utf-8")
            try:
                pdf = typst.compile(
                    str(work / "main.typ"), root=str(work), ignore_system_fonts=True, timestamp=_stamp(book)
                )
            except typst.TypstError as exc:
                raise LayoutError(f"The print layout engine (Typst) could not lay out the book: {exc}") from exc
            if not isinstance(pdf, bytes):  # pragma: no cover - single-file PDF output
                raise RuntimeError("Typst did not return a PDF")
            import io

            from pypdf import PdfReader

            pages = len(PdfReader(io.BytesIO(pdf)).pages)
            need = kdp_rules.gutter_for(max(pages, 24)) or kdp_rules.GUTTER[-1][2]
            if inside >= need or passes >= MAX_PASSES:
                return TypstBuild(source, pdf, pages, inside, passes, wr.stats, w, h)
            inside = need  # a longer book needs a wider gutter: lay it out again
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_png_pages(source: str, book: Book, ppi: int = 60) -> list[bytes]:
    """Page images rendered from the same Typst source as the PDF (not the PDF file itself)."""
    work = Path(tempfile.mkdtemp(prefix="pbs-typst-png-"))
    try:
        (work / "assets").mkdir()
        for a in book.assets.values():
            (work / "assets" / f"{a.short_hash}.{a.ext}").write_bytes(a.data)
        (work / "main.typ").write_text(source, encoding="utf-8")
        out = typst.compile(str(work / "main.typ"), root=str(work), ignore_system_fonts=True, format="png", ppi=ppi)
        return list(out) if isinstance(out, list) else [out]
    finally:
        shutil.rmtree(work, ignore_errors=True)
