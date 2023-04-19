from __future__ import annotations as _annotations

from typing import Any, Dict, Optional, Tuple, Type

from pydantic import ConfigDict, DirectoryPath, FilePath
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

env_file_sentinel: DotenvType = FilePath('')


class BaseSettings(BaseModel):
    """
    Base class for settings, allowing values to be overridden by environment variables.

    This is useful in production for secrets you do not wish to save in code, it plays nicely with docker(-compose),
    Heroku and any 12 factor app design.
    """

    def __init__(
        __pydantic_self__,
        _env_file: Optional[DotenvType] = env_file_sentinel,
        _env_file_encoding: Optional[str] = None,
        _env_nested_delimiter: Optional[str] = None,
        _secrets_dir: Optional[DirectoryPath] = None,
        **values: Any,
    ) -> None:
        # Uses something other than `self` the first arg to allow "self" as a settable attribute
        super().__init__(
            **__pydantic_self__._build_values(
                values,
                _env_file=_env_file,
                _env_file_encoding=_env_file_encoding,
                _env_nested_delimiter=_env_nested_delimiter,
                _secrets_dir=_secrets_dir,
            )
        )

    @classmethod
    def customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, dotenv_settings, file_secret_settings

    def _build_values(
        self,
        init_kwargs: Dict[str, Any],
        _env_file: Optional[DotenvType] = None,
        _env_file_encoding: Optional[str] = None,
        _env_nested_delimiter: Optional[str] = None,
        _secrets_dir: Optional[DirectoryPath] = None,
    ) -> Dict[str, Any]:
        # Configure built-in sources
        init_settings = InitSettingsSource(self.__class__, init_kwargs=init_kwargs)
        env_settings = EnvSettingsSource(
            self.__class__,
            env_nested_delimiter=(
                _env_nested_delimiter
                if _env_nested_delimiter is not None
                else self.model_config.get('env_nested_delimiter')
            ),
            env_prefix_len=len(self.model_config.get('env_prefix')),
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
            env_prefix_len=len(self.model_config.get('env_prefix')),
        )

        file_secret_settings = SecretsSettingsSource(
            self.__class__, secrets_dir=_secrets_dir or self.model_config.get('secrets_dir')
        )
        # Provide a hook to set built-in sources priority and add / remove sources
        sources = self.customise_sources(
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

    model_config = ConfigDict(  # type: ignore[typeddict-item]
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
