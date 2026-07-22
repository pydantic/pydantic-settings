"""YAML file settings source."""

from __future__ import annotations as _annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

from ..base import ConfigFileSourceMixin, InitSettingsSource
from ..types import DEFAULT_PATH, ConfigFileSourceType
from ..utils import InitState

if TYPE_CHECKING:
    from pathlib import Path

    import yaml

    from pydantic_settings.main import BaseSettings

    from ..types import Traversable
else:
    yaml = None


def import_yaml() -> None:
    global yaml
    if yaml is not None:
        return
    try:
        import yaml
    except ImportError as e:
        raise ImportError('PyYAML is not installed, run `pip install pydantic-settings[yaml]`') from e


class YamlConfigSettingsSource(InitSettingsSource, ConfigFileSourceMixin):
    """
    A source class that loads variables from a yaml file
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: ConfigFileSourceType | None = DEFAULT_PATH,
        yaml_file_encoding: str | None = None,
        yaml_config_section: str | None = None,
        deep_merge: bool = False,
        _init_state: InitState | None = None,
    ):
        self.yaml_file_path = yaml_file if yaml_file != DEFAULT_PATH else settings_cls.model_config.get('yaml_file')
        self.yaml_file_encoding = (
            yaml_file_encoding
            if yaml_file_encoding is not None
            else settings_cls.model_config.get('yaml_file_encoding')
        )
        self.yaml_config_section = (
            yaml_config_section
            if yaml_config_section is not None
            else settings_cls.model_config.get('yaml_config_section')
        )
        self.yaml_data = self._read_files(self.yaml_file_path, deep_merge=deep_merge)

        if self.yaml_config_section is not None:
            section_data = self._traverse_nested_section(
                self.yaml_data, self.yaml_config_section, self.yaml_config_section
            )
            # An empty section (`section:` with no children) parses to `None`; treat it as an
            # empty mapping so it falls back to defaults, mirroring `_read_file`'s `or {}` for
            # an empty whole file. A non-mapping section (e.g. a scalar) is a user error, so
            # raise a clear message instead of letting `InitSettingsSource` choke on `.keys()`.
            if section_data is None:
                section_data = {}
            elif not isinstance(section_data, dict):
                raise TypeError(
                    f'yaml_config_section "{self.yaml_config_section}" in {self.yaml_file_path} '
                    f'must be a mapping, got {type(section_data).__name__}.'
                )
            self.yaml_data = section_data
        super().__init__(settings_cls, self.yaml_data, _init_state=_init_state)

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        import_yaml()
        with file_path.open(encoding=self.yaml_file_encoding) as yaml_file:
            return yaml.safe_load(yaml_file) or {}

    def _traverse_nested_section(
        self, data: dict[str, Any], section_path: str, original_path: str | None = None
    ) -> dict[str, Any]:
        """
        Traverse nested YAML sections using dot-notation path.

        This method tries to match the longest possible key first before splitting on dots,
        allowing access to YAML keys that contain literal dot characters.

        For example, with section_path="a.b.c", it will try:
        1. "a.b.c" as a literal key
        2. "a.b" as a key, then traverse to "c"
        3. "a" as a key, then traverse to "b.c"
        4. "a" as a key, then "b" as a key, then "c" as a key
        """
        # Track the original path for error messages
        if original_path is None:
            original_path = section_path

        # Only reject truly empty paths
        if not section_path:
            raise ValueError('yaml_config_section cannot be empty')

        # Try the full path as a literal key first (even with leading/trailing/consecutive dots)
        try:
            return data[section_path]
        except KeyError:
            pass  # Not a literal key, try splitting
        except TypeError:
            raise TypeError(
                f'yaml_config_section path "{original_path}" cannot be traversed in {self.yaml_file_path}. '
                f'An intermediate value is not a dictionary.'
            )

        # If path contains no dots, we already tried it as a literal key above
        if '.' not in section_path:
            raise KeyError(f'yaml_config_section key "{original_path}" not found in {self.yaml_file_path}')

        # Try progressively shorter prefixes (greedy left-to-right approach)
        parts = section_path.split('.')
        for i in range(len(parts) - 1, 0, -1):
            prefix = '.'.join(parts[:i])
            suffix = '.'.join(parts[i:])

            if prefix in data:
                # Found the prefix as a literal key, now recursively traverse the suffix
                try:
                    return self._traverse_nested_section(data[prefix], suffix, original_path)
                except TypeError:
                    raise TypeError(
                        f'yaml_config_section path "{original_path}" cannot be traversed in {self.yaml_file_path}. '
                        f'An intermediate value is not a dictionary.'
                    )

        # If we get here, no match was found
        raise KeyError(f'yaml_config_section key "{original_path}" not found in {self.yaml_file_path}')

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(yaml_file={self.yaml_file_path})'


__all__ = ['YamlConfigSettingsSource']
