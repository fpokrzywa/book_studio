"""Assembled book -> editable DOCX (python-docx), with named styles a publisher or editor can restyle.

Styles: Title, Subtitle, Heading 1-4, Normal, Quote, Caption, List Bullet, List Number, and PBS styles
"PBS Code" (monospace), "PBS Equation", "PBS Chapter Label", "PBS Matter". Documented substitutes
(listed in every export report, never silent):
* equations are kept as their LaTeX source in the "PBS Equation" style (Word's native equation format
  cannot be produced reliably here);
* footnotes become numbered notes at the end of each chapter, with superscript markers;
* the table of contents is a Word TOC field that Word fills in when the document is opened and fields
  are updated.
The file is re-zipped with fixed timestamps, so the same book gives the same bytes.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from pbs_core.document.bookmd import SAFE_LINK_SCHEMES, inline_text
from pbs_core.publishing import kdp_rules
from pbs_core.publishing.book import Book, MatterItem
from pbs_core.publishing.write_html import prepare

_FIXED = (2026, 1, 1, 0, 0, 0)


@dataclass
class DocxStats:
    equations_as_latex: int = 0
    images: int = 0
    links: list[str] = field(default_factory=list)
    notes: int = 0
    broken_links: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def _style(
    doc: Any, name: str, base: str, *, font: str | None = None, size: float | None = None, italic: bool | None = None
) -> None:
    styles = doc.styles
    if name in [s.name for s in styles]:
        return
    st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    st.base_style = styles[base]
    if font:
        st.font.name = font
        st.element.rPr.rFonts.set(qn("w:eastAsia"), font)
    if size:
        st.font.size = Pt(size)
    if italic is not None:
        st.font.italic = italic


def _hyperlink(par: Any, url: str, text: str) -> None:
    rid = par.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    rpr.append(style)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rpr.append(u)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    par._p.append(link)


class _W:
    def __init__(self, book: Book) -> None:
        self.book = book
        self.doc = Document()
        self.stats = DocxStats()
        self.notes: list[str] = []
        self.note_order: list[str] = []
        self.footnotes: dict[str, list[dict[str, Any]]] = {}
        t = book.template
        normal = self.doc.styles["Normal"]
        normal.font.name = t["body_font"]
        normal.font.size = Pt(t["body_pt"])
        _style(self.doc, "PBS Code", "Normal", font="Consolas", size=t["code_pt"])
        _style(self.doc, "PBS Equation", "Normal", font="Cambria Math", size=t["body_pt"])
        _style(self.doc, "PBS Chapter Label", "Normal", size=9)
        _style(self.doc, "PBS Matter", "Normal", size=t["body_pt"])
        w, _h, _ = kdp_rules.TRIM_SIZES[t["trim"]]
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Inches(float(w)), Inches(float(kdp_rules.TRIM_SIZES[t["trim"]][1]))
        sec.left_margin = Inches(t["inside_in"])
        sec.right_margin = Inches(t["outside_in"])
        sec.top_margin, sec.bottom_margin = Inches(t["top_in"]), Inches(t["bottom_in"])
        self.text_width = Decimal(str(float(w) - t["inside_in"] - t["outside_in"]))

    # ----- inline -----
    def runs(self, par: Any, nodes: list[dict[str, Any]], fmt: dict[str, bool] | None = None) -> None:
        fmt = fmt or {}
        for n in nodes:
            t = n["t"]
            if t == "text":
                r = par.add_run(n["v"])
                r.italic, r.bold = fmt.get("i") or None, fmt.get("b") or None
                if fmt.get("s"):
                    r.font.strike = True
            elif t == "softbreak":
                par.add_run(" ")
            elif t == "hardbreak":
                par.add_run().add_break()
            elif t == "code":
                r = par.add_run(n["v"])
                r.font.name = "Consolas"
            elif t == "math":
                self.stats.equations_as_latex += 1
                r = par.add_run(n["tex"])
                r.font.name = "Cambria Math"
            elif t in ("emph", "strong", "strike"):
                key = {"emph": "i", "strong": "b", "strike": "s"}[t]
                self.runs(par, n["c"], {**fmt, key: True})
            elif t == "link":
                href = n["href"]
                text = inline_text(n["c"])
                if href.startswith("#") or not href.lower().startswith(SAFE_LINK_SCHEMES):
                    if not href.startswith("#"):
                        self.stats.unsupported.append(f"unsafe link removed: {href[:60]}")
                    self.runs(par, n["c"], fmt)
                else:
                    self.stats.links.append(href)
                    _hyperlink(par, href, text or href)
            elif t == "image":
                self.picture(par, n["src"], n.get("alt") or inline_text(n["c"]), inline=True)
            elif t == "cite":
                par.add_run("(" + "; ".join(self.book.cite_label(i) for i in n["items"]) + ")")
            elif t == "footnote_ref":
                lbl = n["label"]
                if lbl not in self.note_order:
                    self.note_order.append(lbl)
                    body = self.footnotes.get(lbl)
                    self.notes.append(
                        " ".join(inline_text(b.get("inlines", [])) for b in body or [] if b.get("type") == "paragraph")
                        if body
                        else f"[^{lbl}] (no text)"
                    )
                r = par.add_run(str(self.note_order.index(lbl) + 1))
                r.font.superscript = True
            else:
                par.add_run(str(n.get("v", "")))

    def picture(self, par: Any, src: str, alt: str, *, inline: bool = False) -> None:
        if not src.startswith("asset:"):
            par.add_run(f"[image not included: {src[:60]}]")
            self.stats.unsupported.append(f"web image not embedded: {src[:60]}")
            return
        a = self.book.assets.get(src[6:])
        if a is None:
            par.add_run("[missing image]")
            return
        natural = Decimal(a.width_px or 600) / Decimal(kdp_rules.MIN_IMAGE_DPI)
        width = min(natural, self.text_width) if not inline else min(Decimal("0.3"), natural)
        shape = par.add_run().add_picture(io.BytesIO(a.data), width=Inches(float(width)))
        doc_pr = shape._inline.docPr
        doc_pr.set("descr", alt)
        doc_pr.set("title", alt[:100])
        self.stats.images += 1

    # ----- blocks -----
    def blocks(self, items: list[dict[str, Any]], *, list_style: str | None = None) -> None:
        for b in items:
            self.block(b, list_style=list_style)

    def caption(self, b: dict[str, Any], nodes: list[dict[str, Any]] | None, text: str | None = None) -> None:
        par = self.doc.add_paragraph(style="Caption")
        if nodes:
            self.runs(par, nodes)
        elif text:
            par.add_run(text)

    def block(self, b: dict[str, Any], *, list_style: str | None = None) -> None:
        t = b["type"]
        if t == "heading":
            self.runs(self.doc.add_heading(level=min(b["level"], 4)), b["inlines"])
        elif t == "paragraph":
            self.runs(self.doc.add_paragraph(style=list_style or "Normal"), b["inlines"])
        elif t == "thematic_break":
            p = self.doc.add_paragraph("* * *")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif t == "code":
            cap = b.get("attrs", {}).get("kv", {}).get("caption")
            if cap:
                self.caption(b, None, cap)
            for line in b["text"].split("\n"):
                self.doc.add_paragraph(line, style="PBS Code")
        elif t == "math_block":
            self.stats.equations_as_latex += 1
            p = self.doc.add_paragraph(b["tex"], style="PBS Equation")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif t == "quote":
            for inner in b["blocks"]:
                if inner["type"] == "paragraph":
                    self.runs(self.doc.add_paragraph(style="Quote"), inner["inlines"])
                else:
                    self.block(inner)
        elif t == "list":
            style = "List Number" if b["ordered"] else "List Bullet"
            for item in b["items"]:
                first = True
                for inner in item["blocks"]:
                    if inner["type"] == "paragraph":
                        par = self.doc.add_paragraph(style=style if first else "Normal")
                        if "checked" in item and first:
                            par.add_run("☑ " if item["checked"] else "☐ ")
                        self.runs(par, inner["inlines"])
                        first = False
                    else:
                        self.block(inner)
        elif t == "table":
            n = max(len(b["head"]), max((len(r) for r in b["rows"]), default=0), 1)
            if b.get("caption"):
                self.caption(b, b["caption"])
            table = self.doc.add_table(rows=1 + len(b["rows"]), cols=n)
            table.style = "Table Grid"
            for i, c in enumerate((b["head"] + [[]] * n)[:n]):
                cell_par = table.rows[0].cells[i].paragraphs[0]
                self.runs(cell_par, c, {"b": True})
            for ri, row in enumerate(b["rows"], start=1):
                for i, c in enumerate((row + [[]] * n)[:n]):
                    self.runs(table.rows[ri].cells[i].paragraphs[0], c)
            hdr = table.rows[0]._tr.get_or_add_trPr()
            th = OxmlElement("w:tblHeader")
            th.set(qn("w:val"), "true")
            hdr.append(th)
        elif t == "figure":
            alt = b.get("alt") if b.get("alt") is not None else inline_text(b["caption"])
            par = self.doc.add_paragraph()
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self.picture(par, b["src"], alt or "")
            if b.get("caption"):
                self.caption(b, b["caption"])
        elif t == "div":
            self.blocks(b["blocks"])
        elif t == "unsupported":
            self.stats.unsupported.append("unsupported block kept as written")
            for line in b["raw"].split("\n"):
                self.doc.add_paragraph(line, style="PBS Code")
        else:
            self.stats.unsupported.append(f"unknown block type {t}")

    def page_break(self) -> None:
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def notes_section(self) -> None:
        if not self.notes:
            return
        self.doc.add_paragraph("Notes", style="Heading 3")
        for i, text in enumerate(self.notes, start=1):
            p = self.doc.add_paragraph(style="PBS Matter")
            r = p.add_run(f"{i}. ")
            r.bold = True
            p.add_run(text)
        self.stats.notes += len(self.notes)
        self.notes, self.note_order = [], []

    def toc_field(self, title: str) -> None:
        self.doc.add_paragraph(title, style="Heading 1")
        p = self.doc.add_paragraph()
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), 'TOC \\o "1-2" \\h \\z \\u')
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "Right-click and choose Update Field to build the table of contents."
        r.append(t)
        fld.append(r)
        p._p.append(fld)

    def matter(self, m: MatterItem) -> None:
        from pbs_core.document import bookmd

        b = self.book
        self.page_break()
        k = m.kind
        if k == "half_title":
            p = self.doc.add_paragraph(b.title, style="Title")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            return
        if k == "title_page":
            self.doc.add_paragraph(b.title, style="Title").alignment = WD_ALIGN_PARAGRAPH.CENTER
            if b.subtitle:
                self.doc.add_paragraph(b.subtitle, style="Subtitle").alignment = WD_ALIGN_PARAGRAPH.CENTER
            if b.author:
                self.doc.add_paragraph(b.author).alignment = WD_ALIGN_PARAGRAPH.CENTER
            return
        if k == "copyright":
            c = b.copyright
            if (c.get("notice_md") or "").strip():
                self.blocks(bookmd.parse(c["notice_md"], chapter_id="c", new_id=lambda: "x").doc.get("blocks", []))
            elif c.get("holder") or c.get("year"):
                self.doc.add_paragraph(
                    f"Copyright © {c.get('year') or ''} {c.get('holder') or ''}".strip(), style="PBS Matter"
                )
            if c.get("edition"):
                self.doc.add_paragraph(str(c["edition"]), style="PBS Matter")
            if c.get("isbn"):
                self.doc.add_paragraph(f"ISBN {c['isbn']}", style="PBS Matter")
            return
        if k == "toc":
            self.toc_field(m.title)
            return
        self.doc.add_heading(m.title, level=1)
        if k == "glossary":
            for term, d in b.glossary:
                p = self.doc.add_paragraph(style="PBS Matter")
                p.add_run(term).bold = True
                p.add_run(f": {d}")
            return
        if k == "bibliography":
            for key in b.cited_keys:
                e = b.bibliography.get(key)
                if e is None:
                    self.doc.add_paragraph(f"{key} (no details entered)", style="PBS Matter")
                    continue
                p = self.doc.add_paragraph(style="PBS Matter")
                if e.authors:
                    p.add_run(", ".join(e.authors) + " ")
                if e.year:
                    p.add_run(f"({e.year}) ")
                p.add_run(e.title).italic = True
                p.add_run(". ")
                if e.publisher:
                    p.add_run(e.publisher + ". ")
                link = f"https://doi.org/{e.doi}" if e.doi else e.url
                if link:
                    _hyperlink(p, link, link)
            return
        if k == "index":
            from pbs_core.publishing.book import index_hits

            titles = {c.id: c.title for c in b.chapters}
            for term, ids in sorted(index_hits(b).items(), key=lambda kv: kv[0].lower()):
                self.doc.add_paragraph(
                    f"{term}: " + (", ".join(titles[i] for i in ids) or "not found in the text"), style="PBS Matter"
                )
            return
        if k == "endnotes":
            self.doc.add_paragraph("Notes appear at the end of each chapter in this edition.", style="PBS Matter")
            return
        doc = m.doc if m.doc is not None else bookmd.parse(m.body_md, chapter_id="m", new_id=lambda: "x").doc
        self.footnotes = dict(doc.get("footnotes", {}))
        self.blocks(doc.get("blocks", []))
        self.notes_section()


def build(book: Book) -> tuple[bytes, DocxStats]:
    w = _W(book)
    d = w.doc
    cp = d.core_properties
    cp.title, cp.author, cp.language = book.title, book.author or "", book.language
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    cp.created = cp.modified = fixed
    cp.last_modified_by = "Personal Book Studio"
    cp.revision = 1
    first = True
    for m in book.front:
        if first:
            first = False
            if m.kind in ("half_title", "title_page"):
                d.add_paragraph(book.title, style="Title").alignment = WD_ALIGN_PARAGRAPH.CENTER
                if m.kind == "title_page":
                    if book.subtitle:
                        d.add_paragraph(book.subtitle, style="Subtitle").alignment = WD_ALIGN_PARAGRAPH.CENTER
                    if book.author:
                        d.add_paragraph(book.author).alignment = WD_ALIGN_PARAGRAPH.CENTER
                continue
        w.matter(m)

    def target(a: str) -> str | None:
        return "#" + a

    for ch in book.chapters:
        doc, broken, _dropped = prepare(book, ch, target)
        w.stats.broken_links += broken
        w.page_break()
        lead = book.template["chapter_label"]
        if lead and ch.number:
            d.add_paragraph(f"{lead} {ch.number}".upper(), style="PBS Chapter Label")
        d.add_heading(ch.title, level=min(ch.depth + 1, 4))
        w.footnotes = dict(doc.get("footnotes", {}))
        w.blocks(doc.get("blocks", []))
        w.notes_section()
    for m in book.back:
        w.matter(m)
    raw = io.BytesIO()
    d.save(raw)
    # Re-zip with fixed timestamps and a stable order: the same book always gives the same bytes.
    src = zipfile.ZipFile(io.BytesIO(raw.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(src.namelist(), key=lambda n: (n != "[Content_Types].xml", n)):
            info = zipfile.ZipInfo(name, date_time=_FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, src.read(name))
    return out.getvalue(), w.stats
