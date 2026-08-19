"""
Test pydantic_settings.AWSSystemsManagerSettingsSource.
"""

import os

import pytest

try:
    import yaml
    from moto import mock_aws
except ImportError:
    yaml = None
    mock_aws = None

from pydantic import BaseModel, Field

from pydantic_settings import (
    AWSSystemsManagerSettingsSource,
    BaseSettings,
    PydanticBaseSettingsSource,
)
from pydantic_settings.sources.providers.aws import import_aws_systems_manager

try:
    aws_systems_manager = True
    import_aws_systems_manager()
    import boto3

    os.environ['AWS_DEFAULT_REGION'] = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
except ImportError:
    aws_systems_manager = False


MODULE = 'pydantic_settings.sources'

if not yaml:
    pytest.skip('PyYAML is not installed', allow_module_level=True)


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
