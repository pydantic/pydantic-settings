import json
from collections.abc import Mapping
from typing import Optional

from pydantic_settings.main import BaseSettings

from .env import EnvSettingsSource

boto3_client = None
SecretsManagerClient = None


def import_aws_secrets_manager() -> None:
    global boto3_client
    global SecretsManagerClient

    try:
        from boto3 import client as boto3_client
        from mypy_boto3_secretsmanager.client import SecretsManagerClient
    except ImportError as e:
        raise ImportError(
            'AWS Secrets Manager dependencies are not installed, run `pip install pydantic-settings[aws-secrets-manager]`'
        ) from e


class AWSSecretsManagerSettingsSource(EnvSettingsSource):
    _secret_id: str
    _secretsmanager_client: SecretsManagerClient  # type: ignore

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        secret_id: str,
        env_prefix: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
    ) -> None:
        import_aws_secrets_manager()
        self._secretsmanager_client = boto3_client('secretsmanager')  # type: ignore
        self._secret_id = secret_id
        super().__init__(
            settings_cls,
            case_sensitive=True,
            env_prefix=env_prefix,
            env_nested_delimiter='--',
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

    def _load_env_vars(self) -> Mapping[str, Optional[str]]:
        response = self._secretsmanager_client.get_secret_value(SecretId=self._secret_id)  # type: ignore

        return json.loads(response['SecretString'])

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(secret_id={self._secret_id!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r})'
        )
