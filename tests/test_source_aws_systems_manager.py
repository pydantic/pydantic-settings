"""
Test pydantic_settings.AWSSystemsManagerSettingsSource.
"""

import os

import pytest

try:
    from moto import mock_aws
except ImportError:
    mock_aws = None

from pydantic import BaseModel, Field

from pydantic_settings import (
    AWSSystemsManagerSettingsSource,
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsError,
)
from pydantic_settings.sources.providers.aws import import_aws_systems_manager

try:
    aws_systems_manager = True
    import_aws_systems_manager()
    import boto3

    os.environ['AWS_DEFAULT_REGION'] = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
except ImportError:
    aws_systems_manager = False


if not mock_aws:
    pytest.skip('moto is not installed', allow_module_level=True)


@pytest.mark.skipif(not aws_systems_manager, reason='pydantic-settings[aws-systems-manager] is not installed')
class TestAWSSystemsManagerSettingsSource:
    """Test AWSSystemsManagerSettingsSource."""

    @mock_aws
    def test_repr(self) -> None:
        source = AWSSystemsManagerSettingsSource(BaseSettings, '/test-path')
        assert repr(source) == "AWSSystemsManagerSettingsSource(ssm_path='/test-path', env_nested_delimiter='/')"

    @mock_aws
    def test___init__(self) -> None:
        """Test __init__."""

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

        AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/test-path')

    @mock_aws
    def test___call__(self) -> None:
        """Test __call__."""

        class SqlServer(BaseModel):
            password: str = Field(..., alias='Password')

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

            sql_server_user: str = Field(..., alias='SqlServerUser')
            sql_server: SqlServer = Field(..., alias='SqlServer')

        client = boto3.client('ssm')
        client.put_parameter(Name='/test-path/SqlServerUser', Value='test-user', Type='String')
        client.put_parameter(Name='/test-path/SqlServer/Password', Value='test-password', Type='SecureString')

        obj = AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/test-path')

        settings = obj()

        assert settings['SqlServerUser'] == 'test-user'
        assert settings['SqlServer']['Password'] == 'test-password'

    @mock_aws
    def test_systems_manager_case_insensitive(self) -> None:
        """Test systems manager getitem case insensitive."""

        class SqlServer(BaseModel):
            password: str = Field(..., alias='Password')

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

            sql_server_user: str
            sql_server: SqlServer

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (AWSSystemsManagerSettingsSource(settings_cls, '/test-path', case_sensitive=False),)

        client = boto3.client('ssm')
        client.put_parameter(Name='/test-path/SQL_SERVER_USER', Value='test-user', Type='String')
        client.put_parameter(Name='/test-path/SQL_SERVER/PASSWORD', Value='test-password', Type='SecureString')

        settings = AWSSystemsManagerSettings()  # type: ignore

        assert settings.sql_server_user == 'test-user'
        assert settings.sql_server.password == 'test-password'

    @mock_aws
    def test_aws_systems_manager_settings_source(self) -> None:
        """Test AWSSystemsManagerSettingsSource."""

        class SqlServer(BaseModel):
            password: str = Field(..., alias='Password')

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

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
                return (AWSSystemsManagerSettingsSource(settings_cls, '/test-path'),)

        client = boto3.client('ssm')
        client.put_parameter(Name='/test-path/SqlServerUser', Value='test-user', Type='String')
        client.put_parameter(Name='/test-path/SqlServer/Password', Value='test-password', Type='SecureString')

        settings = AWSSystemsManagerSettings()  # type: ignore

        assert settings.sql_server_user == 'test-user'
        assert settings.sql_server.password == 'test-password'

    @mock_aws
    def test_root_path(self) -> None:
        """Parameters are read relative to a root ``ssm_path``."""

        class AWSSystemsManagerSettings(BaseSettings):
            foo: str = Field(..., alias='foo')

        client = boto3.client('ssm')
        client.put_parameter(Name='/foo', Value='bar', Type='String')

        obj = AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/')

        settings = obj()

        assert settings['foo'] == 'bar'

    @mock_aws
    def test_trailing_slash_is_normalized(self) -> None:
        """``ssm_path`` with and without a trailing slash behave the same."""

        class AWSSystemsManagerSettings(BaseSettings):
            foo: str

        client = boto3.client('ssm')
        client.put_parameter(Name='/test-path/foo', Value='bar', Type='String')

        assert AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/test-path')() == {'foo': 'bar'}
        assert AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/test-path/')() == {'foo': 'bar'}

    @mock_aws
    def test_sibling_path_prefix_is_not_matched(self) -> None:
        """A path sharing a textual prefix with ``ssm_path`` is not picked up."""

        class AWSSystemsManagerSettings(BaseSettings):
            foo: str

        client = boto3.client('ssm')
        client.put_parameter(Name='/app/foo', Value='included', Type='String')
        client.put_parameter(Name='/app-other/bar', Value='excluded', Type='String')

        assert AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/app')() == {'foo': 'included'}

    @mock_aws
    def test_pagination(self) -> None:
        """All parameters are read, beyond a single ``get_parameters_by_path`` page."""

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

        client = boto3.client('ssm')
        for index in range(25):
            client.put_parameter(Name=f'/test-path/key{index:02d}', Value=str(index), Type='String')

        obj = AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, '/test-path')

        assert obj._load_env_vars() == {f'key{index:02d}': str(index) for index in range(25)}

    @pytest.mark.parametrize('ssm_path', ['', 'test-path'])
    def test_path_must_start_with_slash(self, ssm_path: str) -> None:
        """An ``ssm_path`` without a leading slash is rejected up front."""

        class AWSSystemsManagerSettings(BaseSettings):
            """AWSSystemsManager settings."""

        with pytest.raises(SettingsError, match='must start with "/"'):
            AWSSystemsManagerSettingsSource(AWSSystemsManagerSettings, ssm_path)
