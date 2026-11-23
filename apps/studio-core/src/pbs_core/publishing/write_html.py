"""Assembled book -> HTML fragments (shared by the HTML export and the EPUB), and the standalone HTML book.

Anchors are made unique per chapter (``<slug>-<id>``), links to them are pointed at the right file,
captions get the same numbers as every other format, citations link to the bibliography, and a body
heading that repeats the chapter title is folded into the chapter title.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pbs_core.document import html as html_render
from pbs_core.publishing.book import Book, BookChapter, MatterItem, index_hits
from pbs_core.publishing.fidelity import _title_heading

LinkTarget = Callable[[str], str | None]
_INTERNAL = re.compile(r"^(?:[A-Za-z0-9_.-]+\.xhtml)?#[A-Za-z0-9_.:-]+$")  # a link inside this book


@dataclass
class Fragment:
    html: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
    broken_links: list[str] = field(default_factory=list)
    dropped_title_heading: bool = False


class _BookRenderer(html_render._Renderer):
    def __init__(
        self, book: Book, resolve: html_render.AssetResolver, bib_href: Callable[[str], str], **kw: Any
    ) -> None:
        super().__init__(resolve, external_images=False, **kw)
        self.book = book
        self.bib_href = bib_href

    def node(self, n: dict[str, Any]) -> str:
        if n["t"] == "link" and _INTERNAL.match(n["href"]):
            # A link to another part of this book (same file or another file of the EPUB).
            return f'<a href="{html.escape(n["href"])}">{self.inl(n["c"])}</a>'
        if n["t"] == "cite":
            keys = " ".join(i["key"] for i in n["items"])
            parts = []
            for i in n["items"]:
                text = html.escape(self.book.cite_label(i), quote=False)
                parts.append(
                    f'<a href="{html.escape(self.bib_href(i["key"]))}">{text}</a>'
                    if i["key"] in self.book.bibliography
                    else text
                )
            return f'<cite class="citation" data-keys="{html.escape(keys)}">(' + "; ".join(parts) + ")</cite>"
        return super().node(n)


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


def _inline_lists(b: dict[str, Any]) -> list[list[dict[str, Any]]]:
    out = []
    for key in ("inlines", "caption"):
        if isinstance(b.get(key), list):
            out.append(b[key])
    if b.get("type") == "table":
        out += b["head"] + [c for r in b["rows"] for c in r]
    return out


def _walk_inlines(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for n in nodes:
        out.append(n)
        if isinstance(n.get("c"), list):
            out += _walk_inlines(n["c"])
    return out


def prepare(
    book: Book, ch: BookChapter, target: LinkTarget, *, offset: int = 1
) -> tuple[dict[str, Any], list[str], bool]:
    """A copy of the chapter's document ready for HTML-like writers. Returns (doc, broken links, dropped title)."""
    doc = copy.deepcopy(ch.doc or {"blocks": []})
    blocks = doc.get("blocks", [])
    dropped = False
    if _title_heading(blocks, ch.title):
        doc["blocks"] = blocks = blocks[1:]
        dropped = True
    broken: list[str] = []
    all_blocks = _walk(blocks) + [x for fn in doc.get("footnotes", {}).values() for x in _walk(fn)]
    for b in all_blocks:
        attrs = b.get("attrs")
        if attrs and attrs.get("id"):
            attrs["id"] = f"{ch.slug}-{attrs['id']}"
        if b.get("type") == "heading":
            b["level"] = min(6, b["level"] + offset)
        lbl = book.labels.get(b.get("id", ""))
        if lbl:
            if b["type"] in ("figure", "table"):
                b["caption"] = [{"t": "text", "v": f"{lbl}: "}, *list(b.get("caption") or [])]
            elif b["type"] == "code":
                kv = b.setdefault("attrs", {}).setdefault("kv", {})
                kv["caption"] = f"{lbl}: {kv.get('caption', '')}"
        for lst in _inline_lists(b):
            for n in _walk_inlines(lst):
                if n.get("t") == "link" and n.get("href", "").startswith("#"):
                    frag = n["href"][1:]
                    href = target(f"{ch.slug}-{frag}") or target(frag)
                    for other in book.chapters:  # an anchor in another chapter
                        href = href or target(f"{other.slug}-{frag}")
                    if href is None:
                        broken.append(n["href"])
                    else:
                        n["href"] = href
    return doc, broken, dropped


