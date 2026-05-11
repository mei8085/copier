"""Question schema parsing and validation.

This module contains the schema layer for questions, responsible for:
- Parsing raw question configuration from YAML
- Validating question structure
- Providing type-safe schema objects

This layer is decoupled from runtime execution and user interaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import field
from typing import Any

from pydantic import ConfigDict, Field, field_validator
from pydantic.dataclasses import dataclass
from pydantic_core.core_schema import ValidationInfo

from ._types import MISSING, MissingType


DEFAULT_DATA_KEYS = {"now", "make_secret"}


def _get_default_type_name(default_value: Any) -> str:
    """Determine type name from default value."""
    default_type_name = type(default_value).__name__
    return (
        default_type_name
        if default_type_name
        in {"bool", "float", "int", "json", "str", "yaml", "path"}
        else "yaml"
    )


@dataclass(config=ConfigDict(arbitrary_types_allowed=True, frozen=True))
class QuestionSchema:
    """Schema definition for a question.

    This class represents the parsed and validated schema of a question,
    without any runtime execution context. It is decoupled from:
    - Answers provided by the user
    - Jinja rendering context
    - User interaction (TUI/CLI)

    Attributes:
        var_name:
            Question name in the answers dict.

        choices:
            Selections available for the user if the question requires them.
            Can be templated.

        multiselect:
            Indicates if the question supports multiple answers.
            Only supported by choices type.

        default:
            Default value presented to the user to make it easier to respond.
            Can be templated.

        help:
            Additional text printed to the user, explaining the purpose of
            this question. Can be templated.

        multiline:
            Indicates if the question should allow multiline input. Defaults
            to `True` for JSON and YAML questions, and to `False` otherwise.
            Only meaningful for str-based questions. Can be templated.

        placeholder:
            Text that appears if there's nothing written in the input field,
            but disappears as soon as the user writes anything. Can be templated.

        qmark:
            Custom emoji or mark to display before the question. If not specified,
            defaults to 🎤 for regular questions and 🕵️ for secret questions.

        secret:
            Indicates if the question should be removed from the answers file.
            If the question type is str, it will hide user input on the screen
            by displaying asterisks: `****`.

        type:
            The type of question. Affects the rendering, validation and filtering.
            Can be templated.

        validator:
            Jinja template with which to validate the user input. This template
            will be rendered with the combined answers as variables; it should
            render *nothing* if the value is valid, and an error message to show
            to the user otherwise.

        when:
            Condition that, if `False`, skips the question. Can be templated.
            If it is a boolean, it is used directly. If it is a str, it is
            converted to boolean using a parser similar to YAML, but only for
            boolean values.
    """

    var_name: str
    choices: Sequence[Any] | dict[Any, Any] | str = field(default_factory=list)
    multiselect: bool = False
    default: Any = MISSING
    help: str = ""
    multiline: str | bool = False
    placeholder: str = ""
    qmark: str | None = None
    secret: bool = False
    type: str = Field(default="", validate_default=True)
    validator: str = ""
    when: str | bool = True

    @field_validator("var_name")
    @classmethod
    def _check_var_name(cls, v: str) -> str:
        if v in DEFAULT_DATA_KEYS:
            raise ValueError("Invalid question name")
        return v

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str, info: ValidationInfo) -> str:
        if v == "":
            v = _get_default_type_name(info.data.get("default"))
        return v

    @field_validator("secret")
    @classmethod
    def _check_secret_question_default_value(
        cls, v: bool, info: ValidationInfo
    ) -> bool:
        if v and info.data["default"] is MISSING:
            raise ValueError("Secret question requires a default value")
        return v

    @classmethod
    def from_raw(
        cls, var_name: str, raw: Mapping[str, Any] | Any
    ) -> "QuestionSchema":
        """Create a QuestionSchema from raw configuration data.

        Args:
            var_name: The variable name for the question.
            raw: Raw configuration. Can be a dict with question properties,
                 or a single value (used as the default).

        Returns:
            A validated QuestionSchema instance.
        """
        if isinstance(raw, dict):
            return cls(var_name=var_name, **raw)
        return cls(var_name=var_name, default=raw)
