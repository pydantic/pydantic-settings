from __future__ import annotations as _annotations

from pathlib import Path
from typing import Any

from pydantic import ConfigDict
from pydantic._internal._utils import deep_update
from pydantic.main import BaseModel

from .sources import (
    DotEnvSettingsSource,
    DotenvType,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
)

env_file_sentinel: DotenvType = Path('')


class SettingsConfigDict(ConfigDict):
    case_sensitive: bool
    env_prefix: str
    env_file: DotenvType | None
    env_file_encoding: str | None
    env_nested_delimiter: str | None
    secrets_dir: str | Path | None


class BaseSettings(BaseModel):
    """
    Base class for settings, allowing values to be overridden by environment variables.

    This is useful in production for secrets you do not wish to save in code, it plays nicely with docker(-compose),
    Heroku and any 12 factor app design.
    """

    def __init__(
        __pydantic_self__,
        _env_file: DotenvType | None = env_file_sentinel,
        _env_file_encoding: str | None = None,
        _env_nested_delimiter: str | None = None,
        _secrets_dir: str | Path | None = None,
        **values: Any,
    ) -> None:
        # Uses something other than `self` the first arg to allow "self" as a settable attribute
        super().__init__(
            **__pydantic_self__._settings_build_values(
                values,
                _env_file=_env_file,
                _env_file_encoding=_env_file_encoding,
                _env_nested_delimiter=_env_nested_delimiter,
                _secrets_dir=_secrets_dir,
            )
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, dotenv_settings, file_secret_settings

    def _settings_build_values(
        self,
        init_kwargs: dict[str, Any],
        _env_file: DotenvType | None = None,
        _env_file_encoding: str | None = None,
        _env_nested_delimiter: str | None = None,
        _secrets_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        # Configure built-in sources
        init_settings = InitSettingsSource(self.__class__, init_kwargs=init_kwargs)
        env_settings = EnvSettingsSource(
            self.__class__,
            env_nested_delimiter=(
                _env_nested_delimiter
                if _env_nested_delimiter is not None
                else self.model_config.get('env_nested_delimiter')
            ),
            env_prefix_len=len(self.model_config.get('env_prefix', '')),
        )
        dotenv_settings = DotEnvSettingsSource(
            self.__class__,
            env_file=(_env_file if _env_file != env_file_sentinel else self.model_config.get('env_file')),
            env_file_encoding=(
                _env_file_encoding if _env_file_encoding is not None else self.model_config.get('env_file_encoding')
            ),
            env_nested_delimiter=(
                _env_nested_delimiter
                if _env_nested_delimiter is not None
                else self.model_config.get('env_nested_delimiter')
            ),
            env_prefix_len=len(self.model_config.get('env_prefix', '')),
        )

        file_secret_settings = SecretsSettingsSource(
            self.__class__, secrets_dir=_secrets_dir or self.model_config.get('secrets_dir')
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

    model_config = SettingsConfigDict(
        extra='forbid',
        arbitrary_types_allowed=True,
        validate_default=True,
        case_sensitive=False,
        env_prefix='',
        env_file=None,
        env_file_encoding=None,
        env_nested_delimiter=None,
        secrets_dir=None,
    )
