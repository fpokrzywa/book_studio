"""Phase 11 final acceptance: a complete book publishing simulation, with every export inspected.

A representative technical book (three chapters, tables, a diagram, code, inline and display math,
citations with a bibliography, a footnote, a cross-reference, front and back matter) is imported
from a Markdown manuscript, edited by AI under the author's control, and exported to DOCX, EPUB and
PDF. Each file is opened and checked for missing chapters, broken images, wrong references, lost
formatting, duplicated passages and altered technical content.

Set PBS_ACCEPTANCE_OUT to a file path to also write the per-format findings as JSON (used for
docs/FINAL_ACCEPTANCE_REPORT.md).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from typing import Any

from docx import Document
from fastapi.testclient import TestClient
from lxml import etree
from pypdf import PdfReader

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from tests.test_publishing import HANDBOOK, build, diagram_png, file_bytes

CODE = "def gap_ok(mm):\n    return 0.6 <= mm <= 0.8"
DISPLAY_MATH = "\\frac{V_1}{V_2} = \\frac{N_1}{N_2}"
SENTENCES = [  # one per chapter; each must appear exactly once in every export
    "Small engines need clean fuel.",
    "The spark plug fires once per turn.",
    "Clean the carburettor every season.",
]
MANUSCRIPT = f"""# Fuel and Air

