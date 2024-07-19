"""Test pydantic_settings.sources."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel, Field

from pydantic_settings.main import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    AzureKeyVaultSettingsSource,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    import_azure_key_vault,
)

try:
    import tomli
except ImportError:
    tomli = None


try:
    azure_key_vault = True
    import_azure_key_vault()
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import KeyVaultSecret, SecretProperties
except ImportError:
    azure_key_vault = False

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


MODULE = 'pydantic_settings.sources'

SOME_TOML_DATA = """
field = "top-level"

[some]
[some.table]
field = "some"

[other.table]
field = "other"
"""


class SimpleSettings(BaseSettings):
    """Simple settings."""

    model_config = SettingsConfigDict(pyproject_toml_depth=1, pyproject_toml_table_header=('some', 'table'))


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
class TestPyprojectTomlConfigSettingsSource:
    """Test PyprojectTomlConfigSettingsSource."""

    def test___init__(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == tmp_path / 'pyproject.toml'

    def test___init___explicit(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ explicit file."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'child' / 'pyproject.toml'
        pyproject.parent.mkdir()
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings, pyproject)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == pyproject

    def test___init___explicit_missing(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ explicit file missing."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'child' / 'pyproject.toml'
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings, pyproject)
        assert obj.toml_table_header == ('some', 'table')
        assert not obj.toml_data
        assert obj.toml_file_path == pyproject

    @pytest.mark.parametrize('depth', [0, 99])
    def test___init___no_file(self, depth: int, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ no file."""

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(pyproject_toml_depth=depth)

        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path / 'foo')
        obj = PyprojectTomlConfigSettingsSource(Settings)
        assert obj.toml_table_header == ('tool', 'pydantic-settings')
        assert not obj.toml_data
        assert obj.toml_file_path == tmp_path / 'foo' / 'pyproject.toml'

    def test___init___parent(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ parent directory."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path / 'child')
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == tmp_path / 'pyproject.toml'


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
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
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

    def _raise_resource_not_found_when_getting_parent_secret_name(self, secret_name: str) -> KeyVaultSecret:
        expected_secret_value = 'SecretValue'
        key_vault_secret = KeyVaultSecret(SecretProperties(), expected_secret_value)

        if secret_name == 'SqlServer':
            raise ResourceNotFoundError()

        return key_vault_secret
