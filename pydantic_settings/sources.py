from __future__ import annotations as _annotations

import json
import os
import warnings
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Mapping, Sequence, Tuple, Union, cast, Literal

from pydantic import AliasChoices, AliasPath, BaseModel, Json, ConfigDict
from pydantic._internal._typing_extra import origin_is_union
from pydantic._internal._utils import deep_update, lenient_issubclass
from pydantic.fields import FieldInfo
from typing_extensions import get_args, get_origin

from pydantic_settings.utils import path_type_label

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


DotenvType = Union[Path, str, List[Union[Path, str]], Tuple[Union[Path, str], ...]]

# This is used as default value for `_env_file` in the `BaseSettings` class and
# `env_file` in `DotEnvSettingsSource` so the default can be distinguished from `None`.
# See the docstring of `BaseSettings` for more details.
ENV_FILE_SENTINEL: DotenvType = Path('')


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
        return self.init_kwargs

    def __repr__(self) -> str:
        return f'InitSettingsSource(init_kwargs={self.init_kwargs!r})'


class PydanticBaseEnvSettingsSource(PydanticBaseSettingsSource):
    class __SourceConfig(ConfigDict):
        case_sensitive: bool
        env_prefix: str

    def __init__(
        self, settings_cls: type[BaseSettings], case_sensitive: bool | None = None, env_prefix: str | None = None
    ) -> None:
        super().__init__(settings_cls)
        self.source_config = self.__init_source_config(case_sensitive=case_sensitive, env_prefix=env_prefix)

    def __init_source_config(
        self, *, case_sensitive: bool | None = None, env_prefix: str | None = None
    ) -> Self.__SourceConfig:
        case_sensitive = case_sensitive if case_sensitive is not None else self.config.get('case_sensitive', False)
        env_prefix = env_prefix if env_prefix is not None else self.config.get('env_prefix', '')
        return self.__SourceConfig(env_prefix=env_prefix, case_sensitive=case_sensitive)

    def load_env_vars(self) -> Mapping[str, Any]:
        raise NotImplementedError()

    @classmethod
    def prepare_field_value_from_env_vars(
        cls,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
        env_vars: Mapping[str, Any],
        config: Self.__SourceConfig,
    ) -> Any:
        raise NotImplementedError()

    @classmethod
    def read_model_fields(
        cls, model_fields: Mapping[str, Any], env_vars: Mapping[str, str | None], config: Self.__SourceConfig
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field_name, field in model_fields.items():
            try:
                field_value, field_key, value_is_complex = cls.get_field_value_from_env_vars(
                    field, field_name, env_vars, config
                )
            except Exception as e:
                raise SettingsError(f'error getting value for field "{field_name}" from source "{cls.__name__}"') from e

            try:
                field_value = cls.prepare_field_value_from_env_vars(
                    field_name, field, field_value, value_is_complex, env_vars, config
                )
            except ValueError as e:
                raise SettingsError(f'error parsing value for field "{field_name}" from source "{cls.__name__}"') from e

            if field_value is not None:
                if (
                    not config["case_sensitive"]
                    and lenient_issubclass(field.annotation, BaseModel)
                    and isinstance(field_value, dict)
                ):
                    data[field_key] = cls._replace_field_names_case_insensitively(field, field_value)
                else:
                    data[field_key] = field_value
        return data

    @classmethod
    def get_field_value_from_env_vars(
        cls, field: FieldInfo, field_name: str, env_vars: Mapping[str, Any], config: Self.__SourceConfig
    ) -> tuple[Any, str, bool]:
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
        for field_key, env_name, value_is_complex in cls._extract_field_info(field, field_name, config):
            env_val = env_vars.get(env_name)
            if env_val is not None:
                break

        return env_val, field_key, value_is_complex

    @classmethod
    def _replace_field_names_case_insensitively(cls, field: FieldInfo, field_values: dict[str, Any]) -> dict[str, Any]:
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
                values[sub_model_field_name] = cls._replace_field_names_case_insensitively(sub_model_field, value)
            else:
                values[sub_model_field_name] = value

        return values

    @classmethod
    def _extract_field_info(
        cls, field: FieldInfo, field_name: str, config: Self.__SourceConfig
    ) -> list[tuple[Any, str, bool]]:
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
                        field_info.append(
                            (alias, cls._apply_case_sensitive(alias, config), True if len(alias) > 1 else False)
                        )
                    elif isinstance(alias, list):  # AliasChoices
                        first_arg = cast(str, alias[0])  # first item of an AliasChoices must be a str
                        field_info.append(
                            (first_arg, cls._apply_case_sensitive(first_arg, config), True if len(alias) > 1 else False)
                        )
            else:  # string validation alias
                field_info.append((v_alias, cls._apply_case_sensitive(v_alias, config), False))
        else:
            field_info.append((field_name, cls._apply_case_sensitive(config["env_prefix"] + field_name, config), False))

        return field_info

    def field_is_complex(self, field: FieldInfo) -> bool:
        return self._field_is_complex(field)

    @classmethod
    def _field_is_complex(cls, field: FieldInfo) -> bool:
        """
        Checks whether a field is complex, in which case it will attempt to be parsed as JSON.

        Args:
            field: The field.

        Returns:
            Whether the field is complex.
        """
        return _annotation_is_complex(field.annotation, field.metadata)

    @staticmethod
    def _apply_case_sensitive(value: str, config: Self.__SourceConfig) -> str:
        return value.lower() if not config["case_sensitive"] else value

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        return self._decode_complex_value(field_name, field, value)

    @classmethod
    def _decode_complex_value(cls, field_name: str, field: FieldInfo, value: Any) -> Any:
        return json.loads(value)

    def __call__(self) -> dict[str, Any]:
        model_fields = self.settings_cls.model_fields
        data: dict[str, Any] = self.read_model_fields(model_fields, self.load_env_vars(), self.source_config)
        return data


class SecretsSettingsSource(PydanticBaseEnvSettingsSource):
    """
    Source class for loading settings values from secret files.
    """

    class __SourceConfig(ConfigDict):
        secrets_dir: str | Path | None
        case_sensitive: bool
        env_prefix: str

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        secrets_dir: str | Path | None = None,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
    ) -> None:
        super().__init__(settings_cls, case_sensitive, env_prefix)
        self.source_config = self.__init_source_config(
            secrets_dir=secrets_dir, case_sensitive=case_sensitive, env_prefix=env_prefix
        )
        self.__env_vars_cache: Any = None
        self.env_vars = self.__load_env_vars()

    def __init_source_config(
        self,
        *,
        secrets_dir: str | Path | None = None,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
    ) -> Self.__SourceConfig:
        secrets_dir = secrets_dir if secrets_dir is not None else self.config.get('secrets_dir')
        case_sensitive = (
            case_sensitive if case_sensitive is not None else self.source_config.get("case_sensitive", False)
        )
        env_prefix = env_prefix if env_prefix is not None else self.source_config.get("env_prefix", "")
        return self.__SourceConfig(secrets_dir=secrets_dir, env_prefix=env_prefix, case_sensitive=case_sensitive)

    def load_env_vars(self) -> dict[str, Path]:
        return self.__load_env_vars()

    def __load_env_vars(self) -> dict[str, Path]:
        if self.__env_vars_cache is not None:
            return self.__env_vars_cache
        if self.source_config["secrets_dir"] is None:
            self.__env_vars_cache = {}
            return {}
        secrets_path = Path(self.source_config["secrets_dir"]).expanduser()
        if not secrets_path.exists():
            warnings.warn(f'directory "{secrets_path}" does not exist')
            self.__env_vars_cache = {}
            return {}
        if not secrets_path.is_dir():
            raise SettingsError(f'secrets_dir must reference a directory, not a {path_type_label(secrets_path)}')
        res: dict[str, Path] = {}
        if self.source_config["secrets_dir"] is None:
            self.__env_vars_cache = {}
            return res
        for f in secrets_path.iterdir():
            fname = self._apply_case_sensitive(f.name, self.source_config)
            res[fname] = f
        self.__env_vars_cache = res
        return res

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

        path, field_key, value_is_complex = self.get_field_value_from_env_vars(
            field, field_name, self.env_vars, self.source_config
        )
        if path is None:
            return None, field_key, value_is_complex
        return path.read_text().strip(), field_key, value_is_complex

    @classmethod
    def get_field_value_from_env_vars(
        cls, field: FieldInfo, field_name: str, env_vars: Mapping[str, Path], config: Self.__SourceConfig
    ) -> tuple[Any, str, bool]:
        """
        Gets the value for field from environment variables and a flag to determine whether value is complex.

        Args:
            field: The field.
            field_name: The field name.

        Returns:
            A tuple contains the key, value if the file exists otherwise `None`, and
                a flag to determine whether value is complex.
        """

        env_val: Path | None = None
        for field_key, env_name, value_is_complex in cls._extract_field_info(field, field_name, config):
            env_val = env_vars.get(env_name)
            if env_val is None:
                continue
            if env_val.is_file():
                payload = env_val.read_text().strip()
                return payload, field_key, value_is_complex
            else:
                warnings.warn(
                    f'attempted to load secret file "{env_val}" but found a {path_type_label(env_val)} instead.',
                    stacklevel=4,
                )

        return None, field_key, value_is_complex

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        self.prepare_field_value_from_env_vars(
            field_name,
            field,
            value,
            value_is_complex,
            self.env_vars,
            self.source_config,
        )

    @classmethod
    def prepare_field_value_from_env_vars(
        cls,
        field_name: str,
        field: FieldInfo,
        value: str | None,
        value_is_complex: bool,
        env_vars: Mapping[str, Path | None],
        config: Self.__SourceConfig,
    ) -> Any:
        if value is None:
            return value
        if cls._field_is_complex(field) or value_is_complex:
            return cls._decode_complex_value(field_name, field, value)
        return value

    def __repr__(self) -> str:
        return f'SecretsSettingsSource(secrets_dir={self.source_config["secrets_dir"]!r})'