def render_fragment(
    book: Book, doc: dict[str, Any], resolve: html_render.AssetResolver, bib_href: Callable[[str], str], id_prefix: str
) -> tuple[str, list[dict[str, Any]]]:
    r = _BookRenderer(book, resolve, bib_href, id_prefix=id_prefix)
    body = r.blocks(doc.get("blocks", [])) + r.footnotes(doc.get("footnotes", {}))
    # Internal links (#…, file.xhtml#…) must survive sanitising: nh3 keeps relative URLs.
    return html_render.sanitize(body, allow_data_urls=True), r.warnings


def anchors(book: Book) -> dict[str, str]:
    """Every block anchor in the book -> chapter slug that holds it."""
    out: dict[str, str] = {}
    for ch in book.chapters:
        out[f"ch-{ch.slug}"] = ch.slug
        for b in _walk((ch.doc or {}).get("blocks", [])):
            a = b.get("attrs", {}).get("id")
            if a:
                out[f"{ch.slug}-{a}"] = ch.slug
    return out


def matter_html(
    book: Book,
    m: MatterItem,
    render_md: Callable[[MatterItem], str],
    toc_html: str,
    bib_href: Callable[[str], str],
    chapter_href: Callable[[str], str],
) -> str:
    """The inner HTML of one front/back matter item (no outer section)."""
    e = html.escape
    k = m.kind
    if k == "half_title":
        return f'<p class="half-title">{e(book.title)}</p>'
    if k == "title_page":
        out = [f'<h1 class="book-title">{e(book.title)}</h1>']
        if book.subtitle:
            out.append(f'<p class="subtitle">{e(book.subtitle)}</p>')
        if book.author:
            out.append(f'<p class="author">{e(book.author)}</p>')
        return "".join(out)
    if k == "copyright":
        c = book.copyright
        out = []
        if (c.get("notice_md") or "").strip():
            out.append(render_md(MatterItem("copyright", "front", m.title, c["notice_md"], False)))
        elif c.get("holder") or c.get("year"):
            out.append(f"<p>Copyright © {e(str(c.get('year') or ''))} {e(c.get('holder') or '')}</p>")
        if c.get("edition"):
            out.append(f"<p>{e(str(c['edition']))}</p>")
        if c.get("isbn"):
            out.append(f"<p>ISBN {e(c['isbn'])}</p>")
        return "".join(out)
    if k == "toc":
        return f"<h2>{e(m.title)}</h2>{toc_html}"
    if k == "glossary":
        items = "".join(f"<dt>{e(t)}</dt><dd>{e(d)}</dd>" for t, d in book.glossary)
        return f'<h2>{e(m.title)}</h2><dl class="glossary">{items}</dl>'
    if k == "bibliography":
        rows = []
        for key in book.cited_keys:
            b = book.bibliography.get(key)
            anchor = bib_href(key).split("#")[-1]
            if b is None:
                rows.append(f'<li id="{e(anchor)}">{e(key)} (no details entered)</li>')
                continue
            bits = []
            if b.authors:
                bits.append(e(", ".join(b.authors)))
            if b.year:
                bits.append(f"({e(b.year)})")
            bits.append(f"<em>{e(b.title)}</em>.")
            if b.publisher:
                bits.append(e(b.publisher) + ".")
            link = f"https://doi.org/{b.doi}" if b.doi else b.url
            if link:
                bits.append(f'<a href="{e(link)}">{e(link)}</a>')
            rows.append(f'<li id="{e(anchor)}">{" ".join(bits)}</li>')
        return f'<h2>{e(m.title)}</h2><ol class="bibliography">{"".join(rows)}</ol>'
    if k == "index":
        hits = index_hits(book)
        titles = {c.id: c.title for c in book.chapters}
        rows = []
        for term in sorted(hits, key=str.lower):
            links = ", ".join(f'<a href="{e(chapter_href(cid))}">{e(titles[cid])}</a>' for cid in hits[term])
            rows.append(f"<li>{e(term)}: {links or 'not found in the text'}</li>")
        return f'<h2>{e(m.title)}</h2><ul class="index">{"".join(rows)}</ul>'
    if k == "endnotes":
        return f"<h2>{e(m.title)}</h2><p>Notes appear at the end of each chapter in this edition.</p>"
    return f"<h2>{e(m.title)}</h2>{render_md(m)}"


