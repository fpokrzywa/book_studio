import itertools

from pbs_core.document import bookmd_v0

KITCHEN = """# Title {#t}

Para with *emph*, `code`, $E=mc^2$ and a citation [@key, p. 3][^1].

| a | b |
|---|--:|
| 1 | 2 |

```python
def f():\tpass  
```

- one
- two
  - nested

> quote

<script>alert(1)</script>

[^1]: A footnote.
"""


def _ids():
    counter = itertools.count()
    return lambda: f"B{next(counter):025d}"


def test_every_block_keeps_exact_source_span() -> None:
    doc, _ = bookmd_v0.parse(KITCHEN, chapter_id="C", new_id=_ids())
    lines = KITCHEN.split("\n")
    for block in doc["blocks"]:
        span = block["src"].split("\n")
        assert lines[block["line"] : block["line"] + len(span)] == span
    covered = "".join(b["src"] for b in doc["blocks"])
    for needle in ["$E=mc^2$", "[@key, p. 3]", "| 1 | 2 |", "def f():\tpass  ", "<script>alert(1)</script>"]:
        assert needle in covered


def test_types_and_raw_html_is_not_interpreted() -> None:
    doc, _ = bookmd_v0.parse(KITCHEN, chapter_id="C", new_id=_ids())
    types = [b["type"] for b in doc["blocks"]]
    assert types[0] == "heading" and doc["blocks"][0]["level"] == 1
    assert "code" in types and "list" in types and "quote" in types
    assert doc["schema"] == "bdm/0" and doc["parser"] == bookmd_v0.PARSER_VERSION


def test_unchanged_blocks_keep_ids() -> None:
    ids = _ids()
    first, _ = bookmd_v0.parse("A para.\n\nB para.\n\nC para.\n", chapter_id="C", new_id=ids)
    second, _ = bookmd_v0.parse("A para.\n\nB edited.\n\nC para.\n", chapter_id="C", new_id=ids, previous=first)
    a1, b1, c1 = (b["id"] for b in first["blocks"])
    a2, b2, c2 = (b["id"] for b in second["blocks"])
    assert (a1, c1) == (a2, c2)
    assert b1 != b2


def test_word_count_excludes_code() -> None:
    _, words = bookmd_v0.parse("One two three.\n\n```\nnot counted at all\n```\n", chapter_id="C", new_id=_ids())
    assert words == 3


def test_crlf_normalised() -> None:
    assert bookmd_v0.normalize_source("a\r\nb\rc") == "a\nb\nc"
    assert bookmd_v0.content_hash("a\r\nb") == bookmd_v0.content_hash("a\nb")
