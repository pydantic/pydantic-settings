from __future__ import annotations as _annotations

import json
import os
import sys
import warnings
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import is_dataclass
from pathlib import Path
from types import FunctionType
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Mapping, Sequence, Tuple, TypeVar, Union, cast

import typing_extensions
from dotenv import dotenv_values
from pydantic import AliasChoices, AliasPath, BaseModel, Json, TypeAdapter
from pydantic._internal._repr import Representation
from pydantic._internal._typing_extra import WithArgsTypes, origin_is_union, typing_base
from pydantic._internal._utils import deep_update, is_model_class, lenient_issubclass
from pydantic.fields import FieldInfo
from typing_extensions import Annotated, get_args, get_origin

from pydantic_settings.utils import path_type_label

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings

from argparse import SUPPRESS, ArgumentParser, _ArgumentGroup, _SubParsersAction

DotenvType = Union[Path, str, List[Union[Path, str]], Tuple[Union[Path, str], ...]]

# This is used as default value for `_env_file` in the `BaseSettings` class and
# `env_file` in `DotEnvSettingsSource` so the default can be distinguished from `None`.
# See the docstring of `BaseSettings` for more details.
ENV_FILE_SENTINEL: DotenvType = Path('')


class _CliSubCommand:
    pass


class _CliPositionalArg:
    pass


T = TypeVar('T')
CliSubCommand = Annotated[Union[T, None], _CliSubCommand]
CliPositionalArg = Annotated[T, _CliPositionalArg]


class EnvNoneType(str):
    pass


class SettingsError(ValueError):
    pass


class PydanticBaseSettingsSource(ABC):
    """
    Abstract base class for settings sources, every settings source classes should inherit from it.
    """

    def __init__(self, settings_cls: type[BaseSettings]):
        self.settings_cls = settings_cls
        self.config = settings_cls.model_config

    @abstractmethod
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """
        Gets the value, the key for model creation, and a flag to determine whether value is complex.

        This is an abstract method that should be overridden in every settings source classes.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple contains the key, value and a flag to determine whether value is complex.
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
        return json.loads(value)

    @abstractmethod
    def __call__(self) -> dict[str, Any]:
        pass


class InitSettingsSource(PydanticBaseSettingsSource):
    """
    Source class for loading values provided during settings class initialization.
    """

    def __init__(self, settings_cls: type[BaseSettings], init_kwargs: dict[str, Any]):
        self.init_kwargs = init_kwargs
        super().__init__(settings_cls)

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Nothing to do here. Only implement the return statement to make mypy happy
        return None, '', False

    def __call__(self) -> dict[str, Any]:
        return TypeAdapter(Dict[str, Any]).dump_python(self.init_kwargs)

    def __repr__(self) -> str:
        return f'InitSettingsSource(init_kwargs={self.init_kwargs!r})'


class PydanticBaseEnvSettingsSource(PydanticBaseSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_ignore_empty: bool | None = None,
        env_parse_none_str: str | None = None,
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
        elif origin_is_union(get_origin(field.annotation)) and _union_is_complex(field.annotation, field.metadata):
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

            # This is here to make mypy happy
            # Item "None" of "Optional[Type[Any]]" has no attribute "model_fields"
            if not field.annotation or not hasattr(field.annotation, 'model_fields'):
                values[name] = value
                continue

            # Find field in sub model by looking in fields case insensitively
            for sub_model_field_name, f in field.annotation.model_fields.items():
                if not f.validation_alias and sub_model_field_name.lower() == name.lower():
                    sub_model_field = f
                    break

            if not sub_model_field:
                values[name] = value
                continue

            if lenient_issubclass(sub_model_field.annotation, BaseModel) and isinstance(value, dict):
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

    def __call__(self) -> dict[str, Any]:
        data: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            try:
                field_value, field_key, value_is_complex = self.get_field_value(field, field_name)
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
                    and lenient_issubclass(field.annotation, BaseModel)
                    and isinstance(field_value, dict)
                ):
                    data[field_key] = self._replace_field_names_case_insensitively(field, field_value)
                else:
                    data[field_key] = field_value

        return data


class SecretsSettingsSource(PydanticBaseEnvSettingsSource):
    """
    Source class for loading settings values from secret files.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        secrets_dir: str | Path | None = None,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_ignore_empty: bool | None = None,
        env_parse_none_str: str | None = None,
    ) -> None:
        super().__init__(settings_cls, case_sensitive, env_prefix, env_ignore_empty, env_parse_none_str)
        self.secrets_dir = secrets_dir if secrets_dir is not None else self.config.get('secrets_dir')

    def __call__(self) -> dict[str, Any]:
        """
        Build fields from "secrets" files.
        """
        secrets: dict[str, str | None] = {}

        if self.secrets_dir is None:
            return secrets

        self.secrets_path = Path(self.secrets_dir).expanduser()

        if not self.secrets_path.exists():
            warnings.warn(f'directory "{self.secrets_path}" does not exist')
            return secrets

        if not self.secrets_path.is_dir():
            raise SettingsError(f'secrets_dir must reference a directory, not a {path_type_label(self.secrets_path)}')

        return super().__call__()

    @classmethod
    def find_case_path(cls, dir_path: Path, file_name: str, case_sensitive: bool) -> Path | None:
        """
        Find a file within path's directory matching filename, optionally ignoring case.

        Args:
            dir_path: Directory path.
            file_name: File name.
            case_sensitive: Whether to search for file name case sensitively.

        Returns:
            Whether file path or `None` if file does not exist in directory.
        """
        for f in dir_path.iterdir():
            if f.name == file_name:
                return f
            elif not case_sensitive and f.name.lower() == file_name.lower():
                return f
        return None

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """
        Gets the value for field from secret file and a flag to determine whether value is complex.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple contains the key, value if the file exists otherwise `None`, and
                a flag to determine whether value is complex.
        """

        for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
            path = self.find_case_path(self.secrets_path, env_name, self.case_sensitive)
            if not path:
                # path does not exist, we currently don't return a warning for this
                continue

            if path.is_file():
                return path.read_text().strip(), field_key, value_is_complex
            else:
                warnings.warn(
                    f'attempted to load secret file "{path}" but found a {path_type_label(path)} instead.',
                    stacklevel=4,
                )

        return None, field_key, value_is_complex

    def __repr__(self) -> str:
        return f'SecretsSettingsSource(secrets_dir={self.secrets_dir!r})'


