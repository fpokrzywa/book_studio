"""Local capability report: optional external tools, detected by PATH lookup only.

No subprocesses are executed and no network is touched (Phase 01). Version probing
arrives with the features that need each tool.
"""

from __future__ import annotations

import importlib.util
import shutil

from pbs_core.contracts import CapabilityOut

_TOOLS = [
    ("pandoc", "Pandoc", "High-fidelity DOCX import/export", "02 / 07"),
    ("java", "Java runtime", "Runs EPUBCheck (optional EPUB validator)", "07"),
    ("epubcheck", "EPUBCheck", "Optional EPUB validation", "07"),
    ("ollama", "Ollama", "Local AI models (optional)", "03"),
    ("ebook-convert", "Calibre ebook-convert", "Optional MOBI/AZW3 external conversion", "07"),
    ("typst", "Typst CLI", "Fallback print-PDF engine", "07"),
]


def report() -> list[CapabilityOut]:
    out: list[CapabilityOut] = []
    for exe, label, purpose, phase in _TOOLS:
        path = shutil.which(exe)
        out.append(
            CapabilityOut(
                id=exe,
                label=label,
                purpose=purpose,
                needed_from_phase=phase,
                found=path is not None,
                detail=path or "Not found on PATH",
            )
        )
    has_weasy = importlib.util.find_spec("weasyprint") is not None
    out.append(
        CapabilityOut(
            id="weasyprint",
            label="WeasyPrint",
            purpose="Print-layout PDF engine",
            needed_from_phase="07",
            found=has_weasy,
            detail="Python package importable" if has_weasy else "Python package not installed",
        )
    )
    return out
