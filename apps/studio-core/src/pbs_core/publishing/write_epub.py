"""Assembled book -> reflowable, accessible EPUB 3 (deterministic ZIP).

* One XHTML file per front-matter item, chapter and back-matter item; a navigation document with the
  table of contents and landmarks; images packaged as files with their alt text.
* Equations are MathML (declared with the ``mathml`` property), so reading systems and assistive
  technology get structured math.
* Accessibility metadata (schema.org access modes, features, hazards and a summary) is filled from
  what the book really contains.
* The ZIP is written with ``mimetype`` first and uncompressed and fixed timestamps, so the same book
  always gives the same bytes.
"""

from __future__ import annotations

import hashlib
import html
import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

import lxml.html
from lxml import etree

from pbs_core.publishing.book import Book, MatterItem
from pbs_core.publishing.write_html import CSS, anchors, matter_html, prepare, render_fragment

XHTML_NS = "http://www.w3.org/1999/xhtml"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
EPUB_NS = "http://www.idpf.org/2007/ops"
_VOID = {"br", "img", "hr", "input", "col", "meta", "link"}
_MATH_TAGS = {
    "math", "semantics", "annotation", "mrow", "mi", "mo", "mn", "ms", "mtext", "mspace", "msup", "msub",
    "msubsup", "mfrac", "msqrt", "mroot", "mover", "munder", "munderover", "mtable", "mtr", "mtd", "mstyle",
    "mpadded", "mphantom", "menclose", "merror", "mfenced",
}  # fmt: skip
_FIXED = (2026, 1, 1, 0, 0, 0)


def _ser(el: Any, out: list[str], in_math: bool = False) -> None:
    if not isinstance(el.tag, str):  # comment or processing instruction
        if el.tail:
            out.append(html.escape(el.tail, quote=False))
        return
    tag = el.tag.split("}")[-1].lower()
    math_root = tag == "math" and not in_math
    attrs = []
    for k, v in el.attrib.items():
        k = k.split("}")[-1]
        if k == "xmlns" or k.startswith("xmlns:"):
            continue
        if tag == "input" and k in ("disabled", "checked"):
            v = k
        attrs.append(f' {k}="{html.escape(v, quote=True)}"')
    if math_root:
        attrs.insert(0, f' xmlns="{MATHML_NS}"')
    if tag == "aside" and not any(a.startswith(" epub:type") for a in attrs):
        pass
    a = "".join(attrs)
    if tag in _VOID and not len(el) and not (el.text or "").strip():
        out.append(f"<{tag}{a}/>")
    else:
        out.append(f"<{tag}{a}>")
        if el.text:
            out.append(html.escape(el.text, quote=False))
        for child in el:
            _ser(child, out, in_math or tag == "math")
        out.append(f"</{tag}>")
    if el.tail:
        out.append(html.escape(el.tail, quote=False))


def to_xhtml(fragment: str) -> str:
    """HTML fragment (from the shared renderer) -> well-formed XHTML."""
    if not fragment.strip():
        return ""
    parts = lxml.html.fragments_fromstring(fragment)
    out: list[str] = []
    for p in parts:
        if isinstance(p, str):
            out.append(html.escape(p, quote=False))
        else:
            _ser(p, out)
    return "".join(out)


def _page(title: str, lang: str, body: str, *, epub_type: str = "", has_math: bool = False) -> str:
    et = f' epub:type="{epub_type}"' if epub_type else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" xml:lang="{html.escape(lang)}" lang="{html.escape(lang)}">\n'
        f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        f"<body><section{et}>{body}</section></body>\n</html>\n"
    )


