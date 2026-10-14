"""Azure Key Vault settings source."""

from __future__ import annotations as _annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, get_args, get_origin

from pydantic._internal._utils import is_model_class
from pydantic.alias_generators import to_snake
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic.fields import FieldInfo
from typing_inspection.introspection import is_union_origin

from ...utils import _lenient_issubclass
from ..utils import (
    InitState,
    _get_model_config,
    _get_model_fields,
    _parse_env_none_str,
    _resolve_type_alias,
    _strip_annotated,
)
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets import SecretClient

    from pydantic_settings.main import BaseSettings
else:
    TokenCredential = None
    ResourceNotFoundError = None
    SecretClient = None


def import_azure_key_vault() -> None:
    global TokenCredential
    global SecretClient
    global ResourceNotFoundError

    try:
        from azure.core.credentials import TokenCredential
        from azure.core.exceptions import ResourceNotFoundError
        from azure.keyvault.secrets import SecretClient
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'Azure Key Vault dependencies are not installed, run `pip install pydantic-settings[azure-key-vault]`'
        ) from e


def _collect_nested_types(annotation: Any, models: list[Any], dict_value_types: list[Any]) -> None:
    """Collect the models and dict value types that nested keys of `annotation` can belong to."""
    annotation = _strip_annotated(_resolve_type_alias(annotation))
    origin = get_origin(annotation)
    if is_union_origin(origin):
        for arg in get_args(annotation):
            _collect_nested_types(arg, models, dict_value_types)
    elif _lenient_issubclass(origin, dict):
        # A bare `typing.Dict` has no value type, so its keys are left as-is.
        if args := get_args(annotation):
            dict_value_types.append(args[-1])
    elif is_model_class(annotation) or is_pydantic_dataclass(annotation):
        models.append(annotation)


class AzureKeyVaultMapping(Mapping[str, str | None]):
    _loaded_secrets: dict[str, str | None]
    _secret_client: SecretClient
    _secret_names: list[str]

    def __init__(
        self,
        secret_client: SecretClient,
        case_sensitive: bool,
        snake_case_conversion: bool,
        env_prefix: str | None,
        env_parse_none_str: str | None = None,
    ) -> None:
        self._loaded_secrets = {}
        self._secret_client = secret_client
        self._case_sensitive = case_sensitive
        self._snake_case_conversion = snake_case_conversion
        self._env_prefix = env_prefix or ''
        self._env_parse_none_str = env_parse_none_str
        self._secret_map: dict[str, str] = self._load_remote()

    def _load_remote(self) -> dict[str, str]:
        secret_names: Iterator[str] = (
            secret.name for secret in self._secret_client.list_properties_of_secrets() if secret.name and secret.enabled
        )

        if self._snake_case_conversion:
            name_map: dict[str, str] = {}
            for name in secret_names:
                if name.startswith(self._env_prefix):
                    name_map[f'{self._env_prefix}{to_snake(name[len(self._env_prefix) :])}'] = name
                else:
                    name_map[to_snake(name)] = name
            return name_map

        if self._case_sensitive:
            return {name: name for name in secret_names}

        return {name.lower(): name for name in secret_names}

    def __getitem__(self, key: str) -> str | None:
        new_key = key

        if self._snake_case_conversion:
            if key.startswith(self._env_prefix):
                new_key = f'{self._env_prefix}{to_snake(key[len(self._env_prefix) :])}'
            else:
                new_key = to_snake(key)

        elif not self._case_sensitive:
            new_key = key.lower()

        if new_key not in self._loaded_secrets:
            if new_key in self._secret_map:
                self._loaded_secrets[new_key] = self._secret_client.get_secret(self._secret_map[new_key]).value
            else:
                raise KeyError(key)

        return _parse_env_none_str(self._loaded_secrets[new_key], self._env_parse_none_str)

    def __len__(self) -> int:
        return len(self._secret_map)

    def __iter__(self) -> Iterator[str]:
        return iter(self._secret_map.keys())


