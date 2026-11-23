"""Covers: a print full-wrap cover (back + spine + front, with bleed) and a front-only eBook cover.

* Artwork is an image the author uploaded and declared they have the right to use. PBS has no image
  generation provider configured, and it never asks an image model to draw lettering.
* Title, subtitle, author, spine and back-cover text are typography layers set by Typst: real,
  editable text in embedded fonts, positioned within the safe area.
* Sizes come from kdp_rules.cover_spec with the FINAL interior page count, so a new interior PDF with
  a different page count changes the spine and the full width automatically.
* The barcode area (KDP's suggested 2 × 1.2 in, at least 0.25 in from the spine and trim) is kept
  clear and white. KDP does not publish its exact position, so the report asks for a manual check
  against KDP's cover template.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import typst

from pbs_core.publishing import kdp_rules
from pbs_core.publishing.kdp_rules import CoverSpec

FONTS = ("Libertinus Serif", "New Computer Modern", "DejaVu Sans Mono")
TEXT_INSET = Decimal("0.375")  # text boxes stay this far inside the trim (KDP minimum is 0.125)
EBOOK_W_IN, EBOOK_H_IN, EBOOK_PPI = Decimal("5"), Decimal("8"), 320  # 1600 x 2560 px


def default_layers(title: str, subtitle: str | None, author: str | None) -> list[dict[str, Any]]:
    layers = [{"role": "title", "text": title, "font": FONTS[0], "size_pt": 34, "weight": "bold", "y": 0.22}]
    if subtitle:
        layers.append(
            {"role": "subtitle", "text": subtitle, "font": FONTS[0], "size_pt": 16, "weight": "regular", "y": 0.42}
        )
    if author:
        layers.append(
            {"role": "author", "text": author, "font": FONTS[0], "size_pt": 18, "weight": "regular", "y": 0.82}
        )
    layers.append(
        {
            "role": "spine",
            "text": f"{title}" + (f"  ·  {author}" if author else ""),
            "font": FONTS[0],
            "size_pt": 10,
            "weight": "regular",
            "y": 0.5,
        }
    )
    layers.append({"role": "back_text", "text": "", "font": FONTS[0], "size_pt": 11, "weight": "regular", "y": 0.12})
    return layers


def _s(x: str) -> str:
    return json.dumps(x, ensure_ascii=False)


def _color(c: str | None, default: str) -> str:
    c = (c or default).strip()
    if len(c) == 7 and c.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in c[1:]):
        return f'rgb("{c}")'
    return f'rgb("{default}")'


@dataclass
class CoverBuild:
    pdf: bytes
    proof_pdf: bytes
    spec: CoverSpec
    report: list[dict[str, Any]] = field(default_factory=list)
    artwork_dpi: int | None = None


def _text_box(layer: dict[str, Any], x: Decimal, y_top: Decimal, w: Decimal, color: str, scale: float = 1.0) -> str:
    size = max(7.0, float(layer.get("size_pt") or 12) * scale)  # KDP: text at least 7 pt
    weight = "bold" if layer.get("weight") == "bold" else "regular"
    font = layer.get("font") if layer.get("font") in FONTS else FONTS[0]
    align = {"left": "left", "right": "right"}.get(layer.get("align") or "", "center")
    return (
        f"#place(top + left, dx: {x}in, dy: {y_top}in, box(width: {w}in)[#set align({align})\n"
        f"#set par(leading: 0.35em)\n"
        f'#text(font: {_s(str(font))}, size: {size}pt, weight: "{weight}", fill: {color})[{_esc(layer.get("text") or "")}]]'
        ")"
    )


def _compile(source: str, files: dict[str, bytes], *, fmt: str = "pdf", ppi: int | None = None) -> Any:
    work = Path(tempfile.mkdtemp(prefix="pbs-cover-"))
    try:
        for name, data in files.items():
            (work / name).write_bytes(data)
        (work / "cover.typ").write_text(source, encoding="utf-8")
        kw: dict[str, Any] = {"root": str(work), "ignore_system_fonts": True, "timestamp": 1767225600}
        if fmt == "png":
            kw.update(format="png", ppi=ppi)
        return typst.compile(str(work / "cover.typ"), **kw)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_print(cfg: dict[str, Any], spec: CoverSpec, artwork: tuple[bytes, str, int, int] | None) -> CoverBuild:
    """artwork: (bytes, extension, width_px, height_px) or None."""
    W, H, b = spec.width, spec.height, spec.bleed
    tw, th, sp = spec.trim_w, spec.trim_h, spec.spine
    back_x, spine_x, front_x = b, b + tw, b + tw + sp
    bg = _color(cfg.get("background"), "#1f3a5f")
    fg = _color(cfg.get("text_color"), "#ffffff")
    layers = cfg.get("layers") or []
    report: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    body = [f"#set page(width: {W}in, height: {H}in, margin: 0pt, fill: {bg})", '#set text(lang: "en")']
    dpi = None
    if artwork:
        data, ext, wpx, hpx = artwork
        files[f"art.{ext}"] = data
        wrap = cfg.get("artwork_fit") == "wrap"
        ax, aw = (Decimal(0), W) if wrap else (front_x, W - front_x)
        body.append(
            f'#place(top + left, dx: {ax}in, dy: 0in, image("art.{ext}", width: {aw}in, height: {H}in, fit: "cover"))'
        )
        scale = max(aw / Decimal(wpx), H / Decimal(hpx)) if wpx and hpx else Decimal(1)
        dpi = int(Decimal(1) / scale) if scale else None
        status = "pass" if dpi and dpi >= kdp_rules.MIN_IMAGE_DPI else "fail"
        report.append({"check": "Artwork resolution", "status": status,
                       "detail": f"About {dpi} DPI where it is placed (KDP asks for at least {kdp_rules.MIN_IMAGE_DPI})."})  # fmt: skip
    text_w = tw - 2 * TEXT_INSET
    for layer in layers:
        role = layer.get("role")
        if not (layer.get("text") or "").strip():
            continue
        y = Decimal(str(layer.get("y", 0.2)))
        if role in ("title", "subtitle", "author"):
            top = b + TEXT_INSET + (th - 2 * TEXT_INSET) * y
            body.append(
                _text_box(
                    layer,
                    front_x + TEXT_INSET,
                    top,
                    text_w,
                    _color(layer.get("color"), "#ffffff") if layer.get("color") else fg,
                )
            )
        elif role == "back_text":
            top = b + TEXT_INSET + (th - 2 * TEXT_INSET) * y
            body.append(_text_box({**layer, "align": "left"}, back_x + TEXT_INSET, top, text_w, fg))
        elif role == "spine":
            if not spec.spine_text_allowed:
                report.append({"check": "Spine text", "status": "pass",
                               "detail": f"Left off: KDP allows spine text from {kdp_rules.SPINE_TEXT_MIN_PAGES} pages; this book has {spec.page_count}."})  # fmt: skip
                continue
            room = sp - 2 * kdp_rules.SPINE_TEXT_MARGIN
            max_pt = float(room) * 72 * 0.72
            size = min(float(layer.get("size_pt") or 10), max_pt)
            if size < kdp_rules.MIN_TEXT_PT:
                report.append({"check": "Spine text", "status": "warn",
                               "detail": f"The spine is {sp} in wide: text would be under {kdp_rules.MIN_TEXT_PT} pt, so it was left off."})  # fmt: skip
                continue
            cx = spine_x + sp / 2
            body.append(
                f"#place(top + left, dx: {cx}in, dy: {H / 2}in, rotate(90deg, origin: center + horizon, "
                f"box(width: {th - 2 * TEXT_INSET}in, align(center, text(font: {_s(layer.get('font') if layer.get('font') in FONTS else FONTS[0])}, "
                f"size: {round(size, 2)}pt, fill: {fg})[{_esc(layer['text'])}]))))"
            )
            report.append({"check": "Spine text", "status": "pass",
                           "detail": f"{round(size, 1)} pt, at least {kdp_rules.SPINE_TEXT_MARGIN} in from each spine edge."})  # fmt: skip
    bw, bh = kdp_rules.BARCODE_SUGGESTED
    bx = spine_x - kdp_rules.BARCODE_EDGE - bw
    by = b + th - kdp_rules.BARCODE_EDGE - bh
    body.append(
        f"#place(top + left, dx: {bx}in, dy: {by}in, rect(width: {bw}in, height: {bh}in, fill: white, stroke: none))"
    )
    report.append({"check": "Barcode area", "status": "manual",
                   "detail": f"A white {bw} × {bh} in area is kept clear {kdp_rules.BARCODE_EDGE} in from the spine and bottom trim. "
                             "KDP does not publish where it places its barcode: compare with KDP's cover template."})  # fmt: skip
    source = "\n".join(body) + "\n"
    pdf = _compile(source, files)
    guides = [
        f'#place(top + left, dx: {b}in, dy: {b}in, rect(width: {W - 2 * b}in, height: {th}in, stroke: (paint: red, thickness: 0.5pt, dash: "dashed")))',
        f"#place(top + left, dx: {spine_x}in, dy: 0in, line(length: {H}in, angle: 90deg, stroke: (paint: blue, thickness: 0.5pt)))",
        f"#place(top + left, dx: {front_x}in, dy: 0in, line(length: {H}in, angle: 90deg, stroke: (paint: blue, thickness: 0.5pt)))",
        f'#place(top + left, dx: {back_x + TEXT_INSET}in, dy: {b + TEXT_INSET}in, rect(width: {text_w}in, height: {th - 2 * TEXT_INSET}in, stroke: (paint: green, thickness: 0.4pt, dash: "dotted")))',
        f'#place(top + left, dx: {front_x + TEXT_INSET}in, dy: {b + TEXT_INSET}in, rect(width: {text_w}in, height: {th - 2 * TEXT_INSET}in, stroke: (paint: green, thickness: 0.4pt, dash: "dotted")))',
        f"#place(top + left, dx: {bx}in, dy: {by}in, rect(width: {bw}in, height: {bh}in, stroke: (paint: orange, thickness: 0.8pt)))",
        f"#place(top + left, dx: {bx + Decimal('0.1')}in, dy: {by + Decimal('0.1')}in, text(size: 7pt, fill: orange)[barcode area])",
        "#place(bottom + left, dx: 0.3in, dy: -0.3in, text(size: 7pt, fill: red)[PROOF WITH GUIDES. NOT FOR UPLOAD. Red: trim. Blue: spine folds. Green: text safe area.])",
    ]
    proof = _compile(source + "\n".join(guides) + "\n", files)
    report.append({"check": "Cover size", "status": "pass",
                   "detail": f"{W} × {H} in: bleed {b} + back {tw} + spine {sp} + front {tw} + bleed {b}; height {b} + {th} + {b}."})  # fmt: skip
    report.append({"check": "Colour", "status": "manual",
                   "detail": "Colours are RGB. KDP asks for CMYK images on print covers and prints colours as they convert; check a printed proof."})  # fmt: skip
    return CoverBuild(pdf=pdf, proof_pdf=proof, spec=spec, report=report, artwork_dpi=dpi)


def _esc(text: str) -> str:
    out = text
    for ch in "\\#[]$*_`<>@~":
        out = out.replace(ch, "\\" + ch)
    return out


def build_ebook(
    cfg: dict[str, Any], trim_w: Decimal, artwork: tuple[bytes, str, int, int] | None
) -> tuple[bytes, list[dict[str, Any]]]:
    """Front cover only, 1600 × 2560 px JPEG (KDP's ideal eBook cover)."""
    from PIL import Image

    bg = _color(cfg.get("background"), "#1f3a5f")
    fg = _color(cfg.get("text_color"), "#ffffff")
    files: dict[str, bytes] = {}
    body = [f"#set page(width: {EBOOK_W_IN}in, height: {EBOOK_H_IN}in, margin: 0pt, fill: {bg})"]
    if artwork:
        data, ext, _w, _h = artwork
        files[f"art.{ext}"] = data
        body.append(
            f'#place(top + left, image("art.{ext}", width: {EBOOK_W_IN}in, height: {EBOOK_H_IN}in, fit: "cover"))'
        )
    scale = float(EBOOK_W_IN / trim_w)
    inset = TEXT_INSET
    for layer in cfg.get("layers") or []:
        if layer.get("role") not in ("title", "subtitle", "author") or not (layer.get("text") or "").strip():
            continue
        top = inset + (EBOOK_H_IN - 2 * inset) * Decimal(str(layer.get("y", 0.2)))
        body.append(_text_box(layer, inset, top, EBOOK_W_IN - 2 * inset, fg, scale))
    pages = _compile("\n".join(body) + "\n", files, fmt="png", ppi=EBOOK_PPI)
    png = pages[0] if isinstance(pages, list) else pages
    img = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    w, h = img.size
    report = [
        {"check": "eBook cover size", "status": "pass" if (w, h) == kdp_rules.EBOOK_COVER_IDEAL else "warn",
         "detail": f"{w} × {h} px JPEG, RGB (KDP ideal {kdp_rules.EBOOK_COVER_IDEAL[0]} × {kdp_rules.EBOOK_COVER_IDEAL[1]}; ratio {h / w:.2f}:1)."},
        {"check": "eBook cover file size", "status": "pass" if out.tell() < kdp_rules.EBOOK_COVER_MAX_MB * 1024 * 1024 else "fail",
         "detail": f"{out.tell() / 1024:.0f} KB (limit {kdp_rules.EBOOK_COVER_MAX_MB} MB)."},
    ]  # fmt: skip
    return out.getvalue(), report
