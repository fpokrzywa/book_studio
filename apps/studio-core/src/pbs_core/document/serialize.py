"""bdm/1 -> BookMD source (normal form).

Used when content enters the studio from a structured source (HTML, DOCX, text, PDF imports)
and for round-trip verification. Invariant (tested): parse(serialize(doc)) is structurally
equal to doc, ignoring block IDs and source spans.
"""

from __future__ import annotations

import re
from typing import Any

Block = dict[str, Any]
Inline = dict[str, Any]

_ALWAYS_ESCAPE = set("\\`*_[]<>$~|{}")
_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_ORDERED_START = re.compile(r"^(\d{1,9})([.)])")
_URL_NEEDS_BRACKETS = re.compile(r"[\s()<>]")


def escape_text(text: str, *, at_line_start: bool) -> str:
    out: list[str] = []
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in _ALWAYS_ESCAPE or (ch == "!" and nxt == "["):
            out.append("\\" + ch)
        elif ch == "&" and _ENTITY.match(text, i):
            out.append("\\&")
        else:
            out.append(ch)
    s = "".join(out)
    if at_line_start:
        if s[:1] in ("#", ">", "-", "+", "=", ":"):
            s = "\\" + s
        else:
            m = _ORDERED_START.match(s)
            if m:
                s = m.group(1) + "\\" + s[len(m.group(1)) :]
    return s


