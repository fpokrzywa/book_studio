"""Create clearly-labelled demo projects. Runs ONLY when invoked explicitly:

    uv run python -m pbs_core.tools.seed_demo

Demo projects are flagged `is_demo` and shown with a "Demo" badge in the library.
"""

from __future__ import annotations

from pbs_core.config import Settings
from pbs_core.context import build_context
from pbs_core.contracts import ChapterCreate, ChapterSaveIn, ProjectCreate
from pbs_core.services import chapters, projects

DEMOS = [
    (
        ProjectCreate(
            title="Demo: Field Notes on Small Engines",
            subtitle="A sample technical manual",
            author_name="Demo Author",
            project_type="technical",
            language="en",
            audience="Hobbyist mechanics",
            target_word_count=40000,
            publication_formats=["ebook", "paperback"],
        ),
        [("Getting Started", "This is demo text.\n\n## Tools you need\n\n- A socket set\n- Patience\n")],
    ),
    (
        ProjectCreate(
            title="Demo: The Lantern Keeper",
            project_type="fiction",
            language="en-GB",
            audience="Adult readers of quiet mysteries",
            target_word_count=80000,
            publication_formats=["ebook"],
        ),
        [("One", "The lamp guttered twice before the knock came.\n")],
    ),
]


def main() -> None:
    ctx = build_context(Settings())
    try:
        for data, chapter_list in DEMOS:
            project = projects.create_project(ctx, data, is_demo=True)
            for title, text in chapter_list:
                ch = chapters.create_chapter(ctx, project.id, ChapterCreate(title=title))
                chapters.save_content(ctx, project.id, ch.id, ChapterSaveIn(source_md=text, expected_head_no=0))
            print(f"created demo project {project.title} ({project.id})")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
