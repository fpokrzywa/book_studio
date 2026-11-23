"""Phase 07: assembly, five export formats, fidelity, covers, preflight, metadata and the publish package."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image, ImageDraw
from pypdf import PdfReader

from pbs_core.context import AppContext
from pbs_core.publishing import kdp_rules, preflight
from pbs_core.publishing.latex_typst import UnsupportedMath, to_typst
from tests.conftest import new_chapter, save

FIX = Path(__file__).resolve().parents[3] / "fixtures"
HANDBOOK = (FIX / "knowledge" / "torque-handbook.md").read_bytes()


def diagram_png(w: int = 900, h: int = 600) -> bytes:
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    m = min(40, w // 4, h // 4)
    d.rectangle((m, m, w - m, h - m), outline="black", width=3)
    d.line((m, h - m, w - m, m), fill="black", width=3)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


CH1 = """# Fuel and Air

Small engines need clean fuel. The handbook gives the mixing ratio [@torque-handbook, p. 3], and
the [fuel guide](https://example.org/fuel) explains storage. A useful identity is $a^2 + b^2 = c^2$.[^n1]

| Part | Ratio | Note |
|:-----|------:|:----:|
| Petrol | 50 | fresh |
| Oil | 1 | two-stroke |

: Mixing ratios for two-stroke fuel {#tbl-mix}

[^n1]: Measured by volume.
"""

CH2 = """# Ignition

![The ignition circuit](asset:{hash}){{#fig-circuit alt="Diagram of the ignition coil and spark plug"}}

The spark plug fires once per turn. See the mixing table in [the first chapter](#tbl-mix).

```python {{caption="Checking the spark gap"}}
def gap_ok(mm):
    return 0.6 <= mm <= 0.8
```

$$
\\frac{{V_1}}{{V_2}} = \\frac{{N_1}}{{N_2}}
$$

Coil theory follows the handbook [@torque-handbook].
"""

CH3 = """# Maintenance

Clean the carburettor every season and check the spark plug gap of $\\sqrt{{x}}$ millimetres.

| Task | Interval |
|------|----------|
| Change oil | 25 hours |
| Replace spark plug | 100 hours |

: Service intervals {{#tbl-service}}

```json
{{"interval_hours": 25}}
```
"""


def fixture_book(client: TestClient) -> dict[str, Any]:
    r = client.post(
        "/api/projects",
        json={
            "title": "The Quiet Engine",
            "subtitle": "A field manual",
            "project_type": "technical",
            "author_name": "Ada Example",
        },
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    asset = client.post(
        f"/api/projects/{pid}/assets", files={"file": ("circuit.png", diagram_png(), "image/png")}
    ).json()
    src = client.post(
        f"/api/projects/{pid}/knowledge/sources", files={"file": ("torque-handbook.md", HANDBOOK)}
    ).json()["source"]
    client.patch(
        f"/api/knowledge/sources/{src['id']}",
        json={"authors": ["Jane Torque"], "year": "2019", "publisher": "Shop Press"},
    )
    ids = []
    for title, text in (
        ("Fuel and Air", CH1),
        ("Ignition", CH2.format(hash=asset["short_hash"])),
        ("Maintenance", CH3.format()),
    ):
        cid = new_chapter(client, pid, title)["id"]
        assert save(client, pid, cid, text, 0).status_code == 200
        ids.append(cid)
    prof = client.get(f"/api/projects/{pid}/publishing/profile").json()
    matter = prof["matter"]
    for m in matter:
        if m["kind"] == "glossary":
            m["enabled"], m["body_md"] = (
                True,
                "- **Carburettor**: mixes fuel and air\n- **Gap**: distance between electrodes",
            )
        if m["kind"] == "about_author":
            m["enabled"], m["body_md"] = True, "Ada Example repairs engines."
        if m["kind"] in ("preface",):
            m["enabled"] = False
    body = {
        "template": "technical_manual",
        "trim": "6x9",
        "ink_paper": "bw_white",
        "matter": matter,
        "copyright": {"holder": "Ada Example", "year": "2026", "edition": "First edition", "isbn": "", "notice_md": ""},
        "metadata": {"description": "A practical manual.", "keywords": ["small engine repair", "two-stroke"]},
        "cover": {"layers": prof["cover"]["layers"]},
        "index_terms": ["spark plug", "carburettor"],
    }
    r = client.put(f"/api/projects/{pid}/publishing/profile", json=body)
    assert r.status_code == 200, r.text
    return {"pid": pid, "chapters": ids, "asset": asset, "profile": body}


def build(client: TestClient, pid: str, formats: list[str]) -> dict[str, dict[str, Any]]:
    r = client.post(f"/api/projects/{pid}/publishing/build", json={"formats": formats})
    assert r.status_code == 201, r.text
    return {p["kind"]: p for p in r.json()["publications"]}


def file_bytes(client: TestClient, pid: str, pub_id: str) -> bytes:
    r = client.get(f"/api/projects/{pid}/publishing/publications/{pub_id}/file")
    assert r.status_code == 200
    return r.content


# ---------- acceptance: one fixture, five formats, inspected programmatically ----------


def test_fixture_exports_to_all_five_formats_and_each_is_inspected(client: TestClient, ctx: AppContext) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    pubs = build(client, pid, ["markdown", "html", "epub", "docx", "pdf"])
    assert set(pubs) == {"markdown", "html", "epub", "docx", "pdf"} and all(
        p["status"] == "succeeded" for p in pubs.values()
    )

    # PDF: page size, page count, fonts, language, text.
    pdf = file_bytes(client, pid, pubs["pdf"]["id"])
    r = PdfReader(io.BytesIO(pdf))
    assert len(r.pages) == pubs["pdf"]["page_count"] >= 8
    assert {(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in r.pages} == {
        (432, 648)
    }  # 6 × 9 in
    assert str(r.trailer["/Root"]["/Lang"]) == "en" and not r.is_encrypted
    text = "\n".join(p.extract_text() for p in r.pages)
    for t in (
        "Fuel and Air",
        "Ignition",
        "Maintenance",
        "Mixing ratios for two-stroke fuel",
        "Figure 2.1",
        "Listing 2.1",
        "Glossary",
        "Index",
    ):
        assert t.replace(" ", "") in text.replace(" ", "").replace("\n", "")
    flat = "".join(text.split())
    assert "https://example.org/fuel" in flat and "Torque2019,p.3" in flat
    rep = client.get(f"/api/projects/{pid}/publishing/publications/{pubs['pdf']['id']}/report").json()
    checks = {i["check"]: i for i in rep["items"]}
    assert checks["Page size"]["status"] == "pass" and checks["Fonts embedded"]["status"] == "pass"
    assert checks["Page count"]["status"] == "fail" and "KDP allows 24–828" in checks["Page count"]["detail"]
    assert checks["Inside margin (gutter)"]["status"] == "pass" and checks["Image resolution"]["status"] == "pass"
    assert rep["rules"]["ruleset"] == kdp_rules.RULESET and "does not guarantee" in rep["disclaimer"]

    # EPUB: container, metadata, navigation, chapters, images with alt, MathML, links.
    ep = zipfile.ZipFile(io.BytesIO(file_bytes(client, pid, pubs["epub"]["id"])))
    names = ep.namelist()
    assert names[0] == "mimetype" and ep.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    opf = etree.fromstring(ep.read("OEBPS/content.opf"))
    dc = "{http://purl.org/dc/elements/1.1/}"
    assert opf.find(f".//{dc}title").text == "The Quiet Engine" and opf.find(f".//{dc}language").text == "en"
    assert any(m.get("property") == "schema:accessibilityFeature" and m.text == "MathML" for m in opf.iter("{*}meta"))
    chapters = sorted(n for n in names if n.startswith("OEBPS/chapter-"))
    assert len(chapters) == 3 and "OEBPS/nav.xhtml" in names
    ch2 = ep.read(chapters[1]).decode()
    assert 'alt="Diagram of the ignition coil and spark plug"' in ch2 and "<math" in ch2
    assert 'href="chapter-001.xhtml#fuel-and-air-tbl-mix"' in ch2  # cross-chapter link resolved
    assert "Figure 2.1: The ignition circuit" in ch2
    erep = client.get(f"/api/projects/{pid}/publishing/publications/{pubs['epub']['id']}/report").json()
    estat = {i["check"]: i["status"] for i in erep["items"]}
    assert estat["Internal links"] == "pass" and estat["Navigation"] == "pass" and estat["Image alt text"] == "pass"
    if preflight.epubcheck_command() is None:
        assert estat["EPUBCheck"] == "unavailable"

    # DOCX: paragraphs and styles.
    d = Document(io.BytesIO(file_bytes(client, pid, pubs["docx"]["id"])))
    heads = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    assert [h for h in heads if h in ("Fuel and Air", "Ignition", "Maintenance")] == [
        "Fuel and Air",
        "Ignition",
        "Maintenance",
    ]
    styles = {p.style.name for p in d.paragraphs}
    assert {"PBS Code", "PBS Equation", "Caption", "Title"} <= styles
    assert any(p.text == "def gap_ok(mm):" and p.style.name == "PBS Code" for p in d.paragraphs)
    assert len(d.tables) == 2
    assert [x.get("descr") for x in d.element.body.xpath(".//wp:docPr")] == [
        "Diagram of the ignition coil and spark plug"
    ]
    assert "https://example.org/fuel" in {rel.target_ref for rel in d.part.rels.values() if rel.is_external}

    # HTML and Markdown.
    html = file_bytes(client, pid, pubs["html"]["id"]).decode()
    assert html.count('<section class="chapter"') == 3 and "data:image/png;base64," in html and "<math" in html
    md = zipfile.ZipFile(io.BytesIO(file_bytes(client, pid, pubs["markdown"]["id"])))
    text_md = md.read("book.md").decode()
    assert "def gap_ok(mm):" in text_md and f"images/{f['asset']['short_hash']}.png" in text_md

    # Fidelity: nothing missing; documented substitutes reported as degraded.
    fid = {k: p["fidelity"] for k, p in pubs.items() if p["fidelity"]}
    assert fid == {"markdown": "ok", "html": "ok", "epub": "ok", "docx": "degraded", "pdf": "degraded"}
    # Every export has its report saved beside it.
    folder = ctx.workspace.project_dir(pid) / "publish"
    assert [
        p["kind"] for p in pubs.values() if not (folder / p["id"] / f"{p['file_name']}.report.json").is_file()
    ] == []
    # Deterministic: the same book gives the same files.
    again = build(client, pid, ["html", "epub", "docx", "pdf"])
    assert {k: again[k]["sha256"] == pubs[k]["sha256"] for k in again} == {k: True for k in again}


def test_unsupported_math_is_printed_as_source_and_reported(client: TestClient) -> None:
    f = fixture_book(client)
    pid, cid = f["pid"], f["chapters"][2]
    save(client, pid, cid, CH3.format() + "\n$$\n\\weirdmacro{x}\n$$\n", 1)
    pdf = build(client, pid, ["pdf"])["pdf"]
    rep = client.get(f"/api/projects/{pid}/publishing/publications/{pdf['id']}/report").json()
    eq = next(i for i in rep["items"] if i["check"] == "Equations")
    assert eq["status"] == "warn" and "\\weirdmacro{x}" in eq["detail"]
    row = next(r for r in rep["fidelity"]["pdf"]["rows"] if r["element"] == "equations")
    assert row["status"] == "degraded" and "LaTeX source" in row["note"]


# ---------- acceptance: the print cover follows the final page count ----------


def test_print_cover_recalculates_when_the_final_page_count_changes(client: TestClient) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    assert client.get(f"/api/projects/{pid}/publishing/cover-spec").json()["spec"] is None
    assert client.post(f"/api/projects/{pid}/publishing/covers").status_code == 409  # no PDF yet
    pdf1 = build(client, pid, ["pdf"])["pdf"]
    spec1 = client.get(f"/api/projects/{pid}/publishing/cover-spec").json()
    assert spec1["based_on_pdf"]["page_count"] == pdf1["page_count"]
    n1 = pdf1["page_count"]
    assert Decimal(spec1["spec"]["spine_width_in"]) == kdp_rules.q(Decimal("0.002252") * n1)
    covers = {p["kind"]: p for p in client.post(f"/api/projects/{pid}/publishing/covers").json()["publications"]}
    cov = PdfReader(io.BytesIO(file_bytes(client, pid, covers["cover_print"]["id"])))
    assert abs(float(cov.pages[0].mediabox.width) / 72 - float(spec1["spec"]["cover_width_in"])) < 0.001
    assert Image.open(io.BytesIO(file_bytes(client, pid, covers["cover_ebook"]["id"]))).size == (1600, 2560)

    # The interior grows: the next PDF has more pages, so the spine and full cover width change.
    long = (
        CH3.format()
        + "\n\n"
        + "\n\n".join(f"Paragraph {i}: clean the filter and check the fuel line." for i in range(400))
    )
    save(client, pid, f["chapters"][2], long, 1)
    pdf2 = build(client, pid, ["pdf"])["pdf"]
    assert pdf2["page_count"] > n1
    spec2 = client.get(f"/api/projects/{pid}/publishing/cover-spec").json()
    assert spec2["based_on_pdf"]["publication_id"] == pdf2["id"]
    assert Decimal(spec2["spec"]["cover_width_in"]) > Decimal(spec1["spec"]["cover_width_in"])
    assert spec2["latest_cover"]["stale"] is True and "build it again" in spec2["message"]
    covers2 = {p["kind"]: p for p in client.post(f"/api/projects/{pid}/publishing/covers").json()["publications"]}
    cov2 = PdfReader(io.BytesIO(file_bytes(client, pid, covers2["cover_print"]["id"])))
    assert abs(float(cov2.pages[0].mediabox.width) / 72 - float(spec2["spec"]["cover_width_in"])) < 0.001
    assert covers2["cover_print"]["settings"]["interior_publication_id"] == pdf2["id"]
    assert client.get(f"/api/projects/{pid}/publishing/cover-spec").json()["latest_cover"]["stale"] is False


def test_cover_artwork_needs_rights_and_its_resolution_is_checked(client: TestClient) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    tiny = client.post(
        f"/api/projects/{pid}/assets", files={"file": ("tiny.png", diagram_png(60, 90), "image/png")}
    ).json()
    body = {**f["profile"], "cover": {**f["profile"]["cover"], "artwork_asset": tiny["short_hash"]}}
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=body).status_code == 422
    body["cover"]["artwork_license"] = {"source": "My own drawing", "license": "Mine", "confirmed": True}
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=body).status_code == 200
    build(client, pid, ["pdf"])
    cov = client.post(f"/api/projects/{pid}/publishing/covers").json()["publications"][0]
    rep = client.get(f"/api/projects/{pid}/publishing/publications/{cov['id']}/report").json()
    res = next(i for i in rep["items"] if i["check"] == "Artwork resolution")
    assert res["status"] == "fail" and "at least 300" in res["detail"]
    assert any(i["check"] == "Barcode area" and i["status"] == "manual" for i in rep["items"])


# ---------- acceptance: EPUB validation is never faked ----------


def test_epub_validation_is_unavailable_never_passed_without_epubcheck(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = fixture_book(client)
    monkeypatch.setattr(preflight, "epubcheck_command", lambda: None)
    ep = build(client, f["pid"], ["epub"])["epub"]
    st = {
        i["check"]: i
        for i in client.get(f"/api/projects/{f['pid']}/publishing/publications/{ep['id']}/report").json()["items"]
    }
    assert st["EPUBCheck"]["status"] == "unavailable" and "not a pass" in st["EPUBCheck"]["detail"]
    # With a validator present, its exit code decides.
    monkeypatch.setattr(
        preflight, "epubcheck_command", lambda: [sys.executable, "-c", "import sys; print('1 error'); sys.exit(1)"]
    )
    ep2 = build(client, f["pid"], ["epub"])["epub"]
    st2 = {
        i["check"]: i
        for i in client.get(f"/api/projects/{f['pid']}/publishing/publications/{ep2['id']}/report").json()["items"]
    }
    assert st2["EPUBCheck"]["status"] == "fail" and "1 error" in st2["EPUBCheck"]["detail"]


# ---------- acceptance: the sample publish package ----------


def test_publish_package_has_everything_and_publishes_nothing(client: TestClient, ctx: AppContext) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    r = client.post(f"/api/projects/{pid}/publishing/package")
    assert r.status_code == 201, r.text
    pkg = r.json()
    names = {x["name"] for x in pkg["files"]}
    for n in (
        "book/The Quiet Engine.epub",
        "book/The Quiet Engine.docx",
        "book/The Quiet Engine.html",
        "book/The Quiet Engine.md.zip",
        "book/The Quiet Engine-interior-6x9.pdf",
        "cover/print-cover.pdf",
        "cover/print-cover-proof-NOT-FOR-UPLOAD.pdf",
        "cover/ebook-cover.jpg",
        "metadata.json",
        "metadata.txt",
        "preflight-report.json",
        "preflight-report.html",
        "COPYRIGHT-AND-LICENSES.txt",
        "SOURCES.txt",
        "KDP-UPLOAD-STEPS.md",
    ):
        assert n in names, n
    folder = Path(pkg["folder"])
    assert (folder / "manifest.json").is_file() and all((folder / n).is_file() for n in names)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["auto_publish"] is False and manifest["ruleset"] == kdp_rules.RULESET
    steps = (folder / "KDP-UPLOAD-STEPS.md").read_text(encoding="utf-8")
    assert "does not publish anything" in steps and "does not mean KDP will accept" in steps
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert meta["keywords"][:2] == ["small engine repair", "two-stroke"] and "unverified" in meta["categories_note"]
    assert meta["print"]["page_count"] == pkg["publication"]["page_count"]
    lic = (folder / "COPYRIGHT-AND-LICENSES.txt").read_text(encoding="utf-8")
    assert "Libertinus Serif: SIL Open Font License" in lic and "not drawn by an image model" in lic
    assert "Jane Torque" in (folder / "SOURCES.txt").read_text(encoding="utf-8")
    report_html = client.get(
        f"/api/projects/{pid}/publishing/publications/{pkg['publication']['id']}/package-file",
        params={"name": "preflight-report.html", "inline": True},
    )
    assert report_html.status_code == 200 and "inline" in report_html.headers["content-disposition"]
    assert "does not guarantee that KDP will accept" in report_html.text and kdp_rules.RULESET in report_html.text
    zipped = client.get(f"/api/projects/{pid}/publishing/publications/{pkg['publication']['id']}/file")
    assert zipped.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(zipped.content)).namelist()) == len(names) + 1
    assert pkg["report_summary"].get("pass", 0) > 10


# ---------- matter, metadata and previews ----------


def test_front_matter_never_invents_legal_text_or_isbn(client: TestClient) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    body = {**f["profile"], "copyright": {"holder": "", "year": "", "edition": "", "isbn": "", "notice_md": ""}}
    for m in body["matter"]:
        if m["kind"] == "dedication":
            m["enabled"], m["body_md"] = True, ""
    client.put(f"/api/projects/{pid}/publishing/profile", json=body)
    out = client.post(f"/api/projects/{pid}/publishing/build", json={"formats": ["html"]}).json()
    codes = {w["code"] for w in out["warnings"]}
    assert {"copyright_empty", "empty_matter"} <= codes
    html = file_bytes(client, pid, out["publications"][0]["id"]).decode()
    assert "All rights reserved" not in html and "ISBN" not in html and "Copyright ©" not in html
    bad = {**body, "copyright": {**body["copyright"], "isbn": "978-0-00-000000-1"}}
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=bad).status_code == 422
    good = {
        **body,
        "copyright": {**body["copyright"], "isbn": "978-3-16-148410-0", "holder": "Ada Example", "year": "2026"},
    }
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=good).status_code == 200
    ep = build(client, pid, ["epub"])["epub"]
    opf = zipfile.ZipFile(io.BytesIO(file_bytes(client, pid, ep["id"]))).read("OEBPS/content.opf").decode()
    assert "urn:isbn:9783161484100" in opf


def test_metadata_handoff_checks(client: TestClient) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    too_many = {**f["profile"], "metadata": {"keywords": [f"k{i}" for i in range(8)]}}
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=too_many).status_code == 422
    cats = {**f["profile"], "metadata": {"categories": [{"text": f"c{i}"} for i in range(4)]}}
    assert client.put(f"/api/projects/{pid}/publishing/profile", json=cats).status_code == 422
    meta = {
        "description": "Visit https://example.com for the bestseller edition.",
        "keywords": ["bestseller engines", "The Quiet Engine", "lawn mower repair"],
        "categories": [{"text": "Engineering > Mechanical"}],
        "ai_disclosure": {"text": "", "images": "none", "translation": "none"},
    }
    client.put(f"/api/projects/{pid}/publishing/profile", json={**f["profile"], "metadata": meta})
    pkg = client.post(f"/api/projects/{pid}/publishing/package").json()
    items = {
        i["check"]: i
        for i in client.get(f"/api/projects/{pid}/publishing/publications/{pkg['publication']['id']}/report").json()[
            "items"
        ]
        if i["area"] == "Metadata"
    }
    assert items["Description"]["status"] == "fail" and "web address" in items["Description"]["detail"]
    assert items["Keywords"]["status"] == "warn" and "sales or promotional claim" in items["Keywords"]["detail"]
    assert "repeats the title" in items["Keywords"]["detail"]
    assert items["Categories"]["status"] == "manual" and items["AI disclosure"]["status"] == "warn"
    txt = Path(pkg["folder"], "metadata.txt").read_text(encoding="utf-8")
    assert "UNVERIFIED" in txt and "AI-generated:" in txt


def test_previews_say_whether_they_match_the_export(client: TestClient) -> None:
    f = fixture_book(client)
    pid = f["pid"]
    first = client.get(f"/api/projects/{pid}/publishing/preview/html").json()
    assert first["identical_to_last_export"] is None
    html = build(client, pid, ["html"])["html"]
    same = client.get(f"/api/projects/{pid}/publishing/preview/html").json()
    assert same["identical_to_last_export"] is True and same["sha256"] == html["sha256"]
    save(client, pid, f["chapters"][0], CH1 + "\nOne more line.\n", 1)
    changed = client.get(f"/api/projects/{pid}/publishing/preview/html").json()
    assert changed["identical_to_last_export"] is False and "Not identical" in changed["note"]
    page = client.get(f"/api/projects/{pid}/publishing/preview/pdf-page/1")
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert int(page.headers["x-page-count"]) >= 8 and "not the PDF file" in page.headers["x-preview-note"]


def test_profile_reports_rules_and_tools(client: TestClient) -> None:
    f = fixture_book(client)
    prof = client.get(f"/api/projects/{f['pid']}/publishing/profile").json()
    assert prof["rules"]["ruleset"] == kdp_rules.RULESET and prof["rules"]["checked_on"] == "2026-11-22"
    assert prof["rules"]["sources"]["paperback_cover"].startswith("https://kdp.amazon.com/")
    assert "Not configured" in prof["tools"]["image_generation"] and "MOBI" in prof["tools"]["mobi"]
    assert prof["options"]["keyword_slots"] == 7 and "6x9" in prof["options"]["trims"]


# ---------- pure rules ----------


def test_kdp_cover_and_margin_rules() -> None:
    s = kdp_rules.cover_spec("6x9", "bw_white", 120)
    assert (s.spine, s.width, s.height) == (Decimal("0.2702"), Decimal("12.5202"), Decimal("9.2500"))
    assert kdp_rules.cover_spec("6x9", "bw_cream", 100).spine == Decimal("0.2500")
    assert kdp_rules.cover_spec("6x9", "bw_white", 78).spine_text_allowed is False
    assert kdp_rules.gutter_for(150) == Decimal("0.375") and kdp_rules.gutter_for(151) == Decimal("0.5")
    assert kdp_rules.page_range("8.27x11.69", "standard_color_white") is None
    with pytest.raises(ValueError):
        kdp_rules.cover_spec("6x9", "bw_groundwood", 100)


def test_latex_to_typst_conversion() -> None:
    assert to_typst(r"\frac{a}{b}") == "frac(a, b)"
    assert to_typst(r"x^{2} + \alpha") == "x ^(2) + alpha"
    assert to_typst(r"\sqrt[3]{x}") == "root(3, x)"
    assert to_typst(r"\text{rate} \leq 5") == '"rate" <= 5'
    with pytest.raises(UnsupportedMath):
        to_typst(r"\weirdmacro{x}")
