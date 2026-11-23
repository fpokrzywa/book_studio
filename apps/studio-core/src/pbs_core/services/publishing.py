"""Phase 07 service: publishing profile, exports in five formats, covers, previews and the package."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_publishing import (
    BuildIn,
    BuildOut,
    CoverSpecOut,
    PackageOut,
    PreviewHtmlOut,
    ProfileIn,
    ProfileOut,
    PublicationOut,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.knowledge import retrieval
from pbs_core.publishing import book as book_mod
from pbs_core.publishing import cover as cover_mod
from pbs_core.publishing import (
    fidelity,
    kdp_rules,
    metadata,
    package,
    preflight,
    write_docx,
    write_epub,
    write_html,
    write_markdown,
    write_typst,
)
from pbs_core.services import activity
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.knowledge_models import Source
from pbs_core.storage.models import Asset, ChapterRevision, Project
from pbs_core.storage.paths import atomic_write_bytes, safe_join, sanitize_filename, slugify
from pbs_core.storage.publishing_models import Publication, PublishingProfile

MEDIA = {
    "markdown": "application/zip",
    "html": "text/html; charset=utf-8",
    "epub": "application/epub+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "cover_print": "application/pdf",
    "cover_proof": "application/pdf",
    "cover_ebook": "image/jpeg",
    "package": "application/zip",
}
EXT = {"markdown": "md.zip", "html": "html", "epub": "epub", "docx": "docx", "pdf": "pdf"}
IMAGE_GENERATION = "Not configured. PBS has no image generation provider; use artwork you have the rights to."


def _tools() -> dict[str, Any]:
    import typst

    return {
        "pdf_engine": f"Typst {getattr(typst, '__version__', '')} (built in)".strip(),
        "epubcheck": "available" if preflight.epubcheck_command() else "unavailable",
        "epubcheck_note": "Install EPUBCheck (needs Java) or set PBS_EPUBCHECK_JAR to validate EPUBs officially.",
        "image_generation": IMAGE_GENERATION,
        "mobi": "Not built. MOBI/AZW3 are not needed for KDP (it takes EPUB); no converter is installed.",
    }


def _rules() -> dict[str, Any]:
    return {
        "ruleset": kdp_rules.RULESET,
        "checked_on": kdp_rules.CHECKED_ON,
        "sources": kdp_rules.SOURCES,
        "not_published": kdp_rules.NOT_PUBLISHED,
        "ai_definitions": kdp_rules.AI_DEFINITIONS,
    }


def _options() -> dict[str, Any]:
    return {
        "templates": {k: {"label": v["label"], "trim": v["trim"]} for k, v in book_mod.TEMPLATES.items()},
        "trims": {
            k: {"width_in": str(w), "height_in": str(h), "pages": {ip: list(r) if r else None for ip, r in rng.items()}}
            for k, (w, h, rng) in kdp_rules.TRIM_SIZES.items()
        },
        "ink_paper": kdp_rules.INK_PAPER_LABELS,
        "matter_kinds": {
            k: {"position": p, "title": t, "generated": g} for k, (p, t, g) in book_mod.MATTER_KINDS.items()
        },
        "fonts": list(cover_mod.FONTS),
        "font_licenses": book_mod.FONT_LICENSES,
        "keyword_slots": kdp_rules.KEYWORD_SLOTS,
        "category_max": kdp_rules.CATEGORY_MAX,
    }


def _ai_evidence(s: Session, project_id: str) -> dict[str, Any]:
    n = s.scalar(
        select(func.count())
        .select_from(ChapterRevision)
        .where(ChapterRevision.project_id == project_id, ChapterRevision.origin.in_(("ai_generated", "ai_assisted")))
    )
    return {"ai_revisions": int(n or 0)}


def _profile_dict(s: Session, project: Project) -> dict[str, Any]:
    p = s.get(PublishingProfile, project.id)
    if p is None:
        tpl = (
            "novel"
            if project.project_type in ("fiction", "serial")
            else "technical_manual"
            if project.project_type in ("technical", "course")
            else "workbook"
            if project.project_type == "workbook"
            else "nonfiction"
        )
        return {
            "template": tpl,
            "trim": book_mod.TEMPLATES[tpl]["trim"],
            "ink_paper": "bw_white",
            "matter": book_mod.default_matter(tpl),
            "copyright": {},
            "metadata": metadata.defaults(project.title, project.subtitle, project.author_name, project.language),
            "cover": {"layers": cover_mod.default_layers(project.title, project.subtitle, project.author_name)},
            "index_terms": [],
            "updated_at": None,
        }
    return {
        "template": p.template,
        "trim": p.trim,
        "ink_paper": p.ink_paper,
        "matter": json.loads(p.matter_json),
        "copyright": json.loads(p.copyright_json),
        "metadata": json.loads(p.metadata_json),
        "cover": json.loads(p.cover_json),
        "index_terms": json.loads(p.index_terms_json),
        "updated_at": p.updated_at,
    }


def _profile_out(s: Session, project: Project) -> ProfileOut:
    d = _profile_dict(s, project)
    return ProfileOut(
        **{k: v for k, v in d.items()},
        options=_options(),
        rules=_rules(),
        tools=_tools(),
        ai_evidence=_ai_evidence(s, project.id),
    )


def get_profile(ctx: AppContext, project_id: str) -> ProfileOut:
    with ctx.db.tx() as s:
        return _profile_out(s, require_project(s, project_id))


def put_profile(ctx: AppContext, project_id: str, data: ProfileIn) -> ProfileOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        if data.trim not in kdp_rules.TRIM_SIZES:
            raise ValidationFailedError(f"Unknown trim size {data.trim}.")
        if kdp_rules.page_range(data.trim, data.ink_paper) is None:
            raise ValidationFailedError(
                f"KDP does not offer {data.trim} with {kdp_rules.INK_PAPER_LABELS[data.ink_paper]}."
            )
        kinds = [m.kind for m in data.matter]
        unknown = [k for k in kinds if k not in book_mod.MATTER_KINDS]
        if unknown:
            raise ValidationFailedError("Unknown matter: " + ", ".join(unknown))
        if data.copyright.isbn.strip() and not book_mod.isbn_valid(data.copyright.isbn):
            raise ValidationFailedError(
                "That ISBN has an invalid check digit. Enter the ISBN exactly as assigned to you."
            )
        if data.cover.artwork_asset:
            a = s.scalars(
                select(Asset).where(Asset.project_id == project_id, Asset.short_hash == data.cover.artwork_asset)
            ).first()
            if a is None:
                raise NotFoundError("That artwork is not an image in this book.")
            if not data.cover.artwork_license.confirmed:
                raise ValidationFailedError(
                    "Confirm that you have the right to use this artwork on a book cover you sell."
                )
        p = s.get(PublishingProfile, project_id)
        now = ctx.clock.iso()
        values = {
            "template": data.template,
            "trim": data.trim,
            "ink_paper": data.ink_paper,
            "matter_json": json.dumps([m.model_dump() for m in data.matter], ensure_ascii=False),
            "copyright_json": json.dumps(data.copyright.model_dump(), ensure_ascii=False),
            "metadata_json": json.dumps(data.metadata.model_dump(), ensure_ascii=False),
            "cover_json": json.dumps(data.cover.model_dump(), ensure_ascii=False),
            "index_terms_json": json.dumps(data.index_terms, ensure_ascii=False),
            "updated_at": now,
        }
        if p is None:
            s.add(PublishingProfile(project_id=project_id, **values))
        else:
            for k, v in values.items():
                setattr(p, k, v)
        s.flush()
        return _profile_out(s, project)


# ---------- building ----------


def _book(ctx: AppContext, s: Session, project: Project, prof: dict[str, Any]) -> book_mod.Book:
    b = book_mod.assemble(
        ctx,
        s,
        project,
        {
            "template": prof["template"],
            "matter": prof["matter"],
            "copyright": prof["copyright"],
            "index_terms": prof["index_terms"],
        },
    )
    b.template = {**b.template, "trim": prof["trim"]}
    return b


def _report(items: list[dict[str, str]], fid: dict[str, Any], built_at: str) -> dict[str, Any]:
    return {
        "items": items,
        "fidelity": fid,
        "summary": preflight.summary(items + [{"status": "fail"} for v in fid.values() if v["summary"] == "missing"]),
        "rules": _rules(),
        "disclaimer": preflight.disclaimer(),
        "built_at": built_at,
    }


def _save(ctx: AppContext, s: Session, project: Project, prof: dict[str, Any], kind: str, data: bytes, file_name: str,
          report: dict[str, Any], *, book: book_mod.Book, page_count: int | None = None, settings: dict[str, Any] | None = None,
          package_id: str | None = None) -> Publication:  # fmt: skip
    pid = ctx.ids.new()
    rel = f"publish/{pid}/{file_name}"
    base = ctx.workspace.project_dir(project.id)
    atomic_write_bytes(safe_join(base, rel), data)
    atomic_write_bytes(safe_join(base, f"publish/{pid}/{file_name}.report.json"), package.dumps(report))
    pub = Publication(
        id=pid,
        project_id=project.id,
        kind=kind,
        status="succeeded",
        package_id=package_id,
        file_name=file_name,
        output_path=rel,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        page_count=page_count,
        template=prof["template"],
        trim=prof["trim"],
        ink_paper=prof["ink_paper"],
        ruleset=kdp_rules.RULESET,
        revision_set_json=json.dumps({c.id: c.revision_no for c in book.chapters}),
        settings_json=json.dumps(settings or {}, ensure_ascii=False),
        report_json=json.dumps(report, ensure_ascii=False),
        created_at=ctx.clock.iso(),
    )
    s.add(pub)
    s.flush()
    return pub


def _build_formats(ctx: AppContext, s: Session, project: Project, prof: dict[str, Any], formats: list[str],
                   package_id: str | None = None) -> tuple[list[Publication], book_mod.Book, dict[str, bytes], Any]:  # fmt: skip
    b = _book(ctx, s, project, prof)
    inv = fidelity.inventory(b)
    stem = sanitize_filename(project.title)
    built_at = ctx.clock.iso()
    pubs: list[Publication] = []
    blobs: dict[str, bytes] = {}
    fid: dict[str, dict[str, Any]]
    typst_build = None
    for fmt in formats:
        if fmt == "markdown":
            data, text = write_markdown.build(b)
            fid = {"markdown": {"rows": fidelity.check_markdown(b, text), "summary": ""}}
            items = [
                preflight.item(
                    "Markdown",
                    "Chapters",
                    "pass",
                    f"{len(b.chapters)} chapter(s), text verbatim; {len(b.assets)} image file(s).",
                )
            ]
        elif fmt == "html":
            data, st = write_html.standalone(b)
            fid = {"html": {"rows": fidelity.check_html(inv, data), "summary": ""}}
            items = [
                preflight.item(
                    "HTML", "Self-contained", "pass", "Images embedded; no web requests (Content-Security-Policy)."
                )
            ]
            if st["broken_links"]:
                items.append(
                    preflight.item(
                        "HTML",
                        "Internal links",
                        "warn",
                        "Links to missing anchors: " + ", ".join(sorted(set(st["broken_links"]))),
                    )
                )
        elif fmt == "epub":
            cover_jpeg = None
            if prof.get("cover"):
                art = _artwork(s, ctx, project.id, prof["cover"])
                cover_jpeg, _ = cover_mod.build_ebook(prof["cover"], kdp_rules.TRIM_SIZES[prof["trim"]][0], art)
            eb = write_epub.build(b, cover_jpeg)
            data = eb.data
            fid = {"epub": {"rows": fidelity.check_epub(inv, data), "summary": ""}}
            items = preflight.epub(data)
        elif fmt == "docx":
            data, _ds = write_docx.build(b)
            fid = {"docx": {"rows": fidelity.check_docx(inv, data), "summary": ""}}
            items = preflight.docx(data)
        elif fmt == "pdf":
            try:
                typst_build = write_typst.build(b, prof["trim"])
            except write_typst.LayoutError as exc:
                raise ConflictError(str(exc)[:500], extra={"reason": "layout_failed"}) from exc
            data = typst_build.pdf
            fid = {"pdf": {"rows": fidelity.check_pdf(inv, data, typst_build.stats), "summary": ""}}
            items = preflight.pdf_interior(
                data, b, prof["trim"], prof["ink_paper"], typst_build.inside_in, typst_build.stats
            )
        else:  # pragma: no cover - validated by the contract
            raise ValidationFailedError(f"Unknown format {fmt}")
        for v in fid.values():
            v["summary"] = fidelity.summarize(v["rows"])
        items += [preflight.item("Book", w["code"], "warn", w["message"]) for w in b.warnings]
        report = _report(items, fid, built_at)
        name = f"{stem}.{EXT[fmt]}" if fmt != "pdf" else f"{stem}-interior-{prof['trim']}.pdf"
        settings = (
            {"inside_margin_in": str(typst_build.inside_in), "layout_passes": typst_build.passes}
            if fmt == "pdf" and typst_build
            else {}
        )
        pub = _save(ctx, s, project, prof, fmt, data, name, report, book=b,
                    page_count=typst_build.page_count if fmt == "pdf" and typst_build else None, settings=settings, package_id=package_id)  # fmt: skip
        pubs.append(pub)
        blobs[fmt] = data
    return pubs, b, blobs, typst_build


def build(ctx: AppContext, project_id: str, data: BuildIn) -> BuildOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        prof = _profile_dict(s, project)
        pubs, b, _blobs, _tb = _build_formats(ctx, s, project, prof, list(dict.fromkeys(data.formats)))
        activity.record(s, ctx, kind="publication_built", project_id=project_id, ref_type="project", ref_id=project_id,
                        summary=f"Built {', '.join(p.kind.upper() for p in pubs)} for “{project.title}”")  # fmt: skip
        return BuildOut(publications=[_pub_out(p) for p in pubs], warnings=b.warnings)


def _artwork(s: Session, ctx: AppContext, project_id: str, cfg: dict[str, Any]) -> tuple[bytes, str, int, int] | None:
    h = cfg.get("artwork_asset")
    if not h:
        return None
    a = s.scalars(select(Asset).where(Asset.project_id == project_id, Asset.short_hash == h)).first()
    if a is None:
        return None
    from pbs_core.services.exports import _asset_bytes

    ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(a.mime, "png")
    return _asset_bytes(ctx, a), ext, a.width_px or 0, a.height_px or 0


def _latest(s: Session, project_id: str, kind: str, package_id: str | None = None) -> Publication | None:
    stmt = select(Publication).where(
        Publication.project_id == project_id, Publication.kind == kind, Publication.status == "succeeded"
    )
    if package_id:
        stmt = stmt.where(Publication.package_id == package_id)
    return s.scalars(stmt.order_by(Publication.created_at.desc(), Publication.id.desc())).first()


def cover_spec(ctx: AppContext, project_id: str) -> CoverSpecOut:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        prof = _profile_dict(s, project)
        pdf = _latest(s, project_id, "pdf")
        last = _latest(s, project_id, "cover_print")
        latest_cover = None
        if last is not None:
            st = json.loads(last.settings_json)
            stale = pdf is not None and (
                st.get("interior_publication_id") != pdf.id or last.page_count != pdf.page_count
            )
            latest_cover = {"publication_id": last.id, "page_count": last.page_count, "built_at": last.created_at, "stale": stale,
                            "width_in": st.get("spec", {}).get("cover_width_in")}  # fmt: skip
        if pdf is None or pdf.page_count is None:
            return CoverSpecOut(spec=None, based_on_pdf=None, latest_cover=latest_cover,
                                message="Build the print PDF first: the spine width depends on the final page count.")  # fmt: skip
        if pdf.trim != prof["trim"] or pdf.ink_paper != prof["ink_paper"]:
            msg = "The print PDF was built with a different trim or paper; build it again before the cover."
        else:
            msg = "Sized from the final page count of the latest print PDF."
        try:
            spec = kdp_rules.cover_spec(prof["trim"], prof["ink_paper"], pdf.page_count).as_dict()
        except ValueError as exc:
            return CoverSpecOut(spec=None, based_on_pdf=None, latest_cover=latest_cover, message=str(exc))
        return CoverSpecOut(
            spec=spec,
            based_on_pdf={
                "publication_id": pdf.id,
                "page_count": pdf.page_count,
                "built_at": pdf.created_at,
                "trim": pdf.trim,
            },
            latest_cover=latest_cover,
            message=msg
            + (
                " The last cover was built for a different page count: build it again."
                if latest_cover and latest_cover["stale"]
                else ""
            ),
        )


def _covers(ctx: AppContext, s: Session, project: Project, prof: dict[str, Any], pdf: Publication, b: book_mod.Book,
            package_id: str | None = None) -> list[Publication]:  # fmt: skip
    if pdf.page_count is None:
        raise ConflictError("Build the print PDF first: the spine width depends on the final page count.")
    try:
        spec = kdp_rules.cover_spec(prof["trim"], prof["ink_paper"], pdf.page_count)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    cfg = prof.get("cover") or {}
    if not cfg.get("layers"):
        cfg = {**cfg, "layers": cover_mod.default_layers(project.title, project.subtitle, project.author_name)}
    art = _artwork(s, ctx, project.id, cfg)
    cb = cover_mod.build_print(cfg, spec, art)
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(cb.pdf))
    w = round(float(r.pages[0].mediabox.width) / 72, 4)
    h = round(float(r.pages[0].mediabox.height) / 72, 4)
    a = "Print cover (PDF)"
    items = [
        preflight.item(a, "Single page", "pass" if len(r.pages) == 1 else "fail", f"{len(r.pages)} page(s)."),
        preflight.item(
            a,
            "Dimensions",
            "pass" if abs(w - float(spec.width)) < 0.01 and abs(h - float(spec.height)) < 0.01 else "fail",
            f"{w} × {h} in; expected {spec.width} × {spec.height} in for {pdf.page_count} pages.",
        ),
        preflight.item(a, "Based on final page count", "pass", f"Interior PDF {pdf.id} with {pdf.page_count} pages."),
    ] + [preflight.item(a, x["check"], x["status"], x["detail"]) for x in cb.report]
    if cfg.get("artwork_asset") and not (cfg.get("artwork_license") or {}).get("confirmed"):
        items.append(preflight.item(a, "Artwork rights", "fail", "You have not confirmed you may use this artwork."))
    items.append(
        preflight.item(
            a,
            "Printer check",
            "manual",
            "Compare with KDP's cover calculator template for this trim, paper and page count, and order a printed proof.",
        )
    )
    settings = {"spec": spec.as_dict(), "interior_publication_id": pdf.id}
    report = _report(items, {}, ctx.clock.iso())
    stem = sanitize_filename(project.title)
    out = [
        _save(
            ctx,
            s,
            project,
            prof,
            "cover_print",
            cb.pdf,
            f"{stem}-cover-{prof['trim']}-{pdf.page_count}p.pdf",
            report,
            book=b,
            page_count=pdf.page_count,
            settings=settings,
            package_id=package_id,
        ),
        _save(
            ctx,
            s,
            project,
            prof,
            "cover_proof",
            cb.proof_pdf,
            f"{stem}-cover-proof-NOT-FOR-UPLOAD.pdf",
            report,
            book=b,
            page_count=pdf.page_count,
            settings=settings,
            package_id=package_id,
        ),
    ]
    jpg, erep = cover_mod.build_ebook(cfg, spec.trim_w, art)
    eitems = [preflight.item("eBook cover (JPEG)", x["check"], x["status"], x["detail"]) for x in erep]
    out.append(
        _save(
            ctx,
            s,
            project,
            prof,
            "cover_ebook",
            jpg,
            f"{stem}-ebook-cover.jpg",
            _report(eitems, {}, ctx.clock.iso()),
            book=b,
            package_id=package_id,
        )
    )
    return out


def build_covers(ctx: AppContext, project_id: str) -> BuildOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        prof = _profile_dict(s, project)
        pdf = _latest(s, project_id, "pdf")
        if pdf is None:
            raise ConflictError("Build the print PDF first: the spine width depends on the final page count.")
        if pdf.trim != prof["trim"] or pdf.ink_paper != prof["ink_paper"]:
            raise ConflictError("The print PDF was built with a different trim or paper. Build the PDF again first.")
        b = _book(ctx, s, project, prof)
        pubs = _covers(ctx, s, project, prof, pdf, b)
        activity.record(s, ctx, kind="cover_built", project_id=project_id, ref_type="publication", ref_id=pubs[0].id,
                        summary=f"Built covers for “{project.title}” ({pdf.page_count} pages)")  # fmt: skip
        return BuildOut(publications=[_pub_out(p) for p in pubs], warnings=[])


def build_package(ctx: AppContext, project_id: str) -> PackageOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        prof = _profile_dict(s, project)
        pkg_id = ctx.ids.new()
        pubs, b, blobs, _tb = _build_formats(
            ctx, s, project, prof, ["markdown", "html", "epub", "docx", "pdf"], package_id=pkg_id
        )
        pdf_pub = next(p for p in pubs if p.kind == "pdf")
        cover_pubs = _covers(ctx, s, project, prof, pdf_pub, b, package_id=pkg_id)
        cover_files = {
            p.kind: (p, safe_join(ctx.workspace.project_dir(project_id), p.output_path or "").read_bytes())
            for p in cover_pubs
        }
        meta = prof["metadata"]
        meta_items = metadata.check(
            meta, project.title, project.subtitle, project.author_name, _ai_evidence(s, project_id)
        )
        all_items: list[dict[str, Any]] = []
        all_fid: dict[str, Any] = {}
        for p in pubs + cover_pubs:
            rep = json.loads(p.report_json)
            all_items += [i for i in rep["items"] if i not in all_items]
            all_fid.update(rep.get("fidelity", {}))
        all_items += meta_items
        report = _report(all_items, all_fid, ctx.clock.iso())
        stem = sanitize_filename(project.title)
        files: dict[str, bytes] = {
            f"book/{stem}.md.zip": blobs["markdown"],
            f"book/{stem}.html": blobs["html"],
            f"book/{stem}.epub": blobs["epub"],
            f"book/{stem}.docx": blobs["docx"],
            f"book/{stem}-interior-{prof['trim']}.pdf": blobs["pdf"],
            "cover/print-cover.pdf": cover_files["cover_print"][1],
            "cover/print-cover-proof-NOT-FOR-UPLOAD.pdf": cover_files["cover_proof"][1],
            "cover/ebook-cover.jpg": cover_files["cover_ebook"][1],
        }
        cover_spec_d = json.loads(cover_files["cover_print"][0].settings_json)["spec"]
        meta_json = {
            "title": project.title,
            "subtitle": project.subtitle,
            "author": project.author_name,
            **meta,
            "categories_note": "Suggestions only, unverified: choose categories in KDP's picker.",
            "print": {
                "trim": prof["trim"],
                "ink_paper": prof["ink_paper"],
                "page_count": pdf_pub.page_count,
                "bleed": False,
                "cover": cover_spec_d,
            },
            "ruleset": kdp_rules.RULESET,
        }
        files["metadata.json"] = package.dumps(meta_json)
        files["metadata.txt"] = metadata.as_text(meta, project.title, project.subtitle, project.author_name).encode(
            "utf-8"
        )
        files["preflight-report.json"] = package.dumps(report)
        files["preflight-report.html"] = preflight.report_html(f"Preflight report: {project.title}", report).encode(
            "utf-8"
        )
        files["COPYRIGHT-AND-LICENSES.txt"] = package.licenses_text(b, prof.get("cover")).encode("utf-8")
        libs = retrieval.library_ids(s, project_id)
        knowledge = [{"title": x.title, "kind": x.kind, "removed": x.removed_at is not None}
                     for x in (s.scalars(select(Source).where(Source.library_id.in_(libs))).all() if libs else [])]  # fmt: skip
        files["SOURCES.txt"] = package.sources_text(b, knowledge).encode("utf-8")
        names = {"epub": f"book/{stem}.epub", "pdf": f"book/{stem}-interior-{prof['trim']}.pdf"}
        files["KDP-UPLOAD-STEPS.md"] = package.upload_steps(b, names, cover_spec_d).encode("utf-8")
        folder_rel = f"publish/packages/{pkg_id}/{slugify(project.title) or 'book'}"
        folder = safe_join(ctx.workspace.project_dir(project_id), folder_rel)
        manifest = package.write(folder, files)
        manifest.update(
            {"package_id": pkg_id, "built_at": report["built_at"], "ruleset": kdp_rules.RULESET, "auto_publish": False}
        )
        files["manifest.json"] = package.dumps(manifest)
        atomic_write_bytes(folder / "manifest.json", files["manifest.json"])
        zipped = package.zip_folder(files, slugify(project.title) or "book")
        pkg = Publication(
            id=pkg_id,
            project_id=project_id,
            kind="package",
            status="succeeded",
            package_id=pkg_id,
            file_name=f"{slugify(project.title) or 'book'}-kdp-package.zip",
            output_path=f"publish/packages/{pkg_id}/{slugify(project.title) or 'book'}-kdp-package.zip",
            sha256=hashlib.sha256(zipped).hexdigest(),
            byte_size=len(zipped),
            page_count=pdf_pub.page_count,
            template=prof["template"],
            trim=prof["trim"],
            ink_paper=prof["ink_paper"],
            ruleset=kdp_rules.RULESET,
            revision_set_json=json.dumps({c.id: c.revision_no for c in b.chapters}),
            settings_json=json.dumps({"folder": folder_rel, "files": manifest["files"]}),
            report_json=json.dumps(report, ensure_ascii=False),
            created_at=ctx.clock.iso(),
        )
        atomic_write_bytes(safe_join(ctx.workspace.project_dir(project_id), pkg.output_path or ""), zipped)
        s.add(pkg)
        s.flush()
        activity.record(s, ctx, kind="package_built", project_id=project_id, ref_type="publication", ref_id=pkg_id,
                        summary=f"Built the publish package for “{project.title}” (not uploaded anywhere)")  # fmt: skip
        return PackageOut(
            publication=_pub_out(pkg),
            folder=str(folder),
            files=[{"name": k, **v} for k, v in manifest["files"].items()],
            report_summary=report["summary"],
        )


# ---------- reading ----------


def _pub_out(p: Publication) -> PublicationOut:
    rep = json.loads(p.report_json or "{}")
    fid = rep.get("fidelity") or {}
    worst = None
    if fid:
        vals = [v["summary"] for v in fid.values()]
        worst = "missing" if "missing" in vals else "degraded" if "degraded" in vals else "ok"
    return PublicationOut(
        id=p.id,
        kind=p.kind,
        status=p.status,
        package_id=p.package_id,
        file_name=p.file_name,
        sha256=p.sha256,
        byte_size=p.byte_size,
        page_count=p.page_count,
        template=p.template,
        trim=p.trim,
        ink_paper=p.ink_paper,
        ruleset=p.ruleset,
        settings={k: v for k, v in json.loads(p.settings_json or "{}").items() if k != "files"},
        report_summary=rep.get("summary") or {},
        fidelity=worst,
        error=p.error,
        created_at=p.created_at,
    )


def list_publications(ctx: AppContext, project_id: str) -> list[PublicationOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(
            select(Publication)
            .where(Publication.project_id == project_id)
            .order_by(Publication.created_at.desc(), Publication.id.desc())
            .limit(100)
        ).all()
        return [_pub_out(p) for p in rows]


def _require(s: Session, project_id: str, pub_id: str) -> Publication:
    p = s.get(Publication, pub_id) if is_ulid(pub_id) else None
    if p is None or p.project_id != project_id:
        raise NotFoundError("Build not found in this book.")
    return p


def report(ctx: AppContext, project_id: str, pub_id: str) -> dict[str, Any]:
    with ctx.db.tx() as s:
        return dict(json.loads(_require(s, project_id, pub_id).report_json))


def report_html(ctx: AppContext, project_id: str, pub_id: str) -> str:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        p = _require(s, project_id, pub_id)
        return preflight.report_html(f"Preflight report: {project.title} ({p.kind})", json.loads(p.report_json))


def publication_file(ctx: AppContext, project_id: str, pub_id: str) -> tuple[Path, str, str]:
    with ctx.db.tx() as s:
        p = _require(s, project_id, pub_id)
        path = safe_join(ctx.workspace.project_dir(project_id), p.output_path or "")
        if not path.is_file():
            raise NotFoundError("The file is missing from disk.")
        return path, p.file_name or path.name, MEDIA.get(p.kind, "application/octet-stream")


def package_file(ctx: AppContext, project_id: str, pub_id: str, name: str) -> tuple[Path, str, str]:
    with ctx.db.tx() as s:
        p = _require(s, project_id, pub_id)
        if p.kind != "package":
            raise NotFoundError("Not a publish package.")
        files = json.loads(p.settings_json).get("files", {})
        if name not in files:
            raise NotFoundError("No such file in this package.")
        folder = json.loads(p.settings_json)["folder"]
        path = safe_join(ctx.workspace.project_dir(project_id), folder, *name.split("/"))
        media = {".html": "text/html; charset=utf-8", ".json": "application/json", ".txt": "text/plain; charset=utf-8",
                 ".md": "text/markdown; charset=utf-8", ".pdf": "application/pdf", ".jpg": "image/jpeg",
                 ".epub": "application/epub+zip", ".docx": MEDIA["docx"], ".zip": "application/zip"}  # fmt: skip
        return path, Path(name).name, media.get(Path(name).suffix, "application/octet-stream")


# ---------- previews ----------


def preview_html(ctx: AppContext, project_id: str) -> PreviewHtmlOut:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        prof = _profile_dict(s, project)
        b = _book(ctx, s, project, prof)
        data, _st = write_html.standalone(b)
        sha = hashlib.sha256(data).hexdigest()
        last = _latest(s, project_id, "html")
        same = None if last is None else last.sha256 == sha
        note = (
            "No HTML export yet: this preview is what an export would contain right now."
            if last is None
            else "Byte-identical to your last HTML export."
            if same
            else "Not identical to your last HTML export: the book or settings changed since. Export again to update it."
        )
        return PreviewHtmlOut(html=data.decode("utf-8"), sha256=sha, identical_to_last_export=same, note=note)


def preview_pdf_pages(ctx: AppContext, project_id: str, page: int, ppi: int = 50) -> tuple[bytes, int]:
    """One page image from a fresh layout of the current book (the same Typst source the PDF export uses)."""
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        prof = _profile_dict(s, project)
        b = _book(ctx, s, project, prof)
        tb = write_typst.build(b, prof["trim"])
        pages = write_typst.render_png_pages(tb.source, b, ppi=ppi)
        if not 1 <= page <= len(pages):
            raise NotFoundError(f"The book has {len(pages)} pages.")
        return pages[page - 1], len(pages)


def preview_note() -> str:
    return (
        "Page images are rendered from the same Typst layout the PDF export uses, but they are pictures, not the PDF "
        "file: they are not byte-identical to an export. Open the exported PDF to check the exact file you upload."
    )