def _code_span(v: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", v)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if v.startswith("`") or v.endswith("`") or (v.startswith(" ") and v.endswith(" ") and v.strip()) else ""
    return f"{fence}{pad}{v}{pad}{fence}"


def _url(href: str) -> str:
    if _URL_NEEDS_BRACKETS.search(href) or href == "":
        return "<" + href.replace("<", "%3C").replace(">", "%3E") + ">"
    return href.replace("\\", "\\\\")


def _title(title: str | None) -> str:
    if not title:
        return ""
    return ' "' + title.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _attr_value(v: str) -> str:
    """Attribute values are entity-escaped so quotes and braces cannot end the attribute block."""
    return (
        v.replace("&", "&amp;")
        .replace("\\", "&#92;")  # a trailing backslash would otherwise escape the closing quote
        .replace('"', "&quot;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
    )


def attrs_text(attrs: dict[str, Any] | None, extra_kv: dict[str, str] | None = None) -> str:
    if not attrs and not extra_kv:
        return ""
    parts: list[str] = []
    attrs = attrs or {}
    if attrs.get("id"):
        parts.append("#" + attrs["id"])
    parts.extend("." + c for c in attrs.get("classes", []))
    kv = {**(extra_kv or {}), **attrs.get("kv", {})}
    for k, v in kv.items():
        parts.append(f'{k}="{_attr_value(v)}"')
    return "{" + " ".join(parts) + "}" if parts else ""


def inlines(nodes: list[Inline], *, line_start: bool = True) -> str:
    out: list[str] = []
    at_start = line_start
    for n in nodes:
        t = n["t"]
        if t == "text":
            out.append(escape_text(n["v"], at_line_start=at_start))
        elif t == "softbreak":
            out.append("\n")
            at_start = True
            continue
        elif t == "hardbreak":
            out.append("\\\n")
            at_start = True
            continue
        elif t == "code":
            out.append(_code_span(n["v"]))
        elif t == "math":
            out.append(f"${n['tex']}$")
        elif t == "emph":
            out.append("*" + inlines(n["c"], line_start=False) + "*")
        elif t == "strong":
            out.append("**" + inlines(n["c"], line_start=False) + "**")
        elif t == "strike":
            out.append("~~" + inlines(n["c"], line_start=False) + "~~")
        elif t == "link":
            out.append(f"[{inlines(n['c'], line_start=False)}]({_url(n['href'])}{_title(n.get('title'))})")
        elif t == "image":
            kv = {**({"alt": n["alt"]} if n.get("alt") else {}), **n.get("attrs", {})}
            attrs = attrs_text({"kv": kv} if kv else None)
            out.append(f"![{inlines(n['c'], line_start=False)}]({_url(n['src'])}{_title(n.get('title'))}){attrs}")
        elif t == "cite":
            items = []
            for it in n["items"]:
                s = ("-" if it.get("suppress_author") else "") + "@" + it["key"]
                if it.get("locator"):
                    s += ", " + it["locator"]
                items.append(s)
            out.append("[" + "; ".join(items) + "]")
        elif t == "footnote_ref":
            out.append(f"[^{n['label']}]")
        else:  # pragma: no cover - unknown inline types are never produced by the parser
            out.append(escape_text(str(n.get("v", "")), at_line_start=at_start))
        at_start = False
    return "".join(out)


def _indent(text: str, prefix: str, first: str | None = None) -> str:
    lines = text.split("\n")
    res = []
    for i, line in enumerate(lines):
        p = first if (i == 0 and first is not None) else prefix
        res.append((p + line) if line else p.rstrip())
    return "\n".join(res)


def block(b: Block, depth: int = 0) -> str:
    t = b["type"]
    if t == "heading":
        text = inlines(b["inlines"], line_start=False)
        attrs = attrs_text(b.get("attrs"))
        return "#" * int(b["level"]) + " " + text + (" " + attrs if attrs else "")
    if t == "paragraph":
        return inlines(b["inlines"])
    if t == "thematic_break":
        return "***"
    if t == "code":
        text = b["text"]
        longest = max((len(m) for m in re.findall(r"`{3,}", text)), default=0)
        fence = "`" * max(3, longest + 1)
        info = b.get("lang", "")
        attrs = attrs_text(b.get("attrs"))
        if attrs:
            info = (info + " " + attrs).strip()
        body = text if text.endswith("\n") or text == "" else text + "\n"
        return f"{fence}{info}\n{body}{fence}"
    if t == "math_block":
        label = b.get("attrs", {}).get("id")
        return f"$$\n{b['tex']}\n$$" + (f" ({label})" if label else "")
    if t == "quote":
        inner = blocks(b["blocks"], depth)
        return "\n".join(("> " + line) if line else ">" for line in inner.split("\n"))
    if t == "list":
        parts = []
        n = b.get("start", 1)
        for idx, item in enumerate(b["items"]):
            marker = f"{n + idx}. " if b["ordered"] else "- "
            sep = "\n" if b.get("tight", True) else "\n\n"
            body = sep.join(block(x, depth) for x in item["blocks"])
            if "checked" in item:
                body = ("[x] " if item["checked"] else "[ ] ") + body
            if not body:
                parts.append(marker.rstrip())
                continue
            parts.append(_indent(body, " " * len(marker), first=marker))
        return ("\n" if b.get("tight", True) else "\n\n").join(parts)
    if t == "table":

        def row(cells: list[list[Inline]]) -> str:
            return "| " + " | ".join(inlines(c, line_start=False) or " " for c in cells) + " |"

        delim = []
        for a in b["align"]:
            delim.append({"left": ":---", "right": "---:", "center": ":---:"}.get(a or "", "---"))
        lines = [row(b["head"]), "| " + " | ".join(delim) + " |", *(row(r) for r in b["rows"])]
        out = "\n".join(lines)
        if "caption" in b:
            attrs = attrs_text(b.get("attrs"))
            out += "\n\n: " + inlines(b["caption"], line_start=False) + (" " + attrs if attrs else "")
        return out
    if t == "figure":
        fig_attrs = dict(b.get("attrs", {}))
        extra = {"alt": str(b["alt"])} if b.get("alt") is not None else None
        return f"![{inlines(b['caption'], line_start=False)}]({_url(b['src'])}{_title(b.get('title'))})" + attrs_text(
            fig_attrs, extra
        )
    if t == "div":
        fence = ":" * (3 + _div_depth(b))
        attrs = attrs_text(b.get("attrs")) or "{}"
        return f"{fence} {attrs}\n{blocks(b['blocks'], depth + 1)}\n{fence}"
    if t == "unsupported":
        return str(b["raw"])
    raise ValueError(f"unknown block type {t}")  # pragma: no cover


def _div_depth(b: Block) -> int:
    inner = [x for x in b["blocks"] if x["type"] == "div"]
    return 1 + max((_div_depth(x) for x in inner), default=0) if inner else 0


def blocks(items: list[Block], depth: int = 0) -> str:
    return "\n\n".join(block(b, depth) for b in items)


def serialize(doc: dict[str, Any]) -> str:
    parts = [blocks(doc.get("blocks", []))]
    for label, fn_blocks in doc.get("footnotes", {}).items():
        body = blocks(fn_blocks)
        parts.append(_indent(body, "    ", first=f"[^{label}]: "))
    text = "\n\n".join(p for p in parts if p)
    return text + "\n" if text else ""
