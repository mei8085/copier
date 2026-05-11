"""Tests for multi-profile answers file support."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

import copier
from copier._user_data import load_answersfile_data, save_answersfile_data

from .helpers import build_file_tree


def test_load_answersfile_data_old_format(tmp_path: Path) -> None:
    """Test loading answers from old format (backwards compatible)."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _commit: v1.0
            _src_path: https://example.com/template
            name: test
            env: dev
            """
        )
    )

    data = load_answersfile_data(tmp_path, ".copier-answers.yml")
    assert data["_commit"] == "v1.0"
    assert data["name"] == "test"
    assert data["env"] == "dev"


def test_load_answersfile_data_new_format(tmp_path: Path) -> None:
    """Test loading answers from new multi-profile format."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _default: dev
            _profiles:
              dev:
                _commit: v1.0
                _src_path: https://example.com/template
                name: test-dev
                env: dev
              prod:
                _commit: v1.0
                _src_path: https://example.com/template
                name: test-prod
                env: prod
            """
        )
    )

    data = load_answersfile_data(tmp_path, ".copier-answers.yml", profile="dev")
    assert data["_commit"] == "v1.0"
    assert data["name"] == "test-dev"
    assert data["env"] == "dev"

    data = load_answersfile_data(tmp_path, ".copier-answers.yml", profile="prod")
    assert data["name"] == "test-prod"
    assert data["env"] == "prod"


def test_load_answersfile_data_default_profile(tmp_path: Path) -> None:
    """Test loading default profile when not specified."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _default: prod
            _profiles:
              dev:
                name: test-dev
              prod:
                name: test-prod
            """
        )
    )

    data = load_answersfile_data(tmp_path, ".copier-answers.yml")
    assert data["name"] == "test-prod"


def test_save_answersfile_data_new_profile(tmp_path: Path) -> None:
    """Test saving answers to a new profile."""
    answers = {
        "_commit": "v1.0",
        "_src_path": "https://example.com/template",
        "name": "test-dev",
    }

    result = save_answersfile_data(tmp_path, ".copier-answers.yml", answers, profile="dev")

    assert "_profiles" in result
    assert result["_default"] == "dev"
    assert result["_profiles"]["dev"]["name"] == "test-dev"


def test_save_answersfile_data_multiple_profiles(tmp_path: Path) -> None:
    """Test saving multiple profiles to the same file."""
    dev_answers = {
        "_commit": "v1.0",
        "_src_path": "https://example.com/template",
        "name": "test-dev",
    }
    save_answersfile_data(
        tmp_path, ".copier-answers.yml", dev_answers, profile="dev", write=True
    )

    prod_answers = {
        "_commit": "v1.0",
        "_src_path": "https://example.com/template",
        "name": "test-prod",
    }
    result = save_answersfile_data(
        tmp_path, ".copier-answers.yml", prod_answers, profile="prod"
    )

    assert "_profiles" in result
    assert result["_profiles"]["dev"]["name"] == "test-dev"
    assert result["_profiles"]["prod"]["name"] == "test-prod"


def test_save_answersfile_data_update_existing_profile(tmp_path: Path) -> None:
    """Test updating an existing profile."""
    initial_answers = {
        "_commit": "v1.0",
        "name": "test-v1",
    }
    save_answersfile_data(
        tmp_path, ".copier-answers.yml", initial_answers, profile="dev", write=True
    )

    updated_answers = {
        "_commit": "v2.0",
        "name": "test-v2",
    }
    result = save_answersfile_data(
        tmp_path, ".copier-answers.yml", updated_answers, profile="dev"
    )

    assert result["_profiles"]["dev"]["_commit"] == "v2.0"
    assert result["_profiles"]["dev"]["name"] == "test-v2"


def test_save_answersfile_data_upgrade_from_old_format(tmp_path: Path) -> None:
    """Test upgrading from old format to new format when using profile."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _commit: v1.0
            _src_path: https://example.com/template
            name: old-format
            """
        )
    )

    new_answers = {
        "_commit": "v2.0",
        "_src_path": "https://example.com/template",
        "name": "new-format",
    }
    result = save_answersfile_data(
        tmp_path, ".copier-answers.yml", new_answers, profile="dev"
    )

    assert "_profiles" in result
    assert result["_default"] == "dev"
    assert result["_profiles"]["default"]["name"] == "old-format"
    assert result["_profiles"]["dev"]["name"] == "new-format"


def test_run_copy_with_profile(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Test running copier with profile parameter."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                environment:
                  type: str
                  default: dev
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
            (src / "config.txt.jinja"): (
                "Name: [[ name ]]\nEnvironment: [[ environment ]]\n"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject", "environment": "dev"},
        defaults=True,
        overwrite=True,
        profile="dev",
    )

    answers_file = dst / ".copier-answers.yml"
    assert answers_file.exists()

    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" in data
    assert data["_default"] == "dev"
    assert data["_profiles"]["dev"]["name"] == "myproject"
    assert data["_profiles"]["dev"]["environment"] == "dev"


def test_run_copy_multiple_profiles(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Test running copier with multiple profiles."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                environment:
                  type: str
                  default: dev
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject-dev", "environment": "dev"},
        defaults=True,
        overwrite=True,
        profile="dev",
    )

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject-prod", "environment": "prod"},
        defaults=True,
        overwrite=True,
        profile="prod",
    )

    answers_file = dst / ".copier-answers.yml"
    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" in data
    assert data["_profiles"]["dev"]["name"] == "myproject-dev"
    assert data["_profiles"]["prod"]["name"] == "myproject-prod"


def test_run_copy_backwards_compatible(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Test that running copier without profile maintains backwards compatibility."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject"},
        defaults=True,
        overwrite=True,
    )

    answers_file = dst / ".copier-answers.yml"
    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" not in data
    assert data["name"] == "myproject"


def test_run_copy_update_default_profile_without_specifying(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Test updating the default profile when not specifying profile."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                version:
                  type: str
                  default: "1.0"
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject", "version": "1.0"},
        defaults=True,
        overwrite=True,
        profile="dev",
    )

    copier.run_copy(
        str(src),
        dst,
        {"name": "myproject", "version": "2.0"},
        defaults=True,
        overwrite=True,
    )

    answers_file = dst / ".copier-answers.yml"
    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" in data
    assert data["_default"] == "dev"
    assert data["_profiles"]["dev"]["version"] == "2.0"


def test_run_copy_upgrade_from_old_format_to_multi_profile(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Test that using profile upgrades from old format to multi-profile format."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "old-project"},
        defaults=True,
        overwrite=True,
    )

    answers_file = dst / ".copier-answers.yml"
    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)
    assert "_profiles" not in data
    assert data["name"] == "old-project"

    copier.run_copy(
        str(src),
        dst,
        {"name": "new-project"},
        defaults=True,
        overwrite=True,
        profile="dev",
    )

    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" in data
    assert data["_default"] == "dev"
    assert data["_profiles"]["default"]["name"] == "old-project"
    assert data["_profiles"]["dev"]["name"] == "new-project"


def test_run_copy_three_profiles(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Test running copier with three different profiles."""
    src = tmp_path_factory.mktemp("template")
    build_file_tree(
        {
            (src / "copier.yml"): dedent(
                """\
                _answers_file: .copier-answers.yml
                name:
                  type: str
                  default: myproject
                environment:
                  type: str
                  default: dev
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].jinja"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    dst = tmp_path_factory.mktemp("dst")

    copier.run_copy(
        str(src),
        dst,
        {"name": "dev-project", "environment": "dev"},
        defaults=True,
        overwrite=True,
        profile="dev",
    )

    copier.run_copy(
        str(src),
        dst,
        {"name": "staging-project", "environment": "staging"},
        defaults=True,
        overwrite=True,
        profile="staging",
    )

    copier.run_copy(
        str(src),
        dst,
        {"name": "prod-project", "environment": "prod"},
        defaults=True,
        overwrite=True,
        profile="prod",
    )

    answers_file = dst / ".copier-answers.yml"
    with answers_file.open("rb") as f:
        data = yaml.safe_load(f)

    assert "_profiles" in data
    assert data["_default"] == "dev"
    assert data["_profiles"]["dev"]["name"] == "dev-project"
    assert data["_profiles"]["staging"]["name"] == "staging-project"
    assert data["_profiles"]["prod"]["name"] == "prod-project"


def test_load_answersfile_data_uses_default_profile(tmp_path: Path) -> None:
    """Test that load_answersfile_data uses _default when no profile specified."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _default: prod
            _profiles:
              dev:
                name: dev-name
                env: dev
              staging:
                name: staging-name
                env: staging
              prod:
                name: prod-name
                env: prod
            """
        )
    )

    data = load_answersfile_data(tmp_path, ".copier-answers.yml")
    assert data["name"] == "prod-name"
    assert data["env"] == "prod"


def test_save_answersfile_data_preserves_all_profiles(tmp_path: Path) -> None:
    """Test that saving to one profile preserves other profiles."""
    answers_file = tmp_path / ".copier-answers.yml"
    answers_file.write_text(
        dedent(
            """\
            _default: dev
            _profiles:
              dev:
                name: dev-name
                version: "1.0"
              prod:
                name: prod-name
                version: "1.0"
            """
        )
    )

    updated_dev_answers = {
        "name": "dev-name-updated",
        "version": "2.0",
    }
    result = save_answersfile_data(
        tmp_path, ".copier-answers.yml", updated_dev_answers, profile="dev"
    )

    assert result["_profiles"]["dev"]["name"] == "dev-name-updated"
    assert result["_profiles"]["dev"]["version"] == "2.0"
    assert result["_profiles"]["prod"]["name"] == "prod-name"
    assert result["_profiles"]["prod"]["version"] == "1.0"
