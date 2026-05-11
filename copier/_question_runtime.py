"""Question runtime execution.

This module contains the runtime layer for questions, responsible for:
- Conditional logic evaluation (when)
- Default value calculation
- Type casting and validation
- Template rendering

This layer is decoupled from user interaction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from functools import cached_property
from typing import Any

import yaml
from jinja2 import StrictUndefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from questionary.prompts.common import Choice

from copier._jinja_ext import UnsetError
from copier._question_schema import QuestionSchema
from copier._settings import SettingsModel

from ._tools import cast_to_bool, cast_to_str, force_str_end
from ._types import MISSING, AnyByStrDict, AnswersMap, MissingType
from .errors import InvalidTypeError, UserMessageError


def parse_yaml_string(string: str) -> Any:
    """Parse a YAML string and raise a ValueError if parsing failed.

    This method is needed because :meth:`prompt` requires a ``ValueError``
    to repeat failed questions.
    """
    try:
        return yaml.safe_load(string)
    except yaml.error.YAMLError as error:
        raise ValueError(str(error))


def parse_yaml_list(string: str) -> list[str]:
    """Shallowly parse a YAML string that contains a list of items.

    All items remain raw strings, only the outermost list is parsed.

    Args:
        string: The YAML string.

    Returns:
        The parsed list of raw items.

    Raises:
        ValueError: If the YAML string is not a list.
    """
    node = yaml.compose(string, Loader=yaml.SafeLoader)

    if not isinstance(node, yaml.nodes.SequenceNode):
        raise ValueError(f"Not a YAML list: {string!r}")

    items = []
    for item in node.value:
        raw = string[item.start_mark.index : item.end_mark.index].strip()

        if (
            isinstance(item, yaml.nodes.ScalarNode)
            and item.tag == "tag:yaml.org,2002:str"
        ):
            if (raw.startswith('"') and raw.endswith('"')) or (
                raw.startswith("'") and raw.endswith("'")
            ):
                raw = raw[1:-1]

        items.append(raw)

    return items


CAST_STR_TO_NATIVE: Mapping[str, Any] = {
    "bool": cast_to_bool,
    "float": float,
    "int": int,
    "json": json.loads,
    "str": cast_to_str,
    "yaml": parse_yaml_string,
    "path": str,
}


class QuestionRuntime:
    """Runtime execution context for a question.

    This class handles the runtime execution logic for a question,
    including:
    - Template rendering
    - Conditional logic (when)
    - Default value calculation
    - Type casting
    - Answer validation

    It is decoupled from user interaction.

    Args:
        schema: The question schema.
        answers: A map containing the answers provided by the user.
        context: A map containing the full rendering context.
        jinja_env: The Jinja environment used to rendering answers.
        settings: User settings model.
    """

    def __init__(
        self,
        schema: QuestionSchema,
        answers: AnswersMap,
        context: Mapping[str, Any],
        jinja_env: SandboxedEnvironment,
        settings: SettingsModel,
    ) -> None:
        self.schema = schema
        self.answers = answers
        self.context = context
        self.jinja_env = jinja_env
        self.settings = settings

    @property
    def var_name(self) -> str:
        """Get the question variable name."""
        return self.schema.var_name

    def render_value(
        self, value: Any, extra_answers: AnyByStrDict | None = None
    ) -> Any:
        """Render a single templated value using Jinja.

        If the value cannot be used as a template, it will be returned as is.
        `extra_answers` are combined with `self.context` when rendering
        the template.
        """
        try:
            template = self.jinja_env.from_string(value)
        except TypeError:
            return (
                [self.render_value(item) for item in value]
                if isinstance(value, list)
                else value
            )
        try:
            return template.render({**self.context, **(extra_answers or {})})
        except UnsetError:
            raise
        except UndefinedError as error:
            raise UserMessageError(str(error)) from error

    def get_type_name(self) -> str:
        """Render the type name and return it."""
        type_name = self.render_value(self.schema.type)
        if type_name not in CAST_STR_TO_NATIVE:
            raise InvalidTypeError(
                f'Unsupported type "{type_name}" in question "{self.schema.var_name}"'
            )
        return type_name

    def cast_answer(self, answer: Any) -> Any:
        """Cast answer to expected type."""
        type_name = self.get_type_name()
        type_fn = CAST_STR_TO_NATIVE[type_name]
        if answer is None and type_name not in {"json", "yaml"}:
            raise InvalidTypeError(
                f'Invalid answer "{answer}" of type "{type(answer)}" '
                f'to question "{self.schema.var_name}" of type "{type_name}"'
            )
        try:
            if self.schema.multiselect and isinstance(answer, list):
                return [type_fn(item) for item in answer]
            return type_fn(answer)
        except (TypeError, AttributeError) as error:
            if type_name in {"json", "yaml"}:
                return answer
            raise InvalidTypeError from error

    def get_when(self) -> bool:
        """Get skip condition for question."""
        return cast_to_bool(self.render_value(self.schema.when))

    def get_multiline(self) -> bool:
        """Get the value for multiline."""
        return cast_to_bool(self.render_value(self.schema.multiline))

    def validate_answer(self, answer: Any) -> None:
        """Validate user answer."""
        try:
            err_msg = self.render_value(
                self.schema.validator, {self.schema.var_name: answer}
            ).strip()
        except Exception as error:
            err_msg = str(error)
        if err_msg:
            raise ValueError(
                f"Validation error for question '{self.schema.var_name}': {err_msg}"
            )

    @cached_property
    def _formatted_choices(self) -> Sequence[Choice]:
        """Obtain choices rendered and properly formatted."""
        result = []
        choices = self.schema.choices
        if isinstance(choices, str):
            choices = parse_yaml_string(self.render_value(choices))
        if isinstance(choices, dict):
            choices = list(choices.items())
        for choice in choices:
            if isinstance(choice, (tuple, list)):
                name, value = choice
            else:
                name = value = choice
            name = str(self.render_value(name))
            disabled = ""
            if isinstance(choice, (tuple, list)) and isinstance(value, dict):
                if "value" not in value:
                    raise KeyError("Property 'value' is required")
                if "validator" in value and not isinstance(value["validator"], str):
                    raise ValueError("Property 'validator' must be a string")

                disabled = self.render_value(value.get("validator", ""))
                value = value["value"]
            c = Choice(name, self.render_value(value), disabled=disabled)
            self.cast_answer(c.value)
            result.append(c)
        return result

    def get_default(self) -> Any:
        """Get the default value for this question, casted to its expected type."""
        try:
            result = self.answers.init[self.schema.var_name]
        except KeyError:
            try:
                result = self.answers.last[self.schema.var_name]
            except KeyError:
                try:
                    result = self.answers.user_defaults[self.schema.var_name]
                except KeyError:
                    try:
                        result = self.render_value(
                            self.settings.defaults.get(
                                self.schema.var_name, self.schema.default
                            ),
                            extra_answers={
                                "UNSET": StrictUndefined("UNSET", exc=UnsetError)
                            },
                        )
                    except UnsetError:
                        return MISSING
                    if result is MISSING:
                        return MISSING
        result = self.parse_answer(result)
        if self.get_when() and not self.schema.secret:
            self.validate_answer(result)
        return result

    def get_default_rendered(self) -> bool | str | Choice | None | MissingType:
        """Get default answer rendered for the questionary lib.

        The questionary lib expects some specific data types, and returns
        it when the user answers. Sometimes you need to compare the response
        to the rendered one, or vice-versa.

        This helper allows such usages.
        """
        default = self.get_default()
        if default is MISSING:
            return MISSING
        if self.schema.choices:
            if not self.schema.multiselect:
                for choice in self._formatted_choices:
                    if choice.value == default:
                        return choice
            return None
        if isinstance(default, bool) and self.get_type_name() == "bool":
            return default
        if default is None:
            return ""
        if self.get_type_name() == "json":
            return json.dumps(default, indent=2 if self.get_multiline() else None)
        if self.get_type_name() == "yaml":
            return yaml.safe_dump(
                default, default_flow_style=not self.get_multiline(), width=2147483647
            ).strip()
        return str(default)

    def get_message(self) -> str:
        """Get the message that will be printed to the user."""
        if self.schema.help:
            if rendered_help := self.render_value(self.schema.help):
                return force_str_end(rendered_help) + "  "
        message = self.schema.var_name
        if (answer_type := self.get_type_name()) != "str":
            message += f" ({answer_type})"
        return message + "\n  "

    def get_placeholder(self) -> str:
        """Render and obtain the placeholder."""
        return self.render_value(self.schema.placeholder)

    def _parse_answer(self, answer: Any) -> Any:
        """Parse a single answer according to the question's type."""
        ans = self.cast_answer(answer)
        choices = self._formatted_choices
        if not choices:
            return ans
        choice_error = ""
        for choice in choices:
            if ans == self.cast_answer(choice.value):
                if not choice.disabled:
                    return ans
                if not choice_error:
                    choice_error = choice.disabled
        raise ValueError(
            f"Invalid choice: {choice_error}" if choice_error else "Invalid choice"
        )

    def parse_answer(self, answer: Any) -> Any:
        """Parse the answer according to the question's type."""
        if self.schema.multiselect:
            if isinstance(answer, str):
                answer = parse_yaml_list(answer)
            answer = [self._parse_answer(a) for a in answer]
            choices = (
                self.cast_answer(choice.value) for choice in self._formatted_choices
            )
            return [choice for choice in choices if choice in answer]
        return self._parse_answer(answer)

    def get_questionary_structure(self) -> AnyByStrDict:
        """Get the question in a format that the questionary lib understands."""

        def _validate(answer: str) -> str | Any:
            try:
                ans = self.parse_answer(answer)
            except Exception:
                return "Invalid input"
            try:
                self.validate_answer(ans)
            except Exception as exc:
                return str(exc)
            return True

        from prompt_toolkit.lexers import PygmentsLexer
        from pygments.lexers.data import JsonLexer, YamlLexer

        lexer = None
        result: AnyByStrDict = {
            "filter": self.cast_answer,
            "message": self.get_message(),
            "mouse_support": True,
            "name": self.schema.var_name,
            "qmark": self.schema.qmark or ("🕵️" if self.schema.secret else "🎤"),
            "when": lambda _: self.get_when(),
        }
        default = self.get_default_rendered()
        if default is not MISSING:
            result["default"] = default
        questionary_type = "input"
        type_name = self.get_type_name()
        if type_name == "bool":
            questionary_type = "confirm"
            if default is MISSING:
                result["default"] = False
        if self.schema.choices:
            questionary_type = "checkbox" if self.schema.multiselect else "select"
            choices = self._formatted_choices
            if self.schema.multiselect and isinstance(
                default_choices := self.get_default(), list
            ):
                for choice in (choices := deepcopy(choices)):
                    choice.checked = self.cast_answer(choice.value) in default_choices
            result["choices"] = choices
        if questionary_type == "input":
            if self.schema.secret:
                questionary_type = "password"
            elif type_name == "yaml":
                lexer = PygmentsLexer(YamlLexer)
            elif type_name == "json":
                lexer = PygmentsLexer(JsonLexer)
            if lexer:
                result["lexer"] = lexer
            result["multiline"] = self.get_multiline()
            if placeholder := self.get_placeholder():
                result["placeholder"] = placeholder
        if type_name == "path":
            questionary_type = "path"
        if questionary_type in {"input", "checkbox", "password", "path"}:
            result["validate"] = _validate
        result.update({"type": questionary_type})
        return result
