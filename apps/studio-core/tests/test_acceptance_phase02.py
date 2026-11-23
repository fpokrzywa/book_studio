"""Phase 02 acceptance (prompt 02 "TESTS / ACCEPTANCE"), driven through the HTTP API with a real restart.

1. Import a multi-chapter fixture with a table, image + caption, code block, citation and math.
2. Edit and save. 3. Restart Core. 4. Round-trip and verify preservation.
5. Restore a previous revision; the newer revision stays in history.
6. Reorder chapters; content, image and citation references stay stable.
7. Backup -> restore produces an equivalent manuscript and metadata.
"""

import io
import itertools
import zipfile
from pathlib import Path

from pbs_core.context import build_context
from pbs_core.document import bookmd, serialize
from tests.conftest import make_settings, signed_client
from tests.test_backup import snapshot

FIX = Path(__file__).resolve().parents[3] / "fixtures"


def _client(workspace: Path):
    ctx = build_context(make_settings(workspace))
    return ctx


def _ids():
    counter = itertools.count()
    return lambda: f"{next(counter):026d}"


def _structures(text: str) -> dict[str, int]:
    counter = itertools.count()
    doc = bookmd.parse(text, chapter_id="x", new_id=lambda: f"{next(counter):026d}").doc
    kinds = [b["type"] for b in bookmd.walk_blocks(doc)]
    inl = [n["t"] for n in bookmd.iter_all_inlines(doc)]
    return {"table": kinds.count("table"), "figure": kinds.count("figure"), "code": kinds.count("code"),
            "cite": inl.count("cite"), "math": inl.count("math") + kinds.count("math_block"),
            "footnote": inl.count("footnote_ref")}  # fmt: skip


def test_phase02_acceptance(workspace: Path) -> None:
    ctx = _client(workspace)
    with signed_client(ctx, make_settings(workspace)) as c:
        # 1. Import
        imp = c.post(
            "/api/imports", files={"file": ("quiet-engine.html", (FIX / "import/multi-chapter.html").read_bytes())}
        ).json()
        assert imp["status"] == "preview_ready" and len(imp["chapters"]) == 3
        done = c.post(
            f"/api/imports/{imp['id']}/commit", json={"mode": "new_project", "project_title": "The Quiet Engine"}
        ).json()
        pid, (ch1, ch2, ch3) = done["project_id"], done["chapter_ids"]
        imported = {
            cid: c.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["source_md"] for cid in done["chapter_ids"]
        }
        totals = {
            k: sum(_structures(t)[k] for t in imported.values()) for k in ("table", "figure", "code", "cite", "math")
        }
        assert totals == {"table": 1, "figure": 1, "code": 1, "cite": 1, "math": 2}, totals

        # 2. Edit and save (a human revision on top of the imported one)
        edited = imported[ch2] + "\nTighten bolts in a star pattern [@smith2020, p. 4].\n"
        r = c.put(f"/api/projects/{pid}/chapters/{ch2}/content", json={"source_md": edited, "expected_head_no": 1})
        assert r.status_code == 200 and r.json()["content"]["revision_no"] == 2
    ctx.close()

    # 3. Restart: a new Core context on the same workspace
    ctx = _client(workspace)
    with signed_client(ctx, make_settings(workspace)) as c:
        after = {
            cid: c.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["source_md"] for cid in (ch1, ch2, ch3)
        }
        assert after[ch2] == edited and after[ch1] == imported[ch1] and after[ch3] == imported[ch3]

        # 4. Round trip: stored text -> canonical model -> normal-form text -> model is lossless,
        #    and both exports carry every structure.
        for text in after.values():
            doc = bookmd.parse(text, chapter_id="x", new_id=_ids()).doc
            again = bookmd.parse(serialize.serialize(doc), chapter_id="x", new_id=_ids()).doc
            assert bookmd.strip_ids(doc) == bookmd.strip_ids(again)
        md = c.post(f"/api/projects/{pid}/exports", json={"format": "markdown"}).json()
        assert md["format"] == "markdown_zip"
        zf = zipfile.ZipFile(io.BytesIO(c.get(md["download_url"]).content))
        names = zf.namelist()
        book = zf.read(next(n for n in names if n.endswith(".md"))).decode("utf-8")
        image = next(n for n in names if n.startswith("assets/"))
        assert f"]({image}" in book and zf.read(image)[:8] == b"\x89PNG\r\n\x1a\n"
        for text in after.values():
            assert text.replace("(asset:", "(assets/").split("(assets/")[0] in book
        exported_structs = _structures(book.replace(f"({image}", "(asset:0123456789abcdef"))
        assert exported_structs["table"] == 1 and exported_structs["figure"] == 1 and exported_structs["code"] == 1
        assert exported_structs["cite"] == 2 and exported_structs["math"] == 2 and exported_structs["footnote"] == 1
        html = c.get(c.post(f"/api/projects/{pid}/exports", json={"format": "html"}).json()["download_url"]).text
        for needle in ["<table>", "<caption>Fastener torque values</caption>", "<figcaption>", 'alt="Line drawing',
                       '<code class="language-python">', "<math", 'data-keys="smith2020"', 'class="footnotes"']:  # fmt: skip
            assert needle in html, needle

        # 5. Restore revision 1 of chapter 2 as a NEW revision; revision 2 remains in history.
        res = c.post(f"/api/projects/{pid}/chapters/{ch2}/revisions/1/restore", json={"expected_head_no": 2}).json()
        assert res["content"]["revision_no"] == 3 and res["content"]["source_md"] == imported[ch2]
        revs = c.get(f"/api/projects/{pid}/chapters/{ch2}/revisions").json()
        assert [(r["revision_no"], r["origin"]) for r in revs] == [(3, "restored"), (2, "human"), (1, "imported")]
        assert c.get(f"/api/projects/{pid}/chapters/{ch2}/revisions/2").json()["source_md"] == edited

        # 6. Reorder: chapter 3 first, chapter 1 becomes a section of chapter 2.
        c.post(f"/api/projects/{pid}/chapters/{ch3}/move", json={"parent_id": None, "index": 0})
        order = c.post(f"/api/projects/{pid}/chapters/{ch1}/move", json={"parent_id": ch2, "index": 0}).json()
        assert [(x["id"], x["depth"]) for x in order] == [(ch3, 0), (ch2, 0), (ch1, 1)]
        for cid in (ch1, ch2, ch3):
            assert c.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["source_md"] in (
                after[cid],
                imported[cid],
            )
        html2 = c.get(c.post(f"/api/projects/{pid}/exports", json={"format": "html"}).json()["download_url"]).text
        assert (
            html2.index("Chapter Three: Running")
            < html2.index("Chapter Two: Torque")
            < html2.index("Chapter One: Waking")
        )
        assert "data:image/png;base64," in html2 and 'data-keys="smith2020"' in html2 and "Missing image" not in html2

        # 7. Backup -> restore equivalence
        before = snapshot(c, pid)
        b = c.post(f"/api/projects/{pid}/backups").json()
        restored = c.post("/api/backups/restore", files={"file": ("b.zip", c.get(b["download_url"]).content)}).json()
        assert snapshot(c, restored["project"]["id"]) == before
    ctx.close()
