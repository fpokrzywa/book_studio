from pathlib import Path

import pytest

from pbs_core.storage.paths import (
    UnsafePathError,
    Workspace,
    atomic_write_bytes,
    safe_join,
    sanitize_filename,
    slugify,
)


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../x",
        "a/../../x",
        r"..\x",
        r"C:\x",
        "c:x",
        r"\\server\share",
        "//server/share",
        "/etc/passwd",
        "a:b",
        "file.txt:stream",
        "CON",
        "nul.txt",
        "com1",
        "LPT9.md",
        "x. ",
        "trailing.",
        "",
        "a\x00b",
    ],
)
def test_safe_join_rejects(tmp_path: Path, bad: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, bad)


def test_safe_join_accepts_nested(tmp_path: Path) -> None:
    assert safe_join(tmp_path, "exports/abc/book.md") == tmp_path.resolve() / "exports" / "abc" / "book.md"


def test_safe_join_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / "base"
    base.mkdir()
    link = base / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted for this user on this OS")
    with pytest.raises(UnsafePathError):
        safe_join(base, "link/secret.txt")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Quiet Engine", "The Quiet Engine"),
        ('a<b>c:d"e/f\\g|h?i*j', "a-b-c-d-e-f-g-h-i-j"),
        ("  ..hidden.. ", "hidden"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("", "untitled"),
        ("\x00\x01", "untitled"),
        ("Cafe\u0301", "Caf\u00e9"),  # NFC normalisation
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates() -> None:
    assert len(sanitize_filename("x" * 500)) == 120


def test_slugify() -> None:
    assert slugify("Chapter One: The Start!") == "chapter-one-the-start"
    assert slugify("\u00dcn\u00efc\u00f6d\u00e9 \u00c4rger") == "unicode-arger"
    assert slugify("???") == "section"


def test_atomic_write(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b.txt"
    atomic_write_bytes(target, b"one")
    atomic_write_bytes(target, b"two")
    assert target.read_bytes() == b"two"
    assert [p.name for p in target.parent.iterdir()] == ["b.txt"]


def test_workspace_project_dir_requires_ulid(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    with pytest.raises(UnsafePathError):
        ws.project_dir("../../evil")
