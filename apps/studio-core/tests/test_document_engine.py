"""bookmd-1 / bdm/1: structure, lossless round trip, IDs, HTML rendering and sanitization."""

import itertools
import string
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from pbs_core.document import bookmd, serialize
from pbs_core.document import html as html_render

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
KITCHEN = (FIXTURES / "bookmd" / "kitchen-sink.md").read_text(encoding="utf-8")


def ids():
    counter = itertools.count()
    return lambda: f"{next(counter):026d}"


def parse(text: str, previous: dict[str, Any] | None = None) -> bookmd.ParseResult:
    return bookmd.parse(text, chapter_id="C", new_id=ids(), previous=previous)


def types(doc: dict[str, Any]) -> list[str]:
    return [b["type"] for b in bookmd.walk_blocks(doc)]


def test_kitchen_sink_structure() -> None:
    r = parse(KITCHEN)
    doc = r.doc
    assert doc["schema"] == "bdm/1"
    t = types(doc)
    for expected in [
        "heading",
        "paragraph",
        "list",
        "quote",
        "table",
        "code",
        "math_block",
        "figure",
        "div",
        "thematic_break",
    ]:
        assert expected in t, expected
    heading = doc["blocks"][0]
    assert heading["attrs"] == {"id": "kitchen"} and bookmd.inline_text(heading["inlines"]) == "The Kitchen Sink"

    fig = next(b for b in bookmd.walk_blocks(doc) if b["type"] == "figure")
    assert fig["src"] == "asset:0123456789abcdef"
    assert fig["alt"] == "Line drawing of a small two-stroke engine"
    assert bookmd.inline_text(fig["caption"]) == "The engine at rest, seen from the left"  # caption != alt
    assert fig["attrs"]["id"] == "fig-engine" and fig["attrs"]["kv"]["width"] == "60%"

    table = next(b for b in bookmd.walk_blocks(doc) if b["type"] == "table")
    assert table["align"] == ["left", "right", "center"]
    assert bookmd.inline_text(table["caption"]) == "Fastener torque values"
    assert table["attrs"]["id"] == "tbl-torque"
    assert bookmd.inline_text(table["rows"][1][2]) == "a | b"

    code = next(b for b in bookmd.walk_blocks(doc) if b["type"] == "code")
    assert code["lang"] == "python" and code["attrs"]["id"] == "lst-start"
    assert "\treturn engine.ignite()  # tab and trailing spaces kept  \n" in code["text"]

    math = next(b for b in bookmd.walk_blocks(doc) if b["type"] == "math_block")
    assert math["tex"] == r"\int_0^1 x^2 \, dx = \frac{1}{3}" and math["attrs"]["id"] == "eq-area"

    tasks = [b for b in bookmd.walk_blocks(doc) if b["type"] == "list" and b.get("task")]
    assert [i["checked"] for i in tasks[0]["items"]] == [False, True]

    div = next(b for b in bookmd.walk_blocks(doc) if b["type"] == "div")
    assert div["attrs"] == {"classes": ["callout-note"], "id": "note-safety"}

    assert bookmd.citation_keys(doc) == ["smith2020", "doe2019", "roe2021"]
    cites = [n for n in bookmd.iter_all_inlines(doc) if n["t"] == "cite"]
    assert cites[0]["items"] == [{"key": "smith2020", "locator": "p. 12"}]
    assert cites[1]["items"][1] == {"key": "roe2021", "suppress_author": True}
    assert set(doc["footnotes"]) == {"note"}
    assert bookmd.asset_refs(doc) == {"0123456789abcdef"}
    assert r.warnings == []
    assert r.word_count > 80


def test_kitchen_sink_round_trips_through_the_serializer() -> None:
    first = parse(KITCHEN).doc
    text = serialize.serialize(first)
    second = parse(text).doc
    assert bookmd.strip_ids(first) == bookmd.strip_ids(second)
    assert serialize.serialize(second) == text  # normal form is stable


