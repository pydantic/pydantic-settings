"""Azure Key Vault settings source."""

from __future__ import annotations as _annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Optional

from .env import EnvSettingsSource

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets import SecretClient

    from pydantic_settings.main import BaseSettings
else:
    TokenCredential = None
    ResourceNotFoundError = None
    SecretClient = None


def import_azure_key_vault() -> None:
    global TokenCredential
    global SecretClient
    global ResourceNotFoundError

    try:
        from azure.core.credentials import TokenCredential
        from azure.core.exceptions import ResourceNotFoundError
        from azure.keyvault.secrets import SecretClient
    except ImportError as e:
        raise ImportError(
            'Azure Key Vault dependencies are not installed, run `pip install pydantic-settings[azure-key-vault]`'
        ) from e


class AzureKeyVaultMapping(Mapping[str, Optional[str]]):
    _loaded_secrets: dict[str, str | None]
    _secret_client: SecretClient
    _secret_names: list[str]

    def __init__(
        self,
        secret_client: SecretClient,
    ) -> None:
        self._loaded_secrets = {}
        self._secret_client = secret_client
        self._secret_names: list[str] = [
            secret.name for secret in self._secret_client.list_properties_of_secrets() if secret.name and secret.enabled
        ]

    def __getitem__(self, key: str) -> str | None:
        if key not in self._loaded_secrets:
            try:
                self._loaded_secrets[key] = self._secret_client.get_secret(key).value
            except Exception:
                raise KeyError(key)

        return self._loaded_secrets[key]

    def __len__(self) -> int:
        return len(self._secret_names)

    def __iter__(self) -> Iterator[str]:
        return iter(self._secret_names)


class AzureKeyVaultSettingsSource(EnvSettingsSource):
    _url: str
    _credential: TokenCredential

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        url: str,
        credential: TokenCredential,
        env_prefix: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
    ) -> None:
        import_azure_key_vault()
        self._url = url
        self._credential = credential
        super().__init__(
            settings_cls,
            case_sensitive=True,
            env_prefix=env_prefix,
            env_nested_delimiter='--',
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

    def _load_env_vars(self) -> Mapping[str, Optional[str]]:
        secret_client = SecretClient(vault_url=self._url, credential=self._credential)
        return AzureKeyVaultMapping(secret_client)

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(url={self._url!r}, env_nested_delimiter={self.env_nested_delimiter!r})'


__all__ = ['AzureKeyVaultMapping', 'AzureKeyVaultSettingsSource']
