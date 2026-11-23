"""Preflight: inspect every built file against the KDP rule set and general file checks.

Statuses: pass, warn, fail, manual (a person must check, e.g. against KDP's own previewer or cover
template), unavailable (the tool needed for the check is not installed: NEVER reported as pass).
Every report carries the rule-set version, the date the rules were checked and their source URLs,
and says that passing preflight does not mean KDP will accept the book.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from lxml import etree

from pbs_core.publishing import kdp_rules
from pbs_core.publishing.book import Book

PT = Decimal(72)
TOL_IN = Decimal("0.01")
DISCLAIMER = (
    "Preflight checks the files against the KDP specifications PBS knows (rule set {ruleset}, checked "
    "{checked}). It does not guarantee that KDP will accept, print or publish the book: KDP reviews every "
    "title, and its specifications can change. Use KDP's previewers before you publish."
)


def item(area: str, check: str, status: str, detail: str) -> dict[str, str]:
    return {"area": area, "check": check, "status": status, "detail": detail}


# ---------- interior PDF ----------


def pdf_interior(
    data: bytes, book: Book, trim: str, ink_paper: str, inside_in: Decimal, stats: Any
) -> list[dict[str, str]]:
    from pypdf import PdfReader

    out: list[dict[str, str]] = []
    a = "Print interior (PDF)"
    r = PdfReader(io.BytesIO(data))
    n = len(r.pages)
    tw, th, _ = kdp_rules.TRIM_SIZES[trim]
    sizes = {
        (round(Decimal(str(float(p.mediabox.width))) / PT, 3), round(Decimal(str(float(p.mediabox.height))) / PT, 3))
        for p in r.pages
    }
    ok = all(abs(w - tw) <= TOL_IN and abs(h - th) <= TOL_IN for w, h in sizes)
    out.append(item(a, "Page size", "pass" if ok and len(sizes) == 1 else "fail",
                    f"Every page is {tw} × {th} in (trim, no bleed)." if ok else f"Page sizes found: {sorted(sizes)}; expected {tw} × {th} in."))  # fmt: skip
    rng = kdp_rules.page_range(trim, ink_paper)
    if rng is None:
        out.append(
            item(
                a, "Trim and paper", "fail", f"KDP does not offer {trim} with {kdp_rules.INK_PAPER_LABELS[ink_paper]}."
            )
        )
    else:
        lo, hi = rng
        st = "pass" if lo <= n <= hi else "fail"
        out.append(item(a, "Page count", st, f"{n} pages; KDP allows {lo}–{hi} for {trim}, {kdp_rules.INK_PAPER_LABELS[ink_paper]}."
                        + (" KDP rounds an odd page count up to an even number." if n % 2 else "")))  # fmt: skip
    need = kdp_rules.gutter_for(max(n, 24))
    if need is not None:
        out.append(item(a, "Inside margin (gutter)", "pass" if inside_in >= need else "fail",
                        f"{inside_in} in used; KDP minimum for {n} pages is {need} in."))  # fmt: skip
    t = book.template
    outs = min(Decimal(str(t["outside_in"])), Decimal(str(t["top_in"])), Decimal(str(t["bottom_in"])))
    out.append(item(a, "Outside, top and bottom margins", "pass" if outs >= kdp_rules.OUTSIDE_MIN else "fail",
                    f"At least {outs} in (KDP minimum {kdp_rules.OUTSIDE_MIN} in without bleed)."))  # fmt: skip
    out.append(item(a, "Bleed", "pass", "No bleed: nothing in the interior is printed to the page edge."))
    unembedded, subset, names = [], 0, set()
    for p in r.pages:
        fonts = (p.get("/Resources") or {}).get("/Font")
        if not fonts:
            continue
        for f in fonts.get_object().values():
            f = f.get_object()
            base = str(f.get("/BaseFont", "?"))
            names.add(re.sub(r"^[A-Z]{6}\+", "", base))
            fd = f.get("/FontDescriptor")
            if fd is None and "/DescendantFonts" in f:
                fd = f["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            fd = fd.get_object() if fd is not None else {}
            if not any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                unembedded.append(base)
            if re.match(r"^[A-Z]{6}\+", base):
                subset += 1
    out.append(item(a, "Fonts embedded", "fail" if unembedded else "pass",
                    ("Not embedded: " + ", ".join(sorted(set(unembedded)))) if unembedded else f"All fonts embedded: {', '.join(sorted(names))}."))  # fmt: skip
    if subset:
        out.append(
            item(
                a,
                "Font subsetting",
                "warn",
                "Fonts are embedded as subsets. KDP recommends full embedding but asks for embedded fonts; check KDP's print previewer.",
            )
        )
    low = [i for i in stats.images if i["effective_dpi"] is not None and i["effective_dpi"] < kdp_rules.MIN_IMAGE_DPI]
    out.append(item(a, "Image resolution", "fail" if low else "pass",
                    f"{len(stats.images)} image(s); each is printed at {kdp_rules.MIN_IMAGE_DPI} DPI or more (images are never enlarged past that)."
                    if not low else f"{len(low)} image(s) below {kdp_rules.MIN_IMAGE_DPI} DPI."))  # fmt: skip
    root: Any = r.trailer["/Root"]
    lang = str(root.get("/Lang", ""))
    out.append(item(a, "Document language", "pass" if lang else "fail", f"Language tag: {lang or 'missing'}."))
    annots = sum(len(p.get("/Annots") or []) for p in r.pages)
    out.append(
        item(
            a,
            "Links, comments and annotations",
            "pass" if annots == 0 else "warn",
            f"{annots} annotation(s) (KDP asks for none in print files).",
        )
    )
    outline = "/Outlines" in root
    out.append(
        item(
            a,
            "Bookmarks",
            "pass" if not outline else "warn",
            "No bookmarks." if not outline else "The PDF has bookmarks; KDP asks for none.",
        )
    )
    out.append(
        item(
            a,
            "Encryption",
            "pass" if not r.is_encrypted else "fail",
            "Not encrypted." if not r.is_encrypted else "The PDF is encrypted.",
        )
    )
    mb = len(data) / 1024 / 1024
    out.append(
        item(
            a,
            "File size",
            "pass" if mb < kdp_rules.MAX_FILE_MB else "fail",
            f"{mb:.2f} MB (KDP limit {kdp_rules.MAX_FILE_MB} MB).",
        )
    )
    blank = [
        i
        for i, p in enumerate(r.pages)
        if not (p.extract_text() or "").strip() and not ((p.get("/Resources") or {}).get("/XObject"))
    ]
    runs, cur = [], [blank[0]] if blank else []
    for i in blank[1:]:
        if i == cur[-1] + 1:
            cur.append(i)
        else:
            runs.append(cur)
            cur = [i]
    if cur:
        runs.append(cur)
    worst_mid = max((len(x) for x in runs if x[-1] != n - 1), default=0)
    worst_end = max((len(x) for x in runs if x[-1] == n - 1), default=0)
    ok_blank = worst_mid <= kdp_rules.MAX_BLANK_START_MIDDLE and worst_end <= kdp_rules.MAX_BLANK_END
    out.append(item(a, "Blank pages", "pass" if ok_blank else "fail",
                    f"Longest run of blank pages: {worst_mid} (start/middle, limit {kdp_rules.MAX_BLANK_START_MIDDLE}), {worst_end} at the end (limit {kdp_rules.MAX_BLANK_END})."))  # fmt: skip
    out.append(item(a, "Text size", "pass" if min(t["code_pt"], t["body_pt"], 8.5) >= kdp_rules.MIN_TEXT_PT else "fail",
                    f"Smallest text in the template is {min(t['code_pt'], 8.5)} pt (KDP minimum {kdp_rules.MIN_TEXT_PT} pt)."))  # fmt: skip
    text_w = tw - inside_in - Decimal(str(t["outside_in"]))
    cap = int(text_w * PT / (Decimal("0.6") * Decimal(str(t["code_pt"]))))
    long_lines = [ln for ch in book.chapters if ch.doc for ln in _code_lines(ch.doc) if len(ln) > cap]
    out.append(item(a, "Text overflow", "warn" if long_lines else "pass",
                    f"{len(long_lines)} code line(s) are longer than {cap} characters and run past the right margin; wrap them in the chapter."
                    if long_lines else f"No code line is longer than the {cap} characters that fit the text width."))  # fmt: skip
    as_src = stats.equations_as_source
    out.append(item(a, "Equations", "warn" if as_src else "pass",
                    f"{len(as_src)} equation(s) printed as LaTeX source (not converted): {'; '.join(as_src[:3])}" if as_src else f"{stats.equations} equation(s) typeset."))  # fmt: skip
    if stats.broken_refs:
        out.append(
            item(
                a, "Cross-references", "warn", "Links to missing anchors: " + ", ".join(sorted(set(stats.broken_refs)))
            )
        )
    out.append(
        item(
            a,
            "PDF standard",
            "manual",
            "Standard PDF 1.7 with tags. KDP prefers PDF/X-1a but accepts other PDFs; check KDP's print previewer.",
        )
    )
    return out


def _code_lines(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def walk(blocks: list[dict[str, Any]]) -> None:
        for b in blocks:
            if b.get("type") == "code":
                out.extend(b["text"].split("\n"))
            if isinstance(b.get("blocks"), list):
                walk(b["blocks"])
            if b.get("type") == "list":
                for it in b["items"]:
                    walk(it["blocks"])

    walk(doc.get("blocks", []))
    return out


# ---------- EPUB ----------


def epubcheck_command() -> list[str] | None:
    exe = shutil.which("epubcheck")
    if exe:
        return [exe]
    jar = os.environ.get("PBS_EPUBCHECK_JAR")
    java = shutil.which("java")
    if jar and java and Path(jar).is_file():
        return [java, "-jar", jar]
    return None


def epub(data: bytes) -> list[dict[str, str]]:
    a = "EPUB"
    out: list[dict[str, str]] = []
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    first_ok = (
        infos
        and infos[0].filename == "mimetype"
        and infos[0].compress_type == zipfile.ZIP_STORED
        and z.read("mimetype") == b"application/epub+zip"
    )
    out.append(
        item(
            a,
            "Container",
            "pass" if first_ok else "fail",
            "mimetype first and uncompressed; container.xml present." if first_ok else "The mimetype entry is wrong.",
        )
    )
    opf_path = etree.fromstring(z.read("META-INF/container.xml")).find(".//{*}rootfile").get("full-path")
    opf = etree.fromstring(z.read(opf_path))
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    dc = "{http://purl.org/dc/elements/1.1/}"
    meta_ok = {k: bool(opf.findall(f".//{dc}{k}")) for k in ("title", "language", "identifier")}
    modified = any(m.get("property") == "dcterms:modified" for m in opf.iter("{*}meta"))
    missing = [k for k, v in meta_ok.items() if not v] + ([] if modified else ["dcterms:modified"])
    out.append(
        item(
            a,
            "Metadata",
            "pass" if not missing else "fail",
            "Title, language, identifier and modified date present."
            if not missing
            else "Missing: " + ", ".join(missing),
        )
    )
    items = {i.get("id"): i for i in opf.iter("{*}item")}
    names = set(z.namelist())
    absent = [i.get("href") for i in items.values() if base + unquote(i.get("href")) not in names]
    out.append(
        item(
            a,
            "Manifest",
            "pass" if not absent else "fail",
            f"{len(items)} item(s), all in the file." if not absent else "Missing files: " + ", ".join(absent),
        )
    )
    nav = [i for i in items.values() if "nav" in (i.get("properties") or "").split()]
    nav_ok = False
    if nav:
        nav_doc = etree.fromstring(z.read(base + nav[0].get("href")))
        nav_ok = any(n.get("{http://www.idpf.org/2007/ops}type") == "toc" for n in nav_doc.iter("{*}nav"))
    out.append(
        item(
            a,
            "Navigation",
            "pass" if nav_ok else "fail",
            "Navigation document with a table of contents." if nav_ok else "No navigation table of contents.",
        )
    )
    ids: dict[str, set[str]] = {}
    docs: dict[str, Any] = {}
    bad_xml = []
    for i in items.values():
        if i.get("media-type") == "application/xhtml+xml":
            path = base + unquote(i.get("href"))
            try:
                root = etree.fromstring(z.read(path))
            except etree.XMLSyntaxError:
                bad_xml.append(path)
                continue
            docs[path] = root
            ids[path] = {e.get("id") for e in root.iter() if e.get("id")}
    out.append(
        item(
            a,
            "XHTML well-formed",
            "pass" if not bad_xml else "fail",
            f"{len(docs)} document(s) parse as XML." if not bad_xml else "Not well-formed: " + ", ".join(bad_xml),
        )
    )
    broken, external = [], 0
    no_alt = 0
    for path, root in docs.items():
        folder = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        for el in root.iter("{*}a"):
            href = el.get("href") or ""
            if not href:
                continue
            parts = urlsplit(href)
            if parts.scheme in ("http", "https", "mailto"):
                external += 1
                continue
            target = path if not parts.path else os.path.normpath(folder + unquote(parts.path)).replace("\\", "/")
            if target not in ids or (parts.fragment and parts.fragment not in ids[target]):
                broken.append(f"{path.rsplit('/', 1)[-1]} → {href}")
        no_alt += sum(1 for el in root.iter("{*}img") if el.get("alt") is None)
    out.append(item(a, "Internal links", "pass" if not broken else "fail",
                    f"All internal links resolve ({external} web link(s) not visited)." if not broken else "Broken: " + "; ".join(broken[:10])))  # fmt: skip
    out.append(
        item(
            a,
            "Image alt text",
            "pass" if not no_alt else "fail",
            "Every image has alt text." if not no_alt else f"{no_alt} image(s) without alt text.",
        )
    )
    acc = [m.text for m in opf.iter("{*}meta") if (m.get("property") or "").startswith("schema:")]
    out.append(
        item(
            a,
            "Accessibility metadata",
            "pass" if acc else "warn",
            f"{len(acc)} schema.org accessibility entries." if acc else "No accessibility metadata.",
        )
    )
    cmd = epubcheck_command()
    if cmd is None:
        out.append(item(a, "EPUBCheck", "unavailable",
                        "Validation unavailable: EPUBCheck is not installed (needs Java). Install it, or set PBS_EPUBCHECK_JAR, to run the official validator. This is not a pass."))  # fmt: skip
    else:
        tmp = Path(tempfile.mkdtemp(prefix="pbs-epubcheck-"))
        try:
            f = tmp / "book.epub"
            f.write_bytes(data)
            proc = subprocess.run([*cmd, str(f)], capture_output=True, text=True, timeout=300, check=False)  # noqa: S603
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
            out.append(item(a, "EPUBCheck", "pass" if proc.returncode == 0 else "fail", " ".join(tail)[:500]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            out.append(
                item(
                    a, "EPUBCheck", "unavailable", f"EPUBCheck could not run: {type(exc).__name__}. This is not a pass."
                )
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out.append(
        item(
            a,
            "Kindle Previewer",
            "manual",
            "Open the EPUB in Kindle Previewer (free from KDP) to see how it looks on Kindle devices.",
        )
    )
    return out


# ---------- DOCX ----------


def docx(data: bytes) -> list[dict[str, str]]:
    a = "Word document (DOCX)"
    out: list[dict[str, str]] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        needed = {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "_rels/.rels"}
        miss = needed - names
        for n in ("word/document.xml", "word/styles.xml", "[Content_Types].xml"):
            if n in names:
                etree.fromstring(z.read(n))
        out.append(
            item(
                a,
                "Package",
                "pass" if not miss else "fail",
                "Required parts present and well-formed." if not miss else "Missing: " + ", ".join(sorted(miss)),
            )
        )
        from docx import Document

        d = Document(io.BytesIO(data))
        heads = [p.text for p in d.paragraphs if p.style is not None and p.style.name.startswith("Heading")]
        out.append(
            item(
                a,
                "Opens in python-docx",
                "pass",
                f"{len(d.paragraphs)} paragraphs, {len(heads)} headings, {len(d.tables)} tables.",
            )
        )
        no_alt = sum(1 for x in d.element.body.xpath(".//wp:docPr") if not x.get("descr"))
        out.append(
            item(
                a,
                "Image alt text",
                "pass" if not no_alt else "fail",
                "Every picture has a description." if not no_alt else f"{no_alt} picture(s) without a description.",
            )
        )
    except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError, ValueError) as exc:
        out.append(item(a, "Package", "fail", f"Not a valid DOCX: {type(exc).__name__}."))
    out.append(item(a, "Equations and table of contents", "manual",
                    "Equations are LaTeX source text; the table of contents is a field Word fills in (Update Field)."))  # fmt: skip
    return out


def summary(items: list[dict[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i["status"]] = out.get(i["status"], 0) + 1
    return out


def disclaimer() -> str:
    return DISCLAIMER.format(ruleset=kdp_rules.RULESET, checked=kdp_rules.CHECKED_ON)


def report_html(title: str, report: dict[str, Any]) -> str:
    import html

    e = html.escape
    rows = "".join(
        f'<tr class="{e(i["status"])}"><td>{e(i["area"])}</td><td>{e(i["check"])}</td><td><strong>{e(i["status"])}</strong></td><td>{e(i["detail"])}</td></tr>'
        for i in report["items"]
    )
    fid = "".join(
        f"<h3>{e(fmt)}: {e(v['summary'])}</h3><table><tr><th>Element</th><th>Expected</th><th>Found</th><th>Status</th><th>Note</th></tr>"
        + "".join(
            f'<tr class="{e(r["status"])}"><td>{e(r["element"])}</td><td>{e(str(r["expected"]))[:200]}</td><td>{e(str(r["found"]))[:200]}</td><td>{e(r["status"])}</td><td>{e(r["note"])}</td></tr>'
            for r in v["rows"]
        )
        + "</table>"
        for fmt, v in report.get("fidelity", {}).items()
    )
    sources = "".join(f'<li>{e(k)}: <a href="{e(v)}">{e(v)}</a></li>' for k, v in report["rules"]["sources"].items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<style>body{{font-family:system-ui,sans-serif;max-width:70em;margin:2em auto;padding:0 1em;line-height:1.45}}
table{{border-collapse:collapse;width:100%;margin:1em 0}}td,th{{border:1px solid #ccc;padding:.35em .5em;text-align:left;vertical-align:top;font-size:.92em}}
tr.fail td,tr.missing td{{background:#fbe3e1}}tr.warn td,tr.degraded td{{background:#fdf3d6}}tr.manual td,tr.unavailable td{{background:#e6eef9}}
.note{{border-left:4px solid #6f5418;padding:.5em 1em;background:#faf6ea}}</style></head><body>
<h1>{e(title)}</h1>
<p class="note">{e(report["disclaimer"])}</p>
<p>Built {e(report["built_at"])}. Rule set <strong>{e(report["rules"]["ruleset"])}</strong>, checked on {e(report["rules"]["checked_on"])}.
Summary: {e(", ".join(f"{k} {v}" for k, v in report["summary"].items()))}.</p>
<h2>Checks</h2><table><tr><th>File</th><th>Check</th><th>Status</th><th>Detail</th></tr>{rows}</table>
<h2>Round-trip fidelity</h2>{fid}
<h2>Rule sources</h2><ul>{sources}</ul>
<h2>Not published by KDP (checked manually)</h2><ul>{"".join(f"<li>{e(x)}</li>" for x in report["rules"]["not_published"])}</ul>
</body></html>
"""