def test_block_ids_stable_across_edits_and_anchors_win() -> None:
    first = parse(KITCHEN).doc
    edited = KITCHEN.replace("Second quote paragraph.", "Second quote paragraph, edited.")
    edited = edited.replace("# The Kitchen Sink {#kitchen}", "# The Renamed Sink {#kitchen}")
    second = parse(edited, previous=first).doc
    a = {b["id"] for b in bookmd.walk_blocks(first)}
    b = {b["id"] for b in bookmd.walk_blocks(second)}
    assert first["blocks"][0]["id"] == second["blocks"][0]["id"]  # explicit anchor kept the ID
    assert len(a & b) >= len(a) - 2  # only the edited quote (and its paragraph) got new IDs


def test_warnings_for_lossy_or_risky_content() -> None:
    r = parse(
        '![No alt](asset:0123456789abcdef)\n\n![Web](https://example.com/x.png){alt="x"}\n\n'
        '![Local](images/a.png){alt="y"}\n\nText[^missing]\n\n# A {#dup}\n\n# B {#dup}\n'
    )
    codes = [w.code for w in r.warnings]
    for code in ["missing_alt", "external_image", "unresolved_image", "missing_footnote", "duplicate_anchor"]:
        assert code in codes, code


def test_raw_html_is_text_not_markup() -> None:
    r = parse("<script>alert(1)</script>\n\nHello <b onclick=x>there</b>\n")
    rendered = html_render.render(r.doc, lambda h: None).html
    assert "<script" not in rendered and "<b" not in rendered
    assert "&lt;script&gt;" in rendered


def test_html_render_and_sanitization() -> None:
    doc = parse(KITCHEN).doc
    out = html_render.render(doc, lambda h: f"/api/projects/P/assets/{h}")
    h = out.html
    assert '<figure id="fig-engine"><img src="/api/projects/P/assets/0123456789abcdef" alt="Line drawing' in h
    assert "<figcaption>The engine at rest, seen from the left</figcaption>" in h
    assert "<caption>Fastener torque values</caption>" in h
    assert '<code class="language-python">' in h and "\treturn engine.ignite()" in h
    assert "<math" in h and 'class="math display"' in h
    assert '<cite class="citation" data-keys="smith2020">' in h
    assert 'class="footnotes"' in h and 'id="fn-note"' in h
    assert '<input type="checkbox" disabled' in h
    assert 'rel="noopener noreferrer"' in h


def test_unsafe_links_and_external_images_are_inert() -> None:
    doc = {
        "schema": "bdm/1",
        "blocks": [
            {
                "type": "paragraph",
                "inlines": [{"t": "link", "href": "javascript:alert(1)", "c": [{"t": "text", "v": "x"}]}],
            },
            {"type": "figure", "src": "https://tracker.example/p.png", "alt": "a", "caption": []},
        ],
    }
    h = html_render.render(doc, lambda _: None).html
    assert "javascript:" not in h and 'class="unsafe-link"' in h
    assert "tracker.example/p.png" not in h.split("Image not loaded")[0]
    assert "<img" not in h


# ---------- property-based round trip ----------

