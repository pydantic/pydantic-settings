"""Base classes and core functionality for pydantic-settings sources."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from pydantic import AliasChoices, AliasPath, BaseModel, TypeAdapter
from pydantic._internal._typing_extra import (  # type: ignore[attr-defined]
    get_origin,
)
from pydantic._internal._utils import is_model_class
from pydantic.fields import FieldInfo
from typing_extensions import get_args
from typing_inspection.introspection import is_union_origin

from ..exceptions import SettingsError
from ..utils import _lenient_issubclass
from .types import EnvNoneType, ForceDecode, NoDecode, PathType, PydanticModel, _CliSubCommand
from .utils import (
    _annotation_is_complex,
    _get_alias_names,
    _get_model_fields,
    _union_is_complex,
)

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


def get_subcommand(
    model: PydanticModel, is_required: bool = True, cli_exit_on_error: bool | None = None
) -> Optional[PydanticModel]:
    """
    Get the subcommand from a model.

    Args:
        model: The model to get the subcommand from.
        is_required: Determines whether a model must have subcommand set and raises error if not
            found. Defaults to `True`.
        cli_exit_on_error: Determines whether this function exits with error if no subcommand is found.
            Defaults to model_config `cli_exit_on_error` value if set. Otherwise, defaults to `True`.

    Returns:
        The subcommand model if found, otherwise `None`.

    Raises:
        SystemExit: When no subcommand is found and is_required=`True` and cli_exit_on_error=`True`
            (the default).
        SettingsError: When no subcommand is found and is_required=`True` and
            cli_exit_on_error=`False`.
    """

    model_cls = type(model)
    if cli_exit_on_error is None and is_model_class(model_cls):
        model_default = model_cls.model_config.get('cli_exit_on_error')
        if isinstance(model_default, bool):
            cli_exit_on_error = model_default
    if cli_exit_on_error is None:
        cli_exit_on_error = True

    subcommands: list[str] = []
    for field_name, field_info in _get_model_fields(model_cls).items():
        if _CliSubCommand in field_info.metadata:
            if getattr(model, field_name) is not None:
                return getattr(model, field_name)
            subcommands.append(field_name)

    if is_required:
        error_message = (
            f'Error: CLI subcommand is required {{{", ".join(subcommands)}}}'
            if subcommands
            else 'Error: CLI subcommand is required but no subcommands were found.'
        )
        raise SystemExit(error_message) if cli_exit_on_error else SettingsError(error_message)

    return None


class PydanticBaseSettingsSource(ABC):
    """
    Abstract base class for settings sources, every settings source classes should inherit from it.
    """

    def __init__(self, settings_cls: type[BaseSettings]):
        self.settings_cls = settings_cls
        self.config = settings_cls.model_config
        self._current_state: dict[str, Any] = {}
        self._settings_sources_data: dict[str, dict[str, Any]] = {}

    def _set_current_state(self, state: dict[str, Any]) -> None:
        """
        Record the state of settings from the previous settings sources. This should
        be called right before __call__.
        """
        self._current_state = state

    def _set_settings_sources_data(self, states: dict[str, dict[str, Any]]) -> None:
        """
        Record the state of settings from all previous settings sources. This should
        be called right before __call__.
        """
        self._settings_sources_data = states

    @property
    def current_state(self) -> dict[str, Any]:
        """
        The current state of the settings, populated by the previous settings sources.
        """
        return self._current_state

    @property
    def settings_sources_data(self) -> dict[str, dict[str, Any]]:
        """
        The state of all previous settings sources.
        """
        return self._settings_sources_data

    @abstractmethod
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """
        Gets the value, the key for model creation, and a flag to determine whether value is complex.

        This is an abstract method that should be overridden in every settings source classes.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple that contains the value, key and a flag to determine whether value is complex.
        """
        pass

    def field_is_complex(self, field: FieldInfo) -> bool:
        """
        Checks whether a field is complex, in which case it will attempt to be parsed as JSON.

        Args:
            field: The field.

        Returns:
            Whether the field is complex.
        """
        return _annotation_is_complex(field.annotation, field.metadata)

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        """
        Prepares the value of a field.

        Args:
            field_name: The field name.
            field: The field.
            value: The value of the field that has to be prepared.
            value_is_complex: A flag to determine whether value is complex.

        Returns:
            The prepared value.
        """
        if value is not None and (self.field_is_complex(field) or value_is_complex):
            return self.decode_complex_value(field_name, field, value)
        return value

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        """
        Decode the value for a complex field

        Args:
            field_name: The field name.
            field: The field.
            value: The value of the field that has to be prepared.

        Returns:
            The decoded value for further preparation
        """
        if field and (
            NoDecode in field.metadata
            or (self.config.get('enable_decoding') is False and ForceDecode not in field.metadata)
        ):
            return value

        return json.loads(value)

    @abstractmethod
    def __call__(self) -> dict[str, Any]:
        pass


class ConfigFileSourceMixin(ABC):
    def _read_files(self, files: PathType | None) -> dict[str, Any]:
        if files is None:
            return {}
        if isinstance(files, (str, os.PathLike)):
            files = [files]
        vars: dict[str, Any] = {}
        for file in files:
            file_path = Path(file).expanduser()
            if file_path.is_file():
                vars.update(self._read_file(file_path))
        return vars

    @abstractmethod
    def _read_file(self, path: Path) -> dict[str, Any]:
        pass


class DefaultSettingsSource(PydanticBaseSettingsSource):
    """
    Source class for loading default object values.

    Args:
        settings_cls: The Settings class.
        nested_model_default_partial_update: Whether to allow partial updates on nested model default object fields.
            Defaults to `False`.
    """

    def __init__(self, settings_cls: type[BaseSettings], nested_model_default_partial_update: bool | None = None):
        super().__init__(settings_cls)
        self.defaults: dict[str, Any] = {}
        self.nested_model_default_partial_update = (
            nested_model_default_partial_update
            if nested_model_default_partial_update is not None
            else self.config.get('nested_model_default_partial_update', False)
        )
        if self.nested_model_default_partial_update:
            for field_name, field_info in settings_cls.model_fields.items():
                alias_names, *_ = _get_alias_names(field_name, field_info)
                preferred_alias = alias_names[0]
                if is_dataclass(type(field_info.default)):
                    self.defaults[preferred_alias] = asdict(field_info.default)
                elif is_model_class(type(field_info.default)):
                    self.defaults[preferred_alias] = field_info.default.model_dump()

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Nothing to do here. Only implement the return statement to make mypy happy
        return None, '', False

    def __call__(self) -> dict[str, Any]:
        return self.defaults

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(nested_model_default_partial_update={self.nested_model_default_partial_update})'
        )


class InitSettingsSource(PydanticBaseSettingsSource):
    """
    Source class for loading values provided during settings class initialization.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        init_kwargs: dict[str, Any],
        nested_model_default_partial_update: bool | None = None,
    ):
        self.init_kwargs = {}
        init_kwarg_names = set(init_kwargs.keys())
        for field_name, field_info in settings_cls.model_fields.items():
            alias_names, *_ = _get_alias_names(field_name, field_info)
            init_kwarg_name = init_kwarg_names & set(alias_names)
            if init_kwarg_name:
                preferred_alias = alias_names[0]
                init_kwarg_names -= init_kwarg_name
                self.init_kwargs[preferred_alias] = init_kwargs[init_kwarg_name.pop()]
        self.init_kwargs.update({key: val for key, val in init_kwargs.items() if key in init_kwarg_names})

        super().__init__(settings_cls)
        self.nested_model_default_partial_update = (
            nested_model_default_partial_update
            if nested_model_default_partial_update is not None
            else self.config.get('nested_model_default_partial_update', False)
        )

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Nothing to do here. Only implement the return statement to make mypy happy
        return None, '', False

    def __call__(self) -> dict[str, Any]:
        return (
            TypeAdapter(dict[str, Any]).dump_python(self.init_kwargs)
            if self.nested_model_default_partial_update
            else self.init_kwargs
        )

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(init_kwargs={self.init_kwargs!r})'


