from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

from copier import run_copy
from copier._types import (
    clear_validators,
    get_all_validators,
    get_validator,
    register_validator,
)


BRACKET_ENVOPS = {
    "autoescape": False,
    "block_end_string": "%]",
    "block_start_string": "[%",
    "comment_end_string": "#]",
    "comment_start_string": "[#",
    "keep_trailing_newline": True,
    "variable_end_string": "]]",
    "variable_start_string": "[[",
}
BRACKET_ENVOPS_JSON = json.dumps(BRACKET_ENVOPS)
SUFFIX_TMPL = ".tmpl"


def build_file_tree(spec, dedent=True, encoding="utf-8"):
    for path, contents in spec.items():
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, Path):
            path.symlink_to(contents)
        else:
            binary = isinstance(contents, bytes)
            if not binary and dedent:
                contents = textwrap.dedent(contents)
            mode = "wb" if binary else "w"
            enc = None if binary else encoding
            with Path(path).open(mode, encoding=enc) as fd:
                fd.write(contents)


@pytest.fixture(autouse=True)
def _reset_validators():
    """Reset validators registry before and after each test."""
    clear_validators()
    yield
    clear_validators()


def test_register_and_get_validator():
    """Test registering and retrieving a custom validator."""

    def my_validator(value: str, question_name: str) -> str:
        if not value:
            return "Value cannot be empty"
        return ""

    register_validator("my_validator", my_validator)

    assert get_validator("my_validator") is my_validator
    assert get_validator("non_existent") is None
    assert "my_validator" in get_all_validators()


