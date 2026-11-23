"""Write a representative test manuscript (DOCX) to stdout. Synthetic text, made for validation.

Run it with the studio image, which has python-docx and Pillow:
    docker compose ... run --rm --no-deps -T app python - < deploy/validation/make_manuscript.py > book.docx

Three chapters (Heading 1), a section heading, bold and italic text, a bulleted list, a numbered
list, a table and an embedded PNG figure with a caption: the structures an existing book brings.
"""

from __future__ import annotations

import io
import sys

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw


def figure() -> bytes:
    img = Image.new("RGB", (480, 240), (238, 241, 239))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 60, 200, 200), outline=(46, 94, 78), width=6)
    d.ellipse((260, 60, 400, 200), outline=(111, 84, 24), width=6)
    d.line((200, 130, 260, 130), fill=(29, 42, 51), width=4)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def main() -> None:
    doc = Document()
    doc.core_properties.title = "The Lighthouse Ledger"
    doc.core_properties.author = "Validation Author"

    doc.add_heading("The Arrival", level=1)
    doc.add_paragraph(
        "Mara reached the lighthouse in the last hour of daylight. The keeper's ledger lay open on the "
        "table, its pages swollen by forty winters of sea air."
    )
    p = doc.add_paragraph("She read the first entry aloud: ")
    p.add_run("“Fog at dawn, lamp lit at four.”").italic = True
    p.add_run(" The words were ")
    p.add_run("exactly").bold = True
    p.add_run(" what her grandmother had written.")
    doc.add_heading("What the ledger kept", level=2)
    for item in ("Weather at dawn and dusk", "Ships sighted, with their flags", "Oil used for the lamp"):
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("The Inventory", level=1)
    doc.add_paragraph("Mara counted what the station still held and wrote it down in a table of her own.")
    table = doc.add_table(rows=4, cols=3)
    table.style = "Table Grid"
    for r, row in enumerate([("Item", "Count", "Condition"), ("Lamp wicks", "12", "dry"),
                             ("Oil barrels", "3", "half full"), ("Logbooks", "41", "readable")]):  # fmt: skip
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.add_paragraph("Then she followed the steps the keeper had numbered on the wall:")
    for step in ("Trim the wick.", "Clean the lens.", "Light the lamp at dusk."):
        doc.add_paragraph(step, style="List Number")

    doc.add_heading("The Light", level=1)
    doc.add_paragraph("The lens and the lamp, as the keeper sketched them on the inside cover:")
    doc.add_picture(io.BytesIO(figure()), width=Inches(4))
    doc.add_paragraph("Figure 1. The keeper's sketch of the lens and the lamp.", style="Caption")
    doc.add_paragraph(
        "When the beam finally swept the water, Mara wrote her first entry beneath her grandmother's last: "
        "lamp lit at four, sea calm, one ship to the north."
    )

    buf = io.BytesIO()
    doc.save(buf)
    sys.stdout.buffer.write(buf.getvalue())


if __name__ == "__main__":
    main()