words = (
    st.text(
        alphabet=string.ascii_letters + string.digits + " .,;:!?'\"()&#*_[]<>$~|{}\\-+=@^%/", min_size=1, max_size=25
    )
    .map(lambda s: " ".join(s.split()))
    .filter(bool)
)
plain = st.builds(lambda v: {"t": "text", "v": v}, words)
code_inline = st.builds(
    lambda v: {"t": "code", "v": v},
    st.text(alphabet=string.ascii_letters + " `*_", min_size=1, max_size=10).filter(
        lambda s: s.strip() and s == s.strip()
    ),
)
math_inline = st.builds(
    lambda v: {"t": "math", "tex": v}, st.sampled_from(["x^2", r"\frac{a}{b}", "E=mc^2", r"\alpha+\beta"])
)
cite = st.builds(
    lambda k, loc: {"t": "cite", "items": [{"key": k, **({"locator": loc} if loc else {})}]},
    st.from_regex(r"[a-z][a-z0-9]{1,8}", fullmatch=True),
    st.sampled_from(["", "p. 3", "ch. 2"]),
)
emph = st.builds(
    lambda v: {"t": "emph", "c": [{"t": "text", "v": v}]}, words.filter(lambda s: s[0].isalnum() and s[-1].isalnum())
)
strong = st.builds(
    lambda v: {"t": "strong", "c": [{"t": "text", "v": v}]}, words.filter(lambda s: s[0].isalnum() and s[-1].isalnum())
)
link = st.builds(
    lambda v, u: {"t": "link", "href": u, "c": [{"t": "text", "v": v}]},
    words,
    st.sampled_from(["https://example.com/a", "https://example.com/a%20b", "mailto:a@b.c", "#anchor"]),
)
inline_seq = st.lists(st.one_of(plain, code_inline, math_inline, cite, emph, strong, link), min_size=1, max_size=6)


def _separate(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put a space between neighbours, as a writer would (avoids ambiguous adjacency)."""
    out: list[dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if i:
            out.append({"t": "text", "v": " "})
        out.append(n)
    return bookmd._merge_text(out)


paragraph = st.builds(lambda c: {"type": "paragraph", "inlines": _separate(c)}, inline_seq)
heading = st.builds(
    lambda lvl, c: {"type": "heading", "level": lvl, "inlines": _separate(c)}, st.integers(1, 6), inline_seq
)
codeblock = st.builds(
    lambda lang, text: {"type": "code", "lang": lang, "text": text},
    st.sampled_from(["", "python", "bash"]),
    st.text(alphabet=string.printable.replace("\r", "").replace("\x0b", "").replace("\x0c", ""), max_size=60).map(
        lambda s: s if s.endswith("\n") else s + "\n"
    ),
)
table = st.builds(
    lambda h, rows, al: {"type": "table", "align": al[: len(h)] + [None] * (len(h) - len(al[: len(h)])),
                         "head": [[{"t": "text", "v": x}] for x in h],
                         "rows": [[[{"t": "text", "v": c}] for c in r[: len(h)]] + [[] for _ in range(len(h) - len(r[: len(h)]))] for r in rows]},
    st.lists(words, min_size=1, max_size=3),
    st.lists(st.lists(words, min_size=1, max_size=3), max_size=3),
    st.lists(st.sampled_from([None, "left", "right", "center"]), max_size=3),
)  # fmt: skip
math_block = st.builds(lambda t: {"type": "math_block", "tex": t}, st.sampled_from(["x^2", r"\int_0^1 f(x)\,dx"]))
figure = st.builds(
    lambda cap, alt: {
        "type": "figure",
        "src": "asset:0123456789abcdef",
        "caption": [{"t": "text", "v": cap}],
        "alt": alt,
    },
    words,
    words,
)
blocks = st.lists(st.one_of(paragraph, heading, codeblock, table, math_block, figure), min_size=1, max_size=6)


@settings(max_examples=150, deadline=None)
@given(blocks)
def test_property_serialize_then_parse_is_identity(bl: list[dict[str, Any]]) -> None:
    doc = {"schema": "bdm/1", "blocks": bl}
    text = serialize.serialize(doc)
    parsed = parse(text).doc
    assert bookmd.strip_ids(parsed["blocks"]) == bookmd.strip_ids(bl), text


def test_attribute_values_with_backslashes_round_trip() -> None:
    """Hypothesis counterexample (Phase 03 run): alt text ending in a backslash escaped the closing quote."""
    for alt in ("\\", 'a\\"b', "C:\\path\\", r"{\}"):
        bl = [{"type": "figure", "src": "asset:0123456789abcdef", "caption": [{"t": "text", "v": "0"}], "alt": alt}]
        text = serialize.serialize({"schema": "bdm/1", "blocks": bl})
        assert bookmd.strip_ids(parse(text).doc["blocks"]) == bookmd.strip_ids(bl), text
