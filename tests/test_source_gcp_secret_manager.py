"""
Test pydantic_settings.GoogleSecretSettingsSource
"""

from typing import Annotated

import pytest
from pydantic import Field
from pytest_mock import MockerFixture

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import GoogleSecretManagerSettingsSource
from pydantic_settings.sources.providers.gcp import GoogleSecretManagerMapping, import_gcp_secret_manager
from pydantic_settings.sources.types import SecretVersion

try:
    gcp_secret_manager = True
    import_gcp_secret_manager()
    from google.cloud.secretmanager import SecretManagerServiceClient
except ImportError:
    gcp_secret_manager = False


SECRET_VALUES = {'test-secret': 'test-value'}


@pytest.fixture
def mock_secret_client_factory(mocker: MockerFixture):
    def _create_client(secrets_config: list[dict] | None = None):
        client = mocker.Mock(spec=SecretManagerServiceClient)

        # Default config if generic usage
        if secrets_config is None:
            secrets_config = [
                {'name': 'test-secret', 'project': 'test-project', 'version': 'latest', 'value': 'test-value'}
            ]

        # Helper to normalize access path
        def _get_path(project, secret, version):
            # If secret is already a path, extract the name
            if '/' in secret:
                secret = secret.split('/')[-1]
            return f'projects/{project}/secrets/{secret}/versions/{version}'

        client.secret_version_path = _get_path
        client.common_project_path.return_value = 'projects/test-project'
        client.parse_secret_path = SecretManagerServiceClient.parse_secret_path

        # Prepare data for list_secrets and access_secret_version
        known_secrets = []
        secret_values = {}

        for cfg in secrets_config:
            project = cfg.get('project', 'test-project')
            secret_name = cfg['name']
            version = cfg.get('version', 'latest')
            value = cfg.get('value', 'test-value')

            full_secret_path = f'projects/{project}/secrets/{secret_name}'
            full_version_path = _get_path(project, secret_name, version)

            # Create secret mock for list_secrets
            s_mock = mocker.Mock()
            s_mock.name = full_secret_path
            # Avoid duplicates in listing
            if not any(s.name == full_secret_path for s in known_secrets):
                known_secrets.append(s_mock)

            # Store value for access
            secret_values[full_version_path] = value

        client.list_secrets.return_value = known_secrets

        def mock_access_secret_version(name: str):
            if name in secret_values:
                resp = mocker.Mock()
                resp.payload.data.decode.return_value = secret_values[name]
                return resp
            raise Exception(f'Secret not found or access denied: {name}')

        client.access_secret_version = mocker.Mock(side_effect=mock_access_secret_version)

        return client

    return _create_client


