from __future__ import annotations

import re
from pathlib import Path

import pytest

import copier
from copier._cli import CopierApp

from .helpers import build_file_tree


def test_preview_mode_does_not_write_files(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: test
                """
            ),
            (src / "{{ name }}.txt"): "Hello {{ name }}!",
            (src / "subdir" / "file.txt"): "static file",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)

    assert not (dst / "test.txt").exists()
    assert not (dst / "subdir").exists()
    assert worker.preview is True
    assert len(worker._preview_tree) > 0


def test_preview_mode_collects_correct_paths(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: myproject
                """
            ),
            (src / "{{ name }}.txt"): "Content",
            (src / "static.txt"): "Static",
            (src / "folder" / "nested.txt"): "Nested",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)

    preview_paths = {str(p) for p in worker._preview_tree}
    assert "myproject.txt" in preview_paths
    assert "static.txt" in preview_paths
    assert "folder/nested.txt" in preview_paths or "folder\\nested.txt" in preview_paths


def test_preview_mode_respects_exclude_patterns(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                _exclude:
                    - "*.log"
                    - "ignored/"
                name:
                    type: str
                    default: test
                """
            ),
            (src / "keep.txt"): "keep",
            (src / "ignored.log"): "ignore",
            (src / "ignored" / "file.txt"): "ignore",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)

    preview_paths = {str(p) for p in worker._preview_tree}
    assert "keep.txt" in preview_paths
    assert "ignored.log" not in preview_paths
    assert not any("ignored" in p for p in preview_paths if "/" in p or "\\" in p)


def test_preview_mode_formats_tree(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: proj
                """
            ),
            (src / "a.txt"): "a",
            (src / "b.txt"): "b",
            (src / "dir" / "c.txt"): "c",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)
    tree_output = worker._format_tree()

    assert tree_output
    assert "a.txt" in tree_output
    assert "b.txt" in tree_output
    assert "c.txt" in tree_output
    assert "dir" in tree_output
    assert dst.name in tree_output or "." in tree_output


def test_preview_mode_with_templated_paths(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                module_name:
                    type: str
                    default: mymodule
                """
            ),
            (src / "{{ module_name }}" / "__init__.py"): "from .main import *",
            (src / "{{ module_name }}" / "main.py"): "print('hello')",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)

    preview_paths = {str(p) for p in worker._preview_tree}
    assert any("mymodule" in p for p in preview_paths)
    assert not (dst / "mymodule").exists()


def test_preview_mode_cli(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: test
                """
            ),
            (src / "file.txt"): "content",
        }
    )

    run_result = CopierApp.run(
        [
            "copier",
            "copy",
            "--preview",
            "--defaults",
            "--quiet",
            str(src),
            str(dst),
        ],
        exit=False,
    )

    assert run_result[1] == 0
    assert not (dst / "file.txt").exists()


def test_preview_mode_output(
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: test
                """
            ),
            (src / "output.txt"): "content",
        }
    )

    copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=False)
    _, err = capsys.readouterr()

    assert re.search(r"Previewing template version", err)
    assert re.search(r"Preview of generated directory tree", err)
    assert re.search(r"output\.txt", err)
    assert re.search(r"This is a preview - no files were written to disk", err)


def test_preview_mode_without_quiet_outputs_tree(
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: proj
                """
            ),
            (src / "file1.txt"): "1",
            (src / "sub" / "file2.txt"): "2",
        }
    )

    copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=False)
    _, err = capsys.readouterr()

    assert "file1.txt" in err
    assert "file2.txt" in err
    assert "sub" in err


def test_preview_mode_quiet_suppresses_output(
    capsys: pytest.CaptureFixture[str],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: test
                """
            ),
            (src / "file.txt"): "content",
        }
    )

    copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)
    out, err = capsys.readouterr()

    assert out == ""
    assert err == ""


def test_preview_mode_does_not_execute_tasks(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                _tasks:
                    - echo "task executed"
                name:
                    type: str
                    default: test
                """
            ),
            (src / "file.txt"): "content",
        }
    )

    worker = copier.run_copy(str(src), dst, defaults=True, preview=True, quiet=True)

    assert not (dst / "file.txt").exists()
    assert worker.preview is True


def test_normal_copy_still_works(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    build_file_tree(
        {
            (src / "copier.yml"): (
                """\
                name:
                    type: str
                    default: myproject
                """
            ),
            (src / "{{ name }}.txt"): "Hello {{ name }}!",
        }
    )

    copier.run_copy(str(src), dst, defaults=True, quiet=True)

    assert (dst / "myproject.txt").exists()
    assert (dst / "myproject.txt").read_text() == "Hello myproject!"
