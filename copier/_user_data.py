"""Functions used to load user data.

Note: This module is being refactored into layers:
- Schema layer: _question_schema.py (QuestionSchema)
- Runtime layer: _question_runtime.py (QuestionRuntime)

This module re-exports for backward compatibility.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from functools import cached_property
from hashlib import sha512
from os import urandom
from pathlib import Path
from typing import Any

import yaml
from jinja2.sandbox import SandboxedEnvironment
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from questionary.prompts.common import Choice

from copier._question_runtime import (
    CAST_STR_TO_NATIVE,
    QuestionRuntime,
    parse_yaml_list,
    parse_yaml_string,
)
from copier._question_schema import QuestionSchema
from copier._settings import SettingsModel
from copier._types import (
    MISSING,
    AnyByStrDict,
    AnswersMap,
    LazyDict,
    MissingType,
    StrOrPath,
)
from .errors import MissingFileWarning


def _now() -> datetime:
    warnings.warn(
        "'now' will be removed in a future release of Copier.\n"
        "Please use this instead: {{ '%Y-%m-%d %H:%M:%S' | strftime }}\n"
        "strftime format reference https://strftime.org/",
        FutureWarning,
    )
    return datetime.utcnow()


def _make_secret() -> str:
    warnings.warn(
        "'make_secret' will be removed in a future release of Copier.\n"
        "Please use this instead: {{ 999999999999999999999999999999999|ans_random|hash('sha512') }}\n"
        "random and hash filters documentation: https://docs.ansible.com/ansible/2.3/playbooks_filters.html",
        FutureWarning,
    )
    return sha512(urandom(48)).hexdigest()


from copier._types import DEFAULT_DATA

DEFAULT_DATA["now"] = _now
DEFAULT_DATA["make_secret"] = _make_secret


def load_answersfile_data(
    dst_path: StrOrPath,
    answers_file: StrOrPath = ".copier-answers.yml",
    *,
    warn_on_missing: bool = False,
) -> AnyByStrDict:
    """Load answers data from a `$dst_path/$answers_file` file if it exists."""
    try:
        with Path(dst_path, answers_file).open("rb") as fd:
            return yaml.safe_load(fd)
    except (FileNotFoundError, IsADirectoryError):
        if warn_on_missing:
            warnings.warn(
                f"File not found; returning empty dict: {answers_file}",
                MissingFileWarning,
            )
        return {}


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Question:
    """One question asked to the user.

    This class is a compatibility wrapper that delegates to QuestionRuntime.
    For a clean layered architecture, use QuestionSchema and QuestionRuntime directly.

    Attributes:
        var_name:
            Question name in the answers dict.

        answers:
            A map containing the answers provided by the user.

        context:
            A map containing the full rendering context.

        jinja_env:
            The Jinja environment used to rendering answers.

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
    answers: AnswersMap
    context: dict[str, Any]
    jinja_env: SandboxedEnvironment
    settings: SettingsModel
    choices: list | dict | str = None
    multiselect: bool = False
    default: Any = MISSING
    help: str = ""
    multiline: str | bool = False
    placeholder: str = ""
    qmark: str | None = None
    secret: bool = False
    type: str = ""
    validator: str = ""
    when: str | bool = True

    @cached_property
    def _schema(self) -> QuestionSchema:
        """Get the underlying QuestionSchema."""
        return QuestionSchema(
            var_name=self.var_name,
            choices=self.choices if self.choices is not None else [],
            multiselect=self.multiselect,
            default=self.default,
            help=self.help,
            multiline=self.multiline,
            placeholder=self.placeholder,
            qmark=self.qmark,
            secret=self.secret,
            type=self.type,
            validator=self.validator,
            when=self.when,
        )

    @cached_property
    def _runtime(self) -> QuestionRuntime:
        """Get the underlying QuestionRuntime."""
        return QuestionRuntime(
            schema=self._schema,
            answers=self.answers,
            context=self.context,
            jinja_env=self.jinja_env,
            settings=self.settings,
        )

    def cast_answer(self, answer: Any) -> Any:
        """Cast answer to expected type."""
        return self._runtime.cast_answer(answer)

    def get_default(self) -> Any:
        """Get the default value for this question, casted to its expected type."""
        return self._runtime.get_default()

    def get_default_rendered(self) -> bool | str | Choice | None | MissingType:
        """Get default answer rendered for the questionary lib."""
        return self._runtime.get_default_rendered()

    @cached_property
    def _formatted_choices(self) -> list:
        """Obtain choices rendered and properly formatted."""
        return self._runtime._formatted_choices

    def get_message(self) -> str:
        """Get the message that will be printed to the user."""
        return self._runtime.get_message()

    def get_placeholder(self) -> str:
        """Render and obtain the placeholder."""
        return self._runtime.get_placeholder()

    def get_questionary_structure(self) -> AnyByStrDict:
        """Get the question in a format that the questionary lib understands."""
        return self._runtime.get_questionary_structure()

    def get_type_name(self) -> str:
        """Render the type name and return it."""
        return self._runtime.get_type_name()

    def get_multiline(self) -> bool:
        """Get the value for multiline."""
        return self._runtime.get_multiline()

    def validate_answer(self, answer: Any) -> None:
        """Validate user answer."""
        self._runtime.validate_answer(answer)

    def get_when(self) -> bool:
        """Get skip condition for question."""
        return self._runtime.get_when()

    def render_value(
        self, value: Any, extra_answers: AnyByStrDict | None = None
    ) -> Any:
        """Render a single templated value using Jinja."""
        return self._runtime.render_value(value, extra_answers)

    def parse_answer(self, answer: Any) -> Any:
        """Parse the answer according to the question's type."""
        return self._runtime.parse_answer(answer)

    def _parse_answer(self, answer: Any) -> Any:
        """Parse a single answer according to the question's type."""
        return self._runtime._parse_answer(answer)


__all__ = [
    "AnswersMap",
    "Question",
    "QuestionSchema",
    "QuestionRuntime",
    "parse_yaml_string",
    "parse_yaml_list",
    "load_answersfile_data",
    "CAST_STR_TO_NATIVE",
    "DEFAULT_DATA",
]
