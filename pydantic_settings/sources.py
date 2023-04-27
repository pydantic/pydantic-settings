from __future__ import annotations as _annotations

import json
import os
import warnings
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple, Type, Union

from pydantic import BaseModel
from pydantic._internal._typing_extra import origin_is_union
from pydantic._internal._utils import deep_update, lenient_issubclass
from pydantic.fields import FieldInfo
from typing_extensions import get_origin

from pydantic_settings.utils import path_type_label

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


DotenvType = Union[Path, List[Path], Tuple[Path, ...]]


class SettingsError(ValueError):
    pass


class PydanticBaseSettingsSource(ABC):
    """
    Abstract base class for settings sources, every settings source classes should inherit from it.
    """

    def __init__(self, settings_cls: Type[BaseSettings]):
        self.settings_cls = settings_cls
        self.config = settings_cls.model_config

    @abstractmethod
    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        """
        Gets the value, the key for model creation, and a flag to determine whether value is complex.

        This is an abstract method that should be overrided in every settings source classes.

        Args:
            field (FieldInfo): The field.
            field_name (str): The field name.

        Returns:
            Tuple[str, Any, bool]: The key, value and a flag to determine whether value is complex.
        """
        pass

    def field_is_complex(self, field: FieldInfo) -> bool:
        """
        Checks whether a field is complex, in which case it will attempt to be parsed as JSON.

        Args:
            field (FieldInfo): The field.

        Returns:
            bool: Whether the field is complex.
        """
        return _annotation_is_complex(field.annotation)

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        """
        Prepares the value of a field.

        Args:
            field_name (str): The field name.
            field (FieldInfo): The field.
            value (Any): The value of the field that has to be prepared.
            value_is_complex: A flag to determine whether value is complex.

        Returns:
            Any: The prepared value.
        """
        if self.field_is_complex(field) or value_is_complex:
            return json.loads(value)
        return value

    @abstractmethod
    def __call__(self) -> Dict[str, Any]:
        pass


class InitSettingsSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: Type[BaseSettings], init_kwargs: Dict[str, Any]):
        self.init_kwargs = init_kwargs
        super().__init__(settings_cls)

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        pass

    def __call__(self) -> Dict[str, Any]:
        return self.init_kwargs

    def __repr__(self) -> str:
        return f'InitSettingsSource(init_kwargs={self.init_kwargs!r})'