Small engines need clean fuel. The handbook gives the mixing ratio [@torque-handbook, p. 3], and
the [fuel guide](https://example.org/fuel) explains storage. A useful identity is $a^2 + b^2 = c^2$.[^n1]

| Part | Ratio | Note |
|:-----|------:|:----:|
| Petrol | 50 | fresh |
| Oil | 1 | two-stroke |

: Mixing ratios for two-stroke fuel {{#tbl-mix}}

[^n1]: Measured by volume.

# Ignition

The spark plug fires once per turn. See the mixing table in [the first chapter](#tbl-mix).

```python {{caption="Checking the spark gap"}}
{CODE}
```

$$
{DISPLAY_MATH}
$$

Coil theory follows the handbook [@torque-handbook].

# Maintenance

Clean the carburettor every season. Check the spark plug gap often, because a worn plug wastes fuel and makes starting hard.

| Task | Interval |
|------|----------|
| Change oil | 25 hours |
| Replace spark plug | 100 hours |

: Service intervals {{#tbl-service}}
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _flat(s: str) -> str:
    return "".join(s.split())


def _ai_job(
    client: TestClient, pid: str, cid: str, prov: str, runner: JobRunner, text: str, para: str
) -> dict[str, Any]:
    start = text.index(para)
    head = client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["revision_no"]
    job = client.post(f"/api/projects/{pid}/ai/jobs", json={
        "chapter_id": cid, "task": "revise", "mode": "replace_selection", "base_revision_no": head,
        "selection_start": start, "selection_end": start + len(para), "provider_id": prov,
        "model_name": "mock-writer", "client_request_id": os.urandom(8).hex(),
        "instruction": "Make this paragraph clearer.",
    })  # fmt: skip
    assert job.status_code == 202, job.text
    runner.run_until_idle()
    j = client.get(f"/api/ai/jobs/{job.json()['id']}").json()
    assert j["status"] == "succeeded", j
    props = [p for p in client.get(f"/api/projects/{pid}/proposals?chapter_id={cid}").json() if p["job_id"] == j["id"]]
    assert len(props) == 1 and props[0]["status"] == "pending"
    return dict(props[0])


def test_complete_book_publishing_simulation(client: TestClient, ctx: AppContext, runner: JobRunner) -> None:
    findings: dict[str, Any] = {}

    # ---- 1. Import the manuscript; the original is kept byte for byte ----
    raw = MANUSCRIPT.encode("utf-8")
    imp = client.post("/api/imports", files={"file": ("quiet-engine.md", raw)}).json()
    assert imp["status"] == "preview_ready" and len(imp["chapters"]) == 3
    out = client.post(f"/api/imports/{imp['id']}/commit", json={
        "mode": "new_project", "project_title": "The Quiet Engine", "project_type": "technical"}).json()  # fmt: skip
    pid, cids = out["project_id"], out["chapter_ids"]
    original = client.get(f"/api/imports/{imp['id']}/original")
    assert original.status_code == 200 and hashlib.sha256(original.content).digest() == hashlib.sha256(raw).digest()
    findings["import"] = {"chapters": 3, "original_sha256_identical": True}
    client.patch(f"/api/projects/{pid}", json={"subtitle": "A field manual", "author_name": "Ada Example"})

    # References: the cited handbook as a knowledge source with bibliographic details.
    src = client.post(f"/api/projects/{pid}/knowledge/sources",
                      files={"file": ("torque-handbook.md", HANDBOOK)}).json()["source"]  # fmt: skip
    client.patch(f"/api/knowledge/sources/{src['id']}",
                 json={"authors": ["Jane Torque"], "year": "2019", "publisher": "Shop Press"})  # fmt: skip

    # Author inserts the diagram into chapter 2 (a human revision).
    asset = client.post(
        f"/api/projects/{pid}/assets", files={"file": ("circuit.png", diagram_png(), "image/png")}
    ).json()
    c2 = client.get(f"/api/projects/{pid}/chapters/{cids[1]}/content").json()
    fig = f'![The ignition circuit](asset:{asset["short_hash"]}){{#fig-circuit alt="Diagram of the ignition coil and spark plug"}}\n\n'
    body = c2["source_md"].replace("The spark plug fires", fig + "The spark plug fires", 1)
    r = client.put(f"/api/projects/{pid}/chapters/{cids[1]}/content",
                   json={"source_md": body, "expected_head_no": c2["revision_no"]})  # fmt: skip
    assert r.status_code == 200, r.text
    code_before = re.search(r"```python.*?```", body, re.S).group(0)  # type: ignore[union-attr]
    math_before = re.search(r"\$\$.*?\$\$", body, re.S).group(0)  # type: ignore[union-attr]

    # ---- 2. Controlled AI editing: one suggestion rejected, one approved ----
    prov = client.post("/api/ai/providers", json={"kind": "mock"}).json()["id"]
    c3 = client.get(f"/api/projects/{pid}/chapters/{cids[2]}/content").json()
    para = next(p for p in c3["source_md"].split("\n\n") if p.startswith("Clean the carburettor"))
    first = _ai_job(client, pid, cids[2], prov, runner, c3["source_md"], para)
    assert client.get(f"/api/projects/{pid}/chapters/{cids[2]}/content").json()["revision_no"] == c3["revision_no"]
    assert client.post(f"/api/projects/{pid}/proposals/{first['id']}/reject", json={}).status_code == 200
    assert client.get(f"/api/projects/{pid}/chapters/{cids[2]}/content").json()["source_md"] == c3["source_md"]
    second = _ai_job(client, pid, cids[2], prov, runner, c3["source_md"], para)
    acc = client.post(
        f"/api/projects/{pid}/proposals/{second['id']}/accept", json={"expected_head_no": c3["revision_no"]}
    )
    assert acc.status_code == 200, acc.text
    again = client.post(
        f"/api/projects/{pid}/proposals/{second['id']}/accept", json={"expected_head_no": c3["revision_no"]}
    )
    assert again.status_code == 409  # never applied twice
    after = client.get(f"/api/projects/{pid}/chapters/{cids[2]}/content").json()
    revs = client.get(f"/api/projects/{pid}/chapters/{cids[2]}/revisions").json()
    origins = [r["origin"] for r in sorted(revs, key=lambda r: r["revision_no"])]
    assert origins[0] == "imported" and origins[-1] in ("ai_generated", "ai_assisted") and len(revs) == 2
    assert para not in after["source_md"] and "Service intervals" in after["source_md"]  # only the selection changed
    edited = after["source_md"]
    new_para = next(p for p in edited.split("\n\n") if p.strip() and p not in c3["source_md"])
    new_probe = _flat(new_para.split("]", 1)[-1])[:40]  # first words of the approved replacement (after its label)
    old_probe = _flat("Check the spark plug gap often, because a worn plug wastes fuel")
    c2_now = client.get(f"/api/projects/{pid}/chapters/{cids[1]}/content").json()["source_md"]
    assert code_before in c2_now and math_before in c2_now  # technical content untouched
    findings["ai_edit"] = {"rejected_left_text_unchanged": True, "approved_created_revision": origins,
                           "double_accept_refused": True}  # fmt: skip
    # The AI-edited paragraph replaces the old one in exports; the old one must not appear.
    SENT = [SENTENCES[0], SENTENCES[1]]

    # ---- 3. Front and back matter ----
    prof = client.get(f"/api/projects/{pid}/publishing/profile").json()
    for m in prof["matter"]:
        if m["kind"] == "dedication":
            m["enabled"], m["body_md"] = True, "For everyone who keeps old engines running."
        if m["kind"] == "glossary":
            m["enabled"], m["body_md"] = (
                True,
                "- **Carburettor**: mixes fuel and air\n- **Gap**: distance between electrodes",
            )
        if m["kind"] == "about_author":
            m["enabled"], m["body_md"] = True, "Ada Example repairs engines."
        if m["kind"] == "preface":
            m["enabled"] = False
    r = client.put(f"/api/projects/{pid}/publishing/profile", json={
        "template": "technical_manual", "trim": "6x9", "ink_paper": "bw_white", "matter": prof["matter"],
        "copyright": {"holder": "Ada Example", "year": "2026", "edition": "First edition", "isbn": "", "notice_md": ""},
        "metadata": {"description": "A practical manual.", "keywords": ["small engine repair"]},
        "cover": {"layers": prof["cover"]["layers"]}, "index_terms": ["spark plug", "carburettor"],
    })  # fmt: skip
    assert r.status_code == 200, r.text

    # ---- 4. Export and inspect each format ----
    pubs = build(client, pid, ["docx", "epub", "pdf"])
    assert all(p["status"] == "succeeded" for p in pubs.values())
    must = ["Fuel and Air", "Ignition", "Maintenance", "For everyone who keeps old engines running.",
            "Ada Example repairs engines.", "Glossary", "Bibliography", "Jane Torque", "Measured by volume"]  # fmt: skip

    # DOCX
    d = Document(io.BytesIO(file_bytes(client, pid, pubs["docx"]["id"])))
    paras = [p.text for p in d.paragraphs]
    dtext = "\n".join(paras + [c.text for t in d.tables for row in t.rows for c in row.cells])
    fn_xml = b"".join(part.blob for part in d.part.package.parts if part.partname.endswith("footnotes.xml"))
    dfull = dtext + fn_xml.decode("utf-8", "ignore")
    heads = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
    docx = {
        "chapters_in_order": [h for h in heads if h in ("Fuel and Air", "Ignition", "Maintenance")]
        == ["Fuel and Air", "Ignition", "Maintenance"],
        "front_back_matter_and_references": all(x in dfull for x in must),
        "tables": len(d.tables) == 2 and "Replace spark plug" in dtext,
        "images_with_alt": [x.get("descr") for x in d.element.body.xpath(".//wp:docPr")]
        == ["Diagram of the ignition coil and spark plug"],
        "code_verbatim": all(line in paras for line in CODE.split("\n")),
        "math": any(p.style.name == "PBS Equation" for p in d.paragraphs),
        "citation": "Torque 2019, p. 3" in dtext,
        "no_duplicates": all(_norm(dtext).count(s) == 1 for s in SENT),
        "ai_edit_applied": new_probe in _flat(dtext) and old_probe not in _flat(dtext),
    }
    # EPUB
    ep = zipfile.ZipFile(io.BytesIO(file_bytes(client, pid, pubs["epub"]["id"])))
    names = set(ep.namelist())
    xhtml = {n: ep.read(n).decode() for n in names if n.endswith(".xhtml")}
    body_text = "".join(etree.fromstring(v.encode()).xpath("string(//*[local-name()='body'])")
                        for n, v in sorted(xhtml.items()) if "nav" not in n)  # fmt: skip
    ids = {i for v in xhtml.values() for i in re.findall(r'\sid="([^"]+)"', v)}
    links = [(n, h) for n, v in xhtml.items() for h in re.findall(r'href="([^"#:]*)(?:#[^"]*)?"', v) if h]
    frags = [h.split("#", 1)[1] for v in xhtml.values() for h in re.findall(r'href="([^":]*#[^"]+)"', v)]
    imgs = [(n, s) for n, v in xhtml.items() for s in re.findall(r'<img[^>]+src="([^"]+)"', v)]
    nav = xhtml.get("OEBPS/nav.xhtml", "")
    pre = "\n".join(re.findall(r"<pre[^>]*>(.*?)</pre>", "".join(xhtml.values()), re.S))
    epub = {
        "container": ep.namelist()[0] == "mimetype",
        "chapters_in_nav": all(t in nav for t in ("Fuel and Air", "Ignition", "Maintenance")),
        "front_back_matter_and_references": all(x in body_text for x in must),
        "tables": sum(v.count("<table") for v in xhtml.values()) == 2,
        "images_resolve": bool(imgs) and all(f"OEBPS/{s}" in names for _, s in imgs),
        "internal_links_resolve": all(f"OEBPS/{h}" in names for _, h in links) and all(f in ids for f in frags),
        "code_verbatim": all(
            re.sub(r"<[^>]+>", "", line).replace("&lt;", "<") in re.sub(r"<[^>]+>", "", pre).replace("&lt;", "<")
            for line in CODE.split("\n")
        ),
        "math": any("<math" in v and "mfrac" in v for v in xhtml.values()),
        "citation": "Torque 2019, p. 3" in body_text,
        "no_duplicates": all(_norm(body_text).count(s) == 1 for s in SENT),
        "ai_edit_applied": new_probe in _flat(body_text) and old_probe not in _flat(body_text),
    }
    # PDF
    reader = PdfReader(io.BytesIO(file_bytes(client, pid, pubs["pdf"]["id"])))
    ptext = "\n".join(p.extract_text() for p in reader.pages)
    pflat = _flat(ptext)
    images = sum(len([o for o in (p.get("/Resources", {}).get("/XObject", {}) or {}).values()
                      if o.get_object().get("/Subtype") == "/Image"]) for p in reader.pages)  # fmt: skip
    pdf = {
        "pages": len(reader.pages),
        "page_size_6x9": {(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in reader.pages}
        == {(432, 648)},
        "chapters": all(_flat(t) in pflat for t in ("Fuel and Air", "Ignition", "Maintenance")),
        "front_back_matter_and_references": all(_flat(x) in pflat for x in must),
        "images": images >= 1,
        "code_verbatim": all(_flat(line) in pflat for line in CODE.split("\n")),
        "citation": _flat("Torque 2019, p. 3") in pflat,
        "no_duplicates": all(pflat.count(_flat(s)) == 1 for s in SENT),
        "ai_edit_applied": new_probe in pflat and old_probe not in pflat,
    }
    reports = {
        k: client.get(f"/api/projects/{pid}/publishing/publications/{p['id']}/report").json() for k, p in pubs.items()
    }
    findings["formats"] = {"docx": docx, "epub": epub, "pdf": pdf}
    findings["fidelity"] = {k: p.get("fidelity") for k, p in pubs.items()}
    findings["preflight"] = {k: {i["check"]: i["status"] for i in rep["items"]} for k, rep in reports.items()}
    findings["sizes"] = {k: p["byte_size"] for k, p in pubs.items()}
    if os.environ.get("PBS_ACCEPTANCE_OUT"):
        out_path = os.environ["PBS_ACCEPTANCE_OUT"]
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(findings, fh, indent=2, default=str)
        for kind, p in pubs.items():  # keep the files for external validators (EPUBCheck)
            with open(f"{out_path}.{kind}", "wb") as fh:
                fh.write(file_bytes(client, pid, p["id"]))

    failed = [f"{fmt}.{k}" for fmt, checks in findings["formats"].items() for k, v in checks.items()
              if v is False]  # fmt: skip
    assert failed == [], failed
    assert len(new_probe) >= 20, new_para
