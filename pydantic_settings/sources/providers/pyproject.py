"""Pyproject TOML file settings source."""

from __future__ import annotations as _annotations

from itertools import islice
from pathlib import Path
from typing import (
    TYPE_CHECKING,
)

from ..utils import InitState
from .toml import TomlConfigSettingsSource

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


class PyprojectTomlConfigSettingsSource(TomlConfigSettingsSource):
    """
    A source class that loads variables from a `pyproject.toml` file.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        toml_file: Path | None = None,
        _init_state: InitState | None = None,
    ) -> None:
        self.toml_file_path = self._pick_pyproject_toml_file(
            toml_file, settings_cls.model_config.get('pyproject_toml_depth', 0)
        )
        self.toml_table_header: tuple[str, ...] = settings_cls.model_config.get(
            'pyproject_toml_table_header', ('tool', 'pydantic-settings')
        )
        self.toml_data = self._read_files(self.toml_file_path)
        for key in self.toml_table_header:
            self.toml_data = self.toml_data.get(key, {})
        super(TomlConfigSettingsSource, self).__init__(settings_cls, self.toml_data, _init_state=_init_state)

    @staticmethod
    def _pick_pyproject_toml_file(provided: Path | None, depth: int) -> Path:
        """Pick a `pyproject.toml` file path to use.

        Args:
            provided: Explicit path provided when instantiating this class.
            depth: Number of directories up the tree to check for a pyproject.toml.

        """
        if provided:
            return provided.expanduser().resolve()
        rv = Path.cwd() / 'pyproject.toml'
        if not rv.is_file():
            for parent in islice(rv.parent.parents, max(depth, 0)):
                candidate = parent / 'pyproject.toml'
                if candidate.is_file():
                    return candidate
        return rv


__all__ = ['PyprojectTomlConfigSettingsSource']
