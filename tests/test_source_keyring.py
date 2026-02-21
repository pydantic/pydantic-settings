"""Test pydantic_settings.KeyringSettingsSource."""

import pytest
from pydantic import Field, SecretStr, ValidationError

from pydantic_settings import BaseSettings, KeyringSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

try:
    import keyring
except ImportError:
    keyring = None


@pytest.mark.skipif(keyring is not None, reason='keyring is installed')
def test_keyring_not_installed_raises_import_error() -> None:
    class Settings(BaseSettings):
        my_foo: str
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    with pytest.raises(
        ImportError,
        match=r'^keyring is not installed, run `pip install pydantic-settings\[keyring\]` '
        r'or `uv add "pydantic-settings\[keyring\]"`$',
    ):
        Settings()


def test_keyring_service_name_model_config_source(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username.lower() == 'password':
            return 'from-keyring-password'
        if username.lower() == 'api_token':
            return 'from-keyring-api-token'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        password: SecretStr | None = None
        api_token: SecretStr | None = None

        model_config = SettingsConfigDict(keyring_service_name='my_app')

    s = Settings()
    assert s.password is not None
    assert s.api_token is not None
    assert s.password.get_secret_value() == 'from-keyring-password'
    assert s.api_token.get_secret_value() == 'from-keyring-api-token'


def test_keyring_settings_customise_sources(mocker, monkeypatch) -> None:
    monkeypatch.delenv('DB_PASSWORD', raising=False)

    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username.lower() == 'db_password':
            return 'bar'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        db_password: SecretStr

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
                init_settings,
                env_settings,
                dotenv_settings,
                file_secret_settings,
                KeyringSettingsSource(settings_cls, service_name='my_app'),
            )

    s = Settings()
    assert s.db_password.get_secret_value() == 'bar'


def test_keyring_repr(mocker) -> None:
    mock_keyring = mocker.Mock()
    mock_keyring.get_password = mocker.Mock(return_value=None)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    source = KeyringSettingsSource(BaseSettings, service_name='my_app')
    assert repr(source) == "KeyringSettingsSource(service_name='my_app', env_nested_delimiter=None)"


def test_dash_to_underscore_translation(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'db-password':
            return 'from-dashed-alias'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        db_password: SecretStr = Field(..., alias='db-password')
        model_config = SettingsConfigDict(keyring_service_name='my_app', populate_by_name=True)

    s = Settings()
    assert s.db_password.get_secret_value() == 'from-dashed-alias'


def test_snake_case_conversion(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        values = {
            'my-field-from-kebab-case': 'kebab',
            'MyFieldFromPascalCase': 'pascal',
            'myFieldFromCamelCase': 'camel',
        }
        return values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        my_field_from_kebab_case: SecretStr = Field(..., alias='my-field-from-kebab-case')
        my_field_from_pascal_case: SecretStr = Field(..., alias='MyFieldFromPascalCase')
        my_field_from_camel_case: SecretStr = Field(..., alias='myFieldFromCamelCase')

        model_config = SettingsConfigDict(keyring_service_name='my_app', populate_by_name=True)

    s = Settings()
    assert s.my_field_from_kebab_case.get_secret_value() == 'kebab'
    assert s.my_field_from_pascal_case.get_secret_value() == 'pascal'
    assert s.my_field_from_camel_case.get_secret_value() == 'camel'


def test_snake_case_conversion_missing_alias(mocker) -> None:
    mock_keyring = mocker.Mock()
    mock_keyring.get_password = mocker.Mock(return_value=None)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        my_field_from_kebab_case: str = Field(..., alias='my-field-from-kebab-case')
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    with pytest.raises(ValidationError):
        Settings()


def test_alias_ambiguity_raises_settings_error(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'API_TOKEN':
            return 'raw-value'
        if username == 'api_token':
            return 'normalized-value'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        api_token: str = Field(..., alias='API_TOKEN')
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    with pytest.raises(SettingsError, match='^Ambiguous keyring values'):
        Settings()


def test_pydantic_base_settings(mocker, monkeypatch) -> None:
    monkeypatch.setenv('API_TOKEN', 'from-environment')

    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'api_token':
            return 'from-keyring'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings, case_sensitive=False):
        api_token: str = Field(..., alias='API_TOKEN')

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
                init_settings,
                env_settings,
                dotenv_settings,
                file_secret_settings,
                KeyringSettingsSource(settings_cls, service_name='my_app'),
            )

    settings = Settings()  # type: ignore
    assert settings.api_token == 'from-environment'
