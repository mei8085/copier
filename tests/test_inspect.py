from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from copier import run_inspect
from copier._cli import CopierApp

from .helpers import build_file_tree


def test_inspect_dot_format(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                owner1:
                    type: str
                has_2_owners:
                    type: bool
                    default: false
                owner2:
                    type: str
                    default: "{{ owner1 }}"
                    when: "{{ has_2_owners }}"
                """
            ),
        }
    )

    result = run_inspect(str(src), format="dot")

    assert "digraph question_dependencies {" in result
    assert '"owner1"' in result
    assert '"has_2_owners"' in result
    assert '"owner2"' in result
    assert 'label="when"' in result
    assert 'label="default"' in result
    assert '"has_2_owners" -> "owner2"' in result
    assert '"owner1" -> "owner2"' in result


def test_inspect_mermaid_format(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                owner1:
                    type: str
                has_2_owners:
                    type: bool
                    default: false
                owner2:
                    type: str
                    default: "{{ owner1 }}"
                    when: "{{ has_2_owners }}"
                """
            ),
        }
    )

    result = run_inspect(str(src), format="mermaid")

    assert "flowchart TD" in result
    assert "owner1" in result
    assert "has_2_owners" in result
    assert "owner2" in result
    assert "-- when -->" in result
    assert "-. default .->" in result


def test_inspect_no_dependencies(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                q1:
                    type: str
                q2:
                    type: int
                    default: 42
                """
            ),
        }
    )

    result = run_inspect(str(src), format="dot")

    assert "digraph question_dependencies {" in result
    assert '"q1"' in result
    assert '"q2"' in result
    assert "->" not in result


def test_inspect_only_when_dependency(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                show_details:
                    type: bool
                    default: false
                details:
                    type: str
                    when: "{{ show_details }}"
                """
            ),
        }
    )

    result = run_inspect(str(src), format="dot")

    assert "digraph question_dependencies {" in result
    assert 'label="when"' in result
    assert 'label="default"' not in result
    assert '"show_details" -> "details"' in result


def test_inspect_only_default_dependency(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                project_name:
                    type: str
                package_name:
                    type: str
                    default: "{{ project_name | replace('-', '_') }}"
                """
            ),
        }
    )

    result = run_inspect(str(src), format="dot")

    assert "digraph question_dependencies {" in result
    assert 'label="when"' not in result
    assert 'label="default"' in result
    assert '"project_name" -> "package_name"' in result


def test_inspect_cli_dot(tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                q1:
                    type: str
                q2:
                    type: str
                    when: "{{ q1 }}"
                """
            ),
        }
    )

    run_result = CopierApp.run(
        ["copier", "inspect", str(src)],
        exit=False,
    )
    assert run_result[1] == 0

    captured = capsys.readouterr()
    assert "digraph question_dependencies {" in captured.out
    assert '"q1"' in captured.out
    assert '"q2"' in captured.out


def test_inspect_cli_mermaid(tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                q1:
                    type: str
                q2:
                    type: str
                    when: "{{ q1 }}"
                """
            ),
        }
    )

    run_result = CopierApp.run(
        ["copier", "inspect", "--format", "mermaid", str(src)],
        exit=False,
    )
    assert run_result[1] == 0

    captured = capsys.readouterr()
    assert "flowchart TD" in captured.out


def test_inspect_help(capsys: pytest.CaptureFixture[str]) -> None:
    run_result = CopierApp.run(
        ["copier", "inspect", "--help"],
        exit=False,
    )
    assert run_result[1] == 0
    captured = capsys.readouterr()
    assert "inspect" in captured.out
    assert "--format" in captured.out or "-f" in captured.out


def test_inspect_bracket_envops(tmp_path_factory: pytest.TempPathFactory) -> None:
    src = tmp_path_factory.mktemp("src")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _envops:
                    variable_start_string: "[["
                    variable_end_string: "]]"
                a:
                    type: str
                b:
                    type: str
                    default: "[[ a ]]"
                    when: "[[ a ]]"
                """
            ),
        }
    )

    result = run_inspect(str(src), format="dot")

    assert '"a" -> "b"' in result
    assert 'label="when"' in result
    assert 'label="default"' in result
