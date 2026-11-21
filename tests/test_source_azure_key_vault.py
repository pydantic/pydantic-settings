"""
Test pydantic_settings.AzureKeyVaultSettingsSource.
"""

from typing import Annotated, Dict, Literal  # noqa: UP035

import pytest
from pydantic import AliasPath, BaseModel, ConfigDict, Discriminator, Field, Tag, ValidationError
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pytest_mock import MockerFixture

from pydantic_settings import (
    AzureKeyVaultSettingsSource,
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources.providers.azure import import_azure_key_vault

try:
    azure_key_vault = True
    import_azure_key_vault()
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import KeyVaultSecret, SecretClient, SecretProperties
except ImportError:
    azure_key_vault = False


@pytest.mark.skipif(not azure_key_vault, reason='pydantic-settings[azure-key-vault] is not installed')
class TestAzureKeyVaultSettingsSource:
    """Test AzureKeyVaultSettingsSource."""

    def test___init__(self, mocker: MockerFixture) -> None:
        """Test __init__."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=[],
        )

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

        expected_secrets = [
            type('', (), {'name': 'SqlServerUser', 'enabled': True}),
            type('', (), {'name': 'SqlServer--Password', 'enabled': True}),
        ]
        expected_secret_value = 'SecretValue'
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            side_effect=self._raise_resource_not_found_when_getting_parent_secret_name,
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

        settings = obj()

        assert settings['SqlServerUser'] == expected_secret_value
        assert settings['SqlServer']['Password'] == expected_secret_value

    @pytest.mark.parametrize('from_config', [False, True])
    @pytest.mark.parametrize(
        ('parse_none_str', 'secret_value', 'expected'),
        [(None, 'null', 'null'), ('null', 'null', None), ('VOID', 'VOID', None), ('null', 'ordinary', 'ordinary')],
    )
    def test_parse_none_str(
        self,
        mocker: MockerFixture,
        from_config: bool,
        parse_none_str: str | None,
        secret_value: str,
        expected: str | None,
    ) -> None:
        class NestedModel(BaseModel):
            value: str | None = 'default'

        class AzureKeyVaultSettings(BaseSettings):
            model_config = {'env_parse_none_str': parse_none_str if from_config else None}
            direct: str | None = 'default'
            nested: NestedModel

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=[
                type('', (), {'name': 'direct', 'enabled': True}),
                type('', (), {'name': 'nested--value', 'enabled': True}),
            ],
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), secret_value),
        )
        source = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings,
            'https://my-resource.vault.azure.net/',
            DefaultAzureCredential(),
            env_parse_none_str=None if from_config else parse_none_str,
        )

        values = source()
        assert values == {'direct': expected, 'nested': {'value': expected}}
        settings = AzureKeyVaultSettings(**values)
        assert settings.direct == expected
        assert settings.nested.value == expected

    def test_repr(self, mocker: MockerFixture) -> None:
        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=[],
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

        assert repr(obj) == (
            "AzureKeyVaultSettingsSource(url='https://my-resource.vault.azure.net/', env_nested_delimiter='--')"
        )

    def test_mapping_case_sensitive(self, mocker: MockerFixture) -> None:
        """With `case_sensitive=True` secret names are mapped verbatim."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            SqlServerUser: str

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=[type('', (), {'name': 'SqlServerUser', 'enabled': True})],
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), 'SecretValue'),
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings,
            'https://my-resource.vault.azure.net/',
            DefaultAzureCredential(),
            case_sensitive=True,
        )

        assert len(obj.env_vars) == 1
        assert list(obj.env_vars) == ['SqlServerUser']
        assert obj.env_vars['SqlServerUser'] == 'SecretValue'
        with pytest.raises(KeyError):
            obj.env_vars['sqlserveruser']

    def test_mapping_case_insensitive(self, mocker: MockerFixture) -> None:
        """With `case_sensitive=False` lookups are lower-cased on both sides."""

        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            sqlserveruser: str

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=[type('', (), {'name': 'SqlServerUser', 'enabled': True})],
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), 'SecretValue'),
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings,
            'https://my-resource.vault.azure.net/',
            DefaultAzureCredential(),
            case_sensitive=False,
        )

        assert len(obj.env_vars) == 1
        assert obj.env_vars['SqlServerUser'] == 'SecretValue'
        assert obj.env_vars['sqlserveruser'] == 'SecretValue'

    def test_do_not_load_disabled_secrets(self, mocker: MockerFixture) -> None:
        class AzureKeyVaultSettings(BaseSettings):
            """AzureKeyVault settings."""

            SqlServerPassword: str
            DisabledSqlServerPassword: str

        disabled_secret_name = 'SqlServerPassword'
        expected_secrets = [
            type('', (), {'name': disabled_secret_name, 'enabled': False}),
        ]
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), 'SecretValue'),
        )
        obj = AzureKeyVaultSettingsSource(
            AzureKeyVaultSettings, 'https://my-resource.vault.azure.net/', DefaultAzureCredential()
        )

        settings = obj()

        assert disabled_secret_name not in settings

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

        expected_secrets = [
            type('', (), {'name': 'SqlServerUser', 'enabled': True}),
            type('', (), {'name': 'SqlServer--Password', 'enabled': True}),
        ]
        expected_secret_value = 'SecretValue'
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
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
            raise ResourceNotFoundError

        return key_vault_secret

    def test_dash_to_underscore_translation(self, mocker: MockerFixture) -> None:
        """Test that dashes in secret names are mapped to underscores in field names."""

        class AzureKeyVaultSettings(BaseSettings):
            my_field: str
            alias_field: str = Field(..., alias='Secret-Alias')

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
                        settings_cls,
                        'https://my-resource.vault.azure.net/',
                        DefaultAzureCredential(),
                        dash_to_underscore=True,
                    ),
                )

        expected_secrets = [
            type('', (), {'name': 'my-field', 'enabled': True}),
            type('', (), {'name': 'Secret-Alias', 'enabled': True}),
        ]
        expected_secret_value = 'SecretValue'

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), expected_secret_value),
        )

        settings = AzureKeyVaultSettings()

        assert settings.my_field == expected_secret_value
        assert settings.alias_field == expected_secret_value

    def _load_dash_to_underscore_settings(
        self,
        mocker: MockerFixture,
        settings_cls: type[BaseSettings],
        secrets: dict[str, str],
        env_prefix: str | None = None,
    ) -> BaseSettings:
        mocker.patch.object(
            SecretClient,
            'list_properties_of_secrets',
            return_value=[type('', (), {'name': name, 'enabled': True}) for name in secrets],
        )
        mocker.patch.object(
            SecretClient, 'get_secret', side_effect=lambda name: KeyVaultSecret(SecretProperties(), secrets[name])
        )

        class AzureKeyVaultSettings(settings_cls):  # type: ignore[valid-type,misc]
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
                        settings_cls,
                        'https://my-resource.vault.azure.net/',
                        DefaultAzureCredential(),
                        dash_to_underscore=True,
                        env_prefix=env_prefix,
                    ),
                )

        return AzureKeyVaultSettings()

    @pytest.mark.parametrize('env_prefix', (None, 'APP-'))
    def test_dash_to_underscore_translation_nested(self, mocker: MockerFixture, env_prefix: str | None) -> None:
        class ConnectionPool(BaseModel):
            max_size: int

        class Database(BaseModel):
            sql_password: str
            api_key: str = Field(alias='api-key')
            app_token: str = Field(alias='app-token')
            connection_pool: ConnectionPool
            metadata: dict[str, str]
            optional_note: str = 'default'

        class Settings(BaseSettings):
            database: Database

        prefix = env_prefix or ''
        secrets = {
            f'{prefix}database--sql-password': 'password',
            f'{prefix}database--api-key': 'api-secret',
            f'{prefix}database--app-token': 'app-secret',
            f'{prefix}database--connection-pool--max-size': '10',
            f'{prefix}database--metadata--keep-dash': 'value',
        }
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets, env_prefix)

        assert settings.database.sql_password == 'password'
        assert settings.database.api_key == 'api-secret'
        assert settings.database.app_token == 'app-secret'
        assert settings.database.connection_pool.max_size == 10
        assert settings.database.metadata == {'keep-dash': 'value'}
        assert settings.database.optional_note == 'default'

    def test_dash_to_underscore_translation_union_alias(self, mocker: MockerFixture) -> None:
        class FirstDatabase(BaseModel):
            api_key: str
            kind: Literal['first']

        class AliasedDatabase(BaseModel):
            api_key: str = Field(alias='api-key')
            kind: Literal['aliased']

        class Settings(BaseSettings):
            database: FirstDatabase | AliasedDatabase

        secrets = {'database--api-key': 'secret', 'database--kind': 'aliased'}
        aliased_settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)
        assert isinstance(aliased_settings.database, AliasedDatabase)
        assert aliased_settings.database.api_key == 'secret'

        secrets['database--kind'] = 'first'
        first_settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)
        assert isinstance(first_settings.database, FirstDatabase)
        assert first_settings.database.api_key == 'secret'

    def test_dash_to_underscore_translation_discriminated_union(self, mocker: MockerFixture) -> None:
        class SqlDatabase(BaseModel):
            kind: Literal['sql']
            sql_password: str

        class RedisDatabase(BaseModel):
            kind: Literal['redis']
            redis_url: str

        class Settings(BaseSettings):
            database: Annotated[
                Annotated[SqlDatabase, Tag('sql')] | Annotated[RedisDatabase, Tag('redis')], Discriminator('kind')
            ]

        secrets = {'database--kind': 'sql', 'database--sql-password': 'password'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.database == SqlDatabase(kind='sql', sql_password='password')

    def test_dash_to_underscore_translation_dict_of_models(self, mocker: MockerFixture) -> None:
        class Database(BaseModel):
            sql_password: str

        class Settings(BaseSettings):
            databases: dict[str, Database] | None = None

        secrets = {'databases--main-db--sql-password': 'main', 'databases--replica--sql-password': 'replica'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.databases == {
            'main-db': Database(sql_password='main'),
            'replica': Database(sql_password='replica'),
        }

    def test_dash_to_underscore_translation_bare_dict(self, mocker: MockerFixture) -> None:
        class Settings(BaseSettings):
            metadata: Dict  # noqa: UP006

        secrets = {'metadata--keep-dash': 'value'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.metadata == {'keep-dash': 'value'}

    def test_dash_to_underscore_translation_nested_validate_by_name(self, mocker: MockerFixture) -> None:
        @pydantic_dataclass(config=ConfigDict(validate_by_name=True))
        class Credentials:
            api_key: str = Field(validation_alias='apiKey')

        class Database(BaseModel):
            model_config = ConfigDict(validate_by_name=True)

            sql_password: str = Field(validation_alias='sqlPassword')
            credentials: Credentials

        class Settings(BaseSettings):
            database: Database

        secrets = {'database--sql-password': 'password', 'database--credentials--api-key': 'secret'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.database.sql_password == 'password'
        assert settings.database.credentials.api_key == 'secret'

    def test_dash_to_underscore_translation_nested_model_validates_by_alias(self, mocker: MockerFixture) -> None:
        class Database(BaseModel):
            sql_password: str = Field(validation_alias='sql_password_alias')

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(validate_by_alias=False)

            database: Database

        secrets = {'database--sql-password-alias': 'password'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.database.sql_password == 'password'

    def test_dash_to_underscore_translation_nested_validate_by_alias_false(self, mocker: MockerFixture) -> None:
        @pydantic_dataclass(config=ConfigDict(validate_by_alias=False))
        class Credentials:
            api_key: str = Field(validation_alias='apiKey')

        class Database(BaseModel):
            model_config = ConfigDict(validate_by_alias=False)

            sql_password: str = Field(validation_alias='sqlPassword')
            credentials: Credentials

        class Settings(BaseSettings):
            database: Database

        secrets = {'database--sql-password': 'password', 'database--credentials--api-key': 'secret'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.database.sql_password == 'password'
        assert settings.database.credentials.api_key == 'secret'

    def test_dash_to_underscore_translation_nested_alias_path(self, mocker: MockerFixture) -> None:
        class Nested(BaseModel):
            v: str = Field(validation_alias=AliasPath('my_path', 0))

        class Settings(BaseSettings):
            nest: Nested

        secrets = {'nest--my-path': '["a"]'}
        settings = self._load_dash_to_underscore_settings(mocker, Settings, secrets)

        assert settings.nest.v == 'a'

    @pytest.mark.parametrize(
        'env_prefix', (None, 'singlewordprefix', 'prefix-kebab-case-', 'PrefixPascalCaseprefixCamelCaseSeparator-')
    )
    def test_snake_case_conversion(self, mocker: MockerFixture, env_prefix: str | None) -> None:
        """Test that secret names are mapped to snake case in field names."""

        class NestedModel(BaseModel):
            nested_field: str

        class AzureKeyVaultSettings(BaseSettings):
            my_field_from_kebab_case: str
            my_field_from_pascal_case: str
            my_field_from_camel_case: str
            alias_field: str = Field(alias='Secret-Alias')
            alias_field_2: str = Field(alias='another-SECRET-AliaS')
            nested_model: NestedModel

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
                        settings_cls,
                        'https://my-resource.vault.azure.net/',
                        DefaultAzureCredential(),
                        snake_case_conversion=True,
                        env_prefix=env_prefix,
                    ),
                )

        expected_secrets = [
            type(
                '', (), {'name': f'{"" if env_prefix is None else env_prefix}my-field-from-kebab-case', 'enabled': True}
            ),
            type('', (), {'name': f'{"" if env_prefix is None else env_prefix}MyFieldFromPascalCase', 'enabled': True}),
            type('', (), {'name': f'{"" if env_prefix is None else env_prefix}myFieldFromCamelCase', 'enabled': True}),
            type('', (), {'name': 'Secret-Alias', 'enabled': True}),
            type('', (), {'name': 'another-SECRET-AliaS', 'enabled': True}),
            type(
                '', (), {'name': f'{"" if env_prefix is None else env_prefix}NestedModel--NestedField', 'enabled': True}
            ),
        ]
        expected_secret_value = 'SecretValue'

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), expected_secret_value),
        )

        settings = AzureKeyVaultSettings()

        assert settings.my_field_from_kebab_case == expected_secret_value
        assert settings.my_field_from_pascal_case == expected_secret_value
        assert settings.my_field_from_camel_case == expected_secret_value
        assert settings.alias_field == expected_secret_value
        assert settings.alias_field_2 == expected_secret_value
        assert settings.nested_model.nested_field == expected_secret_value

    def test_snake_case_conversion_missing_alias(self, mocker: MockerFixture) -> None:
        class AzureKeyVaultSettings(BaseSettings):
            my_field_from_kebab_case: str

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
                        settings_cls,
                        'https://my-resource.vault.azure.net/',
                        DefaultAzureCredential(),
                        snake_case_conversion=True,
                        env_prefix='some-prefix',
                    ),
                )

        expected_secrets = [
            type('', (), {'name': 'my-field-from-kebab-case', 'enabled': True}),
        ]
        expected_secret_value = 'SecretValue'

        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.list_properties_of_secrets.__qualname__}',
            return_value=expected_secrets,
        )
        mocker.patch(
            f'{AzureKeyVaultSettingsSource.__module__}.{SecretClient.get_secret.__qualname__}',
            return_value=KeyVaultSecret(SecretProperties(), expected_secret_value),
        )
        with pytest.raises(ValidationError):
            AzureKeyVaultSettings()
