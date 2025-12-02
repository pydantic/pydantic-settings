"""Lazy loading support for settings sources."""

from __future__ import annotations as _annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from pydantic.fields import FieldInfo

from ..exceptions import SettingsError
from .utils import _get_alias_names

if TYPE_CHECKING:
    from .base import PydanticBaseEnvSettingsSource


class LazyMapping(Mapping[str, Any]):
    """Dict-like mapping that defers field value resolution until keys are accessed."""

    def __init__(self, source: PydanticBaseEnvSettingsSource) -> None:
        """Initialize with a source instance that will compute values on demand."""
        self._source = source
        self._cached_values: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        """Get a field value, computing it lazily on first access."""
        # Return cached value if available
        if key in self._cached_values:
            return self._cached_values[key]

        # Find the field in the settings class
        field_name: str | None = None
        field_info: FieldInfo | None = None

        for fname, finfo in self._source.settings_cls.model_fields.items():
            alias_names, *_ = _get_alias_names(fname, finfo)
            if key in alias_names or key == fname:
                field_name = fname
                field_info = finfo
                break

        if field_name is None or field_info is None:
            raise KeyError(key)

        # Resolve and cache the field value
        try:
            field_value, _, value_is_complex = self._source._get_resolved_field_value(field_info, field_name)
            prepared_value = self._source.prepare_field_value(field_name, field_info, field_value, value_is_complex)
            self._cached_values[key] = prepared_value
            return prepared_value
        except Exception as e:
            raise SettingsError(
                f'error getting value for field "{field_name}" from source "{self._source.__class__.__name__}"'
            ) from e

    def __iter__(self) -> Iterator[str]:
        """Iterate over all possible field keys."""
        seen: set[str] = set()
        for field_name, field_info in self._source.settings_cls.model_fields.items():
            alias_names, *_ = _get_alias_names(field_name, field_info)
            for alias in alias_names:
                if alias not in seen:
                    seen.add(alias)
                    yield alias
            if field_name not in seen:
                yield field_name

    def __len__(self) -> int:
        """Return the count of fields in the settings class."""
        return len(self._source.settings_cls.model_fields)

    def copy(self) -> LazyMapping:
        """Return a copy to preserve lazy behavior through Pydantic's deep_update()."""
        new_mapping = LazyMapping(self._source)
        new_mapping._cached_values = self._cached_values.copy()
        return new_mapping


__all__ = ['LazyMapping']
