from __future__ import annotations as _annotations

import json
import os
import warnings
from abc import ABC, abstractmethod
from dataclasses import is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple, Type, Union

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
        def _annotation_is_complex(annotation: type[Any] | None) -> bool:
            return lenient_issubclass(annotation, (BaseModel, list, set, frozenset, dict)) or is_dataclass(annotation)

        return _annotation_is_complex(field.annotation) or _annotation_is_complex(get_origin(field.annotation))

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
                field_info.append(
                    (v_alias, self._apply_case_sensitive(self.config.get('env_prefix', '') + v_alias), False)
                )
        else:
            field_info.append(
                (field_name, self._apply_case_sensitive(self.config.get('env_prefix', '') + field_name), False)
            )

        return field_info

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
            for key in keys:
                env_var = env_var.setdefault(key, {})
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
