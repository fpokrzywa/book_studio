"""BookMD (bookmd-1) -> canonical Book Document Model (bdm/1).

BookMD is CommonMark plus: GFM tables (with an optional ``: Caption {#tbl-id}`` line after the
table), strikethrough, task lists, footnotes, ``$inline$`` / ``$$display$$ (label)`` math,
``{#id .class key="value"}`` attributes, ``[@key, locator]`` citations, ``::: {.class #id}``
fenced divs, and standalone images as figures:
``![Caption](asset:<hash>){#fig-id alt="Alt text" width="60%"}``. Raw HTML is disabled.

The author's source text stays authoritative. The BDM is derived from it deterministically.
Anything the parser cannot model becomes an ``unsupported`` block that keeps its exact source
and raises a fidelity warning: content is never dropped.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import mdit_py_plugins.dollarmath.index as _dollarmath_index
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from pbs_core.domain.wordcount import count_words


def _is_escaped(state: Any, back_pos: int, mod: int = 0) -> bool:
    """Count the backslashes right before ``back_pos`` (fixed copy of the plugin's helper).

    mdit-py-plugins 0.7.0 reads ``src[-1]`` for a dollar sign at the very start of the text, which
    Python wraps to the *last* character: a paragraph ending in a backslash then hid its first inline
    math. Found by the serializer property test.
    """
    backslashes = 0
    i = back_pos - 1
    while i >= 0 and state.src[i] == "\\":
        backslashes += 1
        i -= 1
    return backslashes > 0 and (backslashes % 2) != mod


_dollarmath_index.is_escaped = _is_escaped

PARSER_VERSION = "bookmd-1.0"
BDM_SCHEMA = "bdm/1"

Block = dict[str, Any]
Inline = dict[str, Any]

SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:", "#", "pbs:")
_ATTR_BLOCK = re.compile(r"\s*\{([^{}]*)\}\s*$")
_ATTR_TOKEN = re.compile(r'#([\w:.\-]+)|\.([\w\-]+)|([\w\-]+)=(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'}]+))')
_CITE_GROUP = re.compile(r"\[([^\[\]]*@[^\[\]]*)\]")
_CITE_ITEM = re.compile(r"^\s*(-?)@([\w][\w:.#$%&\-+?<>~/]*)\s*(?:,\s*(.*?))?\s*$")
_ASSET_SRC = re.compile(r"^asset:([0-9a-f]{16})$")
_UNDEFINED_FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\]")


def _md() -> MarkdownIt:
    return (
        MarkdownIt("commonmark", {"html": False})
        .enable(["table", "strikethrough"])
        .use(footnote_plugin)
        .use(dollarmath_plugin, allow_space=True, allow_digits=True, double_inline=False)
        .use(attrs_plugin)
        .use(tasklists_plugin)
        .use(container_plugin, name="div", validate=lambda params, *_: True)
    )


_MD = _md()


@dataclass
class Warning_:
    code: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.line is not None:
            d["line"] = self.line + 1  # 1-based for people
        return d


@dataclass
class ParseResult:
    doc: dict[str, Any]
    word_count: int
    warnings: list[Warning_] = field(default_factory=list)


def normalize_source(source: str) -> str:
    """Line endings to LF (browsers already submit LF); nothing else changes."""
    return source.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode("utf-8")).hexdigest()


def parse_attrs(text: str) -> dict[str, Any]:
    """Parse the inside of ``{#id .class key="v"}`` into {"id","classes","kv"}."""
    out: dict[str, Any] = {}
    classes: list[str] = []
    kv: dict[str, str] = {}
    for m in _ATTR_TOKEN.finditer(text):
        if m.group(1):
            out["id"] = m.group(1)
        elif m.group(2):
            classes.append(m.group(2))
        else:
            kv[m.group(3)] = html.unescape(next(g for g in (m.group(4), m.group(5), m.group(6)) if g is not None))
    if classes:
        out["classes"] = classes
    if kv:
        out["kv"] = kv
    return out


def _split_trailing_attrs(text: str) -> tuple[str, dict[str, Any]]:
    m = _ATTR_BLOCK.search(text)
    if not m:
        return text, {}
    return text[: m.start()], parse_attrs(m.group(1))


class _Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.lines = source.split("\n")
        self.warnings: list[Warning_] = []
        self.footnote_labels: dict[int, str] = {}

    # ---------- inline ----------
    def inlines(self, children: list[Token] | None, line: int | None) -> list[Inline]:
        out: list[Inline] = []
        stack: list[tuple[Inline, list[Inline]]] = []
        node: Inline

        def emit(node: Inline) -> None:
            (stack[-1][1] if stack else out).append(node)

        for tok in children or []:
            t = tok.type
            if t == "text":
                for node in self._text_with_citations(tok.content):
                    emit(node)
            elif t == "softbreak":
                emit({"t": "softbreak"})
            elif t == "hardbreak":
                emit({"t": "hardbreak"})
            elif t == "code_inline":
                emit({"t": "code", "v": tok.content})
            elif t == "math_inline":
                emit({"t": "math", "tex": tok.content})
            elif t == "footnote_ref":
                emit({"t": "footnote_ref", "label": str(tok.meta.get("label"))})
            elif t == "html_inline":
                continue  # only produced by the task-list plugin; checked state is read from the item
            elif t in ("em_open", "strong_open", "s_open"):
                kind = {"em_open": "emph", "strong_open": "strong", "s_open": "strike"}[t]
                node = {"t": kind, "c": []}
                stack.append((node, node["c"]))
            elif t == "link_open":
                href = str(tok.attrs.get("href", ""))
                node = {"t": "link", "href": href, "c": []}  # same Inline type as above
                if tok.attrs.get("title"):
                    node["title"] = str(tok.attrs["title"])
                if not href.lower().startswith(SAFE_LINK_SCHEMES):
                    self.warnings.append(
                        Warning_(
                            "unsafe_link",
                            f"Link target “{href[:60]}” is not allowed and will be shown as plain text.",
                            line,
                        )
                    )
                stack.append((node, node["c"]))
            elif t in ("em_close", "strong_close", "s_close", "link_close"):
                if stack:
                    node, _ = stack.pop()
                    emit(node)
            elif t == "image":
                img: Inline = {
                    "t": "image",
                    "src": str(tok.attrs.get("src", "")),
                    "c": self.inlines(tok.children, line),
                }
                attrs = {k: html.unescape(str(v)) for k, v in tok.attrs.items() if k not in ("src", "alt")}
                if tok.attrs.get("alt"):
                    img["alt"] = html.unescape(str(tok.attrs["alt"]))
                if tok.attrs.get("title"):
                    img["title"] = str(tok.attrs["title"])
                    attrs.pop("title", None)
                if attrs:
                    img["attrs"] = attrs
                emit(img)
            else:
                emit({"t": "text", "v": tok.content})
                self.warnings.append(
                    Warning_("unsupported_inline", f"Unsupported inline element ({t}) kept as text.", line)
                )
        while stack:  # unbalanced (should not happen); flatten
            node, _ = stack.pop()
            emit(node)
        return _merge_text(_currency_guard(out))

    def _text_with_citations(self, text: str) -> Iterator[Inline]:
        pos = 0
        for m in _CITE_GROUP.finditer(text):
            items: list[dict[str, Any]] = []
            for part in m.group(1).split(";"):
                im = _CITE_ITEM.match(part)
                if not im:
                    items = []
                    break
                item: dict[str, Any] = {"key": im.group(2)}
                if im.group(3):
                    item["locator"] = im.group(3)
                if im.group(1):
                    item["suppress_author"] = True
                items.append(item)
            if not items:
                continue
            if m.start() > pos:
                yield {"t": "text", "v": text[pos : m.start()]}
            yield {"t": "cite", "items": items}
            pos = m.end()
        if pos < len(text):
            yield {"t": "text", "v": text[pos:]}

    # ---------- blocks ----------
    def blocks(self, tokens: list[Token], i: int, end_types: tuple[str, ...]) -> tuple[list[Block], int]:
        out: list[Block] = []
        while i < len(tokens):
            tok = tokens[i]
            if tok.type in end_types:
                return out, i
            block, i = self.block(tokens, i)
            if block is not None:
                out.append(block)
        return out, i

    def _span(self, tok: Token) -> list[int] | None:
        return list(tok.map) if tok.map else None

    def block(self, tokens: list[Token], i: int) -> tuple[Block | None, int]:
        tok = tokens[i]
        line = tok.map[0] if tok.map else None
        t = tok.type
        if t == "heading_open":
            inl = tokens[i + 1]
            children = list(inl.children or [])
            attrs: dict[str, Any] = {}
            if children and children[-1].type == "text":
                stripped, attrs = _split_trailing_attrs(children[-1].content)
                if attrs:
                    children[-1] = _copy_text(children[-1], stripped.rstrip())
            block: Block = {"type": "heading", "level": int(tok.tag[1]), "inlines": self.inlines(children, line)}
            if attrs:
                block["attrs"] = attrs
            block["_span"] = self._span(tok)
            return block, _skip_to(tokens, i, "heading_close")
        if t == "paragraph_open":
            inl = tokens[i + 1]
            block = self._paragraph(inl, line)
            if tok.attrs:
                block.setdefault("attrs", {}).update(_html_attrs(tok.attrs))
            block["_span"] = self._span(tok)
            return block, _skip_to(tokens, i, "paragraph_close")
        if t in ("bullet_list_open", "ordered_list_open"):
            return self._list(tokens, i)
        if t == "blockquote_open":
            inner, j = self.blocks(tokens, i + 1, ("blockquote_close",))
            return {"type": "quote", "blocks": inner, "_span": self._span(tok)}, j + 1
        if t in ("fence", "code_block"):
            info = tok.info.strip() if t == "fence" else ""
            lang, attrs = info, {}
            if "{" in info:
                lang, attrs = _split_trailing_attrs(info)
                lang = lang.strip()
            block = {"type": "code", "lang": lang.split()[0] if lang else "", "text": tok.content}
            if attrs:
                block["attrs"] = attrs
            block["_span"] = self._span(tok)
            return block, i + 1
        if t in ("math_block", "math_block_label"):
            tex = tok.content.strip("\n")
            block = {"type": "math_block", "tex": tex}
            if t == "math_block_label" and tok.info:
                block["attrs"] = {"id": tok.info}
            block["_span"] = self._span(tok)
            return block, i + 1
        if t == "hr":
            return {"type": "thematic_break", "_span": self._span(tok)}, i + 1
        if t == "table_open":
            return self._table(tokens, i)
        if t == "container_div_open":
            if "{" in tok.info:
                _, attrs = _split_trailing_attrs(tok.info)
            else:
                words = [w.lstrip(".") for w in tok.info.split() if w]
                attrs = {"classes": words} if words else {}
            inner, j = self.blocks(tokens, i + 1, ("container_div_close",))
            block = {"type": "div", "blocks": inner}
            if attrs:
                block["attrs"] = attrs
            block["_span"] = self._span(tok)
            return block, j + 1
        if t == "footnote_block_open":
            j = i + 1
            while j < len(tokens) and tokens[j].type != "footnote_block_close":
                if tokens[j].type == "footnote_open":
                    label = str(tokens[j].meta.get("label"))
                    inner, k = self.blocks(tokens, j + 1, ("footnote_close",))
                    self.footnotes[label] = inner
                    j = k + 1
                else:
                    j += 1
            return None, j + 1
        if t == "footnote_anchor":
            return None, i + 1
        # Anything else: keep its source verbatim.
        span = self._span(tok)
        raw = "\n".join(self.lines[span[0] : span[1]]) if span else tok.content
        self.warnings.append(
            Warning_("unsupported_block", f"Unsupported content ({t}) is kept as-is but not formatted.", line)
        )
        return {"type": "unsupported", "raw": raw, "_span": span}, i + 1

    footnotes: dict[str, list[Block]]

    def _paragraph(self, inl: Token, line: int | None) -> Block:
        children = list(inl.children or [])
        # A paragraph that is only an image (+ optional attribute text) is a figure.
        meaningful = [c for c in children if not (c.type == "text" and not c.content.strip())]
        if meaningful and meaningful[0].type == "image" and len(meaningful) <= 2:
            img = meaningful[0]
            trailing_attrs: dict[str, Any] = {}
            if len(meaningful) == 2:
                if meaningful[1].type != "text":
                    return {"type": "paragraph", "inlines": self.inlines(children, line)}
                rest, trailing_attrs = _split_trailing_attrs(meaningful[1].content)
                if rest.strip() or not trailing_attrs:
                    return {"type": "paragraph", "inlines": self.inlines(children, line)}
            html_attrs = {k: html.unescape(str(v)) for k, v in img.attrs.items() if k not in ("src", "alt", "title")}
            attrs = _merge_attrs(_html_attrs(html_attrs), trailing_attrs)
            kv = attrs.pop("kv", {})
            explicit = html.unescape(str(img.attrs.get("alt") or ""))  # set by the attrs plugin from {alt="..."}
            alt = kv.pop("alt", None) or (explicit or None)
            figure: Block = {
                "type": "figure",
                "src": str(img.attrs.get("src", "")),
                "caption": self.inlines(img.children, line),
            }
            if alt is not None:
                figure["alt"] = alt
            if img.attrs.get("title"):
                figure["title"] = str(img.attrs["title"])
            if kv:
                attrs["kv"] = kv
            if attrs:
                figure["attrs"] = attrs
            if alt is None or not alt.strip():
                self.warnings.append(
                    Warning_(
                        "missing_alt", 'Figure has no alt text. Add alt="…" so screen readers can describe it.', line
                    )
                )
            return figure
        return {"type": "paragraph", "inlines": self.inlines(children, line)}

    def _list(self, tokens: list[Token], i: int) -> tuple[Block, int]:
        open_tok = tokens[i]
        ordered = open_tok.type == "ordered_list_open"
        close = "ordered_list_close" if ordered else "bullet_list_close"
        block: Block = {"type": "list", "ordered": ordered, "tight": True, "items": []}
        if ordered:
            start = open_tok.attrs.get("start")
            block["start"] = int(start) if start is not None else 1
        task = "contains-task-list" in str(open_tok.attrs.get("class", ""))
        j = i + 1
        while j < len(tokens) and tokens[j].type != close:
            if tokens[j].type == "list_item_open":
                item_tok = tokens[j]
                checked: bool | None = None
                if "task-list-item" in str(item_tok.attrs.get("class", "")):
                    checked = False
                    for k in range(j + 1, min(j + 4, len(tokens))):
                        if tokens[k].type == "inline":
                            kids = list(tokens[k].children or [])
                            if kids and kids[0].type == "html_inline":
                                checked = 'checked="checked"' in kids[0].content
                                kids = kids[1:]
                                if kids and kids[0].type == "text":
                                    kids[0] = _copy_text(kids[0], kids[0].content.lstrip(" "))
                                tokens[k].children = kids
                            break
                for k in range(j + 1, len(tokens)):
                    if tokens[k].type == "paragraph_open":
                        if not tokens[k].hidden:
                            block["tight"] = False
                        break
                    if tokens[k].type == "list_item_close":
                        break
                inner, k = self.blocks(tokens, j + 1, ("list_item_close",))
                item: dict[str, Any] = {"blocks": inner}
                if checked is not None:
                    item["checked"] = checked
                block["items"].append(item)
                j = k + 1
            else:
                j += 1
        if task:
            block["task"] = True
        block["_span"] = self._span(open_tok)
        return block, j + 1

    def _table(self, tokens: list[Token], i: int) -> tuple[Block, int]:
        open_tok = tokens[i]
        align: list[str | None] = []
        head: list[list[Inline]] = []
        rows: list[list[list[Inline]]] = []
        current: list[list[Inline]] | None = None
        in_head = False
        j = i + 1
        while tokens[j].type != "table_close":
            tt = tokens[j].type
            if tt == "thead_open":
                in_head = True
            elif tt == "thead_close":
                in_head = False
            elif tt == "tr_open":
                current = []
            elif tt == "tr_close":
                if current is not None and not in_head:
                    rows.append(current)
                current = None
            elif tt in ("th_open", "td_open"):
                style = str(tokens[j].attrs.get("style", ""))
                cell_map = tokens[j + 1].map
                cell = self.inlines(tokens[j + 1].children, cell_map[0] if cell_map else None)
                if in_head:
                    head.append(cell)
                    align.append(style.split(":", 1)[1] if style.startswith("text-align:") else None)
                elif current is not None:
                    current.append(cell)
            j += 1
        return {"type": "table", "align": align, "head": head, "rows": rows, "_span": self._span(open_tok)}, j + 1


def _skip_to(tokens: list[Token], i: int, close: str) -> int:
    """Index after the matching close token (footnote anchors can sit before a paragraph_close)."""
    j = i + 1
    while j < len(tokens) and tokens[j].type != close:
        j += 1
    return j + 1


def _currency_guard(nodes: list[Inline]) -> list[Inline]:
    """``$5 and $6`` is money, not math: a ``$`` touching a digit outside the math is literal text.

    (Implemented here instead of the plugin's allow_digits option, whose check misreads the
    character before a ``$`` at the very start of a line.)
    """
    out: list[Inline] = []
    for i, n in enumerate(nodes):
        if n["t"] == "math":
            prev = out[-1] if out else None
            nxt = nodes[i + 1] if i + 1 < len(nodes) else None
            before = prev is not None and prev["t"] == "text" and prev["v"][-1:].isdigit()
            after = nxt is not None and nxt["t"] == "text" and nxt["v"][:1].isdigit()
            if before or after:
                out.append({"t": "text", "v": "$" + n["tex"] + "$"})
                continue
        if "c" in n:
            n = {**n, "c": _currency_guard(n["c"])}
        out.append(n)
    return out


def _copy_text(tok: Token, content: str) -> Token:
    new = Token("text", "", 0)
    new.content = content
    return new


def _html_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    kv: dict[str, str] = {}
    for k, v in attrs.items():
        if k == "id":
            out["id"] = str(v)
        elif k == "class":
            out["classes"] = str(v).split()
        else:
            kv[str(k)] = str(v)
    if kv:
        out["kv"] = kv
    return out


def _merge_attrs(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    if "id" in b:
        out["id"] = b["id"]
    if b.get("classes"):
        out["classes"] = [*out.get("classes", []), *b["classes"]]
    if b.get("kv"):
        out["kv"] = {**out.get("kv", {}), **b["kv"]}
    return out


def _merge_text(nodes: list[Inline]) -> list[Inline]:
    out: list[Inline] = []
    for n in nodes:
        if n["t"] == "text" and out and out[-1]["t"] == "text":
            out[-1] = {"t": "text", "v": out[-1]["v"] + n["v"]}
        elif n["t"] == "text" and n["v"] == "":
            continue
        else:
            out.append(n)
    return out


def _attach_table_captions(blocks: list[Block]) -> list[Block]:
    """A paragraph starting with ': ' directly after a table is that table's caption."""
    out: list[Block] = []
    for b in blocks:
        if (
            b["type"] == "paragraph"
            and out
            and out[-1]["type"] == "table"
            and "caption" not in out[-1]
            and b["inlines"]
            and b["inlines"][0]["t"] == "text"
            and b["inlines"][0]["v"].startswith(": ")
        ):
            inl = [dict(x) for x in b["inlines"]]
            inl[0] = {"t": "text", "v": inl[0]["v"][2:]}
            attrs: dict[str, Any] = {}
            if inl[-1]["t"] == "text":
                stripped, attrs = _split_trailing_attrs(inl[-1]["v"])
                if attrs:
                    inl[-1] = {"t": "text", "v": stripped.rstrip()}
            out[-1]["caption"] = _merge_text(inl)
            if attrs:
                out[-1]["attrs"] = attrs
            span = b.get("_span")
            if span and out[-1].get("_span"):
                out[-1]["_span"] = [out[-1]["_span"][0], span[1]]
            continue
        for key in ("blocks",):
            if key in b:
                b[key] = _attach_table_captions(b[key])
        if b["type"] == "list":
            for item in b["items"]:
                item["blocks"] = _attach_table_captions(item["blocks"])
        out.append(b)
    return out


# ---------- IDs, hashing, words ----------


def strip_ids(value: Any) -> Any:
    """Structural view for equality: no block IDs, source spans or hashes (anchors in attrs are kept)."""
    if isinstance(value, dict):
        is_block = "type" in value
        return {
            k: strip_ids(v)
            for k, v in value.items()
            if k not in ("_span", "src_lines", "hash") and not (k == "id" and is_block)
        }
    if isinstance(value, list):
        return [strip_ids(v) for v in value]
    return value


def _block_hash(block: Block) -> str:
    canon = json.dumps(strip_ids(block), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _walk_blocks(blocks: list[Block]) -> Iterator[Block]:
    for b in blocks:
        yield b
        if "blocks" in b:
            yield from _walk_blocks(b["blocks"])
        if b["type"] == "list":
            for item in b["items"]:
                yield from _walk_blocks(item["blocks"])


def inline_text(nodes: list[Inline]) -> str:
    parts: list[str] = []
    for n in nodes:
        t = n["t"]
        if t == "text":
            parts.append(n["v"])
        elif t in ("emph", "strong", "strike", "link", "image"):
            parts.append(inline_text(n.get("c", [])))
        elif t == "code":
            parts.append(n["v"])
        elif t in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)


def _block_words(b: Block) -> int:
    t = b["type"]
    if t in ("heading", "paragraph"):
        return count_words(inline_text(b["inlines"]))
    if t == "table":
        cells = [*b["head"], *(c for row in b["rows"] for c in row)]
        total = sum(count_words(inline_text(c)) for c in cells)
        return total + count_words(inline_text(b.get("caption", [])))
    if t == "figure":
        return count_words(inline_text(b["caption"]))
    return 0


def assign_ids(doc: dict[str, Any], new_id: Callable[[], str], previous: dict[str, Any] | None) -> None:
    """Give every block an ID, reusing IDs of structurally identical blocks from the previous revision.

    Explicit anchors ({#id}) always map to the same block ID.
    """
    by_anchor: dict[str, str] = {}
    by_hash: dict[str, list[str]] = {}
    if previous and previous.get("schema") == BDM_SCHEMA:
        prev_blocks = list(_walk_blocks(previous.get("blocks", [])))
        for fn in previous.get("footnotes", {}).values():
            prev_blocks.extend(_walk_blocks(fn))
        for b in prev_blocks:
            if "id" not in b:
                continue
            anchor = b.get("attrs", {}).get("id")
            if anchor:
                by_anchor.setdefault(anchor, b["id"])
            by_hash.setdefault(b.get("hash", ""), []).append(b["id"])
    used: set[str] = set()

    def give(b: Block) -> None:
        h = _block_hash(b)
        b["hash"] = h
        anchor = b.get("attrs", {}).get("id")
        candidate = by_anchor.get(anchor) if anchor else None
        if candidate is None or candidate in used:
            candidate = next((x for x in by_hash.get(h, []) if x not in used), None)
        b["id"] = candidate or f"b_{new_id()}"
        used.add(b["id"])

    all_blocks = list(_walk_blocks(doc["blocks"]))
    for fn in doc.get("footnotes", {}).values():
        all_blocks.extend(_walk_blocks(fn))
    for b in all_blocks:
        give(b)


def parse(
    source: str,
    *,
    chapter_id: str,
    new_id: Callable[[], str],
    previous: dict[str, Any] | None = None,
) -> ParseResult:
    text = normalize_source(source)
    p = _Parser(text)
    p.footnotes = {}
    tokens = _MD.parse(text)
    blocks, _ = p.blocks(tokens, 0, ())
    blocks = _attach_table_captions(blocks)
    for b in blocks:  # keep top-level source line ranges for editor mapping
        span = b.get("_span")
        if span:
            b["src_lines"] = span
    for b in _walk_blocks(blocks):
        b.pop("_span", None)
    footnotes = p.footnotes
    for fn in footnotes.values():
        for b in _walk_blocks(fn):
            b.pop("_span", None)

    doc: dict[str, Any] = {"schema": BDM_SCHEMA, "parser": PARSER_VERSION, "chapter_id": chapter_id, "blocks": blocks}
    if footnotes:
        doc["footnotes"] = footnotes
    assign_ids(doc, new_id, previous)
    _check_references(doc, p.warnings)

    words = sum(_block_words(b) for b in _walk_blocks(blocks))
    words += sum(_block_words(b) for fn in footnotes.values() for b in _walk_blocks(fn))
    return ParseResult(doc, words, p.warnings)


def iter_inlines(nodes: list[Inline]) -> Iterator[Inline]:
    for n in nodes:
        yield n
        if "c" in n:
            yield from iter_inlines(n["c"])


def iter_all_inlines(doc: dict[str, Any]) -> Iterator[Inline]:
    blocks = list(_walk_blocks(doc.get("blocks", [])))
    for fn in doc.get("footnotes", {}).values():
        blocks.extend(_walk_blocks(fn))
    for b in blocks:
        for key in ("inlines", "caption"):
            if key in b:
                yield from iter_inlines(b[key])
        if b["type"] == "table":
            for cell in [*b["head"], *(c for row in b["rows"] for c in row)]:
                yield from iter_inlines(cell)


def walk_blocks(doc: dict[str, Any]) -> Iterator[Block]:
    yield from _walk_blocks(doc.get("blocks", []))
    for fn in doc.get("footnotes", {}).values():
        yield from _walk_blocks(fn)


def asset_refs(doc: dict[str, Any]) -> set[str]:
    """Asset hashes referenced by figures and inline images (``asset:<16 hex>``)."""
    refs: set[str] = set()
    for b in walk_blocks(doc):
        if b["type"] == "figure":
            m = _ASSET_SRC.match(b["src"])
            if m:
                refs.add(m.group(1))
    for n in iter_all_inlines(doc):
        if n["t"] == "image":
            m = _ASSET_SRC.match(n["src"])
            if m:
                refs.add(m.group(1))
    return refs


def citation_keys(doc: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for n in iter_all_inlines(doc):
        if n["t"] == "cite":
            for item in n["items"]:
                if item["key"] not in keys:
                    keys.append(item["key"])
    return keys


def _check_references(doc: dict[str, Any], warnings: list[Warning_]) -> None:
    labels = set(doc.get("footnotes", {}).keys())
    for n in iter_all_inlines(doc):
        if n["t"] == "footnote_ref" and n["label"] not in labels:
            warnings.append(Warning_("missing_footnote", f"Footnote [^{n['label']}] has no text."))
        elif n["t"] == "text":
            for m in _UNDEFINED_FOOTNOTE.finditer(n["v"]):
                warnings.append(
                    Warning_("missing_footnote", f"Footnote [^{m.group(1)}] has no text, so it is shown as written.")
                )
    seen: set[str] = set()
    for b in walk_blocks(doc):
        anchor = b.get("attrs", {}).get("id")
        if anchor:
            if anchor in seen:
                warnings.append(Warning_("duplicate_anchor", f"The anchor #{anchor} is used more than once."))
            seen.add(anchor)
        src = b.get("src") if b["type"] == "figure" else None
        if src and src.startswith(("http://", "https://")):
            warnings.append(
                Warning_(
                    "external_image",
                    "An image points to the web. It is not loaded in preview (privacy) and should be imported as a file.",
                )
            )
        elif src and not _ASSET_SRC.match(src) and not src.startswith(("http://", "https://")):
            warnings.append(
                Warning_("unresolved_image", f"Image “{src[:60]}” is not a project asset and cannot be shown.")
            )