class EnvSettingsSource(PydanticBaseEnvSettingsSource):
    """
    Source class for loading settings values from environment variables.
    """

    class __SourceConfig(ConfigDict):
        case_sensitive: bool
        env_prefix: str
        env_nested_delimiter: str | None

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = None,
    ) -> None:
        super().__init__(settings_cls, case_sensitive, env_prefix)
        self.source_config = self.__init_source_config(
            case_sensitive=case_sensitive, env_prefix=env_prefix, env_nested_delimiter=env_nested_delimiter
        )
        self.__env_vars_cache: Any = None
        self.env_vars = self.__load_env_vars()

    def __init_source_config(
        self, *, case_sensitive: bool | None = None, env_prefix: str | None = None, env_nested_delimiter: str | None
    ) -> Self.__SourceConfig:
        env_nested_delimiter = (
            env_nested_delimiter if env_nested_delimiter is not None else self.config.get('env_nested_delimiter')
        )
        case_sensitive = (
            case_sensitive if case_sensitive is not None else self.source_config.get('case_sensitive', False)
        )
        env_prefix = env_prefix if env_prefix is not None else self.source_config.get('env_prefix', '')
        return self.__SourceConfig(
            env_nested_delimiter=env_nested_delimiter, env_prefix=env_prefix, case_sensitive=case_sensitive
        )

    def load_env_vars(self) -> dict[str, str | None]:
        return self.__load_env_vars()

    def __load_env_vars(self) -> dict[str, str | None]:
        if self.__env_vars_cache is not None:
            return self.__env_vars_cache
        res: dict[str, str | None] = {}
        res = {self._apply_case_sensitive(k, self.source_config): v for k, v in os.environ.items()}
        self.__env_vars_cache = res
        return res

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self.get_field_value_from_env_vars(field, field_name, self.env_vars, self.source_config)

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        self.prepare_field_value_from_env_vars(
            field_name,
            field,
            value,
            value_is_complex,
            self.env_vars,
            self.source_config,
        )

    @classmethod
    def prepare_field_value_from_env_vars(
        cls,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
        env_vars: Mapping[str, str | Any],
        config: Self.__SourceConfig,
    ) -> Any:
        is_complex, allow_parse_failure = cls._field_is_complex_with_failflag(field)
        if is_complex or value_is_complex:
            if value is None:
                # field is complex but no value found so far, try explode_env_vars
                env_val_built = cls.explode_env_vars(field_name, field, env_vars, config)
                if env_val_built:
                    return env_val_built
            else:
                # field is complex and there's a value, decode that as JSON, then add explode_env_vars
                try:
                    value = cls._decode_complex_value(field_name, field, value)
                except ValueError as e:
                    if not allow_parse_failure:
                        raise e

                if isinstance(value, dict):
                    return deep_update(
                        value,
                        cls.explode_env_vars(field_name, field, env_vars, config),
                    )
                else:
                    return value
        elif value is not None:
            # simplest case, field is not complex, we only need to add the value if it was found
            return value

    @classmethod
    def explode_env_vars(
        cls,
        field_name: str,
        field: FieldInfo,
        env_vars: Mapping[str, str | None],
        config: Self.__SourceConfig,
    ) -> dict[str, Any]:
        """
        Process env_vars and extract the values of keys containing env_nested_delimiter into nested dictionaries.

        This is applied to a single field, hence filtering by env_var prefix.

        Args:
            field_name: The field name.
            field: The field.
            env_vars: Environment variables.

        Returns:
            A dictionaty contains extracted values from nested env values.
        """
        prefixes = [
            f'{env_name}{config["env_nested_delimiter"]}'
            for _, env_name, _ in cls._extract_field_info(field, field_name, config)
        ]
        result: dict[str, Any] = {}
        for env_name, env_val in env_vars.items():
            if not any(env_name.startswith(prefix) for prefix in prefixes):
                continue
            # we remove the prefix before splitting in case the prefix has characters in common with the delimiter
            env_name_without_prefix = env_name[len(config["env_prefix"]) :]
            _, *keys, last_key = env_name_without_prefix.split(config["env_nested_delimiter"])
            env_var = result
            target_field: FieldInfo | None = field
            for key in keys:
                target_field = cls.next_field(target_field, key)
                env_var = env_var.setdefault(key, {})

            # get proper field with last_key
            target_field = cls.next_field(target_field, last_key)

            # check if env_val maps to a complex field and if so, parse the env_val
            if target_field and env_val:
                is_complex, allow_json_failure = cls._field_is_complex_with_failflag(target_field)
                if is_complex:
                    try:
                        env_val = cls._decode_complex_value(last_key, target_field, env_val)
                    except ValueError as e:
                        if not allow_json_failure:
                            raise e
            env_var[last_key] = env_val

        return result

    @staticmethod
    def next_field(field: FieldInfo | None, key: str) -> FieldInfo | None:
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
        if not field or origin_is_union(get_origin(field.annotation)):
            # no support for Unions of complex BaseSettings fields
            return None
        elif field.annotation and hasattr(field.annotation, 'model_fields') and field.annotation.model_fields.get(key):
            return field.annotation.model_fields[key]

        return None

    @classmethod
    def _union_is_complex(cls, annotation: type[Any] | None, metadata: list[Any]) -> bool:
        return any(_annotation_is_complex(arg, metadata) for arg in get_args(annotation))

    @classmethod
    def _field_is_complex_with_failflag(cls, field: FieldInfo) -> tuple[bool, bool]:
        """
        Find out if a field is complex, and if so whether JSON errors should be ignored
        """
        if cls._field_is_complex(field):
            allow_parse_failure = False
        elif origin_is_union(get_origin(field.annotation)) and cls._union_is_complex(field.annotation, field.metadata):
            allow_parse_failure = True
        else:
            return False, False

        return True, allow_parse_failure

    def __repr__(self) -> str:
        return (
            f'EnvSettingsSource(env_nested_delimiter={self.source_config["env_nested_delimiter"]!r}, '
            f'env_prefix_len={len(self.source_config["env_prefix"])!r})'
        )


