"""
Test pydantic_settings.GoogleSecretSettingsSource
"""

import pytest
from pydantic import Field
from pytest_mock import MockerFixture

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources import GoogleSecretManagerSettingsSource
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
            _ = Settings()  # type: ignore

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

    @pytest.mark.parametrize(
        'case_sensitive, secret_name_in_gcp, requested_key, expected_value',
        [
            (True, 'test-secret', 'test-secret', 'test-value'),
            (True, 'TEST-SECRET', 'TEST-SECRET', 'test-value'),
            (True, 'testSecret', 'testSecret', 'test-value'),
            (True, 'TEST-SECRET', 'test-secret', None),
            (True, 'test-secret', 'TEST_SECRET', None),
            (False, 'test-secret', 'TEST-SECRET', 'test-value'),
            (False, 'TEST-SECRET', 'test-secret', 'test-value'),
            (False, 'TEST-SECRET', 'TEST-SECRET', 'test-value'),
            (False, 'testSecret', 'testSecret', 'test-value'),
            (False, 'testSecret', 'TESTSECRET', 'test-value'),
        ],
    )
    def test_secret_manager_mapping_retrieval_cases(
        self, mocker, case_sensitive, secret_name_in_gcp, requested_key, expected_value
    ):
        """
        Tests various combinations of case sensitivity and secret naming.
        """
        client = mocker.Mock(spec=SecretManagerServiceClient)
        client.common_project_path.return_value = 'projects/test-project'
        client.secret_version_path = (
            lambda project, secret, version: f'projects/{project}/secrets/{secret}/versions/{version}'
        )
        client.parse_secret_path = SecretManagerServiceClient.parse_secret_path

        # Mock list_secrets to return the specific secret name
        secret = mocker.Mock()
        secret.name = f'projects/test-project/secrets/{secret_name_in_gcp}'
        client.list_secrets.return_value = [secret]

        secret_response = mocker.Mock()
        secret_response.payload.data.decode.return_value = 'test-value'

        def mock_access_secret_version(name: str):
            # GCP is always case-sensitive
            if name == f'projects/test-project/secrets/{secret_name_in_gcp}/versions/latest':
                return secret_response
            raise Exception(f'Secret not found or access denied: {name}')

        client.access_secret_version = mock_access_secret_version

        mapping = GoogleSecretManagerMapping(client, project_id='test-project', case_sensitive=case_sensitive)

        if expected_value is None:
            # Depending on implementation, it might raise KeyError or return None if we try to access it via .get() or handled access
            # The Mapping __getitem__ implementation in pydantic-settings currently returns None if access fails
            # OR raises KeyError if the key isn't in the list at all.

            # If the key is not in _secret_names, it raises KeyError.
            # If it IS in _secret_names but access fails, it returns None.

            # For case (True, 'TEST-SECRET', 'test-secret', None):
            # _secret_names will be ['TEST-SECRET']. 'test-secret' is not in there. KeyError expected.
            try:
                val = mapping[requested_key]
                assert val == expected_value
            except KeyError:
                assert expected_value is None
        else:
            assert mapping[requested_key] == expected_value

    @pytest.mark.parametrize(
        'case_sensitive, requested_key, expected_value',
        [
            (True, 'TEST-SECRET', 'UPPER_VAL'),
            (True, 'test-secret', 'lower_val'),
            # Case insensitive collision with "Prefer Exact Match" logic:
            (False, 'TEST-SECRET', 'UPPER_VAL'),  # Exact match exists, prefer it
            (False, 'test-secret', 'lower_val'),  # Exact match exists, prefer it
            (False, 'Test-Secret', 'lower_val'),  # No exact match, fallback to 'lower_val' (last loaded)
        ],
    )
    def test_secret_manager_mapping_collision(self, mocker, case_sensitive, requested_key, expected_value):
        client = mocker.Mock(spec=SecretManagerServiceClient)
        client.common_project_path.return_value = 'projects/test-project'
        client.secret_version_path = (
            lambda project, secret, version: f'projects/{project}/secrets/{secret}/versions/{version}'
        )
        client.parse_secret_path = SecretManagerServiceClient.parse_secret_path

        # Mock list_secrets with colliding names
        secrets = []
        for name in ['TEST-SECRET', 'test-secret']:
            s = mocker.Mock()
            s.name = f'projects/test-project/secrets/{name}'
            secrets.append(s)
        client.list_secrets.return_value = secrets

        def mock_access_secret_version(name: str):
            # name format: projects/test-project/secrets/{SECRET_ID}/versions/latest
            if '/secrets/TEST-SECRET/' in name:
                resp = mocker.Mock()
                resp.payload.data.decode.return_value = 'UPPER_VAL'
                return resp
            elif '/secrets/test-secret/' in name:
                resp = mocker.Mock()
                resp.payload.data.decode.return_value = 'lower_val'
                return resp
            raise Exception(f'Secret not found: {name}')

        client.access_secret_version = mock_access_secret_version

        mapping = GoogleSecretManagerMapping(client, project_id='test-project', case_sensitive=case_sensitive)

        if not case_sensitive:
            with pytest.warns(UserWarning, match='Secret collision'):
                _ = mapping._secret_name_map
        else:
            _ = mapping._secret_name_map

        assert mapping[requested_key] == expected_value
