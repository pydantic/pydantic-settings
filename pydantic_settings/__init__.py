import warnings
from .version import VERSION

__version__ = VERSION
warnings.warn(
    'This is a placeholder until pydantic-settings is released, '
    'see https://github.com/pydantic/pydantic/pull/4492'
)
