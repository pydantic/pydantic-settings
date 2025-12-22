from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, EnvSettingsSource

if TYPE_CHECKING:
    import keyring
else:
    keyring = None


def import_keyring() -> None:
    global keyring
    if keyring is not None:
        return
    try:
        import keyring

        return
    except ImportError as e:
        raise ImportError('Keyring is not installed, run `pip install keyring`') from e


class KeyringConfigSettingsSource(EnvSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        keyring_service: str,
        case_sensitive: bool | None = None,
        env_prefix: str | None = None,
    ):
        self.keyring_service = keyring_service if case_sensitive else keyring_service.lower()
        super().__init__(settings_cls, case_sensitive=case_sensitive, env_prefix=env_prefix)

    def _load_env_vars(self) -> Mapping[str, str | None]:
        import_keyring()

        prefix = self.env_prefix
        if not self.case_sensitive:
            prefix = self.env_prefix.lower()
        env_vars: dict[str, str | None] = {}
        for field in self.settings_cls.model_fields.keys():
            if not self.case_sensitive:
                field = field.lower()
            credential = keyring.get_credential(self.keyring_service, prefix + field)
            if credential is not None:
                key = credential.username
                if not self.case_sensitive:
                    key = key.lower()
                env_vars[key] = credential.password

        return env_vars

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(keyring_service={self.keyring_service})'


__all__ = [
    'KeyringConfigSettingsSource',
]