class PydanticBaseEnvSettingsSource(PydanticBaseSettingsSource):
    def _apply_case_sensitive(self, value: str) -> str:
        return value.lower() if not self.config.get('case_sensitive') else value

    def _extract_field_info(self, field: FieldInfo, field_name: str) -> List[Tuple[str, str, bool]]:
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
            List[Tuple[str, str, bool]]: List of tuples, each tuple contanis field_key, env_name, and value_is_complex.
        """
        field_info: List[Tuple[str, str, bool]] = []
        v_alias = field.validation_alias

        if v_alias:
            if isinstance(v_alias, list):  # AliasChoices, AliasPath
                for alias in v_alias:
                    if isinstance(alias, str):  # AliasPath
                        field_info.append((alias, self._apply_case_sensitive(alias), True if len(alias) > 1 else False))
                    elif isinstance(alias, list):  # AliasChoices
                        field_info.append(
                            (alias[0], self._apply_case_sensitive(alias[0]), True if len(alias) > 1 else False)
                        )
            else:  # string validation alias
                field_info.append((v_alias, self._apply_case_sensitive(v_alias), False))
        else:
            field_info.append(
                (field_name, self._apply_case_sensitive(self.config.get('env_prefix', '') + field_name), False)
            )

        return field_info

    def _replace_field_names_case_insensitively(self, field: FieldInfo, field_values: Dict[str, Any]) -> Dict[str, Any]:
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

                model_config = ConfigDict(env_nested_delimiter='__')
            ```

        Then:
            _replace_field_names_case_insensitively(
                field,
                {"val1": "v1", "sub_SUB": {"VAL2": "v2", "sub_SUB_sUb": {"vAl3": "v3"}}}
            )
            Returns {'VAL1': 'v1', 'SUB_sub': {'Val2': 'v2', 'SUB_sub_SuB': {'VaL3': 'v3'}}}
        """
        values: Dict[str, Any] = {}

        for name, value in field_values.items():
            sub_model_field: Optional[FieldInfo] = None

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

            if lenient_issubclass(sub_model_field.annotation, BaseModel):
                values[sub_model_field_name] = self._replace_field_names_case_insensitively(sub_model_field, value)
            else:
                values[sub_model_field_name] = value

        return values

    def __call__(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

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
                if not self.config.get('case_sensitive', False) and lenient_issubclass(field.annotation, BaseModel):
                    d[field_key] = self._replace_field_names_case_insensitively(field, field_value)
                else:
                    d[field_key] = field_value

        return d


class SecretsSettingsSource(PydanticBaseEnvSettingsSource):
    def __init__(self, settings_cls: Type[BaseSettings], secrets_dir: Optional[Union[str, Path]]):
        self.secrets_dir = secrets_dir
        super().__init__(settings_cls)

    def __call__(self) -> Dict[str, Any]:
        """
        Build fields from "secrets" files.
        """
        secrets: Dict[str, Optional[str]] = {}

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
    def find_case_path(cls, dir_path: Path, file_name: str, case_sensitive: bool) -> Optional[Path]:
        """
        Find a file within path's directory matching filename, optionally ignoring case.
        """
        for f in dir_path.iterdir():
            if f.name == file_name:
                return f
            elif not case_sensitive and f.name.lower() == file_name.lower():
                return f
        return None

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
            path = self.find_case_path(
                self.secrets_path, env_name, self.settings_cls.model_config.get('case_sensitive', False)
            )
            if not path:
                # path does not exist, we curently don't return a warning for this
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
    def __init__(
        self,
        settings_cls: Type[BaseSettings],
        env_nested_delimiter: Optional[str] = None,
        env_prefix_len: int = 0,
    ):
        super().__init__(settings_cls)

        self.env_nested_delimiter: Optional[str] = env_nested_delimiter
        self.env_prefix_len: int = env_prefix_len

        self.env_vars: Mapping[str, Optional[str]] = self._load_env_vars()

    def _load_env_vars(self) -> Mapping[str, Optional[str]]:
        if self.settings_cls.model_config.get('case_sensitive'):
            return os.environ
        return {k.lower(): v for k, v in os.environ.items()}

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        env_val: Optional[str] = None
        for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
            env_val = self.env_vars.get(env_name)
            if env_val is not None:
                break

        return env_val, field_key, value_is_complex

    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        is_complex, allow_parse_failure = self._field_is_complex(field)
        if is_complex or value_is_complex:
            if value is None:
                # field is complex but no value found so far, try explode_env_vars
                env_val_built = self.explode_env_vars(field_name, field, self.env_vars)
                if env_val_built:
                    return env_val_built
            else:
                # field is complex and there's a value, decode that as JSON, then add explode_env_vars
                try:
                    value = json.loads(value)
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

    def _field_is_complex(self, field: FieldInfo) -> Tuple[bool, bool]:
        """
        Find out if a field is complex, and if so whether JSON errors should be ignored
        """
        if self.field_is_complex(field):
            allow_parse_failure = False
        elif origin_is_union(get_origin(field.annotation)):
            allow_parse_failure = True
        else:
            return False, False

        return True, allow_parse_failure

    @staticmethod
    def next_field(field: Optional[FieldInfo], key: str) -> Optional[FieldInfo]:
        """
        Find the field in a sub model by key(env name)

        By having the following models:

            ```py
            class SubSubModel(BaseSettings):
                dvals: Dict

            class SubModel(BaseSettings):
                vals: List[str]
                sub_sub_model: SubSubModel

            class Cfg(BaseSettings):
                sub_model: SubModel
            ```

        Then:
            next_field(sub_model, 'vals') Returns the `vals` field of `SubModel` class
            next_field(sub_model, 'sub_sub_model') Returns `sub_sub_model` field of `SubModel` class
        """
        if not field or origin_is_union(get_origin(field.annotation)):
            # no support for Unions of complex BaseSettings fields
            return None
        elif field.annotation and hasattr(field.annotation, 'model_fields') and field.annotation.model_fields.get(key):
            return field.annotation.model_fields[key]

        return None

    def explode_env_vars(
        self, field_name: str, field: FieldInfo, env_vars: Mapping[str, Optional[str]]
    ) -> Dict[str, Any]:
        """
        Process env_vars and extract the values of keys containing env_nested_delimiter into nested dictionaries.

        This is applied to a single field, hence filtering by env_var prefix.
        """
        prefixes = [
            f'{env_name}{self.env_nested_delimiter}' for _, env_name, _ in self._extract_field_info(field, field_name)
        ]
        result: Dict[str, Any] = {}
        for env_name, env_val in env_vars.items():
            if not any(env_name.startswith(prefix) for prefix in prefixes):
                continue
            # we remove the prefix before splitting in case the prefix has characters in common with the delimiter
            env_name_without_prefix = env_name[self.env_prefix_len :]
            _, *keys, last_key = env_name_without_prefix.split(self.env_nested_delimiter)
            env_var = result
            target_field: Optional[FieldInfo] = field

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
                        env_val = json.loads(env_val)
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
    def __init__(
        self,
        settings_cls: Type[BaseSettings],
        env_file: Optional[DotenvType],
        env_file_encoding: Optional[str],
        env_nested_delimiter: Optional[str] = None,
        env_prefix_len: int = 0,
    ):
        self.env_file: Optional[DotenvType] = env_file
        self.env_file_encoding: Optional[str] = env_file_encoding

        super().__init__(settings_cls, env_nested_delimiter, env_prefix_len)

    def _load_env_vars(self) -> Mapping[str, Optional[str]]:
        env_vars = super()._load_env_vars()
        dotenv_vars = self._read_env_files(self.settings_cls.model_config.get('case_sensitive', False))
        if dotenv_vars:
            env_vars = {**dotenv_vars, **env_vars}

        return env_vars

    def _read_env_files(self, case_sensitive: bool) -> Mapping[str, Optional[str]]:
        env_files = self.env_file
        if env_files is None:
            return {}

        if isinstance(env_files, (str, os.PathLike)):
            env_files = [env_files]

        dotenv_vars = {}
        for env_file in env_files:
            env_path = Path(env_file).expanduser()
            if env_path.is_file():
                dotenv_vars.update(
                    read_env_file(env_path, encoding=self.env_file_encoding, case_sensitive=case_sensitive)
                )

        return dotenv_vars

    def __repr__(self) -> str:
        return (
            f'DotEnvSettingsSource(env_file={self.env_file!r}, env_file_encoding={self.env_file_encoding!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r}, env_prefix_len={self.env_prefix_len!r})'
        )


def read_env_file(file_path: Path, *, encoding: str = None, case_sensitive: bool = False) -> Dict[str, Optional[str]]:
    try:
        from dotenv import dotenv_values
    except ImportError as e:
        raise ImportError('python-dotenv is not installed, run `pip install pydantic[dotenv]`') from e

    file_vars: Dict[str, Optional[str]] = dotenv_values(file_path, encoding=encoding or 'utf8')
    if not case_sensitive:
        return {k.lower(): v for k, v in file_vars.items()}
    else:
        return file_vars


def find_case_path(dir_path: Path, file_name: str, case_sensitive: bool) -> Optional[Path]:
    """
    Find a file within path's directory matching filename, optionally ignoring case.
    """
    for f in dir_path.iterdir():
        if f.name == file_name:
            return f
        elif not case_sensitive and f.name.lower() == file_name.lower():
            return f
    return None


def _annotation_is_complex(annotation: type[Any] | None) -> bool:
    origin = get_origin(annotation)
    return (
        _annotation_is_complex_inner(annotation)
        or _annotation_is_complex_inner(origin)
        or hasattr(origin, '__pydantic_core_schema__')
        or hasattr(origin, '__get_pydantic_core_schema__')
    )


def _annotation_is_complex_inner(annotation: type[Any] | None) -> bool:
    if lenient_issubclass(annotation, str):
        return False

    return lenient_issubclass(annotation, (BaseModel, Mapping, Sequence, tuple, set, frozenset, deque)) or is_dataclass(
        annotation
    )
