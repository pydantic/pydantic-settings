from typing import TYPE_CHECKING, Mapping

from pydantic_settings import BaseSettings, EnvSettingsSource

if TYPE_CHECKING:
    import keyring
else:
    keyring = None

def import_keyring():
    global keyring
    if keyring is not None:
        return
    try:
        import keyring

        return
    except ImportError as e:
        raise ImportError("Keyring is not installed, run `pip install keyring`") from e


class KeyringConfigSettingsSource(EnvSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        keyring_service: str,
        case_sensitive: bool | None = True,
        env_prefix: str | None = None,
    ):
        self.keyring_service = keyring_service
        super().__init__(
            settings_cls, case_sensitive=case_sensitive, env_prefix=env_prefix
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        import_keyring()

        env_vars = {}
        for field in self.settings_cls.model_fields.keys():
            credential = keyring.get_credential(
                self.keyring_service, self.env_prefix + field
            )
            if credential is not None:
                key = credential.username
                key = key if self.case_sensitive else key.lower()
                env_vars[key] = credential.password

        return env_vars

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(keyring_service={self.keyring_service})"


__all__ = [
    "KeyringConfigSettingsSource",
]