class EnvSettingsSource(PydanticBaseEnvSettingsSource):
    """
    Source class for loading settings values from environment variables.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = None,
        env_ignore_empty: bool | None = None,
        env_parse_none_str: str | None = None,
    ) -> None:
        super().__init__(settings_cls, case_sensitive, env_prefix, env_ignore_empty, env_parse_none_str)
        self.env_nested_delimiter = (
            env_nested_delimiter if env_nested_delimiter is not None else self.config.get('env_nested_delimiter')
        )
        self.env_prefix_len = len(self.env_prefix)

        self.env_vars = self._load_env_vars()

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return parse_env_vars(os.environ, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """
        Gets the value for field from environment variables and a flag to determine whether value is complex.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple contains the key, value if the file exists otherwise `None`, and
                a flag to determine whether value is complex.
        """

        env_val: str | None = None
        for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
            env_val = self.env_vars.get(env_name)
            if env_val is not None:
                break

        return env_val, field_key, value_is_complex

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        """
        Prepare value for the field.

        * Extract value for nested field.
        * Deserialize value to python object for complex field.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple contains prepared value for the field.

        Raises:
            ValuesError: When There is an error in deserializing value for complex field.
        """
        is_complex, allow_parse_failure = self._field_is_complex(field)
        if is_complex or value_is_complex:
            if isinstance(value, EnvNoneType):
                return value
            elif value is None:
                # field is complex but no value found so far, try explode_env_vars
                env_val_built = self.explode_env_vars(field_name, field, self.env_vars)
                if env_val_built:
                    return env_val_built
            else:
                # field is complex and there's a value, decode that as JSON, then add explode_env_vars
                try:
                    value = self.decode_complex_value(field_name, field, value)
                except ValueError as e:
                    if not allow_parse_failure:
                        raise e

                if isinstance(value, dict):
                    return deep_update(value, self.explode_env_vars(field_name, field, self.env_vars))
                else:
                    return value
        elif value is not None:
            # simplest case, field is not complex, we only need to add the value if it was found
            return value

    def _field_is_complex(self, field: FieldInfo) -> tuple[bool, bool]:
        """
        Find out if a field is complex, and if so whether JSON errors should be ignored
        """
        if self.field_is_complex(field):
            allow_parse_failure = False
        elif origin_is_union(get_origin(field.annotation)) and _union_is_complex(field.annotation, field.metadata):
            allow_parse_failure = True
        else:
            return False, False

        return True, allow_parse_failure

    @staticmethod
    def next_field(field: FieldInfo | Any | None, key: str) -> FieldInfo | None:
        """
        Find the field in a sub model by key(env name)

        By having the following models:

            ```py
            class SubSubModel(BaseSettings):
                dvals: Dict

            class SubModel(BaseSettings):
                vals: list[str]
                sub_sub_model: SubSubModel

            class Cfg(BaseSettings):
                sub_model: SubModel
            ```

        Then:
            next_field(sub_model, 'vals') Returns the `vals` field of `SubModel` class
            next_field(sub_model, 'sub_sub_model') Returns `sub_sub_model` field of `SubModel` class

        Args:
            field: The field.
            key: The key (env name).

        Returns:
            Field if it finds the next field otherwise `None`.
        """
        if not field:
            return None

        annotation = field.annotation if isinstance(field, FieldInfo) else field
        if origin_is_union(get_origin(annotation)) or isinstance(annotation, WithArgsTypes):
            for type_ in get_args(annotation):
                type_has_key = EnvSettingsSource.next_field(type_, key)
                if type_has_key:
                    return type_has_key
        elif is_model_class(annotation) and annotation.model_fields.get(key):
            return annotation.model_fields[key]

        return None

    def explode_env_vars(self, field_name: str, field: FieldInfo, env_vars: Mapping[str, str | None]) -> dict[str, Any]:
        """
        Process env_vars and extract the values of keys containing env_nested_delimiter into nested dictionaries.

        This is applied to a single field, hence filtering by env_var prefix.

        Args:
            field_name: The field name.
            field: The field.
            env_vars: Environment variables.

        Returns:
            A dictionary contains extracted values from nested env values.
        """
        prefixes = [
            f'{env_name}{self.env_nested_delimiter}' for _, env_name, _ in self._extract_field_info(field, field_name)
        ]
        result: dict[str, Any] = {}
        for env_name, env_val in env_vars.items():
            if not any(env_name.startswith(prefix) for prefix in prefixes):
                continue
            # we remove the prefix before splitting in case the prefix has characters in common with the delimiter
            env_name_without_prefix = env_name[self.env_prefix_len :]
            _, *keys, last_key = env_name_without_prefix.split(self.env_nested_delimiter)
            env_var = result
            target_field: FieldInfo | None = field
            for key in keys:
                target_field = self.next_field(target_field, key)
                env_var = env_var.setdefault(key, {})

            # get proper field with last_key
            target_field = self.next_field(target_field, last_key)

            # check if env_val maps to a complex field and if so, parse the env_val
            if target_field and env_val:
                is_complex, allow_json_failure = self._field_is_complex(target_field)
                if is_complex:
                    try:
                        env_val = self.decode_complex_value(last_key, target_field, env_val)
                    except ValueError as e:
                        if not allow_json_failure:
                            raise e
            env_var[last_key] = env_val

        return result

    def __repr__(self) -> str:
        return (
            f'EnvSettingsSource(env_nested_delimiter={self.env_nested_delimiter!r}, '
            f'env_prefix_len={self.env_prefix_len!r})'
        )


class DotEnvSettingsSource(EnvSettingsSource):
    """
    Source class for loading settings values from env files.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_file: DotenvType | None = ENV_FILE_SENTINEL,
        env_file_encoding: str | None = None,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = None,
        env_ignore_empty: bool | None = None,
        env_parse_none_str: str | None = None,
    ) -> None:
        self.env_file = env_file if env_file != ENV_FILE_SENTINEL else settings_cls.model_config.get('env_file')
        self.env_file_encoding = (
            env_file_encoding if env_file_encoding is not None else settings_cls.model_config.get('env_file_encoding')
        )
        super().__init__(
            settings_cls, case_sensitive, env_prefix, env_nested_delimiter, env_ignore_empty, env_parse_none_str
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return self._read_env_files()

    def _read_env_files(self) -> Mapping[str, str | None]:
        env_files = self.env_file
        if env_files is None:
            return {}

        if isinstance(env_files, (str, os.PathLike)):
            env_files = [env_files]

        dotenv_vars: dict[str, str | None] = {}
        for env_file in env_files:
            env_path = Path(env_file).expanduser()
            if env_path.is_file():
                dotenv_vars.update(
                    read_env_file(
                        env_path,
                        encoding=self.env_file_encoding,
                        case_sensitive=self.case_sensitive,
                        ignore_empty=self.env_ignore_empty,
                        parse_none_str=self.env_parse_none_str,
                    )
                )

        return dotenv_vars

    def __call__(self) -> dict[str, Any]:
        data: dict[str, Any] = super().__call__()

        data_lower_keys: list[str] = []
        is_extra_allowed = self.config.get('extra') != 'forbid'
        if not self.case_sensitive:
            data_lower_keys = [x.lower() for x in data.keys()]
        # As `extra` config is allowed in dotenv settings source, We have to
        # update data with extra env variabels from dotenv file.
        for env_name, env_value in self.env_vars.items():
            if not is_extra_allowed and not env_name.startswith(self.env_prefix):
                raise SettingsError(
                    "unable to load environment variables from dotenv file "
                    f"due to the presence of variables without the specified prefix - '{self.env_prefix}'"
                )
            if env_name.startswith(self.env_prefix) and env_value is not None:
                env_name_without_prefix = env_name[self.env_prefix_len :]
                first_key, *_ = env_name_without_prefix.split(self.env_nested_delimiter)

                if (data_lower_keys and first_key not in data_lower_keys) or (
                    not data_lower_keys and first_key not in data
                ):
                    data[first_key] = env_value

        return data

    def __repr__(self) -> str:
        return (
            f'DotEnvSettingsSource(env_file={self.env_file!r}, env_file_encoding={self.env_file_encoding!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r}, env_prefix_len={self.env_prefix_len!r})'
        )


class CliSettingsSource(EnvSettingsSource):
    """
    Source class for loading settings values from CLI.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        cli_prog_name: str | None = None,
        cli_parse_args: bool | list[str] | None = None,
        cli_parse_none_str: str | None = None,
        cli_hide_none_type: bool | None = None,
        cli_avoid_json: bool | None = None,
        cli_enforce_required: bool | None = None,
        cli_use_class_docs_for_groups: bool | None = None,
    ) -> None:
        self.cli_prog_name = sys.argv[0] if cli_prog_name is None else cli_prog_name
        self.cli_parse_args = cli_parse_args
        if self.cli_parse_args not in (None, False):
            if self.cli_parse_args is True:
                self.cli_parse_args = sys.argv[1:]
            elif not isinstance(self.cli_parse_args, list):
                raise SettingsError(f'cli_parse_args must be List[str], recieved {type(self.cli_parse_args)}')
        self.cli_hide_none_type = (
            cli_hide_none_type if cli_hide_none_type is not None else self.config.get('cli_hide_none_type', False)
        )
        self.cli_avoid_json = cli_avoid_json if cli_avoid_json is not None else self.config.get('cli_avoid_json', False)
        if cli_parse_none_str is None:
            cli_parse_none_str = 'None' if self.cli_avoid_json is True else 'null'
        self.cli_enforce_required = (
            cli_enforce_required if cli_enforce_required is not None else self.config.get('cli_enforce_required', False)
        )
        self.cli_use_class_docs_for_groups = (
            cli_use_class_docs_for_groups
            if cli_use_class_docs_for_groups is not None
            else self.config.get('cli_use_class_docs_for_groups', False)
        )
        super().__init__(settings_cls, env_nested_delimiter='.', env_parse_none_str=cli_parse_none_str)

    def _load_env_vars(self) -> Mapping[str, str | None]:
        if self.cli_parse_args in (None, False):
            return {}

        self._cli_dict_arg_names: list[str] = []
        self._cli_subcommands: dict[str, list[str]] = {}
        parser: ArgumentParser = self._add_fields_to_parser(
            ArgumentParser(prog=self.cli_prog_name, description=self.settings_cls.__doc__),
            model=self.settings_cls,
            added_args=[],
            arg_prefix='',
            subcommand_prefix='',
            group=None,
        )

        parsed_args: dict[str, list[str] | str] = vars(parser.parse_args(self.cli_parse_args))  # type: ignore
        selected_subcommands: list[str] = []
        for field_name, val in parsed_args.items():
            if isinstance(val, list):
                merge_list = []
                for sub_val in val:
                    if sub_val.startswith('[') and sub_val.endswith(']'):
                        sub_val = sub_val[1:-1]
                    merge_list.append(sub_val)
                parsed_args[field_name] = (
                    f'[{",".join(merge_list)}]'
                    if field_name not in self._cli_dict_arg_names
                    else self._merge_json_key_val_list_str(f'[{",".join(merge_list)}]')
                )
            elif field_name.endswith(':subcommand') and val is not None:
                selected_subcommands.append(field_name.split(':')[0] + val)

        for subcommands in self._cli_subcommands.values():
            for subcommand in subcommands:
                if subcommand not in selected_subcommands:
                    parsed_args[subcommand] = self.env_parse_none_str  # type: ignore

        parsed_args = {key: val for key, val in parsed_args.items() if not key.endswith(':subcommand')}
        if selected_subcommands:
            last_selected_subcommand = max(selected_subcommands, key=len)
            if not any(field_name for field_name in parsed_args.keys() if f'{last_selected_subcommand}.' in field_name):
                parsed_args[last_selected_subcommand] = '{}'

        return parse_env_vars(
            parsed_args, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str  # type: ignore
        )

    def _merge_json_key_val_list_str(self, key_val_list_str: str) -> str:
        orig_key_val_list_str, key_val_list_str = key_val_list_str, key_val_list_str[1:-1]
        key_val_dict: dict[str, str] = {}
        obj_count = 0
        while key_val_list_str:
            if obj_count != 0:
                raise SettingsError(f'Parsing error encountered on JSON object {orig_key_val_list_str}')
            for i in range(len(key_val_list_str)):
                if key_val_list_str[i] == '{':
                    obj_count += 1
                elif key_val_list_str[i] == '}':
                    obj_count -= 1
                    if obj_count == 0:
                        key_val_dict.update(json.loads(key_val_list_str[: i + 1]))
                        key_val_list_str = key_val_list_str[i + 1 :].lstrip(',')
                        break
                elif obj_count == 0:
                    val, quote_count = '', 0
                    key, key_val_list_str = key_val_list_str.split('=', 1)
                    for i in range(len(key_val_list_str)):
                        if key_val_list_str[i] in ('"', "'"):
                            quote_count += 1
                        if key_val_list_str[i] == ',' and quote_count % 2 == 0:
                            val, key_val_list_str = key_val_list_str[:i], key_val_list_str[i:].lstrip(',')
                            break
                    if not val:
                        val, key_val_list_str = key_val_list_str, ''
                    key_val_dict.update({key.strip('\'"'): val.strip('\'"')})
                    break
        return json.dumps(key_val_dict)

    def _get_sub_models(self, model: type[BaseModel], field_name: str, field_info: FieldInfo) -> list[type[BaseModel]]:
        field_types: tuple[Any, ...] = (
            (field_info.annotation,) if not get_args(field_info.annotation) else get_args(field_info.annotation)
        )
        if self.cli_hide_none_type:
            field_types = tuple([type_ for type_ in field_types if type_ is not type(None)])

        sub_models: list[type[BaseModel]] = []
        for type_ in field_types:
            if get_origin(type_) is Annotated:
                if _CliSubCommand in get_args(type_):
                    raise SettingsError(f'CliSubCommand is not outermost annotation for {model.__name__}.{field_name}')
                elif _CliPositionalArg in get_args(type_):
                    raise SettingsError(
                        f'CliPositionalArg is not outermost annotation for {model.__name__}.{field_name}'
                    )
            if is_model_class(type_):
                sub_models.append(type_)
        return sub_models

    def _sort_arg_fields(self, model: type[BaseModel]) -> list[tuple[str, FieldInfo]]:
        positional_args, subcommand_args, optional_args = [], [], []
        for field_name, field_info in model.model_fields.items():
            if _CliSubCommand in field_info.metadata:
                if not field_info.is_required():
                    raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has a default value')
                else:
                    field_types = [type_ for type_ in get_args(field_info.annotation) if type_ is not type(None)]
                    if len(field_types) != 1:
                        raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has multiple types')
                    elif not is_model_class(field_types[0]):
                        raise SettingsError(
                            f'subcommand argument {model.__name__}.{field_name} is not derived from BaseModel'
                        )
                subcommand_args.append((field_name, field_info))
            elif _CliPositionalArg in field_info.metadata:
                if not field_info.is_required():
                    raise SettingsError(f'positional argument {model.__name__}.{field_name} has a default value')
                positional_args.append((field_name, field_info))
            else:
                optional_args.append((field_name, field_info))
        return positional_args + subcommand_args + optional_args

    def _add_fields_to_parser(
        self,
        parser: ArgumentParser,
        model: type[BaseModel],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        group: _ArgumentGroup | None,
    ) -> ArgumentParser:
        subparsers: _SubParsersAction[Any] | None = None
        for field_name, field_info in self._sort_arg_fields(model):
            sub_models: list[type[BaseModel]] = self._get_sub_models(model, field_name, field_info)
            if _CliSubCommand in field_info.metadata:
                if subparsers is None:
                    subparsers = parser.add_subparsers(
                        title='subcommands', dest=f'{arg_prefix}:subcommand', required=self.cli_enforce_required
                    )
                    self._cli_subcommands[f'{arg_prefix}:subcommand'] = [f'{arg_prefix}{field_name}']
                else:
                    self._cli_subcommands[f'{arg_prefix}:subcommand'].append(f'{arg_prefix}{field_name}')
                metavar = ','.join(self._cli_subcommands[f'{arg_prefix}:subcommand'])
                subparsers.metavar = f'{{{metavar}}}'

                model = sub_models[0]
                self._add_fields_to_parser(
                    subparsers.add_parser(
                        field_name,
                        help=field_info.description,
                        formatter_class=parser.formatter_class,
                        description=model.__doc__,
                    ),
                    model,
                    added_args=[],
                    arg_prefix=f'{arg_prefix}{field_name}.',
                    subcommand_prefix=f'{subcommand_prefix}{field_name}.',
                    group=None,
                )
            else:
                arg_flag: str = '--'
                kwargs: dict[str, Any] = {}
                kwargs['default'] = SUPPRESS
                kwargs['help'] = field_info.description
                kwargs['dest'] = f'{arg_prefix}{field_name}'
                kwargs['metavar'] = self._metavar_format(field_info.annotation)
                kwargs['required'] = self.cli_enforce_required and field_info.is_required()
                if kwargs['dest'] in added_args:
                    continue
                if _annotation_contains_types(field_info.annotation, (list, set, dict, Sequence, Mapping)):
                    kwargs['action'] = 'append'
                    if _annotation_contains_types(field_info.annotation, (dict, Mapping)):
                        self._cli_dict_arg_names.append(kwargs['dest'])

                arg_name = f'{arg_prefix.replace(subcommand_prefix, "", 1)}{field_name}'
                if _CliPositionalArg in field_info.metadata:
                    kwargs['metavar'] = field_name.upper()
                    arg_name = kwargs['dest']
                    del kwargs['dest']
                    del kwargs['required']
                    arg_flag = ''

                if sub_models and kwargs.get('action') != 'append':
                    group_help_text = (
                        sub_models[0].__doc__
                        if self.cli_use_class_docs_for_groups and len(sub_models) == 1
                        else field_info.description
                    )
                    model_group = parser.add_argument_group(f'{arg_name} options', group_help_text)
                    if not self.cli_avoid_json:
                        added_args.append(arg_name)
                        kwargs['help'] = f'set {arg_name} from JSON string'
                        model_group.add_argument(f'{arg_flag}{arg_name}', **kwargs)
                    for model in sub_models:
                        self._add_fields_to_parser(
                            parser,
                            model,
                            added_args=added_args,
                            arg_prefix=f'{arg_prefix}{field_name}.',
                            subcommand_prefix=subcommand_prefix,
                            group=model_group,
                        )
                elif group is not None:
                    added_args.append(arg_name)
                    group.add_argument(f'{arg_flag}{arg_name}', **kwargs)
                else:
                    added_args.append(arg_name)
                    parser.add_argument(f'{arg_flag}{arg_name}', **kwargs)
        return parser

    def _get_modified_args(self, obj: Any) -> tuple[str, ...]:
        if not self.cli_hide_none_type:
            return get_args(obj)
        else:
            return tuple([type_ for type_ in get_args(obj) if type_ is not type(None)])

    def _metavar_format_list(self, args: list[str]) -> str:
        args = args if 'JSON' not in args else [arg for arg in args[args.index('JSON') + 1 :] if arg != 'JSON']
        return ','.join(args)

    def _metavar_format(self, obj: Any) -> str:
        """Pretty metavar representation of a type. Adapts logic from `pydantic._repr.display_as_type`."""
        if isinstance(obj, FunctionType):
            return obj.__name__
        elif obj is ...:
            return '...'
        elif isinstance(obj, Representation):
            return repr(obj)
        elif isinstance(obj, typing_extensions.TypeAliasType):
            return str(obj)

        if not isinstance(obj, (typing_base, WithArgsTypes, type)):
            obj = obj.__class__

        if origin_is_union(get_origin(obj)):
            args = self._metavar_format_list(list(map(self._metavar_format, self._get_modified_args(obj))))
            return f'{{{args}}}' if ',' in args else args
        elif isinstance(obj, WithArgsTypes):
            if get_origin(obj) == Literal:
                args = self._metavar_format_list(list(map(repr, self._get_modified_args(obj))))
                return f'{{{args}}}' if ',' in args else args
            else:
                args = self._metavar_format_list(list(map(self._metavar_format, self._get_modified_args(obj))))
            try:
                return f'{obj.__qualname__}[{args}]'
            except AttributeError:
                return str(obj)  # handles TypeAliasType in 3.12
        elif obj is type(None):
            return self.env_parse_none_str
        elif is_model_class(obj):
            return 'JSON'
        elif isinstance(obj, type):
            return obj.__qualname__
        else:
            return repr(obj).replace('typing.', '').replace('typing_extensions.', '')


def _get_env_var_key(key: str, case_sensitive: bool = False) -> str:
    return key if case_sensitive else key.lower()


def _parse_env_none_str(value: str | None, parse_none_str: str | None = None) -> str | None | EnvNoneType:
    return value if not (value == parse_none_str and parse_none_str is not None) else EnvNoneType(value)


def parse_env_vars(
    env_vars: Mapping[str, str | None],
    case_sensitive: bool = False,
    ignore_empty: bool = False,
    parse_none_str: str | None = None,
) -> Mapping[str, str | None]:
    return {
        _get_env_var_key(k, case_sensitive): _parse_env_none_str(v, parse_none_str)
        for k, v in env_vars.items()
        if not (ignore_empty and v == '')
    }


def read_env_file(
    file_path: Path,
    *,
    encoding: str | None = None,
    case_sensitive: bool = False,
    ignore_empty: bool = False,
    parse_none_str: str | None = None,
) -> Mapping[str, str | None]:
    file_vars: dict[str, str | None] = dotenv_values(file_path, encoding=encoding or 'utf8')
    return parse_env_vars(file_vars, case_sensitive, ignore_empty, parse_none_str)


def _annotation_is_complex(annotation: type[Any] | None, metadata: list[Any]) -> bool:
    if any(isinstance(md, Json) for md in metadata):  # type: ignore[misc]
        return False
    origin = get_origin(annotation)
    return (
        _annotation_is_complex_inner(annotation)
        or _annotation_is_complex_inner(origin)
        or hasattr(origin, '__pydantic_core_schema__')
        or hasattr(origin, '__get_pydantic_core_schema__')
    )


def _annotation_is_complex_inner(annotation: type[Any] | None) -> bool:
    if lenient_issubclass(annotation, (str, bytes)):
        return False

    return lenient_issubclass(annotation, (BaseModel, Mapping, Sequence, tuple, set, frozenset, deque)) or is_dataclass(
        annotation
    )


def _union_is_complex(annotation: type[Any] | None, metadata: list[Any]) -> bool:
    return any(_annotation_is_complex(arg, metadata) for arg in get_args(annotation))


def _annotation_contains_types(annotation: type[Any] | None, types: tuple[Any, ...]) -> bool:
    if get_origin(annotation) in types:
        return True
    for type_ in get_args(annotation):
        if _annotation_contains_types(type_, types):
            return True
    return annotation in types