class AzureKeyVaultSettingsSource(EnvSettingsSource):
    _url: str
    _credential: TokenCredential

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        url: str,
        credential: TokenCredential,
        dash_to_underscore: bool = False,
        case_sensitive: bool | None = None,
        snake_case_conversion: bool = False,
        env_prefix: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
        _init_state: InitState | None = None,
    ) -> None:
        import_azure_key_vault()
        self._url = url
        self._credential = credential
        self._dash_to_underscore = dash_to_underscore
        self._snake_case_conversion = snake_case_conversion
        super().__init__(
            settings_cls,
            case_sensitive=True if snake_case_conversion else case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter='__' if snake_case_conversion else '--',
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
            _init_state=_init_state,
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        secret_client = SecretClient(vault_url=self._url, credential=self._credential)
        return AzureKeyVaultMapping(
            secret_client=secret_client,
            case_sensitive=self.case_sensitive,
            snake_case_conversion=self._snake_case_conversion,
            env_prefix=self.env_prefix,
            env_parse_none_str=self.env_parse_none_str,
        )

    def _extract_field_info(
        self, field: FieldInfo, field_name: str, model_config: Mapping[str, Any] | None = None
    ) -> list[tuple[str, str, bool]]:
        field_info = super()._extract_field_info(field, field_name, model_config)
        if self._dash_to_underscore and not self._snake_case_conversion:
            return [
                (field_key, env_name.replace('_', '-'), is_complex) for field_key, env_name, is_complex in field_info
            ]
        return field_info

    def explode_env_vars(self, field_name: str, field: FieldInfo, env_vars: Mapping[str, str | None]) -> dict[str, Any]:
        values = super().explode_env_vars(field_name, field, env_vars)
        if self._dash_to_underscore and not self._snake_case_conversion:
            self._translate_nested_keys(values, [field.annotation])
        return values

    def _translate_nested_keys(self, values: dict[str, Any], annotations: Iterable[Any]) -> None:
        """Rename the kebab-case keys of `values` to the keys of the nested model fields they belong to.

        The parent prefix has already been removed from the keys in `values`.
        """
        models: list[Any] = []
        dict_value_types: list[Any] = []
        for annotation in annotations:
            _collect_nested_types(annotation, models, dict_value_types)

        targets = self._nested_field_targets(models)
        field_keys = {field_key for field_targets in targets.values() for field_key, _ in field_targets}

        # Translate each nested dict once, against every field it may belong to.
        nested: dict[int, tuple[dict[str, Any], list[Any]]] = {}
        for env_name, field_targets in targets.items():
            if env_name not in values:
                continue
            value = values[env_name]
            for field_key, annotation in field_targets:
                values.setdefault(field_key, value)
                if isinstance(value, dict):
                    nested.setdefault(id(value), (value, []))[1].append(annotation)
            # Keep the dashed key when it is itself a field key, e.g. an alias of another union member.
            if env_name not in field_keys:
                del values[env_name]

        for value, field_annotations in nested.values():
            self._translate_nested_keys(value, field_annotations)

        if dict_value_types:
            for value in values.values():
                if isinstance(value, dict):
                    self._translate_nested_keys(value, dict_value_types)

    def _nested_field_targets(self, models: list[Any]) -> dict[str, list[tuple[str, Any]]]:
        """Map the dashed secret name segment of each field of `models` to its field keys and annotations.

        A dashed name may belong to several fields, e.g. the same field in two union members.
        """
        targets: dict[str, list[tuple[str, Any]]] = {}
        for model in models:
            config = _get_model_config(model)
            for field_name, field in _get_model_fields(model).items():
                for field_key, _, _ in self._extract_field_info(field, field_name, config):
                    env_name = self._apply_case_sensitive(field_key).replace('_', '-')
                    targets.setdefault(env_name, []).append((field_key, field.annotation))
        return targets

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(url={self._url!r}, env_nested_delimiter={self.env_nested_delimiter!r})'


__all__ = ['AzureKeyVaultMapping', 'AzureKeyVaultSettingsSource']
