"""JSON file settings source."""

from __future__ import annotations as _annotations

import json
from typing import (
    TYPE_CHECKING,
    Any,
)

from ..base import ConfigFileSourceMixin, InitSettingsSource
from ..types import DEFAULT_PATH, ConfigFileSourceType
from ..utils import InitState

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_settings.main import BaseSettings

    from ..types import Traversable


class JsonConfigSettingsSource(InitSettingsSource, ConfigFileSourceMixin):
    """
    A source class that loads variables from a JSON file
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        json_file: ConfigFileSourceType | None = DEFAULT_PATH,
        json_file_encoding: str | None = None,
        deep_merge: bool = False,
        _init_state: InitState | None = None,
    ):
        self.json_file_path = json_file if json_file != DEFAULT_PATH else settings_cls.model_config.get('json_file')
        self.json_file_encoding = (
            json_file_encoding
            if json_file_encoding is not None
            else settings_cls.model_config.get('json_file_encoding')
        )
        self.json_data = self._read_files(self.json_file_path, deep_merge=deep_merge)
        super().__init__(settings_cls, self.json_data, _init_state=_init_state)

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        # Default to UTF-8 rather than the locale encoding, matching `DotEnvSettingsSource`
        # and `SecretsSettingsSource`: RFC 8259 mandates UTF-8 for interchanged JSON, and
        # the locale default corrupts (or fails to decode) it on a non-UTF-8 Windows code page.
        encoding = self.json_file_encoding if self.json_file_encoding is not None else 'utf-8'
        with file_path.open(encoding=encoding) as json_file:
            content = json_file.read()
        # An empty (or whitespace-only) file is not valid JSON; treat it as an empty
        # mapping so it falls back to defaults, mirroring `YamlConfigSettingsSource`'s
        # `yaml.safe_load(...) or {}` (and `tomllib`, which returns `{}` for an empty file).
        return json.loads(content) if content.strip() else {}

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(json_file={self.json_file_path})'


__all__ = ['JsonConfigSettingsSource']
