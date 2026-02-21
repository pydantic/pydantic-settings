"""Test pydantic_settings.KeyringSettingsSource."""

import pytest
from pydantic import AliasChoices, AliasPath, Field, SecretStr, ValidationError

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


def test_populate_by_name_with_alias_path_when_using_alias(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'fruits':
            return '["empire", "honeycrisp"]'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        apple: str = Field('default', validation_alias=AliasPath('fruits', 0))
        model_config = SettingsConfigDict(keyring_service_name='my_app', populate_by_name=True)

    s = Settings()
    assert s.apple == 'empire'


def test_populate_by_name_with_alias_path_when_using_name(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'apple':
            return 'jonathan gold'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        apple: str = Field('default', validation_alias=AliasPath('fruits', 0))
        model_config = SettingsConfigDict(keyring_service_name='my_app', populate_by_name=True)

    s = Settings()
    assert s.apple == 'jonathan gold'


@pytest.mark.parametrize(
    ('keyring_values', 'expected_value'),
    [
        ({'pomo': 'pomo-chosen'}, 'pomo-chosen'),
        ({'pomme': 'pomme-chosen'}, 'pomme-chosen'),
        ({'manzano': 'manzano-chosen'}, 'manzano-chosen'),
        ({'pomo': 'pomo-chosen', 'pomme': 'pomme-chosen', 'manzano': 'manzano-chosen'}, 'pomo-chosen'),
        ({'pomme': 'pomme-chosen', 'manzano': 'manzano-chosen'}, 'pomme-chosen'),
    ],
)
def test_populate_by_name_with_alias_choices_when_using_alias(mocker, keyring_values: dict[str, str], expected_value: str) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        return keyring_values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        apple: str = Field('default', validation_alias=AliasChoices('pomo', 'pomme', 'manzano'))
        model_config = SettingsConfigDict(keyring_service_name='my_app', populate_by_name=True)

    assert Settings().apple == expected_value


def test_validation_aliases(mocker) -> None:
    mock_keyring = mocker.Mock()
    keyring_values = {'foobar_alias': 'xxx'}

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        return keyring_values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field('default value', validation_alias='foobar_alias')
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    assert Settings().foobar == 'xxx'


def test_validation_aliases_alias_path(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'foo':
            return '{"bar": ["val0", "val1"]}'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasPath('foo', 'bar', 1))
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    assert Settings().foobar == 'val1'


def test_env_list_alias_choices_priority(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        values = {
            'different1': 'value 1',
            'different2': 'value 2',
        }
        return values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasChoices('different1', 'different2'))
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    assert Settings().foobar == 'value 1'


def test_validation_aliases_alias_choices(mocker) -> None:
    mock_keyring = mocker.Mock()
    keyring_values = {
        'foo': 'val1',
        'foo1': '{"bar": ["val0", "val2"]}',
        'bar': '["val1", "val2", "val3"]',
    }

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        return keyring_values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasChoices('foo', AliasPath('foo1', 'bar', 1), AliasPath('bar', 2)))
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    assert Settings().foobar == 'val1'

    keyring_values.pop('foo')
    assert Settings().foobar == 'val2'

    keyring_values.pop('foo1')
    assert Settings().foobar == 'val3'


def test_validation_alias_alias_choices_with_alias_path_first(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username == 'MY_FIELD':
            return 'env-value'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        my_field: str = Field(
            default='default-value',
            validation_alias=AliasChoices(AliasPath('nested', 'key'), 'MY_FIELD'),
        )
        model_config = SettingsConfigDict(keyring_service_name='my_app')

    assert Settings().my_field == 'env-value'


def test_validation_alias_with_env_prefix(mocker) -> None:
    mock_keyring = mocker.Mock()
    keyring_values = {'p_foo': 'bar'}

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        return keyring_values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field(validation_alias='foo')
        model_config = SettingsConfigDict(keyring_service_name='my_app', env_prefix='p_')

    with pytest.raises(ValidationError):
        Settings()

    keyring_values.clear()
    keyring_values['foo'] = 'bar'
    assert Settings().foobar == 'bar'


@pytest.mark.parametrize('env_prefix_target', ['all', 'alias'])
def test_validation_alias_with_env_prefix_and_env_prefix_target(mocker, env_prefix_target: str) -> None:
    mock_keyring = mocker.Mock()
    keyring_values = {'foo': 'bar'}

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        return keyring_values.get(username)

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        foobar: str = Field(validation_alias='foo')
        model_config = SettingsConfigDict(
            keyring_service_name='my_app',
            env_prefix='p_',
            env_prefix_target=env_prefix_target,
        )

    with pytest.raises(ValidationError):
        Settings()

    keyring_values.clear()
    keyring_values['p_foo'] = 'bar'
    assert Settings().foobar == 'bar'


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