CSS = {
    "base": """
body{margin:0 auto;max-width:40em;padding:1.5em;line-height:1.55;font-family:Georgia,'Libertinus Serif',serif;color:#1d1d1f;background:#fff}
h1,h2,h3,h4{line-height:1.25}
.chapter-label{text-transform:uppercase;letter-spacing:.12em;font-size:.8em;margin:2.5em 0 .3em}
section.chapter>h1{margin-top:0}
figure{margin:1.5em 0;text-align:center}figure img{max-width:100%;height:auto}
figcaption,caption{font-size:.9em;color:#444}
table{border-collapse:collapse;margin:1em auto}th,td{border:1px solid #999;padding:.3em .6em}
pre{background:#f4f4f4;padding:.7em;overflow-x:auto;white-space:pre-wrap;font-size:.85em}
code{font-family:'DejaVu Sans Mono',Consolas,monospace}
.equation{text-align:center;margin:1em 0}
blockquote{margin:1em 2em;font-style:italic}
.half-title,.book-title{text-align:center;font-size:2em;margin-top:3em}
.subtitle,.author{text-align:center;font-size:1.25em}
.footnotes{font-size:.9em}
.align-right{text-align:right}.align-center{text-align:center}
dl.glossary dt{font-weight:bold}
""",
    "novel": "body{font-size:1.05em}p{text-indent:1.5em;margin:0}p:first-of-type{text-indent:0}",
    "technical_manual": "body{max-width:46em}",
    "workbook": "body{max-width:48em;font-size:1.05em}",
    "nonfiction": "",
}


def standalone(book: Book) -> tuple[bytes, dict[str, Any]]:
    """One self-contained HTML file (images embedded). Returns (bytes, stats)."""
    e = html.escape
    uris: dict[str, str] = {}

    def resolve(h: str) -> str | None:
        a = book.assets.get(h)
        if a is None:
            return None
        if h not in uris:
            uris[h] = f"data:{a.mime};base64," + base64.b64encode(a.data).decode("ascii")
        return uris[h]

    amap = anchors(book)

    def target(a: str) -> str | None:
        return f"#{a}" if a in amap else None

    def bib_href(key: str) -> str:
        return f"#bib-{hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:10]}"

    def chapter_href(cid: str) -> str:
        ch = next(c for c in book.chapters if c.id == cid)
        return f"#ch-{ch.slug}"

    def render_md(m: MatterItem) -> str:
        from pbs_core.document import bookmd

        doc = m.doc if m.doc is not None else bookmd.parse(m.body_md, chapter_id="m", new_id=lambda: "x").doc
        out, _ = render_fragment(book, doc, resolve, bib_href, f"matter-{m.kind}-")
        return out

    stats: dict[str, Any] = {"broken_links": [], "warnings": [], "dropped_title_headings": 0}
    toc = (
        "<ol>"
        + "".join(f'<li class="toc-{c.depth}"><a href="#ch-{e(c.slug)}">{e(c.title)}</a></li>' for c in book.chapters)
        + "</ol>"
    )
    parts: list[str] = []
    for m in book.front:
        if m.kind == "toc":
            parts.append(
                f'<nav class="toc" aria-label="{e(m.title)}">{matter_html(book, m, render_md, toc, bib_href, chapter_href)}</nav>'
            )
        else:
            parts.append(
                f'<section class="matter {m.kind}">{matter_html(book, m, render_md, toc, bib_href, chapter_href)}</section>'
            )
    for ch in book.chapters:
        doc, broken, dropped = prepare(book, ch, target)
        stats["broken_links"] += broken
        stats["dropped_title_headings"] += int(dropped)
        body, warns = render_fragment(book, doc, resolve, bib_href, f"{ch.slug}-")
        stats["warnings"] += warns
        lead = book.template["chapter_label"]
        label_html = f'<p class="chapter-label">{e(lead)} {ch.number}</p>' if lead and ch.number else ""
        lvl = min(ch.depth + 1, 6)
        parts.append(
            f'<section class="chapter" id="ch-{e(ch.slug)}">{label_html}<h{lvl}>{e(ch.title)}</h{lvl}>{body}</section>'
        )
    for m in book.back:
        parts.append(
            f'<section class="matter {m.kind}">{matter_html(book, m, render_md, toc, bib_href, chapter_href)}</section>'
        )
    css = CSS["base"] + CSS.get(book.template_key, "")
    csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    author = f'<meta name="author" content="{e(book.author)}">\n' if book.author else ""
    doc_html = (
        "<!doctype html>\n"
        f'<html lang="{e(book.language)}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{author}"
        '<meta name="generator" content="Personal Book Studio (pbs-html-book/1)">\n'
        f"<title>{e(book.title)}</title>\n<style>{css}</style>\n</head>\n<body>\n"
        + "\n".join(parts)
        + "\n</body>\n</html>\n"
    )
    return doc_html.encode("utf-8"), stats
