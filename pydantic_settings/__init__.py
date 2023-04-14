import warnings

from .main import BaseSettings
from .sources import (
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
)
from .version import VERSION

__all__ = (
    'BaseSettings',
    'PydanticBaseSettingsSource',
    'InitSettingsSource',
    'SecretsSettingsSource',
    'EnvSettingsSource',
    'DotEnvSettingsSource',
)

__version__ = VERSION
warnings.warn(
    'This is a placeholder until pydantic-settings is released, see https://github.com/pydantic/pydantic/pull/4492'
)
