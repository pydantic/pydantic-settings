"""TOML file settings source."""

from __future__ import annotations as _annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from ..base import ConfigFileSourceMixin, InitSettingsSource
from ..types import DEFAULT_PATH, ConfigFileSourceType
from ..utils import InitState

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings

    from ..types import Traversable

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        tomllib = None
    import tomli
else:
    tomllib = None
    tomli = None


def import_toml() -> None:
    global tomli
    global tomllib
    if sys.version_info < (3, 11):
        if tomli is not None:
            return
        try:
            import tomli
        except ImportError as e:  # pragma: no cover
            raise ImportError('tomli is not installed, run `pip install pydantic-settings[toml]`') from e
    else:
        if tomllib is not None:
            return
        import tomllib


class TomlConfigSettingsSource(InitSettingsSource, ConfigFileSourceMixin):
    """
    A source class that loads variables from a TOML file
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        toml_file: ConfigFileSourceType | None = DEFAULT_PATH,
        toml_table_header: tuple[str, ...] = (),
        deep_merge: bool = False,
        _init_state: InitState | None = None,
    ):
        self.toml_file_path = toml_file if toml_file != DEFAULT_PATH else settings_cls.model_config.get('toml_file')
        self.toml_table_header = (
            toml_table_header if toml_table_header else settings_cls.model_config.get('toml_table_header', ())
        )
        self.toml_data = self._read_files(self.toml_file_path, deep_merge=deep_merge)

        if self._any_file_exists(self.toml_file_path):
            for key in self.toml_table_header:
                if key not in self.toml_data:
                    raise KeyError(f'toml_table_header key "{key}" not found in {self.toml_file_path}')
                self.toml_data = self.toml_data[key]

        super().__init__(settings_cls, self.toml_data, _init_state=_init_state)

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        import_toml()
        with file_path.open(mode='rb') as toml_file:
            if sys.version_info < (3, 11):
                return tomli.load(toml_file)
            return tomllib.load(toml_file)

    @staticmethod
    def _any_file_exists(paths: ConfigFileSourceType | None) -> bool:
        """Check if any of the given file paths exist."""
        if paths is None:
            return False
        if isinstance(paths, str) or not isinstance(paths, Sequence):
            paths = [paths]

        def _exists(path: Path | str | Traversable) -> bool:
            if isinstance(path, (str, Path)):
                return Path(path).exists()
            # Non-`Path` `Traversable` (e.g. a resource inside a zip/wheel) is not
            # `os.PathLike`, so it can't be wrapped in `Path`; query it directly.
            return path.is_file()

        return any(_exists(path) for path in paths)

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(toml_file={self.toml_file_path}, toml_table_header={self.toml_table_header})'
