from __future__ import annotations as _annotations

from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple, Type, Union

from pydantic import ConfigDict
from pydantic._internal._config import config_keys
from pydantic._internal._utils import deep_update
from pydantic.main import BaseModel

from .sources import (
    ENV_FILE_SENTINEL,
    DotEnvSettingsSource,
    DotenvType,
    EnvSettingsSource,
    InitSettingsSource,
    PathType,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
)


class SettingsConfigDict(ConfigDict, total=False):
    case_sensitive: bool
    env_prefix: str
    env_file: Optional[DotenvType]
    env_file_encoding: Optional[str]
    env_ignore_empty: bool
    env_nested_delimiter: Optional[str]
    env_parse_none_str: Optional[str]
    env_parse_enums: Optional[bool]
    secrets_dir: Optional[Union[str, Path]]
    json_file: Optional[PathType]
    json_file_encoding: Optional[str]
    yaml_file: Optional[PathType]
    yaml_file_encoding: Optional[str]
    pyproject_toml_depth: int
    """
    Number of levels **up** from the current working directory to attempt to find a pyproject.toml
    file.

    This is only used when a pyproject.toml file is not found in the current working directory.
    """

    pyproject_toml_table_header: Tuple[str, ...]
    """
    Header of the TOML table within a pyproject.toml file to use when filling variables.
    This is supplied as a `Tuple[str, ...]` instead of a `str` to accommodate for headers
    containing a `.`.

    For example, `toml_table_header = ("tool", "my.tool", "foo")` can be used to fill variable
    values from a table with header `[tool."my.tool".foo]`.

    To use the root table, exclude this config setting or provide an empty tuple.
    """

    toml_file: Optional[PathType]


# Extend `config_keys` by pydantic settings config keys to
# support setting config through class kwargs.
# Pydantic uses `config_keys` in `pydantic._internal._config.ConfigWrapper.for_model`
# to extract config keys from model kwargs, So, by adding pydantic settings keys to
# `config_keys`, they will be considered as valid config keys and will be collected
# by Pydantic.
config_keys |= set(SettingsConfigDict.__annotations__.keys())


