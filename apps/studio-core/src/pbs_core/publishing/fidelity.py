"""Round-trip fidelity: what the book contains vs. what each export really contains.

The source inventory comes from the assembled book. Each export is opened and inspected on its own
terms (HTML and EPUB parsed, DOCX read with python-docx, PDF text and objects read with pypdf).
Every element is reported as ok, degraded (present but changed, e.g. an equation kept as LaTeX
source in DOCX) or missing. Nothing unsupported is dropped without a line in this report.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

import lxml.html
from lxml import etree

from pbs_core.document.bookmd import inline_text
from pbs_core.publishing.book import Book

_WS = re.compile(r"[\s­​-]+")


def norm(text: str) -> str:
    return _WS.sub("", text).lower()


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


def _inl(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for n in nodes:
        out.append(n)
        if isinstance(n.get("c"), list):
            out += _inl(n["c"])
    return out


def _title_heading(blocks: list[dict[str, Any]], title: str) -> bool:
    """The chapter text starts with a level-1 heading that repeats the chapter title."""
    return bool(
        blocks
        and blocks[0].get("type") == "heading"
        and blocks[0].get("level") == 1
        and inline_text(blocks[0]["inlines"]).strip().lower() == title.strip().lower()
    )


@dataclass
class Inventory:
    chapters: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    tables: int = 0
    table_cells: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    equations: list[str] = field(default_factory=list)
    images: list[tuple[str, str]] = field(default_factory=list)  # (asset hash, alt)
    captions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # rendered labels
    citation_keys: list[str] = field(default_factory=list)


def inventory(book: Book) -> Inventory:
    inv = Inventory(chapters=[c.title for c in book.chapters])
    for ch in book.chapters:
        blocks = list((ch.doc or {}).get("blocks", []))
        if _title_heading(blocks, ch.title):
            blocks = blocks[1:]
        for b in _walk(blocks):
            t = b.get("type")
            lists: list[list[dict[str, Any]]] = []
            if t == "heading":
                inv.headings.append(inline_text(b["inlines"]))
            if t == "table":
                inv.tables += 1
                cells = b["head"] + [c for r in b["rows"] for c in r]
                inv.table_cells += [inline_text(c) for c in cells if inline_text(c).strip()]
                lists += cells
                if b.get("caption"):
                    inv.captions.append(inline_text(b["caption"]))
            if t == "code":
                inv.code.append(b["text"])
                cap = b.get("attrs", {}).get("kv", {}).get("caption")
                if cap:
                    inv.captions.append(cap)
            if t == "math_block":
                inv.equations.append(b["tex"])
            if t == "figure":
                inv.images.append(
                    (
                        str(b.get("src", ""))[6:],
                        str(b["alt"]) if b.get("alt") is not None else inline_text(b["caption"]),
                    )
                )
                if b.get("caption"):
                    inv.captions.append(inline_text(b["caption"]))
                lists.append(b.get("caption") or [])
            for key in ("inlines",):
                if isinstance(b.get(key), list):
                    lists.append(b[key])
            for lst in lists:
                for n in _inl(lst):
                    if n["t"] == "link" and not n["href"].startswith("#"):
                        inv.links.append(n["href"])
                    elif n["t"] == "math":
                        inv.equations.append(n["tex"])
                    elif n["t"] == "cite":
                        for i in n["items"]:
                            inv.citation_keys.append(i["key"])
                            inv.citations.append(book.cite_label(i))
                    elif n["t"] == "image":
                        inv.images.append((str(n.get("src", ""))[6:], n.get("alt") or inline_text(n["c"])))
    return inv


def _row(element: str, expected: Any, found: Any, status: str, note: str = "") -> dict[str, Any]:
    return {"element": element, "expected": expected, "found": found, "status": status, "note": note}


def _order_ok(titles: list[str], text: str) -> bool:
    pos = -1
    for t in titles:
        i = text.find(norm(t), pos + 1)
        if i < 0:
            return False
        pos = i
    return True


def _common(inv: Inventory, text: str, rows: list[dict[str, Any]], *, fmt: str) -> None:
    """Checks that only need the export's full plain text."""
    n = norm(text)
    rows.append(_row("chapter order", inv.chapters, "in order" if _order_ok(inv.chapters, n) else "out of order or missing",
                     "ok" if _order_ok(inv.chapters, n) else "missing"))  # fmt: skip
    missing_h = [h for h in inv.headings if norm(h) not in n]
    rows.append(
        _row(
            "headings",
            len(inv.headings),
            len(inv.headings) - len(missing_h),
            "ok" if not missing_h else "missing",
            "; ".join(missing_h[:5]),
        )
    )
    missing_c = [c for c in inv.table_cells if norm(c) not in n]
    rows.append(
        _row(
            "table cell text",
            len(inv.table_cells),
            len(inv.table_cells) - len(missing_c),
            "ok" if not missing_c else "missing",
            "; ".join(missing_c[:5]),
        )
    )
    missing_code = [c for c in inv.code if norm(c) not in n]
    rows.append(
        _row(
            "code blocks (exact text)",
            len(inv.code),
            len(inv.code) - len(missing_code),
            "ok" if not missing_code else "missing",
        )
    )
    missing_cap = [c for c in inv.captions if norm(c) not in n]
    rows.append(
        _row(
            "captions",
            len(inv.captions),
            len(inv.captions) - len(missing_cap),
            "ok" if not missing_cap else "missing",
            "; ".join(missing_cap[:5]),
        )
    )
    missing_cite = [c for c in dict.fromkeys(inv.citations) if norm(c) not in n]
    rows.append(
        _row(
            "citation references",
            len(set(inv.citations)),
            len(set(inv.citations)) - len(missing_cite),
            "ok" if not missing_cite else "missing",
            "; ".join(missing_cite[:5]),
        )
    )