class DotEnvSettingsSource(EnvSettingsSource):
    """
    Source class for loading settings values from env files.
    """

    class __SourceConfig(ConfigDict):
        case_sensitive: bool
        env_prefix: str
        env_nested_delimiter: str | None
        env_file: DotenvType | None
        env_file_encoding: str | None

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_file: DotenvType | None = ENV_FILE_SENTINEL,
        env_file_encoding: str | None = None,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = None,
        extra: Literal["allow", "ignore", "forbid"] | None = None,
    ) -> None:
        super().__init__(settings_cls, case_sensitive, env_prefix, env_nested_delimiter)
        self.source_config = self.__init_source_config(
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_file=env_file,
            env_file_encoding=env_file_encoding,
            extra=extra,
        )
        self.__env_vars_cache = None
        self.env_vars = self.load_env_vars()

    def __init_source_config(
        self,
        *,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None,
        env_file: DotenvType | None,
        env_file_encoding: str | None,
        extra: Literal["allow", "ignore", "forbid"] | None,
    ) -> Self.__SourceConfig:
        env_nested_delimiter = (
            env_nested_delimiter if env_nested_delimiter is not None else self.source_config["env_nested_delimiter"]
        )
        case_sensitive = case_sensitive if case_sensitive is not None else self.source_config["case_sensitive"]
        env_prefix = env_prefix if env_prefix is not None else self.source_config["env_prefix"]
        env_file = env_file if env_file != ENV_FILE_SENTINEL else self.config.get('env_file')
        extra = extra if extra is not None else self.config.get('extra', 'forbid')
        env_file_encoding = env_file_encoding if env_file_encoding is not None else self.config.get('env_file_encoding')
        return self.__SourceConfig(
            env_nested_delimiter=env_nested_delimiter,
            env_prefix=env_prefix,
            case_sensitive=case_sensitive,
            env_file=env_file,
            env_file_encoding=env_file_encoding,
            extra=extra,
        )

    def load_env_vars(self) -> dict[str, str | None]:
        return self.__load_env_vars()

    def __load_env_vars(self) -> dict[str, str | None]:
        if self.__env_vars_cache is not None:
            return self.__env_vars_cache
        res = self._read_env_files(self.source_config["case_sensitive"])
        self.__env_vars_cache = res
        return res

    def _read_env_files(self, case_sensitive: bool) -> dict[str, str | None]:
        env_files = self.source_config["env_file"]
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
                        env_path, encoding=self.source_config["env_file_encoding"], case_sensitive=case_sensitive
                    )
                )

        return dotenv_vars

    @classmethod
    def read_model_fields(
        cls, model_fields: Mapping[str, Any], env_vars: Mapping[str, str | None], config: Self.__SourceConfig
    ) -> dict[str, Any]:
        data: dict[str, Any] = super().read_model_fields(model_fields, env_vars, config)

        if config["extra"] == "ignore":
            return data

        data_lower_keys: list[str] = []
        if not config["case_sensitive"]:
            data_lower_keys = [x.lower() for x in data.keys()]

        # As `extra` config is allowed in dotenv settings source, We have to
        # update data with extra env variabels from dotenv file.
        for env_name, env_value in env_vars.items():
            if env_name.startswith(config["env_prefix"]) and env_value is not None:
                env_name_without_prefix = env_name[len(config["env_prefix"]) :]
                first_key, *_ = env_name_without_prefix.split(config["env_nested_delimiter"])

                if (data_lower_keys and first_key not in data_lower_keys) or (
                    not data_lower_keys and first_key not in data
                ):
                    data[first_key] = env_value
        return data

    def __repr__(self) -> str:
        return (
            f'DotEnvSettingsSource(env_file={self.source_config["env_file"]!r}, env_file_encoding={self.source_config["env_file_encoding"]!r}, '
            f'env_nested_delimiter={self.source_config["env_nested_delimiter"]!r}, env_prefix_len={len(self.source_config["env_prefix"])!r})'
        )


def read_env_file(
    file_path: Path, *, encoding: str | None = None, case_sensitive: bool = False
) -> Mapping[str, str | None]:
    try:
        from dotenv import dotenv_values
    except ImportError as e:
        raise ImportError('python-dotenv is not installed, run `pip install pydantic[dotenv]`') from e

    file_vars: dict[str, str | None] = dotenv_values(file_path, encoding=encoding or 'utf8')
    if not case_sensitive:
        return {k.lower(): v for k, v in file_vars.items()}
    else:
        return file_vars


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
