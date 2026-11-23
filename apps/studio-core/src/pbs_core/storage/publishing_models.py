"""Phase 07 tables: the publishing profile and every built publication (exports, covers, packages).

A publication row records exactly what was built: the file, its hash, the template and trim, the
KDP rule-set version, the interior page count a cover was sized for, and the full preflight and
fidelity report. Files live in the project's workspace folder; nothing is uploaded anywhere.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

TEMPLATE_KEYS = ("technical_manual", "nonfiction", "novel", "workbook")
PUBLICATION_KINDS = ("markdown", "html", "epub", "docx", "pdf", "cover_print", "cover_proof", "cover_ebook", "package")
PUBLICATION_STATUSES = ("succeeded", "failed")


class PublishingProfile(Base):
    __tablename__ = "publishing_profile"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), primary_key=True)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    trim: Mapped[str] = mapped_column(Text, nullable=False)
    ink_paper: Mapped[str] = mapped_column(Text, nullable=False)
    matter_json: Mapped[str] = mapped_column(Text, nullable=False)
    copyright_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    cover_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    index_terms_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(_in("template", TEMPLATE_KEYS), name="template"),)


class Publication(Base):
    __tablename__ = "publication"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    package_id: Mapped[str | None] = mapped_column(Text)  # set when built as part of a package
    file_name: Mapped[str | None] = mapped_column(Text)
    output_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    trim: Mapped[str] = mapped_column(Text, nullable=False)
    ink_paper: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset: Mapped[str] = mapped_column(Text, nullable=False)
    revision_set_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    report_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", PUBLICATION_KINDS), name="kind"),
        CheckConstraint(_in("status", PUBLICATION_STATUSES), name="status"),
        Index("ix_publication_project", "project_id", "kind", "created_at"),
    )