@pytest.fixture
def mock_secret_client(mock_secret_client_factory):
    """Legacy fixture support for tests that just need the default 'test-secret'."""
    return mock_secret_client_factory()


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
        'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(mocker.Mock(), 'test-project')
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

    def test_secret_manager_mapping_getitem_access_error(self, secret_manager_mapping, mocker):
        secret_manager_mapping._secret_client.access_secret_version = mocker.Mock(
            side_effect=Exception('Access denied')
        )

        assert secret_manager_mapping['test-secret'] is None

    def test_secret_manager_mapping_iter(self, secret_manager_mapping):
        assert list(secret_manager_mapping) == ['test-secret']

    @pytest.mark.parametrize(
        'project_id, credentials, expected_project_id',
        [
            pytest.param(None, None, 'test-project', id='Init: Default Project ID from Auth'),
            pytest.param('custom-project', 'mock', 'custom-project', id='Init: Custom Project ID and Credentials'),
        ],
    )
    def test_settings_source_init(
        self, mocker, mock_google_auth, test_settings, project_id, credentials, expected_project_id
    ):
        if credentials == 'mock':
            credentials = mocker.Mock()

        source = GoogleSecretManagerSettingsSource(test_settings, credentials=credentials, project_id=project_id)
        assert source._project_id == expected_project_id
        if credentials:
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
        'case_sensitive, secret_name_in_gcp, requested_key, expected_value, expected_error',
        [
            pytest.param(
                True, 'test-secret', 'test-secret', 'test-value', None, id='Retrieval: CS=True - Exact Match (Lower)'
            ),
            pytest.param(
                True, 'TEST-SECRET', 'TEST-SECRET', 'test-value', None, id='Retrieval: CS=True - Exact Match (Upper)'
            ),
            pytest.param(
                True, 'testSecret', 'testSecret', 'test-value', None, id='Retrieval: CS=True - Exact Match (Camel)'
            ),
            pytest.param(
                True,
                'TEST-SECRET',
                'test-secret',
                None,
                KeyError,
                id='Retrieval: CS=True - Case Mismatch Raises KeyError',
            ),
            pytest.param(
                True,
                'test-secret',
                'TEST_SECRET',
                None,
                KeyError,
                id='Retrieval: CS=True - Key Mismatch Raises KeyError',
            ),
            pytest.param(
                False,
                'test-secret',
                'TEST-SECRET',
                'test-value',
                None,
                id='Retrieval: CS=False - Uppercase Key / Lowercase Secret',
            ),
            pytest.param(
                False,
                'TEST-SECRET',
                'test-secret',
                'test-value',
                None,
                id='Retrieval: CS=False - Lowercase Key / Uppercase Secret',
            ),
            pytest.param(
                False, 'TEST-SECRET', 'TEST-SECRET', 'test-value', None, id='Retrieval: CS=False - Exact Match (Upper)'
            ),
            pytest.param(
                False, 'testSecret', 'testSecret', 'test-value', None, id='Retrieval: CS=False - Exact Match (Camel)'
            ),
            pytest.param(
                False,
                'testSecret',
                'TESTSECRET',
                'test-value',
                None,
                id='Retrieval: CS=False - Uppercase Key / Camel Case Secret',
            ),
            pytest.param(
                True,
                'test-secret',
                'nonexistent-secret',
                None,
                KeyError,
                id='Retrieval: CS=True - Nonexistent Secret Raises KeyError',
            ),
            pytest.param(
                False,
                'test-secret',
                'nonexistent-secret',
                None,
                KeyError,
                id='Retrieval: CS=False - Nonexistent Secret Raises KeyError',
            ),
        ],
    )
    def test_secret_manager_mapping_retrieval_cases(
        self,
        mock_secret_client_factory,
        case_sensitive,
        secret_name_in_gcp,
        requested_key,
        expected_value,
        expected_error,
    ):
        """
        Tests various combinations of case sensitivity, secret naming, and error raising (when the Key doesn't exist).
        """
        client = mock_secret_client_factory([{'name': secret_name_in_gcp, 'value': 'test-value'}])

        mapping = GoogleSecretManagerMapping(client, project_id='test-project', case_sensitive=case_sensitive)

        if expected_error:
            with pytest.raises(expected_error):
                _ = mapping[requested_key]
        else:
            assert mapping[requested_key] == expected_value

    @pytest.mark.parametrize(
        'case_sensitive, requested_key, expected_value',
        [
            pytest.param(
                True, 'TEST-SECRET', 'UPPER_VAL', id='Collision Test: CS=True - Uppercase Key Returns Correct Value'
            ),
            pytest.param(
                True, 'test-secret', 'lower_val', id='Collision Test: CS=True - Lowercase Key Returns Correct Value'
            ),
            # Case insensitive collision with "Prefer Exact Match" logic:
            pytest.param(
                False, 'TEST-SECRET', 'UPPER_VAL', id='Collision Test: CS=False - Uppercase Key Prefers Exact Match'
            ),
            pytest.param(
                False, 'test-secret', 'lower_val', id='Collision Test: CS=False - Lowercase Key Prefers Exact Match'
            ),
            pytest.param(
                False,
                'Test-Secret',
                'lower_val',
                id='Collision Test: CS=False - Mixed Case Key Fallback to Last Loaded',
            ),
        ],
    )
    def test_secret_manager_mapping_collision(
        self, mock_secret_client_factory, case_sensitive, requested_key, expected_value
    ):
        client = mock_secret_client_factory(
            [
                {'name': 'TEST-SECRET', 'value': 'UPPER_VAL'},
                {'name': 'test-secret', 'value': 'lower_val'},
            ]
        )

        mapping = GoogleSecretManagerMapping(client, project_id='test-project', case_sensitive=case_sensitive)

        if not case_sensitive:
            with pytest.warns(UserWarning, match='Secret collision'):
                _ = mapping._secret_name_map
        else:
            _ = mapping._secret_name_map

        assert mapping[requested_key] == expected_value

    @pytest.mark.parametrize(
        'case_sensitive',
        [
            # Case Sensitive = True: We expect exact alias match to work
            pytest.param(True, id='Version Annotation: CS=True - Exact Alias Match'),
            # Case Sensitive = False: We expect case-insensitive match (alias mismatch) to work
            pytest.param(False, id='Version Annotation: CS=False - Case Insensitive Alias Match'),
        ],
    )
    def test_secret_version_annotation(self, mock_secret_client, mocker, case_sensitive):
        mock_secret_client.secret_version_path = (
            lambda project, secret, version: f'projects/{project}/secrets/{secret}/versions/{version}'
        )

        resp_latest = mocker.Mock()
        resp_latest.payload.data.decode.return_value = 'latest-value'

        resp_v1 = mocker.Mock()
        resp_v1.payload.data.decode.return_value = 'v1-value'

        def mock_access(name: str):
            if name.endswith('/versions/latest'):
                return resp_latest

            if name.endswith('/versions/1'):
                return resp_v1

            raise Exception(f'Not found: {name}')

        mock_secret_client.access_secret_version = mock_access

        alias = 'test-secret' if case_sensitive else 'TEST-SECRET'

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True, case_sensitive=case_sensitive)
            test_secret_v1: Annotated[str, Field(alias=alias), SecretVersion('1')]
            test_secret_latest: str = Field(alias='test-secret')

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
                    GoogleSecretManagerSettingsSource(
                        settings_cls, secret_client=mock_secret_client, case_sensitive=case_sensitive
                    ),
                )

        s = Settings()

        assert s.test_secret_v1 == 'v1-value'
        assert s.test_secret_latest == 'latest-value'

    def test_secret_version_annotation_missing_secret(self, mock_secret_client, mocker):
        """Test SecretVersion annotation when secret is missing"""
        mock_secret_client.secret_version_path.return_value = 'path/to/missing'
        # Only test-secret exists
        mock_secret_client.list_secrets.return_value = []

        class Settings(BaseSettings):
            missing_secret: Annotated[str, SecretVersion('1')] = 'default'

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(settings_cls, secret_client=mock_secret_client),)

        s = Settings()
        assert s.missing_secret == 'default'

    def test_secret_version_annotation_access_failure(self, mock_secret_client, mocker):
        """Test SecretVersion annotation when secret access fails (covers branch 209->202)."""
        mock_secret_client.secret_version_path.return_value = 'path/to/secret'

        # Secret exists in list
        secret = mocker.Mock()
        secret.name = 'projects/test-project/secrets/existing-secret'
        mock_secret_client.list_secrets.return_value = [secret]

        # Access fails (returns None from mapping._get_secret_value due to exception)
        mock_secret_client.access_secret_version.side_effect = Exception('Access denied')

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True)
            existing_secret: Annotated[str, Field(alias='existing-secret'), SecretVersion('1')] = 'default'

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(settings_cls, secret_client=mock_secret_client),)

        s = Settings()
        assert s.existing_secret == 'default'

    def test_secret_version_annotation_case_insensitive_multiple_versions(self, mock_secret_client_factory, mocker):
        """
        Test fetching multiple versions of the same secret with case-insensitive, matching different aliases.
        """
        client = mock_secret_client_factory(
            [
                {'name': 'test-secret', 'version': '1', 'value': 'v1-val'},
                {'name': 'test-secret', 'version': '2', 'value': 'v2-val'},
            ]
        )

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True, case_sensitive=False)
            # Both should map to 'test-secret' in GCP, but requesting different versions
            v1: Annotated[str, Field(alias='test-secret'), SecretVersion('1')]
            v2: Annotated[str, Field(alias='TEST-SECRET'), SecretVersion('2')]

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(settings_cls, secret_client=client, case_sensitive=False),)

        s = Settings()
        assert s.v1 == 'v1-val'
        assert s.v2 == 'v2-val'

    def test_secret_version_annotation_case_sensitive_failure(self, mock_secret_client, mocker):
        """Test that case sensitive lookup fails when case mismatches."""
        mock_secret_client.secret_version_path.return_value = 'path/to/secret'

        # Secret exists as 'test-secret'
        secret = mocker.Mock()
        secret.name = 'projects/test-project/secrets/test-secret'
        mock_secret_client.list_secrets.return_value = [secret]

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True, case_sensitive=True)
            # Alias mismatch case
            my_secret: Annotated[str, Field(alias='TEST-SECRET'), SecretVersion('1')]

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
                    GoogleSecretManagerSettingsSource(
                        settings_cls, secret_client=mock_secret_client, case_sensitive=True
                    ),
                )

        from pydantic import ValidationError

        with pytest.raises(ValidationError) as excinfo:
            Settings()

        # Expecting validation error because the secret was not found due to case mismatch
        # and no default value was provided.
        assert 'TEST-SECRET' in str(excinfo.value)

    def test_secret_manager_cache_behavior(self, mock_secret_client_factory, mocker):
        """Test that accessing the same secret twice does not fetch it again from GCP."""
        client = mock_secret_client_factory([{'name': 'test-secret', 'value': 'secret-value'}])

        mapping = GoogleSecretManagerMapping(client, project_id='test-project', case_sensitive=True)

        # First access
        val1 = mapping['test-secret']
        assert val1 == 'secret-value'
        assert client.access_secret_version.call_count == 1

        # Second access should hit cache
        val2 = mapping['test-secret']
        assert val2 == 'secret-value'
        assert client.access_secret_version.call_count == 1

    def test_init_triggers_import(self, mocker, test_settings):
        """Test that initializing the source triggers the import if globals are None."""
        mocker.patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient', None)
        mock_import = mocker.patch('pydantic_settings.sources.providers.gcp.import_gcp_secret_manager')

        # Side effect to restore the class so initialization continues
        def side_effect():
            mocker.patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient', mocker.Mock())
            mocker.patch('pydantic_settings.sources.providers.gcp.Credentials', mocker.Mock())
            mocker.patch(
                'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(mocker.Mock(), 'p')
            )

        mock_import.side_effect = side_effect

        credentials = mocker.Mock()
        GoogleSecretManagerSettingsSource(test_settings, credentials=credentials, project_id='p')

    def test_secret_version_no_fallback(self, mock_secret_client_factory, mocker):
        """
        Test that we do NOT fallback to 'latest' if a specific version is requested but missing.
        """
        # Client has 'latest' but NOT version '1'
        # We simulate this by having the mock client raise an exception or return None for v1 path
        # but work for latest.

        client = mock_secret_client_factory([{'name': 'test-secret', 'value': 'latest-val'}])

        # We need to ensure accessing version '1' fails.
        # The factory's access_secret_version mocks per path.

        original_access = client.access_secret_version

        def access_side_effect(name, **kwargs):
            if 'versions/1' in name:
                raise Exception('Version 1 missing')
            return original_access(name, **kwargs)

        client.access_secret_version.side_effect = access_side_effect

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True)
            # This should fail if we don't fallback (because v1 is missing)
            # If we DO fallback (bug), it will get 'latest-val'
            v1: Annotated[str, Field(alias='test-secret'), SecretVersion('1')]

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(cls, secret_client=client, project_id='test-project'),)

        from pydantic import ValidationError

        # EXPECTATION: ValidationError because v1 is missing.
        # REALITY (Bug): It gets 'latest-val' and succeeds.

        # We assert that it raises ValidationError.
        # If the bug is present, this assertion will FAIL (no exception raised).
        with pytest.raises(ValidationError) as excinfo:
            Settings()

        assert 'Field required' in str(excinfo.value) or 'test-secret' in str(excinfo.value)

        """
        Test that duplicate aliases with different versions work correctly when populate_by_name is True.
        """
        client = mock_secret_client_factory(
            [
                {'name': 'test-secret', 'version': '1', 'value': 'v1-val'},
                {'name': 'test-secret', 'version': '2', 'value': 'v2-val'},
            ]
        )

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=True, case_sensitive=True)
            v1: Annotated[str, Field(alias='test-secret'), SecretVersion('1')]
            v2: Annotated[str, Field(alias='test-secret'), SecretVersion('2')]

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(cls, secret_client=client, project_id='test-project'),)

        s = Settings()
        assert s.v1 == 'v1-val'
        assert s.v2 == 'v2-val'

    def test_secret_version_annotation_duplicate_alias_fail(self, mock_secret_client_factory, mocker):
        """
        Test that duplicate aliases fail when populate_by_name is False.
        """
        client = mock_secret_client_factory(
            [
                {'name': 'test-secret', 'version': '1', 'value': 'v1-val'},
                {'name': 'test-secret', 'version': '2', 'value': 'v2-val'},
            ]
        )

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(populate_by_name=False)
            v1: Annotated[str, Field(alias='test-secret'), SecretVersion('1')]
            v2: Annotated[str, Field(alias='test-secret'), SecretVersion('2')]

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (GoogleSecretManagerSettingsSource(cls, secret_client=client, project_id='test-project'),)

        s = Settings()
        # With populate_by_name=False, we return the alias as the key.
        # Since both fields have the same alias, they collide in the input dictionary.
        # Pydantic assigns the single value to both fields.
        # This proves we need populate_by_name=True to distinguish them.
        assert s.v1 == s.v2
        # One of them is definitely wrong (or both if overridden by something else, but here one wins)
        assert s.v1 != 'v1-val' or s.v2 != 'v2-val'
