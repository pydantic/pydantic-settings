"""Test pydantic_settings.sources."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from pydantic.fields import FieldInfo

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
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import KeyVaultSecret, SecretProperties
except ImportError:
    azure_key_vault = None

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


@pytest.mark.skipif(azure_key_vault is None, reason='azure-keyvault-secrets and azure-identity are not installed')
class TestAzureKeyVaultSettingsSource:
    """Test AzureKeyVaultSettingsSource."""

    def test___init__(self) -> None:
        """Test __init__."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

        AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

    def test_get_field_value(self, mocker: MockerFixture) -> None:
        """Test _get_field_value."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

        expected_secret_value = 'SecretValue'
        key_vault_secret = KeyVaultSecret(SecretProperties(), expected_secret_value)

        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )
        mocker.patch(f'{MODULE}.SecretClient.get_secret', return_value=key_vault_secret)

        secret_value = obj.get_field_value(field=FieldInfo(), field_name='sqlserverpassword')[0]

        assert secret_value == expected_secret_value

    def test___call__(self, mocker: MockerFixture) -> None:
        """Test __cal__."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            sqlserverpassword: str
            SQLSERVERPASSWORD: str
            sql_server__password: str

        expected_secret_value = 'SecretValue'
        key_vault_secret = KeyVaultSecret(SecretProperties(), expected_secret_value)
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )
        mocker.patch(f'{MODULE}.SecretClient.get_secret', return_value=key_vault_secret)

        settings = obj()

        assert settings['sqlserverpassword'] == expected_secret_value
        assert settings['SQLSERVERPASSWORD'] == expected_secret_value
        assert settings['sql_server__password'] == expected_secret_value

    def test_azure_key_vault_settings_source(self, mocker: MockerFixture) -> None:
        """Test AzureKeyVaultSettingsSource."""

        class AzureKeyVaultSettings(BaseSettings):
            my_password: str
            sql_server__password: str

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

        expected_secret_value = 'SecretValue'
        key_vault_secret = KeyVaultSecret(SecretProperties(), expected_secret_value)
        mocker.patch(f'{MODULE}.SecretClient.get_secret', return_value=key_vault_secret)

        settings = AzureKeyVaultSettings()  # type: ignore

        assert settings.my_password == expected_secret_value
        assert settings.sql_server__password == expected_secret_value
