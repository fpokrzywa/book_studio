"""HTML -> bdm/1 -> BookMD.

HTML is untrusted. It is parsed with the standard-library parser (no entity or DTD expansion,
no network) into a small tree, and only known structural elements are mapped. Scripts, styles,
frames, objects and forms are dropped and reported. Event-handler attributes never survive,
because attributes are never copied through. Images embedded as data: URLs become project
images; remote images are not downloaded.

Also understands the footnote, math and citation markup produced by Pandoc and by mammoth (DOCX).
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote

from pbs_core.document.bookmd import _MD, SAFE_LINK_SCHEMES
from pbs_core.importers.base import ImportResult, short_hash, split_blocks
from pbs_core.services.assets import sniff_image

VOID = {"br", "img", "hr", "input", "meta", "link", "col", "source", "wbr", "area", "base", "embed", "param", "track"}
DROP = {"script", "style", "template", "iframe", "object", "embed", "form", "button", "select", "textarea",
        "noscript", "svg", "canvas", "head", "title", "meta", "link", "audio", "video", "frame", "frameset"}  # fmt: skip
CONTAINERS = {"div", "section", "article", "main", "header", "footer", "body", "html", "nav", "aside", "center", "span"}
_WS = re.compile(r"\s+")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)  # Node | str

    def cls(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.dropped: dict[str, int] = {}
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._drop_depth or tag in DROP:
            if tag not in VOID:
                self._drop_depth += 1
            if tag in DROP:
                self.dropped[tag] = self.dropped.get(tag, 0) + 1
            return
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID and not self._drop_depth and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._drop_depth:
            if tag not in VOID:
                self._drop_depth -= 1
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.stack[-1].children.append(data)


def parse_html(markup: str) -> tuple[Node, dict[str, int]]:
    b = _TreeBuilder()
    b.feed(markup)
    b.close()
    return b.root, b.dropped


class _Converter:
    def __init__(self, result: ImportResult) -> None:
        self.result = result
        self.footnotes: dict[str, list[dict[str, Any]]] = {}
        self.fn_ids: dict[str, str] = {}  # html id of a footnote definition -> label
        self.unsupported: set[str] = set()

    # ----- footnote discovery (Pandoc: #fn1, mammoth: #footnote-1 / #endnote-1) -----
    def collect_footnotes(self, root: Node) -> None:
        for li in _find_all(root, "li"):
            fid = li.attrs.get("id", "")
            m = re.match(r"^(?:fn|footnote-|endnote-)(\d+)$", fid)
            if not m:
                continue
            label = ("e" if fid.startswith("endnote") else "") + m.group(1)
            self.fn_ids[fid] = label
            _remove_backlinks(li)
            self.footnotes[label] = self.blocks(li.children)
            li.attrs["data-pbs-consumed"] = "1"

    # ----- blocks -----
    def blocks(self, children: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        inline_run: list[Any] = []

        def flush_inline() -> None:
            if inline_run:
                inl = _trim(self.inlines(inline_run))
                if inl:
                    out.append({"type": "paragraph", "inlines": inl})
                inline_run.clear()

        for child in children:
            if isinstance(child, str) or (child.tag not in _BLOCK_TAGS and child.tag not in CONTAINERS):
                inline_run.append(child)
                continue
            if child.tag == "span" and not _has_block_child(child):
                inline_run.append(child)
                continue
            flush_inline()
            out.extend(self.block(child))
        flush_inline()
        return _attach_captions(out)

    def block(self, n: Node) -> list[dict[str, Any]]:
        t = n.tag
        if n.attrs.get("data-pbs-consumed"):
            return []
        if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            block: dict[str, Any] = {"type": "heading", "level": int(t[1]), "inlines": _trim(self.inlines(n.children))}
            if n.attrs.get("id") and re.fullmatch(r"[\w:.\-]+", n.attrs["id"]):
                block["attrs"] = {"id": n.attrs["id"]}
            return [block] if block["inlines"] else []
        if t == "p":
            if "pbs-caption" in n.cls() or "caption" in n.cls():
                return [{"type": "_caption", "inlines": _trim(self.inlines(n.children))}]
            only = [c for c in n.children if not (isinstance(c, str) and not c.strip())]
            if len(only) == 1 and isinstance(only[0], Node) and only[0].tag == "img":
                fig = self.figure(only[0], [])
                return [fig] if fig else []
            inl = _trim(self.inlines(n.children))
            return [{"type": "paragraph", "inlines": inl}] if inl else []
        if t in ("ul", "ol"):
            if t == "ol" and _is_footnote_list(n, self.fn_ids):
                return []
            items = []
            task = False
            for li in (c for c in n.children if isinstance(c, Node) and c.tag == "li"):
                checked = None
                box = next((c for c in li.children if isinstance(c, Node) and c.tag == "input"), None)
                if box is not None and box.attrs.get("type") == "checkbox":
                    checked, task = "checked" in box.attrs, True
                item: dict[str, Any] = {"blocks": self.blocks(li.children) or [{"type": "paragraph", "inlines": []}]}
                if checked is not None:
                    item["checked"] = checked
                items.append(item)
            items = [i for i in items if i["blocks"] and i["blocks"][0].get("inlines", True) != []] or items
            lst: dict[str, Any] = {"type": "list", "ordered": t == "ol", "tight": True, "items": items}
            if t == "ol":
                start = n.attrs.get("start", "1")
                lst["start"] = int(start) if start.isdigit() else 1
            if task:
                lst["task"] = True
            for it in items:
                if any(b["type"] != "paragraph" for b in it["blocks"]) or len(it["blocks"]) > 1:
                    lst["tight"] = False
            return [lst] if items else []
        if t == "blockquote":
            inner = self.blocks(n.children)
            return [{"type": "quote", "blocks": inner}] if inner else []
        if t == "pre":
            code = next((c for c in n.children if isinstance(c, Node) and c.tag == "code"), None)
            src = code if code is not None else n
            lang = ""
            for c in sorted((code.cls() if code is not None else set()) | n.cls()):
                if c.startswith(("language-", "lang-")):
                    lang = c.split("-", 1)[1]
                elif c in ("python", "javascript", "sql", "bash", "json") and not lang:
                    lang = c
            text = src.text()
            return [{"type": "code", "lang": lang, "text": text if text.endswith("\n") else text + "\n"}]
        if t == "hr":
            return [{"type": "thematic_break"}]
        if t == "table":
            return [self.table(n)]
        if t == "figure":
            img = _find_first(n, "img")
            cap = _find_first(n, "figcaption")
            if img is None:
                return self.blocks([c for c in n.children if c is not cap])
            fig = self.figure(img, self.inlines(cap.children) if cap else [])
            return [fig] if fig else []
        if t == "img":
            fig = self.figure(n, [])
            return [fig] if fig else []
        if t == "math" or (t in ("div", "span") and "math" in n.cls() and "display" in n.cls()):
            tex = _tex_of(n)
            if tex is not None:
                return [{"type": "math_block", "tex": tex}]
        if t in ("dl",):
            self.unsupported.add("definition lists")
            return self.blocks(n.children)
        if t in ("section", "div", "aside") and ("footnotes" in n.cls() or n.attrs.get("role") == "doc-endnotes"):
            return []
        if t in CONTAINERS:
            return self.blocks(n.children)
        self.unsupported.add(t)
        inl = _trim(self.inlines(n.children))
        return [{"type": "paragraph", "inlines": inl}] if inl else []

    def figure(self, img: Node, caption: list[dict[str, Any]]) -> dict[str, Any] | None:
        src = self.image_src(img.attrs.get("src", ""))
        if src is None:
            return None
        alt = img.attrs.get("alt", "").strip()
        fig: dict[str, Any] = {"type": "figure", "src": src, "caption": _trim(caption)}
        if alt:
            fig["alt"] = alt
        return fig

    def image_src(self, src: str) -> str | None:
        if src.startswith("data:"):
            m = re.match(r"^data:([\w/+.-]+)?(;base64)?,(.*)$", src, re.DOTALL)
            if not m:
                self.result.warn("image_unreadable", "An embedded image could not be read and was skipped.")
                return None
            try:
                data = base64.b64decode(m.group(3), validate=False) if m.group(2) else unquote(m.group(3)).encode()
            except (binascii.Error, ValueError):
                self.result.warn("image_unreadable", "An embedded image could not be read and was skipped.")
                return None
            if sniff_image(data) is None:
                self.result.warn(
                    "image_unsupported", "An embedded image is not PNG, JPEG, GIF or WebP and was skipped."
                )
                return None
            h = short_hash(data)
            self.result.images[h] = (data, f"image-{h}")
            return f"asset:{h}"
        src = _MD.normalizeLink(src)
        if src.startswith(("http://", "https://")):
            self.result.warn(
                "external_image",
                "Images that point to the web were not downloaded (privacy). Their links are kept; "
                "save those images and insert them into the chapter.",
            )
            return src
        self.result.warn(
            "unresolved_image",
            f"The image “{src[:60]}” is a separate file and was not included. Insert it into the chapter after importing.",
        )
        return src or None

    def table(self, n: Node) -> dict[str, Any]:
        rows: list[tuple[list[Node], bool]] = []
        caption: list[dict[str, Any]] = []
        for el in _walk_table(n):
            if el.tag == "caption":
                caption = _trim(self.inlines(el.children))
            elif el.tag == "tr":
                cells = [c for c in el.children if isinstance(c, Node) and c.tag in ("td", "th")]
                is_head = all(c.tag == "th" for c in cells) and bool(cells)
                rows.append((cells, is_head))
        if not rows:
            return {"type": "paragraph", "inlines": [{"t": "text", "v": n.text().strip()}]}
        head_cells, _ = rows[0]
        body = rows[1:]
        width = max(len(c) for c, _ in rows)
        if any(c.attrs.get("colspan") not in (None, "", "1") or c.attrs.get("rowspan") not in (None, "", "1")
               for cells, _ in rows for c in cells):  # fmt: skip
            self.result.warn("table_spans", "Merged table cells were split; check tables after importing.")
            self.result.lossy = True

        def cell_inlines(c: Node) -> list[dict[str, Any]]:
            inl = self.inlines(_flatten_blocks_to_inline(c.children))
            return _trim(inl)

        align = []
        for c in head_cells:
            style = c.attrs.get("style", "") + " " + c.attrs.get("align", "")
            m = re.search(r"(left|right|center)", style)
            align.append(m.group(1) if m else None)
        align += [None] * (width - len(align))
        head = [cell_inlines(c) for c in head_cells] + [[] for _ in range(width - len(head_cells))]
        body_rows = [[cell_inlines(c) for c in cells] + [[] for _ in range(width - len(cells))] for cells, _ in body]
        table: dict[str, Any] = {"type": "table", "align": align, "head": head, "rows": body_rows}
        if caption:
            table["caption"] = caption
        return table

    # ----- inline -----
    def inlines(self, children: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in children:
            if isinstance(c, str):
                text = _WS.sub(" ", c)
                if text:
                    out.append({"t": "text", "v": text})
                continue
            out.extend(self.inline(c))
        return _merge(out)

    def inline(self, n: Node) -> list[dict[str, Any]]:
        t = n.tag
        if t in ("strong", "b"):
            return _wrap("strong", self.inlines(n.children))
        if t in ("em", "i", "cite") and "citation" not in n.cls():
            return _wrap("emph", self.inlines(n.children))
        if t in ("s", "del", "strike"):
            return _wrap("strike", self.inlines(n.children))
        if t in ("code", "kbd", "samp", "tt"):
            return [{"t": "code", "v": n.text()}] if n.text() else []
        if t == "br":
            return [{"t": "hardbreak"}]
        if t == "img":
            src = self.image_src(n.attrs.get("src", ""))
            if src is None:
                return []
            return [
                {
                    "t": "image",
                    "src": src,
                    "c": [{"t": "text", "v": n.attrs.get("alt", "")}] if n.attrs.get("alt") else [],
                }
            ]
        if t == "a":
            href = n.attrs.get("href", "")
            fn = re.match(r"^#(fn\d+|footnote-\d+|endnote-\d+)$", href)
            if fn and fn.group(1) in self.fn_ids:
                return [{"t": "footnote_ref", "label": self.fn_ids[fn.group(1)]}]
            inner = self.inlines(n.children)
            if not href or href.startswith("#"):
                return inner
            if not href.lower().startswith(SAFE_LINK_SCHEMES):
                self.result.warn(
                    "unsafe_link", f"A link to “{href[:40]}” was removed because it is not a web or mail link."
                )
                return inner
            node: dict[str, Any] = {"t": "link", "href": _MD.normalizeLink(href), "c": inner}
            if n.attrs.get("title"):
                node["title"] = n.attrs["title"]
            return [node]
        if t == "sup":
            inner_link = _find_first(n, "a")
            if inner_link is not None:
                href = inner_link.attrs.get("href", "")
                fn = re.match(r"^#(fn\d+|footnote-\d+|endnote-\d+)$", href)
                if fn and fn.group(1) in self.fn_ids:
                    return [{"t": "footnote_ref", "label": self.fn_ids[fn.group(1)]}]
            self.unsupported.add("superscript")
            return self.inlines(n.children)
        if t == "sub":
            self.unsupported.add("subscript")
            return self.inlines(n.children)
        if t == "math" or (t == "span" and "math" in n.cls()):
            tex = _tex_of(n)
            if tex is not None:
                return [{"t": "math", "tex": tex}]
        if t == "span" and "citation" in n.cls() and n.attrs.get("data-cites"):
            keys = [k for k in n.attrs["data-cites"].split() if re.fullmatch(r"[\w][\w:.#$%&\-+?<>~/]*", k)]
            if keys:
                return [{"t": "cite", "items": [{"key": k} for k in keys]}]
        if t in ("input", "label", "abbr", "small", "mark", "u", "q", "time", "font", "span", "bdi", "bdo", "data"):
            return self.inlines(n.children)
        if t in _BLOCK_TAGS:
            return self.inlines(n.children)
        self.unsupported.add(t)
        return self.inlines(n.children)


_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote", "pre", "hr", "table", "figure",
               "img", "math", "dl", "li", "figcaption", "caption", "thead", "tbody", "tr", "td", "th"}  # fmt: skip


def _find_all(n: Node, tag: str) -> list[Node]:
    out = []
    for c in n.children:
        if isinstance(c, Node):
            if c.tag == tag:
                out.append(c)
            out.extend(_find_all(c, tag))
    return out


def _find_first(n: Node, tag: str) -> Node | None:
    found = _find_all(n, tag)
    return found[0] if found else None


def _has_block_child(n: Node) -> bool:
    return any(isinstance(c, Node) and (c.tag in _BLOCK_TAGS or _has_block_child(c)) for c in n.children)


def _walk_table(n: Node) -> list[Node]:
    out = []
    for c in n.children:
        if isinstance(c, Node):
            if c.tag in ("caption", "tr"):
                out.append(c)
            elif c.tag in ("thead", "tbody", "tfoot"):
                out.extend(_walk_table(c))
    return out


def _flatten_blocks_to_inline(children: list[Any]) -> list[Any]:
    out: list[Any] = []
    for c in children:
        if isinstance(c, Node) and c.tag in ("p", "div") and out:
            out.append(" ")
        out.extend(c.children if isinstance(c, Node) and c.tag in ("p", "div") else [c])
    return out


def _remove_backlinks(n: Node) -> None:
    keep = []
    for c in n.children:
        if isinstance(c, Node):
            href = c.attrs.get("href", "")
            if c.tag == "a" and (
                "footnote-back" in c.cls() or re.match(r"^#(fnref\d+|footnote-ref-\d+|endnote-ref-\d+)$", href)
            ):
                continue
            _remove_backlinks(c)
        keep.append(c)
    n.children = keep


def _is_footnote_list(n: Node, ids: dict[str, str]) -> bool:
    lis = [c for c in n.children if isinstance(c, Node) and c.tag == "li"]
    return bool(lis) and all(li.attrs.get("id") in ids for li in lis)


def _tex_of(n: Node) -> str | None:
    annotation = next((a for a in _find_all(n, "annotation") if "tex" in a.attrs.get("encoding", "")), None)
    if annotation is not None:
        return annotation.text().strip()
    if n.tag == "math":
        return n.attrs.get("alttext") or None
    text = n.text().strip()
    m = re.fullmatch(r"\\\((.*)\\\)|\\\[(.*)\\\]|\$\$(.*)\$\$|\$(.*)\$", text, re.DOTALL)
    if m:
        return next(g for g in m.groups() if g is not None).strip()
    return text or None


def _wrap(kind: str, inner: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inner = _trim_edges(inner)
    return [{"t": kind, "c": inner}] if inner else []


def _trim_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emphasis content may not start or end with whitespace in Markdown: move it outside."""
    return _trim(nodes)