class BaseSettings(BaseModel):
    """
    Base class for settings, allowing values to be overridden by environment variables.

    This is useful in production for secrets you do not wish to save in code, it plays nicely with docker(-compose),
    Heroku and any 12 factor app design.

    All the below attributes can be set via `model_config`.

    Args:
        _case_sensitive: Whether environment variables names should be read with case-sensitivity. Defaults to `None`.
        _env_prefix: Prefix for all environment variables. Defaults to `None`.
        _env_file: The env file(s) to load settings values from. Defaults to `Path('')`, which
            means that the value from `model_config['env_file']` should be used. You can also pass
            `None` to indicate that environment variables should not be loaded from an env file.
        _env_file_encoding: The env file encoding, e.g. `'latin-1'`. Defaults to `None`.
        _env_ignore_empty: Ignore environment variables where the value is an empty string. Default to `False`.
        _env_nested_delimiter: The nested env values delimiter. Defaults to `None`.
        _env_parse_none_str: The env string value that should be parsed (e.g. "null", "void", "None", etc.)
            into `None` type(None). Defaults to `None` type(None), which means no parsing should occur.
        _env_parse_enums: Parse enum field names to values. Defaults to `None.`, which means no parsing should occur.
        _secrets_dir: The secret files directory. Defaults to `None`.
    """

    def __init__(
        __pydantic_self__,
        _case_sensitive: Optional[bool] = None,
        _env_prefix: Optional[str] = None,
        _env_file: Optional[DotenvType] = ENV_FILE_SENTINEL,
        _env_file_encoding: Optional[str] = None,
        _env_ignore_empty: Optional[bool] = None,
        _env_nested_delimiter: Optional[str] = None,
        _env_parse_none_str: Optional[str] = None,
        _env_parse_enums: Optional[bool] = None,
        _secrets_dir: Optional[Union[str, Path]] = None,
        **values: Any,
    ) -> None:
        # Uses something other than `self` the first arg to allow "self" as a settable attribute
        super().__init__(
            **__pydantic_self__._settings_build_values(
                values,
                _case_sensitive=_case_sensitive,
                _env_prefix=_env_prefix,
                _env_file=_env_file,
                _env_file_encoding=_env_file_encoding,
                _env_ignore_empty=_env_ignore_empty,
                _env_nested_delimiter=_env_nested_delimiter,
                _env_parse_none_str=_env_parse_none_str,
                _env_parse_enums=_env_parse_enums,
                _secrets_dir=_secrets_dir,
            )
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """
        Define the sources and their order for loading the settings values.

        Args:
            settings_cls: The Settings class.
            init_settings: The `InitSettingsSource` instance.
            env_settings: The `EnvSettingsSource` instance.
            dotenv_settings: The `DotEnvSettingsSource` instance.
            file_secret_settings: The `SecretsSettingsSource` instance.

        Returns:
            A tuple containing the sources and their order for loading the settings values.
        """
        return init_settings, env_settings, dotenv_settings, file_secret_settings

    def _settings_build_values(
        self,
        init_kwargs: Dict[str, Any],
        _case_sensitive: Optional[bool] = None,
        _env_prefix: Optional[str] = None,
        _env_file: Optional[DotenvType] = None,
        _env_file_encoding: Optional[str] = None,
        _env_ignore_empty: Optional[bool] = None,
        _env_nested_delimiter: Optional[str] = None,
        _env_parse_none_str: Optional[str] = None,
        _env_parse_enums: Optional[bool] = None,
        _secrets_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        # Determine settings config values
        case_sensitive = _case_sensitive if _case_sensitive is not None else self.model_config.get('case_sensitive')
        env_prefix = _env_prefix if _env_prefix is not None else self.model_config.get('env_prefix')
        env_file = _env_file if _env_file != ENV_FILE_SENTINEL else self.model_config.get('env_file')
        env_file_encoding = (
            _env_file_encoding if _env_file_encoding is not None else self.model_config.get('env_file_encoding')
        )
        env_ignore_empty = (
            _env_ignore_empty if _env_ignore_empty is not None else self.model_config.get('env_ignore_empty')
        )
        env_nested_delimiter = (
            _env_nested_delimiter
            if _env_nested_delimiter is not None
            else self.model_config.get('env_nested_delimiter')
        )
        env_parse_none_str = (
            _env_parse_none_str if _env_parse_none_str is not None else self.model_config.get('env_parse_none_str')
        )
        env_parse_enums = _env_parse_enums if _env_parse_enums is not None else self.model_config.get('env_parse_enums')
        secrets_dir = _secrets_dir if _secrets_dir is not None else self.model_config.get('secrets_dir')

        # Configure built-in sources
        init_settings = InitSettingsSource(self.__class__, init_kwargs=init_kwargs)
        env_settings = EnvSettingsSource(
            self.__class__,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_ignore_empty=env_ignore_empty,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )
        dotenv_settings = DotEnvSettingsSource(
            self.__class__,
            env_file=env_file,
            env_file_encoding=env_file_encoding,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_ignore_empty=env_ignore_empty,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

        file_secret_settings = SecretsSettingsSource(
            self.__class__, secrets_dir=secrets_dir, case_sensitive=case_sensitive, env_prefix=env_prefix
        )
        # Provide a hook to set built-in sources priority and add / remove sources
        sources = self.settings_customise_sources(
            self.__class__,
            init_settings=init_settings,
            env_settings=env_settings,
            dotenv_settings=dotenv_settings,
            file_secret_settings=file_secret_settings,
        )
        if sources:
            return deep_update(*reversed([source() for source in sources]))
        else:
            # no one should mean to do this, but I think returning an empty dict is marginally preferable
            # to an informative error and much better than a confusing error
            return {}

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        extra='forbid',
        arbitrary_types_allowed=True,
        validate_default=True,
        case_sensitive=False,
        env_prefix='',
        env_file=None,
        env_file_encoding=None,
        env_ignore_empty=False,
        env_nested_delimiter=None,
        env_parse_none_str=None,
        env_parse_enums=None,
        json_file=None,
        json_file_encoding=None,
        yaml_file=None,
        yaml_file_encoding=None,
        toml_file=None,
        secrets_dir=None,
        protected_namespaces=('model_', 'settings_'),
    )
