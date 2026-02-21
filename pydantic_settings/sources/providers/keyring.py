from __future__ import annotations as _annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..utils import parse_env_vars
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


keyring: Any = None


def import_keyring() -> None:
    global keyring

    try:
        import keyring
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'keyring is not installed, run `pip install pydantic-settings[keyring]` '
            'or `uv add "pydantic-settings[keyring]"`'
        ) from e


class KeyringSettingsSource(EnvSettingsSource):
    _service_name: str

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        service_name: str | None = None,
        case_sensitive: bool | None = True,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
    ) -> None:
        if keyring is None:
            import_keyring()

        service_name = (
            service_name if service_name is not None else settings_cls.model_config.get('keyring_service_name')
        )
        if not service_name:
            raise ValueError(
                '`service_name` is required for KeyringSettingsSource. '
                'Pass it directly or set `keyring_service_name` in model_config.'
            )

        self._service_name = service_name

        super().__init__(
            settings_cls,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        keyring_values: dict[str, str | None] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            for _, env_name, _ in self._extract_field_info(field, field_name):
                if env_name in keyring_values:
                    continue
                keyring_values[env_name] = keyring.get_password(self._service_name, env_name)

        return parse_env_vars(keyring_values, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(service_name={self._service_name!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r})'
        )


__all__ = ['KeyringSettingsSource', 'import_keyring']