def test_url_validator(tmp_path_factory: pytest.TempPathFactory):
    """Test a URL validator."""

    def url_validator(value: str, question_name: str) -> str:
        if not value:
            return "URL cannot be empty"
        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                return f"'{value}' is not a valid URL"
        except Exception:
            return f"'{value}' is not a valid URL"
        return ""

    register_validator("url", url_validator)

    src = tmp_path_factory.mktemp("src_url")
    dst_valid = tmp_path_factory.mktemp("dst_url_valid")
    dst_invalid = tmp_path_factory.mktemp("dst_url_invalid")

    build_file_tree(
        {
            (src / "copier.yml"): yaml.dump(
                {
                    "_envops": BRACKET_ENVOPS,
                    "_templates_suffix": SUFFIX_TMPL,
                    "project_url": {
                        "type": "str",
                        "default": "https://example.com",
                        "validator": "url",
                    },
                }
            ),
            (src / "[[ _copier_conf.answers_file ]].tmpl"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    run_copy(
        str(src),
        str(dst_valid),
        data={"project_url": "https://github.com/copier-org/copier"},
        defaults=True,
        overwrite=True,
        quiet=True,
    )

    with pytest.raises(ValueError, match="Validation error"):
        run_copy(
            str(src),
            str(dst_invalid),
            data={"project_url": "not-a-valid-url"},
            defaults=True,
            overwrite=True,
            quiet=True,
        )


def test_regex_validator(tmp_path_factory: pytest.TempPathFactory):
    """Test a regex validator."""

    def regex_validator_factory(pattern: str, error_msg: str):
        def regex_validator(value: str, question_name: str) -> str:
            if not re.match(pattern, str(value)):
                return error_msg
            return ""

        return regex_validator

    email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    register_validator(
        "email", regex_validator_factory(email_pattern, "Invalid email format")
    )

    src = tmp_path_factory.mktemp("src_regex")
    dst_valid = tmp_path_factory.mktemp("dst_regex_valid")
    dst_invalid = tmp_path_factory.mktemp("dst_regex_invalid")

    build_file_tree(
        {
            (src / "copier.yml"): yaml.dump(
                {
                    "_envops": BRACKET_ENVOPS,
                    "_templates_suffix": SUFFIX_TMPL,
                    "author_email": {
                        "type": "str",
                        "default": "dev@example.com",
                        "validator": "email",
                    },
                }
            ),
            (src / "[[ _copier_conf.answers_file ]].tmpl"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    run_copy(
        str(src),
        str(dst_valid),
        data={"author_email": "test@example.org"},
        defaults=True,
        overwrite=True,
        quiet=True,
    )

    with pytest.raises(ValueError, match="Invalid email format"):
        run_copy(
            str(src),
            str(dst_invalid),
            data={"author_email": "invalid-email"},
            defaults=True,
            overwrite=True,
            quiet=True,
        )


def test_semver_validator(tmp_path_factory: pytest.TempPathFactory):
    """Test a semantic versioning validator."""
    from packaging.version import InvalidVersion, Version

    def semver_validator(value: str, question_name: str) -> str:
        try:
            Version(str(value))
        except InvalidVersion:
            return f"'{value}' is not a valid semantic version"
        return ""

    register_validator("semver", semver_validator)

    src = tmp_path_factory.mktemp("src_semver")
    dst_valid1 = tmp_path_factory.mktemp("dst_semver_valid1")
    dst_valid2 = tmp_path_factory.mktemp("dst_semver_valid2")
    dst_invalid = tmp_path_factory.mktemp("dst_semver_invalid")

    build_file_tree(
        {
            (src / "copier.yml"): yaml.dump(
                {
                    "_envops": BRACKET_ENVOPS,
                    "_templates_suffix": SUFFIX_TMPL,
                    "version": {
                        "type": "str",
                        "default": "1.0.0",
                        "validator": "semver",
                    },
                }
            ),
            (src / "[[ _copier_conf.answers_file ]].tmpl"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    run_copy(
        str(src), str(dst_valid1), data={"version": "2.3.4"}, defaults=True, overwrite=True, quiet=True
    )

    run_copy(
        str(src),
        str(dst_valid2),
        data={"version": "1.0.0-alpha.1"},
        defaults=True,
        overwrite=True,
        quiet=True,
    )

    with pytest.raises(ValueError, match="not a valid semantic version"):
        run_copy(
            str(src),
            str(dst_invalid),
            data={"version": "invalid-version"},
            defaults=True,
            overwrite=True,
            quiet=True,
        )


def test_template_validator_still_works(tmp_path_factory: pytest.TempPathFactory):
    """Ensure that the original template-based validator still works."""
    src = tmp_path_factory.mktemp("src_template")
    dst_valid = tmp_path_factory.mktemp("dst_template_valid")
    dst_invalid = tmp_path_factory.mktemp("dst_template_invalid")

    build_file_tree(
        {
            (src / "copier.yml"): (
                f"""\
                _envops: {BRACKET_ENVOPS_JSON}
                _templates_suffix: {SUFFIX_TMPL}
                age:
                    type: int
                    default: 18
                    validator: |-
                        [% if age < 0 %]
                            Age cannot be negative
                        [% endif %]
                """
            ),
            (src / "[[ _copier_conf.answers_file ]].tmpl"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    run_copy(str(src), str(dst_valid), data={"age": 25}, defaults=True, overwrite=True, quiet=True)

    with pytest.raises(ValueError, match="Age cannot be negative"):
        run_copy(str(src), str(dst_invalid), data={"age": -5}, defaults=True, overwrite=True, quiet=True)


def test_custom_validator_with_int_value(tmp_path_factory: pytest.TempPathFactory):
    """Test custom validator with integer values."""

    def positive_int_validator(value: int, question_name: str) -> str:
        if not isinstance(value, (int, float)) or value <= 0:
            return f"{question_name} must be a positive number"
        return ""

    register_validator("positive_int", positive_int_validator)

    src = tmp_path_factory.mktemp("src_int")
    dst_valid = tmp_path_factory.mktemp("dst_int_valid")
    dst_zero = tmp_path_factory.mktemp("dst_int_zero")
    dst_negative = tmp_path_factory.mktemp("dst_int_negative")

    build_file_tree(
        {
            (src / "copier.yml"): yaml.dump(
                {
                    "_envops": BRACKET_ENVOPS,
                    "_templates_suffix": SUFFIX_TMPL,
                    "count": {
                        "type": "int",
                        "default": 1,
                        "validator": "positive_int",
                    },
                }
            ),
            (src / "[[ _copier_conf.answers_file ]].tmpl"): (
                "[[ _copier_answers|to_nice_yaml ]]"
            ),
        }
    )

    run_copy(str(src), str(dst_valid), data={"count": 10}, defaults=True, overwrite=True, quiet=True)

    with pytest.raises(ValueError, match="must be a positive number"):
        run_copy(str(src), str(dst_zero), data={"count": 0}, defaults=True, overwrite=True, quiet=True)

    with pytest.raises(ValueError, match="must be a positive number"):
        run_copy(str(src), str(dst_negative), data={"count": -1}, defaults=True, overwrite=True, quiet=True)