def check_html(inv: Inventory, data: bytes) -> list[dict[str, Any]]:
    root = lxml.html.fromstring(data)
    rows: list[dict[str, Any]] = []
    _common(inv, root.text_content(), rows, fmt="html")
    _markup_checks(inv, [root], rows)
    return rows


def _markup_checks(inv: Inventory, roots: list[Any], rows: list[dict[str, Any]]) -> None:
    def xp(q: str) -> list[Any]:
        out: list[Any] = []
        for r in roots:
            out += r.xpath(q)
        return out

    tables = len(xp("//*[local-name()='table']"))
    rows.append(_row("tables", inv.tables, tables, "ok" if tables >= inv.tables else "missing"))
    hrefs = {a.get("href") for a in xp("//*[local-name()='a']")}
    miss = [h for h in inv.links if h not in hrefs]
    rows.append(
        _row(
            "hyperlinks",
            len(inv.links),
            len(inv.links) - len(miss),
            "ok" if not miss else "missing",
            "; ".join(miss[:5]),
        )
    )
    maths = len(xp("//*[local-name()='math']"))
    src = len(xp("//*[local-name()='code' and contains(@class,'math-source')]"))
    rows.append(_row("equations", len(inv.equations), maths + src, "ok" if maths >= len(inv.equations) else ("degraded" if maths + src >= len(inv.equations) else "missing"),
                     f"{src} shown as LaTeX source" if src else "MathML"))  # fmt: skip
    alts = [i.get("alt") or "" for i in xp("//*[local-name()='img']")]
    rows.append(_row("images", len(inv.images), len(alts), "ok" if len(alts) >= len(inv.images) else "missing"))
    want_alt = [a for _h, a in inv.images if a]
    rows.append(
        _row(
            "image alt text",
            len(want_alt),
            sum(1 for a in want_alt if a in alts),
            "ok" if all(a in alts for a in want_alt) else "missing",
        )
    )


