from __future__ import annotations as _annotations  # important for BaseSettings import to work

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ...exceptions import SettingsError
from ..utils import InitState, parse_env_vars
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from types_boto3_secretsmanager.client import SecretsManagerClient
    from types_boto3_ssm.client import SSMClient

    from pydantic_settings.main import BaseSettings


boto3_client = None


def import_aws_secrets_manager() -> None:
    global boto3_client

    try:
        from boto3 import client as boto3_client
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'AWS Secrets Manager dependencies are not installed, run `pip install pydantic-settings[aws-secrets-manager]`'
        ) from e


def import_aws_systems_manager() -> None:
    global boto3_client

    try:
        from boto3 import client as boto3_client
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'AWS Systems Manager dependencies are not installed, run `pip install pydantic-settings[aws-systems-manager]`'
        ) from e


class AWSSecretsManagerSettingsSource(EnvSettingsSource):
    _secret_id: str
    _secretsmanager_client: SecretsManagerClient

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        secret_id: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        case_sensitive: bool | None = True,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = '--',
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
        version_id: str | None = None,
        _init_state: InitState | None = None,
    ) -> None:
        import_aws_secrets_manager()
        self._secretsmanager_client = boto3_client('secretsmanager', region_name=region_name, endpoint_url=endpoint_url)  # type: ignore
        self._secret_id = secret_id
        self._version_id = version_id
        super().__init__(
            settings_cls,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
            _init_state=_init_state,
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        request = {'SecretId': self._secret_id}

        if self._version_id:
            request['VersionId'] = self._version_id

        response = self._secretsmanager_client.get_secret_value(**request)

        return parse_env_vars(
            json.loads(response['SecretString']),
            self.case_sensitive,
            self.env_ignore_empty,
            self.env_parse_none_str,
        )

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(secret_id={self._secret_id!r}, '
            f'env_nested_delimiter={self.env_nested_delimiter!r})'
        )


class AWSSystemsManagerSettingsSource(EnvSettingsSource):
    _ssm_path: str
    _ssm_client: SSMClient

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        ssm_path: str = '/',
        region_name: str | None = None,
        endpoint_url: str | None = None,
        case_sensitive: bool | None = True,
        env_prefix: str | None = None,
        env_nested_delimiter: str | None = '/',
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
        _init_state: InitState | None = None,
    ) -> None:
        if not ssm_path.startswith('/'):
            raise SettingsError(f'AWS Systems Manager path must start with "/": {ssm_path!r}')

        import_aws_systems_manager()
        self._ssm_client = boto3_client('ssm', region_name=region_name, endpoint_url=endpoint_url)  # type: ignore
        self._ssm_path = ssm_path
        super().__init__(
            settings_cls,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
            _init_state=_init_state,
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        prefix = self._ssm_path.rstrip('/') + '/'

        paginator = self._ssm_client.get_paginator('get_parameters_by_path')
        page_iterator = paginator.paginate(Path=self._ssm_path, Recursive=True, WithDecryption=True)

        parameters: dict[str, str | None] = {}
        for page in page_iterator:
            for parameter in page['Parameters']:
                key = parameter['Name'].removeprefix(prefix)
                parameters[key] = parameter.get('Value')

        return parse_env_vars(
            parameters,
            self.case_sensitive,
            self.env_ignore_empty,
            self.env_parse_none_str,
        )

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(ssm_path={self._ssm_path!r}, env_nested_delimiter={self.env_nested_delimiter!r})'


__all__ = [
    'AWSSecretsManagerSettingsSource',
    'AWSSystemsManagerSettingsSource',
]
