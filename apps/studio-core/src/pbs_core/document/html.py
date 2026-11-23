"""bdm/1 -> HTML. One renderer for preview and HTML export (ARCHITECTURE section 4).

Every text value is escaped. Links with unsafe schemes are rendered inert. External images are not
loaded in preview (that would be a network request). The final markup is also passed through
nh3 (ammonia) with an allowlist as defense in depth.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import nh3
from latex2mathml.converter import convert as latex_to_mathml

from pbs_core.document.bookmd import SAFE_LINK_SCHEMES

Block = dict[str, Any]
Inline = dict[str, Any]
AssetResolver = Callable[[str], str | None]  # asset hash -> URL (or None if missing)

_MATHML_TAGS = {
    "math", "semantics", "annotation", "mrow", "mi", "mo", "mn", "ms", "mtext", "mspace", "msup", "msub",
    "msubsup", "mfrac", "msqrt", "mroot", "mover", "munder", "munderover", "mtable", "mtr", "mtd", "mstyle",
    "mpadded", "mphantom", "menclose", "merror", "mfenced", "mlabeledtr", "maligngroup", "malignmark",
}  # fmt: skip
_HTML_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "em", "strong", "s", "code", "pre", "a", "ul", "ol", "li", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td", "caption", "figure", "figcaption", "img", "hr", "br", "div", "span",
    "section", "sup", "input", "cite", "aside",
}  # fmt: skip
_GLOBAL_ATTRS = {"id", "class", "title", "role", "aria-label", "data-keys", "data-warning"}
_MATH_ATTRS = {"display", "xmlns", "mathvariant", "stretchy", "fence", "separator", "accent", "accentunder",
               "columnalign", "lspace", "rspace", "width", "height", "depth", "encoding", "notation",
               "linethickness", "scriptlevel", "displaystyle", "minsize", "maxsize", "movablelimits"}  # fmt: skip


@dataclass
class RenderResult:
    html: str
    warnings: list[dict[str, Any]] = field(default_factory=list)


class _Renderer:
    def __init__(self, resolve_asset: AssetResolver, *, external_images: bool, id_prefix: str = "") -> None:
        self.id_prefix = id_prefix
        self.resolve_asset = resolve_asset
        self.external_images = external_images
        self.warnings: list[dict[str, Any]] = []
        self.footnote_order: list[str] = []

    # ----- inline -----
    def inl(self, nodes: list[Inline]) -> str:
        return "".join(self.node(n) for n in nodes)

    def node(self, n: Inline) -> str:
        t = n["t"]
        if t == "text":
            return html.escape(n["v"], quote=False)
        if t == "softbreak":
            return "\n"
        if t == "hardbreak":
            return "<br>"
        if t == "code":
            return f"<code>{html.escape(n['v'], quote=False)}</code>"
        if t == "math":
            return self.math(n["tex"], display=False)
        if t in ("emph", "strong", "strike"):
            tag = {"emph": "em", "strong": "strong", "strike": "s"}[t]
            return f"<{tag}>{self.inl(n['c'])}</{tag}>"
        if t == "link":
            href = n["href"]
            inner = self.inl(n["c"])
            if not href.lower().startswith(SAFE_LINK_SCHEMES):
                return f'<span class="unsafe-link" title="Link removed: unsafe address">{inner}</span>'
            title = f' title="{html.escape(n["title"])}"' if n.get("title") else ""
            return f'<a href="{html.escape(href)}"{title}>{inner}</a>'
        if t == "image":
            return self.img(n["src"], alt=n.get("alt") or _plain(n["c"]), title=n.get("title"))
        if t == "cite":
            keys = " ".join(i["key"] for i in n["items"])
            label = "; ".join(i["key"] + (", " + i["locator"] if i.get("locator") else "") for i in n["items"])
            return f'<cite class="citation" data-keys="{html.escape(keys)}">({html.escape(label)})</cite>'
        if t == "footnote_ref":
            label = n["label"]
            if label not in self.footnote_order:
                self.footnote_order.append(label)
            num = self.footnote_order.index(label) + 1
            fid = html.escape(self.id_prefix + label)
            return f'<sup class="footnote-ref"><a href="#fn-{fid}" id="fnref-{fid}">{num}</a></sup>'
        return html.escape(str(n.get("v", "")), quote=False)

    def math(self, tex: str, *, display: bool) -> str:
        try:
            mathml = latex_to_mathml(tex, display="block" if display else "inline")
        except Exception:
            self.warnings.append({"code": "math_render_failed", "message": f"Could not render math: {tex[:60]}"})
            cls = "math-source display" if display else "math-source"
            return f'<code class="{cls}" title="Math could not be rendered">{html.escape(tex, quote=False)}</code>'
        return f'<span class="math{" display" if display else ""}">{mathml}</span>'

    def img(self, src: str, *, alt: str, title: str | None = None) -> str:
        title_attr = f' title="{html.escape(title)}"' if title else ""
        if src.startswith("asset:"):
            url = self.resolve_asset(src[6:])
            if url is None:
                self.warnings.append(
                    {"code": "missing_asset", "message": f"Image file {src} is missing from this project."}
                )
                return f'<span class="missing-image" role="img" aria-label="{html.escape(alt)}">Missing image</span>'
            return f'<img src="{html.escape(url)}" alt="{html.escape(alt)}"{title_attr}>'
        if src.startswith(("http://", "https://")) and self.external_images:
            return f'<img src="{html.escape(src)}" alt="{html.escape(alt)}"{title_attr}>'
        return (
            f'<span class="external-image" role="img" aria-label="{html.escape(alt)}" '
            f'data-warning="not loaded">Image not loaded: {html.escape(src[:80])}</span>'
        )

    # ----- blocks -----
    def blocks(self, items: list[Block]) -> str:
        return "\n".join(self.block(b) for b in items)

    def block(self, b: Block) -> str:
        t = b["type"]
        anchor = b.get("attrs", {}).get("id")
        classes = b.get("attrs", {}).get("classes", [])
        id_attr = f' id="{html.escape(anchor)}"' if anchor else ""
        cls_attr = f' class="{html.escape(" ".join(classes))}"' if classes else ""
        if t == "heading":
            lvl = b["level"]
            return f"<h{lvl}{id_attr}{cls_attr}>{self.inl(b['inlines'])}</h{lvl}>"
        if t == "paragraph":
            return f"<p{id_attr}{cls_attr}>{self.inl(b['inlines'])}</p>"
        if t == "thematic_break":
            return "<hr>"
        if t == "code":
            lang = b.get("lang") or ""
            lang_cls = f' class="language-{html.escape(lang)}"' if lang else ""
            caption = b.get("attrs", {}).get("kv", {}).get("caption")
            cap = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
            code = f"<pre{'' if cap else id_attr}><code{lang_cls}>{html.escape(b['text'], quote=False)}</code></pre>"
            return f'<figure class="listing"{id_attr}>{cap}{code}</figure>' if cap else code
        if t == "math_block":
            return f'<div class="equation"{id_attr}>{self.math(b["tex"], display=True)}</div>'
        if t == "quote":
            return f"<blockquote{id_attr}>\n{self.blocks(b['blocks'])}\n</blockquote>"
        if t == "list":
            tag = "ol" if b["ordered"] else "ul"
            start = f' start="{b["start"]}"' if b["ordered"] and b.get("start", 1) != 1 else ""
            items = []
            for item in b["items"]:
                inner = self.list_item(item["blocks"], tight=b.get("tight", True))
                if "checked" in item:
                    box = '<input type="checkbox" disabled' + (" checked" if item["checked"] else "") + "> "
                    items.append(f'<li class="task">{box}{inner}</li>')
                else:
                    items.append(f"<li>{inner}</li>")
            return f"<{tag}{start}>\n" + "\n".join(items) + f"\n</{tag}>"
        if t == "table":
            cap = f"<caption>{self.inl(b['caption'])}</caption>" if b.get("caption") else ""

            def cell(tag: str, c: list[Inline], i: int) -> str:
                a = b["align"][i] if i < len(b["align"]) else None
                cls = f' class="align-{a}"' if a else ""
                return f"<{tag}{cls}>{self.inl(c)}</{tag}>"

            head = "<tr>" + "".join(cell("th", c, i) for i, c in enumerate(b["head"])) + "</tr>"
            rows = "".join("<tr>" + "".join(cell("td", c, i) for i, c in enumerate(r)) + "</tr>" for r in b["rows"])
            return f"<table{id_attr}>{cap}<thead>{head}</thead><tbody>{rows}</tbody></table>"
        if t == "figure":
            alt = b.get("alt") if b.get("alt") is not None else _plain(b["caption"])
            img = self.img(b["src"], alt=alt or "", title=b.get("title"))
            cap = f"<figcaption>{self.inl(b['caption'])}</figcaption>" if b["caption"] else ""
            return f"<figure{id_attr}{cls_attr}>{img}{cap}</figure>"
        if t == "div":
            return f"<div{id_attr}{cls_attr}>\n{self.blocks(b['blocks'])}\n</div>"
        if t == "unsupported":
            return f'<pre class="unsupported" title="Not formatted: shown as written">{html.escape(b["raw"], quote=False)}</pre>'
        return ""

    def list_item(self, items: list[Block], *, tight: bool) -> str:
        if tight:
            return "".join(self.inl(x["inlines"]) if x["type"] == "paragraph" else self.block(x) for x in items)
        return self.blocks(items)

    def footnotes(self, notes: dict[str, list[Block]]) -> str:
        if not notes:
            return ""
        order = self.footnote_order + [k for k in notes if k not in self.footnote_order]
        items = []
        for label in order:
            if label not in notes:
                continue
            fid = html.escape(self.id_prefix + label)
            back = f' <a href="#fnref-{fid}" class="footnote-back" aria-label="Back to text">↩</a>'
            items.append(f'<li id="fn-{fid}">{self.blocks(notes[label])}{back}</li>')
        return '<section class="footnotes" role="doc-endnotes"><hr><ol>' + "".join(items) + "</ol></section>"


def _plain(nodes: list[Inline]) -> str:
    from pbs_core.document.bookmd import inline_text

    return inline_text(nodes)


def sanitize(markup: str, *, allow_data_urls: bool) -> str:
    tags = _HTML_TAGS | _MATHML_TAGS
    attributes: dict[str, set[str]] = {t: set(_GLOBAL_ATTRS) for t in tags}
    attributes["a"] |= {"href"}
    attributes["img"] |= {"src", "alt"}
    attributes["ol"] |= {"start"}
    attributes["input"] |= {"type", "disabled", "checked"}
    for t in _MATHML_TAGS:
        attributes[t] |= _MATH_ATTRS
    schemes = {"http", "https", "mailto"} | ({"data"} if allow_data_urls else set())
    return nh3.clean(
        markup,
        tags=tags,
        attributes=attributes,
        url_schemes=schemes,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


def render(
    doc: dict[str, Any],
    resolve_asset: AssetResolver,
    *,
    external_images: bool = False,
    allow_data_urls: bool = False,
    id_prefix: str = "",
) -> RenderResult:
    r = _Renderer(resolve_asset, external_images=external_images, id_prefix=id_prefix)
    body = r.blocks(doc.get("blocks", []))
    body += r.footnotes(doc.get("footnotes", {}))
    return RenderResult(sanitize(body, allow_data_urls=allow_data_urls), r.warnings)