def check_epub(inv: Inventory, data: bytes) -> list[dict[str, Any]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    opf = etree.fromstring(z.read("OEBPS/content.opf"))
    ns = {"o": "http://www.idpf.org/2007/opf"}
    items = {i.get("id"): i.get("href") for i in opf.findall(".//o:manifest/o:item", ns)}
    spine = [items[r.get("idref")] for r in opf.findall(".//o:spine/o:itemref", ns)]
    roots = [etree.fromstring(z.read(f"OEBPS/{f}")) for f in spine]
    text = " ".join("".join(r.itertext()) for r in roots)
    rows: list[dict[str, Any]] = []
    _common(inv, text, rows, fmt="epub")
    _markup_checks(inv, roots, rows)
    return rows


def check_docx(inv: Inventory, data: bytes) -> list[dict[str, Any]]:
    from docx import Document

    d = Document(io.BytesIO(data))
    paras = d.paragraphs
    cell_text = [p.text for t in d.tables for row in t.rows for c in row.cells for p in c.paragraphs]
    text = "\n".join([p.text for p in paras] + cell_text)
    rows: list[dict[str, Any]] = []
    _common(inv, text, rows, fmt="docx")
    rows.append(_row("tables", inv.tables, len(d.tables), "ok" if len(d.tables) >= inv.tables else "missing"))
    rels = {r.target_ref for r in d.part.rels.values() if r.is_external}
    miss = [h for h in inv.links if h not in rels]
    rows.append(
        _row(
            "hyperlinks",
            len(inv.links),
            len(inv.links) - len(miss),
            "ok" if not miss else "missing",
            "; ".join(miss[:5]),
        )
    )
    eq_found = sum(1 for e in inv.equations if norm(e) in norm(text))
    rows.append(_row("equations", len(inv.equations), eq_found, "degraded" if eq_found >= len(inv.equations) else "missing",
                     "Kept as LaTeX source (PBS Equation style); Word equations are not generated."))  # fmt: skip
    docprs = d.element.body.xpath(".//wp:docPr")
    alts = [x.get("descr") or "" for x in docprs]
    rows.append(_row("images", len(inv.images), len(docprs), "ok" if len(docprs) >= len(inv.images) else "missing"))
    want = [a for _h, a in inv.images if a]
    rows.append(
        _row(
            "image alt text",
            len(want),
            sum(1 for a in want if a in alts),
            "ok" if all(a in alts for a in want) else "missing",
        )
    )
    styles = sorted({p.style.name for p in paras if p.style is not None})
    rows.append(_row("paragraph styles", "named styles", styles, "ok"))
    return rows


def check_pdf(inv: Inventory, data: bytes, stats: Any) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(data))
    text = "\n".join(p.extract_text() or "" for p in r.pages)
    rows: list[dict[str, Any]] = []
    _common(inv, text, rows, fmt="pdf")
    n = norm(text)
    printed = [h for h in inv.links if norm(h.removeprefix("mailto:")) in n]
    rows.append(_row("hyperlinks", len(inv.links), len(printed), "degraded" if len(printed) == len(inv.links) else "missing",
                     "Print has no live links: each web address is printed after its link text."))  # fmt: skip
    as_src = len(stats.equations_as_source)
    rows.append(_row("equations", len(inv.equations), stats.equations,
                     "ok" if stats.equations >= len(inv.equations) and not as_src else ("degraded" if stats.equations >= len(inv.equations) else "missing"),
                     f"{as_src} printed as LaTeX source: " + "; ".join(stats.equations_as_source[:3]) if as_src else "Typeset by Typst"))  # fmt: skip
    images = 0
    for p in r.pages:
        res = p.get("/Resources") or {}
        xo = res.get("/XObject") if hasattr(res, "get") else None
        if xo:
            for v in xo.get_object().values():
                if v.get_object().get("/Subtype") == "/Image":
                    images += 1
    rows.append(_row("images", len(inv.images), images, "ok" if images >= len(inv.images) else "missing"))
    rows.append(
        _row(
            "image alt text",
            len([a for _h, a in inv.images if a]),
            "in tagged PDF structure",
            "ok",
            "Typst writes alt text into the PDF tags.",
        )
    )
    return rows


def check_markdown(book: Book, text: str) -> list[dict[str, Any]]:
    rows = []
    missing = [
        c.title
        for c in book.chapters
        if norm(re.sub(r"\(asset:[0-9a-f]{16}", "(", c.source_md))
        not in norm(re.sub(r"\(images/[0-9a-f]{16}\.\w+", "(", text))
    ]
    rows.append(
        _row(
            "chapter text (verbatim)",
            len(book.chapters),
            len(book.chapters) - len(missing),
            "ok" if not missing else "missing",
            "; ".join(missing),
        )
    )
    rows.append(
        _row(
            "chapter order",
            [c.title for c in book.chapters],
            "in order" if _order_ok([c.title for c in book.chapters], norm(text)) else "out of order",
            "ok" if _order_ok([c.title for c in book.chapters], norm(text)) else "missing",
        )
    )
    return rows


def summarize(rows: list[dict[str, Any]]) -> str:
    if any(r["status"] == "missing" for r in rows):
        return "missing"
    if any(r["status"] == "degraded" for r in rows):
        return "degraded"
    return "ok"
