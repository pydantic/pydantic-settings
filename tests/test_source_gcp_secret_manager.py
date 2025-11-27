"""
Test pydantic_settings.GoogleSecretSettingsSource
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import Field
from pytest_mock import MockerFixture

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources import GoogleSecretManagerSettingsSource
from pydantic_settings.sources.lazy import LazyMapping
from pydantic_settings.sources.providers.gcp import GoogleSecretManagerMapping, import_gcp_secret_manager

try:
    gcp_secret_manager = True
    import_gcp_secret_manager()
    from google.cloud.secretmanager import SecretManagerServiceClient
except ImportError:
    gcp_secret_manager = False


SECRET_VALUES = {'test-secret': 'test-value'}


@pytest.fixture
def mock_secret_client(mocker: MockerFixture):
    client = mocker.Mock(spec=SecretManagerServiceClient)

    # Mock common_project_path
    client.common_project_path.return_value = 'projects/test-project'

    # Mock secret_version_path
    client.secret_version_path.return_value = 'projects/test-project/secrets/test-secret/versions/latest'

    client.parse_secret_path = SecretManagerServiceClient.parse_secret_path

    def mock_list_secrets(parent: str) -> list:
        # Mock list_secrets
        secret = mocker.Mock()
        secret.name = f'{parent}/secrets/test-secret'
        return [secret]

    client.list_secrets = mock_list_secrets

    secret_response = mocker.Mock()
    secret_response.payload.data.decode.return_value = 'test-value'

    def mock_access_secret_version(name: str):
        if name == 'projects/test-project/secrets/test-secret/versions/latest':
            return secret_response
        else:
            raise KeyError()

    client.access_secret_version = mock_access_secret_version

    return client


@pytest.fixture
def secret_manager_mapping(mock_secret_client):
    return GoogleSecretManagerMapping(mock_secret_client, project_id='test-project', case_sensitive=True)


@pytest.fixture
def test_settings():
    class TestSettings(BaseSettings):
        test_secret: str
        another_secret: str

    return TestSettings


@pytest.fixture(autouse=True)
def mock_google_auth(mocker: MockerFixture):
    mocker.patch(
        'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(mocker.Mock(), 'default-project')
    )


@pytest.mark.skipif(not gcp_secret_manager, reason='pydantic-settings[gcp-secret-manager] is not installed')
class TestGoogleSecretManagerSettingsSource:
    """Test GoogleSecretManagerSettingsSource."""

    def test_secret_manager_mapping_init(self, secret_manager_mapping):
        assert secret_manager_mapping._project_id == 'test-project'
        assert len(secret_manager_mapping._loaded_secrets) == 0

    def test_secret_manager_mapping_gcp_project_path(self, secret_manager_mapping, mock_secret_client):
        secret_manager_mapping._gcp_project_path
        mock_secret_client.common_project_path.assert_called_once_with('test-project')

    def test_secret_manager_mapping_secret_names(self, secret_manager_mapping):
        names = secret_manager_mapping._secret_names
        assert names == ['test-secret']

    def test_secret_manager_mapping_getitem_success(self, secret_manager_mapping):
        value = secret_manager_mapping['test-secret']
        assert value == 'test-value'

    def test_secret_manager_mapping_getitem_case_insensitive_success(self, mock_secret_client):
        case_insensitive_mapping = GoogleSecretManagerMapping(
            mock_secret_client, project_id='test-project', case_sensitive=False
        )
        value = case_insensitive_mapping['TEST-SECRET']
        assert value == 'test-value'

    def test_secret_manager_mapping_getitem_nonexistent_key(self, secret_manager_mapping):
        with pytest.raises(KeyError):
            _ = secret_manager_mapping['nonexistent-secret']

    def test_secret_manager_mapping_getitem_access_error(self, secret_manager_mapping, mocker):
        secret_manager_mapping._secret_client.access_secret_version = mocker.Mock(
            side_effect=Exception('Access denied')
        )

        assert secret_manager_mapping['test-secret'] is None

    def test_secret_manager_mapping_iter(self, secret_manager_mapping):
        assert list(secret_manager_mapping) == ['test-secret']

    def test_settings_source_init_with_defaults(self, mock_google_auth, test_settings):
        source = GoogleSecretManagerSettingsSource(test_settings)
        assert source._project_id == 'default-project'

    def test_settings_source_init_with_custom_values(self, mocker, test_settings):
        credentials = mocker.Mock()
        source = GoogleSecretManagerSettingsSource(test_settings, credentials=credentials, project_id='custom-project')
        assert source._project_id == 'custom-project'
        assert source._credentials == credentials

    def test_settings_source_init_with_custom_values_no_project_raises_error(self, mocker, test_settings):
        credentials = mocker.Mock()
        mocker.patch('pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(mocker.Mock(), None))

        with pytest.raises(AttributeError):
            _ = GoogleSecretManagerSettingsSource(test_settings, credentials=credentials)

    def test_settings_source_load_env_vars(self, mock_secret_client, mocker, test_settings):
        credentials = mocker.Mock()
        source = GoogleSecretManagerSettingsSource(test_settings, credentials=credentials, project_id='test-project')
        source._secret_client = mock_secret_client

        env_vars = source._load_env_vars()
        assert isinstance(env_vars, GoogleSecretManagerMapping)
        assert env_vars.get('test-secret') == 'test-value'
        assert env_vars.get('another_secret') is None

    def test_settings_source_repr(self, test_settings):
        source = GoogleSecretManagerSettingsSource(test_settings, project_id='test-project')
        assert 'test-project' in repr(source)
        assert 'GoogleSecretManagerSettingsSource' in repr(source)

    def test_pydantic_base_settings(self, mock_secret_client, monkeypatch, mocker):
        monkeypatch.setenv('ANOTHER_SECRET', 'yep_this_one')

        class Settings(BaseSettings, case_sensitive=False):
            test_secret: str = Field(..., alias='test-secret')
            another_secret: str = Field(..., alias='ANOTHER_SECRET')

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                google_secret_manager_settings = GoogleSecretManagerSettingsSource(
                    settings_cls, secret_client=mock_secret_client
                )
                return (
                    init_settings,
                    env_settings,
                    dotenv_settings,
                    file_secret_settings,
                    google_secret_manager_settings,
                )

        settings = Settings()  # type: ignore
        assert settings.another_secret == 'yep_this_one'
        assert settings.test_secret == 'test-value'

    def test_pydantic_base_settings_with_unknown_attribute(self, mock_secret_client, monkeypatch, mocker):
        from pydantic_core._pydantic_core import ValidationError

        class Settings(BaseSettings, case_sensitive=False):
            test_secret: str = Field(..., alias='test-secret')
            another_secret: str = Field(..., alias='ANOTHER_SECRET')

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                google_secret_manager_settings = GoogleSecretManagerSettingsSource(
                    settings_cls, secret_client=mock_secret_client
                )
                return (
                    init_settings,
                    env_settings,
                    dotenv_settings,
                    file_secret_settings,
                    google_secret_manager_settings,
                )

        with pytest.raises(ValidationError):
            _ = Settings()

    def test_pydantic_base_settings_with_default_value(self, mock_secret_client):
        class Settings(BaseSettings):
            my_field: str | None = Field(default='foo')

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                google_secret_manager_settings = GoogleSecretManagerSettingsSource(
                    settings_cls, secret_client=mock_secret_client
                )
                return (
                    init_settings,
                    env_settings,
                    dotenv_settings,
                    file_secret_settings,
                    google_secret_manager_settings,
                )

        settings = Settings()
        assert settings.my_field == 'foo'

    def test_secret_manager_mapping_list_secrets_error(self, secret_manager_mapping, mocker):
        secret_manager_mapping._secret_client.list_secrets = mocker.Mock(side_effect=Exception('Permission denied'))

        with pytest.raises(Exception, match='Permission denied'):
            _ = secret_manager_mapping._secret_names


@pytest.mark.skipif(not gcp_secret_manager, reason='pydantic-settings[gcp-secret-manager] is not installed')
class TestGCPSecretManagerLazyLoading:
    """Unit tests for lazy_load behavior in GoogleSecretManagerSettingsSource."""

    def test_returns_lazy_mapping_when_lazy_load_true(self):
        """Test GoogleSecretManagerSettingsSource stores LazyMapping when lazy_load=True."""

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=True)
                result = source()
                assert isinstance(result, dict)
                assert len(result) == 0
                assert hasattr(source, '_lazy_mapping')
                assert isinstance(source._lazy_mapping, LazyMapping)

    def test_returns_dict_when_lazy_load_false(self):
        """Test GoogleSecretManagerSettingsSource returns dict when lazy_load=False."""

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=False)
                result = source()
                assert isinstance(result, dict)
                assert not hasattr(source, '_lazy_mapping') or source._lazy_mapping is None

    def test_lazy_mapping_defers_resolution(self):
        """Test GoogleSecretManagerSettingsSource LazyMapping defers resolution."""

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=True)

                with patch.object(
                    source, '_get_resolved_field_value', wraps=source._get_resolved_field_value
                ) as mock_resolve:
                    source()
                    assert mock_resolve.call_count == 0

                    lazy_mapping = source._lazy_mapping
                    try:
                        _ = lazy_mapping['field']
                        assert mock_resolve.call_count > 0
                    except KeyError:
                        assert mock_resolve.call_count > 0


@pytest.mark.skipif(not gcp_secret_manager, reason='pydantic-settings[gcp-secret-manager] is not installed')
def test_gcp_secrets_source_accepts_lazy_load():
    """Test GoogleSecretManagerSettingsSource accepts lazy_load parameter."""

    class TestSettings(BaseSettings):
        field: str = 'default'

    try:
        # This will fail if google-cloud-secret-manager is not installed
        import inspect

        sig = inspect.signature(GoogleSecretManagerSettingsSource.__init__)
        assert 'lazy_load' in sig.parameters
    except ImportError:
        # gcp not installed, skip
        pytest.skip('google-cloud-secret-manager not installed')