class PydanticBaseEnvSettingsSource(PydanticBaseSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_ignore_empty: bool | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
    ) -> None:
        super().__init__(settings_cls)
        self.case_sensitive = case_sensitive if case_sensitive is not None else self.config.get('case_sensitive', False)
        self.env_prefix = env_prefix if env_prefix is not None else self.config.get('env_prefix', '')
        self.env_ignore_empty = (
            env_ignore_empty if env_ignore_empty is not None else self.config.get('env_ignore_empty', False)
        )
        self.env_parse_none_str = (
            env_parse_none_str if env_parse_none_str is not None else self.config.get('env_parse_none_str')
        )
        self.env_parse_enums = env_parse_enums if env_parse_enums is not None else self.config.get('env_parse_enums')

    def _apply_case_sensitive(self, value: str) -> str:
        return value.lower() if not self.case_sensitive else value

    def _extract_field_info(self, field: FieldInfo, field_name: str) -> list[tuple[str, str, bool]]:
        """
        Extracts field info. This info is used to get the value of field from environment variables.

        It returns a list of tuples, each tuple contains:
            * field_key: The key of field that has to be used in model creation.
            * env_name: The environment variable name of the field.
            * value_is_complex: A flag to determine whether the value from environment variable
              is complex and has to be parsed.

        Args:
            field (FieldInfo): The field.
            field_name (str): The field name.

        Returns:
            list[tuple[str, str, bool]]: List of tuples, each tuple contains field_key, env_name, and value_is_complex.
        """
        field_info: list[tuple[str, str, bool]] = []
        if isinstance(field.validation_alias, (AliasChoices, AliasPath)):
            v_alias: str | list[str | int] | list[list[str | int]] | None = field.validation_alias.convert_to_aliases()
        else:
            v_alias = field.validation_alias

        if v_alias:
            if isinstance(v_alias, list):  # AliasChoices, AliasPath
                for alias in v_alias:
                    if isinstance(alias, str):  # AliasPath
                        field_info.append((alias, self._apply_case_sensitive(alias), True if len(alias) > 1 else False))
                    elif isinstance(alias, list):  # AliasChoices
                        first_arg = cast(str, alias[0])  # first item of an AliasChoices must be a str
                        field_info.append(
                            (first_arg, self._apply_case_sensitive(first_arg), True if len(alias) > 1 else False)
                        )
            else:  # string validation alias
                field_info.append((v_alias, self._apply_case_sensitive(v_alias), False))

        if not v_alias or self.config.get('populate_by_name', False):
            if is_union_origin(get_origin(field.annotation)) and _union_is_complex(field.annotation, field.metadata):
                field_info.append((field_name, self._apply_case_sensitive(self.env_prefix + field_name), True))
            else:
                field_info.append((field_name, self._apply_case_sensitive(self.env_prefix + field_name), False))

        return field_info

    def _replace_field_names_case_insensitively(self, field: FieldInfo, field_values: dict[str, Any]) -> dict[str, Any]:
        """
        Replace field names in values dict by looking in models fields insensitively.

        By having the following models:

            ```py
            class SubSubSub(BaseModel):
                VaL3: str

            class SubSub(BaseModel):
                Val2: str
                SUB_sub_SuB: SubSubSub

            class Sub(BaseModel):
                VAL1: str
                SUB_sub: SubSub

            class Settings(BaseSettings):
                nested: Sub

                model_config = SettingsConfigDict(env_nested_delimiter='__')
            ```

        Then:
            _replace_field_names_case_insensitively(
                field,
                {"val1": "v1", "sub_SUB": {"VAL2": "v2", "sub_SUB_sUb": {"vAl3": "v3"}}}
            )
            Returns {'VAL1': 'v1', 'SUB_sub': {'Val2': 'v2', 'SUB_sub_SuB': {'VaL3': 'v3'}}}
        """
        values: dict[str, Any] = {}

        for name, value in field_values.items():
            sub_model_field: FieldInfo | None = None

            annotation = field.annotation

            # If field is Optional, we need to find the actual type
            if is_union_origin(get_origin(field.annotation)):
                args = get_args(annotation)
                if len(args) == 2 and type(None) in args:
                    for arg in args:
                        if arg is not None:
                            annotation = arg
                            break

            # This is here to make mypy happy
            # Item "None" of "Optional[Type[Any]]" has no attribute "model_fields"
            if not annotation or not hasattr(annotation, 'model_fields'):
                values[name] = value
                continue

            # Find field in sub model by looking in fields case insensitively
            for sub_model_field_name, f in annotation.model_fields.items():
                if not f.validation_alias and sub_model_field_name.lower() == name.lower():
                    sub_model_field = f
                    break

            if not sub_model_field:
                values[name] = value
                continue

            if _lenient_issubclass(sub_model_field.annotation, BaseModel) and isinstance(value, dict):
                values[sub_model_field_name] = self._replace_field_names_case_insensitively(sub_model_field, value)
            else:
                values[sub_model_field_name] = value

        return values

    def _replace_env_none_type_values(self, field_value: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively parse values that are of "None" type(EnvNoneType) to `None` type(None).
        """
        values: dict[str, Any] = {}

        for key, value in field_value.items():
            if not isinstance(value, EnvNoneType):
                values[key] = value if not isinstance(value, dict) else self._replace_env_none_type_values(value)
            else:
                values[key] = None

        return values

    def _get_resolved_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """
        Gets the value, the preferred alias key for model creation, and a flag to determine whether value
        is complex.

        Note:
            In V3, this method should either be made public, or, this method should be removed and the
            abstract method get_field_value should be updated to include a "use_preferred_alias" flag.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple that contains the value, preferred key and a flag to determine whether value is complex.
        """
        field_value, field_key, value_is_complex = self.get_field_value(field, field_name)
        if not (value_is_complex or (self.config.get('populate_by_name', False) and (field_key == field_name))):
            field_infos = self._extract_field_info(field, field_name)
            preferred_key, *_ = field_infos[0]
            return field_value, preferred_key, value_is_complex
        return field_value, field_key, value_is_complex

    def __call__(self) -> dict[str, Any]:
        data: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            try:
                field_value, field_key, value_is_complex = self._get_resolved_field_value(field, field_name)
            except Exception as e:
                raise SettingsError(
                    f'error getting value for field "{field_name}" from source "{self.__class__.__name__}"'
                ) from e

            try:
                field_value = self.prepare_field_value(field_name, field, field_value, value_is_complex)
            except ValueError as e:
                raise SettingsError(
                    f'error parsing value for field "{field_name}" from source "{self.__class__.__name__}"'
                ) from e

            if field_value is not None:
                if self.env_parse_none_str is not None:
                    if isinstance(field_value, dict):
                        field_value = self._replace_env_none_type_values(field_value)
                    elif isinstance(field_value, EnvNoneType):
                        field_value = None
                if (
                    not self.case_sensitive
                    # and _lenient_issubclass(field.annotation, BaseModel)
                    and isinstance(field_value, dict)
                ):
                    data[field_key] = self._replace_field_names_case_insensitively(field, field_value)
                else:
                    data[field_key] = field_value

        return data


__all__ = [
    'ConfigFileSourceMixin',
    'DefaultSettingsSource',
    'InitSettingsSource',
    'PydanticBaseEnvSettingsSource',
    'PydanticBaseSettingsSource',
    'SettingsError',
]
