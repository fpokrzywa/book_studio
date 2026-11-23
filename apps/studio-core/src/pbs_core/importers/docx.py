"""DOCX import via mammoth (DOCX -> semantic HTML -> bdm/1).

The archive is checked before mammoth opens it: size limits, zip bombs, path traversal,
encryption, and DTD/entity declarations (XXE). Features mammoth cannot convert (equations,
comments, tracked changes, text boxes) are detected and reported instead of silently lost.
"""

from __future__ import annotations

import io
import re

import mammoth

from pbs_core.importers.base import ImportError_, ImportResult
from pbs_core.importers.html_import import import_html
from pbs_core.security.archive import UnsafeArchiveError, open_checked, read_capped, reject_xml_dtd

STYLE_MAP = """
p[style-name='Caption'] => p.pbs-caption:fresh
p[style-name='Code'] => pre:separator('\\n')
p[style-name='Source Code'] => pre:separator('\\n')
p[style-name='HTML Preformatted'] => pre:separator('\\n')
r[style-name='Code Char'] => code
r[style-name='Verbatim Char'] => code
p[style-name='Quote'] => blockquote > p:fresh
p[style-name='Intense Quote'] => blockquote > p:fresh
"""


def import_docx(data: bytes, fallback_title: str) -> ImportResult:
    result = ImportResult("docx", [], lossy=True)
    try:
        zf = open_checked(data)
        names = set(zf.namelist())
        if "word/document.xml" not in names:
            raise ImportError_("This file is not a Word document (word/document.xml is missing).")
        reject_xml_dtd(zf)
        document_xml = read_capped(zf, "word/document.xml").decode("utf-8", errors="replace")
    except UnsafeArchiveError as exc:
        raise ImportError_(f"The document was rejected for safety: {exc}") from exc

    equations = len(re.findall(r"<m:oMath[ >]", document_xml))
    if equations:
        result.warn(
            "docx_equations",
            f"{equations} Word equation(s) could not be converted and are missing from the import. "
            "Re-type them as $LaTeX$ math (Pandoc-based equation import is planned).",
        )
    if "word/comments.xml" in names:
        result.warn("docx_comments", "Word comments were not imported.")
    if re.search(r"<w:(ins|del) ", document_xml):
        result.warn("docx_tracked_changes", "The document contains tracked changes; the import shows them as accepted.")
    if "<w:txbxContent" in document_xml:
        result.warn("docx_text_boxes", "Text boxes may be missing or out of order. Check the import.")

    try:
        converted = mammoth.convert_to_html(io.BytesIO(data), style_map=STYLE_MAP)
    except Exception as exc:
        raise ImportError_("The Word document could not be read. It may be damaged.") from exc
    for message in converted.messages:
        text = str(getattr(message, "message", message))
        if "Unrecognised paragraph style" in text or "Unrecognised run style" in text:
            style = re.search(r"'([^']+)'", text)
            result.warn(
                "docx_style", f"Word style “{style.group(1) if style else '?'}” has no equivalent; kept as plain text."
            )
        else:
            result.warn("docx_message", text[:200])
    import_html(converted.value.encode("utf-8"), fallback_title, importer="docx", result=result)
    return result
