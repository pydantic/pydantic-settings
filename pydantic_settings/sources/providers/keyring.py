from __future__ import annotations as _annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic_settings.exceptions import SettingsError

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
        case_sensitive: bool | None = None,
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

    def _raw_env_name_from_field_key(self, field_key: str, field_name: str) -> str:
        if field_key == field_name:
            env_prefix = self.env_prefix if self.env_prefix_target in ('variable', 'all') else ''
        else:
            env_prefix = self.env_prefix if self.env_prefix_target in ('alias', 'all') else ''
        return f'{env_prefix}{field_key}'

    def _load_env_vars(self) -> Mapping[str, str | None]:
        keyring_values: dict[str, str | None] = {}
        password_cache: dict[str, str | None] = {}

        def _get_password(username: str) -> str | None:
            if username not in password_cache:
                password_cache[username] = keyring.get_password(self._service_name, username)
            return password_cache[username]

        for field_name, field in self.settings_cls.model_fields.items():
            for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
                if env_name in keyring_values:
                    continue

                raw_env_name = self._raw_env_name_from_field_key(field_key, field_name)
                raw_value = _get_password(raw_env_name)
                normalized_value = raw_value if raw_env_name == env_name else _get_password(env_name)

                if (
                    raw_env_name != env_name
                    and raw_value is not None
                    and normalized_value is not None
                    and raw_value != normalized_value
                ):
                    # Fail fast for ambiguity: two different keyring usernames map to the same resolved settings key.
                    raise SettingsError(
                        f'Ambiguous keyring values for field {field_name!r}: '
                        f'{raw_env_name!r} and {env_name!r} both exist with different values'
                    )

                selected_value = (
                    normalized_value if value_is_complex else (raw_value if raw_value is not None else normalized_value)
                )
                keyring_values[env_name] = selected_value

        return parse_env_vars(keyring_values, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(service_name={self._service_name!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r})'
        )


__all__ = ['KeyringSettingsSource', 'import_keyring']
