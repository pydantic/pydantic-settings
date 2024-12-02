"""
Test pydantic_settings.AzureKeyVaultSettingsSource.
"""

from typing import Tuple, Type

import pytest
from pydantic import BaseModel, Field
from pytest_mock import MockerFixture

from pydantic_settings import (
    AzureKeyVaultSettingsSource,
    BaseSettings,
    PydanticBaseSettingsSource,
)
from pydantic_settings.sources import import_azure_key_vault

try:
    azure_key_vault = True
    import_azure_key_vault()
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import KeyVaultSecret, SecretProperties
except ImportError:
    azure_key_vault = False


MODULE = 'pydantic_settings.sources'


@pytest.mark.skipif(not azure_key_vault, reason='pydantic-settings[azure-key-vault] is not installed')
class TestAzureKeyVaultSettingsSource:
    """Test AzureKeyVaultSettingsSource."""

    def test___init__(self, mocker: MockerFixture) -> None:
        """Test __init__."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

        mocker.patch(f'{MODULE}.SecretClient.list_properties_of_secrets', return_value=[])

        AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

    def test___call__(self, mocker: MockerFixture) -> None:
        """Test __call__."""

        class SqlServer(BaseModel):
            password: str = Field(..., alias='Password')

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            SqlServerUser: str
            sql_server_user: str = Field(..., alias='SqlServerUser')
            sql_server: SqlServer = Field(..., alias='SqlServer')

        expected_secrets = [type('', (), {'name': 'SqlServerUser'}), type('', (), {'name': 'SqlServer--Password'})]
        expected_secret_value = 'SecretValue'
        mocker.patch(f'{MODULE}.SecretClient.list_properties_of_secrets', return_value=expected_secrets)
        mocker.patch(
            f'{MODULE}.SecretClient.get_secret',
            side_effect=self._raise_resource_not_found_when_getting_parent_secret_name,
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

        settings = obj()

        assert settings['SqlServerUser'] == expected_secret_value
        assert settings['SqlServer']['Password'] == expected_secret_value

    def test_azure_key_vault_settings_source(self, mocker: MockerFixture) -> None:
        """Test AzureKeyVaultSettingsSource."""

        class SqlServer(BaseModel):
            password: str = Field(..., alias='Password')

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            SqlServerUser: str
            sql_server_user: str = Field(..., alias='SqlServerUser')
            sql_server: SqlServer = Field(..., alias='SqlServer')

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: Type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> Tuple[PydanticBaseSettingsSource, ...]:
                return (
                    AzureKeyVaultSettingsSource(
                        settings_cls, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
                    ),
                )

        expected_secrets = [type('', (), {'name': 'SqlServerUser'}), type('', (), {'name': 'SqlServer--Password'})]
        expected_secret_value = 'SecretValue'
        mocker.patch(f'{MODULE}.SecretClient.list_properties_of_secrets', return_value=expected_secrets)
        mocker.patch(
            f'{MODULE}.SecretClient.get_secret',
            side_effect=self._raise_resource_not_found_when_getting_parent_secret_name,
        )

        settings = AzureKeyVaultSettings()  # type: ignore

        assert settings.SqlServerUser == expected_secret_value
        assert settings.sql_server_user == expected_secret_value
        assert settings.sql_server.password == expected_secret_value

    def _raise_resource_not_found_when_getting_parent_secret_name(self, secret_name: str):
        expected_secret_value = 'SecretValue'
        key_vault_secret = KeyVaultSecret(SecretProperties(), expected_secret_value)

        if secret_name == 'SqlServer':
            raise ResourceNotFoundError()

        return key_vault_secret