def _merge(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in nodes:
        if n["t"] == "text" and out and out[-1]["t"] == "text":
            out[-1] = {"t": "text", "v": _WS.sub(" ", out[-1]["v"] + n["v"])}
        else:
            out.append(n)
    return out


def _trim(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = [dict(n) for n in _merge(nodes)]
    while nodes and nodes[0]["t"] == "text" and not nodes[0]["v"].strip():
        nodes.pop(0)
    while (
        nodes
        and nodes[-1]["t"] in ("text", "hardbreak")
        and (nodes[-1]["t"] == "hardbreak" or not nodes[-1]["v"].strip())
    ):
        nodes.pop()
    while nodes and nodes[0]["t"] == "hardbreak":
        nodes.pop(0)
    if nodes and nodes[0]["t"] == "text":
        nodes[0]["v"] = nodes[0]["v"].lstrip()
    if nodes and nodes[-1]["t"] == "text":
        nodes[-1]["v"] = nodes[-1]["v"].rstrip()
    return nodes


def _attach_captions(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A caption-styled paragraph right after a figure (or table) becomes its caption."""
    out: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] == "_caption":
            if out and out[-1]["type"] == "figure" and not out[-1]["caption"]:
                out[-1]["caption"] = b["inlines"]
                continue
            if out and out[-1]["type"] == "table" and "caption" not in out[-1]:
                out[-1]["caption"] = b["inlines"]
                continue
            if b["inlines"]:
                out.append({"type": "paragraph", "inlines": b["inlines"]})
            continue
        out.append(b)
    return out


def html_to_doc(markup: str, result: ImportResult) -> dict[str, Any]:
    root, dropped = parse_html(markup)
    conv = _Converter(result)
    conv.collect_footnotes(root)
    blocks = conv.blocks(root.children)
    if dropped:
        listed = ", ".join(
            f"{k} ×{v}" for k, v in sorted(dropped.items()) if k not in ("head", "title", "meta", "link")
        )
        if listed:
            result.warn("removed_elements", f"Removed unsafe or unsupported embedded content: {listed}.")
            result.lossy = True
    if conv.unsupported:
        result.warn(
            "unsupported_elements",
            "Some formatting has no equivalent and was kept as plain text: "
            + ", ".join(sorted(conv.unsupported))
            + ".",
        )
        result.lossy = True
    doc: dict[str, Any] = {"blocks": blocks}
    if conv.footnotes:
        doc["footnotes"] = conv.footnotes
    return doc


def import_html(
    data: bytes, fallback_title: str, *, importer: str = "html", result: ImportResult | None = None
) -> ImportResult:
    from pbs_core.importers.base import decode_text

    result = result or ImportResult(importer, [])
    markup = decode_text(data, result) if isinstance(data, bytes) else data
    title_match = re.search(r"<title[^>]*>(.*?)</title>", markup, re.IGNORECASE | re.DOTALL)
    if title_match and title_match.group(1).strip():
        fallback_title = _WS.sub(" ", title_match.group(1)).strip()[:300]
    doc = html_to_doc(markup, result)
    result.chapters = split_blocks(doc, fallback_title)
    return result
