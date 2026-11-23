"""SQLAlchemy models. The Alembic migrations are authoritative; a test checks for drift.

Project isolation: child tables reference parents through composite (project_id, id)
foreign keys, so a row can never point at another project's data.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

PROJECT_TYPES = ("nonfiction", "technical", "course", "workbook", "memoir", "fiction", "serial")
PROJECT_STATUSES = ("active", "archived")
CHAPTER_KINDS = ("part", "chapter", "section", "front_matter", "back_matter")
CHAPTER_STATUSES = ("planned", "draft", "in_review", "approved")
REVISION_ORIGINS = (
    "human",
    "ai_generated",
    "ai_assisted",
    "imported",
    "restored",
    "system_migration",
)
EXPORT_FORMATS = ("markdown", "markdown_zip", "html")
EXPORT_STATUSES = ("completed", "failed")
BACKUP_KINDS = ("manual", "pre_migration", "pre_restore")


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text)
    author_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    project_type: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    audience: Mapped[str | None] = mapped_column(Text)
    target_word_count: Mapped[int | None] = mapped_column(Integer)
    publication_formats: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    is_demo: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duplicated_from_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("project_type", PROJECT_TYPES), name="project_type"),
        CheckConstraint(_in("status", PROJECT_STATUSES), name="status"),
        CheckConstraint("target_word_count IS NULL OR target_word_count >= 0", name="target_words"),
        CheckConstraint("length(title) BETWEEN 1 AND 300", name="title_len"),
        Index("ix_project_status_updated", "status", "updated_at"),
    )


class Chapter(Base):
    __tablename__ = "chapter"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="chapter")
    position: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    locked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    target_word_count: Mapped[int | None] = mapped_column(Integer)
    head_revision_id: Mapped[str | None] = mapped_column(Text)
    head_revision_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    outline_node_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "slug"),
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["chapter.project_id", "chapter.id"],
            name="fk_chapter_parent",
        ),
        ForeignKeyConstraint(
            ["project_id", "head_revision_id"],
            ["chapter_revision.project_id", "chapter_revision.id"],
            name="fk_chapter_head_revision",
            use_alter=True,
        ),
        CheckConstraint(_in("kind", CHAPTER_KINDS), name="kind"),
        CheckConstraint(_in("status", CHAPTER_STATUSES), name="status"),
        CheckConstraint("locked IN (0, 1)", name="locked"),
        Index("ix_chapter_project_position", "project_id", "position"),
    )


class ChapterRevision(Base):
    __tablename__ = "chapter_revision"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    source_md: Mapped[str] = mapped_column(Text, nullable=False)
    bdm_json: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    accepted_proposal_id: Mapped[str | None] = mapped_column(Text)
    restored_from_revision_id: Mapped[str | None] = mapped_column(Text)
    import_run_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("chapter_id", "revision_no"),
        ForeignKeyConstraint(
            ["project_id", "chapter_id"],
            ["chapter.project_id", "chapter.id"],
            name="fk_revision_chapter",
        ),
        CheckConstraint(_in("origin", REVISION_ORIGINS), name="origin"),
        CheckConstraint("revision_no >= 1", name="revision_no"),
        # Added by migration 0004: a proposal can be applied at most once.
        Index(
            "uq_revision_accepted_proposal",
            "accepted_proposal_id",
            unique=True,
            sqlite_where=text("accepted_proposal_id IS NOT NULL"),
        ),
    )


class ActivityEvent(Base):
    __tablename__ = "activity_event"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("project.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_activity_created", "created_at"),
        Index("ix_activity_project_created", "project_id", "created_at"),
    )


class ExportRun(Base):
    __tablename__ = "export_run"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    revision_set_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    output_path: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        CheckConstraint(_in("format", EXPORT_FORMATS), name="format"),
        CheckConstraint(_in("status", EXPORT_STATUSES), name="status"),
    )


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)


class BackupRun(Base):
    """Backup bookkeeping (manifest/1). Added by migration 0002; ZIP writer lands in Phase 02."""

    __tablename__ = "backup_run"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("project.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(Text)
    schema_revision: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(_in("kind", BACKUP_KINDS), name="kind"),)


class PurgeContext(Base):
    """Rows here temporarily lift immutability triggers for one project (explicit purge only)."""

    __tablename__ = "_purge_ctx"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)


IMPORT_STATUSES = ("preview_ready", "committed", "failed", "cancelled")
IMPORT_FORMATS = ("markdown", "text", "html", "docx", "pdf")


class OriginalFile(Base):
    """An uploaded file, stored byte-for-byte and content-addressed. Immutable (DB trigger)."""

    __tablename__ = "original_file"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    detected_format: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[str] = mapped_column(Text, nullable=False)


class ImportRun(Base):
    __tablename__ = "import_run"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    original_file_id: Mapped[str] = mapped_column(Text, ForeignKey("original_file.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("project.id"))
    target_project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("project.id"))
    importer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lossy: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("status", IMPORT_STATUSES), name="status"),
        CheckConstraint(_in("importer", IMPORT_FORMATS), name="importer"),
    )


class Asset(Base):
    """Image or media file owned by a project; referenced from text as ``asset:<short_hash>``."""

    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    short_hash: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    original_name: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    import_run_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "sha256"),
        UniqueConstraint("project_id", "short_hash"),
    )


class ChapterDraft(Base):
    """Autosaved working copy (mutable). Saving turns it into an immutable revision."""

    __tablename__ = "chapter_draft"

    chapter_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    base_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_md: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "chapter_id"],
            ["chapter.project_id", "chapter.id"],
            name="fk_draft_chapter",
        ),
    )


class RevisionTag(Base):
    """Label and note added to a revision after it was saved (the revision itself never changes)."""

    __tablename__ = "revision_tag"

    revision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "revision_id"],
            ["chapter_revision.project_id", "chapter_revision.id"],
            name="fk_tag_revision",
        ),
    )


# Phase 03 and 04 tables live in their own modules but share this metadata.
from pbs_core.storage import ai_models, knowledge_models, planning_models  # noqa: E402, F401