@dataclass
class EpubBuild:
    data: bytes
    files: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def build(book: Book, cover_jpeg: bytes | None = None) -> EpubBuild:
    e = html.escape
    lang = book.language
    amap = anchors(book)
    files: dict[str, str] = {}  # slug/item -> file name
    order: list[tuple[str, str, str, str]] = []  # (id, file, title, epub:type)
    for i, m in enumerate(book.front):
        files[f"front-{m.kind}"] = f"front-{i + 1:02d}-{m.kind}.xhtml"
    for i, ch in enumerate(book.chapters):
        files[ch.slug] = f"chapter-{i + 1:03d}.xhtml"
    for i, m in enumerate(book.back):
        files[f"back-{m.kind}"] = f"back-{i + 1:02d}-{m.kind}.xhtml"

    def target(a: str) -> str | None:
        slug = amap.get(a)
        return f"{files[slug]}#{a}" if slug else None

    def bib_href(key: str) -> str:
        frag = f"bib-{hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:10]}"
        f = files.get("back-bibliography")
        return f"{f}#{frag}" if f else f"#{frag}"

    def chapter_href(cid: str) -> str:
        ch = next(c for c in book.chapters if c.id == cid)
        return f"{files[ch.slug]}#ch-{ch.slug}"

    def resolve(h: str) -> str | None:
        a = book.assets.get(h)
        return f"images/{h}.{a.ext}" if a else None

    def render_md(m: MatterItem) -> str:
        from pbs_core.document import bookmd

        doc = m.doc if m.doc is not None else bookmd.parse(m.body_md, chapter_id="m", new_id=lambda: "x").doc
        out, _ = render_fragment(book, doc, resolve, bib_href, f"matter-{m.kind}-")
        return out

    toc_items = "".join(f'<li><a href="{files[c.slug]}#ch-{e(c.slug)}">{e(c.title)}</a></li>' for c in book.chapters)
    xhtml: dict[str, str] = {}
    math_files: set[str] = set()
    stats: dict[str, Any] = {"broken_links": [], "warnings": [], "dropped_title_headings": 0}
    for m in book.front:
        if m.kind == "toc":
            continue  # the navigation document is the table of contents
        body = to_xhtml(matter_html(book, m, render_md, f"<ol>{toc_items}</ol>", bib_href, chapter_href))
        et = {"title_page": "titlepage", "half_title": "halftitlepage", "copyright": "copyright-page",
              "dedication": "dedication", "epigraph": "epigraph", "foreword": "foreword", "preface": "preface",
              "introduction": "introduction"}.get(m.kind, "frontmatter")  # fmt: skip
        f = files[f"front-{m.kind}"]
        xhtml[f] = _page(m.title, lang, body, epub_type=et, has_math="<math" in body)
        order.append((f"front-{m.kind}", f, m.title, et))
    for ch in book.chapters:
        doc, broken, dropped = prepare(book, ch, target)
        stats["broken_links"] += broken
        stats["dropped_title_headings"] += int(dropped)
        frag, warns = render_fragment(book, doc, resolve, bib_href, f"{ch.slug}-")
        stats["warnings"] += warns
        lead = book.template["chapter_label"]
        label = f'<p class="chapter-label">{e(lead)} {ch.number}</p>' if lead and ch.number else ""
        lvl = min(ch.depth + 1, 6)
        body = f'{label}<h{lvl} id="ch-{e(ch.slug)}">{e(ch.title)}</h{lvl}>' + to_xhtml(frag)
        body = body.replace(
            '<section class="footnotes" role="doc-endnotes">',
            '<section class="footnotes" role="doc-endnotes" epub:type="endnotes">',
        )
        f = files[ch.slug]
        if "<math" in body:
            math_files.add(f)
        xhtml[f] = _page(ch.title, lang, body, epub_type="chapter")
        order.append((ch.slug, f, ch.title, "chapter"))
    for m in book.back:
        body = to_xhtml(matter_html(book, m, render_md, "", bib_href, chapter_href))
        et = {"bibliography": "bibliography", "glossary": "glossary", "index": "index", "appendix": "appendix",
              "acknowledgments": "acknowledgments", "endnotes": "endnotes"}.get(m.kind, "backmatter")  # fmt: skip
        f = files[f"back-{m.kind}"]
        xhtml[f] = _page(m.title, lang, body, epub_type=et)
        order.append((f"back-{m.kind}", f, m.title, et))
    for content in xhtml.values():
        etree.fromstring(content.encode("utf-8"))  # well-formed, or fail loudly here

    landmarks = '<li><a epub:type="toc" href="nav.xhtml#toc">Contents</a></li>'
    first_chapter = next((files[c.slug] for c in book.chapters), None)
    if first_chapter:
        landmarks += f'<li><a epub:type="bodymatter" href="{first_chapter}">Start of content</a></li>'
    nav_toc = "".join(f'<li><a href="{f}">{e(title)}</a></li>' for _id, f, title, _t in order)
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" xml:lang="{e(lang)}" lang="{e(lang)}">\n'
        f'<head><meta charset="utf-8"/><title>Contents</title></head>\n<body>\n'
        f'<nav epub:type="toc" id="toc" role="doc-toc"><h1>Contents</h1><ol>{nav_toc}</ol></nav>\n'
        f'<nav epub:type="landmarks" id="landmarks" hidden="hidden"><h2>Landmarks</h2><ol>{landmarks}</ol></nav>\n'
        "</body>\n</html>\n"
    )
    has_images = bool(book.assets)
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if has_images:
        features.append("alternativeText")
    if math_files:
        features.append("MathML")
    modes = ["textual"] + (["visual"] if has_images else [])
    summary = (
        "Reflowable text with a navigable table of contents and structured headings."
        + (" Images have alternative text." if has_images else "")
        + (" Equations are MathML." if math_files else "")
    )
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']  # fmt: skip
    spine = []
    for _id, f, _title, _t in order:
        props = ' properties="mathml"' if f in math_files else ""
        iid = "x-" + f.replace(".xhtml", "")
        manifest.append(f'<item id="{iid}" href="{f}" media-type="application/xhtml+xml"{props}/>')
        spine.append(f'<itemref idref="{iid}"/>')
    for a in book.assets.values():
        manifest.append(f'<item id="img-{a.short_hash}" href="images/{a.short_hash}.{a.ext}" media-type="{a.mime}"/>')
    if cover_jpeg:
        manifest.append(
            '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
        )
    meta = [
        f'<dc:identifier id="pub-id">{e(book.identifier)}</dc:identifier>',
        f"<dc:title>{e(book.title)}</dc:title>",
        f"<dc:language>{e(lang)}</dc:language>",
        f'<meta property="dcterms:modified">{e(book.modified)}</meta>',
    ]
    if book.author:
        meta.append(f'<dc:creator id="creator">{e(book.author)}</dc:creator>')
    if book.subtitle:
        meta.append(f'<meta property="dcterms:alternative">{e(book.subtitle)}</meta>')
    if book.copyright.get("holder"):
        meta.append(
            f"<dc:rights>Copyright {e(str(book.copyright.get('year') or ''))} {e(book.copyright['holder'])}</dc:rights>"
        )
    meta += [f'<meta property="schema:accessMode">{m}</meta>' for m in modes]
    meta.append('<meta property="schema:accessModeSufficient">textual</meta>')
    meta += [f'<meta property="schema:accessibilityFeature">{f}</meta>' for f in features]
    meta.append('<meta property="schema:accessibilityHazard">none</meta>')
    meta.append(f'<meta property="schema:accessibilitySummary">{e(summary)}</meta>')
    if cover_jpeg:
        meta.append('<meta name="cover" content="cover-image"/>')
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" '
        f'xml:lang="{e(lang)}">\n<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(meta)
        + "\n</metadata>\n<manifest>\n"
        + "\n".join(manifest)
        + "\n</manifest>\n<spine>\n"
        + "\n".join(spine)
        + "\n</spine>\n</package>\n"
    )
    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>\n"
    )
    css = CSS["base"] + CSS.get(book.template_key, "")
    buf = io.BytesIO()
    names: list[str] = []
    with zipfile.ZipFile(buf, "w") as z:

        def put(name: str, data: bytes, compress: bool = True) -> None:
            info = zipfile.ZipInfo(name, date_time=_FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
            names.append(name)

        put("mimetype", b"application/epub+zip", compress=False)
        put("META-INF/container.xml", container.encode())
        put("OEBPS/content.opf", opf.encode())
        put("OEBPS/nav.xhtml", nav.encode())
        put("OEBPS/style.css", css.encode())
        for _id, f, _t, _e in order:
            put(f"OEBPS/{f}", xhtml[f].encode("utf-8"))
        for a in book.assets.values():
            put(f"OEBPS/images/{a.short_hash}.{a.ext}", a.data, compress=False)
        if cover_jpeg:
            put("OEBPS/images/cover.jpg", cover_jpeg, compress=False)
    stats["math_files"] = sorted(math_files)
    return EpubBuild(buf.getvalue(), names, stats)
