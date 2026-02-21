"""Test pydantic_settings.KeyringSettingsSource."""

import pytest

from pydantic_settings import BaseSettings, KeyringSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

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
        if username.lower() == 'option':
            return 'from-keyring'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        option: str = 'foo'
        list_option: str = 'fizz'

        model_config = SettingsConfigDict(keyring_service_name='my_app')

    s = Settings()
    assert s.option == 'from-keyring'
    assert s.list_option == 'fizz'


def test_keyring_settings_customise_sources(mocker) -> None:
    mock_keyring = mocker.Mock()

    def _get_password(service_name: str, username: str) -> str | None:
        assert service_name == 'my_app'
        if username.lower() == 'my_foo':
            return 'bar'
        return None

    mock_keyring.get_password = mocker.Mock(side_effect=_get_password)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    class Settings(BaseSettings):
        my_foo: str

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
    assert s.my_foo == 'bar'


def test_keyring_repr(mocker) -> None:
    mock_keyring = mocker.Mock()
    mock_keyring.get_password = mocker.Mock(return_value=None)
    mocker.patch('pydantic_settings.sources.providers.keyring.keyring', mock_keyring)

    source = KeyringSettingsSource(BaseSettings, service_name='my_app')
    assert repr(source) == "KeyringSettingsSource(service_name='my_app', env_nested_delimiter=None)"
